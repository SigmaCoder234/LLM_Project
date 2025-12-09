#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🤖 АГЕНТ №2 — ГЛАВНЫЙ АНАЛИТИК (v1.3 FIXED)
✅ Исправлена инициализация Mistral
✅ Добавлена проверка подключения
✅ Работает с legacy SDK v0.4.2
"""

import json
import redis
import time
from typing import Dict, Any, List
from datetime import datetime

# ============================================================================
# ИМПОРТ КОНФИГА СНАЧАЛА
# ============================================================================

from config import (
    MISTRAL_API_KEY, MISTRAL_MODEL, MISTRAL_GENERATION_PARAMS,
    get_redis_config, QUEUE_AGENT_2_INPUT, QUEUE_AGENT_2_OUTPUT,
    QUEUE_AGENT_3_INPUT, QUEUE_AGENT_4_INPUT, DEFAULT_RULES, setup_logging
)

logger = setup_logging("АГЕНТ 2")

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ MISTRAL AI
# ============================================================================

mistral_client = None
MISTRAL_VERSION = "none"

logger.info("🔧 Инициализация Mistral AI...")

try:
    # Импортируем клиент
    from mistralai.client import MistralClient
    logger.info("✅ Импорт mistralai.client успешен")
    
    # Проверяем API ключ
    if not MISTRAL_API_KEY:
        logger.error("❌ MISTRAL_API_KEY не установлен в config!")
        mistral_client = None
    else:
        logger.info(f"✅ API ключ найден (длина: {len(MISTRAL_API_KEY)})")
        
        # Создаём клиент
        try:
            mistral_client = MistralClient(api_key=MISTRAL_API_KEY)
            MISTRAL_VERSION = "v0.4.2 (legacy)"
            logger.info("✅ Mistral клиент успешно создан")
            
            # Тестируем подключение (быстрый запрос)
            logger.info("🧪 Тестирую подключение к API...")
            test_msg = [{"role": "user", "content": "OK"}]
            test_response = mistral_client.chat(
                model=MISTRAL_MODEL,
                messages=test_msg,
                max_tokens=5
            )
            logger.info("✅ MISTRAL API ПОДКЛЮЧЕН И РАБОТАЕТ")
            
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации MistralClient: {e}")
            logger.error(f"   Тип ошибки: {type(e).__name__}")
            mistral_client = None

except ImportError as e:
    logger.error(f"❌ Ошибка импорта mistralai: {e}")
    logger.error("   Установите: pip install mistralai==0.4.2")
    mistral_client = None

except Exception as e:
    logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА при инициализации: {e}")
    logger.error(f"   Тип: {type(e).__name__}")
    mistral_client = None

# ============================================================================
# ПРОМПТ ДЛЯ MISTRAL
# ============================================================================

MODERATION_PROMPT = """Ты модератор чата. Анализируй сообщение и определи нарушает ли оно правила чата.

ПРАВИЛА ЧАТА:
{rules}

СООБЩЕНИЕ ПОЛЬЗОВАТЕЛЯ: "{message}"

ТРЕБОВАНИЯ:
1. Ответь ТОЛЬКО JSON (без других текстов!)
2. Severity: число от 0 до 10 (0=OK, 10=критично)
3. Confidence: число от 0 до 100 (твоя уверенность)

