"""Единая точка загрузки конфигурации из переменных окружения.

Все секреты берутся ТОЛЬКО из окружения. Хардкодить значения запрещено.
Для локальной разработки опционально подхватывается файл .env через python-dotenv.
"""

import os

# Локальная разработка: если установлен python-dotenv и рядом есть .env —
# подгружаем переменные. В проде (переменные заданы в окружении) это no-op.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv не обязателен в проде
    pass

# Секреты и настройки (только из окружения)
TG_TOKEN = os.environ.get("TG_TOKEN", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Модель OpenRouter — настраивается, по умолчанию текущая используемая модель.
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "openrouter/owl-alpha")

# Константа эндпоинта OpenRouter (не секрет).
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
