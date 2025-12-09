#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🤖 АГЕНТ №2 — ГЛАВНЫЙ АНАЛИТИК (ИСПРАВЛЕННАЯ ВЕРСИЯ v3.0)

✅ ИСПРАВЛЕНО: Правильная обработка severity и confidence
✅ ИСПРАВЛЕНО: Fallback парсинг JSON
✅ ИСПРАВЛЕНО: Проверка action перед отправкой
✅ ИСПРАВЛЕНО: Гарантированы значения всех полей
"""

import json
import redis
import time
import re
from typing import Dict, Any, List
from datetime import datetime

try:
    from mistralai import Mistral
    from mistralai import UserMessage, SystemMessage
    MISTRAL_IMPORT_SUCCESS = True
    MISTRAL_IMPORT_VERSION = "v1.0+ (новый SDK)"
except ImportError:
    try:
        from mistralai.client import MistralClient as Mistral
        from mistralai.models.chat_completion import ChatMessage
        def UserMessage(content):
            return {"role": "user", "content": content}
        def SystemMessage(content):
            return {"role": "system", "content": content}
        MISTRAL_IMPORT_SUCCESS = True
        MISTRAL_IMPORT_VERSION = "v0.4.2 (legacy)"
    except ImportError:
        print("❌ Не удалось импортировать Mistral AI")
        MISTRAL_IMPORT_SUCCESS = False
        MISTRAL_IMPORT_VERSION = "none"
        class Mistral:
            def __init__(self, api_key): pass
            def chat(self, **kwargs):
                raise ImportError("Mistral AI не установлен")
        def UserMessage(content):
            return {"role": "user", "content": content}
        def SystemMessage(content):
            return {"role": "system", "content": content}

from config import (
    MISTRAL_API_KEY, MISTRAL_MODEL, MISTRAL_GENERATION_PARAMS,
    get_redis_config, QUEUE_AGENT_2_INPUT, QUEUE_AGENT_2_OUTPUT,
    QUEUE_AGENT_3_INPUT, QUEUE_AGENT_4_INPUT, DEFAULT_RULES, setup_logging
)

logger = setup_logging("АГЕНТ 2")

if MISTRAL_IMPORT_SUCCESS:
    logger.info(f"✅ Mistral AI импортирован успешно ({MISTRAL_IMPORT_VERSION})")
else:
    logger.error("❌ Mistral AI не импортирован")

if MISTRAL_IMPORT_SUCCESS and MISTRAL_API_KEY:
    try:
        mistral_client = Mistral(api_key=MISTRAL_API_KEY)
        logger.info("✅ Mistral AI клиент создан")
    except Exception as e:
        logger.error(f"❌ Ошибка создания Mistral AI клиента: {e}")
        mistral_client = None
else:
    mistral_client = None
    logger.warning("⚠️ Mistral AI клиент не создан")

# ============================================================================
# ПРОМПТ ДЛЯ MISTRAL
# ============================================================================

MODERATION_PROMPT = """Ты модератор чата. Проанализируй сообщение и определи нарушает ли оно правила.

ПРАВИЛА ЧАТА:
{rules}

СООБЩЕНИЕ: "{message}"

ТРЕБОВАНИЯ:

1. Ответь ТОЛЬКО JSON (никакого другого текста!)
2. Severity: 0-10 (0=OK, 10=критично)
3. Confidence: 0-100 (насколько уверен)

ДОПУСТИМЫЕ ТИПЫ:
- obscene (мат, оскорбления)
- hate_speech (ненависть к группе)
- threat (угроза, насилие)
- spam (спам, реклама)
- violence (описание насилия)
- sexual (сексуальный контент)
- misleading (дезинформация)
- harassment (преследование)
- none (нет нарушений)

ВОЗМОЖНЫЕ ДЕЙСТВИЯ:
- ban (блокировка пользователя)
- mute (запрет на написание)
- warn (предупреждение)
- none (ничего не делать)

