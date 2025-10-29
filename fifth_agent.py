#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
ЧАТ-АГЕНТ №5 с PostgreSQL - Арбитр многоагентной системы
=============================================================================
- Использует модели БД из first_agent.py и teteguard_bot.py
- Интеграция с PostgreSQL через SQLAlchemy ORM
- Арбитраж решений между агентами 3 и 4
- Уведомление модераторов о финальных решениях
=============================================================================
"""

import asyncio
import json
import os
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

import aiohttp
from loguru import logger

# SQLAlchemy imports - используем те же модели что и в первом агенте
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func

# Общие модели БД - те же что в first_agent.py и teteguard_bot.py
from sqlalchemy import Column, Integer, BigInteger, String, Text, Boolean, ForeignKey, DateTime, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()

class Chat(Base):
    __tablename__ = "chats"
    id = Column(Integer, primary_key=True)
    tg_chat_id = Column(String, unique=True, nullable=False)
    messages = relationship('Message', back_populates='chat', cascade="all, delete")
    moderators = relationship('Moderator', back_populates='chat', cascade="all, delete")
    negative_messages = relationship('NegativeMessage', back_populates='chat', cascade="all, delete")

class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, ForeignKey('chats.id'), nullable=False)
    sender_username = Column(String)
    sender_id = Column(BigInteger)
    message_text = Column(String)
    message_link = Column(String)
    created_at = Column(DateTime, default=func.now())
    chat = relationship('Chat', back_populates='messages')

class Moderator(Base):
    __tablename__ = "moderators"
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, ForeignKey('chats.id'), nullable=False)
    username = Column(String)
    telegram_user_id = Column(BigInteger)
    is_active = Column(Boolean, default=True)
    chat = relationship('Chat', back_populates='moderators')

class NegativeMessage(Base):
    __tablename__ = "negative_messages"
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, ForeignKey('chats.id'), nullable=False)
    message_link = Column(String)
    sender_username = Column(String)
    negative_reason = Column(String)
    is_sent_to_moderators = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())
    chat = relationship('Chat', back_populates='negative_messages')

# =========================
# Логирование
# =========================
from pathlib import Path
Path("logs").mkdir(exist_ok=True)

logger.remove()
logger.add(
    "logs/agent_5_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="30 days",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} | {message}"
)
logger.add(lambda msg: print(msg, end=""), level="INFO", format="{time:HH:mm:ss} | {level} | {message}")

# =========================
# Конфигурация
# =========================
class Agent5Config:
    # PostgreSQL настройки - те же что в teteguard_bot.py
    POSTGRES_HOST = "176.108.248.211"
    POSTGRES_PORT = 5432
    POSTGRES_DB = "teleguard_db"
    POSTGRES_USER = "tguser"
    POSTGRES_PASSWORD = "mnvm7110"
    
    # Telegram Bot API для отправки уведомлений
    TELEGRAM_BOT_TOKEN = "8320009669:AAHiVLu-Em8EOXBNHYrJ0UhVX3mMMTm8S_g"
    TELEGRAM_API_URL = "https://api.telegram.org/bot"
    
    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
    
    @property
    def sync_database_url(self) -> str:
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

# =========================
# Классы данных
# =========================
class VerdictType(Enum):
    """Типы вердиктов для модерации"""
    APPROVE = "approve"
    REJECT = "reject"
    WARNING = "warning"
    BAN = "ban"
    UNCERTAIN = "uncertain"

@dataclass
class AgentVerdict:
    """Вердикт от одного агента (№3 или №4)"""
    agent_id: int
    ban: bool
    reason: str
    confidence: float
    timestamp: datetime
    
    def to_verdict_type(self) -> VerdictType:
        """Конвертация в VerdictType"""
        if self.ban:
            return VerdictType.BAN
        else:
            return VerdictType.APPROVE

@dataclass
class Agent5Decision:
    """Финальное решение Агента №5"""
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

    def to_dict(self) -> Dict[str, Any]:
        return {
            'decision_id': self.decision_id,
            'message_id': self.message_id,
            'chat_id': self.chat_id,
            'user_id': self.user_id,
            'username': self.username,
            'message_text': self.message_text,
            'final_verdict': self.final_verdict.value,
            'confidence': self.confidence,
            'reasoning': self.reasoning,
            'agent3_verdict': self.agent3_verdict.value,
            'agent4_verdict': self.agent4_verdict.value,
            'was_conflict': self.was_conflict,
            'timestamp': self.timestamp.isoformat()
        }

# =========================
# Database Manager
# =========================
class Agent5DatabaseManager:
    def __init__(self, config: Agent5Config):
        self.config = config
        self.engine = None
        self.async_session_factory = None
    
    async def init_database(self):
        """Инициализация PostgreSQL базы данных"""
        try:
            # Создание таблиц синхронно
            sync_engine = create_engine(self.config.sync_database_url, echo=False)
            Base.metadata.create_all(sync_engine)
            sync_engine.dispose()
            
            # Создание асинхронного движка PostgreSQL
            self.engine = create_async_engine(
                self.config.database_url,
                echo=False,
                future=True,
                pool_pre_ping=True,
                pool_recycle=3600
            )
            
            self.async_session_factory = async_sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False
            )
            
            logger.success(f"🗄️ Агент 5: PostgreSQL БД инициализирована")
        except Exception as e:
            logger.error(f"❌ Агент 5: Ошибка инициализации PostgreSQL: {e}")
            raise
    
    async def close_database(self):
        if self.engine:
            await self.engine.dispose()
            logger.info("🗄️ Агент 5: Соединение с PostgreSQL закрыто")
    
    def get_session(self) -> AsyncSession:
        if not self.async_session_factory:
            raise RuntimeError("PostgreSQL database not initialized")
        return self.async_session_factory()
    
    async def get_chat_moderators(self, chat_id: int) -> List[Dict[str, Any]]:
        """Получить модераторов чата"""
        try:
            async with self.get_session() as session:
                # Сначала найдем chat по tg_chat_id
                chat_result = await session.execute(
                    select(Chat).where(Chat.tg_chat_id == str(chat_id))
                )
                chat = chat_result.scalar_one_or_none()
                
                if not chat:
                    logger.warning(f"⚠️ Чат {chat_id} не найден в БД")
                    return []
                
                # Получаем модераторов
                moderators_result = await session.execute(
                    select(Moderator).where(
                        Moderator.chat_id == chat.id,
                        Moderator.is_active == True
                    )
                )
                
                moderators = moderators_result.scalars().all()
                
                return [
                    {
                        "id": mod.id,
                        "username": mod.username,
                        "telegram_user_id": mod.telegram_user_id
                    }
                    for mod in moderators
                ]
        except Exception as e:
            logger.error(f"❌ Агент 5: Ошибка получения модераторов: {e}")
            return []
    
    async def save_negative_message(self, decision: Agent5Decision) -> bool:
        """Сохранить негативное сообщение в БД"""
        if decision.final_verdict != VerdictType.BAN:
            return False
        
        try:
            async with self.get_session() as session:
                # Найдем chat
                chat_result = await session.execute(
                    select(Chat).where(Chat.tg_chat_id == str(decision.chat_id))
                )
                chat = chat_result.scalar_one_or_none()
                
                if not chat:
                    # Создаем чат, если не существует
                    chat = Chat(tg_chat_id=str(decision.chat_id))
                    session.add(chat)
                    await session.flush()
                
                # Проверяем, нет ли уже такого негативного сообщения
                existing_result = await session.execute(
                    select(NegativeMessage).where(
                        NegativeMessage.chat_id == chat.id,
                        NegativeMessage.sender_username == decision.username
                    )
                )
                existing = existing_result.scalar_one_or_none()
                
                if not existing:
                    negative_msg = NegativeMessage(
                        chat_id=chat.id,
                        message_link=f"chat_id:{decision.chat_id}/message_id:{decision.message_id}",
                        sender_username=decision.username,
                        negative_reason=decision.reasoning,
                        is_sent_to_moderators=False
                    )
                    
                    session.add(negative_msg)
                    await session.commit()
                    logger.success(f"💾 Агент 5: Негативное сообщение сохранено в БД")
                    return True
                
                return False
        except Exception as e:
            logger.error(f"❌ Агент 5: Ошибка сохранения негативного сообщения: {e}")
            return False

# =========================
# Telegram Notifier
# =========================
class TelegramNotifier:
    def __init__(self, config: Agent5Config):
        self.config = config
        self.http_session: Optional[aiohttp.ClientSession] = None
    
    async def init(self):
        """Инициализация HTTP сессии"""
        timeout = aiohttp.ClientTimeout(total=30)
        self.http_session = aiohttp.ClientSession(timeout=timeout)
        logger.info("📡 Telegram Notifier инициализирован")
    
    async def close(self):
        """Закрытие HTTP сессии"""
        if self.http_session:
            await self.http_session.close()
            logger.info("📡 Telegram Notifier закрыт")
    
    async def send_notification(self, telegram_user_id: int, message: str, max_retries: int = 3) -> bool:
        """Отправка уведомления модератору"""
        if not self.http_session:
            logger.error("❌ HTTP сессия не инициализирована")
            return False
        
        url = f"{self.config.TELEGRAM_API_URL}{self.config.TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            'chat_id': telegram_user_id,
            'text': message,
            'parse_mode': 'HTML'
        }
        
        for attempt in range(1, max_retries + 1):
            try:
                async with self.http_session.post(url, json=data) as response:
                    if response.status == 200:
                        result = await response.json()
                        if result.get('ok'):
                            logger.success(f"📤 Уведомление отправлено пользователю {telegram_user_id}")
                            return True
                        else:
                            logger.error(f"❌ Telegram API ошибка: {result.get('description')}")
                    elif response.status >= 500:
                        # Серверная ошибка - retry
                        logger.warning(f"⚠️ Серверная ошибка {response.status}, повтор {attempt}/{max_retries}")
                        if attempt < max_retries:
                            await asyncio.sleep(2 ** attempt)
                            continue
                    else:
                        # Клиентская ошибка
                        error_text = await response.text()
                        logger.error(f"❌ Ошибка отправки уведомления {response.status}: {error_text}")
                        return False
            except Exception as e:
                logger.error(f"❌ Исключение при отправке уведомления (попытка {attempt}): {e}")
                if attempt < max_retries:
                    await asyncio.sleep(2 ** attempt)
                    continue
        
        return False

# =========================
# Основной Агент №5
# =========================
class ChatAgent5:
    def __init__(self):
        self.config = Agent5Config()
        self.db = Agent5DatabaseManager(self.config)
        self.telegram = TelegramNotifier(self.config)
        self.processed_count = 0
        self.start_time = datetime.now()
        logger.info("🚀 Чат-агент №5 инициализирован")
    
    async def init(self):
        """Инициализация агента"""
        await self.db.init_database()
        await self.telegram.init()
        logger.success("✅ Агент №5 полностью инициализирован")
    
    async def close(self):
        """Закрытие агента"""
        await self.db.close_database()
        await self.telegram.close()
        logger.info("👋 Агент №5 закрыт")
    
    def parse_agent_verdict(self, agent_data: Dict[str, Any]) -> AgentVerdict:
        """Парсинг вердикта агента"""
        return AgentVerdict(
            agent_id=agent_data.get("agent_id", 0),
            ban=agent_data.get("ban", False),
            reason=agent_data.get("reason", ""),
            confidence=agent_data.get("confidence", 0.5),
            timestamp=datetime.now()
        )
    
    def has_conflict(self, agent3: AgentVerdict, agent4: AgentVerdict) -> bool:
        """Проверка наличия конфликта между агентами"""
        # Конфликт если вердикты разные или уверенность низкая
        verdicts_differ = agent3.ban != agent4.ban
        low_confidence = agent3.confidence < 0.7 or agent4.confidence < 0.7
        return verdicts_differ or low_confidence
    
    def resolve_conflict(self, agent3: AgentVerdict, agent4: AgentVerdict, message_text: str) -> tuple[VerdictType, float, str]:
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
            # В реальности здесь может быть третья модель ИИ
            spam_keywords = ['купить', 'скидка', 'заработок', 'кликай', 'переходи', 'вступай']
            toxic_keywords = ['дурак', 'идиот', 'ненавижу', 'хуй', 'блять']
            
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
    
    def make_decision(self, agent3: AgentVerdict, agent4: AgentVerdict, message_data: Dict[str, Any]) -> Agent5Decision:
        """Принятие окончательного решения"""
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
                agent3, agent4, message_data.get("message", "")
            )
        
        decision_id = f"decision_{message_data.get('message_id', 0)}_{int(datetime.now().timestamp())}"
        
        return Agent5Decision(
            decision_id=decision_id,
            message_id=message_data.get("message_id", 0),
            chat_id=message_data.get("chat_id", 0),
            user_id=message_data.get("user_id", 0),
            username=message_data.get("username", ""),
            message_text=message_data.get("message", ""),
            final_verdict=final_verdict,
            confidence=confidence,
            reasoning=reasoning,
            agent3_verdict=agent3.to_verdict_type(),
            agent4_verdict=agent4.to_verdict_type(),
            was_conflict=has_conflict,
            timestamp=datetime.now()
        )
    
    async def notify_moderators(self, decision: Agent5Decision) -> bool:
        """Уведомление модераторов о решении"""
        if decision.final_verdict != VerdictType.BAN:
            return True  # Не нужно уведомлять о разрешенных сообщениях
        
        moderators = await self.db.get_chat_moderators(decision.chat_id)
        
        if not moderators:
            logger.warning(f"⚠️ Модераторы для чата {decision.chat_id} не найдены")
            return False
        
        # Формируем уведомление
        notification = (
            f"🚨 <b>Обнаружено нарушение!</b>\n\n"
            f"👤 <b>Пользователь:</b> {decision.username}\n"
            f"💬 <b>Сообщение:</b> {decision.message_text[:200]}{'...' if len(decision.message_text) > 200 else ''}\n"
            f"⚖️ <b>Решение:</b> {decision.final_verdict.value.upper()}\n"
            f"🎯 <b>Уверенность:</b> {decision.confidence:.1%}\n"
            f"📝 <b>Причина:</b> {decision.reasoning[:300]}{'...' if len(decision.reasoning) > 300 else ''}\n"
            f"🤖 <b>Agent3:</b> {decision.agent3_verdict.value}, <b>Agent4:</b> {decision.agent4_verdict.value}\n"
            f"⚡ <b>Конфликт:</b> {'Да' if decision.was_conflict else 'Нет'}"
        )
        
        success_count = 0
        for moderator in moderators:
            if moderator.get("telegram_user_id"):
                success = await self.telegram.send_notification(
                    moderator["telegram_user_id"], notification
                )
                if success:
                    success_count += 1
        
        logger.info(f"📤 Уведомления отправлены {success_count}/{len(moderators)} модераторам")
        return success_count > 0
    
    async def process_agent_reports(self, agent3_data: Dict[str, Any], agent4_data: Dict[str, Any]) -> Dict[str, Any]:
        """Обработка отчетов от агентов 3 и 4"""
        try:
            # Парсим вердикты
            agent3 = self.parse_agent_verdict(agent3_data)
            agent4 = self.parse_agent_verdict(agent4_data)
            
            # Принимаем решение
            decision = self.make_decision(agent3, agent4, agent3_data)
            
            # Сохраняем негативное сообщение, если нужно
            if decision.final_verdict == VerdictType.BAN:
                await self.db.save_negative_message(decision)
            
            # Уведомляем модераторов
            notification_sent = await self.notify_moderators(decision)
            
            self.processed_count += 1
            
            result = {
                "status": "processed",
                "decision": decision.to_dict(),
                "notification_sent": notification_sent
            }
            
            logger.success(f"✅ Агент 5: Решение принято - {decision.final_verdict.value}")
            return result
            
        except Exception as e:
            logger.error(f"❌ Агент 5: Ошибка обработки отчетов: {e}")
            return {"status": "error", "reason": str(e)}
    
    def get_health_metrics(self) -> Dict[str, Any]:
        uptime = datetime.now() - self.start_time
        return {
            "agent_id": 5,
            "status": "healthy",
            "uptime_seconds": int(uptime.total_seconds()),
            "processed_decisions": self.processed_count,
            "database_connected": self.db.engine is not None,
            "telegram_ready": self.telegram.http_session is not None,
        }

# =========================
# Тестирование
# =========================
async def test_agent_5():
    """Тест агента 5"""
    logger.info("=== ТЕСТ АГЕНТА 5 ===")
    
    agent = ChatAgent5()
    await agent.init()
    
    # Тестовые данные от агентов 3 и 4
    agent3_data = {
        "agent_id": 3,
        "ban": True,
        "reason": "Вердикт: да. Причина: Обнаружена реклама стороннего сообщества",
        "message": "Вступайте в наш чат @spamchannel!",
        "user_id": 123456789,
        "username": "@test_user",
        "chat_id": -1001234567890,
        "message_id": 42,
        "confidence": 0.85,
        "timestamp": datetime.now().isoformat()
    }
    
    agent4_data = {
        "agent_id": 4,
        "ban": False,
        "reason": "Нарушений не обнаружено. Сообщение соответствует правилам чата.",
        "message": "Вступайте в наш чат @spamchannel!",
        "user_id": 123456789,
        "username": "@test_user",
        "chat_id": -1001234567890,
        "message_id": 42,
        "confidence": 0.70,
        "timestamp": datetime.now().isoformat()
    }
    
    result = await agent.process_agent_reports(agent3_data, agent4_data)
    
    logger.info("Результат:")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    
    await agent.close()

# =========================
# Точка входа
# =========================
async def main():
    """Основная функция"""
    agent = ChatAgent5()
    try:
        await agent.init()
        logger.info("🚀 Агент №5 готов к работе")
        
        # В реальности здесь был бы цикл получения данных от агентов 3 и 4
        # через Redis или другую систему очередей
        while True:
            await asyncio.sleep(1)
            # Здесь должна быть логика получения отчетов от агентов
            
    except KeyboardInterrupt:
        logger.info("🛑 Получен сигнал остановки")
    finally:
        await agent.close()

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        asyncio.run(test_agent_5())
    else:
        asyncio.run(main())