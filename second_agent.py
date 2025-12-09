#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🤖 АГЕНТ №2 — ГЛАВНЫЙ АНАЛИТИК (FINAL v2.0)
✅ РАБОЧАЯ ВЕРСИЯ с fallback логикой
✅ Mistral работает 100%
✅ Правильная обработка severity и confidence
"""

import json
import redis
import time
import re
from typing import Dict, Any, List
from datetime import datetime

try:
    from mistralai import Mistral
    from mistralai import UserMessage
    MISTRAL_IMPORT_SUCCESS = True
    MISTRAL_VERSION = "v1.0+ (новый SDK)"
except ImportError:
    try:
        from mistralai.client import MistralClient as Mistral
        def UserMessage(content):
            return {"role": "user", "content": content}
        MISTRAL_IMPORT_SUCCESS = True
        MISTRAL_VERSION = "v0.4.2 (legacy)"
    except ImportError:
        MISTRAL_IMPORT_SUCCESS = False
        MISTRAL_VERSION = "none"
        class Mistral:
            def __init__(self, api_key): pass
            def chat(self, **kwargs):
                raise ImportError("Mistral AI не установлен")
        def UserMessage(content):
            return {"role": "user", "content": content}

from config import (
    MISTRAL_API_KEY, MISTRAL_MODEL, MISTRAL_GENERATION_PARAMS,
    get_redis_config, QUEUE_AGENT_2_INPUT, QUEUE_AGENT_2_OUTPUT,
    QUEUE_AGENT_3_INPUT, QUEUE_AGENT_4_INPUT, DEFAULT_RULES, setup_logging
)

logger = setup_logging("АГЕНТ 2")

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ MISTRAL
# ============================================================================

mistral_client = None

if MISTRAL_IMPORT_SUCCESS:
    logger.info(f"✅ Mistral AI импортирован ({MISTRAL_VERSION})")
    try:
        mistral_client = Mistral(api_key=MISTRAL_API_KEY)
        logger.info("✅ Mistral клиент создан")
    except Exception as e:
        logger.error(f"❌ Ошибка Mistral: {e}")
        mistral_client = None
else:
    logger.error("❌ Mistral не импортирован")
    mistral_client = None

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
- none (нет нарушений)

ВОЗМОЖНЫЕ ДЕЙСТВИЯ:
- ban (блокировка пользователя)
- mute (запрет на написание)
- warn (предупреждение)
- none (ничего не делать)

JSON ФОРМАТ:
{{
  "is_violation": boolean,
  "type": "тип",
  "severity": число 0-10,
  "confidence": число 0-100,
  "action": "ban|mute|warn|none",
  "reason": "объяснение"
}}"""

# ============================================================================
# АНАЛИЗ С MISTRAL
# ============================================================================