JSON ФОРМАТ:
{
"is_violation": boolean,
"type": "тип нарушения",
"severity": число 0-10,
"confidence": число 0-100,
"action": "ban|mute|warn|none",
"reason": "краткое объяснение",
"explanation": "подробное объяснение"
}"""

# ============================================================================
# АНАЛИЗ С MISTRAL - ИСПРАВЛЕННАЯ ВЕРСИЯ
# ============================================================================

def analyze_with_mistral(message: str, rules: List[str]) -> Dict[str, Any]:
    """Анализирует сообщение с помощью Mistral - ИСПРАВЛЕННАЯ ВЕРСИЯ v3.0"""
    try:
        if not mistral_client:
            logger.error("❌ Mistral клиент не инициализирован")
            return {
                "is_violation": False,
                "type": "unknown",
                "severity": 0,
                "confidence": 0,
                "action": "none",
                "reason": "Mistral не доступен",
                "explanation": "Ошибка инициализации Mistral"
            }

        rules_text = "\n".join([f"- {rule}" for rule in rules]) if rules else "- Нет правил"
        prompt = MODERATION_PROMPT.format(rules=rules_text, message=message)
        messages = [UserMessage(prompt)]

        response = mistral_client.chat(
            model=MISTRAL_MODEL,
            messages=messages,
            **MISTRAL_GENERATION_PARAMS
        )

        content = response.choices[0].message.content
        logger.debug(f"📝 Ответ Mistral: {content[:200]}")

        # ✅ ПОПЫТКА 1: Парсим JSON
        try:
            json_start = content.find("{")
            json_end = content.rfind("}") + 1

            if json_start >= 0 and json_end > json_start:
                json_str = content[json_start:json_end]
                result = json.loads(json_str)

                # ✅ НОРМАЛИЗУЕМ ЗНАЧЕНИЯ - ВСЕГДА ЧИСЛА
                try:
                    severity = int(result.get("severity", 0))
                except (ValueError, TypeError):
                    severity = 0
                severity = min(10, max(0, severity))

                try:
                    confidence = int(result.get("confidence", 0))
                except (ValueError, TypeError):
                    confidence = 0
                confidence = min(100, max(0, confidence))

                action = str(result.get("action", "none")).lower()
                if action not in ["ban", "mute", "warn", "none"]:
                    action = "warn" if result.get("is_violation") else "none"

                is_violation = bool(result.get("is_violation", action != "none"))
                violation_type = str(result.get("type", "unknown"))

                logger.info(f"✅ JSON успешен: severity={severity}, action={action}, confidence={confidence}%")

                return {
                    "is_violation": is_violation,
                    "type": violation_type,
                    "severity": severity,
                    "confidence": confidence,
                    "action": action,
                    "reason": result.get("reason", "Нарушение правил"),
                    "explanation": result.get("explanation", "")
                }
        except json.JSONDecodeError as je:
            logger.warning(f"⚠️ JSON невалиден: {je}, переходим на fallback")

        # ✅ ПОПЫТКА 2: Эвристический парсинг (FALLBACK)
        logger.info("📋 Используем fallback парсинг")

        severity = 0
        confidence = 50
        action = "none"
        is_violation = False
        violation_type = "unknown"

        content_lower = content.lower()

        # Ищем числовые значения
        severity_match = re.search(r'severity["\']?\s*[:=]\s*(\d+)', content_lower)
        if severity_match:
            try:
                severity = int(severity_match.group(1))
                severity = min(10, max(0, severity))
            except (ValueError, TypeError):
                severity = 0

        confidence_match = re.search(r'confidence["\']?\s*[:=]\s*(\d+)', content_lower)
        if confidence_match:
            try:
                confidence = int(confidence_match.group(1))
                confidence = min(100, max(0, confidence))
            except (ValueError, TypeError):
                confidence = 50

        # Ищем действие модерации
        if "ban" in content_lower:
            action = "ban"
            is_violation = True
        elif "mute" in content_lower:
            action = "mute"
            is_violation = True
        elif "warn" in content_lower:
            action = "warn"
            is_violation = True
        elif "violation" in content_lower or "нарушение" in content_lower:
            is_violation = True
            if severity >= 7:
                action = "mute"
            else:
                action = "warn"

        # Определяем тип нарушения
        if "мат" in content_lower or "obscene" in content_lower:
            violation_type = "obscene"
        elif "оскорбл" in content_lower or "threat" in content_lower:
            violation_type = "harassment"
        elif "дискримин" in content_lower or "hate" in content_lower:
            violation_type = "hate_speech"
        elif "реклам" in content_lower or "spam" in content_lower:
            violation_type = "spam"

        logger.info(f"⚠️ Fallback: severity={severity}, action={action}, confidence={confidence}%, type={violation_type}")

        return {
            "is_violation": is_violation,
            "type": violation_type,
            "severity": severity,
            "confidence": confidence,
            "action": action,
            "reason": "Эвристический анализ" if is_violation else "Нарушений не обнаружено",
            "explanation": content[:300]
        }

    except Exception as e:
        logger.error(f"❌ Ошибка Mistral: {e}")
        return {
            "is_violation": False,
            "type": "unknown",
            "severity": 0,
            "confidence": 0,
            "action": "none",
            "reason": "Ошибка анализа",
            "explanation": str(e)
        }

# ============================================================================
# ОСНОВНАЯ ФУНКЦИЯ АГЕНТА 2 - ИСПРАВЛЕННАЯ
# ============================================================================

def moderation_agent_2(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Агент 2 — Главный аналитик - ИСПРАВЛЕННАЯ ВЕРСИЯ"""

    message = input_data.get("message", "")
    rules = input_data.get("rules", DEFAULT_RULES)
    user_id = input_data.get("user_id")
    username = input_data.get("username", "unknown")
    chat_id = input_data.get("chat_id")
    message_id = input_data.get("message_id")
    message_link = input_data.get("message_link", "")
    media_type = input_data.get("media_type", "")

    logger.info(f"🔍 Анализирую сообщение от @{username}: '{message[:50] if message else '[фото]'}...'")

    # ✅ ПРОВЕРКА: Пустое сообщение (например, фото без подписи)
    if not message or not message.strip():
        logger.info(f"ℹ️ Пустое сообщение (media_type={media_type})")

        # ✅ Для фото без подписи - возвращаем "OK"
        return {
            "agent_id": 2,
            "message": "",
            "user_id": user_id,
            "username": username,
            "chat_id": chat_id,
            "message_id": message_id,
            "message_link": message_link,
            "action": "none",
            "severity": 0,
            "confidence": 100,
            "reason": "Пустое сообщение",
            "is_violation": False,
            "media_type": media_type,
            "type": "none",
            "explanation": "Нет текста для анализа",
            "timestamp": datetime.now().isoformat()
        }

    # ✅ ГЛАВНЫЙ АНАЛИЗ
    analysis_result = analyze_with_mistral(message, rules)

    # ✅ ФОРМИРУЕМ ВЫХОД (ГАРАНТИРУЕМ ВСЕ ПОЛЯ)
    output = {
        "agent_id": 2,
        "message": message,
        "user_id": user_id,
        "username": username,
        "chat_id": chat_id,
        "message_id": message_id,
        "message_link": message_link,
        "action": analysis_result.get("action", "none"),
        "severity": analysis_result.get("severity", 0),
        "confidence": analysis_result.get("confidence", 0),
        "reason": analysis_result.get("reason", "Анализ завершен"),
        "is_violation": analysis_result.get("is_violation", False),
        "type": analysis_result.get("type", "unknown"),
        "explanation": analysis_result.get("explanation", ""),
        "media_type": media_type,
        "timestamp": datetime.now().isoformat()
    }

    # ✅ ЛОГИРОВАНИЕ
    if analysis_result.get("is_violation"):
        logger.warning(
            f"⚠️ НАРУШЕНИЕ: тип={analysis_result['type']}, "
            f"серьезность={analysis_result['severity']}/10, "
            f"уверенность={analysis_result['confidence']}%, "
            f"действие={analysis_result['action']}"
        )
    else:
        logger.info(f"✅ ОК: {analysis_result['confidence']}% уверенности")

    return output

