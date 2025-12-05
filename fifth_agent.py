#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
АГЕНТ №5 — АРБИТР (ФИНАЛЬНОЕ РЕШЕНИЕ)
======================================

Роль: Принимает решение на основе вердиктов от Агентов 3 и 4
- Если решения СОВПАДАЮТ → принимает это решение
- Если расходятся → Mistral AI выбирает финальное решение
- Выдает ОКОНЧАТЕЛЬНОЕ решение для исполнения ботом
"""

import json
import redis
import time
from typing import Dict, Any, List, Optional
from datetime import datetime
import uuid

try:
    from mistralai import Mistral
    from mistralai import UserMessage, SystemMessage
    MISTRAL_IMPORT_SUCCESS = True
    MISTRAL_IMPORT_VERSION = "v1.0+ (новый SDK)"
except ImportError:
    try:
        from mistralai.client import MistralClient as Mistral
        from mistralai.models.chat_completion import ChatMessage
        def UserMessage(content): return {"role": "user", "content": content}
        def SystemMessage(content): return {"role": "system", "content": content}
        MISTRAL_IMPORT_SUCCESS = True
        MISTRAL_IMPORT_VERSION = "v0.4.2 (legacy)"
    except ImportError:
        MISTRAL_IMPORT_SUCCESS = False
        MISTRAL_IMPORT_VERSION = "none"
        class Mistral:
            def __init__(self, api_key): pass
            def chat(self, **kwargs):
                raise ImportError("Mistral AI не установлен")
        def UserMessage(content): return {"role": "user", "content": content}
        def SystemMessage(content): return {"role": "system", "content": content}

from config import (
    MISTRAL_API_KEY,
    MISTRAL_MODEL,
    get_redis_config,
    QUEUE_AGENT_5_INPUT,
    QUEUE_AGENT_6_OUTPUT,  # Отправляем результат в Агента 6 или боту
    DEFAULT_RULES,
    setup_logging,
)

logger = setup_logging("АГЕНТ 5")

if MISTRAL_IMPORT_SUCCESS:
    logger.info(f"✅ Mistral AI импортирован ({MISTRAL_IMPORT_VERSION})")
else:
    logger.error("❌ Mistral AI не импортирован")

if MISTRAL_IMPORT_SUCCESS and MISTRAL_API_KEY:
    try:
        mistral_client = Mistral(api_key=MISTRAL_API_KEY)
        logger.info("✅ Mistral AI клиент создан")
    except Exception as e:
        logger.error(f"❌ Ошибка создания клиента: {e}")
        mistral_client = None
else:
    mistral_client = None

# ============================================================================
# РАЗРЕШЕНИЕ КОНФЛИКТОВ ЧЕРЕЗ MISTRAL
# ============================================================================

def resolve_conflict_with_mistral(
    message: str,
    agent3_action: str,
    agent3_reason: str,
    agent3_confidence: int,
    agent4_action: str,
    agent4_reason: str,
    agent4_confidence: int,
    agent2_severity: int,
    rules: List[str]
) -> str:
    """
    Когда Агент 3 и 4 не согласны - Mistral выбирает финальное решение
    """
    
    if not MISTRAL_IMPORT_SUCCESS or not mistral_client:
        logger.warning("⚠️ Mistral недоступен, выбираем более строгое решение")
        # Выбираем более строгое действие
        action_priority = {"ban": 3, "mute": 2, "warn": 1, "none": 0}
        return agent4_action if action_priority.get(agent4_action, 0) >= action_priority.get(agent3_action, 0) else agent3_action
    
    try:
        rules_text = "\n".join([f"{i+1}. {rule}" for i, rule in enumerate(rules)])
        
        system_msg = f"""Ты — ФИНАЛЬНЫЙ АРБИТР системы модерации.
Два модератора дали РАЗНЫЕ решения. Ты должен выбрать правильное.

ПРАВИЛА ЧАТА:
{rules_text}

КОНСЕРВАТИВНЫЙ МОДЕРАТОР (Агент 3):
- Решение: {agent3_action}
- Уверенность: {agent3_confidence}%
- Причина: {agent3_reason[:150]}

СТРОГИЙ МОДЕРАТОР (Агент 4):
- Решение: {agent4_action}
- Уверенность: {agent4_confidence}%
- Причина: {agent4_reason[:150]}

