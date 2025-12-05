#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
⚙️ КОНФИГУРАЦИЯ TELEGUARD BOT И АГЕНТОВ
Исправленная версия с .env поддержкой для Mistral API
"""

import logging
import os
from pathlib import Path
from dotenv import load_dotenv

# ============================================================================
# ЗАГРУЗКА .ENV (ПОСТОЯННОЕ ХРАНИЛИЩЕ КЛЮЧЕЙ)
# ============================================================================

# Загружаем .env файл если существует
ENV_FILE = Path(__file__).resolve().parent / ".env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)
else:
    # Создаем .env автоматически при первом запуске
    with open(ENV_FILE, "w") as f:
        f.write("# TeleGuard Bot Configuration\n")
        f.write("# Скопируй свой Mistral API ключ сюда:\n")
        f.write("MISTRAL_API_KEY=ygeDdoQrYFW5iM8aVw2p18pPZ1se30ow\n")

# ============================================================================
# TELEGRAM BOT
# ============================================================================

TELEGRAM_BOT_TOKEN = "8320009669:AAHadwhYKIg6qcwAwJabsBEOO7srfWwMiXE"
TELEGRAM_API_URL = "https://api.telegram.org"

# ============================================================================
# DATABASE - PostgreSQL
# ============================================================================

DB_USER = "tg_user"
DB_PASSWORD = "mnvm71"
DB_HOST = "localhost"
DB_PORT = 5432
DB_NAME = "teleguard"
POSTGRES_URL = "postgresql+psycopg2://tg_user:mnvm71@localhost:5432/teleguard?sslmode=disable"

# ============================================================================
# REDIS
# ============================================================================

REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0
REDIS_PASSWORD = None

def get_redis_config():
    """Возвращает конфигурацию для Redis"""
    return {
        "host": REDIS_HOST,
        "port": REDIS_PORT,
        "db": REDIS_DB,
        "decode_responses": True,
        "password": REDIS_PASSWORD
    }

# ============================================================================
# REDIS ОЧЕРЕДИ (QUEUES)
# ============================================================================

QUEUE_AGENT_1_INPUT = "queue:agent1:input"
QUEUE_AGENT_1_OUTPUT = "queue:agent1:output"

QUEUE_AGENT_2_INPUT = "queue:agent2:input"
QUEUE_AGENT_2_OUTPUT = "queue:agent2:output"

QUEUE_AGENT_3_INPUT = "queue:agent3:input"
QUEUE_AGENT_3_OUTPUT = "queue:agent3:output"

QUEUE_AGENT_4_INPUT = "queue:agent4:input"
QUEUE_AGENT_4_OUTPUT = "queue:agent4:output"

QUEUE_AGENT_5_INPUT = "queue:agent5:input"
QUEUE_AGENT_5_OUTPUT = "queue:agent5:output"

QUEUE_AGENT_6_INPUT = "queue:agent6:input"
QUEUE_AGENT_6_OUTPUT = "queue:agent6:output"

# ============================================================================
# MISTRAL AI (С ПОСТОЯННЫМ ХРАНИЛИЩЕМ)
# ============================================================================

# ✅ ЧИТАЕМ ИЗ .env (постоянно сохраняется)
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "ygeDdoQrYFW5iM8aVw2p18pPZ1se30ow")

MISTRAL_MODEL = "mistral-large-latest"

MISTRAL_GENERATION_PARAMS = {
    "temperature": 0.3,   # ✅ УВЕЛИЧЕНО: было 0.1 → менее консервативна
    "max_tokens": 600,    # ✅ УВЕЛИЧЕНО: было 300 → больше места для анализа
    "top_p": 0.95         # ✅ ОПТИМИЗИРОВАНО: было 0.9
}

# ============================================================================
# МОДЕРАТОРЫ
# ============================================================================

MODERATOR_IDS = [
    1621052774,  # Твой ID
]

# ============================================================================
# ПРАВИЛА ЧАТА (ПО УМОЛЧАНИЮ)
# ============================================================================

DEFAULT_RULES = [
    "1. Запрещен мат и нецензурная лексика",
    "2. Запрещены личные оскорбления и угрозы",
    "3. Запрещена реклама и спам",
    "4. Запрещена дискриминация по расовому, религиозному признаку",
    "5. Запрещены ссылки на вредоносные ресурсы",
    "6. Запрещены сексуальные/порнографические материалы",
    "7. Соблюдайте вежливость и уважение к другим участникам"
]

# ============================================================================
# ПОРТЫ АГЕНТОВ
# ============================================================================

AGENT_PORTS = {
    1: 8001,  # Агент 1 - NLP
    2: 8002,  # Агент 2 - Главный Mistral
    3: 8003,  # Агент 3 - Консервативный
    4: 8004,  # Агент 4 - Строгий
    5: 8005,  # Агент 5 - Арбитр
    6: 8006,  # Агент 6 - Медиа анализ
}

# ============================================================================
# ЛОГИРОВАНИЕ
# ============================================================================

LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

def setup_logging(name):
    """Настраивает логирование для модуля"""
    logger = logging.getLogger(name)
    logger.setLevel(LOG_LEVEL)
    
    handler = logging.StreamHandler()
    handler.setLevel(LOG_LEVEL)
    formatter = logging.Formatter(LOG_FORMAT)
    handler.setFormatter(formatter)
    
    if not logger.handlers:
        logger.addHandler(handler)
    
    return logger

# ============================================================================
# ПУТИ
# ============================================================================

BASE_DIR = Path(__file__).resolve().parent
LOGS_DIR = BASE_DIR / "logs"
DATA_DIR = BASE_DIR / "data"

LOGS_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

# ============================================================================
# ДРУГИЕ НАСТРОЙКИ
# ============================================================================

REQUEST_TIMEOUT = 30
MAX_MESSAGES_BATCH = 100
RETRY_ATTEMPTS = 3
RETRY_DELAY = 2

# ============================================================================
# ПРОВЕРКА КОНФИГУРАЦИИ
# ============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("⚙️ КОНФИГУРАЦИЯ TELEGUARD BOT v3.1")
    print("=" * 70)
    print(f"✅ Telegram Token: {'***' + TELEGRAM_BOT_TOKEN[-10:]}")
    print(f"✅ PostgreSQL: {DB_HOST}:{DB_PORT}/{DB_NAME}")
    print(f"✅ Redis: {REDIS_HOST}:{REDIS_PORT}")
    print(f"✅ Mistral API Key: {'✅ Установлен' if MISTRAL_API_KEY != 'your_mistral_key_here' else '❌ НЕ установлен'}")
    print(f"✅ Mistral Model: {MISTRAL_MODEL}")
    print(f"✅ Temperature: {MISTRAL_GENERATION_PARAMS['temperature']}")
    print(f"✅ Max Tokens: {MISTRAL_GENERATION_PARAMS['max_tokens']}")
    print(f"✅ Модераторы: {len(MODERATOR_IDS)} человек")
    print(f"✅ Правила: {len(DEFAULT_RULES)} правил")
    print(f"✅ Агенты: {len(AGENT_PORTS)} агентов")
    print(f"✅ .env файл: {ENV_FILE}")
    print("=" * 70)

# ============================================================================
# ОПРЕДЕЛЕНИЕ ДЕЙСТВИЯ МОДЕРАЦИИ
# ============================================================================

def determine_action(violation_type: str, severity: int, confidence: float) -> dict:
    """
    Определяет действие модерации по типу нарушения, серьезности и уверенности
    """
    actions = {
        "мат": {
            "low": {"action": "warn", "duration": 0, "severity": "low"},
            "medium": {"action": "mute", "duration": 60, "severity": "medium"},
            "high": {"action": "mute", "duration": 1440, "severity": "high"},
            "critical": {"action": "ban", "duration": 0, "severity": "critical"}
        },
        "оскорбление": {
            "low": {"action": "warn", "duration": 0, "severity": "low"},
            "medium": {"action": "mute", "duration": 720, "severity": "medium"},
            "high": {"action": "ban", "duration": 0, "severity": "high"},
            "critical": {"action": "ban", "duration": 0, "severity": "critical"}
        },
        "дискриминация": {
            "low": {"action": "warn", "duration": 0, "severity": "low"},
            "medium": {"action": "mute", "duration": 1440, "severity": "medium"},
            "high": {"action": "ban", "duration": 0, "severity": "high"},
            "critical": {"action": "ban", "duration": 0, "severity": "critical"}
        },
    }

    if severity >= 9:
        level = "critical"
    elif severity >= 7:
        level = "high"
    elif severity >= 5:
        level = "medium"
    else:
        level = "low"

    violation_actions = actions.get(violation_type, actions.get("оскорбление", {}))
    action_info = violation_actions.get(level, {"action": "none", "duration": 0, "severity": level})

    return {
        "action": action_info["action"],
        "duration": action_info["duration"],
        "reason": f"Нарушение: {violation_type} (уровень: {level})",
        "severity_level": level
    }
