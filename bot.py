import sqlite3
import re
import os
from datetime import datetime, timedelta
import pandas as pd
import matplotlib.pyplot as plt
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# --- SOZLAMALAR ---
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
DB_NAME = "hisobchi_pro.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        type TEXT,
        amount REAL,
        category TEXT,
        date TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS user_categories (
        user_id INTEGER,
        category_name TEXT,
        UNIQUE(user_id, category_name))""")
    conn.commit()
    conn.close()

init_db()

# --- YORDAMCHI FUNKSIYALAR ---

def parse_text(text, user_id):
    text = text.lower()
    amount_match = re.findall(r'\d+', text.replace(',', '').replace(' ', ''))
    if not amount_match: return None
    amount = int(amount_match[0])

    if any(word in text for word in ["kirim", "oldim", "oylik", "+", "tushdi", "daromad"]):
        return ("Kirim", amount, "Daromad")

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT category_name FROM user_categories WHERE user_id=?", (user_id,))
    user_cats = [row[0].lower() for row in c.fetchall()]
    conn.close()

    for cat in user_cats:
        if cat in text: return ("Chiqim", amount, cat.capitalize())
    return ("Chiqim", amount, "Boshqa")

async def send_chart(update, df, title, filename, chart_type='line'):
    if df.empty:
        await update.message.reply_text("Ma'lumot topilmadi.")
        return

    plt.figure(figsize=(10, 6))
    if chart_type == 'line':
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        df['change'] = df.apply(lambda x: x['amount'] if x['type'] == 'Kirim' else -x['amount'], axis=1)
        df['balance'] = df['change'].cumsum()
        plt.plot(df['date'], df['balance'], marker='o', color='#007bff', linewidth=2)
        plt.fill_between(df['date'], df['balance'], color='#007bff', alpha=0.1)
        plt.gca().yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{int(x):,}'))
    elif chart_type == 'pie':
        cat_sum = df.groupby('category')['amount'].sum()
        cat_sum.plot(kind='pie', autopct='%1.1f%%', startangle=140, colors=plt.cm.Paired.colors)
        plt.ylabel('')

    plt.title(title)
    plt.tight_layout()
    plt.savefig(filename)
    plt.close()
    await update.message.reply_photo(photo=open(filename, "rb"), caption=f"📊 {title}")
    if os.path.exists(filename): os.remove(filename)

# --- BUYRUQ HANDLERLARI ---

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Markdown xatoligini oldini olish uchun \_ ishlatildi
    msg = r"""(
        "📜 **Asosiy buyruqlar:**\n\n"
        "/hisobot — Umumiy qoldiq\n"
        "/kunlik — 10 kunlik balans grafigi\n"
        "/haftalik — 4 haftalik tahlil\n"
        "/oylik — 1 yillik tarix\n"
        "/pie — Xarajatlar kategoriyasi (diagramma)\n"
        "/categories — Kategoriya ro'yxati\n"
        "/add\_cat [nomi] — Yangi kategoriya qo'shish\n\n"
        "💡 *Masalan:* 'taksi 20000' yoki 'oylik oldim 5000000'"
    )"""
    await update.message.reply_text(msg, parse_mode="Markdown")

async def hisobot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT type, amount FROM transactions WHERE user_id=?", conn, params=(user_id,))
    conn.close()
    if df.empty:
        await update.message.reply_text("Hozircha hech qanday ma'lumot yo'q.")
        return
    k = df[df['type']=='Kirim']['amount'].sum()
    ch = df[df['type']=='Chiqim']['amount'].sum()
    await update.message.reply_text(
        f"💰 **Kirim:** {k:,} so'm\n"
        f"💸 **Chiqim:** {ch:,} so'm\n"
        f"🧾 **Qoldiq:** {k-ch:,} so'm",
        parse_mode="Markdown"
    )

async def kunlik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    conn = sqlite3.connect(DB_NAME)
    limit = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d')
    df = pd.read_sql_query("SELECT date, type, amount FROM transactions WHERE user_id=? AND date >= ?", conn, params=(user_id, limit))
    conn.close()
    await send_chart(update, df, "10 Kunlik Balans", "daily.png")

async def haftalik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    conn = sqlite3.connect(DB_NAME)
    limit = (datetime.now() - timedelta(days=28)).strftime('%Y-%m-%d')
    df = pd.read_sql_query("SELECT date, type, amount FROM transactions WHERE user_id=? AND date >= ?", conn, params=(user_id, limit))
    conn.close()
    await send_chart(update, df, "4 Haftalik Dinamika", "weekly.png")

async def oylik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    conn = sqlite3.connect(DB_NAME)
    limit = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
    df = pd.read_sql_query("SELECT date, type, amount FROM transactions WHERE user_id=? AND date >= ?", conn, params=(user_id, limit))
    conn.close()
    await send_chart(update, df, "1 Yillik Tahlil", "monthly.png")

async def pie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT category, amount FROM transactions WHERE user_id=? AND type='Chiqim'", conn, params=(user_id,))
    conn.close()
    await send_chart(update, df, "Xarajatlar Taqsimoti", "pie.png", chart_type='pie')

async def list_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT category_name FROM user_categories WHERE user_id=?", (user_id,))
    cats = [r[0] for r in c.fetchall()]
    conn.close()
    res = "📁 **Kategoriyalaringiz:**\n\n" + ("\n".join([f"• {c}" for c in cats]) if cats else "Hali kategoriya qo'shilmagan.")
    await update.message.reply_text(res, parse_mode="Markdown")

async def add_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Nomini yozing. Masalan: `/add_cat Bozor`", parse_mode="Markdown")
        return
    cat = context.args[0].capitalize()
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO user_categories VALUES (?, ?)", (update.message.from_user.id, cat))
        conn.commit()
        await update.message.reply_text(f"✅ '{cat}' ro'yxatga qo'shildi.")
    except:
        await update.message.reply_text("Bu kategoriya allaqachon bor.")
    finally:
        conn.close()

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    res = parse_text(update.message.text, user_id)
    if res:
        t, a, cat = res
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("INSERT INTO transactions (user_id, type, amount, category, date) VALUES (?, ?, ?, ?, ?)",
                  (user_id, t, a, cat, now))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ Saqlandi: **{t}** {a:,} so'm\n📂 Kategoriya: **{cat}**", parse_mode="Markdown")

# --- ASOSIY QISM ---

if __name__ == "__main__":
    if not TOKEN:
        print("❌ BOT_TOKEN topilmadi! .env faylini tekshiring.")
    else:
        app = ApplicationBuilder().token(TOKEN).build()

        # Barcha handlerlarni ro'yxatdan o'tkazish
        app.add_handler(CommandHandler("start", help_command))
        app.add_handler(CommandHandler("help", help_command))
        app.add_handler(CommandHandler("hisobot", hisobot))
        app.add_handler(CommandHandler("kunlik", kunlik))
        app.add_handler(CommandHandler("haftalik", haftalik))
        app.add_handler(CommandHandler("oylik", oylik))
        app.add_handler(CommandHandler("pie", pie))
        app.add_handler(CommandHandler("categories", list_categories))
        app.add_handler(CommandHandler("add_cat", add_cat))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        print("🚀 Bot muvaffaqiyatli ishga tushdi...")
        app.run_polling(drop_pending_updates=True)






# import sqlite3
# import re
# import os
# from datetime import datetime, timedelta
# import pandas as pd
# import matplotlib.pyplot as plt
# from dotenv import load_dotenv
# from telegram import Update
# from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# # --- SOZLAMALAR ---
# load_dotenv()
# TOKEN = os.getenv("BOT_TOKEN")
# DB_NAME = "hisobchi_pro.db"

# def init_db():
#     conn = sqlite3.connect(DB_NAME)
#     c = conn.cursor()
#     c.execute("""CREATE TABLE IF NOT EXISTS transactions (
#         id INTEGER PRIMARY KEY AUTOINCREMENT, 
#         user_id INTEGER, 
#         type TEXT, 
#         amount REAL, 
#         category TEXT, 
#         date TEXT)""")
#     c.execute("""CREATE TABLE IF NOT EXISTS user_categories (
#         user_id INTEGER, 
#         category_name TEXT, 
#         UNIQUE(user_id, category_name))""")
#     conn.commit()
#     conn.close()

# init_db()

# # --- FUNKSIYALAR ---

# def parse_text(text, user_id):
#     text = text.lower()
#     amount_match = re.findall(r'\d+', text.replace(',', '').replace(' ', ''))
#     if not amount_match: return None
#     amount = int(amount_match[0])
    
#     if any(word in text for word in ["kirim", "oldim", "oylik", "+", "tushdi", "daromad"]):
#         return ("Kirim", amount, "Daromad")
    
#     conn = sqlite3.connect(DB_NAME)
#     c = conn.cursor()
#     c.execute("SELECT category_name FROM user_categories WHERE user_id=?", (user_id,))
#     user_cats = [row[0].lower() for row in c.fetchall()]
#     conn.close()

#     for cat in user_cats:
#         if cat in text: return ("Chiqim", amount, cat.capitalize())
#     return ("Chiqim", amount, "Boshqa")

# async def send_chart(update, df, title, filename, chart_type='line'):
#     if df.empty:
#         await update.message.reply_text("Ma'lumot topilmadi.")
#         return

#     plt.figure(figsize=(10, 6))
#     if chart_type == 'line':
#         df['date'] = pd.to_datetime(df['date'])
#         df = df.sort_values('date')
#         df['change'] = df.apply(lambda x: x['amount'] if x['type'] == 'Kirim' else -x['amount'], axis=1)
#         df['balance'] = df['change'].cumsum()
#         plt.plot(df['date'], df['balance'], marker='o', color='#007bff', linewidth=2)
#         plt.fill_between(df['date'], df['balance'], color='#007bff', alpha=0.1)
#         plt.gca().yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{int(x):,}'))
#     elif chart_type == 'pie':
#         cat_sum = df.groupby('category')['amount'].sum()
#         cat_sum.plot(kind='pie', autopct='%1.1f%%', startangle=140, colors=plt.cm.Paired.colors)
#         plt.ylabel('')

#     plt.title(title)
#     plt.tight_layout()
#     plt.savefig(filename)
#     plt.close()
#     await update.message.reply_photo(photo=open(filename, "rb"), caption=f"📊 {title}")
#     if os.path.exists(filename): os.remove(filename)

# # --- BUYRUQLAR ---

# async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     msg = (
#         "📜 **Buyruqlar:**\n"
#         "/hisobot — Umumiy balans\n"
#         "/kunlik — 10 kunlik grafik\n"
#         "/haftalik — 4 haftalik dinamika\n"
#         "/oylik — 1 yillik tahlil\n"
#         "/pie — Kategoriyalar taqsimoti\n"
#         "/categories — Kategoriyalar ro'yxati\n"
#         "/add\_cat [nomi] — Yangi kategoriya qo'shish"
#     )
#     # Markdown xatoligi bermasligi uchun qochirildi
#     await update.message.reply_text(msg, parse_mode="Markdown")

# async def hisobot(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     user_id = update.message.from_user.id
#     conn = sqlite3.connect(DB_NAME)
#     df = pd.read_sql_query("SELECT type, amount FROM transactions WHERE user_id=?", conn, params=(user_id,))
#     conn.close()
#     if df.empty:
#         await update.message.reply_text("Ma'lumot yo'q.")
#         return
#     k = df[df['type']=='Kirim']['amount'].sum()
#     ch = df[df['type']=='Chiqim']['amount'].sum()
#     await update.message.reply_text(f"💰 **Kirim:** {k:,} so'm\n💸 **Chiqim:** {ch:,} so'm\n🧾 **Qoldiq:** {k-ch:,} so'm", parse_mode="Markdown")

# async def kunlik(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     user_id = update.message.from_user.id
#     conn = sqlite3.connect(DB_NAME)
#     limit = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d')
#     df = pd.read_sql_query("SELECT date, type, amount FROM transactions WHERE user_id=? AND date >= ?", conn, params=(user_id, limit))
#     conn.close()
#     await send_chart(update, df, "10 Kunlik Balans", "daily.png")

# async def haftalik(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     user_id = update.message.from_user.id
#     conn = sqlite3.connect(DB_NAME)
#     limit = (datetime.now() - timedelta(days=28)).strftime('%Y-%m-%d')
#     df = pd.read_sql_query("SELECT date, type, amount FROM transactions WHERE user_id=? AND date >= ?", conn, params=(user_id, limit))
#     conn.close()
#     await send_chart(update, df, "4 Haftalik Dinamika", "weekly.png")

# async def oylik(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     user_id = update.message.from_user.id
#     conn = sqlite3.connect(DB_NAME)
#     limit = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
#     df = pd.read_sql_query("SELECT date, type, amount FROM transactions WHERE user_id=? AND date >= ?", conn, params=(user_id, limit))
#     conn.close()
#     await send_chart(update, df, "1 Yillik Tahlil", "monthly.png")

# async def pie(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     user_id = update.message.from_user.id
#     conn = sqlite3.connect(DB_NAME)
#     df = pd.read_sql_query("SELECT category, amount FROM transactions WHERE user_id=? AND type='Chiqim'", conn, params=(user_id,))
#     conn.close()
#     await send_chart(update, df, "Xarajatlar Taqsimoti", "pie.png", chart_type='pie')

# async def list_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     user_id = update.message.from_user.id
#     conn = sqlite3.connect(DB_NAME)
#     c = conn.cursor()
#     c.execute("SELECT category_name FROM user_categories WHERE user_id=?", (user_id,))
#     cats = [r[0] for r in c.fetchall()]
#     conn.close()
#     res = "📁 **Sizning kategoriyalaringiz:**\n\n" + ("\n".join([f"• {c}" for c in cats]) if cats else "Hali kategoriya qo'shilmagan.")
#     await update.message.reply_text(res, parse_mode="Markdown")

# async def add_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     if not context.args:
#         await update.message.reply_text("Kategoriya nomini yozing. Masalan: `/add_cat Taksi`", parse_mode="Markdown")
#         return
#     cat = context.args[0].capitalize()
#     conn = sqlite3.connect(DB_NAME)
#     c = conn.cursor()
#     try:
#         c.execute("INSERT INTO user_categories VALUES (?, ?)", (update.message.from_user.id, cat))
#         conn.commit()
#         await update.message.reply_text(f"✅ '{cat}' kategoriyasi qo'shildi.")
#     except:
#         await update.message.reply_text("Bu kategoriya allaqachon mavjud.")
#     finally:
#         conn.close()

# async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     user_id = update.message.from_user.id
#     res = parse_text(update.message.text, user_id)
#     if res:
#         t, a, cat = res
#         now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
#         conn = sqlite3.connect(DB_NAME)
#         c = conn.cursor()
#         c.execute("INSERT INTO transactions (user_id, type, amount, category, date) VALUES (?, ?, ?, ?, ?)", 
#                   (user_id, t, a, cat, now))
#         conn.commit()
#         conn.close()
#         await update.message.reply_text(f"✅ Saqlandi: **{t}** {a:,} so'm\n📂 Kategoriya: **{cat}**", parse_mode="Markdown")

# if __name__ == "__main__":
#     app = ApplicationBuilder().token(TOKEN).build()
    
#     # Handlerlarni ro'yxatdan o'tkazish
#     app.add_handler(CommandHandler("start", help_command))
#     app.add_handler(CommandHandler("help", help_command))
#     app.add_handler(CommandHandler("hisobot", hisobot))
#     app.add_handler(CommandHandler("kunlik", kunlik))
#     app.add_handler(CommandHandler("haftalik", haftalik))
#     app.add_handler(CommandHandler("oylik", oylik))
#     app.add_handler(CommandHandler("pie", pie))
#     app.add_handler(CommandHandler("categories", list_categories))
#     app.add_handler(CommandHandler("add_cat", add_cat))
#     app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
#     print("🚀 SQLite Bot ishga tushdi...")
#     app.run_polling(drop_pending_updates=True)




# import sqlite3
# import re
# import os
# from datetime import datetime, timedelta
# import pandas as pd
# import matplotlib.pyplot as plt
# from dotenv import load_dotenv
# from telegram import Update
# from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# # --- SOZLAMALAR ---
# load_dotenv()
# TOKEN = os.getenv("BOT_TOKEN")

# # SQLite ulanishi
# DB_NAME = "hisobchi_pro.db"

# def init_db():
#     conn = sqlite3.connect(DB_NAME)
#     c = conn.cursor()
#     c.execute("""CREATE TABLE IF NOT EXISTS transactions (
#         id INTEGER PRIMARY KEY AUTOINCREMENT, 
#         user_id INTEGER, 
#         type TEXT, 
#         amount REAL, 
#         category TEXT, 
#         date TEXT)""")
#     c.execute("""CREATE TABLE IF NOT EXISTS user_categories (
#         user_id INTEGER, 
#         category_name TEXT, 
#         UNIQUE(user_id, category_name))""")
#     conn.commit()
#     conn.close()

# init_db()

# # --- FUNKSIYALAR ---

# def parse_text(text, user_id):
#     text = text.lower()
#     amount_match = re.findall(r'\d+', text.replace(',', '').replace(' ', ''))
#     if not amount_match: return None
#     amount = int(amount_match[0])
    
#     if any(word in text for word in ["kirim", "oldim", "oylik", "+", "tushdi", "daromad"]):
#         return ("Kirim", amount, "Daromad")
    
#     conn = sqlite3.connect(DB_NAME)
#     c = conn.cursor()
#     c.execute("SELECT category_name FROM user_categories WHERE user_id=?", (user_id,))
#     user_cats = [row[0].lower() for row in c.fetchall()]
#     conn.close()

#     for cat in user_cats:
#         if cat in text: return ("Chiqim", amount, cat.capitalize())
#     return ("Chiqim", amount, "Boshqa")

# async def send_chart(update, df, title, filename, chart_type='line'):
#     if df.empty:
#         await update.message.reply_text("Ma'lumot topilmadi.")
#         return

#     plt.figure(figsize=(10, 6))
#     if chart_type == 'line':
#         df['date'] = pd.to_datetime(df['date'])
#         df = df.sort_values('date')
#         df['change'] = df.apply(lambda x: x['amount'] if x['type'] == 'Kirim' else -x['amount'], axis=1)
#         df['balance'] = df['change'].cumsum()
#         plt.plot(df['date'], df['balance'], marker='o', color='#007bff', linewidth=2)
#         plt.fill_between(df['date'], df['balance'], color='#007bff', alpha=0.1)
#         plt.gca().yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{int(x):,}'))
#     elif chart_type == 'pie':
#         cat_sum = df.groupby('category')['amount'].sum()
#         cat_sum.plot(kind='pie', autopct='%1.1f%%', startangle=140, colors=plt.cm.Paired.colors)
#         plt.ylabel('')

#     plt.title(title)
#     plt.tight_layout()
#     plt.savefig(filename)
#     plt.close()
#     await update.message.reply_photo(photo=open(filename, "rb"), caption=f"📊 {title}")
#     if os.path.exists(filename): os.remove(filename)

# # --- BUYRUQLAR ---

# async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     msg = (
#         "📜 **Buyruqlar:**\n"
#         "/hisobot - Balans\n"
#         "/kunlik - 10 kunlik grafik\n"
#         "/haftalik - 4 haftalik grafik\n"
#         "/oylik - 1 yillik tahlil\n"
#         "/pie - Kategoriyalar taqsimoti\n"
#         "/categories - Kategoriyalar\n"
#         "/add_cat [nomi] - Yangi kategoriya"
#     )
#     await update.message.reply_text(msg, parse_mode="Markdown")

# async def hisobot(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     user_id = update.message.from_user.id
#     conn = sqlite3.connect(DB_NAME)
#     df = pd.read_sql_query("SELECT type, amount FROM transactions WHERE user_id=?", conn, params=(user_id,))
#     conn.close()
#     if df.empty:
#         await update.message.reply_text("Ma'lumot yo'q.")
#         return
#     k = df[df['type']=='Kirim']['amount'].sum()
#     ch = df[df['type']=='Chiqim']['amount'].sum()
#     await update.message.reply_text(f"💰 Kirim: {k:,}\n💸 Chiqim: {ch:,}\n🧾 Qoldiq: {k-ch:,}")

# async def kunlik(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     user_id = update.message.from_user.id
#     conn = sqlite3.connect(DB_NAME)
#     # Oxirgi 10 kunni hisoblash
#     date_limit = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d')
#     df = pd.read_sql_query("SELECT date, type, amount FROM transactions WHERE user_id=? AND date >= ?", conn, params=(user_id, date_limit))
#     conn.close()
#     await send_chart(update, df, "10 Kunlik Dinamika", "daily.png")

# async def pie(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     user_id = update.message.from_user.id
#     conn = sqlite3.connect(DB_NAME)
#     df = pd.read_sql_query("SELECT category, amount FROM transactions WHERE user_id=? AND type='Chiqim'", conn, params=(user_id,))
#     conn.close()
#     await send_chart(update, df, "Xarajatlar Taqsimoti", "pie.png", chart_type='pie')

# async def add_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     if not context.args:
#         await update.message.reply_text("Kategoriya nomini yozing. Masalan: /add_cat Taksi")
#         return
#     cat = context.args[0]
#     conn = sqlite3.connect(DB_NAME)
#     c = conn.cursor()
#     try:
#         c.execute("INSERT INTO user_categories VALUES (?, ?)", (update.message.from_user.id, cat))
#         conn.commit()
#         await update.message.reply_text(f"✅ '{cat}' kategoriyasi qo'shildi.")
#     except:
#         await update.message.reply_text("Bu kategoriya allaqachon mavjud.")
#     finally:
#         conn.close()

# async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     user_id = update.message.from_user.id
#     res = parse_text(update.message.text, user_id)
#     if res:
#         t, a, cat = res
#         now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
#         conn = sqlite3.connect(DB_NAME)
#         c = conn.cursor()
#         c.execute("INSERT INTO transactions (user_id, type, amount, category, date) VALUES (?, ?, ?, ?, ?)", 
#                   (user_id, t, a, cat, now))
#         conn.commit()
#         conn.close()
#         await update.message.reply_text(f"✅ Saqlandi: {t} {a:,} so'm ({cat})")

# if __name__ == "__main__":
#     app = ApplicationBuilder().token(TOKEN).build()
#     app.add_handler(CommandHandler("start", help_command))
#     app.add_handler(CommandHandler("help", help_command))
#     app.add_handler(CommandHandler("hisobot", hisobot))
#     app.add_handler(CommandHandler("kunlik", kunlik))
#     app.add_handler(CommandHandler("pie", pie))
#     app.add_handler(CommandHandler("add_cat", add_cat))
#     app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
#     print("🚀 SQLite Bot ishga tushdi...")
#     app.run_polling()

# # import os
# # import re
# # import psycopg2
# # import pandas as pd
# # import matplotlib.pyplot as plt
# # from datetime import datetime, timedelta
# # from dotenv import load_dotenv
# # from telegram import Update
# # from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
# # #uzgarish
# # # --- SOZLAMALAR ---
# # load_dotenv()
# # TOKEN = os.getenv("BOT_TOKEN")
# # DATABASE_URL = os.getenv("postgresql://admin:ke4sEaDybygg1l1gRcbDiVsU3ctKCeAu@dpg-d7o7tk9kh4rs73bkd8v0-a.oregon-postgres.render.com/hisobchi_db")

# # def get_db_connection():
# #     if not DATABASE_URL:
# #         raise ValueError("DATABASE_URL topilmadi!")
# #     if 'localhost' in DATABASE_URL or '127.0.0.1' in DATABASE_URL:
# #         return psycopg2.connect(DATABASE_URL)
# #     return psycopg2.connect(DATABASE_URL, sslmode='require')

# # def init_db():
# #     conn = get_db_connection()
# #     c = conn.cursor()
# #     c.execute("""CREATE TABLE IF NOT EXISTS transactions (
# #         id SERIAL PRIMARY KEY, 
# #         user_id BIGINT, 
# #         type TEXT, 
# #         amount REAL, 
# #         category TEXT, 
# #         date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
# #     c.execute("""CREATE TABLE IF NOT EXISTS user_categories (
# #         user_id BIGINT, 
# #         category_name TEXT, 
# #         UNIQUE(user_id, category_name))""")
# #     conn.commit()
# #     c.close()
# #     conn.close()

# # init_db()

# # # --- FUNKSIYALAR ---

# # def parse_text(text, user_id):
# #     text = text.lower()
# #     amount_match = re.findall(r'\d+', text.replace(',', '').replace(' ', ''))
# #     if not amount_match: return None
# #     amount = int(amount_match[0])
    
# #     if any(word in text for word in ["kirim", "oldim", "oylik", "+", "tushdi", "daromad"]):
# #         return ("Kirim", amount, "Daromad")
    
# #     conn = get_db_connection()
# #     c = conn.cursor()
# #     c.execute("SELECT category_name FROM user_categories WHERE user_id=%s", (user_id,))
# #     user_cats = [row[0].lower() for row in c.fetchall()]
# #     c.close()
# #     conn.close()

# #     for cat in user_cats:
# #         if cat in text: return ("Chiqim", amount, cat.capitalize())
# #     return ("Chiqim", amount, "Boshqa")

# # async def send_chart(update, df, title, filename, chart_type='line'):
# #     if df.empty:
# #         await update.message.reply_text("Ma'lumot topilmadi.")
# #         return

# #     plt.figure(figsize=(10, 6))
# #     if chart_type == 'line':
# #         df['date'] = pd.to_datetime(df['date'])
# #         df = df.sort_values('date')
# #         df['balance'] = df.apply(lambda x: x['amount'] if x['type'] == 'Kirim' else -x['amount'], axis=1).cumsum()
# #         plt.plot(df['date'], df['balance'], marker='o', color='#007bff', linewidth=2)
# #         plt.fill_between(df['date'], df['balance'], color='#007bff', alpha=0.1)
# #         plt.gca().yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{int(x):,}'))
# #     elif chart_type == 'pie':
# #         cat_sum = df.groupby('category')['amount'].sum()
# #         cat_sum.plot(kind='pie', autopct='%1.1f%%', startangle=140, colors=plt.cm.Paired.colors)
# #         plt.ylabel('')

# #     plt.title(title)
# #     plt.tight_layout()
# #     plt.savefig(filename)
# #     plt.close()
# #     await update.message.reply_photo(photo=open(filename, "rb"), caption=f"📊 {title}")
# #     if os.path.exists(filename): os.remove(filename)

# # # --- BUYRUQ HANDLERLARI ---

# # async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     await update.message.reply_text("🤖 Xush kelibsiz! Harajat yoki kirimni yozing.\nBuyruqlar ro'yxati: /help")

# # async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     msg = (
# #         "📜 **Buyruqlar:**\n"
# #         "/hisobot - Balans\n"
# #         "/kunlik - 10 kunlik grafik\n"
# #         "/haftalik - 4 haftalik grafik\n"
# #         "/oylik - 1 yillik tahlil\n"
# #         "/pie - Kategoriyalar taqsimoti\n"
# #         "/categories - Kategoriyalar\n"
# #         "/add_cat [nomi] - Yangi kategoriya"
# #     )
# #     await update.message.reply_text(msg, parse_mode="Markdown")

# # async def hisobot(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     user_id = update.message.from_user.id
# #     conn = get_db_connection()
# #     df = pd.read_sql_query("SELECT type, amount FROM transactions WHERE user_id=%s", conn, params=(user_id,))
# #     conn.close()
# #     if df.empty:
# #         await update.message.reply_text("Hali ma'lumot yo'q.")
# #         return
# #     k = df[df['type']=='Kirim']['amount'].sum()
# #     ch = df[df['type']=='Chiqim']['amount'].sum()
# #     await update.message.reply_text(f"💰 Kirim: {k:,}\n💸 Chiqim: {ch:,}\n🧾 Qoldiq: {k-ch:,}")

# # async def kunlik(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     user_id = update.message.from_user.id
# #     conn = get_db_connection()
# #     df = pd.read_sql_query("SELECT date, type, amount FROM transactions WHERE user_id=%s AND date > NOW() - INTERVAL '10 days'", conn, params=(user_id,))
# #     conn.close()
# #     await send_chart(update, df, "10 Kunlik Dinamika", "daily.png")

# # async def haftalik(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     user_id = update.message.from_user.id
# #     conn = get_db_connection()
# #     df = pd.read_sql_query("SELECT date, type, amount FROM transactions WHERE user_id=%s AND date > NOW() - INTERVAL '30 days'", conn, params=(user_id,))
# #     conn.close()
# #     await send_chart(update, df, "Haftalik Dinamika", "weekly.png")

# # async def oylik(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     user_id = update.message.from_user.id
# #     conn = get_db_connection()
# #     df = pd.read_sql_query("SELECT date, type, amount FROM transactions WHERE user_id=%s AND date > NOW() - INTERVAL '1 year'", conn, params=(user_id,))
# #     conn.close()
# #     await send_chart(update, df, "Yillik Tahlil", "monthly.png")

# # async def pie(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     user_id = update.message.from_user.id
# #     conn = get_db_connection()
# #     df = pd.read_sql_query("SELECT category, amount FROM transactions WHERE user_id=%s AND type='Chiqim'", conn, params=(user_id,))
# #     conn.close()
# #     await send_chart(update, df, "Xarajatlar Taqsimoti", "pie.png", chart_type='pie')

# # async def list_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     user_id = update.message.from_user.id
# #     conn = get_db_connection()
# #     c = conn.cursor()
# #     c.execute("SELECT category_name FROM user_categories WHERE user_id=%s", (user_id,))
# #     cats = [r[0] for r in c.fetchall()]
# #     conn.close()
# #     await update.message.reply_text("📁 Kategoriyalaringiz:\n" + ("\n".join(cats) if cats else "Hali yo'q."))

# # async def add_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     if not context.args: return
# #     cat = context.args[0]
# #     conn = get_db_connection()
# #     c = conn.cursor()
# #     try:
# #         c.execute("INSERT INTO user_categories VALUES (%s, %s)", (update.message.from_user.id, cat))
# #         conn.commit()
# #         await update.message.reply_text(f"✅ '{cat}' qo'shildi.")
# #     except: await update.message.reply_text("Bu kategoriya allaqachon bor.")
# #     finally: conn.close()

# # async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     user_id = update.message.from_user.id
# #     res = parse_text(update.message.text, user_id)
# #     if res:
# #         t, a, cat = res
# #         conn = get_db_connection()
# #         c = conn.cursor()
# #         c.execute("INSERT INTO transactions (user_id, type, amount, category) VALUES (%s, %s, %s, %s)", (user_id, t, a, cat))
# #         conn.commit()
# #         conn.close()
# #         await update.message.reply_text(f"✅ Saqlandi: {t} {a:,} so'm ({cat})")

# # if __name__ == "__main__":
# #     app = ApplicationBuilder().token(TOKEN).build()
# #     app.add_handler(CommandHandler("start", start))
# #     app.add_handler(CommandHandler("help", help_command))
# #     app.add_handler(CommandHandler("hisobot", hisobot))
# #     app.add_handler(CommandHandler("kunlik", kunlik))
# #     app.add_handler(CommandHandler("haftalik", haftalik))
# #     app.add_handler(CommandHandler("oylik", oylik))
# #     app.add_handler(CommandHandler("pie", pie))
# #     app.add_handler(CommandHandler("categories", list_categories))
# #     app.add_handler(CommandHandler("add_cat", add_cat))
# #     app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
# #     app.run_polling()

# # import sqlite3
# # import re
# # import os
# # from datetime import datetime, timedelta
# # import pandas as pd
# # import matplotlib.pyplot as plt
# # from dotenv import load_dotenv
# # from telegram import Update
# # from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# # # --- SOZLAMALAR ---
# # load_dotenv()
# # TOKEN = os.getenv("BOT_TOKEN")
# # conn = sqlite3.connect("hisobchi_pro.db", check_same_thread=False)
# # c = conn.cursor()

# # def init_db():
# #     c.execute("""CREATE TABLE IF NOT EXISTS transactions (
# #         id INTEGER PRIMARY KEY AUTOINCREMENT, 
# #         user_id INTEGER, 
# #         type TEXT, 
# #         amount REAL, 
# #         category TEXT, 
# #         date TEXT)""")
# #     c.execute("""CREATE TABLE IF NOT EXISTS user_categories (
# #         user_id INTEGER, 
# #         category_name TEXT, 
# #         UNIQUE(user_id, category_name))""")
# #     conn.commit()

# # init_db()

# # # --- AI PARSER ---
# # def parse_text(text, user_id):
# #     text = text.lower()
# #     amount_match = re.findall(r'\d+', text.replace(',', '').replace(' ', ''))
# #     if not amount_match: return None
# #     amount = int(amount_match[0])
    
# #     # Kirim kalit so'zlari
# #     if any(word in text for word in ["kirim", "oldim", "oylik", "+", "tushdi", "daromad"]):
# #         return ("Kirim", amount, "Daromad")
    
# #     # Kategoriya bo'yicha chiqim
# #     c.execute("SELECT category_name FROM user_categories WHERE user_id=?", (user_id,))
# #     user_cats = [row[0].lower() for row in c.fetchall()]
# #     for cat in user_cats:
# #         if cat in text: return ("Chiqim", amount, cat.capitalize())
    
# #     return ("Chiqim", amount, "Boshqa")

# # # --- GRAFIK CHIZISH (BALANS DINAMIKASI) ---

# # async def send_balance_chart(update, df, title, filename):
# #     if df.empty:
# #         await update.message.reply_text("Ma'lumot topilmadi.")
# #         return

# #     # Sanani tartiblash
# #     df['date'] = pd.to_datetime(df['date'], format='mixed')
# #     df = df.sort_values('date')

# #     # Kirim/Chiqimni hisobga olgan holda o'zgarishni hisoblash
# #     df['change'] = df.apply(lambda x: x['amount'] if x['type'] == 'Kirim' else -x['amount'], axis=1)
    
# #     # Kumulyativ balans (Har bir nuqtadagi umumiy qoldiq)
# #     df['balance'] = df['change'].cumsum()

# #     plt.figure(figsize=(12, 6))
    
# #     # Grafik chizish
# #     plt.plot(df['date'], df['balance'], marker='o', linestyle='-', color='#007bff', linewidth=3, markersize=8, label='Balans qoldig\'i')
    
# #     # Grafik ostini bo'yash
# #     plt.fill_between(df['date'], df['balance'], color='#007bff', alpha=0.1)

# #     # Chap tomonda (Y o'qi) pullarni formatlash
# #     plt.gca().yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{int(x):,}'))
    
# #     plt.title(title, fontsize=16, fontweight='bold')
# #     plt.xlabel("Sana", fontsize=12)
# #     plt.ylabel("Umumiy summa (so'm)", fontsize=12)
# #     plt.grid(True, linestyle='--', alpha=0.7)
# #     plt.xticks(rotation=45)
    
# #     # Har bir nuqtaga qiymatni yozib chiqish (ixtiyoriy)
# #     for i, txt in enumerate(df['balance']):
# #         plt.annotate(f'{int(txt):,}', (df['date'].iloc[i], df['balance'].iloc[i]), 
# #                      textcoords="offset points", xytext=(0,10), ha='center', fontsize=9)

# #     plt.tight_layout()
# #     plt.savefig(filename, dpi=150)
# #     plt.close()
    
# #     await update.message.reply_photo(photo=open(filename, "rb"), caption=f"💰 {title}")
# #     if os.path.exists(filename): os.remove(filename)

# # # --- BUYRUQLAR ---

# # async def kunlik(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     user_id = update.message.from_user.id
# #     # Oxirgi 15 ta tranzaksiyani olish (dinamikani ko'rish uchun)
# #     df = pd.read_sql_query("SELECT date, type, amount FROM transactions WHERE user_id=? ORDER BY date ASC", conn, params=(user_id,))
# #     await send_balance_chart(update, df, "Balans O'zgarishi Grafigi", "balance.png")

# # async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     res = parse_text(update.message.text, update.message.from_user.id)
# #     if res:
# #         t, a, cat = res
# #         now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
# #         c.execute("INSERT INTO transactions (user_id, type, amount, category, date) VALUES (?,?,?,?,?)", 
# #                   (update.message.from_user.id, t, a, cat, now))
# #         conn.commit()
# #         await update.message.reply_text(f"✅ Saqlandi: {t} {a:,} so'm")
# #     else:
# #         await update.message.reply_text("Tushunmadim. Masalan: 'Oylik oldim 5,000,000'")

# # async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     await update.message.reply_text("🤖 **Xush kelibsiz!**\nKirim va chiqimlarni yozing, men esa sizga balans grafigini chizib beraman.\n\nBuyruq: /kunlik")

# # if __name__ == "__main__":
# #     app = ApplicationBuilder().token(TOKEN).build()
# #     app.add_handler(CommandHandler("start", start))
# #     app.add_handler(CommandHandler("kunlik", kunlik))
# #     app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
# #     print("🚀 Bot ishga tushdi...")
# #     app.run_polling()


    

# # import sqlite3
# # import re
# # import os
# # from datetime import datetime, timedelta
# # import pandas as pd
# # import matplotlib.pyplot as plt
# # from dotenv import load_dotenv
# # from telegram import Update
# # from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# # # --- SOZLAMALAR ---
# # load_dotenv()
# # TOKEN = os.getenv("BOT_TOKEN")
# # conn = sqlite3.connect("hisobchi_pro.db", check_same_thread=False)
# # c = conn.cursor()

# # def init_db():
# #     c.execute("""CREATE TABLE IF NOT EXISTS transactions (
# #         id INTEGER PRIMARY KEY AUTOINCREMENT, 
# #         user_id INTEGER, 
# #         type TEXT, 
# #         amount REAL, 
# #         category TEXT, 
# #         description TEXT, 
# #         date TEXT)""")
# #     c.execute("""CREATE TABLE IF NOT EXISTS user_categories (
# #         user_id INTEGER, 
# #         category_name TEXT, 
# #         UNIQUE(user_id, category_name))""")
# #     conn.commit()

# # init_db()

# # # --- AI PARSER ---
# # def parse_text(text, user_id):
# #     text = text.lower()
# #     amount_match = re.findall(r'\d+', text)
# #     if not amount_match: return None
# #     amount = int(amount_match[0])
    
# #     c.execute("SELECT category_name FROM user_categories WHERE user_id=?", (user_id,))
# #     user_cats = [row[0].lower() for row in c.fetchall()]
# #     for cat in user_cats:
# #         if cat in text: return ("Chiqim", amount, cat.capitalize())
    
# #     keywords = {"taksi": "Transport", "ovqat": "Oziq-ovqat", "kafe": "Kafe", "internet": "Aloqa", "uy": "Ro'zg'or"}
# #     for key, val in keywords.items():
# #         if key in text: return ("Chiqim", amount, val)
    
# #     if any(word in text for word in ["kirim", "oldim", "oylik", "+", "tushdi"]): 
# #         return ("Kirim", amount, "Daromad")
# #     return ("Chiqim", amount, "Boshqa")

# # # --- KOMANDALAR ---

# # async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     msg = (
# #         "🤖 <b>Hisobchi AI Bot — Xush kelibsiz!</b>\n\n"
# #         "Men sizning daromad va xarajatlaringizni tahlil qilaman.\n\n"
# #         "📈 <b>Grafiklar haqida:</b>\n"
# #         "• <b>Kirimlar</b> — yashil chiziq bilan nol chizig'idan <b>tepaga</b> qarab yuradi.\n"
# #         "• <b>Chiqimlar</b> — qizil chiziq bilan nol chizig'idan <b>pastga</b> qarab yuradi.\n\n"
# #         "Barcha buyruqlar: /help"
# #     )
# #     await update.message.reply_text(msg, parse_mode="HTML")

# # async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     help_text = (
# #         "📜 <b>Buyruqlar:</b>\n"
# #         "/hisobot - Balans\n"
# #         "/kunlik - 10 kunlik oqim grafigi\n"
# #         "/haftalik - 4 haftalik dinamika\n"
# #         "/oylik - 1 yillik tahlil\n"
# #         "/pie - Kategoriyalar taqsimoti\n"
# #         "/categories - Kategoriyalar ro'yxati\n"
# #         "/add_cat [nomi] - Yangi kategoriya"
# #     )
# #     await update.message.reply_text(help_text, parse_mode="HTML")

# # # --- ASOSIY GRAFIK CHIZISH (KIRIM TEPAGA, CHIQIM PASGA) ---

# # async def send_flow_chart(update, df, title, filename):
# #     plt.figure(figsize=(12, 6))
    
# #     # Sanani formatlash
# #     df['date'] = pd.to_datetime(df['date'], format='mixed').dt.date
    
# #     # Kirimni musbat, Chiqimni manfiy qiymatga aylantirish
# #     df['plot_amount'] = df.apply(lambda x: x['amount'] if x['type'] == 'Kirim' else -x['amount'], axis=1)
    
# #     # Har bir kun uchun jami kirim va jami chiqimni guruhlash
# #     grouped = df.groupby(['date', 'type'])['plot_amount'].sum().unstack(fill_value=0)
    
# #     # Agar jadvalda faqat Kirim yoki faqat Chiqim bo'lsa, xato bermasligi uchun tekshiramiz
# #     if 'Kirim' not in grouped.columns: grouped['Kirim'] = 0
# #     if 'Chiqim' not in grouped.columns: grouped['Chiqim'] = 0

# #     # Chiziqlarni chizish
# #     dates_str = [d.strftime('%Y-%m-%d') for d in grouped.index]
    
# #     # Kirim (Yashil, tepaga)
# #     plt.plot(dates_str, grouped['Kirim'], marker='o', color='#28a745', label='Kirim (+)', linewidth=3, markersize=8)
# #     plt.fill_between(dates_str, grouped['Kirim'], 0, color='#28a745', alpha=0.2)
    
# #     # Chiqim (Qizil, pastga)
# #     plt.plot(dates_str, grouped['Chiqim'], marker='o', color='#dc3545', label='Chiqim (-)', linewidth=3, markersize=8)
# #     plt.fill_between(dates_str, grouped['Chiqim'], 0, color='#dc3545', alpha=0.2)

# #     # Nol chizig'ini ajratib ko'rsatish
# #     plt.axhline(0, color='black', linewidth=2, linestyle='--')
    
# #     plt.title(title, fontsize=16, fontweight='bold')
# #     plt.ylabel("Summa (so'm)", fontsize=12)
# #     plt.grid(True, linestyle=':', alpha=0.6)
# #     plt.legend(loc='upper left', frameon=True, shadow=True)
# #     plt.xticks(rotation=45)
# #     plt.tight_layout()
    
# #     plt.savefig(filename, dpi=150)
# #     plt.close()
    
# #     await update.message.reply_photo(photo=open(filename, "rb"), caption=f"📊 {title}")
# #     if os.path.exists(filename): os.remove(filename)

# # # --- HISOBOT FUNKSIYALARI ---

# # async def kunlik(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     user_id = update.message.from_user.id
# #     limit = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
# #     df = pd.read_sql_query("SELECT date, type, amount FROM transactions WHERE user_id=? AND date >= ?", conn, params=(user_id, limit))
# #     if not df.empty:
# #         await send_flow_chart(update, df, "10 Kunlik Moliyaviy Oqim", "daily.png")
# #     else: await update.message.reply_text("Ma'lumot topilmadi.")

# # async def haftalik(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     user_id = update.message.from_user.id
# #     limit = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
# #     df = pd.read_sql_query("SELECT date, type, amount FROM transactions WHERE user_id=? AND date >= ?", conn, params=(user_id, limit))
# #     if not df.empty:
# #         await send_flow_chart(update, df, "Haftalik Moliyaviy Dinamika", "weekly.png")
# #     else: await update.message.reply_text("Ma'lumotlar yetarli emas.")

# # async def oylik(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     user_id = update.message.from_user.id
# #     df = pd.read_sql_query("SELECT date, type, amount FROM transactions WHERE user_id=?", conn, params=(user_id,))
# #     if not df.empty:
# #         await send_flow_chart(update, df, "Oylik Moliyaviy Oqim", "monthly.png")
# #     else: await update.message.reply_text("Ma'lumot yo'q.")

# # async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     res = parse_text(update.message.text, update.message.from_user.id)
# #     if res:
# #         t, a, cat = res
# #         today = datetime.now().strftime("%Y-%m-%d")
# #         c.execute("INSERT INTO transactions (user_id, type, amount, category, date) VALUES (?,?,?,?,?)", 
# #                   (update.message.from_user.id, t, a, cat, today))
# #         conn.commit()
# #         await update.message.reply_text(f"✅ Saqlandi: <b>{t}</b> {a:,} so'm", parse_mode="HTML")
# #     else: await update.message.reply_text("🤷‍♂️ Tushunmadim.")

# # # --- BOSHQA BUYRUQLAR (Pie, Categories, Add_cat) ---
# # async def pie_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     user_id = update.message.from_user.id
# #     df = pd.read_sql_query("SELECT category, amount FROM transactions WHERE user_id=? AND type='Chiqim'", conn, params=(user_id,))
# #     if df.empty: return
# #     cat_sum = df.groupby('category')['amount'].sum()
# #     plt.figure(figsize=(7, 7))
# #     cat_sum.plot(kind='pie', autopct='%1.1f%%', startangle=140, shadow=True, colors=plt.cm.Set3.colors)
# #     plt.title("Xarajatlar tarkibi")
# #     plt.ylabel('')
# #     plt.savefig("pie.png")
# #     plt.close()
# #     await update.message.reply_photo(photo=open("pie.png", "rb"))
# #     if os.path.exists("pie.png"): os.remove("pie.png")

# # async def list_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     user_id = update.message.from_user.id
# #     c.execute("SELECT category_name FROM user_categories WHERE user_id=?", (user_id,))
# #     cats = [row[0] for row in c.fetchall()]
# #     text = "📁 <b>Kategoriyalaringiz:</b>\n\n" + ("\n".join([f"🔹 {c}" for c in cats]) if cats else "Ro'yxat bo'sh.")
# #     await update.message.reply_text(text, parse_mode="HTML")

# # async def add_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     if not context.args: return
# #     try:
# #         c.execute("INSERT INTO user_categories VALUES (?, ?)", (update.message.from_user.id, context.args[0]))
# #         conn.commit()
# #         await update.message.reply_text("✅ Qo'shildi.")
# #     except: pass

# # async def hisobot(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     user_id = update.message.from_user.id
# #     df = pd.read_sql_query("SELECT type, amount FROM transactions WHERE user_id=?", conn, params=(user_id,))
# #     if df.empty: return
# #     kir = df[df['type'] == 'Kirim']['amount'].sum()
# #     chiq = df[df['type'] == 'Chiqim']['amount'].sum()
# #     await update.message.reply_text(f"📊 <b>Balans:</b>\n\n💰 Kirim: {kir:,}\n💸 Chiqim: {chiq:,}\n🧾 Qoldiq: {kir-chiq:,}", parse_mode="HTML")

# # if __name__ == "__main__":
# #     app = ApplicationBuilder().token(TOKEN).build()
# #     app.add_handler(CommandHandler("start", start))
# #     app.add_handler(CommandHandler("help", help_command))
# #     app.add_handler(CommandHandler("categories", list_categories))
# #     app.add_handler(CommandHandler("hisobot", hisobot))
# #     app.add_handler(CommandHandler("kunlik", kunlik))
# #     app.add_handler(CommandHandler("haftalik", haftalik))
# #     app.add_handler(CommandHandler("oylik", oylik))
# #     app.add_handler(CommandHandler("pie", pie_chart))
# #     app.add_handler(CommandHandler("add_cat", add_category))
# #     app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
# #     print("🚀 Bot ishlamoqda...")
# #     app.run_polling(drop_pending_updates=True)

# # import sqlite3
# # import re
# # import os
# # from datetime import datetime, timedelta
# # import pandas as pd
# # import matplotlib.pyplot as plt
# # from dotenv import load_dotenv
# # from telegram import Update
# # from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# # # --- SOZLAMALAR ---
# # load_dotenv()
# # TOKEN = os.getenv("BOT_TOKEN")
# # conn = sqlite3.connect("hisobchi_pro.db", check_same_thread=False)
# # c = conn.cursor()

# # def init_db():
# #     c.execute("""CREATE TABLE IF NOT EXISTS transactions (
# #         id INTEGER PRIMARY KEY AUTOINCREMENT, 
# #         user_id INTEGER, 
# #         type TEXT, 
# #         amount REAL, 
# #         category TEXT, 
# #         description TEXT, 
# #         date TEXT)""")
# #     c.execute("""CREATE TABLE IF NOT EXISTS user_categories (
# #         user_id INTEGER, 
# #         category_name TEXT, 
# #         UNIQUE(user_id, category_name))""")
# #     conn.commit()

# # init_db()

# # # --- AI PARSER ---
# # def parse_text(text, user_id):
# #     text = text.lower()
# #     amount_match = re.findall(r'\d+', text)
# #     if not amount_match: return None
# #     amount = int(amount_match[0])
    
# #     c.execute("SELECT category_name FROM user_categories WHERE user_id=?", (user_id,))
# #     user_cats = [row[0].lower() for row in c.fetchall()]
# #     for cat in user_cats:
# #         if cat in text: return ("Chiqim", amount, cat.capitalize())
    
# #     keywords = {"taksi": "Transport", "ovqat": "Oziq-ovqat", "kafe": "Kafe", "internet": "Aloqa", "uy": "Ro'zg'or"}
# #     for key, val in keywords.items():
# #         if key in text: return ("Chiqim", amount, val)
    
# #     if any(word in text for word in ["kirim", "oldim", "oylik", "+", "tushdi"]): return ("Kirim", amount, "Daromad")
# #     return ("Chiqim", amount, "Boshqa")

# # # --- KOMANDALAR ---

# # async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     msg = (
# #         "🤖 <b>Hisobchi AI Bot — Shaxsiy moliya yordamchingiz!</b>\n\n"
# #         "Men sizning xarajat va daromadlaringizni matndan tahlil qilib, bazaga saqlayman.\n\n"
# #         "📝 <b>Qanday ishlatish?</b>\n"
# #         "Shunchaki yozing: <i>'Tushlik uchun 45000 so'm'</i> yoki <i>'Oylik tushdi 5000000'</i>.\n\n"
# #         "📊 <b>Asosiy imkoniyatlar:</b>\n"
# #         "• Kirim va chiqimni alohida grafiklarda ko'rish\n"
# #         "• Shaxsiy kategoriyalar qo'shish\n"
# #         "• Kunlik xarajat limitini belgilash\n\n"
# #         "Barcha buyruqlar ro'yxati uchun: /help"
# #     )
# #     await update.message.reply_text(msg, parse_mode="HTML")

# # async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     help_text = (
# #         "📜 <b>Bot buyruqlari ro'yxati:</b>\n\n"
# #         "💰 <b>Moliya:</b>\n"
# #         "/hisobot - Umumiy balans va qoldiq\n"
# #         "/kunlik - So'nggi 10 kunlik oqim grafigi\n"
# #         "/haftalik - So'nggi 4 haftalik oqim grafigi\n"
# #         "/oylik - Bir yillik oylik dinamika\n"
# #         "/pie - Xarajatlar taqsimoti (kategoriya bo'yicha)\n\n"
# #         "⚙️ <b>Sozlamalar:</b>\n"
# #         "/categories - Siz qo'shgan kategoriyalar\n"
# #         "/add_cat [nomi] - Yangi kategoriya qo'shish\n"
# #         "/limit [summa] - Kunlik xarajat limiti\n"
# #     )
# #     await update.message.reply_text(help_text, parse_mode="HTML")

# # async def list_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     user_id = update.message.from_user.id
# #     c.execute("SELECT category_name FROM user_categories WHERE user_id=?", (user_id,))
# #     cats = [row[0] for row in c.fetchall()]
# #     text = "📁 <b>Sizning kategoriyalaringiz:</b>\n\n" + ("\n".join([f"🔹 {c}" for c in cats]) if cats else "Hali kategoriya qo'shmagansiz.")
# #     await update.message.reply_text(text, parse_mode="HTML")

# # # --- GRAFIK FUNKSIYASI (KIRIM TEPAGA, CHIQIM PASGA) ---

# # async def send_flow_chart(update, df, title, filename):
# #     plt.figure(figsize=(10, 6))
    
# #     # Sanani to'g'ri o'qish (mixed format xatolikni tuzatadi)
# #     df['date'] = pd.to_datetime(df['date'], format='mixed').dt.date
    
# #     # Kirimni musbat, Chiqimni manfiy qilish
# #     df['plot_amount'] = df.apply(lambda x: x['amount'] if x['type'] == 'Kirim' else -x['amount'], axis=1)
    
# #     # Guruhlash
# #     grouped = df.groupby(['date', 'type'])['plot_amount'].sum().unstack(fill_value=0)
    
# #     # Agar ustunlar yetishmasa, xato bermasligi uchun nol qo'shamiz
# #     for col in ['Kirim', 'Chiqim']:
# #         if col not in grouped.columns: grouped[col] = 0

# #     plt.plot(grouped.index.astype(str), grouped['Kirim'], marker='o', color='#28a745', label='Kirim (+)', linewidth=2)
# #     plt.plot(grouped.index.astype(str), grouped['Chiqim'], marker='o', color='#dc3545', label='Chiqim (-)', linewidth=2)
        
# #     plt.axhline(0, color='black', linewidth=1.5, linestyle='--') # Nol chizig'i
# #     plt.fill_between(grouped.index.astype(str), grouped['Kirim'], color='#28a745', alpha=0.1)
# #     plt.fill_between(grouped.index.astype(str), grouped['Chiqim'], color='#dc3545', alpha=0.1)

# #     plt.title(title, fontsize=14)
# #     plt.legend(loc='best')
# #     plt.grid(True, linestyle=':', alpha=0.6)
# #     plt.xticks(rotation=45)
# #     plt.tight_layout()
    
# #     plt.savefig(filename)
# #     plt.close()
# #     await update.message.reply_photo(photo=open(filename, "rb"))
# #     if os.path.exists(filename): os.remove(filename)

# # # --- HISOBOT HANDLERLARI ---

# # async def kunlik(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     user_id = update.message.from_user.id
# #     limit = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
# #     df = pd.read_sql_query("SELECT date, type, amount FROM transactions WHERE user_id=? AND date >= ?", conn, params=(user_id, limit))
# #     if not df.empty:
# #         await send_flow_chart(update, df, "10 Kunlik Moliyaviy Oqim", "daily.png")
# #     else: await update.message.reply_text("Ma'lumot topilmadi.")

# # async def haftalik(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     user_id = update.message.from_user.id
# #     limit = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
# #     df = pd.read_sql_query("SELECT date, type, amount FROM transactions WHERE user_id=? AND date >= ?", conn, params=(user_id, limit))
# #     if not df.empty:
# #         await send_flow_chart(update, df, "Haftalik Moliyaviy Dinamika", "weekly.png")
# #     else: await update.message.reply_text("Ma'lumotlar yetarli emas.")

# # async def oylik(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     user_id = update.message.from_user.id
# #     df = pd.read_sql_query("SELECT date, type, amount FROM transactions WHERE user_id=?", conn, params=(user_id,))
# #     if not df.empty:
# #         await send_flow_chart(update, df, "Oylik Moliyaviy Oqim", "monthly.png")
# #     else: await update.message.reply_text("Ma'lumot yo'q.")

# # async def pie_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     user_id = update.message.from_user.id
# #     df = pd.read_sql_query("SELECT category, amount FROM transactions WHERE user_id=? AND type='Chiqim'", conn, params=(user_id,))
# #     if df.empty:
# #         await update.message.reply_text("Xarajatlar haqida ma'lumot yo'q.")
# #         return
# #     cat_sum = df.groupby('category')['amount'].sum()
# #     plt.figure(figsize=(7, 7))
# #     cat_sum.plot(kind='pie', autopct='%1.1f%%', startangle=140, colors=plt.cm.Paired.colors)
# #     plt.title("Xarajatlar Kategoriyasi")
# #     plt.ylabel('')
# #     plt.savefig("pie.png")
# #     plt.close()
# #     await update.message.reply_photo(photo=open("pie.png", "rb"))
# #     if os.path.exists("pie.png"): os.remove("pie.png")

# # async def hisobot(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     user_id = update.message.from_user.id
# #     df = pd.read_sql_query("SELECT type, amount FROM transactions WHERE user_id=?", conn, params=(user_id,))
# #     if df.empty:
# #         await update.message.reply_text("Bazangiz bo'sh.")
# #         return
# #     kir = df[df['type'] == 'Kirim']['amount'].sum()
# #     chiq = df[df['type'] == 'Chiqim']['amount'].sum()
# #     await update.message.reply_text(f"📊 <b>Umumiy Moliyaviy Holat:</b>\n\n💰 Kirim: <code>{kir:,.0f}</code> so'm\n💸 Chiqim: <code>{chiq:,.0f}</code> so'm\n🧾 Balans: <b>{kir-chiq:,.0f}</b> so'm", parse_mode="HTML")

# # async def add_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     if not context.args:
# #         await update.message.reply_text("Ishlatish: /add_cat Kiyim")
# #         return
# #     cat = context.args[0]
# #     try:
# #         c.execute("INSERT INTO user_categories (user_id, category_name) VALUES (?, ?)", (update.message.from_user.id, cat))
# #         conn.commit()
# #         await update.message.reply_text(f"✅ Yangi kategoriya qo'shildi: <b>{cat}</b>", parse_mode="HTML")
# #     except: await update.message.reply_text("❌ Bu kategoriya allaqachon bor.")

# # async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     res = parse_text(update.message.text, update.message.from_user.id)
# #     if res:
# #         t, a, cat = res
# #         today = datetime.now().strftime("%Y-%m-%d")
# #         c.execute("INSERT INTO transactions (user_id, type, amount, category, date) VALUES (?,?,?,?,?)", 
# #                   (update.message.from_user.id, t, a, cat, today))
# #         conn.commit()
# #         await update.message.reply_text(f"✅ Saqlandi: <b>{t}</b> {a:,} so'm ({cat})", parse_mode="HTML")
# #     else: await update.message.reply_text("🤷‍♂️ Tushunmadim. Masalan: <i>'Taksi 12000'</i> deb yozing.")

# # # --- MAIN ---
# # if __name__ == "__main__":
# #     if not TOKEN:
# #         print("XATO: Token topilmadi!")
# #     else:
# #         app = ApplicationBuilder().token(TOKEN).build()
# #         app.add_handler(CommandHandler("start", start))
# #         app.add_handler(CommandHandler("help", help_command))
# #         app.add_handler(CommandHandler("categories", list_categories))
# #         app.add_handler(CommandHandler("hisobot", hisobot))
# #         app.add_handler(CommandHandler("kunlik", kunlik))
# #         app.add_handler(CommandHandler("haftalik", haftalik))
# #         app.add_handler(CommandHandler("oylik", oylik))
# #         app.add_handler(CommandHandler("pie", pie_chart))
# #         app.add_handler(CommandHandler("add_cat", add_category))
# #         app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
# #         print("🚀 Bot muvaffaqiyatli ishga tushdi...")
# #         app.run_polling(drop_pending_updates=True)

# # import sqlite3
# # import re
# # import os
# # from datetime import datetime, timedelta
# # import pandas as pd
# # import matplotlib.pyplot as plt
# # from dotenv import load_dotenv
# # from telegram import Update
# # from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# # # --- SOZLAMALAR ---
# # load_dotenv()
# # TOKEN = os.getenv("BOT_TOKEN")
# # conn = sqlite3.connect("hisobchi_pro.db", check_same_thread=False)
# # c = conn.cursor()

# # def init_db():
# #     c.execute("""CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, type TEXT, amount REAL, category TEXT, description TEXT, date TEXT)""")
# #     c.execute("""CREATE TABLE IF NOT EXISTS user_categories (user_id INTEGER, category_name TEXT, UNIQUE(user_id, category_name))""")
# #     conn.commit()

# # init_db()

# # # --- AI PARSER ---
# # def parse_text(text, user_id):
# #     text = text.lower()
# #     amount_match = re.findall(r'\d+', text)
# #     if not amount_match: return None
# #     amount = int(amount_match[0])
    
# #     c.execute("SELECT category_name FROM user_categories WHERE user_id=?", (user_id,))
# #     user_cats = [row[0].lower() for row in c.fetchall()]
# #     for cat in user_cats:
# #         if cat in text: return ("Chiqim", amount, cat.capitalize())
    
# #     keywords = {"taksi": "Transport", "ovqat": "Oziq-ovqat", "kafe": "Kafe", "internet": "Aloqa"}
# #     for key, val in keywords.items():
# #         if key in text: return ("Chiqim", amount, val)
    
# #     if any(word in text for word in ["kirim", "oldim", "oylik", "+"]): return ("Kirim", amount, "Daromad")
# #     return ("Chiqim", amount, "Boshqa")

# # # --- KOMANDALAR ---

# # async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     msg = (
# #         "🤖 <b>Hisobchi AI Bot - Shaxsiy Moliya Menejeri</b>\n\n"
# #         "Men sizning xarajat va daromadlaringizni nazorat qiluvchi aqlli botman.\n"
# #         "Yozuvni tushunaman (masalan: 'tushlikka 50 ming ketdi').\n\n"
# #         "ℹ️ <b>Asosiy ma'lumot:</b>\n"
# #         "- Bazangizni avtomatik yuritaman.\n"
# #         "- Grafiklar orqali moliyaviy oqimingizni ko'rsataman.\n"
# #         "- Limitlar o'rnatib, xarajatni nazorat qilishingizga yordam beraman.\n\n"
# #         "Barcha buyruqlarni ko'rish uchun /help ni bosing."
# #     )
# #     await update.message.reply_text(msg, parse_mode="HTML")

# # async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     help_text = (
# #         "📜 <b>Bot buyruqlari:</b>\n\n"
# #         "/hisobot - Umumiy balans\n"
# #         "/kunlik - Kunlik oqim grafigi\n"
# #         "/haftalik - Haftalik oqim grafigi\n"
# #         "/oylik - Oylik oqim grafigi\n"
# #         "/pie - Kategoriya tahlili\n"
# #         "/categories - Kategoriyalar ro'yxati\n"
# #         "/add_cat [nomi] - Yangi kategoriya qo'shish\n"
# #         "/limit [summa] - Kunlik limit"
# #     )
# #     await update.message.reply_text(help_text, parse_mode="HTML")

# # async def list_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     user_id = update.message.from_user.id
# #     c.execute("SELECT category_name FROM user_categories WHERE user_id=?", (user_id,))
# #     cats = [row[0] for row in c.fetchall()]
# #     text = "📁 <b>Sizning kategoriyalaringiz:</b>\n\n" + ("\n".join([f"🔹 {c}" for c in cats]) if cats else "Hali kategoriya qo'shmagansiz.")
# #     await update.message.reply_text(text, parse_mode="HTML")

# # # --- GRAFIK (KIRIM TEPAGA, CHIQIM PASGA) ---

# # async def send_flow_chart(update, df, title, filename):
# #     plt.figure(figsize=(10, 6))
    
# #     # Kirimni musbat, Chiqimni manfiy qilish
# #     df['plot_amount'] = df.apply(lambda x: x['amount'] if x['type'] == 'Kirim' else -x['amount'], axis=1)
# #     grouped = df.groupby(['date', 'type'])['plot_amount'].sum().unstack(fill_value=0)
    
# #     # Grafika chizish
# #     if 'Kirim' in grouped.columns:
# #         plt.plot(grouped.index, grouped['Kirim'], marker='o', color='green', label='Kirim', linewidth=2)
# #     if 'Chiqim' in grouped.columns:
# #         plt.plot(grouped.index, grouped['Chiqim'], marker='o', color='red', label='Chiqim', linewidth=2)
        
# #     plt.axhline(0, color='black', linewidth=1) # Nol chizig'i
# #     plt.title(title)
# #     plt.legend()
# #     plt.grid(True, linestyle='--', alpha=0.6)
# #     plt.xticks(rotation=45)
# #     plt.tight_layout()
# #     plt.savefig(filename)
# #     plt.close()
# #     await update.message.reply_photo(photo=open(filename, "rb"))
# #     if os.path.exists(filename): os.remove(filename)

# # # --- HISOBOT FUNKSIYALARI ---

# # async def kunlik(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     user_id = update.message.from_user.id
# #     limit = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
# #     df = pd.read_sql_query("SELECT date, type, amount FROM transactions WHERE user_id=? AND date >= ?", conn, params=(user_id, limit))
# #     if not df.empty:
# #         df['date'] = pd.to_datetime(df['date']).dt.date
# #         await send_flow_chart(update, df, "Kunlik Moliyaviy Oqim", "daily.png")
# #     else: await update.message.reply_text("Ma'lumot yo'q.")

# # async def haftalik(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     user_id = update.message.from_user.id
# #     limit = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
# #     df = pd.read_sql_query("SELECT date, type, amount FROM transactions WHERE user_id=? AND date >= ?", conn, params=(user_id, limit))
# #     if not df.empty:
# #         df['date'] = pd.to_datetime(df['date'])
# #         await send_flow_chart(update, df, "Haftalik Moliyaviy Oqim", "weekly.png")
# #     else: await update.message.reply_text("Ma'lumot yo'q.")

# # async def oylik(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     user_id = update.message.from_user.id
# #     df = pd.read_sql_query("SELECT date, type, amount FROM transactions WHERE user_id=?", conn, params=(user_id,))
# #     if not df.empty:
# #         df['date'] = pd.to_datetime(df['date'])
# #         await send_flow_chart(update, df, "Oylik Moliyaviy Oqim", "monthly.png")
# #     else: await update.message.reply_text("Ma'lumot yo'q.")

# # # --- HANDLERLAR ---

# # async def add_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     if not context.args: await update.message.reply_text("Ishlatish: /add_cat [nomi]"); return
# #     try:
# #         c.execute("INSERT INTO user_categories VALUES (?, ?)", (update.message.from_user.id, context.args[0]))
# #         conn.commit()
# #         await update.message.reply_text("✅ Saqlandi")
# #     except: await update.message.reply_text("❌ Xatolik")

# # async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     res = parse_text(update.message.text, update.message.from_user.id)
# #     if res:
# #         t, a, cat = res
# #         c.execute("INSERT INTO transactions (user_id, type, amount, category, date) VALUES (?,?,?,?,?)", 
# #                   (update.message.from_user.id, t, a, cat, datetime.now().strftime("%Y-%m-%d")))
# #         conn.commit()
# #         await update.message.reply_text(f"✅ Saqlandi: {t} {a} ({cat})")
# #     else: await update.message.reply_text("❌ Tushunmadim")

# # if __name__ == "__main__":
# #     app = ApplicationBuilder().token(TOKEN).build()
# #     app.add_handlers([
# #         CommandHandler("start", start),
# #         CommandHandler("help", help_command),
# #         CommandHandler("categories", list_categories),
# #         CommandHandler("kunlik", kunlik),
# #         CommandHandler("haftalik", haftalik),
# #         CommandHandler("oylik", oylik),
# #         CommandHandler("add_cat", add_category),
# #         MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
# #     ])
# #     app.run_polling()

# # import sqlite3
# # import re
# # import os
# # from datetime import datetime, timedelta
# # import pandas as pd
# # import matplotlib.pyplot as plt
# # from dotenv import load_dotenv  # Tokenni yashirish uchun
# # from telegram import Update
# # from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# # # --- SOZLAMALARNI YUKLASH ---
# # load_dotenv()
# # TOKEN = os.getenv("BOT_TOKEN")

# # # --- DATABASE SOZLAMALARI ---
# # conn = sqlite3.connect("hisobchi_pro.db", check_same_thread=False)
# # c = conn.cursor()

# # def init_db():
# #     c.execute("""
# #     CREATE TABLE IF NOT EXISTS transactions (
# #         id INTEGER PRIMARY KEY AUTOINCREMENT,
# #         user_id INTEGER,
# #         type TEXT,
# #         amount REAL,
# #         category TEXT,
# #         description TEXT,
# #         date TEXT
# #     )
# #     """)
# #     c.execute("""
# #     CREATE TABLE IF NOT EXISTS user_categories (
# #         user_id INTEGER,
# #         category_name TEXT,
# #         UNIQUE(user_id, category_name)
# #     )
# #     """)
# #     conn.commit()

# # init_db()

# # # --- AI PARSER ---
# # def parse_text(text, user_id):
# #     text = text.lower()
# #     amount_match = re.findall(r'\d+', text)
# #     if not amount_match:
# #         return None
# #     amount = int(amount_match[0])

# #     c.execute("SELECT category_name FROM user_categories WHERE user_id=?", (user_id,))
# #     user_cats = [row[0].lower() for row in c.fetchall()]
    
# #     for cat in user_cats:
# #         if cat in text:
# #             return ("Chiqim", amount, cat.capitalize())

# #     keywords = {
# #         "taksi": "Transport", "avtobus": "Transport", "benzin": "Transport",
# #         "ovqat": "Oziq-ovqat", "tushlik": "Oziq-ovqat", "bozor": "Oziq-ovqat",
# #         "kafe": "Kafe", "restoran": "Kafe",
# #         "internet": "Aloqa", "paynet": "Aloqa", "tel": "Aloqa"
# #     }
    
# #     for key, val in keywords.items():
# #         if key in text:
# #             return ("Chiqim", amount, val)

# #     if any(word in text for word in ["kirim", "oldim", "oylik", "+", "sovg'a"]):
# #         return ("Kirim", amount, "Daromad")

# #     return ("Chiqim", amount, "Boshqa")

# # # --- KOMANDALAR ---

# # async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     text = (
# #         "💰 <b>Hisobchi AI PRO</b>\n\n"
# #         "Xarajatlarni oddiy matn ko'rinishida yozing.\n"
# #         "📊 <b>Buyruqlar:</b>\n"
# #         "/hisobot - Balans\n"
# #         "/kunlik - Nuqtali grafik\n"
# #         "/haftalik - Nuqtali grafik\n"
# #         "/pie - Kategoriyalar\n"
# #         "/add_cat [nomi] - Yangi kategoriya\n"
# #         "/limit [summa] - Limit o'rnatish"
# #     )
# #     await update.message.reply_text(text, parse_mode="HTML")

# # async def add_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     if not context.args:
# #         await update.message.reply_text("⚠️ Ishlatish: <code>/add_cat Kiyim</code>", parse_mode="HTML")
# #         return
# #     cat_name = context.args[0].strip()
# #     user_id = update.message.from_user.id
# #     try:
# #         c.execute("INSERT INTO user_categories (user_id, category_name) VALUES (?, ?)", (user_id, cat_name))
# #         conn.commit()
# #         await update.message.reply_text(f"✅ Kategoriya qo'shildi: <b>{cat_name}</b>", parse_mode="HTML")
# #     except sqlite3.IntegrityError:
# #         await update.message.reply_text("❌ Bu kategoriya allaqachon mavjud.")

# # async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     text = update.message.text
# #     user_id = update.message.from_user.id
# #     result = parse_text(text, user_id)
    
# #     if result:
# #         t_type, amount, cat = result
# #         date_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
# #         c.execute("INSERT INTO transactions (user_id, type, amount, category, description, date) VALUES (?, ?, ?, ?, ?, ?)",
# #                   (user_id, t_type, amount, cat, text, date_now))
# #         conn.commit()
        
# #         response = f"✅ Saqlandi!\n<b>{t_type}</b>: {amount:,} so'm\n<b>Kategoriya</b>: {cat}"
# #         if t_type == "Chiqim" and 'limit' in context.user_data:
# #             if amount > context.user_data['limit']:
# #                 response += f"\n\n⚠️ <b>DIQQAT!</b> Limitdan oshdingiz!"
# #         await update.message.reply_text(response, parse_mode="HTML")
# #     else:
# #         await update.message.reply_text("🤷‍♂️ Miqdor va maqsadni tushunmadim.")

# # # --- GRAFIK FUNKSIYALARI ---

# # async def send_dot_plot(update, df, title, filename):
# #     """Nuqtali grafik yaratish uchun funksiya"""
# #     plt.figure(figsize=(10, 5))
# #     # 'marker' nuqtalarni qo'yadi, 'linestyle' ularni birlashtiradi
# #     plt.plot(df.index.astype(str), df.values, marker='o', linestyle='-', color='#1f77b4', linewidth=2)
# #     plt.title(title)
# #     plt.xlabel("Sana")
# #     plt.ylabel("Summa (so'm)")
# #     plt.grid(True, linestyle='--', alpha=0.7)
# #     plt.xticks(rotation=45)
# #     plt.tight_layout()
# #     plt.savefig(filename)
# #     plt.close()
# #     await update.message.reply_photo(photo=open(filename, "rb"))
# #     if os.path.exists(filename):
# #         os.remove(filename)

# # async def kunlik(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     user_id = update.message.from_user.id
# #     # Oxirgi 10 kunlik ma'lumot
# #     ten_days_ago = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
# #     df = pd.read_sql_query("SELECT date, amount FROM transactions WHERE user_id=? AND type='Chiqim' AND date >= ?", 
# #                            conn, params=(user_id, ten_days_ago))
# #     if df.empty:
# #         await update.message.reply_text("Oxirgi kunlarda xarajatlar yo'q.")
# #         return
# #     df['date'] = pd.to_datetime(df['date']).dt.date
# #     daily_sum = df.groupby('date')['amount'].sum()
# #     await send_dot_plot(update, daily_sum, "Kunlik xarajatlar tahlili (Nuqtali)", "daily.png")

# # async def haftalik(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     user_id = update.message.from_user.id
# #     # Oxirgi 4 haftalik ma'lumot
# #     one_month_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
# #     df = pd.read_sql_query("SELECT date, amount FROM transactions WHERE user_id=? AND type='Chiqim' AND date >= ?", 
# #                            conn, params=(user_id, one_month_ago))
# #     if df.empty:
# #         await update.message.reply_text("Ma'lumotlar yetarli emas.")
# #         return
# #     df['date'] = pd.to_datetime(df['date'])
# #     # Haftalar bo'yicha guruhlash
# #     weekly_sum = df.resample('W', on='date')['amount'].sum()
# #     await send_dot_plot(update, weekly_sum, "Haftalik xarajatlar tahlili (Nuqtali)", "weekly.png")

# # async def pie_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     user_id = update.message.from_user.id
# #     df = pd.read_sql_query("SELECT category, amount FROM transactions WHERE user_id=? AND type='Chiqim'", conn, params=(user_id,))
# #     if df.empty:
# #         await update.message.reply_text("Ma'lumot yo'q.")
# #         return
# #     cat_sum = df.groupby('category')['amount'].sum()
# #     plt.figure(figsize=(7, 7))
# #     cat_sum.plot(kind='pie', autopct='%1.1f%%', startangle=140, shadow=True)
# #     plt.title("Xarajatlar tarkibi")
# #     plt.ylabel('')
# #     plt.savefig("pie.png")
# #     plt.close()
# #     await update.message.reply_photo(photo=open("pie.png", "rb"))
# #     if os.path.exists("pie.png"):
# #         os.remove("pie.png")

# # async def hisobot(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     user_id = update.message.from_user.id
# #     df = pd.read_sql_query("SELECT type, amount FROM transactions WHERE user_id=?", conn, params=(user_id,))
# #     if df.empty:
# #         await update.message.reply_text("Hali ma'lumotlar yo'q.")
# #         return
# #     kirim = df[df['type'] == 'Kirim']['amount'].sum()
# #     chiqim = df[df['type'] == 'Chiqim']['amount'].sum()
# #     await update.message.reply_text(f"📊 <b>Hisobot</b>\n\n💰 Kirim: {kirim:,}\n💸 Chiqim: {chiqim:,}\n💳 Balans: {kirim-chiqim:,}", parse_mode="HTML")

# # async def set_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
# #     try:
# #         val = int(context.args[0])
# #         context.user_data['limit'] = val
# #         await update.message.reply_text(f"✅ Limit {val:,} so'mga o'rnatildi.")
# #     except:
# #         await update.message.reply_text("Xato! Misol: /limit 50000")

# # # --- ASOSIY ---
# # if __name__ == "__main__":
# #     if not TOKEN:
# #         print("❌ XATO: Token topilmadi! .env faylini tekshiring.")
# #     else:
# #         app = ApplicationBuilder().token(TOKEN).build()
# #         app.add_handler(CommandHandler("start", start))
# #         app.add_handler(CommandHandler("add_cat", add_category))
# #         app.add_handler(CommandHandler("hisobot", hisobot))
# #         app.add_handler(CommandHandler("kunlik", kunlik))
# #         app.add_handler(CommandHandler("haftalik", haftalik))
# #         app.add_handler(CommandHandler("pie", pie_chart))
# #         app.add_handler(CommandHandler("limit", set_limit))
# #         app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
# #         print("🚀 Bot ishga tushdi (Token yashirilgan)...")
# #         app.run_polling(drop_pending_updates=True)