СООБЩЕНИЕ: "{message}"
СЕРЬЕЗНОСТЬ: {agent2_severity}/10

ВЫБЕРИ ФИНАЛЬНОЕ РЕШЕНИЕ: ban/mute/warn/none
Учитывай: серьезность, согласие двух модераторов, правила чата.
Если один модератор намного увереннее - доверься ему.
Ответь ОДНИМ СЛОВОМ: ban или mute или warn или none"""

        if MISTRAL_IMPORT_VERSION.startswith("v1.0"):
            messages = [
                SystemMessage(content=system_msg),
                UserMessage(content="Выбери решение.")
            ]
            response = mistral_client.chat.complete(
                model=MISTRAL_MODEL,
                messages=messages,
                temperature=0.2,
                max_tokens=50
            )
            content = response.choices[0].message.content
        else:
            messages = [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": "Выбери решение."}
            ]
            response = mistral_client.chat(
                model=MISTRAL_MODEL,
                messages=messages,
                temperature=0.2,
                max_tokens=50
            )
            content = response.choices[0].message.content
        
        content_lower = content.lower()
        
        if "ban" in content_lower:
            return "ban"
        elif "mute" in content_lower:
            return "mute"
        elif "warn" in content_lower:
            return "warn"
        else:
            return "none"
    
    except Exception as e:
        logger.error(f"❌ Ошибка разрешения конфликта: {e}")
        # Fallback: выбираем более строгое
        action_priority = {"ban": 3, "mute": 2, "warn": 1, "none": 0}
        return agent4_action if action_priority.get(agent4_action, 0) >= action_priority.get(agent3_action, 0) else agent3_action

# ============================================================================
# ОСНОВНАЯ ФУНКЦИЯ АГЕНТА 5
# ============================================================================

def moderation_agent_5(agent3_result: Dict[str, Any], agent4_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    АГЕНТ 5 — АРБИТР
    
    Получает решения от Агентов 3 и 4, выбирает финальное
    """
    
    message = agent3_result.get("message", "")
    user_id = agent3_result.get("user_id")
    username = agent3_result.get("username", "unknown")
    chat_id = agent3_result.get("chat_id")
    message_id = agent3_result.get("message_id")
    message_link = agent3_result.get("message_link", "")
    
    agent3_action = agent3_result.get("action", "none")
    agent4_action = agent4_result.get("action", "none")
    
    agent3_confidence = agent3_result.get("confidence", 0)
    agent4_confidence = agent4_result.get("confidence", 0)
    
    logger.info(f"⚖️ АРБИТРАЖ: А3={agent3_action}({agent3_confidence}%) vs А4={agent4_action}({agent4_confidence}%)")
    
    # Проверяем совпадение решений
    if agent3_action == agent4_action:
        logger.info(f"✅ СОВПАДЕНИЕ: оба согласны на {agent3_action}")
        final_action = agent3_action
        final_duration = agent3_result.get("action_duration", 0)
        conflict_resolved_by = "agreement"
    else:
        logger.warning(f"⚠️ КОНФЛИКТ: {agent3_action} vs {agent4_action}, вызываем Mistral")
        
        final_action = resolve_conflict_with_mistral(
            message=message,
            agent3_action=agent3_action,
            agent3_reason=agent3_result.get("reason", ""),
            agent3_confidence=agent3_confidence,
            agent4_action=agent4_action,
            agent4_reason=agent4_result.get("reason", ""),
            agent4_confidence=agent4_confidence,
            agent2_severity=agent3_result.get("agent2_severity", 0),
            rules=agent3_result.get("rules", DEFAULT_RULES)
        )
        
        # Определяем длительность
        if final_action == "mute":
            severity = agent3_result.get("agent2_severity", 5)
            if severity >= 8:
                final_duration = 1440
            elif severity >= 6:
                final_duration = 360
            else:
                final_duration = 120
        else:
            final_duration = 0
        
        conflict_resolved_by = "mistral"
        logger.warning(f"🤖 Mistral выбрал: {final_action}")
    
    # Формируем финальный результат
    output = {
        "agent_id": 5,
        "agent_name": "Арбитр",
        "decision_id": str(uuid.uuid4()),
        "message": message,
        "user_id": user_id,
        "username": username,
        "chat_id": chat_id,
        "message_id": message_id,
        "message_link": message_link,
        # Решения модераторов
        "agent3_decision": {
            "action": agent3_action,
            "duration": agent3_result.get("action_duration", 0),
            "confidence": agent3_confidence,
            "style": "conservative"
        },
        "agent4_decision": {
            "action": agent4_action,
            "duration": agent4_result.get("action_duration", 0),
            "confidence": agent4_confidence,
            "style": "strict"
        },
        # ФИНАЛЬНОЕ РЕШЕНИЕ
        "final_action": final_action,
        "final_action_duration": final_duration,
        "conflict": agent3_action != agent4_action,
        "conflict_resolved_by": conflict_resolved_by,
        "status": "success",
        "timestamp": datetime.now().isoformat()
    }
    
    if final_action != "none":
        logger.warning(f"🚨 ФИНАЛЬНОЕ РЕШЕНИЕ: {final_action.upper()} для @{username}")
    else:
        logger.info(f"✅ ФИНАЛЬНОЕ РЕШЕНИЕ: НЕ ДЕЙСТВОВАТЬ для @{username}")
    
    return output

