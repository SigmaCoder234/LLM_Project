#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
АГЕНТ №4 — Эвристический модератор с определением действия
"""

import json
import redis
import time
import re
from typing import Dict, Any, List
from datetime import datetime

# Импортируем конфигурацию
from config import (
    OPENAI_API_KEY,
    get_redis_config,
    QUEUE_AGENT_4_INPUT,
    QUEUE_AGENT_5_INPUT,
    AGENT_PORTS,
    DEFAULT_RULES,
    setup_logging,
    determine_action
)

# ============================================================================
# ЛОГИРОВАНИЕ
# ============================================================================

logger = setup_logging("АГЕНТ 4")

# ============================================================================
# ЭВРИСТИЧЕСКИЕ ПАТТЕРНЫ
# ============================================================================

# Матерные слова
PROFANITY_PATTERNS = [
    r'\b(хуй|хуя|хуё|хуи|хую)\b',
    r'\b(пизд[аеиоу]|пиздец|пиздёж)\b',
    r'\b(ебать|ебал|ебёт|ебут|ебали|ебаный|ебучий)\b',
    r'\b(сука|суки|сучка|сучий)\b',
    r'\b(блядь|блять|бля|блея)\b',
    r'\b(долбоёб|долбаёб|мудак|мудила)\b',
    r'\b(пидор|пидар|пидр|гомик)\b',
    r'\b(говно|говнюк|говняшка)\b',
    r'\b(дурак|дура|дебил|идиот|тупой|тупица)\b',
    r'\b(кретин|придурок|дундук|балбес)\b',
    r'\b(урод|уродина|уебок|уёбок)\b',
    r'\b(тварь|сволочь|гад|падла)\b',
]

# Спам и реклама
SPAM_PATTERNS = [
    r'\b(переходи|кликай|жми|нажимай|вступай|подписывайся)\b',
    r'\b(заходи|регистрируйся|скачивай|покупай)\b',
    r'\b(скидка|акция|распродажа|дешево|выгодно)\b',
    r'\b(заработок|доход|прибыль|инвестиции)\b',
    r'\b(продам|куплю|обмен|торговля)\b',
    r'@[a-zA-Z0-9_]+',
    r't\.me/[a-zA-Z0-9_]+',
    r'https?://[^\s]+',
    r'www\.[^\s]+',
    r'[📢📣🎉💰🔥⚡]{3,}',
]

# Дискриминация
DISCRIMINATION_PATTERNS = [
    r'\b(негр|ниггер|черножоп|чурка|хач|хохол)\b',
    r'\b(жид|еврей[а-я]*\s*(плохо|хуйово))\b',
    r'\b(цыган|цыганё|цыганка)\s*[а-я]*\b',
    r'\b(узкогляз|косоглаз|раскосый)\b',
    r'\b(москаль|кацап|бандера|укроп)\b',
    r'\b(чурбан|лицо кавказской национальности)\b',
    r'\b(азиат|узбек|таджик|киргиз)\s+[а-я]*\b',
    r'все\s+(евреи|негры|цыгане|[а-я]+ы)\s+(плохие|воры|дураки)',
    r'эти\s+(черные|желтые|белые)\s+должны',
]

# Флуд
FLOOD_PATTERNS = [
    r'(.)\\1{10,}',
    r'([а-яё])\1{5,}',
    r'[!]{5,}|[?]{5,}|[.]{5,}',
]

# ============================================================================
# ФУНКЦИИ ПРОВЕРКИ
# ============================================================================

def check_profanity(message: str) -> tuple:
    """Проверка на нецензурную лексику. Возвращает (найдено, причина, уверенность)"""
    message_lower = message.lower()
    violations = []
    
    for pattern in PROFANITY_PATTERNS:
        matches = re.findall(pattern, message_lower, re.IGNORECASE)
        if matches:
            violations.extend(matches)
    
    if violations:
        confidence = min(0.9, 0.65 + len(violations) * 0.1)
        return True, f"Обнаружена нецензурная лексика: {', '.join(set(violations[:3]))}", confidence, "profanity"
    
    return False, "", 0.0, ""

def check_spam(message: str) -> tuple:
    """Проверка на спам. Возвращает (найдено, причина, уверенность, тип)"""
    message_lower = message.lower()
    violations = []
    
    for pattern in SPAM_PATTERNS:
        matches = re.findall(pattern, message_lower, re.IGNORECASE)
        if matches:
            violations.extend(matches[:2])
    
    if violations:
        confidence = min(0.85, 0.5 + len(violations) * 0.15)
        return True, f"Обнаружен спам/реклама: {', '.join(set(violations[:2]))}", confidence, "spam"
    
    return False, "", 0.0, ""

def check_discrimination(message: str) -> tuple:
    """Проверка на дискриминацию. Возвращает (найдено, причина, уверенность, тип)"""
    message_lower = message.lower()
    violations = []
    
    for pattern in DISCRIMINATION_PATTERNS:
        matches = re.findall(pattern, message_lower, re.IGNORECASE)
        if matches:
            violations.extend(matches[:2])
    
    if violations:
        confidence = min(0.95, 0.75 + len(violations) * 0.1)
        return True, f"Обнаружена дискриминация: {', '.join(set(violations[:2]))}", confidence, "discrimination"
    
    return False, "", 0.0, ""

def check_flood(message: str) -> tuple:
    """Проверка на флуд. Возвращает (найдено, причина, уверенность, тип)"""
    violations = []
    
    for pattern in FLOOD_PATTERNS:
        matches = re.findall(pattern, message, re.IGNORECASE)
        if matches:
            violations.extend(matches[:2])
    
    if violations:
        return True, "Обнаружен флуд: повторяющиеся символы", 0.75, "flood"
    
    return False, "", 0.0, ""

# ============================================================================
# ЭВРИСТИЧЕСКИЙ АНАЛИЗ
# ============================================================================

def heuristic_analysis(message: str, rules: List[str]) -> dict:
    """
    Комплексный эвристический анализ сообщения.
    Возвращает результат с определением действия.
    """
    
    violations = []
    max_confidence = 0.0
    main_reason = ""
    violation_type = ""
    severity = 0
    
    # Проверяем все виды нарушений
    checks = [
        check_profanity(message),
        check_spam(message),
        check_discrimination(message),
        check_flood(message)
    ]
    
    for has_violation, reason, confidence, vtype in checks:
        if has_violation:
            violations.append(reason)
            if confidence > max_confidence:
                max_confidence = confidence
                main_reason = reason
                violation_type = vtype
    
    if violations:
        # Определяем серьезность по типу нарушения
        if violation_type == "profanity":
            severity = 7  # высокая серьезность
        elif violation_type == "discrimination":
            severity = 9  # очень высокая серьезность
        elif violation_type == "spam":
            severity = 5  # средняя серьезность
        elif violation_type == "flood":
            severity = 4  # низкая-средняя серьезность
        else:
            severity = 5
        
        # Используем функцию determine_action для определения действия
        action_info = determine_action(violation_type, severity, max_confidence)
        
        reason_text = (
            f"Вердикт: {action_info['action'].upper()}\n"
            f"Причина: {main_reason}\n"
            f"Уверенность: {int(max_confidence * 100)}%"
        )
        
        return {
            "ban": action_info["action"] in ["ban", "mute"],
            "action": action_info["action"],
            "action_duration": action_info["duration"],
            "reason": reason_text,
            "confidence": max_confidence,
            "method": "Эвристический анализ",
            "violation_type": violation_type,
            "severity": severity,
            "violations": violations,
            "status": "success"
        }
    
    else:
        return {
            "ban": False,
            "action": "none",
            "action_duration": 0,
            "reason": "Вердикт: НЕ ДЕЙСТВОВАТЬ\nПричина: Нарушений не обнаружено\nУверенность: 95%",
            "confidence": 0.95,
            "method": "Эвристический анализ",
            "violation_type": "none",
            "severity": 0,
            "violations": [],
            "status": "success"
        }

# ============================================================================
# ОСНОВНАЯ ФУНКЦИЯ АГЕНТА 4
# ============================================================================

def moderation_agent_4(input_data):
    """АГЕНТ 4 — Эвристический модератор с определением действия"""
    
    message = input_data.get("message", "")
    rules = input_data.get("rules", [])
    user_id = input_data.get("user_id")
    username = input_data.get("username", "unknown")
    chat_id = input_data.get("chat_id")
    message_id = input_data.get("message_id")
    message_link = input_data.get("message_link", "")
    
    logger.info(f"🔍 Эвристический анализ от @{username} в чате {chat_id}")
    
    if not message:
        return {
            "agent_id": 4,
            "ban": False,
            "action": "none",
            "action_duration": 0,
            "reason": "Пустое сообщение",
            "confidence": 0,
            "message": "",
            "user_id": user_id,
            "username": username,
            "chat_id": chat_id,
            "message_id": message_id,
            "violation_type": "none",
            "severity": 0,
            "status": "error"
        }
    
    if not rules:
        rules = DEFAULT_RULES
        logger.info("Используются стандартные правила")
    
    # Эвристический анализ
    heuristic_result = heuristic_analysis(message, rules)
    
    output = {
        "agent_id": 4,
        "ban": heuristic_result["ban"],
        "action": heuristic_result["action"],
        "action_duration": heuristic_result["action_duration"],
        "reason": heuristic_result["reason"],
        "confidence": heuristic_result["confidence"],
        "message": message,
        "user_id": user_id,
        "username": username,
        "chat_id": chat_id,
        "message_id": message_id,
        "message_link": message_link,
        "method": heuristic_result["method"],
        "violation_type": heuristic_result["violation_type"],
        "severity": heuristic_result["severity"],
        "rules_used": rules,
        "violations": heuristic_result.get("violations", []),
        "status": heuristic_result["status"],
        "timestamp": datetime.now().isoformat()
    }
    
    if heuristic_result["action"] != "none":
        logger.warning(
            f"⛔ {heuristic_result['action'].upper()} для @{username}: "
            f"{heuristic_result['confidence'] * 100:.0f}% "
            f"(тип: {heuristic_result['violation_type']}, серьезность: {heuristic_result['severity']}/10)"
        )
    else:
        logger.info(f"✅ ОК для @{username}: {heuristic_result['confidence'] * 100:.0f}%")
    
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
                "action": "none",
                "reason": f"Ошибка парсинга: {e}",
                "status": "json_error"
            }
        except Exception as e:
            logger.error(f"Ошибка обработки: {e}")
            return {
                "agent_id": 4,
                "ban": False,
                "action": "none",
                "reason": f"Ошибка агента 4: {e}",
                "status": "error"
            }
    
    def send_result(self, result):
        """Отправляет результат в выходную очередь"""
        try:
            result_json = json.dumps(result, ensure_ascii=False)
            self.redis_client.rpush(QUEUE_AGENT_5_INPUT, result_json)
            logger.info(f"✅ Результат отправлен в очередь Агента 5")
        except Exception as e:
            logger.error(f"Не удалось отправить результат: {e}")
    
    def run(self):
        """Главный цикл обработки сообщений"""
        logger.info(f"✅ Агент 4 запущен (Эвристика v4.5)")
        logger.info(f" Паттернов: профанитет={len(PROFANITY_PATTERNS)}, спам={len(SPAM_PATTERNS)}, дискрим={len(DISCRIMINATION_PATTERNS)}")
        logger.info(f" Слушаю очередь: {QUEUE_AGENT_4_INPUT}")
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
# ТОЧКА ВХОДА
# ============================================================================

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # Тестирование
        test_cases = [
            {
                "message": "Привет всем! Как дела?",
                "description": "Нормальное сообщение"
            },
            {
                "message": "Ты дурак и идиот! Хуй тебе!",
                "description": "Мат и оскорбления"
            },
            {
                "message": "Переходи по ссылке t.me/spam! Заработок 100$ в день!",
                "description": "Спам с ссылкой"
            },
            {
                "message": "Все негры должны убираться отсюда!",
                "description": "Расовая дискриминация"
            }
        ]
        
        for i, test_case in enumerate(test_cases, 1):
            print(f"\n--- Тест {i}: {test_case['description']} ---")
            test_input = {
                "message": test_case["message"],
                "rules": DEFAULT_RULES,
                "user_id": 123 + i,
                "username": f"test_user_{i}",
                "chat_id": -100,
                "message_id": i,
                "message_link": f"https://t.me/test/{i}"
            }
            
            result = moderation_agent_4(test_input)
            print(f"Действие: {result['action']}")
            print(f"Серьезность: {result['severity']}/10")
            print(f"Уверенность: {result['confidence'] * 100:.0f}%")
            print(f"Тип: {result['violation_type']}")
    
    else:
        try:
            worker = Agent4Worker()
            worker.run()
        except KeyboardInterrupt:
            logger.info("Выход")
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")