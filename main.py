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

# === Логирование ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === Токен ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("BOT_TOKEN not set")
    sys.exit(1)

# === База данных ===
conn = sqlite3.connect("subscribers.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        is_subscribed BOOLEAN DEFAULT 0,
        subscribed_until TEXT
    )
""")
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

# === Команды ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = []
    if is_subscribed(user_id):
        keyboard.append([InlineKeyboardButton("✅ Подписка активна", callback_data="sub_info")])
    else:
        keyboard.append([InlineKeyboardButton("💎 Оформить подписку (30 дней)", callback_data="buy_sub")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "👋 Привет! Я скачиваю видео и аудио из соцсетей.\n\n"
        "📌 Отправь мне ссылку (YouTube, TikTok, Instagram, VK и др.) — я пришлю файл.\n"
        "💎 Подписка убирает рекламу и увеличивает лимиты.",
        reply_markup=reply_markup
    )

async def buy_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    set_subscription(user_id, 30)
    await query.edit_message_text("🎉 Подписка оформлена на 30 дней! Реклама отключена.")

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    url = update.message.text.strip()
    if not url.startswith(("http://", "https://")):
        await update.message.reply_text("❌ Это не похоже на ссылку. Отправь корректный URL.")
        return

    status_msg = await update.message.reply_text("⏳ Начинаю загрузку...")

    os.makedirs("downloads", exist_ok=True)

    ydl_opts = {
        "format": "best[height<=720]",
        "outtmpl": "downloads/%(title)s.%(ext)s",
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "extract_flat": False,
        "extractor_args": {
            "youtube": {"skip": ["dash", "hls"]},
        },
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3",
        }
    }

    if os.path.exists("cookies.txt"):
        ydl_opts["cookiefile"] = "cookies.txt"
        logger.info("Using cookies from cookies.txt")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Сначала получаем информацию (без скачивания)
            info = ydl.extract_info(url, download=False)
            if info is None:
                await update.message.reply_text("❌ Не удалось получить информацию по ссылке. Попробуйте позже.")
                return
            # Теперь скачиваем
            ydl.download([url])
            file_path = ydl.prepare_filename(info)
            if not os.path.exists(file_path):
                import glob
                files = glob.glob("downloads/*")
                if files:
                    file_path = files[0]
                else:
                    await update.message.reply_text("❌ Файл не найден после скачивания.")
                    return
            # Отправляем файл
            ext = os.path.splitext(file_path)[1].lower()
            with open(file_path, "rb") as f:
                if ext in ['.mp4', '.webm', '.mov']:
                    await update.message.reply_video(video=f)
                elif ext in ['.mp3', '.m4a', '.aac']:
                    await update.message.reply_audio(audio=f)
                else:
                    await update.message.reply_document(document=f)
            # Реклама бесплатным
            if not is_subscribed(user_id):
                await update.message.reply_text(
                    "💬 Хотите убрать рекламу и скачивать без ограничений? Оформите подписку через /start."
                )
            os.remove(file_path)
    except Exception as e:
        logger.error(f"Download error: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")
    finally:
        await status_msg.delete()

# === Создаём приложение ===
app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(buy_sub, pattern="buy_sub"))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))

# === FastAPI для keep-alive ===
web_app = FastAPI()
@web_app.get("/")
def health():
    return {"status": "ok"}

def run_webserver():
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(web_app, host="0.0.0.0", port=port)

async def run_bot():
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    logger.info("Starting bot...")
    threading.Thread(target=run_webserver, daemon=True).start()
    asyncio.run(run_bot())    if os.path.exists("cookies.txt"):
        ydl_opts["cookiefile"] = "cookies.txt"
        logger.info("Using cookies from cookies.txt")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Сначала получаем информацию (без скачивания)
            info = ydl.extract_info(url, download=False)
            if info is None:
                await update.message.reply_text("❌ Не удалось получить информацию по ссылке. Попробуйте позже.")
                return
            # Теперь скачиваем
            ydl.download([url])
            file_path = ydl.prepare_filename(info)
            if not os.path.exists(file_path):
                import glob
                files = glob.glob("downloads/*")
                if files:
                    file_path = files[0]
                else:
                    await update.message.reply_text("❌ Файл не найден после скачивания.")
                    return
            # Отправляем файл
            ext = os.path.splitext(file_path)[1].lower()
            with open(file_path, "rb") as f:
                if ext in ['.mp4', '.webm', '.mov']:
                    await update.message.reply_video(video=f)
                elif ext in ['.mp3', '.m4a', '.aac']:
                    await update.message.reply_audio(audio=f)
                else:
                    await update.message.reply_document(document=f)
            # Реклама бесплатным
            if not is_subscribed(user_id):
                await update.message.reply_text(
                    "💬 Хотите убрать рекламу и скачивать без ограничений? Оформите подписку через /start."
                )
            os.remove(file_path)
    except Exception as e:
        logger.error(f"Download error: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")
    finally:
        await status_msg.delete()

# === Создаём приложение ===
app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(buy_sub, pattern="buy_sub"))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))

# === FastAPI для keep-alive ===
web_app = FastAPI()
@web_app.get("/")
def health():
    return {"status": "ok"}

def run_webserver():
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(web_app, host="0.0.0.0", port=port)

async def run_bot():
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    logger.info("Starting bot...")
    threading.Thread(target=run_webserver, daemon=True).start()
    asyncio.run(run_bot())}

    # Если есть cookies.txt – используем
    if os.path.exists("cookies.txt"):
        ydl_opts["cookiefile"] = "cookies.txt"
        logger.info("Using cookies from cookies.txt")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
            if not os.path.exists(file_path):
                # Поиск по маске
                import glob
                files = glob.glob("downloads/*")
                if files:
                    file_path = files[0]
                else:
                    await update.message.reply_text("❌ Файл не найден после скачивания.")
                    return
            # Определяем тип файла и отправляем
            ext = os.path.splitext(file_path)[1].lower()
            with open(file_path, "rb") as f:
                if ext in ['.mp4', '.webm', '.mov']:
                    await update.message.reply_video(video=f)
                elif ext in ['.mp3', '.m4a', '.aac']:
                    await update.message.reply_audio(audio=f)
                else:
                    await update.message.reply_document(document=f)
            # Реклама для бесплатных
            if not is_subscribed(user_id):
                await update.message.reply_text(
                    "💬 Хотите убрать рекламу и скачивать без ограничений? Оформите подписку через /start."
                )
            os.remove(file_path)
    except Exception as e:
        logger.error(f"Error downloading: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")
    finally:
        await status_msg.delete()

# === Создаём приложение Telegram ===
app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(buy_sub, pattern="buy_sub"))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))

# === FastAPI для keep-alive ===
web_app = FastAPI()
@web_app.get("/")
def health():
    return {"status": "ok"}

def run_webserver():
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(web_app, host="0.0.0.0", port=port)
    
    async def run_bot():
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    logger.info("Starting bot...")
    threading.Thread(target=run_webserver, daemon=True).start()
    asyncio.run(run_bot())