# ============================================================================
# REDIS WORKER
# ============================================================================

class Agent5Worker:
    def __init__(self):
        try:
            redis_config = get_redis_config()
            self.redis_client = redis.Redis(**redis_config)
            self.redis_client.ping()
            logger.info("✅ Подключение к Redis успешно")
        except Exception as e:
            logger.error(f"❌ Ошибка подключения: {e}")
            raise
        
        self.pending_decisions = {}  # Хранилище решений агентов
    
    def process_result(self, message_data: str) -> Optional[Dict[str, Any]]:
        """Обрабатывает результат от Агента 3 или 4"""
        try:
            agent_result = json.loads(message_data)
            agent_id = agent_result.get("agent_id")
            message_id = agent_result.get("message_id")
            
            if not message_id:
                logger.error("❌ Нет message_id")
                return None
            
            # Сохраняем результат
            if message_id not in self.pending_decisions:
                self.pending_decisions[message_id] = {}
            
            self.pending_decisions[message_id][f"agent_{agent_id}"] = agent_result
            logger.info(f"📨 Получен результат от Агента {agent_id}")
            
            # Проверяем, есть ли результаты от обоих
            if "agent_3" in self.pending_decisions[message_id] and "agent_4" in self.pending_decisions[message_id]:
                logger.info(f"🎯 Есть результаты от обоих агентов")
                
                agent3_data = self.pending_decisions[message_id]["agent_3"]
                agent4_data = self.pending_decisions[message_id]["agent_4"]
                
                final_decision = moderation_agent_5(agent3_data, agent4_data)
                
                del self.pending_decisions[message_id]
                
                return final_decision
            
            return None
        
        except json.JSONDecodeError as e:
            logger.error(f"❌ JSON error: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Error: {e}")
            return None
    
    def send_decision(self, result: Dict[str, Any]) -> bool:
        """Отправляет финальное решение"""
        try:
            result_json = json.dumps(result, ensure_ascii=False)
            self.redis_client.rpush(QUEUE_AGENT_6_OUTPUT, result_json)
            logger.info("📤 Финальное решение отправлено")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {e}")
            return False
    
    def run(self):
        """Главный цикл"""
        logger.info("✅ Агент 5 запущен (Арбитр)")
        logger.info(f"   Слушаю очередь: {QUEUE_AGENT_5_INPUT}")
        logger.info("   Нажмите Ctrl+C для остановки\n")
        
        try:
            while True:
                try:
                    result = self.redis_client.blpop(QUEUE_AGENT_5_INPUT, timeout=1)
                    
                    if result is None:
                        continue
                    
                    queue_name, message_data = result
                    logger.info("📨 Получено решение от модератора")
                    
                    final_decision = self.process_result(message_data)
                    
                    if final_decision:
                        self.send_decision(final_decision)
                        logger.info("✅ Финальное решение готово\n")
                
                except Exception as e:
                    logger.error(f"❌ Ошибка в цикле: {e}")
                    time.sleep(1)
        
        except KeyboardInterrupt:
            logger.info("\n❌ Агент 5 остановлен (Ctrl+C)")

if __name__ == "__main__":
    try:
        worker = Agent5Worker()
        worker.run()
    except KeyboardInterrupt:
        logger.info("Выход")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")