JSON ФОРМАТ (ОБЯЗАТЕЛЬНО):
{{
  "is_violation": boolean,
  "type": "obscene|hate_speech|threat|spam|violence|sexual|none",
  "severity": число,
  "confidence": число,
  "action": "ban|mute|warn|none",
  "reason": "краткое объяснение"
}}"""

# ============================================================================
# ФУНКЦИЯ АНАЛИЗА
# ============================================================================

def analyze_with_mistral(message: str, rules: List[str]) -> Dict[str, Any]:
    """
    Анализирует сообщение с помощью Mistral AI
    """
    try:
        if not mistral_client:
            logger.error("❌ Mistral клиент не доступен")
            return {
                "is_violation": False,
                "type": "unknown",
                "severity": 0,
                "confidence": 0,
                "action": "none",
                "reason": "Mistral не подключен"
            }
        
        # Форматируем правила
        rules_text = "\n".join([f"- {rule}" for rule in rules]) if rules else "- Стандартные правила чата"
        
        # Создаём промпт
        prompt = MODERATION_PROMPT.format(rules=rules_text, message=message)
        
        # Создаём сообщение в формате legacy SDK (dict, не ChatMessage!)
        messages = [
            {"role": "user", "content": prompt}
        ]
        
        logger.info(f"📡 Отправляю запрос к {MISTRAL_MODEL}...")
        
        # Вызываем API
        response = mistral_client.chat(
            model=MISTRAL_MODEL,
            messages=messages,
            **MISTRAL_GENERATION_PARAMS
        )
        
        # Получаем текст ответа
        content = response.choices[0].message.content
        logger.info(f"📝 Ответ Mistral: {content[:150]}")
        
        # Извлекаем JSON из ответа
        json_start = content.find("{")
        json_end = content.rfind("}") + 1
        
        if json_start < 0 or json_end <= json_start:
            logger.error(f"❌ JSON не найден в ответе Mistral: {content}")
            return {
                "is_violation": False,
                "type": "unknown",
                "severity": 0,
                "confidence": 0,
                "action": "none",
                "reason": "Ошибка парсинга ответа"
            }
        
        # Парсим JSON
        json_str = content[json_start:json_end]
        result = json.loads(json_str)
        
        # Нормализуем значения
        severity = int(result.get("severity", 0))
        severity = min(10, max(0, severity))
        
        confidence = int(result.get("confidence", 50))
        confidence = min(100, max(0, confidence))
        
        action = result.get("action", "none")
        if action not in ["ban", "mute", "warn", "none"]:
            action = "warn" if result.get("is_violation") else "none"
        
        is_violation = result.get("is_violation", False)
        violation_type = result.get("type", "unknown")
        reason = result.get("reason", "Анализ завершен")
        
        logger.info(f"✅ АНАЛИЗ: is_violation={is_violation}, severity={severity}, confidence={confidence}%, action={action}, type={violation_type}")
        
        return {
            "is_violation": is_violation,
            "type": violation_type,
            "severity": severity,
            "confidence": confidence,
            "action": action,
            "reason": reason
        }
    
    except json.JSONDecodeError as e:
        logger.error(f"❌ JSON парсинг ошибка: {e}")
        return {
            "is_violation": False,
            "type": "unknown",
            "severity": 0,
            "confidence": 0,
            "action": "none",
            "reason": f"Ошибка парсинга JSON: {str(e)}"
        }
    except Exception as e:
        logger.error(f"❌ Ошибка анализа Mistral: {e}")
        return {
            "is_violation": False,
            "type": "unknown",
            "severity": 0,
            "confidence": 0,
            "action": "none",
            "reason": f"Ошибка анализа: {str(e)}"
        }

# ============================================================================
# ОСНОВНАЯ ФУНКЦИЯ АГЕНТА 2
# ============================================================================

def moderation_agent_2(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Главная функция агента 2 - аналитика сообщений
    """
    
    # Извлекаем входные данные
    message = input_data.get("message", "")
    rules = input_data.get("rules", DEFAULT_RULES)
    user_id = input_data.get("user_id")
    username = input_data.get("username", "unknown")
    chat_id = input_data.get("chat_id")
    message_id = input_data.get("message_id")
    message_link = input_data.get("message_link", "")
    media_type = input_data.get("media_type", "")
    
    logger.info(f"🔍 Анализирую сообщение от @{username}: '{message[:45]}...'")
    
    # Обработка пустых сообщений
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
            f"⚠️ НАРУШЕНИЕ НАЙДЕНО: "
            f"type={analysis_result['type']}, "
            f"severity={analysis_result['severity']}/10, "
            f"confidence={analysis_result['confidence']}%, "
            f"action={analysis_result['action']}"
        )
    else:
        logger.info(f"✅ СООБЩЕНИЕ ОК: confidence={analysis_result['confidence']}%")
    
    return output

