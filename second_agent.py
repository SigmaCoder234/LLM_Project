#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🤖 АГЕНТ №2 — ГЛАВНЫЙ АНАЛИТИК
✅ Получает ВСЕ сообщения от Агента 1
✅ Анализирует с Mistral
✅ Отправляет результат В ОЧЕРЕДИ АГЕНТОВ 3 И 4
✅ Минимальное изменение (3 строки в конце!)
"""

import json
import redis
import time
from typing import Dict, Any, List
from datetime import datetime

try:
    from mistralai import Mistral
    from mistralai.models.chat_completion import ChatMessage
    MISTRAL_IMPORT_SUCCESS = True
    MISTRAL_IMPORT_VERSION = "v1.0+ (новый SDK)"
except ImportError:
    try:
        from mistralai.client import MistralClient as Mistral
        from mistralai.models.chat_completion import ChatMessage
        MISTRAL_IMPORT_SUCCESS = True
        MISTRAL_IMPORT_VERSION = "v0.0.11 (legacy)"
    except Exception as e:
        MISTRAL_IMPORT_SUCCESS = False
        
        class Mistral:
            def __init__(self, api_key=None): 
                pass
            def chat(self, **kwargs):
                raise ImportError("Mistral AI не установлен")
        
        class ChatMessage:
            def __init__(self, role, content):
                self.role = role
                self.content = content

from config import (
    MISTRAL_API_KEY, MISTRAL_MODEL, MISTRAL_GENERATION_PARAMS,
    get_redis_config, QUEUE_AGENT_2_INPUT, QUEUE_AGENT_2_OUTPUT,
    QUEUE_AGENT_3_INPUT, QUEUE_AGENT_4_INPUT, DEFAULT_RULES, setup_logging
)

logger = setup_logging("АГЕНТ 2")

if MISTRAL_IMPORT_SUCCESS:
    logger.info(f"✅ Mistral AI импортирован ({MISTRAL_IMPORT_VERSION})")
else:
    logger.error("❌ Mistral AI не импортирован")

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ MISTRAL
# ============================================================================

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
{{
"is_violation": boolean,
"type": "тип нарушения",
"severity": число 0-10,
"confidence": число 0-100,
"action": "ban|mute|warn|none",
"reason": "краткое объяснение",
"explanation": "подробное объяснение"
}}"""

# ============================================================================
# АНАЛИЗ С MISTRAL
# ============================================================================

def analyze_with_mistral(message: str, rules: List[str]) -> Dict[str, Any]:
    """Анализирует сообщение с помощью Mistral"""
    
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
    
    try:
        rules_text = "\n".join([f"- {rule}" for rule in rules]) if rules else "- Никаких правил"
        prompt = MODERATION_PROMPT.format(rules=rules_text, message=message)
        
        messages = [ChatMessage(role="user", content=prompt)]
        
        logger.info(f"📤 Отправляю запрос к Mistral...")
        
        response = mistral_client.chat(
            model=MISTRAL_MODEL,
            messages=messages,
            **MISTRAL_GENERATION_PARAMS
        )
        
        content = response.choices[0].message.content
        logger.info(f"📥 Получен ответ от Mistral")
        
        try:
            json_start = content.find("{")
            json_end = content.rfind("}") + 1
            
            if json_start >= 0 and json_end > json_start:
                json_str = content[json_start:json_end]
                result = json.loads(json_str)
                
                severity = int(result.get("severity", 5))
                severity = max(0, min(10, severity))
                
                confidence = int(result.get("confidence", 50))
                confidence = max(0, min(100, confidence))
                
                action = result.get("action", "none")
                if action not in ["ban", "mute", "warn", "none"]:
                    action = "warn" if result.get("is_violation") else "none"
                
                logger.info(f"✅ Анализ: severity={severity}, action={action}, confidence={confidence}")
                
                return {
                    "is_violation": result.get("is_violation", False),
                    "type": result.get("type", "unknown"),
                    "severity": severity,
                    "confidence": confidence,
                    "action": action,
                    "reason": result.get("reason", ""),
                    "explanation": result.get("explanation", "")
                }
        
        except json.JSONDecodeError as e:
            logger.warning(f"⚠️ Ошибка парсинга JSON: {e}")
            
            severity = 5
            confidence = 50
            action = "none"
            
            if "ban" in content.lower():
                action = "ban"
                severity = 8
            elif "warn" in content.lower():
                action = "warn"
                severity = 5
            elif "mute" in content.lower():
                action = "mute"
                severity = 4
            
            return {
                "is_violation": action != "none",
                "type": "unknown",
                "severity": severity,
                "confidence": confidence,
                "action": action,
                "reason": "Fallback парсинг",
                "explanation": content[:200]
            }
    
    except Exception as e:
        logger.error(f"❌ Ошибка при анализе: {e}", exc_info=True)
        return {
            "is_violation": False,
            "type": "unknown",
            "severity": 0,
            "confidence": 0,
            "action": "none",
            "reason": f"Ошибка: {str(e)[:50]}",
            "explanation": str(e)
        }