def analyze_with_mistral(message: str, rules: List[str]) -> Dict[str, Any]:
    """Анализирует сообщение с помощью Mistral"""
    try:
        if not mistral_client:
            logger.error("❌ Mistral клиент не инициализирован")
            return {
                "is_violation": False,
                "type": "unknown",
                "severity": 0,
                "confidence": 0,
                "action": "none",
                "reason": "Mistral не доступен"
            }
        
        rules_text = "\n".join([f"- {rule}" for rule in rules]) if rules else "- Нет специальных правил"
        
        prompt = MODERATION_PROMPT.format(rules=rules_text, message=message)
        
        messages = [UserMessage(prompt)]
        
        logger.info(f"📡 Отправляю запрос к {MISTRAL_MODEL}...")
        response = mistral_client.chat(
            model=MISTRAL_MODEL,
            messages=messages,
            **MISTRAL_GENERATION_PARAMS
        )
        
        content = response.choices[0].message.content
        logger.info(f"📝 Ответ: {content[:100]}...")
        
        # ✅ ПАРСИМ JSON
        try:
            json_start = content.find("{")
            json_end = content.rfind("}") + 1
            
            if json_start >= 0 and json_end > json_start:
                json_str = content[json_start:json_end]
                result = json.loads(json_str)
                
                # ✅ НОРМАЛИЗУЕМ ЗНАЧЕНИЯ (с fallback)
                severity = int(result.get("severity", 0))
                severity = min(10, max(0, severity))
                
                confidence = int(result.get("confidence", 50))
                confidence = min(100, max(0, confidence))
                
                is_violation = result.get("is_violation", False)
                action = result.get("action", "none")
                
                # Если severity > 0 но action="none" - исправляем
                if severity > 0 and action == "none":
                    if severity >= 8:
                        action = "ban"
                    elif severity >= 5:
                        action = "warn"
                    elif severity >= 3:
                        action = "mute"
                
                # Если is_violation=True но action="none" - исправляем
                if is_violation and action == "none":
                    action = "warn"
                
                logger.info(f"✅ Анализ: severity={severity}, action={action}, confidence={confidence}%")
                
                return {
                    "is_violation": is_violation,
                    "type": result.get("type", "none"),
                    "severity": severity,
                    "confidence": confidence,
                    "action": action,
                    "reason": result.get("reason", "Определено Mistral")
                }
        except json.JSONDecodeError as e:
            logger.error(f"⚠️ JSON парсинг ошибка: {e}")
            
            # ✅ FALLBACK: парсим текст вручную
            logger.info("📌 Использую fallback парсинг...")
            
            severity_match = re.search(r'severity["\']?\s*[:=]\s*(\d+)', content, re.IGNORECASE)
            severity = int(severity_match.group(1)) if severity_match else 0
            severity = min(10, max(0, severity))
            
            confidence_match = re.search(r'confidence["\']?\s*[:=]\s*(\d+)', content, re.IGNORECASE)
            confidence = int(confidence_match.group(1)) if confidence_match else 50
            confidence = min(100, max(0, confidence))
            
            action = "none"
            violation_type = "none"
            
            if severity > 0:
                if "ban" in content.lower():
                    action = "ban"
                elif "mute" in content.lower():
                    action = "mute"
                elif "warn" in content.lower():
                    action = "warn"
                
                if "obscene" in content.lower() or "мат" in content.lower():
                    violation_type = "obscene"
                elif "hate" in content.lower() or "ненависть" in content.lower():
                    violation_type = "hate_speech"
                elif "threat" in content.lower() or "угроза" in content.lower():
                    violation_type = "threat"
                elif "spam" in content.lower():
                    violation_type = "spam"
            
            logger.info(f"✅ Fallback: severity={severity}, action={action}")
            
            return {
                "is_violation": severity > 0,
                "type": violation_type,
                "severity": severity,
                "confidence": confidence,
                "action": action,
                "reason": "Fallback парсинг"
            }
    
    except Exception as e:
        logger.error(f"❌ Ошибка Mistral: {e}")
        return {
            "is_violation": False,
            "type": "unknown",
            "severity": 0,
            "confidence": 0,
            "action": "none",
            "reason": f"Ошибка: {str(e)}"
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
    
    logger.info(f"🔍 Анализирую от @{username}: '{message[:50]}...'")
    
    if not message or not message.strip():
        logger.warning(f"⚠️ Пустое сообщение от @{username}")
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
            "type": "none",
            "is_violation": False,
            "media_type": media_type,
            "timestamp": datetime.now().isoformat()
        }
    
    # ✅ ГЛАВНЫЙ АНАЛИЗ
    analysis_result = analyze_with_mistral(message, rules)
    
    # ✅ ФОРМИРУЕМ ВЫХОД
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
        "is_violation": analysis_result["is_violation"],
        "media_type": media_type,
        "timestamp": datetime.now().isoformat()
    }
    
    # Логирование результата
    if analysis_result["is_violation"]:
        logger.warning(
            f"⚠️ НАРУШЕНИЕ: "
            f"type={analysis_result['type']}, "
            f"severity={analysis_result['severity']}/10, "
            f"confidence={analysis_result['confidence']}%, "
            f"action={analysis_result['action']}"
        )
    else:
        logger.info(f"✅ ОК: severity={analysis_result['severity']}, confidence={analysis_result['confidence']}%")
    
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
            logger.info("✅ Redis подключен")
        except Exception as e:
            logger.error(f"❌ Ошибка Redis: {e}")
            raise
    
    def run(self):
        """Главный цикл"""
        logger.info("=" * 60)
        logger.info("✅ АГЕНТ 2 ЗАПУЩЕН (Главный аналитик)")
        logger.info("=" * 60)
        logger.info(f"📊 Модель: {MISTRAL_MODEL}")
        logger.info(f"📥 SDK: {MISTRAL_VERSION}")
        logger.info(f"🔔 Очередь: {QUEUE_AGENT_2_INPUT}")
        logger.info("⏱️ Нажмите Ctrl+C для остановки")
        logger.info("=" * 60 + "\n")
        
        try:
            while True:
                try:
                    result = self.redis_client.blpop(QUEUE_AGENT_2_INPUT, timeout=1)
                    
                    if result is None:
                        continue
                    
                    queue_name, message_data = result
                    logger.info("📨 Получено сообщение")
                    
                    try:
                        input_data = json.loads(message_data)
                    except json.JSONDecodeError as e:
                        logger.error(f"❌ JSON ошибка: {e}")
                        continue
                    
                    # ✅ ОБРАБАТЫВАЕМ
                    output = moderation_agent_2(input_data)
                    
                    # ✅ ОТПРАВЛЯЕМ РЕЗУЛЬТАТ
                    try:
                        result_json = json.dumps(output, ensure_ascii=False)
                        
                        # ВСЕГДА отправляем результат (и для action="none")
                        self.redis_client.rpush(QUEUE_AGENT_2_OUTPUT, result_json)
                        
                        # ✅ Отправляем в очереди агентов 3 и 4 если нарушение
                        if output.get("is_violation"):
                            self.redis_client.rpush(QUEUE_AGENT_3_INPUT, result_json)
                            self.redis_client.rpush(QUEUE_AGENT_4_INPUT, result_json)
                            logger.info(f"📤 АГЕНТЫ 3, 4: нарушение отправлено")
                        
                        logger.info(
                            f"📤 БОТ: action={output.get('action')}, "
                            f"severity={output.get('severity')}, "
                            f"is_violation={output.get('is_violation')}"
                        )
                    
                    except Exception as e:
                        logger.error(f"❌ Ошибка отправки: {e}")
                    
                    logger.info("✅ Анализ завершен\n")
                
                except Exception as e:
                    logger.error(f"❌ Ошибка цикла: {e}")
                    time.sleep(1)
        
        except KeyboardInterrupt:
            logger.info("\n" + "=" * 60)
            logger.info("❌ АГЕНТ 2 ОСТАНОВЛЕН")
            logger.info("=" * 60)
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
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        logger.error(traceback.format_exc())
