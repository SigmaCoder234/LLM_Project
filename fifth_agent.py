#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
АГЕНТ №5 — Арбитр многоагентной системы с определением финального действия
"""

import json
import redis
import time
from typing import Dict, Any, List, Optional
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

# Mistral AI импорты
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
        print("❌ Не удалось импортировать Mistral AI")
        MISTRAL_IMPORT_SUCCESS = False
        MISTRAL_IMPORT_VERSION = "none"
        class Mistral:
            def __init__(self, api_key): pass
            def chat(self, **kwargs):
                raise ImportError("Mistral AI не установлен")
        def UserMessage(content): return {"role": "user", "content": content}
        def SystemMessage(content): return {"role": "system", "content": content}

# Импортируем конфигурацию
from config import (
    MISTRAL_API_KEY,
    MISTRAL_MODEL,
    MISTRAL_GENERATION_PARAMS,
    get_redis_config,
    QUEUE_AGENT_5_INPUT,
    AGENT_PORTS,
    DEFAULT_RULES,
    setup_logging,
    determine_action
)

# ============================================================================
# ЛОГИРОВАНИЕ
# ============================================================================

logger = setup_logging("АГЕНТ 5")

if MISTRAL_IMPORT_SUCCESS:
    logger.info(f"✅ Mistral AI импортирован успешно ({MISTRAL_IMPORT_VERSION})")
else:
    logger.error("❌ Mistral AI не импортирован")

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ MISTRAL AI
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
# КЛАССЫ ДАННЫХ
# ============================================================================

class VerdictType(Enum):
    APPROVE = "approve"
    BAN = "ban"
    MUTE = "mute"
    WARN = "warn"
    DELETE = "delete"
    UNCERTAIN = "uncertain"

@dataclass
class AgentVerdict:
    agent_id: int
    action: str  # "ban", "mute", "warn", "delete", "none"
    action_duration: int  # минуты
    reason: str
    confidence: float
    violation_type: str
    severity: int
    timestamp: datetime
    
    def to_verdict_type(self) -> VerdictType:
        if self.action == "ban":
            return VerdictType.BAN
        elif self.action == "mute":
            return VerdictType.MUTE
        elif self.action == "warn":
            return VerdictType.WARN
        elif self.action == "delete":
            return VerdictType.DELETE
        else:
            return VerdictType.APPROVE

@dataclass
class Agent5Decision:
    decision_id: str
    message_id: int
    chat_id: int
    user_id: int
    username: str
    message_text: str
    final_action: str
    final_action_duration: int
    final_confidence: float
    reasoning: str
    agent3_action: str
    agent4_action: str
    agent3_severity: int
    agent4_severity: int
    was_conflict: bool
    conflict_resolved_by: str
    timestamp: datetime

# ============================================================================
# АРБИТРАЖНАЯ ЛОГИКА
# ============================================================================

class ModerationArbiter:
    """Арбитр для разрешения конфликтов между агентами 3 и 4"""
    
    def __init__(self):
        self.processed_count = 0
    
    def has_conflict(self, agent3: AgentVerdict, agent4: AgentVerdict) -> bool:
        """Проверка наличия конфликта между агентами"""
        
        # Конфликт если действия разные (ban vs none, mute vs warn и т.д.)
        actions_differ = agent3.action != agent4.action
        
        # Или если уверенность одного из них низкая
        low_confidence = agent3.confidence < 0.65 or agent4.confidence < 0.65
        
        # Или если серьезность сильно отличается
        severity_diff = abs(agent3.severity - agent4.severity) > 3
        
        return actions_differ or low_confidence or severity_diff
    
    def resolve_conflict_with_mistral(
        self, 
        agent3: AgentVerdict, 
        agent4: AgentVerdict, 
        message_text: str, 
        rules: List[str]
    ) -> tuple:
        """Разрешение конфликта между агентами с помощью Mistral AI"""
        
        logger.info("🤖 Разрешение конфликта с помощью Mistral AI...")
        
        if not MISTRAL_IMPORT_SUCCESS or not mistral_client:
            logger.warning("⚠️ Mistral AI недоступен, используем резервный алгоритм")
            return self.resolve_conflict_fallback(agent3, agent4, message_text)
        
        try:
            if not rules:
                rules = DEFAULT_RULES
            
            rules_text = "\n".join([f"{i+1}. {rule}" for i, rule in enumerate(rules)])
            
            system_message = f"""Ты — модератор Telegram чата. Два агента дали разные решения.