# ============================================================================
# REDIS WORKER - ИСПРАВЛЕННАЯ ВЕРСИЯ
# ============================================================================

class Agent2Worker:
    def __init__(self):
        try:
            redis_config = get_redis_config()
            self.redis_client = redis.Redis(**redis_config)
            self.redis_client.ping()
            logger.info("✅ Подключение к Redis успешно")
        except Exception as e:
            logger.error(f"❌ Не удалось подключиться к Redis: {e}")
            raise

    def run(self):
        """Главный цикл обработки сообщений - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
        logger.info("✅ Агент 2 запущен (Главный аналитик)")
        logger.info(f"📊 Модель: {MISTRAL_MODEL}")
        logger.info(f"📥 Импорт: {MISTRAL_IMPORT_VERSION}")
        logger.info(f"🔔 Слушаю очередь: {QUEUE_AGENT_2_INPUT}")
        logger.info("⏱️ Нажмите Ctrl+C для остановки\n")

        try:
            while True:
                try:
                    result = self.redis_client.blpop(QUEUE_AGENT_2_INPUT, timeout=1)
                    if result is None:
                        continue

                    queue_name, message_data = result
                    logger.info("📨 Получено новое сообщение")

                    # Парсим JSON
                    try:
                        input_data = json.loads(message_data)
                    except json.JSONDecodeError as e:
                        logger.error(f"❌ Невалидный JSON: {e}")
                        continue

                    # Обрабатываем
                    output = moderation_agent_2(input_data)

                    # ✅ ИСПРАВЛЕНИЕ: Проверяем action перед отправкой
                    if output.get("action") == "none" and not output.get("media_type"):
                        # ✅ Если нет нарушения И нет медиа - не отправляем
                        logger.info(f"✅ Сообщение OK - не отправляем дальше")
                        logger.info("✅ Анализ завершен\n")
                        continue

                    # ✅ Отправляем ТОЛЬКО нарушения
                    try:
                        result_json = json.dumps(output, ensure_ascii=False)

                        # Отправляем в выходную очередь БОТа
                        self.redis_client.rpush(QUEUE_AGENT_2_OUTPUT, result_json)
                        logger.info(f"📤 QUEUE_AGENT_2_OUTPUT: action={output.get('action')}")

                        # Отправляем в агентов 3 и 4 для независимого анализа
                        if output.get("action") != "none" or output.get("is_violation"):
                            self.redis_client.rpush(QUEUE_AGENT_3_INPUT, result_json)
                            self.redis_client.rpush(QUEUE_AGENT_4_INPUT, result_json)
                            logger.info(f"📤 QUEUE_AGENT_3_INPUT & QUEUE_AGENT_4_INPUT отправлены")

                    except Exception as e:
                        logger.error(f"❌ Ошибка отправки результата в Redis: {e}")

                    logger.info("✅ Анализ завершен\n")

                except Exception as e:
                    logger.error(f"❌ Ошибка в цикле: {e}")
                    time.sleep(1)

        except KeyboardInterrupt:
            logger.info("\n❌ Агент 2 остановлен (Ctrl+C)")
        finally:
            logger.info("Агент 2 завершил работу")

# ============================================================================
# ТОЧКА ВХОДА
# ============================================================================

if __name__ == "__main__":
    try:
        worker = Agent2Worker()
        worker.run()
    except KeyboardInterrupt:
        logger.info("Выход")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
