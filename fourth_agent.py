#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
АГЕНТ №4 — СТРОГИЙ МОДЕРАТОР
=============================

Роль: Анализирует вывод Агента 2 со СТРОГИМ подходом
- Требует уверенность >= 50% для согласия с наказанием
- Предпочитает более жесткие действия (warn < mute < ban)
- Защищает от пропуска реальных нарушений

Схема: Берет результат от Агента 2 → применяет строгую логику → отправляет в Агента 5
"""

import json
import redis
import time
from typing import Dict, Any, List
from datetime import datetime

from config import (
    get_redis_config,
    QUEUE_AGENT_4_INPUT,
    QUEUE_AGENT_5_INPUT,
    DEFAULT_RULES,
    setup_logging,
    determine_action,
)

logger = setup_logging("АГЕНТ 4")

# ============================================================================
# СТРОГАЯ ЛОГИКА МОДЕРАЦИИ
# ============================================================================

def apply_strict_moderation(agent2_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Применяет строгий подход к результату Агента 2.
    
    Правило: Требует уверенность >= 50% для согласия с наказанием
    """
    
    confidence = agent2_result.get("confidence", 0)
    severity = agent2_result.get("severity", 0)
    violation_type = agent2_result.get("type", "none")
    agent2_action = agent2_result.get("action", "none")
    is_violation = agent2_result.get("is_violation", False)
    
    logger.info(
        f"🔍 Строгий анализ: уверенность={confidence}%, "
        f"серьезность={severity}, тип={violation_type}"
    )
    
    # СТРОГОЕ ПРАВИЛО: даже низкая уверенность может привести к наказанию
    if confidence < 50:
        # Очень низкая уверенность - игнорируем если нет явного нарушения
        if not is_violation:
            logger.info(f"⚠️ Низкая уверенность ({confidence}%) и нет явного нарушения")
            final_action = "none"
            final_duration = 0
        else:
            # Есть нарушение - даже при низкой уверенности принимаем меры
            logger.info(f"⚠️ Низкая уверенность ({confidence}%), но есть нарушение - берем warn")
            final_action = "warn"
            final_duration = 0
    else:
        # Уверенность >= 50% - принимаем рекомендацию или даже усиливаем
        final_action = agent2_action
        
        # Усиливаем действие если серьезность высокая
        if severity >= 8 and final_action == "warn":
            logger.info(f"📈 Серьезность {severity}/10, усиливаем warn на mute")
            final_action = "mute"
        elif severity >= 9 and final_action == "mute":
            logger.info(f"📈 Серьезность {severity}/10, усиливаем mute на ban")
            final_action = "ban"
        
        # Определяем длительность для mute
        if final_action == "mute":
            if severity >= 8:
                final_duration = 1440  # 24 часа
            elif severity >= 6:
                final_duration = 360   # 6 часов
            else:
                final_duration = 120   # 2 часа
        else:
            final_duration = 0
    
    return {
        "agent4_action": final_action,
        "agent4_action_duration": final_duration,
        "agent4_reason": f"Строгий подход: {agent2_result['explanation']}",
        "agent4_confidence": min(confidence + 10, 100),  # Добавляем 10% за строгость
    }

# ============================================================================
# ОСНОВНАЯ ФУНКЦИЯ АГЕНТА 4
# ============================================================================

def moderation_agent_4(agent2_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    АГЕНТ 4 — Строгий модератор
    
    Берет анализ от Агента 2 и применяет строгую логику
    """
    
    message = agent2_result.get("message", "")
    user_id = agent2_result.get("user_id")
    username = agent2_result.get("username", "unknown")
    chat_id = agent2_result.get("chat_id")
    message_id = agent2_result.get("message_id")
    
    logger.info(f"📋 Строгая оценка от @{username}: '{message[:50]}...'")
    
    # Применяем строгую логику
    strict_result = apply_strict_moderation(agent2_result)
    
    # Формируем выход
    output = {
        "agent_id": 4,
        "agent_name": "Строгий модератор",
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
        # Строгий вердикт
        "action": strict_result["agent4_action"],
        "action_duration": strict_result["agent4_action_duration"],
        "reason": strict_result["agent4_reason"],
        "confidence": strict_result["agent4_confidence"],
        "moderation_style": "strict",
        "status": "success",
        "timestamp": datetime.now().isoformat()
    }
    
    logger.info(f"✅ Строгое решение: {strict_result['agent4_action']}")
    
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
            logger.info("✅ Подключение к Redis успешно")
        except Exception as e:
            logger.error(f"❌ Не удалось подключиться к Redis: {e}")
            raise
    
    def process_message(self, message_data: str) -> Dict[str, Any]:
        """Обрабатывает результат от Агента 2"""
        try:
            agent2_result = json.loads(message_data)
            result = moderation_agent_4(agent2_result)
            return result
        except json.JSONDecodeError as e:
            logger.error(f"❌ Невалидный JSON: {e}")
            return {"agent_id": 4, "status": "json_error", "error": str(e)}
        except Exception as e:
            logger.error(f"❌ Ошибка обработки: {e}")
            return {"agent_id": 4, "status": "error", "error": str(e)}
    
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
        logger.info("✅ Агент 4 запущен (Строгий модератор)")
        logger.info(f"   Слушаю очередь: {QUEUE_AGENT_4_INPUT}")
        logger.info("   Нажмите Ctrl+C для остановки\n")
        
        try:
            while True:
                try:
                    result = self.redis_client.blpop(QUEUE_AGENT_4_INPUT, timeout=1)
                    
                    if result is None:
                        continue
                    
                    queue_name, message_data = result
                    logger.info("📨 Получено решение от Агента 2")
                    
                    output = self.process_message(message_data)
                    
                    if output.get("status") != "error":
                        self.send_result(output)
                    
                    logger.info("✅ Строгая оценка завершена\n")
                
                except Exception as e:
                    logger.error(f"❌ Ошибка в цикле: {e}")
                    time.sleep(1)
        
        except KeyboardInterrupt:
            logger.info("\n❌ Агент 4 остановлен (Ctrl+C)")

if __name__ == "__main__":
    try:
        worker = Agent4Worker()
        worker.run()
    except KeyboardInterrupt:
        logger.info("Выход")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")