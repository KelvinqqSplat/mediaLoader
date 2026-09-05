import os, sys, logging, threading, asyncio, sqlite3
from datetime import datetime, timedelta
from fastapi import FastAPI
import uvicorn
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import yt_dlp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("No token")
    sys.exit(1)

conn = sqlite3.connect("subscribers.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, is_subscribed BOOLEAN DEFAULT 0, subscribed_until TEXT)")
conn.commit()

def is_subscribed(user_id):
    cursor.execute("SELECT subscribed_until FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    if not row or not row[0]:
        return False
    if datetime.fromisoformat(row[0]) < datetime.now():
        cursor.execute("UPDATE users SET is_subscribed=0 WHERE user_id=?", (user_id,))
        conn.commit()
        return False
    return True

def set_subscription(user_id, days):
    until = (datetime.now() + timedelta(days=days)).isoformat()
    cursor.execute("INSERT OR REPLACE INTO users (user_id, is_subscribed, subscribed_until) VALUES (?, 1, ?)", (user_id, until))
    conn.commit()

async def start(update, context):
    user_id = update.effective_user.id
    keyboard = [[InlineKeyboardButton("💎 Подписка (30 дней)", callback_data="buy_sub")]] if not is_subscribed(user_id) else []
    await update.message.reply_text("Отправь ссылку на видео", reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None)

async def buy_sub(update, context):
    query = update.callback_query
    await query.answer()
    set_subscription(query.from_user.id, 30)
    await query.edit_message_text("Подписка оформлена!")

async def handle_url(update, context):
    url = update.message.text.strip()
    if not url.startswith(("http://", "https://")):
        await update.message.reply_text("Это не ссылка")
        return
    status = await update.message.reply_text("Загрузка...")
    os.makedirs("downloads", exist_ok=True)
    ydl_opts = {
        "format": "best[height<=720]",
        "outtmpl": "downloads/%(title)s.%(ext)s",
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "headers": {"User-Agent": "Mozilla/5.0"}
    }
    if os.path.exists("cookies.txt"):
        ydl_opts["cookiefile"] = "cookies.txt"
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info is None:
                await update.message.reply_text("Ошибка получения инфо")
                return
            ydl.download([url])
            path = ydl.prepare_filename(info)
            if not os.path.exists(path):
                import glob
                files = glob.glob("downloads/*")
                path = files[0] if files else None
            if path:
                with open(path, "rb") as f:
                    await update.message.reply_video(video=f)
                os.remove(path)
            else:
                await update.message.reply_text("Файл не найден")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")
    finally:
        await status.delete()

app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(buy_sub, pattern="buy_sub"))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))

web_app = FastAPI()
@web_app.get("/")
def health():
    return {"ok": True}

def run_web():
    uvicorn.run(web_app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))

async def bot_loop():
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    logger.info("Starting...")
    threading.Thread(target=run_web, daemon=True).start()
    asyncio.run(bot_loop())
