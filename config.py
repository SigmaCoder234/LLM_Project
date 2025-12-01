#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TeleGuard - Универсальная конфигурация (поддержка OpenAI + Mistral AI)
"""

import os
import logging
from datetime import timezone, timedelta
from dotenv import load_dotenv

# Загружаем переменные из .env файла
load_dotenv()


# ============================================================================
# ФУНКЦИИ ВСПОМОГАТЕЛЬНЫЕ
# ============================================================================
def get_env_bool(key: str, default: bool = False) -> bool:
    """Получить boolean значение из переменной окружения"""
    value = os.getenv(key, str(default)).lower()
    return value in ('true', '1', 'yes', 'on')


def get_env_int(key: str, default: int = 0) -> int:
    """Получить integer значение из переменной окружения"""
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


# ============================================================================
# AI PROVIDER DETECTION (АВТООПРЕДЕЛЕНИЕ)
# ============================================================================
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
MISTRAL_API_KEY = os.getenv('MISTRAL_API_KEY')
AI_PROVIDER = os.getenv('AI_PROVIDER', 'auto').lower()

# Автоматическое определение провайдера
if AI_PROVIDER == 'auto':
    if OPENAI_API_KEY:
        AI_PROVIDER = 'openai'
        logger_msg = "🤖 Автоопределение: найден OPENAI_API_KEY, используем OpenAI"
    elif MISTRAL_API_KEY:
        AI_PROVIDER = 'mistral'
        logger_msg = "🤖 Автоопределение: найден MISTRAL_API_KEY, используем Mistral AI"
    else:
        raise ValueError("❌ Не найдены API ключи! Добавьте OPENAI_API_KEY или MISTRAL_API_KEY в .env файл")
else:
    logger_msg = f"🤖 Ручная настройка: AI_PROVIDER={AI_PROVIDER}"

# Проверяем, что есть нужный ключ
if AI_PROVIDER == 'openai' and not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY не найден в переменных окружения! Проверьте .env файл")
elif AI_PROVIDER == 'mistral' and not MISTRAL_API_KEY:
    raise ValueError("MISTRAL_API_KEY не найден в переменных окружения! Проверьте .env файл")

# ============================================================================
# МОДЕЛИ И ПАРАМЕТРЫ
# ============================================================================
if AI_PROVIDER == 'openai':
    DEFAULT_MODEL = 'gpt-3.5-turbo'
    API_KEY = OPENAI_API_KEY
    CURRENT_MODEL = os.getenv('OPENAI_MODEL', DEFAULT_MODEL)
elif AI_PROVIDER == 'mistral':
    DEFAULT_MODEL = 'mistral-large-latest'
    API_KEY = MISTRAL_API_KEY
    CURRENT_MODEL = os.getenv('MISTRAL_MODEL', DEFAULT_MODEL)

# ============================================================================
# TELEGRAM BOT CONFIGURATION
# ============================================================================
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_API_URL = "https://api.telegram.org/bot"

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не найден в переменных окружения! Проверьте .env файл")

# ============================================================================
# DATABASE CONFIGURATION
# ============================================================================
POSTGRES_URL = os.getenv('POSTGRES_URL')
POSTGRES_HOST = os.getenv('POSTGRES_HOST', 'localhost')
POSTGRES_PORT = get_env_int('POSTGRES_PORT', 5432)
POSTGRES_USER = os.getenv('POSTGRES_USER', 'postgres')
POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD', '')
POSTGRES_DB = os.getenv('POSTGRES_DB', 'teleguard_db')

if not POSTGRES_URL:
    raise ValueError("POSTGRES_URL не найден в переменных окружения! Проверьте .env файл")

# ============================================================================
# REDIS CONFIGURATION
# ============================================================================
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = get_env_int('REDIS_PORT', 6379)
REDIS_DB = get_env_int('REDIS_DB', 0)
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', None)

# Если пароль пустая строка, делаем None
if REDIS_PASSWORD == '':
    REDIS_PASSWORD = None

# ============================================================================
# APPLICATION CONFIGURATION
# ============================================================================
DEBUG = get_env_bool('DEBUG', False)
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()

# ============================================================================
# TIMEZONE CONFIGURATION
# ============================================================================
TIMEZONE_NAME = os.getenv('TIMEZONE', 'Europe/Moscow')

# Московское время (MSK = UTC+3)
MSK_TIMEZONE = timezone(timedelta(hours=3))

# ============================================================================
# QUEUE NAMES (Redis)
# ============================================================================
QUEUE_AGENT_1_INPUT = "queue:agent1:input"
QUEUE_AGENT_2_INPUT = "queue:agent2:input"
QUEUE_AGENT_3_INPUT = "queue:agent3:input"
QUEUE_AGENT_3_OUTPUT = "queue:agent3:output"
QUEUE_AGENT_4_INPUT = "queue:agent4:input"
QUEUE_AGENT_4_OUTPUT = "queue:agent4:output"
QUEUE_AGENT_5_INPUT = "queue:agent5:input"

# ============================================================================
# DEFAULT VALUES
# ============================================================================
DEFAULT_RULES = [
    "Запрещена расовая дискриминация",
    "Запрещены ссылки",
    "Запрещена нецензурная лексика и оскорбления",
    "Запрещены угрозы и призывы к насилию"
]

# ============================================================================
# AGENT PORTS
# ============================================================================
AGENT_PORTS = {
    1: 8001,
    2: 8002,
    3: 8003,
    4: 8004,
    5: 8005
}

# ============================================================================
# AI SPECIFIC CONFIGURATION
# ============================================================================
if AI_PROVIDER == 'openai':
    OPENAI_MODEL = CURRENT_MODEL
    OPENAI_GENERATION_PARAMS = {
        "temperature": 0.1,
        "max_tokens": 300
    }
    OPENAI_API_KEY = API_KEY

elif AI_PROVIDER == 'mistral':
    MISTRAL_MODEL = CURRENT_MODEL
    MISTRAL_API_BASE = "https://api.mistral.ai/v1"
    MISTRAL_SUPPORTED_MODELS = [
        "mistral-large-latest",
        "mistral-medium-latest",
        "mistral-small-latest",
        "open-mistral-7b",
        "open-mistral-8x7b",
        "open-mistral-8x22b"
    ]

    MISTRAL_GENERATION_PARAMS = {
        "temperature": 0.1,
        "max_tokens": 300,
        "top_p": 0.9,
        "safe_mode": False
    }
    MISTRAL_API_KEY = API_KEY


# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================
def setup_logging(agent_name: str = "SYSTEM"):
    """Настройка логирования для агента"""
    numeric_level = getattr(logging, LOG_LEVEL, logging.INFO)

    logging.basicConfig(
        level=numeric_level,
        format=f'[%(asctime)s] [{agent_name}] %(levelname)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    if not DEBUG:
        logging.getLogger('httpx').setLevel(logging.WARNING)
        logging.getLogger('openai').setLevel(logging.WARNING)
        logging.getLogger('mistralai').setLevel(logging.WARNING)
        logging.getLogger('requests').setLevel(logging.WARNING)
        logging.getLogger('urllib3').setLevel(logging.WARNING)

    return logging.getLogger(agent_name)


# ============================================================================
# VALIDATION
# ============================================================================
def validate_config():
    """Проверка корректности конфигурации"""
    errors = []

    if AI_PROVIDER == 'openai':
        if not OPENAI_API_KEY:
            errors.append("OPENAI_API_KEY обязателен для OpenAI провайдера")
        elif len(OPENAI_API_KEY) < 20:
            errors.append("OPENAI_API_KEY кажется слишком коротким")

    elif AI_PROVIDER == 'mistral':
        if not MISTRAL_API_KEY:
            errors.append("MISTRAL_API_KEY обязателен для Mistral AI провайдера")
        elif len(MISTRAL_API_KEY) < 20:
            errors.append("MISTRAL_API_KEY кажется слишком коротким")

    if not TELEGRAM_BOT_TOKEN:
        errors.append("TELEGRAM_BOT_TOKEN обязателен")
    elif ':' not in TELEGRAM_BOT_TOKEN:
        errors.append("TELEGRAM_BOT_TOKEN имеет неверный формат")

    if not POSTGRES_URL:
        errors.append("POSTGRES_URL обязателен")

    if not (1 <= REDIS_PORT <= 65535):
        errors.append(f"REDIS_PORT должен быть в диапазоне 1-65535, получен: {REDIS_PORT}")

    if not (1 <= POSTGRES_PORT <= 65535):
        errors.append(f"POSTGRES_PORT должен быть в диапазоне 1-65535, получен: {POSTGRES_PORT}")

    if errors:
        raise ValueError("Ошибки конфигурации:\n" + "\n".join(f"- {error}" for error in errors))

    return True


# ============================================================================
# REDIS CONNECTION CONFIG
# ============================================================================
def get_redis_config():
    """Получить конфигурацию для подключения к Redis"""
    return {
        "host": REDIS_HOST,
        "port": REDIS_PORT,
        "db": REDIS_DB,
        "password": REDIS_PASSWORD,
        "decode_responses": True
    }


# ============================================================================
# AI CLIENT CONFIG
# ============================================================================
def get_ai_config():
    """Получить конфигурацию для ИИ клиента"""
    if AI_PROVIDER == 'openai':
        return {
            "provider": "openai",
            "api_key": OPENAI_API_KEY,
            "model": OPENAI_MODEL,
            "generation_params": OPENAI_GENERATION_PARAMS
        }
    elif AI_PROVIDER == 'mistral':
        return {
            "provider": "mistral",
            "api_key": MISTRAL_API_KEY,
            "endpoint": MISTRAL_API_BASE,
            "model": MISTRAL_MODEL,
            "generation_params": MISTRAL_GENERATION_PARAMS
        }


# ============================================================================
# CONFIG SUMMARY
# ============================================================================
def get_config_summary():
    """Получить сводку конфигурации (без секретных данных)"""
    return {
        "ai_provider": AI_PROVIDER,
        "ai_model": CURRENT_MODEL,
        "ai_configured": bool(API_KEY),
        "telegram_configured": bool(TELEGRAM_BOT_TOKEN),
        "postgres_host": POSTGRES_HOST,
        "postgres_port": POSTGRES_PORT,
        "postgres_db": POSTGRES_DB,
        "redis_host": REDIS_HOST,
        "redis_port": REDIS_PORT,
        "redis_db": REDIS_DB,
        "debug": DEBUG,
        "log_level": LOG_LEVEL,
        "timezone": TIMEZONE_NAME,
        "agent_ports": AGENT_PORTS,
        "default_rules": DEFAULT_RULES
    }


# ============================================================================
# ИНИЦИАЛИЗАЦИЯ
# ============================================================================
try:
    validate_config()
except ValueError as e:
    print(f"❌ Ошибка конфигурации: {e}")
    exit(1)

logger = setup_logging("CONFIG")
logger.info(f"✅ Конфигурация загружена: {AI_PROVIDER.upper()} ({CURRENT_MODEL})")
print(logger_msg)

if DEBUG:
    logger.debug("🔧 Режим отладки включен")
    logger.debug(f"📊 Сводка конфигурации: {get_config_summary()}")

# ============================================================================
# ЭКСПОРТИРУЕМЫЕ ПЕРЕМЕННЫЕ
# ============================================================================
__all__ = [
    'AI_PROVIDER',
    'API_KEY',
    'CURRENT_MODEL',
    'OPENAI_API_KEY',
    'OPENAI_MODEL',
    'OPENAI_GENERATION_PARAMS',
    'MISTRAL_API_KEY',
    'MISTRAL_MODEL',
    'MISTRAL_API_BASE',
    'MISTRAL_GENERATION_PARAMS',
    'TELEGRAM_BOT_TOKEN',
    'TELEGRAM_API_URL',
    'POSTGRES_URL',
    'POSTGRES_HOST',
    'POSTGRES_PORT',
    'POSTGRES_USER',
    'POSTGRES_PASSWORD',
    'POSTGRES_DB',
    'REDIS_HOST',
    'REDIS_PORT',
    'REDIS_DB',
    'REDIS_PASSWORD',
    'DEBUG',
    'LOG_LEVEL',
    'MSK_TIMEZONE',
    'DEFAULT_RULES',
    'AGENT_PORTS',
    'QUEUE_AGENT_1_INPUT',
    'QUEUE_AGENT_2_INPUT',
    'QUEUE_AGENT_3_INPUT',
    'QUEUE_AGENT_3_OUTPUT',
    'QUEUE_AGENT_4_INPUT',
    'QUEUE_AGENT_4_OUTPUT',
    'QUEUE_AGENT_5_INPUT',
    'setup_logging',
    'validate_config',
    'get_redis_config',
    'get_ai_config',
    'get_config_summary'
]

# ============================================================================
# ТОЧКА ВХОДА (если запускается как скрипт)
# ============================================================================
if __name__ == "__main__":
    print("\n🤖 TeleGuard - Универсальная конфигурация")
    print("=" * 50)
    print(f"🧠 ИИ провайдер: {AI_PROVIDER.upper()}")
    print(f"🔧 Модель: {CURRENT_MODEL}")
    print(f"🔑 API ключ: {'✅ Найден' if API_KEY else '❌ Отсутствует'}")
    print(f"📱 Telegram токен: {'✅ Найден' if TELEGRAM_BOT_TOKEN else '❌ Отсутствует'}")
    print(f"🗄️ PostgreSQL: {'✅ Настроен' if POSTGRES_URL else '❌ Не настроен'}")
    print(f"📡 Redis: {REDIS_HOST}:{REDIS_PORT}")
    print(f"🕐 Часовой пояс: {TIMEZONE_NAME}")
    print(f"🔧 Режим отладки: {'✅ Включен' if DEBUG else '❌ Выключен'}")
    print("\n✅ Конфигурация валидна!")

    summary = get_config_summary()
    print(f"\n📊 Сводка: {summary}")
