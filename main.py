import os
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

# === Токен и настройки ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN not set")

logging.basicConfig(level=logging.INFO)

# === База данных (SQLite) для подписок ===
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

def get_user(user_id):
    cursor.execute("SELECT is_subscribed, subscribed_until FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    if row:
        return {"subscribed": bool(row[0]), "until": row[1]}
    return None

def set_subscription(user_id, days):
    until = (datetime.now() + timedelta(days=days)).isoformat()
    cursor.execute("INSERT OR REPLACE INTO users (user_id, is_subscribed, subscribed_until) VALUES (?, 1, ?)", (user_id, until))
    conn.commit()

def is_subscribed(user_id):
    data = get_user(user_id)
    if not data or not data["subscribed"]:
        return False
    if data["until"] and datetime.fromisoformat(data["until"]) < datetime.now():
        # истекло
        cursor.execute("UPDATE users SET is_subscribed=0 WHERE user_id=?", (user_id,))
        conn.commit()
        return False
    return True

# === Команды ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = []
    if is_subscribed(user_id):
        keyboard.append([InlineKeyboardButton("✅ Подписка активна", callback_data="sub_info")])
    else:
        keyboard.append([InlineKeyboardButton("💎 Оформить подписку (30 дней, 100 ₽)", callback_data="buy_sub")])
    keyboard.append([InlineKeyboardButton("📥 Отправить ссылку", callback_data="send_link")])
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
    # Здесь можно вставить реальную оплату (через Telegram Stars или внешний платёж)
    set_subscription(user_id, 30)
    await query.edit_message_text("🎉 Подписка оформлена на 30 дней! Реклама отключена.")

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    url = update.message.text.strip()
    if not url.startswith(("http://", "https://")):
        await update.message.reply_text("❌ Это не похоже на ссылку. Отправь корректный URL.")
        return
    
    status_msg = await update.message.reply_text("⏳ Начинаю загрузку...")
    
    # Параметры скачивания
    ydl_opts = {
        "format": "best[height<=720]",
        "outtmpl": "downloads/%(title)s.%(ext)s",
        "quiet": True,
        "no_warnings": True,
        "impersonate": "chrome-131",
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
            # Отправляем видео или аудио
            if info.get("ext") in ["mp4", "webm", "mov"]:
                await update.message.reply_video(video=open(file_path, "rb"))
            else:
                await update.message.reply_document(document=open(file_path, "rb"))
            # Показываем рекламу, если нет подписки
            if not is_subscribed(user_id):
                await update.message.reply_text(
                    "💬 Хотите убрать рекламу и скачивать без ограничений? Оформите подписку через /start."
                )
            os.remove(file_path)
    except Exception as e:
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
    if not os.path.exists("downloads"):
        os.makedirs("downloads")
    threading.Thread(target=run_webserver, daemon=True).start()
    asyncio.run(run_bot())
