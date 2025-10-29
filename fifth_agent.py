#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
АГЕНТ №5 — Арбитр многоагентной системы (обновленная версия на основе agent3.4)
"""

import requests
import json
import redis
import time
import logging
from typing import Dict, Any, List, Optional
import urllib3
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey, BigInteger, Text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
import asyncio
from dataclasses import dataclass
from enum import Enum

# Отключаем warning SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============================================================================
# ЛОГИРОВАНИЕ
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [АГЕНТ 5] %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# КОНФИГУРАЦИЯ БД (ОДИНАКОВАЯ С АГЕНТОМ 3.4)
# ============================================================================
POSTGRES_URL = 'postgresql://tguser:mnvm7110@176.108.248.211:5432/teleguard_db?sslmode=disable'

# ============================================================================
# КОНФИГУРАЦИЯ TELEGRAM BOT
# ============================================================================
TELEGRAM_BOT_TOKEN = "8320009669:AAHiVLu-Em8EOXBNHYrJ0UhVX3mMMTm8S_g"
TELEGRAM_API_URL = "https://api.telegram.org/bot"

# ============================================================================
# КОНФИГУРАЦИЯ REDIS
# ============================================================================
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0
REDIS_PASSWORD = None

# Очереди для взаимодействия с другими агентами
QUEUE_AGENT_5_INPUT = "queue:agent5:input"
QUEUE_AGENT_3_OUTPUT = "queue:agent3:output"
QUEUE_AGENT_4_OUTPUT = "queue:agent4:output"

# ============================================================================
# МОДЕЛИ БД (ТОЧНО ТЕ ЖЕ ЧТО В АГЕНТЕ 3.4)
# ============================================================================
Base = declarative_base()

class Chat(Base):
    __tablename__ = 'chats'
    id = Column(Integer, primary_key=True)
    tg_chat_id = Column(String, unique=True, nullable=False)
    title = Column(String, nullable=True)
    chat_type = Column(String, default='group')
    added_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    
    messages = relationship('Message', back_populates='chat', cascade="all, delete")
    moderators = relationship('Moderator', back_populates='chat', cascade="all, delete")
    negative_messages = relationship('NegativeMessage', back_populates='chat', cascade="all, delete")

class Message(Base):
    __tablename__ = 'messages'
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, ForeignKey('chats.id'), nullable=False)
    message_id = Column(BigInteger, nullable=False)
    sender_username = Column(String)
    sender_id = Column(BigInteger)
    message_text = Column(Text)
    message_link = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime)
    ai_response = Column(Text)
    
    chat = relationship('Chat', back_populates='messages')

class Moderator(Base):
    __tablename__ = 'moderators'
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, ForeignKey('chats.id'), nullable=False)
    username = Column(String)
    telegram_user_id = Column(BigInteger)
    is_active = Column(Boolean, default=True)
    added_at = Column(DateTime, default=datetime.utcnow)
    
    chat = relationship('Chat', back_populates='moderators')

class NegativeMessage(Base):
    __tablename__ = 'negative_messages'
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, ForeignKey('chats.id'), nullable=False)
    message_link = Column(String)
    sender_username = Column(String)
    sender_id = Column(BigInteger)
    negative_reason = Column(Text)
    is_sent_to_moderators = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    agent_id = Column(Integer)
    
    chat = relationship('Chat', back_populates='negative_messages')

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ БД И REDIS
# ============================================================================
engine = create_engine(POSTGRES_URL)
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)

def get_db_session():
    return SessionLocal()

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
# АРБИТРАЖНАЯ ЛОГИКА
# ============================================================================
class ModerationArbiter:
    """
    Арбитр для разрешения конфликтов между агентами 3 и 4
    """
    
    def __init__(self):
        self.processed_count = 0
    
    def has_conflict(self, agent3: AgentVerdict, agent4: AgentVerdict) -> bool:
        """Проверка наличия конфликта между агентами"""
        # Конфликт если вердикты разные или уверенность низкая
        verdicts_differ = agent3.ban != agent4.ban
        low_confidence = agent3.confidence < 0.7 or agent4.confidence < 0.7
        return verdicts_differ or low_confidence
    
    def resolve_conflict(self, agent3: AgentVerdict, agent4: AgentVerdict, message_text: str) -> tuple:
        """Разрешение конфликта между агентами"""
        logger.info("🔍 Разрешение конфликта между агентами...")
        
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
                reasoning = f"Конфликт разрешен собственным анализом: обнаружены токсичные слова ({toxic_count})"
            elif spam_count >= 2:
                verdict = VerdictType.BAN
                confidence = 0.70
                reasoning = f"Конфликт разрешен собственным анализом: вероятный спам ({spam_count} спам-маркеров)"
            else:
                verdict = VerdictType.APPROVE
                confidence = 0.65
                reasoning = "Конфликт разрешен собственным анализом: сообщение выглядит безопасным"
        
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
            # Есть конфликт
            logger.warning("⚠️ Обнаружен конфликт между агентами!")
            final_verdict, confidence, reasoning = self.resolve_conflict(
                agent3, agent4, agent3_data.get("message", "")
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
def send_notification_to_moderators(decision: Agent5Decision, db_session):
    """Отправка уведомлений модераторам о принятом решении"""
    if decision.final_verdict != VerdictType.BAN:
        return True  # Не уведомляем о разрешенных сообщениях
    
    try:
        # Находим модераторов чата
        chat = db_session.query(Chat).filter_by(tg_chat_id=str(decision.chat_id)).first()
        if not chat:
            logger.warning(f"⚠️ Чат {decision.chat_id} не найден в БД")
            return False
        
        moderators = db_session.query(Moderator).filter_by(
            chat_id=chat.id, 
            is_active=True
        ).all()
        
        if not moderators:
            logger.warning(f"⚠️ Модераторы для чата {decision.chat_id} не найдены")
            return False
        
        # Формируем уведомление
        notification = (
            f"🚨 <b>Обнаружено нарушение!</b>\n\n"
            f"👤 <b>Пользователь:</b> {decision.username}\n"
            f"💬 <b>Сообщение:</b> {decision.message_text[:200]}{'...' if len(decision.message_text) > 200 else ''}\n"
            f"⚖️ <b>Решение агента 5:</b> {decision.final_verdict.value.upper()}\n"
            f"🎯 <b>Уверенность:</b> {decision.confidence:.1%}\n"
            f"📝 <b>Причина:</b> {decision.reasoning[:300]}{'...' if len(decision.reasoning) > 300 else ''}\n"
            f"🤖 <b>Agent3:</b> {decision.agent3_verdict.value}, <b>Agent4:</b> {decision.agent4_verdict.value}\n"
            f"⚡ <b>Конфликт:</b> {'Да' if decision.was_conflict else 'Нет'}\n"
            f"🕐 <b>Время:</b> {decision.timestamp.strftime('%H:%M:%S')}"
        )
        
        # Отправляем уведомления всем модераторам
        success_count = 0
        for moderator in moderators:
            if moderator.telegram_user_id:
                try:
                    url = f"{TELEGRAM_API_URL}{TELEGRAM_BOT_TOKEN}/sendMessage"
                    data = {
                        'chat_id': moderator.telegram_user_id,
                        'text': notification,
                        'parse_mode': 'HTML'
                    }
                    
                    response = requests.post(url, json=data, timeout=10)
                    if response.status_code == 200:
                        success_count += 1
                        logger.info(f"📤 Уведомление отправлено модератору @{moderator.username}")
                    else:
                        logger.error(f"❌ Ошибка отправки уведомления: {response.text}")
                        
                except Exception as e:
                    logger.error(f"❌ Исключение при отправке уведомления: {e}")
        
        logger.info(f"📤 Уведомления отправлены {success_count}/{len(moderators)} модераторам")
        return success_count > 0
        
    except Exception as e:
        logger.error(f"❌ Ошибка уведомления модераторов: {e}")
        return False

# ============================================================================
# ОСНОВНАЯ ЛОГИКА АГЕНТА 5
# ============================================================================
def moderation_agent_5(agent3_data: Dict[str, Any], agent4_data: Dict[str, Any], db_session):
    """
    АГЕНТ 5 — Арбитр принимает окончательное решение
    """
    arbiter = ModerationArbiter()
    
    # Принимаем решение
    decision = arbiter.make_decision(agent3_data, agent4_data)
    
    # Сохраняем результат если нужно забанить
    if decision.final_verdict == VerdictType.BAN:
        try:
            chat = db_session.query(Chat).filter_by(tg_chat_id=str(decision.chat_id)).first()
            if chat:
                # Обновляем флаг уведомления модераторов
                negative_msgs = db_session.query(NegativeMessage).filter_by(
                    chat_id=chat.id,
                    sender_username=decision.username,
                    is_sent_to_moderators=False
                ).all()
                
                for msg in negative_msgs:
                    msg.is_sent_to_moderators = True
                
                db_session.commit()
                
        except Exception as e:
            logger.error(f"Ошибка обновления БД: {e}")
    
    # Уведомляем модераторов
    notification_sent = send_notification_to_moderators(decision, db_session)
    
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
        "status": "success",
        "timestamp": decision.timestamp.isoformat()
    }
    
    if decision.final_verdict == VerdictType.BAN:
        logger.warning(f"🚨 ФИНАЛЬНОЕ РЕШЕНИЕ: БАН для @{decision.username}")
    else:
        logger.info(f"✅ ФИНАЛЬНОЕ РЕШЕНИЕ: НЕ БАНИТЬ @{decision.username}")
    
    return output

# ============================================================================
# РАБОТА С REDIS
# ============================================================================
class Agent5Worker:
    def __init__(self):
        try:
            redis_config = {
                "host": REDIS_HOST,
                "port": REDIS_PORT,
                "db": REDIS_DB,
                "password": REDIS_PASSWORD,
                "decode_responses": True
            }
            self.redis_client = redis.Redis(**redis_config)
            self.redis_client.ping()
            logger.info(f"✅ Подключение к Redis успешно: {REDIS_HOST}:{REDIS_PORT}")
        except Exception as e:
            logger.error(f"❌ Не удалось подключиться к Redis: {e}")
            raise
        
        self.pending_decisions = {}  # Временное хранение решений агентов
    
    def process_agent_result(self, message_data, db_session):
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
                
                final_decision = moderation_agent_5(agent3_data, agent4_data, db_session)
                
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
        logger.info(f"✅ Агент 5 запущен")
        logger.info(f"   Слушаю очередь: {QUEUE_AGENT_5_INPUT}")
        logger.info("   Нажмите Ctrl+C для остановки\n")
        
        db_session = None
        try:
            while True:
                try:
                    result = self.redis_client.blpop(QUEUE_AGENT_5_INPUT, timeout=1)
                    if result is None:
                        continue
                    
                    queue_name, message_data = result
                    
                    # Создаем новую сессию БД для каждого сообщения
                    db_session = get_db_session()
                    output = self.process_agent_result(message_data, db_session)
                    db_session.close()
                    
                    if output:
                        logger.info(f"✅ Финальное решение принято\n")
                    
                except Exception as e:
                    logger.error(f"Ошибка в цикле: {e}")
                    if db_session:
                        db_session.close()
                    time.sleep(1)
                    
        except KeyboardInterrupt:
            logger.info("\n❌ Агент 5 остановлен (Ctrl+C)")
        finally:
            if db_session:
                db_session.close()
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
                    "name": "Агент №5 (Арбитр)",
                    "version": "5.0",
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
    
    server = HTTPServer(('localhost', 8005), HealthCheckHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("✅ Health check сервер запущен на порту 8005")

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
                "reason": "Вердикт: да. Обнаружено нецензурное слово",
                "message": "Тестовое сообщение с матом",
                "user_id": 123,
                "username": "test_user",
                "chat_id": -100,
                "message_id": 1,
                "confidence": 0.85
            }
            
            agent4_data = {
                "agent_id": 4,
                "ban": False,
                "reason": "Вердикт: нет. Нарушений не обнаружено",
                "message": "Тестовое сообщение с матом",
                "user_id": 123,
                "username": "test_user", 
                "chat_id": -100,
                "message_id": 1,
                "confidence": 0.70
            }
            
            db_session = get_db_session()
            result = moderation_agent_5(agent3_data, agent4_data, db_session)
            db_session.close()
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