# ============================================================================
# ОСНОВНАЯ ФУНКЦИЯ АГЕНТА 2
# ============================================================================

def moderation_agent_2(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Агент 2 — Главный аналитик"""
    
    message = input_data.get("message", "")
    rules = input_data.get("rules", DEFAULT_RULES)
    user_id = input_data.get("user_id")
    username = input_data.get("username", "unknown")
    chat_id = input_data.get("chat_id")
    message_id = input_data.get("message_id")
    message_link = input_data.get("message_link", "")
    media_type = input_data.get("media_type", "")
    
    logger.info(f"🔍 Анализирую сообщение от @{username}: '{message[:50]}...'")
    
    if not message or not message.strip():
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
            "media_type": media_type,
            "timestamp": datetime.now().isoformat()
        }
    
    analysis_result = analyze_with_mistral(message, rules)
    
    output = {
        "agent_id": 2,
        "message": message,
        "user_id": user_id,
        "username": username,
        "chat_id": chat_id,
        "message_id": message_id,
        "message_link": message_link,
        "action": analysis_result["action"],
        "severity": analysis_result["severity"],
        "confidence": analysis_result["confidence"],
        "reason": analysis_result["reason"],
        "type": analysis_result["type"],
        "explanation": analysis_result["explanation"],
        "is_violation": analysis_result["is_violation"],
        "media_type": media_type,
        "timestamp": datetime.now().isoformat()
    }
    
    if analysis_result["is_violation"]:
        logger.warning(
            f"🚨 НАРУШЕНИЕ: type={analysis_result['type']}, "
            f"severity={analysis_result['severity']}/10, action={analysis_result['action']}"
        )
    else:
        logger.info(f"✅ OK: сообщение в порядке")
    
    return output

# ============================================================================
# REDIS WORKER
# ============================================================================

class Agent2Worker:
    def __init__(self):
        try:
            redis_config = get_redis_config()
            self.redis_client = redis.Redis(**redis_config)
            self.redis_client.ping()
            logger.info("✅ Подключение к Redis успешно")
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к Redis: {e}")
            raise
    
    def run(self):
        """Главный цикл обработки сообщений"""
        logger.info("="*80)
        logger.info("✅ АГЕНТ 2 ЗАПУЩЕН (Главный аналитик)")
        logger.info(f"📊 Модель: {MISTRAL_MODEL}")
        logger.info(f"📥 Импорт: {MISTRAL_IMPORT_VERSION}")
        logger.info(f"🔔 Очередь входа: {QUEUE_AGENT_2_INPUT}")
        logger.info(f"📤 Отправляю в Агентов 3 и 4")
        logger.info("⏱️  Нажмите Ctrl+C для остановки")
        logger.info("="*80 + "\n")
        
        try:
            while True:
                try:
                    result = self.redis_client.blpop(QUEUE_AGENT_2_INPUT, timeout=1)
                    
                    if result is None:
                        continue
                    
                    queue_name, message_data = result
                    logger.info("📨 Получено новое сообщение")
                    
                    try:
                        input_data = json.loads(message_data)
                    except json.JSONDecodeError as e:
                        logger.error(f"❌ Невалидный JSON: {e}")
                        continue
                    
                    # Обрабатываем сообщение
                    output = moderation_agent_2(input_data)
                    
                    # ✅ ОТПРАВЛЯЕМ РЕЗУЛЬТАТ В ОЧЕРЕДИ АГЕНТОВ 3 И 4
                    try:
                        result_json = json.dumps(output, ensure_ascii=False)
                        
                        self.redis_client.rpush(QUEUE_AGENT_2_OUTPUT, result_json)
                        self.redis_client.rpush(QUEUE_AGENT_3_INPUT, result_json)
                        self.redis_client.rpush(QUEUE_AGENT_4_INPUT, result_json)
                        
                        logger.info(f"📤 Результат отправлен в Агентов 3 и 4 (action={output.get('action')})\n")
                    except Exception as e:
                        logger.error(f"❌ Ошибка отправки: {e}")
                    
                except Exception as e:
                    logger.error(f"❌ Ошибка в цикле: {e}")
                    time.sleep(1)
        
        except KeyboardInterrupt:
            logger.info("\n🛑 Агент 2 остановлен (Ctrl+C)")
        finally:
            logger.info("Агент 2 завершил работу")

# ============================================================================
# ТОЧКА ВХОДА
# ============================================================================

if __name__ == "__main__":
    try:
        if not mistral_client:
            logger.error("❌ Mistral клиент не инициализирован - выход")
            exit(1)
        
        worker = Agent2Worker()
        worker.run()
    
    except KeyboardInterrupt:
        logger.info("Выход")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
        exit(1)