# ============================================================================
# REDIS WORKER
# ============================================================================

class Agent2Worker:
    """
    Worker для обработки сообщений из Redis очереди
    """
    
    def __init__(self):
        """Инициализация подключения к Redis"""
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
        
        logger.info("=" * 60)
        logger.info("✅ АГЕНТ 2 ЗАПУЩЕН")
        logger.info("=" * 60)
        logger.info(f"📊 Модель: {MISTRAL_MODEL}")
        logger.info(f"📥 SDK: {MISTRAL_VERSION}")
        logger.info(f"🔔 Входная очередь: {QUEUE_AGENT_2_INPUT}")
        logger.info(f"📤 Выходная очередь: {QUEUE_AGENT_2_OUTPUT}")
        logger.info("⏱️ Нажмите Ctrl+C для остановки")
        logger.info("=" * 60 + "\n")
        
        try:
            while True:
                try:
                    # Получаем сообщение из очереди
                    result = self.redis_client.blpop(QUEUE_AGENT_2_INPUT, timeout=1)
                    
                    if result is None:
                        continue
                    
                    queue_name, message_data = result
                    logger.info("📨 Получено новое сообщение из очереди")
                    
                    # Парсим JSON
                    try:
                        input_data = json.loads(message_data)
                    except json.JSONDecodeError as e:
                        logger.error(f"❌ Ошибка парсинга JSON: {e}")
                        continue
                    
                    # ✅ ОБРАБАТЫВАЕМ СООБЩЕНИЕ
                    output = moderation_agent_2(input_data)
                    
                    # ✅ ОТПРАВЛЯЕМ РЕЗУЛЬТАТЫ
                    try:
                        result_json = json.dumps(output, ensure_ascii=False)
                        
                        # СНАЧАЛА в очередь БОТа (QUEUE_AGENT_2_OUTPUT)
                        self.redis_client.rpush(QUEUE_AGENT_2_OUTPUT, result_json)
                        logger.info(
                            f"📤 БОТ: action={output.get('action')}, "
                            f"severity={output.get('severity')}, "
                            f"is_violation={output.get('is_violation')}"
                        )
                        
                        # Потом в очереди агентов 3 и 4 (если это нарушение)
                        if output.get("is_violation"):
                            self.redis_client.rpush(QUEUE_AGENT_3_INPUT, result_json)
                            self.redis_client.rpush(QUEUE_AGENT_4_INPUT, result_json)
                            logger.info(f"📤 АГЕНТЫ 3, 4: нарушение отправлено")
                    
                    except Exception as e:
                        logger.error(f"❌ Ошибка отправки результата в Redis: {e}")
                    
                    logger.info("✅ Анализ завершен\n")
                
                except Exception as e:
                    logger.error(f"❌ Ошибка в цикле обработки: {e}")
                    time.sleep(1)
        
        except KeyboardInterrupt:
            logger.info("\n" + "=" * 60)
            logger.info("❌ АГЕНТ 2 ОСТАНОВЛЕН (Ctrl+C)")
            logger.info("=" * 60)
        finally:
            logger.info("Агент 2 завершил работу")

# ============================================================================
# ТОЧКА ВХОДА
# ============================================================================

if __name__ == "__main__":
    if not mistral_client:
        logger.error("=" * 60)
        logger.error("❌ КРИТИЧЕСКАЯ ОШИБКА: Mistral НЕ ПОДКЛЮЧЕН")
        logger.error("=" * 60)
        logger.error("Проверьте:")
        logger.error("1. MISTRAL_API_KEY в config.py")
        logger.error("2. Установлена ли: pip install mistralai==0.4.2")
        logger.error("3. Есть ли интернет")
        logger.error("4. Валидный ли API ключ")
        logger.error("=" * 60)
        exit(1)
    
    try:
        worker = Agent2Worker()
        worker.run()
    except KeyboardInterrupt:
        logger.info("Выход из программы")
    except Exception as e:
        logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        import traceback
        logger.error(traceback.format_exc())
