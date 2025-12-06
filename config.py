#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
⚙️ КОНФИГУРАЦИЯ TELEGUARD BOT И АГЕНТОВ
Исправленная версия с get_db_connection_string()
"""

import logging
import os
from pathlib import Path
from dotenv import load_dotenv

# ============================================================================
# ЗАГРУЗКА .ENV (ПОСТОЯННОЕ ХРАНИЛИЩЕ КЛЮЧЕЙ)
# ============================================================================

ENV_FILE = Path(__file__).resolve().parent / ".env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)
else:
    with open(ENV_FILE, "w") as f:
        f.write("# TeleGuard Bot Configuration\n")
        f.write("MISTRAL_API_KEY=ygeDdoQrYFW5iM8aVw2p18pPZ1se30ow\n")

# ============================================================================
# TELEGRAM BOT
# ============================================================================

TELEGRAM_BOT_TOKEN = "8320009669:AAHadwhYKIg6qcwAwJabsBEOO7srfWwMiXE"
TELEGRAM_API_URL = "https://api.telegram.org"
TELEGRAM_API_BASE = "https://api.telegram.org"  # ← ДОБАВЛЕНО!

# ============================================================================
# DATABASE - PostgreSQL
# ============================================================================

DB_USER = "tg_user"
DB_PASSWORD = "mnvm71"
DB_HOST = "localhost"
DB_PORT = 5432
DB_NAME = "teleguard"
POSTGRES_URL = "postgresql+psycopg2://tg_user:mnvm71@localhost:5432/teleguard?sslmode=disable"

def get_db_connection_string():
    """Возвращает строку подключения к БД"""
    return POSTGRES_URL

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
# MISTRAL AI
# ============================================================================

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "ygeDdoQrYFW5iM8aVw2p18pPZ1se30ow")
MISTRAL_MODEL = "mistral-large-latest"

MISTRAL_GENERATION_PARAMS = {
    "temperature": 0.3,
    "max_tokens": 600,
    "top_p": 0.95
}

# ============================================================================
# МОДЕРАТОРЫ
# ============================================================================

MODERATOR_IDS = [1621052774]

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
    
    # Логирование в файл
    logs_dir = Path(__file__).resolve().parent / "logs"
    logs_dir.mkdir(exist_ok=True)
    
    log_file = logs_dir / f"{name.lower().replace(' ', '_')}.log"
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(LOG_LEVEL)
    
    # Логирование в консоль
    console_handler = logging.StreamHandler()
    console_handler.setLevel(LOG_LEVEL)
    
    formatter = logging.Formatter(LOG_FORMAT)
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    if not logger.handlers:
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
    
    return logger

# ============================================================================
# ПУТИ И ДИРЕКТОРИИ
# ============================================================================

BASE_DIR = Path(__file__).resolve().parent
LOGS_DIR = str(BASE_DIR / "logs")
DATA_DIR = str(BASE_DIR / "data")
DOWNLOADS_DIR = str(BASE_DIR / "downloads")

Path(LOGS_DIR).mkdir(exist_ok=True)
Path(DATA_DIR).mkdir(exist_ok=True)
Path(DOWNLOADS_DIR).mkdir(exist_ok=True)

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
    print("⚙️ КОНФИГУРАЦИЯ TELEGUARD BOT v3.2")
    print("=" * 70)
    print(f"✅ Telegram Token: {'***' + TELEGRAM_BOT_TOKEN[-10:]}")
    print(f"✅ Telegram API: {TELEGRAM_API_BASE}")
    print(f"✅ PostgreSQL: {DB_HOST}:{DB_PORT}/{DB_NAME}")
    print(f"✅ Redis: {REDIS_HOST}:{REDIS_PORT}")
    print(f"✅ Mistral API Key: {'✅ Установлен' if MISTRAL_API_KEY else '❌ НЕ установлен'}")
    print(f"✅ Mistral Model: {MISTRAL_MODEL}")
    print(f"✅ Температура: {MISTRAL_GENERATION_PARAMS['temperature']}")
    print(f"✅ Max Tokens: {MISTRAL_GENERATION_PARAMS['max_tokens']}")
    print(f"✅ Модераторы: {len(MODERATOR_IDS)}")
    print(f"✅ Агенты: {len(AGENT_PORTS)}")
    print(f"✅ Logs: {LOGS_DIR}")
    print(f"✅ Downloads: {DOWNLOADS_DIR}")
    print("=" * 70)
    print("✅ КОНФИГ ГОТОВ!")

# ============================================================================
# ОПРЕДЕЛЕНИЕ ДЕЙСТВИЯ МОДЕРАЦИИ
# ============================================================================

def determine_action(violation_type: str, severity: int, confidence: float) -> dict:
    """Определяет действие модерации по типу нарушения"""
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
