#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
АГЕНТ №5 — Арбитр многоагентной системы (Mistral AI версия)
"""

import json
import redis
import time
from typing import Dict, Any, List, Optional
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
import requests
from mistralai.client import MistralClient
from mistralai.models.chat_completion import ChatMessage

# Импортируем централизованную конфигурацию
from config import (
    MISTRAL_API_KEY,
    MISTRAL_MODEL,
    MISTRAL_GENERATION_PARAMS,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_API_URL,
    get_redis_config,
    QUEUE_AGENT_5_INPUT,
    AGENT_PORTS,
    DEFAULT_RULES,
    setup_logging
)

# ============================================================================
# ЛОГИРОВАНИЕ
# ============================================================================
logger = setup_logging("АГЕНТ 5")

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ MISTRAL AI
# ============================================================================
mistral_client = MistralClient(api_key=MISTRAL_API_KEY)

# ============================================================================
# КЛАССЫ ДАННЫХ ДЛЯ АРБИТРАЖА
# ============================================================================
class VerdictType(Enum):
    APPROVE = "approve"
    BAN = "ban"
    UNCERTAIN = "uncertain"

@dataclass
class AgentVerdict:
    agent_id: int
    ban: bool
    reason: str
    confidence: float
    timestamp: datetime
    
    def to_verdict_type(self) -> VerdictType:
        return VerdictType.BAN if self.ban else VerdictType.APPROVE

@dataclass
class Agent5Decision:
    decision_id: str
    message_id: int
    chat_id: int
    user_id: int
    username: str
    message_text: str
    final_verdict: VerdictType
    confidence: float
    reasoning: str
    agent3_verdict: VerdictType
    agent4_verdict: VerdictType
    was_conflict: bool
    timestamp: datetime

# ============================================================================
# АРБИТРАЖНАЯ ЛОГИКА С MISTRAL AI (ОБНОВЛЕННЫЙ ПРОМПТ)
# ============================================================================
class ModerationArbiter:
    """
    Арбитр для разрешения конфликтов между агентами 3 и 4 с использованием Mistral AI
    """
    
    def __init__(self):
        self.processed_count = 0
    
    def has_conflict(self, agent3: AgentVerdict, agent4: AgentVerdict) -> bool:
        """Проверка наличия конфликта между агентами"""
        # Конфликт если вердикты разные или уверенность низкая
        verdicts_differ = agent3.ban != agent4.ban
        low_confidence = agent3.confidence < 0.7 or agent4.confidence < 0.7
        return verdicts_differ or low_confidence
    
    def resolve_conflict_with_mistral(self, agent3: AgentVerdict, agent4: AgentVerdict, message_text: str, rules: list) -> tuple:
        """Разрешение конфликта между агентами с помощью Mistral AI (обновленный промпт)"""
        logger.info("🤖 Разрешение конфликта с помощью Mistral AI...")
        
        try:
            # Если правил нет, используем стандартные
            if not rules:
                rules = DEFAULT_RULES
            
            rules_text = "\n".join([f"{i+1}. {rule}" for i, rule in enumerate(rules)])
            
            system_message = f"""Ты — модератор группового чата. Твоя задача — получать сообщения из чата и анализировать их с точки зрения соответствия правилам. По каждому сообщению выноси вердикт: «банить» или «не банить», указывая причину решения и степень уверенности в процентах.

ПРАВИЛА ЧАТА:
{rules_text}

Два других агента дали разные вердикты по этому сообщению:

АГЕНТ 3 (Mistral AI модератор):
- Решение: {"банить" if agent3.ban else "не банить"}  
- Уверенность: {agent3.confidence*100:.0f}%
- Причина: {agent3.reason}

АГЕНТ 4 (Эвристический модератор):
- Решение: {"банить" if agent4.ban else "не банить"}
- Уверенность: {agent4.confidence*100:.0f}%  
- Причина: {agent4.reason}

Проанализируй сообщение и прими окончательное решение.

