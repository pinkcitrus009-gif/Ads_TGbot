import requests
from collections import defaultdict
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

import config

TOKEN = config.TG_TOKEN
OPENROUTER_API_KEY = config.OPENROUTER_API_KEY
OPENROUTER_URL = config.OPENROUTER_URL
MAX_HISTORY = 20

chat_histories = defaultdict(list)

def split_message(text: str, max_len: int = 4000) -> list:
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        split_idx = text.rfind('\n\n', 0, max_len)
        if split_idx == -1:
            split_idx = text.rfind('. ', 0, max_len)
        if split_idx == -1:
            split_idx = max_len
        chunks.append(text[:split_idx].strip())
        text = text[split_idx:].strip()
    return chunks

SYSTEM_PROMPT = """Ты — Dungeon Master для D&D 2024. Отвечай только на русском, ярко и образно, как рассказчик. Не используй звёздочки, подчёркивания, решётки — только текст и эмодзи.

Статус (по команде /status) выдавай в формате:
⚔️ Имя (Раса • Класс • Уровень)
❤️ HP: X/Y
🛡️ КД: Z
⭐ Опыт: A/B
💰 Золото: C зм
💪 Сила: X (+N)
🏃 Ловкость: X (+N)
🧱 Телосложение: X (+N)
🧠 Интеллект: X (+N)
🔭 Мудрость: X (+N)
✨ Харизма: X (+N)
🎒 Инвентарь: предметы
🔮 Способности: способности

В обычных ответах — только история, приключение, диалоги. Никаких технических деталей и правил. Ты — весёлый, опытный мастер."""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    chat_histories[chat_id].clear()
    await update.message.reply_text(
        "🐉 Привет! Я твой DM. Напиши, кем хочешь быть, или просто начни игру.\n\n"
        "📋 /status — лист персонажа\n"
        "🗑 /reset — начать заново"
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    if not chat_histories[chat_id]:
        await update.message.reply_text("⚠️ Сначала создай персонажа через /start")
        return
    chat_histories[chat_id].append({"role": "user", "content": "Покажи лист персонажа"})
    await update.message.chat.send_action("typing")
    try:
        headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
        data = {
            "model": config.OPENROUTER_MODEL,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + chat_histories[chat_id],
            "max_tokens": 700,
            "temperature": 0.8
        }
        response = requests.post(OPENROUTER_URL, headers=headers, json=data, timeout=60)
        response.raise_for_status()
        reply_text = response.json()["choices"][0]["message"]["content"]
        chat_histories[chat_id].append({"role": "assistant", "content": reply_text})
        for chunk in split_message(reply_text):
            await update.message.reply_text(chunk)
    except Exception as e:
        chat_histories[chat_id].pop()
        await update.message.reply_text(f"❌ Ошибка: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    user_text = update.message.text

    chat_histories[chat_id].append({"role": "user", "content": user_text})
    if len(chat_histories[chat_id]) > MAX_HISTORY:
        chat_histories[chat_id] = chat_histories[chat_id][-MAX_HISTORY:]

    await update.message.chat.send_action("typing")
    try:
        headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
        data = {
            "model": config.OPENROUTER_MODEL,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + chat_histories[chat_id],
            "max_tokens": 500,
            "temperature": 0.9
        }
        response = requests.post(OPENROUTER_URL, headers=headers, json=data, timeout=60)
        response.raise_for_status()
        reply_text = response.json()["choices"][0]["message"]["content"]
        chat_histories[chat_id].append({"role": "assistant", "content": reply_text})
        for chunk in split_message(reply_text):
            await update.message.reply_text(chunk)
    except Exception as e:
        chat_histories[chat_id].pop()
        await update.message.reply_text(f"❌ Ошибка: {e}")

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    chat_histories[chat_id].clear()
    await update.message.reply_text("🗑 Начинаем заново!")

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
