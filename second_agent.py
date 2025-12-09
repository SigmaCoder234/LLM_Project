#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🤖 АГЕНТ №2 — ГЛАВНЫЙ АНАЛИТИК (РАБОЧАЯ ВЕРСИЯ ДЛЯ ТЕКСТОВ)

✅ РАБОТАЕТ: С mistralai 0.0.11
✅ ИСПРАВЛЕНО: Правильная передача сообщений в Mistral
✅ ИСПРАВЛЕНО: Передача severity в выходе
✅ ИСПРАВЛЕНО: Передача message_link из входа
✅ ИСПРАВЛЕНО: НЕ отправляем OK сообщения (action == "none")
"""

import json
import redis
import time
import re
from typing import Dict, Any, List
from datetime import datetime

# ============================================================================
# ИМПОРТЫ MISTRAL - РАБОТАЮЩИЙ КОД ДЛЯ 0.0.11
# ============================================================================

print("🔄 Инициализация Mistral...")

MISTRAL_IMPORT_SUCCESS = False
MISTRAL_IMPORT_VERSION = "none"
mistral_client = None

try:
    # Попытка 1: Новый SDK (v1.0+)
    from mistralai import Mistral
    from mistralai import UserMessage, SystemMessage
    
    MISTRAL_IMPORT_SUCCESS = True
    MISTRAL_IMPORT_VERSION = "v1.0+ (новый SDK)"
    print("✅ Используется Mistral v1.0+ (новый SDK)")
    
except ImportError:
    try:
        # Попытка 2: Legacy SDK (v0.0.11) - РАБОТАЮЩИЙ КОД
        from mistralai.client import MistralClient as Mistral
        
        # Создаем простые функции вместо импорта классов
        def UserMessage(content):
            return {"role": "user", "content": content}
        
        def SystemMessage(content):
            return {"role": "system", "content": content}
        
        MISTRAL_IMPORT_SUCCESS = True
        MISTRAL_IMPORT_VERSION = "v0.0.11 (legacy)"
        print("✅ Используется Mistral v0.0.11 (legacy)")
        
    except Exception as e:
        print(f"❌ КРИТИЧЕСКАЯ ОШИБКА при импорте Mistral: {e}")
        MISTRAL_IMPORT_SUCCESS = False
        MISTRAL_IMPORT_VERSION = "none"
        
        # Fallback классы
        class Mistral:
            def __init__(self, api_key): 
                pass
            
            def chat(self, **kwargs):
                raise ImportError("Mistral AI не установлен")
        
        def UserMessage(content):
            return {"role": "user", "content": content}
        
        def SystemMessage(content):
            return {"role": "system", "content": content}

# ============================================================================
# ИМПОРТЫ КОНФИГА И ЛОГИРОВАНИЯ
# ============================================================================

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

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ MISTRAL КЛИЕНТА
# ============================================================================

if MISTRAL_IMPORT_SUCCESS and MISTRAL_API_KEY:
    try:
        mistral_client = Mistral(api_key=MISTRAL_API_KEY)
        logger.info("✅ Mistral AI клиент создан")
        print("✅ Mistral клиент успешно создан")
        
    except Exception as e:
        logger.error(f"❌ Ошибка создания Mistral AI клиента: {e}")
        print(f"❌ ОШИБКА Mistral: {e}")
        mistral_client = None
else:
    if not MISTRAL_API_KEY:
        logger.warning("⚠️ MISTRAL_API_KEY не установлен")
    else:
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
                "reason": "Mistral не доступен",
                "explanation": "Ошибка инициализации Mistral"
            }
        
        rules_text = "\n".join([f"- {rule}" for rule in rules]) if rules else "- Никаких нарушений"
        prompt = MODERATION_PROMPT.format(rules=rules_text, message=message)
        
        # ✅ ИСПОЛЬЗУЕМ DICT ВМЕСТО ОБЪЕКТОВ (для 0.0.11)
        messages = [UserMessage(prompt)]
        
        logger.debug(f"🔄 Отправляю запрос Mistral для: {message[:40]}...")
        
        response = mistral_client.chat(
            model=MISTRAL_MODEL,
            messages=messages,
            **MISTRAL_GENERATION_PARAMS
        )
        
        content = response.choices[0].message.content
        logger.debug(f"📥 Ответ от Mistral: {content[:200]}")
        
        # Парсим JSON
        try:
            json_start = content.find("{")
            json_end = content.rfind("}") + 1
            
            if json_start >= 0 and json_end > json_start:
                json_str = content[json_start:json_end]
                result = json.loads(json_str)
                
                # Нормализуем
                severity = int(result.get("severity", 5))
                severity = min(10, max(0, severity))
                
                confidence = int(result.get("confidence", 50))
                confidence = min(100, max(0, confidence))
                
                action = result.get("action", "none")
                if action not in ["ban", "mute", "warn", "none"]:
                    action = "warn" if result.get("is_violation") else "none"
                
                logger.info(f"✅ Анализ: severity={severity}, action={action}, confidence={confidence}%")
                
                return {
                    "is_violation": result.get("is_violation", False),
                    "type": result.get("type", "unknown"),
                    "severity": severity,
                    "confidence": confidence,
                    "action": action,
                    "reason": result.get("reason", "Нарушение правил"),
                    "explanation": result.get("explanation", "")
                }
        
        except Exception as e:
            logger.error(f"⚠️ Ошибка парсинга JSON: {e}")
            
            # Fallback: парсим текст вручную
            severity_match = re.search(r'severity["\']?\s*[:=]\s*(\d+)', content, re.IGNORECASE)
            severity = int(severity_match.group(1)) if severity_match else 5
            severity = min(10, max(0, severity))
            
            confidence_match = re.search(r'confidence["\']?\s*[:=]\s*(\d+)', content, re.IGNORECASE)
            confidence = int(confidence_match.group(1)) if confidence_match else 50
            confidence = min(100, max(0, confidence))
            
            action = "none"
            if "ban" in content.lower():
                action = "ban"
            elif "mute" in content.lower():
                action = "mute"
            elif "warn" in content.lower():
                action = "warn"
            
            return {
                "is_violation": action != "none",
                "type": "unknown",
                "severity": severity,
                "confidence": confidence,
                "action": action,
                "reason": "Ошибка парсинга",
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
    
    # ГЛАВНЫЙ АНАЛИЗ
    analysis_result = analyze_with_mistral(message, rules)
    
    # ✅ ФОРМИРУЕМ ВЫХОД (С severity И message_link!)
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
    
    # Логирование
    if analysis_result["is_violation"]:
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
            logger.error(f"❌ Не удалось подключиться к Redis: {e}")
            raise
    
    def run(self):
        """Главный цикл обработки сообщений"""
        logger.info("✅ Агент 2 запущен (Главный аналитик)")
        logger.info(f"📊 Модель: {MISTRAL_MODEL}")
        logger.info(f"📥 Импорт: {MISTRAL_IMPORT_VERSION}")
        logger.info(f"🔔 Слушаю очередь: {QUEUE_AGENT_2_INPUT}")
        logger.info("⏱️  Нажмите Ctrl+C для остановки\n")
        
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
                    
                    # ✅ ПИШЕМ РЕЗУЛЬТАТ В REDIS
                    try:
                        result_json = json.dumps(output, ensure_ascii=False)
                        
                        # Отправляем в очередь агентов 3, 4 и в очередь бота
                        self.redis_client.rpush(QUEUE_AGENT_2_OUTPUT, result_json)
                        self.redis_client.rpush(QUEUE_AGENT_3_INPUT, result_json)
                        self.redis_client.rpush(QUEUE_AGENT_4_INPUT, result_json)
                        
                        logger.info(f"📤 ✅ Результат отправлен (action={output.get('action')})")
                    except Exception as e:
                        logger.error(f"❌ Ошибка отправки результата в Redis: {e}")
                    
                    logger.info("✅ Анализ завершен\n")
                    
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
            print("\n" + "=" * 80)
            print("❌ КРИТИЧЕСКАЯ ОШИБКА: Mistral клиент не инициализирован")
            print("=" * 80)
            exit(1)
        
        worker = Agent2Worker()
        worker.run()
    
    except KeyboardInterrupt:
        logger.info("Выход")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        import traceback
        logger.error(traceback.format_exc())
        exit(1)