Формат вывода:
Вердикт: <банить/не банить>
Причина: <текст причины>
Уверенность: <число от 0 до 100>%"""
            
            user_message = f"Сообщение пользователя:\n\"{message_text}\""
            
            messages = [
                ChatMessage(role="system", content=system_message),
                ChatMessage(role="user", content=user_message)
            ]
            
            response = mistral_client.chat(
                model=MISTRAL_MODEL,
                messages=messages,
                temperature=MISTRAL_GENERATION_PARAMS["temperature"],
                max_tokens=MISTRAL_GENERATION_PARAMS["max_tokens"],
                top_p=MISTRAL_GENERATION_PARAMS["top_p"]
            )
            
            content = response.choices[0].message.content
            
            # Парсим ответ в новом формате
            content_lower = content.lower()
            
            # Ищем вердикт
            if "вердикт:" in content_lower:
                verdict_line = [line for line in content.split('\n') if 'вердикт:' in line.lower()]
                if verdict_line:
                    verdict_text = verdict_line[0].lower()
                    if "банить" in verdict_text and "не банить" not in verdict_text:
                        verdict = VerdictType.BAN
                        confidence = 0.8
                    else:
                        verdict = VerdictType.APPROVE
                        confidence = 0.75
                else:
                    verdict = VerdictType.APPROVE
                    confidence = 0.65
            else:
                verdict = VerdictType.APPROVE
                confidence = 0.65
            
            # Ищем уверенность
            if "уверенность:" in content_lower:
                confidence_line = [line for line in content.split('\n') if 'уверенность:' in line.lower()]
                if confidence_line:
                    try:
                        import re
                        numbers = re.findall(r'\d+', confidence_line[0])
                        if numbers:
                            confidence = int(numbers[0]) / 100.0
                            confidence = min(1.0, max(0.0, confidence))
                    except:
                        pass
            
            reasoning = f"Mistral AI арбитр: {content}"
            
            logger.info(f"🤖 Mistral AI принял решение: {verdict.value} (уверенность: {confidence:.2f})")
            return verdict, confidence, reasoning
            
        except Exception as e:
            logger.error(f"Ошибка Mistral AI арбитража: {e}")
            # Fallback логика при ошибке Mistral AI
            return self.resolve_conflict_fallback(agent3, agent4, message_text)
    
    def resolve_conflict_fallback(self, agent3: AgentVerdict, agent4: AgentVerdict, message_text: str) -> tuple:
        """Резервная логика разрешения конфликтов без Mistral AI"""
        logger.info("🔍 Разрешение конфликта (резервный алгоритм)...")
        
        # Взвешенная оценка по уверенности
        weight3 = agent3.confidence
        weight4 = agent4.confidence
        
        # Если один агент значительно увереннее другого
        if weight3 > 0.8 and weight4 < 0.6:
            verdict = VerdictType.BAN if agent3.ban else VerdictType.APPROVE
            confidence = agent3.confidence * 0.9
            reasoning = f"Конфликт разрешен в пользу Агента №3 (уверенность {weight3:.2f}). {agent3.reason}"
        elif weight4 > 0.8 and weight3 < 0.6:
            verdict = VerdictType.BAN if agent4.ban else VerdictType.APPROVE
            confidence = agent4.confidence * 0.9
            reasoning = f"Конфликт разрешен в пользу Агента №4 (уверенность {weight4:.2f}). {agent4.reason}"
        else:
            # Применяем собственный анализ (упрощенный)
            spam_keywords = ['купить', 'скидка', 'заработок', 'кликай', 'переходи', 'вступай']
            toxic_keywords = ['дурак', 'идиот', 'ненавижу', 'хуй', 'блять', 'сука']
            
            message_lower = message_text.lower()
            spam_count = sum(1 for keyword in spam_keywords if keyword in message_lower)
            toxic_count = sum(1 for keyword in toxic_keywords if keyword in message_lower)
            
            if toxic_count > 0:
                verdict = VerdictType.BAN
                confidence = 0.75
                reasoning = f"Конфликт разрешен резервным анализом: обнаружены токсичные слова ({toxic_count})"
            elif spam_count >= 2:
                verdict = VerdictType.BAN
                confidence = 0.70
                reasoning = f"Конфликт разрешен резервным анализом: вероятный спам ({spam_count} спам-маркеров)"
            else:
                verdict = VerdictType.APPROVE
                confidence = 0.65
                reasoning = "Конфликт разрешен резервным анализом: сообщение выглядит безопасным"
        
        logger.info(f"⚖️ Конфликт разрешен: {verdict.value} (уверенность: {confidence:.2f})")
        return verdict, confidence, reasoning
    
    def make_decision(self, agent3_data: Dict[str, Any], agent4_data: Dict[str, Any]) -> Agent5Decision:
        """Принятие окончательного решения"""
        # Парсим вердикты агентов
        agent3 = AgentVerdict(
            agent_id=agent3_data.get("agent_id", 3),
            ban=agent3_data.get("ban", False),
            reason=agent3_data.get("reason", ""),
            confidence=agent3_data.get("confidence", 0.5),
            timestamp=datetime.now()
        )
        
        agent4 = AgentVerdict(
            agent_id=agent4_data.get("agent_id", 4),
            ban=agent4_data.get("ban", False),
            reason=agent4_data.get("reason", ""),
            confidence=agent4_data.get("confidence", 0.5),
            timestamp=datetime.now()
        )
        
        logger.info(f"🤔 Анализ вердиктов: Agent3={'БАН' if agent3.ban else 'НЕ БАНИТЬ'} ({agent3.confidence:.2f}), "
                   f"Agent4={'БАН' if agent4.ban else 'НЕ БАНИТЬ'} ({agent4.confidence:.2f})")
        
        has_conflict = self.has_conflict(agent3, agent4)
        
        if not has_conflict:
            # Вердикты согласованы
            final_verdict = VerdictType.BAN if agent3.ban else VerdictType.APPROVE
            confidence = (agent3.confidence + agent4.confidence) / 2
            reasoning = (
                f"Агенты №3 и №4 согласны. Средняя уверенность: {confidence:.2f}. "
                f"Agent3: {agent3.reason}. Agent4: {agent4.reason}."
            )
            logger.info("✅ Конфликта нет, принимаем согласованное решение")
        else:
            # Есть конфликт - используем Mistral AI арбитр с новым промптом
            logger.warning("⚠️ Обнаружен конфликт между агентами!")
            rules = agent3_data.get("rules", []) or agent4_data.get("rules", [])
            final_verdict, confidence, reasoning = self.resolve_conflict_with_mistral(
                agent3, agent4, agent3_data.get("message", ""), rules
            )
        
        decision_id = f"decision_{agent3_data.get('message_id', 0)}_{int(datetime.now().timestamp())}"
        
        decision = Agent5Decision(
            decision_id=decision_id,
            message_id=agent3_data.get("message_id", 0),
            chat_id=agent3_data.get("chat_id", 0),
            user_id=agent3_data.get("user_id", 0),
            username=agent3_data.get("username", ""),
            message_text=agent3_data.get("message", ""),
            final_verdict=final_verdict,
            confidence=confidence,
            reasoning=reasoning,
            agent3_verdict=agent3.to_verdict_type(),
            agent4_verdict=agent4.to_verdict_type(),
            was_conflict=has_conflict,
            timestamp=datetime.now()
        )
        
        self.processed_count += 1
        return decision

# ============================================================================
# УВЕДОМЛЕНИЕ МОДЕРАТОРОВ
# ============================================================================
def send_notification_to_moderators(decision: Agent5Decision) -> bool:
    """Отправка уведомлений модераторам о принятом решении"""
    if decision.final_verdict != VerdictType.BAN:
        return True  # Не уведомляем о разрешенных сообщениях
    
    try:
        # Формируем уведомление
        notification = (
            f"🚨 <b>Обнаружено нарушение в чате!</b>\n\n"
            f"💬 <b>Чат ID:</b> {decision.chat_id}\n"
            f"👤 <b>Пользователь:</b> {decision.username}\n"
            f"📄 <b>Сообщение:</b> {decision.message_text[:200]}{'...' if len(decision.message_text) > 200 else ''}\n"
            f"⚖️ <b>Решение агента 5:</b> {decision.final_verdict.value.upper()}\n"
            f"🎯 <b>Уверенность:</b> {decision.confidence:.1%}\n"
            f"📝 <b>Причина:</b> {decision.reasoning[:300]}{'...' if len(decision.reasoning) > 300 else ''}\n"
            f"🤖 <b>Agent3:</b> {decision.agent3_verdict.value}, <b>Agent4:</b> {decision.agent4_verdict.value}\n"
            f"⚡ <b>Конфликт:</b> {'Да' if decision.was_conflict else 'Нет'}\n"
            f"🧠 <b>ИИ провайдер:</b> Mistral AI ({MISTRAL_MODEL})\n"
            f"⚙️ <b>Конфигурация:</b> Environment variables (.env)\n"
            f"🕐 <b>Время:</b> {decision.timestamp.strftime('%H:%M:%S')}"
        )
        
        # В реальной реализации здесь должна быть отправка через БД модераторам
        # Для примера логируем уведомление
        logger.info(f"📤 Уведомление готово к отправке модераторам чата {decision.chat_id}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка формирования уведомления: {e}")
        return False

# ============================================================================
# ОСНОВНАЯ ЛОГИКА АГЕНТА 5
# ============================================================================
def moderation_agent_5(agent3_data: Dict[str, Any], agent4_data: Dict[str, Any]):
    """
    АГЕНТ 5 — Арбитр принимает окончательное решение с Mistral AI (обновленный промпт)
    """
    arbiter = ModerationArbiter()
    
    # Принимаем решение
    decision = arbiter.make_decision(agent3_data, agent4_data)
    
    # Уведомляем модераторов
    notification_sent = send_notification_to_moderators(decision)
    
    output = {
        "agent_id": 5,
        "decision_id": decision.decision_id,
        "final_verdict": decision.final_verdict.value,
        "ban": decision.final_verdict == VerdictType.BAN,
        "confidence": decision.confidence,
        "reasoning": decision.reasoning,
        "message": decision.message_text,
        "user_id": decision.user_id,
        "username": decision.username,
        "chat_id": decision.chat_id,
        "message_id": decision.message_id,
        "agent3_verdict": decision.agent3_verdict.value,
        "agent4_verdict": decision.agent4_verdict.value,
        "was_conflict": decision.was_conflict,
        "notification_sent": notification_sent,
        "ai_provider": f"Mistral AI ({MISTRAL_MODEL})",
        "prompt_version": "v2.0 - обновленный формат",
        "configuration": "Environment variables (.env)",
        "status": "success",
        "timestamp": decision.timestamp.isoformat()
    }
    
    if decision.final_verdict == VerdictType.BAN:
        logger.warning(f"🚨 ФИНАЛЬНОЕ РЕШЕНИЕ (Mistral AI): БАН для @{decision.username} в чате {decision.chat_id}")
    else:
        logger.info(f"✅ ФИНАЛЬНОЕ РЕШЕНИЕ (Mistral AI): НЕ БАНИТЬ @{decision.username} в чате {decision.chat_id}")
    
    return output

# ============================================================================
# РАБОТА С REDIS
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
        
        self.pending_decisions = {}  # Временное хранение решений агентов
    
    def process_agent_result(self, message_data):
        """Обрабатывает результат от агента 3 или 4"""
        try:
            agent_data = json.loads(message_data)
            agent_id = agent_data.get("agent_id")
            message_id = agent_data.get("message_id")
            
            if not message_id:
                logger.error("Отсутствует message_id в данных агента")
                return None
            
            # Сохраняем результат агента
            if message_id not in self.pending_decisions:
                self.pending_decisions[message_id] = {}
            
            self.pending_decisions[message_id][f"agent_{agent_id}"] = agent_data
            
            logger.info(f"📨 Получен результат от Агента #{agent_id} для сообщения {message_id}")
            
            # Проверяем, есть ли результаты от обоих агентов
            decision_data = self.pending_decisions[message_id]
            if "agent_3" in decision_data and "agent_4" in decision_data:
                # Есть результаты от обоих агентов - принимаем решение
                logger.info(f"🎯 Есть результаты от обоих агентов для сообщения {message_id}")
                
                agent3_data = decision_data["agent_3"]
                agent4_data = decision_data["agent_4"]
                
                final_decision = moderation_agent_5(agent3_data, agent4_data)
                
                # Удаляем из временного хранения
                del self.pending_decisions[message_id]
                
                return final_decision
                
            else:
                logger.info(f"⏳ Ждем результат от второго агента для сообщения {message_id}")
                return None
                
        except json.JSONDecodeError as e:
            logger.error(f"Невалидный JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"Ошибка обработки результата агента: {e}")
            return None
    
    def run(self):
        """Главный цикл обработки результатов агентов"""
        logger.info(f"✅ Агент 5 запущен (Mistral AI арбитр v5.4)")
        logger.info(f"   Модель: {MISTRAL_MODEL}")
        logger.info(f"   Слушаю очередь: {QUEUE_AGENT_5_INPUT}")
        logger.info(f"   Стандартные правила v2.0: {DEFAULT_RULES}")
        logger.info(f"   ИИ провайдер: Mistral AI")
        logger.info("   Нажмите Ctrl+C для остановки\n")
        
        try:
            while True:
                try:
                    result = self.redis_client.blpop(QUEUE_AGENT_5_INPUT, timeout=1)
                    if result is None:
                        continue
                    
                    queue_name, message_data = result
                    
                    output = self.process_agent_result(message_data)
                    
                    if output:
                        logger.info(f"✅ Финальное решение принято\n")
                    
                except Exception as e:
                    logger.error(f"Ошибка в цикле: {e}")
                    time.sleep(1)
                    
        except KeyboardInterrupt:
            logger.info("\n❌ Агент 5 остановлен (Ctrl+C)")
        finally:
            logger.info("Агент 5 завершил работу")

# ============================================================================
# HEALTH CHECK ENDPOINT
# ============================================================================
def create_health_check_server():
    """Создает простой HTTP сервер для проверки здоровья агента"""
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import threading
    
    class HealthCheckHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/health':
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                health_info = {
                    "status": "online",
                    "agent_id": 5,
                    "name": "Агент №5 (Арбитр Mistral AI)",
                    "version": "5.4 (Mistral)",
                    "ai_provider": f"Mistral AI ({MISTRAL_MODEL})",
                    "prompt_version": "v2.0 - обновленный формат",
                    "configuration": "Environment variables (.env)",
                    "default_rules": DEFAULT_RULES,
                    "timestamp": datetime.now().isoformat(),
                    "redis_queue": QUEUE_AGENT_5_INPUT,
                    "uptime_seconds": int(time.time())
                }
                self.wfile.write(json.dumps(health_info, ensure_ascii=False).encode())
            else:
                self.send_response(404)
                self.end_headers()
        
        def log_message(self, format, *args):
            # Подавляем логирование HTTP запросов
            pass
    
    server = HTTPServer(('localhost', AGENT_PORTS[5]), HealthCheckHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"✅ Health check сервер запущен на порту {AGENT_PORTS[5]}")

# ============================================================================
# ТОЧКА ВХОДА
# ============================================================================
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        mode = sys.argv[1]
        if mode == "test":
            # Тестирование арбитража
            agent3_data = {
                "agent_id": 3,
                "ban": True,
                "reason": "Вердикт: банить\nПричина: Обнаружено нецензурное слово\nУверенность: 85%",
                "confidence": 0.85,
                "message": "Тестовое сообщение с матом",
                "user_id": 123,
                "username": "test_user",
                "chat_id": -100,
                "message_id": 1,
                "rules": DEFAULT_RULES
            }
            
            agent4_data = {
                "agent_id": 4,
                "ban": False,
                "reason": "Вердикт: не банить\nПричина: Нарушений не обнаружено\nУверенность: 70%",
                "confidence": 0.70,
                "message": "Тестовое сообщение с матом",
                "user_id": 123,
                "username": "test_user", 
                "chat_id": -100,
                "message_id": 1,
                "rules": DEFAULT_RULES
            }
            
            result = moderation_agent_5(agent3_data, agent4_data)
            print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        # Запуск основного цикла обработки
        try:
            create_health_check_server()
            worker = Agent5Worker()
            worker.run()
        except KeyboardInterrupt:
            logger.info("Выход из программы")
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")