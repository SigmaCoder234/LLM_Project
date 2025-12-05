#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
АГЕНТ №3 — КОНСЕРВАТИВНЫЙ МОДЕРАТОР
====================================

Роль: Анализирует вывод Агента 2 с КОНСЕРВАТИВНЫМ подходом
- Требует высокую уверенность (75%+) для согласия с наказанием
- Предпочитает более мягкие действия (warn < mute < ban)
- Защищает от false positives

Схема: Берет результат от Агента 2 → применяет консервативную логику → отправляет в Агента 5
"""

import json
import redis
import time
from typing import Dict, Any, List
from datetime import datetime

from config import (
    get_redis_config,
    QUEUE_AGENT_3_INPUT,
    QUEUE_AGENT_5_INPUT,
    DEFAULT_RULES,
    setup_logging,
    determine_action,
)

logger = setup_logging("АГЕНТ 3")

# ============================================================================
# КОНСЕРВАТИВНАЯ ЛОГИКА МОДЕРАЦИИ
# ============================================================================

def apply_conservative_moderation(agent2_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Применяет консервативный подход к результату Агента 2.
    
    Правило: Требует уверенность >= 75% для согласия с наказанием
    """
    
    confidence = agent2_result.get("confidence", 0)
    severity = agent2_result.get("severity", 0)
    violation_type = agent2_result.get("type", "none")
    agent2_action = agent2_result.get("action", "none")
    
    logger.info(
        f"🔍 Консервативный анализ: уверенность={confidence}%, "
        f"серьезность={severity}, тип={violation_type}"
    )
    
    # КОНСЕРВАТИВНОЕ ПРАВИЛО: требуем высокую уверенность
    if confidence < 75:
        logger.info(f"⚠️ Уверенность < 75% ({confidence}%), понижаем действие")
        
        if agent2_action == "ban":
            final_action = "mute"
            final_duration = 60
        elif agent2_action == "mute":
            final_action = "warn"
            final_duration = 0
        elif agent2_action == "warn":
            final_action = "warn"
            final_duration = 0
        else:
            final_action = "none"
            final_duration = 0
    else:
        # Уверенность достаточна, принимаем рекомендацию
        final_action = agent2_action
        
        # Определяем длительность для mute
        if final_action == "mute":
            if severity >= 8:
                final_duration = 1440  # 24 часа
            elif severity >= 6:
                final_duration = 360   # 6 часов
            else:
                final_duration = 60    # 1 час
        else:
            final_duration = 0
    
    # Дополнительная консервативность: снижаем ban на mute
    if final_action == "ban" and severity < 8:
        logger.info(f"⚠️ Серьезность < 8, снижаем ban на mute (консервативный подход)")
        final_action = "mute"
        final_duration = 1440
    
    return {
        "agent3_action": final_action,
        "agent3_action_duration": final_duration,
        "agent3_reason": f"Консервативный подход: {agent2_result['explanation']}",
        "agent3_confidence": min(confidence, 95),  # Не выше 95%
    }

# ============================================================================
# ОСНОВНАЯ ФУНКЦИЯ АГЕНТА 3
# ============================================================================

def moderation_agent_3(agent2_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    АГЕНТ 3 — Консервативный модератор
    
    Берет анализ от Агента 2 и применяет консервативную логику
    """
    
    message = agent2_result.get("message", "")
    user_id = agent2_result.get("user_id")
    username = agent2_result.get("username", "unknown")
    chat_id = agent2_result.get("chat_id")
    message_id = agent2_result.get("message_id")
    
    logger.info(f"📋 Консервативная оценка от @{username}: '{message[:50]}...'")
    
    # Применяем консервативную логику
    conservative_result = apply_conservative_moderation(agent2_result)
    
    # Формируем выход
    output = {
        "agent_id": 3,
        "agent_name": "Консервативный модератор",
        "message": message,
        "user_id": user_id,
        "username": username,
        "chat_id": chat_id,
        "message_id": message_id,
        "message_link": agent2_result.get("message_link", ""),
        # Данные от Агента 2
        "agent2_type": agent2_result.get("type", "none"),
        "agent2_severity": agent2_result.get("severity", 0),
        "agent2_confidence": agent2_result.get("confidence", 0),
        "agent2_action": agent2_result.get("action", "none"),
        "agent2_explanation": agent2_result.get("explanation", ""),
        # Консервативный вердикт
        "action": conservative_result["agent3_action"],
        "action_duration": conservative_result["agent3_action_duration"],
        "reason": conservative_result["agent3_reason"],
        "confidence": conservative_result["agent3_confidence"],
        "moderation_style": "conservative",
        "status": "success",
        "timestamp": datetime.now().isoformat()
    }
    
    logger.info(f"✅ Консервативное решение: {conservative_result['agent3_action']}")
    
    return output

# ============================================================================
# REDIS WORKER
# ============================================================================

class Agent3Worker:
    def __init__(self):
        try:
            redis_config = get_redis_config()
            self.redis_client = redis.Redis(**redis_config)
            self.redis_client.ping()
            logger.info("✅ Подключение к Redis успешно")
        except Exception as e:
            logger.error(f"❌ Не удалось подключиться к Redis: {e}")
            raise
    
    def process_message(self, message_data: str) -> Dict[str, Any]:
        """Обрабатывает результат от Агента 2"""
        try:
            agent2_result = json.loads(message_data)
            result = moderation_agent_3(agent2_result)
            return result
        except json.JSONDecodeError as e:
            logger.error(f"❌ Невалидный JSON: {e}")
            return {"agent_id": 3, "status": "json_error", "error": str(e)}
        except Exception as e:
            logger.error(f"❌ Ошибка обработки: {e}")
            return {"agent_id": 3, "status": "error", "error": str(e)}
    
    def send_result(self, result: Dict[str, Any]) -> bool:
        """Отправляет результат в Агента 5"""
        try:
            result_json = json.dumps(result, ensure_ascii=False)
            self.redis_client.rpush(QUEUE_AGENT_5_INPUT, result_json)
            logger.info("📤 Результат отправлен в Агента 5")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {e}")
            return False
    
    def run(self):
        """Главный цикл"""
        logger.info("✅ Агент 3 запущен (Консервативный модератор)")
        logger.info(f"   Слушаю очередь: {QUEUE_AGENT_3_INPUT}")
        logger.info("   Нажмите Ctrl+C для остановки\n")
        
        try:
            while True:
                try:
                    result = self.redis_client.blpop(QUEUE_AGENT_3_INPUT, timeout=1)
                    
                    if result is None:
                        continue
                    
                    queue_name, message_data = result
                    logger.info("📨 Получено решение от Агента 2")
                    
                    output = self.process_message(message_data)
                    
                    if output.get("status") != "error":
                        self.send_result(output)
                    
                    logger.info("✅ Консервативная оценка завершена\n")
                
                except Exception as e:
                    logger.error(f"❌ Ошибка в цикле: {e}")
                    time.sleep(1)
        
        except KeyboardInterrupt:
            logger.info("\n❌ Агент 3 остановлен (Ctrl+C)")

if __name__ == "__main__":
    try:
        worker = Agent3Worker()
        worker.run()
    except KeyboardInterrupt:
        logger.info("Выход")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")