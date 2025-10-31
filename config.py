#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TeleGuard - Централизованная конфигурация через переменные окружения (Mistral AI версия)
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
# MISTRAL AI CONFIGURATION
# ============================================================================
MISTRAL_API_KEY = os.getenv('MISTRAL_API_KEY')
MISTRAL_MODEL = os.getenv('MISTRAL_MODEL', 'mistral-large-latest')
AI_PROVIDER = os.getenv('AI_PROVIDER', 'mistral')

if not MISTRAL_API_KEY:
    raise ValueError("MISTRAL_API_KEY не найден в переменных окружения! Проверьте .env файл")

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
    "Запрещены ссылки"
]

# ============================================================================
# AGENT PORTS
# ============================================================================
AGENT_PORTS = {
    1: 8001,  # Координатор
    2: 8002,  # Анализатор
    3: 8003,  # Mistral модератор
    4: 8004,  # Эвристический + Mistral
    5: 8005   # Арбитр
}

# ============================================================================
# MISTRAL AI SPECIFIC CONFIGURATION
# ============================================================================
MISTRAL_API_BASE = "https://api.mistral.ai/v1"
MISTRAL_SUPPORTED_MODELS = [
    "mistral-large-latest",
    "mistral-medium-latest", 
    "mistral-small-latest",
    "open-mistral-7b",
    "open-mistral-8x7b",
    "open-mistral-8x22b"
]

# Параметры генерации для Mistral
MISTRAL_GENERATION_PARAMS = {
    "temperature": 0.1,
    "max_tokens": 300,
    "top_p": 0.9,
    "safe_mode": False  # Отключаем safe mode для модерации
}

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
    
    # Подавляем избыточные логи от внешних библиотек
    if not DEBUG:
        logging.getLogger('httpx').setLevel(logging.WARNING)
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
    
    # Проверяем обязательные переменные
    if not MISTRAL_API_KEY:
        errors.append("MISTRAL_API_KEY обязателен")
    
    if not TELEGRAM_BOT_TOKEN:
        errors.append("TELEGRAM_BOT_TOKEN обязателен")
    
    if not POSTGRES_URL:
        errors.append("POSTGRES_URL обязателен")
    
    # Проверяем формат токенов
    if MISTRAL_API_KEY and len(MISTRAL_API_KEY) < 20:
        errors.append("MISTRAL_API_KEY кажется слишком коротким")
    
    if TELEGRAM_BOT_TOKEN and ':' not in TELEGRAM_BOT_TOKEN:
        errors.append("TELEGRAM_BOT_TOKEN имеет неверный формат")
    
    # Проверяем модель Mistral
    if MISTRAL_MODEL not in MISTRAL_SUPPORTED_MODELS:
        errors.append(f"MISTRAL_MODEL '{MISTRAL_MODEL}' не поддерживается. Доступные: {MISTRAL_SUPPORTED_MODELS}")
    
    # Проверяем порты
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
# MISTRAL CLIENT CONFIG
# ============================================================================
def get_mistral_config():
    """Получить конфигурацию для Mistral AI клиента"""
    return {
        "api_key": MISTRAL_API_KEY,
        "endpoint": MISTRAL_API_BASE,
        "model": MISTRAL_MODEL,
        "generation_params": MISTRAL_GENERATION_PARAMS
    }

# ============================================================================
# ЭКСПОРТ КОНФИГУРАЦИИ
# ============================================================================
def get_config_summary():
    """Получить сводку конфигурации (без секретных данных)"""
    return {
        "ai_provider": AI_PROVIDER,
        "mistral_configured": bool(MISTRAL_API_KEY),
        "mistral_model": MISTRAL_MODEL,
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
# Проверяем конфигурацию при импорте
try:
    validate_config()
except ValueError as e:
    print(f"❌ Ошибка конфигурации: {e}")
    exit(1)

# Настраиваем базовое логирование
logger = setup_logging("CONFIG")
logger.info("✅ Конфигурация Mistral AI загружена успешно")

if DEBUG:
    logger.debug("🔧 Режим отладки включен")
    logger.debug(f"📊 Сводка конфигурации: {get_config_summary()}")

# ============================================================================
# ЭКСПОРТИРУЕМЫЕ ПЕРЕМЕННЫЕ
# ============================================================================
__all__ = [
    # AI API Keys
    'MISTRAL_API_KEY',
    'MISTRAL_MODEL',
    'MISTRAL_API_BASE',
    'MISTRAL_GENERATION_PARAMS',
    'AI_PROVIDER',
    
    # Telegram
    'TELEGRAM_BOT_TOKEN',
    'TELEGRAM_API_URL',
    
    # Database
    'POSTGRES_URL',
    'POSTGRES_HOST',
    'POSTGRES_PORT', 
    'POSTGRES_USER',
    'POSTGRES_PASSWORD',
    'POSTGRES_DB',
    
    # Redis
    'REDIS_HOST',
    'REDIS_PORT',
    'REDIS_DB',
    'REDIS_PASSWORD',
    
    # Application
    'DEBUG',
    'LOG_LEVEL',
    'MSK_TIMEZONE',
    'DEFAULT_RULES',
    'AGENT_PORTS',
    
    # Queues
    'QUEUE_AGENT_1_INPUT',
    'QUEUE_AGENT_2_INPUT',
    'QUEUE_AGENT_3_INPUT',
    'QUEUE_AGENT_3_OUTPUT',
    'QUEUE_AGENT_4_INPUT',
    'QUEUE_AGENT_4_OUTPUT',
    'QUEUE_AGENT_5_INPUT',
    
    # Functions
    'setup_logging',
    'validate_config',
    'get_redis_config',
    'get_mistral_config',
    'get_config_summary'
]