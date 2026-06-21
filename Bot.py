import telebot
from openai import OpenAI
import os

# Берем токены из переменных окружения (безопасно)
TG_TOKEN = os.environ.get("8676093761:AAGPBnJpWDGYu42xaPQc4rZF3uY1dVRMrZ4")
DS_API_KEY = os.environ.get("om-4F6SWoUVHRv2dyKGy2uMq3rBNCrQ7RPYtuUMagu1")

if not TG_TOKEN or not DS_API_KEY:
    raise ValueError("Не найдены переменные окружения!")

client = OpenAI(api_key=DS_API_KEY, base_url="https://api.deepseek.com/v1")
bot = telebot.TeleBot(TG_TOKEN)

@bot.message_handler(func=lambda msg: True)
def reply(message):
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": message.text}]
        )
        bot.reply_to(message, response.choices[0].message.content)
    except Exception as e:
        bot.reply_to(message, f"Ошибка: {e}")

bot.polling()
