import telebot
from openai import OpenAI

# 1. Токены
TG_TOKEN = "8676093761:AAGPBnJpWDGYu42xaPQc4rZF3uY1dVRMrZ4"
DS_API_KEY = "om-4F6SWoUVHRv2dyKGy2uMq3rBNCrQ7RPYtuUMagu1"

# 2. Подключаем DeepSeek (совместим с OpenAI SDK)
client = OpenAI(api_key=DS_API_KEY, base_url="https://api.deepseek.com/v1")
bot = telebot.TeleBot(TG_TOKEN)

# 3. Обработка сообщений
@bot.message_handler(func=lambda msg: True)
def reply(message):
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",  # или "deepseek-reasoner" для M4 Flash
            messages=[{"role": "user", "content": message.text}]
        )
        bot.reply_to(message, response.choices[0].message.content)
    except Exception as e:
        bot.reply_to(message, f"Ошибка: {e}")

# 4. Запуск
bot.polling()