ПРАВИЛА ЧАТА:
{rules_text}

АНАЛИЗ АГЕНТОВ:

АГЕНТ 3 (Mistral AI):
- Действие: {agent3.action}
- Серьезность: {agent3.severity}/10
- Уверенность: {agent3.confidence*100:.0f}%
- Причина: {agent3.reason[:200]}

АГЕНТ 4 (Эвристика):
- Действие: {agent4.action}
- Серьезность: {agent4.severity}/10
- Уверенность: {agent4.confidence*100:.0f}%
- Причина: {agent4.reason[:200]}

ТВОЯ ЗАДАЧА:
1. Проанализируй оба решения
2. Прими окончательное решение
3. Определи действие: ban/mute/warn/delete/none
4. Если mute - укажи длительность в минутах
5. Объясни решение

Формат ответа:
ФИНАЛЬНОЕ ДЕЙСТВИЕ: [ban/mute/warn/delete/none]
ДЛИТЕЛЬНОСТЬ: [минуты или 0 для бана]
УВЕРЕННОСТЬ: [0-100]
ПРИЧИНА: [текст]"""
            
            user_message_text = f'Сообщение: "{message_text}"'
            
            # Создаем сообщения
            if MISTRAL_IMPORT_VERSION.startswith("v1.0"):
                messages = [
                    SystemMessage(content=system_message),
                    UserMessage(content=user_message_text)
                ]
            else:
                messages = [
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message_text}
                ]
            
            # Вызываем API
            if MISTRAL_IMPORT_VERSION.startswith("v1.0"):
                response = mistral_client.chat.complete(
                    model=MISTRAL_MODEL,
                    messages=messages,
                    temperature=MISTRAL_GENERATION_PARAMS.get("temperature", 0.1),
                    max_tokens=MISTRAL_GENERATION_PARAMS.get("max_tokens", 400)
                )
                content = response.choices[0].message.content
            else:
                response = mistral_client.chat(
                    model=MISTRAL_MODEL,
                    messages=messages,
                    temperature=MISTRAL_GENERATION_PARAMS.get("temperature", 0.1),
                    max_tokens=MISTRAL_GENERATION_PARAMS.get("max_tokens", 400)
                )
                content = response.choices[0].message.content
            
            # Парсим ответ
            content_lower = content.lower()
            
            # Определяем действие
            final_action = "none"
            if "финальное действие:" in content_lower:
                try:
                    action_line = [line for line in content.split('\n') if 'финальное действие:' in line.lower()][0]
                    action_text = action_line.lower()
                    if "ban" in action_text:
                        final_action = "ban"
                    elif "mute" in action_text:
                        final_action = "mute"
                    elif "warn" in action_text:
                        final_action = "warn"
                    elif "delete" in action_text:
                        final_action = "delete"
                except:
                    pass
            
            # Определяем длительность
            final_duration = 0
            if final_action == "mute" and "длительность:" in content_lower:
                try:
                    duration_line = [line for line in content.split('\n') if 'длительность:' in line.lower()][0]
                    duration_str = ''.join(filter(str.isdigit, duration_line))
                    if duration_str:
                        final_duration = int(duration_str)
                except:
                    pass
            
            # Определяем уверенность
            final_confidence = 0.8
            if "уверенность:" in content_lower:
                try:
                    conf_line = [line for line in content.split('\n') if 'уверенность:' in line.lower()][0]
                    conf_str = ''.join(filter(str.isdigit, conf_line))
                    if conf_str:
                        final_confidence = int(conf_str) / 100.0
                except:
                    pass
            
            reasoning = f"Mistral AI арбитр ({MISTRAL_IMPORT_VERSION}): {content}"
            
            logger.info(f"🤖 Mistral AI принял решение: {final_action} (уверенность: {final_confidence:.2f})")
            
            return final_action, final_duration, final_confidence, reasoning
        
        except Exception as e:
            logger.error(f"Ошибка Mistral AI арбитража: {e}")
            return self.resolve_conflict_fallback(agent3, agent4, message_text)
    
    def resolve_conflict_fallback(
        self, 
        agent3: AgentVerdict, 
        agent4: AgentVerdict, 
        message_text: str
    ) -> tuple:
        """Резервная логика разрешения конфликтов"""
        
        logger.info("🔍 Разрешение конфликта (резервный алгоритм)...")
        
        # Взвешиваем уверенность обоих агентов
        weight3 = agent3.confidence * (1 + agent3.severity / 10)
        weight4 = agent4.confidence * (1 + agent4.severity / 10)
        
        total_weight = weight3 + weight4
        if total_weight == 0:
            total_weight = 1
        
        agent3_percent = weight3 / total_weight
        
        logger.info(f"Веса: Agent3={agent3_percent:.2%}, Agent4={(1-agent3_percent):.2%}")
        
        # Если один агент значительно увереннее
        if weight3 > weight4 * 1.5 and agent3.severity >= 6:
            final_action = agent3.action
            final_duration = agent3.action_duration
            final_confidence = agent3.confidence * 0.95
            reasoning = f"Конфликт разрешен в пользу Агента №3 (вес {agent3_percent:.2%}). {agent3.reason}"
        
        elif weight4 > weight3 * 1.5 and agent4.severity >= 6:
            final_action = agent4.action
            final_duration = agent4.action_duration
            final_confidence = agent4.confidence * 0.95
            reasoning = f"Конфликт разрешен в пользу Агента №4 (вес {(1-agent3_percent):.2%}). {agent4.reason}"
        
        else:
            # Применяем свой анализ
            if agent3.severity > 7 or agent4.severity > 7:
                final_action = "mute"
                final_duration = 1440  # 24 часа
                final_confidence = 0.75
            elif agent3.severity > 5 or agent4.severity > 5:
                final_action = "warn"
                final_duration = 0
                final_confidence = 0.70
            else:
                final_action = "none"
                final_duration = 0
                final_confidence = 0.65
            
            reasoning = f"Конфликт разрешен комбинированным анализом. Среднее: серьезность={(agent3.severity + agent4.severity)/2:.1f}/10"
        
        logger.info(f"⚖️ Конфликт разрешен: {final_action} (уверенность: {final_confidence:.2f})")
        
        return final_action, final_duration, final_confidence, reasoning
    
    def make_decision(self, agent3_data: Dict[str, Any], agent4_data: Dict[str, Any]) -> Agent5Decision:
        """Принятие окончательного решения"""
        
        # Парсим вердикты агентов
        agent3 = AgentVerdict(
            agent_id=3,
            action=agent3_data.get("action", "none"),
            action_duration=agent3_data.get("action_duration", 0),
            reason=agent3_data.get("reason", ""),
            confidence=agent3_data.get("confidence", 0.5),
            violation_type=agent3_data.get("violation_type", "unknown"),
            severity=agent3_data.get("severity", 5),
            timestamp=datetime.now()
        )
        
        agent4 = AgentVerdict(
            agent_id=4,
            action=agent4_data.get("action", "none"),
            action_duration=agent4_data.get("action_duration", 0),
            reason=agent4_data.get("reason", ""),
            confidence=agent4_data.get("confidence", 0.5),
            violation_type=agent4_data.get("violation_type", "unknown"),
            severity=agent4_data.get("severity", 5),
            timestamp=datetime.now()
        )
        
        logger.info(
            f"🤔 Анализ вердиктов: Agent3={agent3.action} "
            f"({agent3.confidence:.2f}, серьезность {agent3.severity}/10), "
            f"Agent4={agent4.action} ({agent4.confidence:.2f}, серьезность {agent4.severity}/10)"
        )
        
        # Проверяем конфликт
        has_conflict = self.has_conflict(agent3, agent4)
        conflict_resolved_by = ""
        
        if not has_conflict:
            # Вердикты согласованы - берем средний результат
            if agent3.action == agent4.action:
                final_action = agent3.action
                final_duration = (agent3.action_duration + agent4.action_duration) // 2
                final_confidence = (agent3.confidence + agent4.confidence) / 2
                reasoning = (
                    f"Агенты №3 и №4 согласны. Действие: {final_action}. "
                    f"Средняя уверенность: {final_confidence:.2f}. "
                    f"Средняя серьезность: {(agent3.severity + agent4.severity) / 2:.1f}/10"
                )
            else:
                # Если действия разные, но уверенность достаточная - выбираем более уверенный
                if agent3.confidence > agent4.confidence:
                    final_action = agent3.action
                    final_duration = agent3.action_duration
                    final_confidence = agent3.confidence
                    reasoning = f"Выбрано действие Агента №3 (выше уверенность: {agent3.confidence:.2f})"
                else:
                    final_action = agent4.action
                    final_duration = agent4.action_duration
                    final_confidence = agent4.confidence
                    reasoning = f"Выбрано действие Агента №4 (выше уверенность: {agent4.confidence:.2f})"
            
            conflict_resolved_by = "consensus"
            logger.info("✅ Конфликта нет, принимаем согласованное решение")
        
        else:
            # Есть конфликт - используем Mistral AI
            logger.warning("⚠️ Обнаружен конфликт между агентами!")
            rules = agent3_data.get("rules", []) or agent4_data.get("rules", [])
            
            final_action, final_duration, final_confidence, reasoning = self.resolve_conflict_with_mistral(
                agent3, agent4, agent3_data.get("message", ""), rules
            )
            
            conflict_resolved_by = "mistral_ai"
        
        # Генерируем уникальный ID решения
        decision_id = f"decision_{agent3_data.get('message_id', 0)}_{int(datetime.now().timestamp()*1000)}"
        
        # Создаем решение
        decision = Agent5Decision(
            decision_id=decision_id,
            message_id=agent3_data.get("message_id", 0),
            chat_id=agent3_data.get("chat_id", 0),
            user_id=agent3_data.get("user_id", 0),
            username=agent3_data.get("username", ""),
            message_text=agent3_data.get("message", ""),
            final_action=final_action,
            final_action_duration=final_duration,
            final_confidence=final_confidence,
            reasoning=reasoning,
            agent3_action=agent3.action,
            agent4_action=agent4.action,
            agent3_severity=agent3.severity,
            agent4_severity=agent4.severity,
            was_conflict=has_conflict,
            conflict_resolved_by=conflict_resolved_by,
            timestamp=datetime.now()
        )
        
        self.processed_count += 1
        return decision

# ============================================================================
# ОСНОВНАЯ ФУНКЦИЯ АГЕНТА 5
# ============================================================================

def moderation_agent_5(agent3_data: Dict[str, Any], agent4_data: Dict[str, Any]):
    """АГЕНТ 5 — Арбитр принимает окончательное решение"""
    
    arbiter = ModerationArbiter()
    decision = arbiter.make_decision(agent3_data, agent4_data)
    
    output = {
        "agent_id": 5,
        "decision_id": decision.decision_id,
        "final_action": decision.final_action,
        "final_action_duration": decision.final_action_duration,
        "final_confidence": decision.final_confidence,
        "reasoning": decision.reasoning,
        "message": decision.message_text,
        "user_id": decision.user_id,
        "username": decision.username,
        "chat_id": decision.chat_id,
        "message_id": decision.message_id,
        "agent3_action": decision.agent3_action,
        "agent4_action": decision.agent4_action,
        "agent3_severity": decision.agent3_severity,
        "agent4_severity": decision.agent4_severity,
        "was_conflict": decision.was_conflict,
        "conflict_resolved_by": decision.conflict_resolved_by,
        "ai_provider": f"Mistral AI ({MISTRAL_MODEL})",
        "import_version": MISTRAL_IMPORT_VERSION,
        "status": "success",
        "timestamp": decision.timestamp.isoformat()
    }
    
    if decision.final_action != "none":
        logger.warning(
            f"🚨 ФИНАЛЬНОЕ РЕШЕНИЕ: {decision.final_action.upper()} "
            f"для @{decision.username} в чате {decision.chat_id} "
            f"(уверенность: {decision.final_confidence:.2%})"
        )
    else:
        logger.info(
            f"✅ ФИНАЛЬНОЕ РЕШЕНИЕ: НЕ ДЕЙСТВОВАТЬ "
            f"для @{decision.username} в чате {decision.chat_id}"
        )
    
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
            logger.info(f"✅ Подключение к Redis успешно")
        except Exception as e:
            logger.error(f"❌ Не удалось подключиться к Redis: {e}")
            raise
        
        self.pending_decisions = {}  # Хранилище решений агентов
    
    def process_agent_result(self, message_data):
        """Обрабатывает результат от агента 3 или 4"""
        try:
            agent_data = json.loads(message_data)
            agent_id = agent_data.get("agent_id")
            message_id = agent_data.get("message_id")
            
            if not message_id:
                logger.error("Отсутствует message_id")
                return None
            
            # Сохраняем результат агента
            if message_id not in self.pending_decisions:
                self.pending_decisions[message_id] = {}
            
            self.pending_decisions[message_id][f"agent_{agent_id}"] = agent_data
            
            logger.info(f"📨 Получен результат от Агента #{agent_id} для сообщения {message_id}")
            
            # Проверяем, есть ли результаты от обоих агентов
            decision_data = self.pending_decisions[message_id]
            
            if "agent_3" in decision_data and "agent_4" in decision_data:
                logger.info(f"🎯 Есть результаты от обоих агентов для сообщения {message_id}")
                
                agent3_data = decision_data["agent_3"]
                agent4_data = decision_data["agent_4"]
                
                final_decision = moderation_agent_5(agent3_data, agent4_data)
                
                # Удаляем из временного хранилища
                del self.pending_decisions[message_id]
                
                return final_decision
            else:
                logger.info(f"⏳ Ждем результат от второго агента для сообщения {message_id}")
                return None
        
        except json.JSONDecodeError as e:
            logger.error(f"Невалидный JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"Ошибка обработки: {e}")
            return None
    
    def save_decision(self, result):
        """Сохраняет решение (можно отправить в БД или очередь)"""
        if result:
            logger.info(f"💾 Решение {result['decision_id']} готово к сохранению")
            # Здесь можно добавить сохранение в БД или отправку в очередь
    
    def run(self):
        """Главный цикл обработки результатов агентов"""
        logger.info(f"✅ Агент 5 запущен (Арбитр v5.5)")
        logger.info(f" Модель: {MISTRAL_MODEL}")
        logger.info(f" Импорт: {MISTRAL_IMPORT_VERSION}")
        logger.info(f" Статус: {'✅ Доступен' if mistral_client else '❌ Недоступен'}")
        logger.info(f" Слушаю очередь: {QUEUE_AGENT_5_INPUT}")
        logger.info(" Нажмите Ctrl+C для остановки\n")
        
        try:
            while True:
                try:
                    result = self.redis_client.blpop(QUEUE_AGENT_5_INPUT, timeout=1)
                    if result is None:
                        continue
                    
                    queue_name, message_data = result
                    
                    output = self.process_agent_result(message_data)
                    
                    if output:
                        self.save_decision(output)
                        logger.info(f"✅ Финальное решение принято\n")
                
                except Exception as e:
                    logger.error(f"Ошибка в цикле: {e}")
                    time.sleep(1)
        
        except KeyboardInterrupt:
            logger.info("\n❌ Агент 5 остановлен (Ctrl+C)")
        finally:
            logger.info("Агент 5 завершил работу")

# ============================================================================
# ТОЧКА ВХОДА
# ============================================================================

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # Тестирование арбитража
        agent3_data = {
            "agent_id": 3,
            "action": "mute",
            "action_duration": 60,
            "reason": "Обнаружен мат",
            "confidence": 0.85,
            "violation_type": "profanity",
            "severity": 7,
            "message": "Ты дурак! Хуй тебе!",
            "user_id": 123,
            "username": "test_user",
            "chat_id": -100,
            "message_id": 1,
            "rules": DEFAULT_RULES
        }
        
        agent4_data = {
            "agent_id": 4,
            "action": "warn",
            "action_duration": 0,
            "reason": "Обнаружена нецензурная лексика",
            "confidence": 0.70,
            "violation_type": "profanity",
            "severity": 6,
            "message": "Ты дурак! Хуй тебе!",
            "user_id": 123,
            "username": "test_user",
            "chat_id": -100,
            "message_id": 1,
            "rules": DEFAULT_RULES
        }
        
        print("\n=== ТЕСТИРОВАНИЕ АГЕНТА 5 ===\n")
        result = moderation_agent_5(agent3_data, agent4_data)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    
    else:
        try:
            worker = Agent5Worker()
            worker.run()
        except KeyboardInterrupt:
            logger.info("Выход")
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")