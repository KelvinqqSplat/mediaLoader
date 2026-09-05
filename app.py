import os
import sys
import logging
import threading
import asyncio
import sqlite3
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = []
    if is_subscribed(user_id):
        keyboard.append([InlineKeyboardButton("✅ Подписка активна", callback_data="sub_info")])
    else:
        keyboard.append([InlineKeyboardButton("💎 Подписка (30 дней)", callback_data="buy_sub")])
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    await update.message.reply_text(
        "👋 Привет! Отправь ссылку на видео (YouTube, TikTok, Instagram, VK и др.)",
        reply_markup=reply_markup
    )

async def buy_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    set_subscription(query.from_user.id, 30)
    await query.edit_message_text("🎉 Подписка оформлена на 30 дней!")

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    url = update.message.text.strip()
    if not url.startswith(("http://", "https://")):
        await update.message.reply_text("❌ Это не ссылка")
        return

    status_msg = await update.message.reply_text("⏳ Загрузка...")
    os.makedirs("downloads", exist_ok=True)

    # Расширенные настройки
    ydl_opts = {
        "format": "best[height<=720]",
        "outtmpl": "downloads/%(title)s.%(ext)s",
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "extract_flat": False,
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        },
        "extractor_args": {
            "youtube": {
                "skip": ["dash", "hls"],
                "player_client": ["android", "web"],
            }
        }
    }

    # Если есть cookies.txt – используем
    if os.path.exists("cookies.txt"):
        ydl_opts["cookiefile"] = "cookies.txt"
        logger.info("Using cookies")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Пытаемся получить информацию
            info = ydl.extract_info(url, download=False)
            if info is None:
                await update.message.reply_text("❌ Не удалось получить информацию. Проверьте ссылку.")
                return
            # Если есть возрастное ограничение
            if info.get("age_limit") and info["age_limit"] > 0:
                await update.message.reply_text("❌ Видео имеет возрастное ограничение.")
                return
            # Скачиваем
            ydl.download([url])
            file_path = ydl.prepare_filename(info)
            if not os.path.exists(file_path):
                import glob
                files = glob.glob("downloads/*")
                file_path = files[0] if files else None
            if not file_path:
                await update.message.reply_text("❌ Файл не найден")
                return
            # Отправляем
            with open(file_path, "rb") as f:
                await update.message.reply_video(video=f)
            if not is_subscribed(user_id):
                await update.message.reply_text("💬 Реклама. Оформи подписку через /start.")
            os.remove(file_path)
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Download error: {error_msg}", exc_info=True)
        await update.message.reply_text(f"❌ Ошибка: {error_msg[:200]}")  # выводим первые 200 символов
    finally:
        await status_msg.delete()

app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(buy_sub, pattern="buy_sub"))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))

web_app = FastAPI()
@web_app.get("/")
def health():
    return {"ok": True}

def run_web():
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(web_app, host="0.0.0.0", port=port)

async def bot_loop():
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    logger.info("Starting bot...")
    threading.Thread(target=run_web, daemon=True).start()
    asyncio.run(bot_loop())        logger.error(f"Download error: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")
    finally:
        await status_msg.delete()

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
