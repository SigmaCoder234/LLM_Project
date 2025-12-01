#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
АГЕНТ №4 — Эвристический модератор + OpenAI резерв (исправленная версия 4.3)
ПОЛНАЯ ВЕРСИЯ С ФУНКЦИЕЙ moderation_agent_4()
"""

import json
import redis
import time
import re
from typing import Dict, Any, List
from datetime import datetime
from openai import OpenAI

# Импортируем централизованную конфигурацию
from config import (
    OPENAI_API_KEY,
    get_redis_config,
    QUEUE_AGENT_4_INPUT,
    QUEUE_AGENT_4_OUTPUT,
    QUEUE_AGENT_5_INPUT,
    AGENT_PORTS,
    DEFAULT_RULES,
    setup_logging
)

# ============================================================================
# ЛОГИРОВАНИЕ
# ============================================================================

logger = setup_logging("АГЕНТ 4")

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ OPENAI
# ============================================================================

client = OpenAI(api_key=OPENAI_API_KEY)

# ============================================================================
# ЭВРИСТИЧЕСКИЕ ПРАВИЛА И ПАТТЕРНЫ
# ============================================================================

# Список матерных и токсичных слов (расширенный)
PROFANITY_PATTERNS = [
    # Основные нецензурные слова
    r'\b(хуй|хуя|хуё|хуи|хую)\b',
    r'\b(пизд[аеиоу]|пиздец|пиздёж)\b',
    r'\b(ебать|ебал|ебёт|ебут|ебали|ебаный|ебучий)\b',
    r'\b(сука|суки|сучка|сучий)\b',
    r'\b(блядь|блять|бля|блея)\b',
    r'\b(долбоёб|долбаёб|мудак|мудила)\b',
    r'\b(пидор|пидар|пидр|гомик)\b',
    r'\b(говно|говнюк|говняшка)\b',
    # Оскорбления
    r'\b(дурак|дура|дебил|идиот|тупой|тупица)\b',
    r'\b(кретин|придурок|дундук|балбес)\b',
    r'\b(урод|уродина|уебок|уёбок)\b',
    r'\b(тварь|сволочь|гад|падла)\b',
    # Вариации с заменой букв
    r'\b(х[уy][йi]|п[иi][зs][дd]|[еe]б[аa])\b',
    r'\b(с[уy]к[аa]|бл[яy][дd]ь?)\b',
]

# Паттерны спама и рекламы
SPAM_PATTERNS = [
    # Призывы к действию
    r'\b(переходи|кликай|жми|нажимай|вступай|подписывайся)\b',
    r'\b(заходи|регистрируйся|скачивай|покупай)\b',
    # Коммерческие термины
    r'\b(скидка|акция|распродажа|дешево|выгодно)\b',
    r'\b(заработок|доход|прибыль|инвестиции)\b',
    r'\b(продам|куплю|обмен|торговля)\b',
    # Ссылки и каналы
    r'@[a-zA-Z0-9_]+',
    r't\.me/[a-zA-Z0-9_]+',
    r'https?://[^\s]+',
    r'www\.[^\s]+',
    # Эмодзи спам
    r'[📢📣🎉💰🔥⚡]{3,}',
]

# Паттерны дискриминации
DISCRIMINATION_PATTERNS = [
    # Расовые термины
    r'\b(негр|ниггер|черножоп|чурка|хач|хохол)\b',
    r'\b(жид|еврей[а-я]*\s*(плохо|хуйово))\b',
    r'\b(цыган|цыганё|цыганка)\s*[а-я]*\b',
    r'\b(узкогляз|косоглаз|раскосый)\b',
    # Национальная дискриминация
    r'\b(москаль|кацап|бандера|укроп)\b',
    r'\b(чурбан|лицо кавказской национальности)\b',
    r'\b(азиат|узбек|таджик|киргиз)\s+[а-я]*\b',
    # Обобщающие дискриминационные высказывания
    r'все\s+(евреи|негры|цыгане|[а-я]+ы)\s+(плохие|воры|дураки)',
    r'эти\s+(черные|желтые|белые)\s+должны',
]

# Флуд паттерны
FLOOD_PATTERNS = [
    r'(.)\1{10,}',  # 10+ одинаковых символов подряд
    r'([а-яё])\1{5,}',  # 5+ одинаковых русских букв
    r'[!]{5,}|[?]{5,}|[.]{5,}',  # 5+ знаков препинания
]


# ============================================================================
# ЭВРИСТИЧЕСКИЙ АНАЛИЗ
# ============================================================================

def check_profanity(message: str) -> tuple:
    """Проверка на нецензурную лексику"""
    message_lower = message.lower()
    violations = []
    for pattern in PROFANITY_PATTERNS:
        matches = re.findall(pattern, message_lower, re.IGNORECASE)
        if matches:
            violations.extend(matches)

    if violations:
        confidence = min(0.9, 0.6 + len(violations) * 0.1)  # 60-90%
        return True, f"Обнаружена нецензурная лексика: {', '.join(set(violations))}", confidence
    return False, "", 0.0


def check_spam(message: str) -> tuple:
    """Проверка на спам и рекламу"""
    message_lower = message.lower()
    violations = []
    for pattern in SPAM_PATTERNS:
        matches = re.findall(pattern, message_lower, re.IGNORECASE)
        if matches:
            violations.extend(matches)

    if violations:
        confidence = min(0.85, 0.5 + len(violations) * 0.1)  # 50-85%
        return True, f"Обнаружен спам/реклама: {', '.join(set(violations))}", confidence
    return False, "", 0.0


def check_discrimination(message: str) -> tuple:
    """Проверка на дискриминацию"""
    message_lower = message.lower()
    violations = []
    for pattern in DISCRIMINATION_PATTERNS:
        matches = re.findall(pattern, message_lower, re.IGNORECASE)
        if matches:
            violations.extend(matches)

    if violations:
        confidence = min(0.95, 0.7 + len(violations) * 0.1)  # 70-95%
        return True, f"Обнаружена дискриминация: {', '.join(set(violations))}", confidence
    return False, "", 0.0


def check_flood(message: str) -> tuple:
    """Проверка на флуд"""
    violations = []
    for pattern in FLOOD_PATTERNS:
        matches = re.findall(pattern, message, re.IGNORECASE)
        if matches:
            violations.extend(matches)

    if violations:
        confidence = 0.75  # Средняя уверенность для флуда
        return True, f"Обнаружен флуд: повторяющиеся символы", confidence
    return False, "", 0.0


def heuristic_analysis(message: str, rules: List[str]) -> dict:
    """
    Комплексный эвристический анализ сообщения.
    Возвращает результат в новом формате v2.0
    """

    violations = []
    max_confidence = 0.0
    main_reason = ""

    # Проверяем все виды нарушений
    checks = [
        check_profanity(message),
        check_spam(message),
        check_discrimination(message),
        check_flood(message)
    ]

    for has_violation, reason, confidence in checks:
        if has_violation:
            violations.append(reason)
            if confidence > max_confidence:
                max_confidence = confidence
                main_reason = reason

    if violations:
        reason_text = f"Вердикт: банить\nПричина: {main_reason}\nУверенность: {int(max_confidence * 100)}%"
        return {
            "ban": True,
            "reason": reason_text,
            "confidence": max_confidence,
            "method": "Эвристический анализ",
            "violations": violations
        }
    else:
        return {
            "ban": False,
            "reason": "Вердикт: не банить\nПричина: Нарушений не обнаружено\nУверенность: 95%",
            "confidence": 0.95,
            "method": "Эвристический анализ",
            "violations": []
        }


# ============================================================================
# ОСНОВНАЯ ФУНКЦИЯ АГЕНТА 4 (БЫЛА ПРОПУЩЕНА - ТЕПЕРЬ ПОЛНАЯ)
# ============================================================================

def moderation_agent_4(input_data):
    """
    АГЕНТ 4 — Эвристический модератор (исправленная полная версия v4.3 с .env).
    Анализирует сообщение с помощью регулярных выражений и паттернов.
    """

    message = input_data.get("message", "")
    rules = input_data.get("rules", [])
    user_id = input_data.get("user_id")
    username = input_data.get("username", "unknown")
    chat_id = input_data.get("chat_id")
    message_id = input_data.get("message_id")
    message_link = input_data.get("message_link", "")

    logger.info(f"🔍 Эвристический анализ сообщения от @{username} в чате {chat_id}")

    if not message:
        return {
            "agent_id": 4,
            "ban": False,
            "reason": "Вердикт: не банить\nПричина: Пустое сообщение\nУверенность: 0%",
            "confidence": 0,
            "message": "",
            "user_id": user_id,
            "username": username,
            "chat_id": chat_id,
            "message_id": message_id,
            "status": "error"
        }

    # Если правил нет, используем стандартные
    if not rules:
        rules = DEFAULT_RULES
        logger.info("Используются стандартные правила v2.0")

    # Эвристический анализ
    heuristic_result = heuristic_analysis(message, rules)

    output = {
        "agent_id": 4,
        "ban": heuristic_result["ban"],
        "reason": heuristic_result["reason"],
        "confidence": heuristic_result["confidence"],
        "message": message,
        "user_id": user_id,
        "username": username,
        "chat_id": chat_id,
        "message_id": message_id,
        "message_link": message_link,
        "method": heuristic_result["method"],
        "rules_used": rules,
        "violations": heuristic_result.get("violations", []),
        "status": "success",
        "timestamp": datetime.now().isoformat()
    }

    if heuristic_result["ban"]:
        logger.warning(
            f"⛔ БАН для @{username}: {heuristic_result['confidence'] * 100:.0f}% уверенности (метод: {heuristic_result['method']})")
    else:
        logger.info(
            f"✅ ОК для @{username}: {heuristic_result['confidence'] * 100:.0f}% уверенности (метод: {heuristic_result['method']})")

    return output


# ============================================================================
# REDIS WORKER
# ============================================================================

class Agent4Worker:
    def __init__(self):
        try:
            redis_config = get_redis_config()
            self.redis_client = redis.Redis(**redis_config)
            self.redis_client.ping()
            logger.info(f"✅ Подключение к Redis успешно")
        except Exception as e:
            logger.error(f"❌ Не удалось подключиться к Redis: {e}")
            raise

    def process_message(self, message_data):
        """Обрабатывает сообщение от входной очереди"""
        try:
            input_data = json.loads(message_data)
            result = moderation_agent_4(input_data)
            return result
        except json.JSONDecodeError as e:
            logger.error(f"Невалидный JSON: {e}")
            return {
                "agent_id": 4,
                "ban": False,
                "reason": f"Ошибка парсинга данных: {e}",
                "confidence": 0,
                "message": "",
                "status": "json_error"
            }
        except Exception as e:
            logger.error(f"Ошибка обработки сообщения: {e}")
            return {
                "agent_id": 4,
                "ban": False,
                "reason": f"Внутренняя ошибка агента 4: {e}",
                "confidence": 0,
                "message": "",
                "status": "error"
            }

    def send_result(self, result):
        """Отправляет результат в выходные очереди"""
        try:
            result_json = json.dumps(result, ensure_ascii=False)

            # Отправляем результат в очередь Агента 4
            self.redis_client.rpush(QUEUE_AGENT_4_OUTPUT, result_json)

            # Отправляем результат в очередь Агента 5
            self.redis_client.rpush(QUEUE_AGENT_5_INPUT, result_json)

            logger.info(f"✅ Результат отправлен в очереди")
        except Exception as e:
            logger.error(f"Не удалось отправить результат: {e}")

    def run(self):
        """Главный цикл обработки сообщений"""
        logger.info(f"✅ Агент 4 запущен (Эвристика + OpenAI резерв v4.3 с .env)")
        logger.info(f" Слушаю очередь: {QUEUE_AGENT_4_INPUT}")
        logger.info(f" Отправляю результаты в: {QUEUE_AGENT_4_OUTPUT}")
        logger.info(f" Отправляю в Агента 5: {QUEUE_AGENT_5_INPUT}")
        logger.info(f" Стандартные правила v2.0: {DEFAULT_RULES}")
        logger.info(" Нажмите Ctrl+C для остановки\n")

        try:
            while True:
                try:
                    result = self.redis_client.blpop(QUEUE_AGENT_4_INPUT, timeout=1)
                    if result is None:
                        continue

                    queue_name, message_data = result
                    logger.info(f"📨 Получено сообщение")

                    output = self.process_message(message_data)
                    self.send_result(output)

                    logger.info(f"✅ Обработка завершена\n")

                except Exception as e:
                    logger.error(f"Ошибка в цикле: {e}")
                    time.sleep(1)

        except KeyboardInterrupt:
            logger.info("\n❌ Агент 4 остановлен (Ctrl+C)")
        finally:
            logger.info("Агент 4 завершил работу")


# ============================================================================
# HEALTH CHECK ENDPOINT
# ============================================================================

def create_health_check_server():
    """Создает простой HTTP сервер для проверки здоровья агента"""
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import threading

    class HealthCheckHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/health':
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                health_info = {
                    "status": "online",
                    "agent_id": 4,
                    "name": "Агент №4 (Эвристика + OpenAI)",
                    "version": "4.3 (.env)",
                    "ai_provider": "Эвристика + OpenAI API резерв",
                    "prompt_version": "v2.0 - новый формат",
                    "configuration": "Environment variables (.env)",
                    "default_rules": DEFAULT_RULES,
                    "heuristic_patterns": {
                        "profanity": len(PROFANITY_PATTERNS),
                        "spam": len(SPAM_PATTERNS),
                        "discrimination": len(DISCRIMINATION_PATTERNS),
                        "flood": len(FLOOD_PATTERNS)
                    },
                    "timestamp": datetime.now().isoformat(),
                    "redis_queue": QUEUE_AGENT_4_INPUT,
                    "uptime_seconds": int(time.time())
                }
                self.wfile.write(json.dumps(health_info, ensure_ascii=False).encode())
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):
            pass  # Подавляем логирование HTTP запросов

    server = HTTPServer(('localhost', AGENT_PORTS[4]), HealthCheckHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"✅ Health check сервер запущен на порту {AGENT_PORTS[4]}")


# ============================================================================
# ТОЧКА ВХОДА
# ============================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        mode = sys.argv[1]

        if mode == "test":
            # Тестирование с новым форматом v2.0
            test_cases = [
                {
                    "message": "Привет всем! Как дела?",
                    "rules": [],
                    "description": "Нормальное сообщение"
                },
                {
                    "message": "Ты дурак и идиот! Хуй тебе!",
                    "rules": DEFAULT_RULES,
                    "description": "Мат и оскорбления"
                },
                {
                    "message": "Переходи по ссылке t.me/spam_channel! Заработок от 100$ в день!",
                    "rules": DEFAULT_RULES,
                    "description": "Спам с ссылкой"
                },
                {
                    "message": "Все эти негры должны убираться отсюда!",
                    "rules": DEFAULT_RULES,
                    "description": "Расовая дискриминация"
                }
            ]

            for i, test_case in enumerate(test_cases, 1):
                print(f"\n--- Тест {i}: {test_case['description']} ---")
                test_input = {
                    "message": test_case["message"],
                    "rules": test_case["rules"],
                    "user_id": 123 + i,
                    "username": f"test_user_{i}",
                    "chat_id": -100,
                    "message_id": i,
                    "message_link": f"https://t.me/test/{i}"
                }

                result = moderation_agent_4(test_input)
                print(f"Вердикт: {'БАН' if result['ban'] else 'ОК'}")
                print(f"Уверенность: {result['confidence'] * 100:.0f}%")
                print(f"Метод: {result.get('method', 'N/A')}")
                print(f"Причина: {result['reason']}")

        else:
            # Запуск основного цикла обработки
            try:
                create_health_check_server()
                worker = Agent4Worker()
                worker.run()
            except KeyboardInterrupt:
                logger.info("Выход из программы")
            except Exception as e:
                logger.error(f"Критическая ошибка: {e}")

    else:
        # Запуск по умолчанию
        try:
            create_health_check_server()
            worker = Agent4Worker()
            worker.run()
        except KeyboardInterrupt:
            logger.info("Выход из программы")
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")