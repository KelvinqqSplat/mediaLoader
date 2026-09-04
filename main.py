import os
import logging
import threading
import asyncio
from fastapi import FastAPI
import uvicorn
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# === ТОКЕН из переменной окружения ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN not set")

# === Настройка логирования ===
logging.basicConfig(level=logging.INFO)

# === Команда /start ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Отправь мне ссылку на видео (YouTube, TikTok, Instagram и др.) – я скачаю его для тебя.")

# === Обработчик ссылок (заглушка, можно расширить) ===
async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    await update.message.reply_text(f"Получил ссылку: {url}\nСкачиваю... (пока заглушка)")

# === Создаём приложение ===
app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
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
    # держим бота активным
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    # Запускаем веб-сервер в фоновом потоке
    threading.Thread(target=run_webserver, daemon=True).start()
    # Запускаем бота в главном потоке
    asyncio.run(run_bot())
