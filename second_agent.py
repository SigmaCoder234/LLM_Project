#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🤖 АГЕНТ №2 — ГЛАВНЫЙ АНАЛИТИК (v1.5 STRICT)
✅ Улучшенный промпт для обнаружения русского мата
✅ Жёсткая модерация
"""

import json
import redis
import time
from typing import Dict, Any, List
from datetime import datetime

# ============================================================================
# ИМПОРТ КОНФИГА
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
    from mistralai.client import MistralClient
    logger.info("✅ Импорт mistralai.client успешен")
    
    if not MISTRAL_API_KEY:
        logger.error("❌ MISTRAL_API_KEY не установлен в config!")
        mistral_client = None
    else:
        logger.info(f"✅ API ключ найден (длина: {len(MISTRAL_API_KEY)})")
        
        try:
            mistral_client = MistralClient(api_key=MISTRAL_API_KEY)
            MISTRAL_VERSION = "v0.4.2 (legacy)"
            logger.info("✅ Mistral клиент создан")
            
            # Тест подключения
            logger.info("🧪 Тестирую подключение к API...")
            test_msg = [{"role": "user", "content": "test"}]
            test_response = mistral_client.chat(
                model=MISTRAL_MODEL,
                messages=test_msg,
                max_tokens=5
            )
            logger.info("✅ MISTRAL API РАБОТАЕТ")
            
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации: {e}")
            mistral_client = None

except ImportError as e:
    logger.error(f"❌ Ошибка импорта mistralai: {e}")
    mistral_client = None

except Exception as e:
    logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
    mistral_client = None

logger.info(f"СТАТУС: mistral_client = {'OK' if mistral_client else 'FAILED'}")

# ============================================================================
# ЖЁСТКИЙ ПРОМПТ ДЛЯ МОДЕРАЦИИ
# ============================================================================

MODERATION_PROMPT = """Ты СТРОГИЙ модератор чата. Твоя задача - ВЫЛОВИТЬ все нарушения.

ПРАВИЛА ЧАТА:
{rules}

СООБЩЕНИЕ ПОЛЬЗОВАТЕЛЯ: "{message}"

ИНСТРУКЦИИ ДЛЯ АНАЛИЗА:
1. Проверь каждое слово на мат
2. Русский мат (хуй, пизда, блядь, еб, сука, ебать, пиздить) = VIOLATION, severity=10
3. Оскорбления (тупой, дурак, идиот, мудак) = VIOLATION, severity=7
4. Угрозы/насилие = VIOLATION, severity=9
5. Спам/реклама = VIOLATION, severity=5
6. Дискриминация = VIOLATION, severity=8
7. Если ничего не найдено = is_violation=false, severity=0

ОТВЕТЬ ТОЛЬКО JSON (без других текстов):
{{
  "is_violation": true или false,
  "type": "obscene|hate_speech|threat|spam|violence|sexual|harassment|none",
  "severity": число от 0 до 10,
  "confidence": число от 0 до 100,
  "action": "ban|mute|warn|none",
  "reason": "краткое объяснение почему это нарушение"
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
        
        # Создаём сообщение
        messages = [
            {"role": "user", "content": prompt}
        ]
        
        logger.info(f"📡 Анализирую: '{message[:50]}...'")
        
        # Вызываем API
        response = mistral_client.chat(
            model=MISTRAL_MODEL,
            messages=messages,
            **MISTRAL_GENERATION_PARAMS
        )
        
        # Получаем ответ
        content = response.choices[0].message.content
        logger.info(f"📝 Ответ Mistral: {content[:200]}")
        
        # Извлекаем JSON
        json_start = content.find("{")
        json_end = content.rfind("}") + 1
        
        if json_start < 0 or json_end <= json_start:
            logger.error(f"❌ JSON не найден: {content}")
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
        
        # Нормализуем
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
        
        # ЛОГИРОВАНИЕ РЕЗУЛЬТАТА
        if is_violation:
            logger.warning(
                f"⚠️ НАРУШЕНИЕ НАЙДЕНО: type={violation_type}, "
                f"severity={severity}/10, confidence={confidence}%, action={action}"
            )
        else:
            logger.info(f"✅ OK: confidence={confidence}%")
        
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
            "reason": f"Ошибка парсинга JSON"
        }
    except Exception as e:
        logger.error(f"❌ Ошибка анализа: {e}")
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
    
    logger.info(f"🔍 От @{username}: '{message[:45]}...'")
    
    # Обработка пустых сообщений
    if not message or not message.strip():
        logger.warning(f"⚠️ Пустое сообщение")
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
    
    # ✅ АНАЛИЗ
    analysis_result = analyze_with_mistral(message, rules)
    
    # ✅ ВЫХОД
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
                    logger.info("📨 Получено новое сообщение")
                    
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
                        
                        # В очередь БОТа
                        self.redis_client.rpush(QUEUE_AGENT_2_OUTPUT, result_json)
                        logger.info(
                            f"📤 БОТ: action={output.get('action')}, "
                            f"severity={output.get('severity')}, "
                            f"is_violation={output.get('is_violation')}"
                        )
                        
                        # В очереди агентов (если нарушение)
                        if output.get("is_violation"):
                            self.redis_client.rpush(QUEUE_AGENT_3_INPUT, result_json)
                            self.redis_client.rpush(QUEUE_AGENT_4_INPUT, result_json)
                            logger.info(f"📤 АГЕНТЫ 3, 4: нарушение отправлено")
                    
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
    if not mistral_client:
        logger.error("❌ КРИТИЧЕСКАЯ ОШИБКА: Mistral НЕ подключен!")
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
        
