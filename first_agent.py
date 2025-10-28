#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
=============================================================================
ЧАТ-АГЕНТ №1 с PostgreSQL - Координатор и Нормализатор
=============================================================================
- SQLAlchemy ORM для работы с PostgreSQL
- GigaChat интеграция
- Redis для очередей между агентами
- FastAPI REST API
- Полный мониторинг и логирование
=============================================================================
"""

import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
import redis

# SQLAlchemy imports
from sqlalchemy import (
    create_engine, Column, Integer, BigInteger, String, Text, Boolean,
    Float, DateTime, JSON, ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.sql import func
from sqlalchemy.future import select
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID, INTERVAL

# =========================
# Логирование
# =========================
Path("logs").mkdir(exist_ok=True)
logger.remove()
logger.add(
    "logs/agent_1_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="30 days",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} | {message}"
)
logger.add(lambda msg: print(msg, end=""), level="INFO", format="{time:HH:mm:ss} | {level} | {message}")

# =========================
# Конфигурация
# =========================
class Config:
    GIGACHAT_AUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    GIGACHAT_API_URL = "https://gigachat.devices.sberbank.ru/api/v1"

    # PostgreSQL настройки (только PostgreSQL)
    POSTGRES_HOST = os.getenv("POSTGRES_HOST", "176.108.248.211")
    POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
    POSTGRES_DB = os.getenv("POSTGRES_DB", "teleguard_db")
    POSTGRES_USER = os.getenv("POSTGRES_USER", "tguser")
    POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "mnvm7110")

    # Redis настройки
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

    # API настройки
    API_HOST = os.getenv("API_HOST", "0.0.0.0")
    API_PORT = int(os.getenv("API_PORT", "8001"))

    # Redis очереди/каналы
    QUEUE_TO_AGENT_2 = "queue:agent1_to_agent2"
    CHANNEL_STATUS_UPDATES = "channel:status_updates"
    CHANNEL_ERROR_NOTIFICATIONS = "channel:errors"
    CHANNEL_HEALTH_CHECKS = "channel:health_checks"

    # Лимиты GigaChat
    MAX_TOKENS_PER_REQUEST = 1024
    MAX_REQUESTS_PER_SECOND = 8
    TOKEN_REFRESH_MARGIN_MINUTES = 5

    # Дефолтный ключ GigaChat
    DEFAULT_GIGACHAT_CREDENTIALS = "MDE5YTJhZjEtYjhjOS03OTViLWFlZjEtZTg4MTgxNjQzNzdjOmE0MzRhNjExLTE2NGYtNDdjYS1iNTM2LThlMGViMmU0YzVmNg=="

    @property
    def database_url(self) -> str:
        """Асинхронный URL для PostgreSQL"""
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    @property
    def sync_database_url(self) -> str:
        """Синхронный URL для создания таблиц PostgreSQL"""
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

# =========================
# SQLAlchemy Models
# =========================
Base = declarative_base()

class Chat(Base):
    __tablename__ = "chats"

    chat_id = Column(BigInteger, primary_key=True, index=True)
    title = Column(String(255), nullable=True)
    chat_type = Column(String(50), default="group")
    added_at = Column(DateTime(timezone=True), default=func.now())
    ruleset_id = Column(Integer, ForeignKey("chat_rulesets.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

    # Relationships
    moderators = relationship("Moderator", back_populates="chat")
    messages = relationship("Message", back_populates="chat")
    rulesets = relationship("ChatRuleset", back_populates="chat")
    logs = relationship("ModerationLog", back_populates="chat")

class Moderator(Base):
    __tablename__ = "moderators"

    chat_id = Column(BigInteger, ForeignKey("chats.chat_id"), primary_key=True)
    user_id = Column(BigInteger, primary_key=True, index=True)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    added_by = Column(BigInteger, nullable=True)
    added_at = Column(DateTime(timezone=True), default=func.now())
    is_active = Column(Boolean, default=True)
    permissions = Column(JSON, default=dict)

    # Relationships
    chat = relationship("Chat", back_populates="moderators")

class ChatRuleset(Base):
    __tablename__ = "chat_rulesets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, ForeignKey("chats.chat_id"), nullable=False)
    version = Column(Integer, default=1)
    prompt = Column(Text, nullable=True)
    rules_json = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=func.now())
    created_by = Column(BigInteger, nullable=True)

    # Relationships
    chat = relationship("Chat", back_populates="rulesets")

    __table_args__ = (UniqueConstraint('chat_id', 'version', name='uq_chat_version'),)

class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, ForeignKey("chats.chat_id"), nullable=False, index=True)
    message_id = Column(BigInteger, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    message_text = Column(Text, nullable=True)
    message_type = Column(String(50), default="text")
    links_json = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), default=func.now(), index=True)

    # Данные обработки
    normalized_text = Column(Text, nullable=True)
    rules_applied = Column(JSON, default=list)
    confidence_score = Column(Float, default=0.0)
    processing_time_ms = Column(Integer, default=0)
    correlation_id = Column(String(36), nullable=True, index=True)
    processed_by = Column(String(50), default="agent_1")

    # Результаты модерации
    verdict = Column(String(50), nullable=True)
    action_taken = Column(String(100), nullable=True)
    ai_response = Column(Text, nullable=True)

    # Метаданные
    error_message = Column(Text, nullable=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    chat = relationship("Chat", back_populates="messages")
    links = relationship("MessageLink", back_populates="message", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint('chat_id', 'message_id', name='uq_chat_message'),)

class MessageLink(Base):
    __tablename__ = "message_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    url = Column(Text, nullable=False)
    domain = Column(String(255), nullable=True, index=True)
    is_whitelisted = Column(Boolean, default=False)
    risk_score = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), default=func.now())

    # Relationships
    message = relationship("Message", back_populates="links")

class Channel(Base):
    __tablename__ = "channels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    username = Column(String(255), nullable=True)
    tg_link = Column(Text, nullable=True)
    channel_type = Column(String(50), nullable=True)
    member_count = Column(Integer, default=0)
    is_monitored = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=func.now())

class ModerationLog(Base):
    __tablename__ = "moderation_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, ForeignKey("chats.chat_id"), nullable=False, index=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=True)
    moderator_id = Column(BigInteger, nullable=True)
    action_type = Column(String(100), nullable=False)
    action_details = Column(JSON, default=dict)
    correlation_id = Column(String(36), nullable=True)
    created_at = Column(DateTime(timezone=True), default=func.now(), index=True)

    # Relationships
    chat = relationship("Chat", back_populates="logs")
    message = relationship("Message")

# =========================
# Структуры данных для API
# =========================
@dataclass
class TelegramMessage:
    message_id: int
    chat_id: int
    sender_id: int
    message_text: str
    timestamp: datetime

@dataclass
class ChatRules:
    max_message_length: Optional[int] = 4000
    forbidden_words: List[str] = field(default_factory=list)
    allowed_commands: List[str] = field(default_factory=list)
    moderation_enabled: bool = True
    spam_detection: bool = True
    auto_reply: bool = True

@dataclass
class ProcessedData:
    originalMessage: str
    processedPrompt: str
    responseText: str
    message_id: int
    chat_id: int
    sender_id: int
    timestamp: datetime
    normalized_text: str
    rules_applied: List[str] = field(default_factory=list)
    confidence_score: float = 0.8
    processing_time_ms: int = 0
    agent_chain: List[str] = field(default_factory=lambda: ["agent_1"])
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))

@dataclass
class AgentMessage:
    agent_id: str
    message_type: str
    timestamp: str
    correlation_id: str
    data: Dict[str, Any]
    target_agent: str = "agent_2"
    priority: int = 1

# =========================
# Database Manager с PostgreSQL
# =========================
class DatabaseManager:
    def __init__(self, database_url: str, sync_database_url: str):
        self.database_url = database_url
        self.sync_database_url = sync_database_url
        self.engine = None
        self.async_session_factory = None

    async def init_database(self):
        """Инициализация PostgreSQL базы данных"""
        try:
            # Создание таблиц синхронно (для совместимости)
            sync_engine = create_engine(self.sync_database_url, echo=False)
            Base.metadata.create_all(sync_engine)
            sync_engine.dispose()

            # Создание асинхронного движка PostgreSQL
            self.engine = create_async_engine(
                self.database_url,
                echo=False,
                future=True,
                pool_pre_ping=True,
                pool_recycle=3600,
                pool_size=10,
                max_overflow=20
            )

            self.async_session_factory = async_sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False
            )

            logger.success(f"🗄️ PostgreSQL база данных инициализирована: {self.database_url}")
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации PostgreSQL: {e}")
            raise

    async def close_database(self):
        """Закрытие соединения с PostgreSQL"""
        if self.engine:
            await self.engine.dispose()
            logger.info("🗄️ Соединение с PostgreSQL закрыто")

    def get_session(self) -> AsyncSession:
        """Получить сессию PostgreSQL"""
        if not self.async_session_factory:
            raise RuntimeError("PostgreSQL database not initialized")
        return self.async_session_factory()

    async def upsert_chat(self, chat_id: int, title: str, chat_type: str = "group"):
        """Добавить/обновить информацию о чате в PostgreSQL"""
        try:
            async with self.get_session() as session:
                # Ищем существующий чат
                result = await session.execute(
                    select(Chat).where(Chat.chat_id == chat_id)
                )
                existing_chat = result.scalar_one_or_none()

                if existing_chat:
                    # Обновляем существующий
                    existing_chat.title = title
                    existing_chat.chat_type = chat_type
                    existing_chat.updated_at = func.now()
                else:
                    # Создаем новый
                    new_chat = Chat(
                        chat_id=chat_id,
                        title=title,
                        chat_type=chat_type
                    )
                    session.add(new_chat)

                await session.commit()
                logger.debug(f"💾 Чат {chat_id} добавлен/обновлен в PostgreSQL")
        except Exception as e:
            logger.error(f"❌ Ошибка upsert чата {chat_id} в PostgreSQL: {e}")

    async def add_moderator(self, chat_id: int, user_id: int, username: str = None,
                          first_name: str = None, added_by: int = None):
        """Добавить модератора в PostgreSQL"""
        try:
            async with self.get_session() as session:
                # Проверяем существование
                result = await session.execute(
                    select(Moderator).where(
                        Moderator.chat_id == chat_id,
                        Moderator.user_id == user_id
                    )
                )
                existing_moderator = result.scalar_one_or_none()

                if existing_moderator:
                    # Обновляем существующего
                    existing_moderator.username = username
                    existing_moderator.first_name = first_name
                    existing_moderator.is_active = True
                else:
                    # Создаем нового
                    new_moderator = Moderator(
                        chat_id=chat_id,
                        user_id=user_id,
                        username=username,
                        first_name=first_name,
                        added_by=added_by
                    )
                    session.add(new_moderator)

                await session.commit()
                logger.debug(f"👤 Модератор {user_id} добавлен в чат {chat_id}")
        except Exception as e:
            logger.error(f"❌ Ошибка добавления модератора в PostgreSQL: {e}")

    async def get_chat_rules(self, chat_id: int) -> Dict[str, Any]:
        """Получить правила чата из PostgreSQL"""
        try:
            async with self.get_session() as session:
                result = await session.execute(
                    select(ChatRuleset)
                    .where(ChatRuleset.chat_id == chat_id)
                    .where(ChatRuleset.is_active == True)
                    .order_by(ChatRuleset.version.desc(), ChatRuleset.created_at.desc())
                    .limit(1)
                )
                ruleset = result.scalar_one_or_none()

                if ruleset:
                    return {
                        "id": ruleset.id,
                        "version": ruleset.version,
                        "prompt": ruleset.prompt,
                        "rules": ruleset.rules_json or {}
                    }
                else:
                    # Дефолтные правила
                    return {
                        "id": None,
                        "version": 1,
                        "prompt": "Обработай сообщение согласно правилам чата",
                        "rules": {
                            "max_message_length": 4000,
                            "forbidden_words": [],
                            "allowed_commands": [],
                            "moderation_enabled": True,
                            "spam_detection": True,
                            "auto_reply": True
                        }
                    }
        except Exception as e:
            logger.error(f"❌ Ошибка получения правил чата {chat_id} из PostgreSQL: {e}")
            return {}

    async def store_message(self, tmsg: TelegramMessage, processed_data: ProcessedData,
                          links: List[str] = None, verdict: str = None,
                          action: str = None, error: str = None) -> int:
        """Сохранить сообщение и результаты обработки в PostgreSQL"""
        try:
            async with self.get_session() as session:
                # Проверяем существование сообщения
                result = await session.execute(
                    select(Message).where(
                        Message.chat_id == tmsg.chat_id,
                        Message.message_id == tmsg.message_id
                    )
                )
                existing_message = result.scalar_one_or_none()

                if existing_message:
                    # Обновляем существующее сообщение
                    existing_message.normalized_text = processed_data.normalized_text
                    existing_message.rules_applied = processed_data.rules_applied
                    existing_message.confidence_score = processed_data.confidence_score
                    existing_message.processing_time_ms = processed_data.processing_time_ms
                    existing_message.correlation_id = processed_data.correlation_id
                    existing_message.verdict = verdict
                    existing_message.action_taken = action
                    existing_message.ai_response = processed_data.responseText
                    existing_message.error_message = error
                    existing_message.processed_at = func.now()
                    existing_message.links_json = links or []

                    message_db_id = existing_message.id
                else:
                    # Создаем новое сообщение
                    new_message = Message(
                        chat_id=tmsg.chat_id,
                        message_id=tmsg.message_id,
                        user_id=tmsg.sender_id,
                        message_text=tmsg.message_text,
                        normalized_text=processed_data.normalized_text,
                        rules_applied=processed_data.rules_applied,
                        confidence_score=processed_data.confidence_score,
                        processing_time_ms=processed_data.processing_time_ms,
                        correlation_id=processed_data.correlation_id,
                        verdict=verdict,
                        action_taken=action,
                        ai_response=processed_data.responseText,
                        error_message=error,
                        processed_at=func.now(),
                        links_json=links or []
                    )
                    session.add(new_message)
                    await session.flush()  # Чтобы получить ID
                    message_db_id = new_message.id

                # Сохраняем ссылки отдельно
                if links and message_db_id:
                    # Удаляем старые ссылки для этого сообщения
                    if existing_message:
                        for old_link in existing_message.links:
                            await session.delete(old_link)

                    # Добавляем новые ссылки
                    for link in links:
                        try:
                            from urllib.parse import urlparse
                            domain = urlparse(link).netloc
                            new_link = MessageLink(
                                message_id=message_db_id,
                                url=link,
                                domain=domain
                            )
                            session.add(new_link)
                        except Exception:
                            pass  # Игнорируем ошибки парсинга URL

                await session.commit()
                logger.debug(f"💾 Сообщение {tmsg.message_id} сохранено в PostgreSQL (ID: {message_db_id})")
                return message_db_id

        except Exception as e:
            logger.error(f"❌ Ошибка сохранения сообщения в PostgreSQL: {e}")
            return 0

    async def get_chat_stats(self, chat_id: int) -> Dict[str, Any]:
        """Получить статистику чата из PostgreSQL"""
        try:
            async with self.get_session() as session:
                # Статистика за последние 24 часа (PostgreSQL INTERVAL)
                result = await session.execute(
                    select(
                        func.count(Message.id).label('total_messages'),
                        func.count().filter(Message.verdict == 'allow').label('allowed_messages'),
                        func.count().filter(Message.verdict == 'block').label('blocked_messages'),
                        func.count(func.distinct(Message.user_id)).label('unique_users'),
                        func.avg(Message.confidence_score).label('avg_confidence'),
                        func.avg(Message.processing_time_ms).label('avg_processing_time')
                    )
                    .where(Message.chat_id == chat_id)
                    .where(Message.created_at >= func.now() - func.cast('24 hours', INTERVAL))
                )
                stats_row = result.first()

                return {
                    'total_messages': stats_row.total_messages or 0,
                    'allowed_messages': stats_row.allowed_messages or 0,
                    'blocked_messages': stats_row.blocked_messages or 0,
                    'unique_users': stats_row.unique_users or 0,
                    'avg_confidence': float(stats_row.avg_confidence or 0),
                    'avg_processing_time': float(stats_row.avg_processing_time or 0)
                }
        except Exception as e:
            logger.error(f"❌ Ошибка получения статистики чата из PostgreSQL: {e}")
            return {}

    async def log_moderation_action(self, chat_id: int, message_id: int = None,
                                  moderator_id: int = None, action_type: str = "",
                                  action_details: Dict = None, correlation_id: str = None):
        """Логирование действий модерации в PostgreSQL"""
        try:
            async with self.get_session() as session:
                log_entry = ModerationLog(
                    chat_id=chat_id,
                    message_id=message_id,
                    moderator_id=moderator_id,
                    action_type=action_type,
                    action_details=action_details or {},
                    correlation_id=correlation_id
                )
                session.add(log_entry)
                await session.commit()
                logger.debug(f"📝 Действие модерации записано в PostgreSQL: {action_type}")
        except Exception as e:
            logger.error(f"❌ Ошибка записи лога модерации в PostgreSQL: {e}")

# =========================
# Dependency для получения сессии PostgreSQL
# =========================
async def get_db_session():
    """Dependency для получения сессии PostgreSQL"""
    if not database_manager:
        raise HTTPException(status_code=500, detail="PostgreSQL database not initialized")

    async with database_manager.get_session() as session:
        try:
            yield session
        except Exception as e:
            await session.rollback()
            logger.error(f"❌ Ошибка в сессии PostgreSQL: {e}")
            raise
        finally:
            await session.close()

# =========================
# Валидаторы
# =========================
def validate_telegram_message(d: Dict[str, Any]) -> TelegramMessage:
    try:
        msg_id = int(d["message_id"])
        chat_id = int(d["chat_id"])
        sender_id = int(d["sender_id"])
        text = str(d["message_text"]).strip()
        if not text:
            raise ValueError("message_text is empty")
        ts_raw = d.get("timestamp")
        if isinstance(ts_raw, str):
            ts = datetime.fromisoformat(ts_raw.replace('Z', '+00:00'))
        elif isinstance(ts_raw, (int, float)):
            ts = datetime.fromtimestamp(ts_raw)
        elif isinstance(ts_raw, datetime):
            ts = ts_raw
        else:
            ts = datetime.now()
        return TelegramMessage(
            message_id=msg_id,
            chat_id=chat_id,
            sender_id=sender_id,
            message_text=text,
            timestamp=ts
        )
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"Missing field: {e}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid telegram_message: {e}")

def validate_chat_rules(d: Optional[Dict[str, Any]]) -> ChatRules:
    if not d:
        return ChatRules()
    try:
        max_len = d.get("max_message_length", 4000)
        max_len = int(max_len) if max_len is not None else None
        forbidden = [str(w).lower().strip() for w in d.get("forbidden_words", []) if str(w).strip()]
        allowed = []
        for cmd in d.get("allowed_commands", []):
            cmd = str(cmd).strip()
            if cmd and not cmd.startswith("/"):
                cmd = "/" + cmd
            if cmd:
                allowed.append(cmd)
        return ChatRules(
            max_message_length=max_len,
            forbidden_words=forbidden,
            allowed_commands=allowed,
            moderation_enabled=bool(d.get("moderation_enabled", True)),
            spam_detection=bool(d.get("spam_detection", True)),
            auto_reply=bool(d.get("auto_reply", True)),
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid chat_rules: {e}")

def validate_prompt(value: Optional[str]) -> str:
    p = (value or "").strip()
    return p if p else "Обработай сообщение согласно правилам чата"

# =========================
# GigaChat клиент
# =========================
class GigaChatClient:
    def __init__(self, credentials: str):
        self.credentials = credentials
        self.access_token: Optional[str] = None
        self.token_expires_at: Optional[datetime] = None
        self._request_count = 0
        self._last_request_time = 0.0
        logger.info("🔧 GigaChat клиент инициализирован")

    async def _ensure_rate_limit(self):
        now = time.time()
        min_interval = 1.0 / Config.MAX_REQUESTS_PER_SECOND
        delta = now - self._last_request_time
        if delta < min_interval:
            await asyncio.sleep(min_interval - delta)
        self._last_request_time = time.time()

    async def get_access_token(self) -> str:
        if (self.access_token and self.token_expires_at and
                datetime.now() + timedelta(minutes=Config.TOKEN_REFRESH_MARGIN_MINUTES) < self.token_expires_at):
            return self.access_token

        await self._ensure_rate_limit()
        payload = {'scope': 'GIGACHAT_API_PERS'}
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json',
            'RqUID': str(uuid.uuid4()),
            'Authorization': f'Basic {self.credentials}'
        }

        try:
            async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
                response = await client.post(Config.GIGACHAT_AUTH_URL, headers=headers, data=payload)
                logger.debug(f"🔑 GigaChat auth request: status={response.status_code}")
                response.raise_for_status()
                token_data = response.json()

                if 'access_token' not in token_data:
                    logger.error(f"❌ Отсутствует access_token в ответе: {token_data}")
                    raise ValueError("access_token not found in response")

                self.access_token = token_data['access_token']
                expires_in = token_data.get('expires_in', 1800)
                self.token_expires_at = datetime.now() + timedelta(seconds=expires_in - 60)

                logger.success(f"🔑 Получен новый токен GigaChat (expires: {self.token_expires_at.strftime('%H:%M:%S')})")
                return self.access_token

        except Exception as e:
            logger.error(f"❌ Ошибка получения токена GigaChat: {e}")
            raise

    async def chat_completion(self, messages: List[Dict[str, str]], model: str = "GigaChat") -> Dict[str, Any]:
        await self._ensure_rate_limit()
        token = await self.get_access_token()

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": Config.MAX_TOKENS_PER_REQUEST,
            "stream": False,
        }

        try:
            async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
                response = await client.post(f"{Config.GIGACHAT_API_URL}/chat/completions", headers=headers, json=payload)
                logger.debug(f"🧠 GigaChat completion request: status={response.status_code}")
                response.raise_for_status()
                result = response.json()
                self._request_count += 1
                logger.debug(f"✅ GigaChat запрос #{self._request_count} выполнен успешно")
                return result

        except Exception as e:
            logger.error(f"❌ Ошибка GigaChat API: {e}")
            raise

# =========================
# Коммуникатор с агентами (Redis)
# =========================
class AgentCommunicator:
    def __init__(self, redis_url: str):
        try:
            self.redis_client = redis.from_url(redis_url, decode_responses=True)
            self.agent_id = "agent_1"
            logger.info(f"🔗 Коммуникатор подключен к Redis: {redis_url}")
        except Exception as e:
            logger.warning(f"⚠️ Не удалось подключиться к Redis: {e}")
            self.redis_client = None

    async def send_to_agent_2(self, processed_data: ProcessedData) -> bool:
        if not self.redis_client:
            logger.warning("⚠️ Redis недоступен, пропускаем отправку в Агент 2")
            return False

        try:
            agent_message = AgentMessage(
                agent_id=self.agent_id,
                message_type="process_request",
                timestamp=datetime.now().isoformat(),
                correlation_id=processed_data.correlation_id,
                data=asdict(processed_data),
                target_agent="agent_2",
                priority=1,
            )
            message_json = json.dumps(asdict(agent_message), ensure_ascii=False)
            result = await asyncio.to_thread(self.redis_client.lpush, Config.QUEUE_TO_AGENT_2, message_json)

            logger.success(f"📤 Отправлено Агенту 2 | msg_id={processed_data.message_id} | corr={processed_data.correlation_id[:8]}...")

            status_msg = {
                "agent_id": self.agent_id,
                "status": "message_sent_to_agent_2",
                "timestamp": datetime.now().isoformat(),
                "data": {"message_id": processed_data.message_id, "correlation_id": processed_data.correlation_id, "queue_size": result},
            }
            await asyncio.to_thread(self.redis_client.publish, Config.CHANNEL_STATUS_UPDATES, json.dumps(status_msg))
            return True

        except Exception as e:
            logger.error(f"❌ Ошибка отправки Агенту 2: {e}")
            return False

    async def send_health_status(self, metrics: Dict[str, Any]) -> bool:
        if not self.redis_client:
            return False
        try:
            health_message = {
                "agent_id": self.agent_id,
                "status": "healthy",
                "metrics": metrics,
                "timestamp": datetime.now().isoformat(),
            }
            await asyncio.to_thread(self.redis_client.publish, Config.CHANNEL_HEALTH_CHECKS, json.dumps(health_message))
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка отправки health: {e}")
            return False

# =========================
# Основной Агент №1 с PostgreSQL
# =========================
class ChatAgent1:
    def __init__(self, gigachat_credentials: str, redis_url: str, database_manager: DatabaseManager):
        self.gigachat = GigaChatClient(gigachat_credentials)
        self.communicator = AgentCommunicator(redis_url)
        self.db = database_manager
        self.agent_id = "agent_1"
        self.start_time = datetime.now()
        self.processed_messages_count = 0
        self.error_count = 0
        logger.info("🚀 Чат-агент №1 с PostgreSQL инициализирован")

    def extract_links(self, text: str) -> List[str]:
        """Извлечение ссылок из текста"""
        import re
        link_pattern = re.compile(r'https?://\S+')
        return [match.group(0) for match in link_pattern.finditer(text or "")]

    async def normalize_message(self, text: str) -> str:
        if not text:
            return ""
        normalized = " ".join(text.split())
        if len(normalized) > 4000:
            normalized = normalized[:4000] + "..."
            logger.warning("✂️ Сообщение обрезано до 4000 символов")
        return normalized

    async def apply_chat_rules(self, message: str, rules: ChatRules) -> Tuple[str, List[str]]:
        applied: List[str] = []
        processed = message

        if not rules.moderation_enabled:
            return processed, applied

        lowered = processed.lower()
        for w in rules.forbidden_words:
            if w and w in lowered:
                processed = processed.replace(w, "*" * len(w))
                applied.append(f"filtered_word_{w}")

        if rules.max_message_length and len(processed) > rules.max_message_length:
            processed = processed[:rules.max_message_length] + "..."
            applied.append("length_limit")

        if processed.startswith("/"):
            cmd = processed.split()[0]
            if rules.allowed_commands and cmd not in rules.allowed_commands:
                applied.append("unauthorized_command")

        return processed, applied

    async def generate_response(self, message: str, prompt: str, rules: ChatRules) -> str:
        system_prompt = f"""
Ты - помощник модерации чата. Анализируй сообщения и давай краткие ответы.

Правила чата:
- Максимальная длина: {rules.max_message_length or 'не ограничено'}
- Модерация: {'включена' if rules.moderation_enabled else 'отключена'}
- Детекция спама: {'включена' if rules.spam_detection else 'отключена'}
- Запрещенные слова: {', '.join(rules.forbidden_words) if rules.forbidden_words else 'нет'}
- Разрешенные команды: {', '.join(rules.allowed_commands) if rules.allowed_commands else 'любые'}

Инструкции: {prompt}

Отвечай кратко и по делу. Не более 200 символов.
""".strip()

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ]

        try:
            response = await self.gigachat.chat_completion(messages)
            if response.get("choices") and len(response["choices"]) > 0:
                generated_text = response["choices"][0]["message"]["content"].strip()
                logger.success(f"🤖 GigaChat ответ: '{generated_text}' ({len(generated_text)} символов)")
                return generated_text
            else:
                logger.warning("⚠️ GigaChat вернул пустой ответ")
                return "Не удалось сгенерировать ответ."
        except Exception as e:
            self.error_count += 1
            logger.error(f"❌ Ошибка генерации ответа: {e}")
            return "Произошла ошибка при генерации ответа."

    async def process_message(self, tmsg: TelegramMessage, prompt: str, rules: ChatRules) -> ProcessedData:
        start = time.time()
        corr = str(uuid.uuid4())

        try:
            # Инициализируем чат в PostgreSQL
            await self.db.upsert_chat(tmsg.chat_id, f"Chat_{tmsg.chat_id}")

            # Обрабатываем сообщение
            normalized = await self.normalize_message(tmsg.message_text)
            processed_text, applied_rules = await self.apply_chat_rules(normalized, rules)
            response_text = await self.generate_response(processed_text, prompt, rules)
            processing_time_ms = int((time.time() - start) * 1000)

            # Извлекаем ссылки
            links = self.extract_links(tmsg.message_text)

            pdata = ProcessedData(
                originalMessage=tmsg.message_text,
                processedPrompt=prompt,
                responseText=response_text,
                message_id=tmsg.message_id,
                chat_id=tmsg.chat_id,
                sender_id=tmsg.sender_id,
                timestamp=tmsg.timestamp,
                normalized_text=normalized,
                rules_applied=applied_rules,
                confidence_score=0.85 if not applied_rules else 0.75,
                processing_time_ms=processing_time_ms,
                agent_chain=["agent_1"],
                correlation_id=corr,
            )

            # Сохраняем в PostgreSQL
            await self.db.store_message(tmsg, pdata, links)

            # Логируем действие модерации в PostgreSQL
            await self.db.log_moderation_action(
                chat_id=tmsg.chat_id,
                action_type="message_processed",
                action_details={
                    "rules_applied": applied_rules,
                    "confidence_score": pdata.confidence_score,
                    "processing_time_ms": processing_time_ms
                },
                correlation_id=corr
            )

            self.processed_messages_count += 1
            return pdata

        except Exception as e:
            self.error_count += 1
            processing_time_ms = int((time.time() - start) * 1000)
            logger.error(f"❌ Ошибка обработки сообщения: {e}")

            # Логируем ошибку в PostgreSQL
            try:
                await self.db.log_moderation_action(
                    chat_id=tmsg.chat_id,
                    action_type="processing_error",
                    action_details={"error": str(e)},
                    correlation_id=corr
                )
            except:
                pass

            return ProcessedData(
                originalMessage=tmsg.message_text,
                processedPrompt=prompt,
                responseText="❌ Ошибка обработки сообщения.",
                message_id=tmsg.message_id,
                chat_id=tmsg.chat_id,
                sender_id=tmsg.sender_id,
                timestamp=tmsg.timestamp,
                normalized_text=tmsg.message_text,
                rules_applied=["error_occurred"],
                confidence_score=0.0,
                processing_time_ms=processing_time_ms,
                agent_chain=["agent_1"],
                correlation_id=corr,
            )

    async def process_and_forward(self, tmsg: TelegramMessage, prompt: str, rules: ChatRules) -> ProcessedData:
        pdata = await self.process_message(tmsg, prompt, rules)
        success = await self.communicator.send_to_agent_2(pdata)
        if success:
            logger.success(f"🎯 Сообщение {pdata.message_id} успешно передано Агенту 2")
        else:
            logger.error(f"❌ Не удалось передать сообщение {pdata.message_id} Агенту 2")
        return pdata

    def get_health_metrics(self) -> Dict[str, Any]:
        uptime = datetime.now() - self.start_time
        return {
            "agent_id": self.agent_id,
            "status": "healthy",
            "uptime_seconds": int(uptime.total_seconds()),
            "processed_messages": self.processed_messages_count,
            "error_count": self.error_count,
            "error_rate": self.error_count / max(self.processed_messages_count, 1),
            "gigachat_requests": getattr(self.gigachat, "_request_count", 0),
            "last_activity": datetime.now().isoformat(),
        }

# =========================
# Глобальные переменные
# =========================
agent: Optional[ChatAgent1] = None
database_manager: Optional[DatabaseManager] = None
config = Config()

# =========================
# Современный lifespan FastAPI
# =========================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global agent, database_manager

    creds = os.getenv("GIGACHAT_CREDENTIALS", config.DEFAULT_GIGACHAT_CREDENTIALS)
    if not creds:
        logger.critical("❌ Не задан GIGACHAT_CREDENTIALS")
        raise RuntimeError("GIGACHAT_CREDENTIALS is required")

    logger.info(f"🔑 Используем GIGACHAT_CREDENTIALS: {creds[:20]}...")
    logger.info(f"🗄️ Подключаемся к PostgreSQL: {config.database_url}")

    # Инициализация PostgreSQL
    database_manager = DatabaseManager(config.database_url, config.sync_database_url)
    await database_manager.init_database()

    # Инициализация агента
    agent = ChatAgent1(creds, config.REDIS_URL, database_manager)

    await agent.communicator.send_health_status(agent.get_health_metrics())
    logger.success("✅ Агент №1 с PostgreSQL запущен и готов к работе")

    yield

    # Shutdown
    if agent:
        metrics = agent.get_health_metrics()
        metrics["status"] = "shutting_down"
        await agent.communicator.send_health_status(metrics)

    if database_manager:
        await database_manager.close_database()

    logger.info("🛑 Агент №1 остановлен")

# =========================
# FastAPI приложение
# =========================
app = FastAPI(
    title="🤖 Чат-агент №1 с PostgreSQL",
    description="Агент №1: нормализация, правила, GigaChat, PostgreSQL, передача в Агент 2",
    version="5.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# -------------------------
# API endpoints
# -------------------------
@app.post("/process_message")
async def process_message_endpoint(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not agent:
        raise HTTPException(status_code=500, detail="Агент не инициализирован")

    try:
        telegram_message = validate_telegram_message(payload.get("telegram_message", {}))
        prompt = validate_prompt(payload.get("prompt"))
        chat_rules = validate_chat_rules(payload.get("chat_rules"))
        processed_data = await agent.process_and_forward(telegram_message, prompt, chat_rules)
        return asdict(processed_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка API /process_message: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/process_batch")
async def process_batch_endpoint(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not agent:
        raise HTTPException(status_code=500, detail="Агент не инициализирован")

    messages = payload.get("messages", [])
    if not isinstance(messages, list) or not messages:
        raise HTTPException(status_code=400, detail="messages must be a non-empty list")
    if len(messages) > 10:
        raise HTTPException(status_code=400, detail="Максимум 10 сообщений за раз")

    try:
        tasks = []
        for item in messages:
            telegram_message = validate_telegram_message(item.get("telegram_message", {}))
            prompt = validate_prompt(item.get("prompt"))
            chat_rules = validate_chat_rules(item.get("chat_rules"))
            tasks.append(agent.process_and_forward(telegram_message, prompt, chat_rules))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        output: List[Dict[str, Any]] = []
        for result in results:
            if isinstance(result, ProcessedData):
                output.append(asdict(result))
        return output

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка /process_batch: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    if not agent:
        return {"status": "error", "message": "Агент не инициализирован"}

    metrics = agent.get_health_metrics()

    # Проверка Redis
    try:
        if agent.communicator.redis_client:
            await asyncio.to_thread(agent.communicator.redis_client.ping)
            metrics["redis_status"] = "connected"
        else:
            metrics["redis_status"] = "not_configured"
    except Exception as e:
        metrics["redis_status"] = "disconnected"
        metrics["redis_error"] = str(e)

    # Проверка PostgreSQL
    try:
        if database_manager and database_manager.engine:
            async with database_manager.get_session() as session:
                result = await session.execute(select(func.count()).select_from(Chat))
                chat_count = result.scalar()
            metrics["database_status"] = "connected"
            metrics["database_type"] = "postgresql"
            metrics["total_chats"] = chat_count
        else:
            metrics["database_status"] = "not_configured"
    except Exception as e:
        metrics["database_status"] = "disconnected"
        metrics["database_error"] = str(e)

    # Проверка GigaChat
    try:
        if agent.gigachat.access_token and agent.gigachat.token_expires_at:
            time_left = agent.gigachat.token_expires_at - datetime.now()
            metrics["gigachat_token_expires_in_minutes"] = int(time_left.total_seconds() / 60)
            metrics["gigachat_token_status"] = "valid" if time_left.total_seconds() > 0 else "expired"
        else:
            metrics["gigachat_token_status"] = "not_obtained"
    except Exception as e:
        metrics["gigachat_token_status"] = "error"
        metrics["gigachat_error"] = str(e)

    metrics["api_status"] = "healthy"
    return metrics

@app.get("/metrics")
async def metrics():
    if not agent:
        raise HTTPException(status_code=500, detail="Агент не инициализирован")

    metrics = agent.get_health_metrics()

    try:
        if agent.communicator.redis_client:
            queue_size = await asyncio.to_thread(agent.communicator.redis_client.llen, Config.QUEUE_TO_AGENT_2)
            metrics["queue_to_agent_2_size"] = int(queue_size or 0)

        metrics["gigachat_token_valid"] = agent.gigachat.access_token is not None
        if agent.gigachat.token_expires_at:
            time_left = agent.gigachat.token_expires_at - datetime.now()
            metrics["gigachat_token_expires_in_minutes"] = int(time_left.total_seconds() / 60)

        # Статистика PostgreSQL
        if database_manager:
            async with database_manager.get_session() as session:
                total_messages_result = await session.execute(select(func.count()).select_from(Message))
                total_moderators_result = await session.execute(select(func.count()).select_from(Moderator))
                total_chats_result = await session.execute(select(func.count()).select_from(Chat))

                metrics["database_stats"] = {
                    "total_messages": total_messages_result.scalar() or 0,
                    "total_moderators": total_moderators_result.scalar() or 0,
                    "total_chats": total_chats_result.scalar() or 0
                }

    except Exception as e:
        logger.warning(f"⚠️ Не удалось собрать дополнительные метрики: {e}")
        metrics["metrics_collection_error"] = str(e)

    return metrics

@app.get("/chat/{chat_id}/stats")
async def get_chat_stats(chat_id: int):
    """Получить статистику чата из PostgreSQL"""
    if not agent:
        raise HTTPException(status_code=500, detail="Агент не инициализирован")

    try:
        stats = await agent.db.get_chat_stats(chat_id)
        return {"chat_id": chat_id, "stats": stats}
    except Exception as e:
        logger.error(f"❌ Ошибка получения статистики чата {chat_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat/{chat_id}/moderator")
async def add_moderator_endpoint(chat_id: int, payload: Dict[str, Any]):
    """Добавить модератора в чат через PostgreSQL"""
    if not agent:
        raise HTTPException(status_code=500, detail="Агент не инициализирован")

    try:
        user_id = int(payload["user_id"])
        username = payload.get("username")
        first_name = payload.get("first_name")
        added_by = payload.get("added_by")

        await agent.db.add_moderator(chat_id, user_id, username, first_name, added_by)
        return {"success": True, "message": f"Модератор {user_id} добавлен в чат {chat_id}"}
    except Exception as e:
        logger.error(f"❌ Ошибка добавления модератора: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/chat/{chat_id}/messages")
async def get_chat_messages(
        chat_id: int,
        limit: int = 50,
        offset: int = 0,
        session: AsyncSession = Depends(get_db_session)
):
    """Получить сообщения чата с пагинацией из PostgreSQL"""
    try:
        result = await session.execute(
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(Message.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        messages = result.scalars().all()

        return {
            "chat_id": chat_id,
            "messages": [
                {
                    "id": msg.id,
                    "message_id": msg.message_id,
                    "user_id": msg.user_id,
                    "message_text": msg.message_text,
                    "normalized_text": msg.normalized_text,
                    "rules_applied": msg.rules_applied,
                    "confidence_score": msg.confidence_score,
                    "verdict": msg.verdict,
                    "ai_response": msg.ai_response,
                    "created_at": msg.created_at.isoformat() if msg.created_at else None,
                    "correlation_id": msg.correlation_id
                }
                for msg in messages
            ],
            "pagination": {
                "limit": limit,
                "offset": offset,
                "count": len(messages)
            }
        }
    except Exception as e:
        logger.error(f"❌ Ошибка получения сообщений чата {chat_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
async def root():
    return {
        "service": "Чат-агент №1 с PostgreSQL",
        "version": "5.0.0",
        "status": "running",
        "features": [
            "🗄️ PostgreSQL база данных с SQLAlchemy ORM",
            "🔧 Современный lifespan FastAPI",
            "🔑 GigaChat интеграция",
            "📊 Полный мониторинг и метрики",
            "🛡️ Расширенные правила модерации",
            "📨 Redis коммуникация с Агентом 2",
            "🔍 Dependency Injection для сессий БД"
        ],
        "database": {
            "type": "postgresql",
            "host": config.POSTGRES_HOST,
            "port": config.POSTGRES_PORT,
            "database": config.POSTGRES_DB,
            "orm": "SQLAlchemy 2.0 + async sessions"
        },
        "endpoints": {
            "process_message": "POST /process_message",
            "process_batch": "POST /process_batch",
            "health": "GET /health",
            "metrics": "GET /metrics",
            "chat_stats": "GET /chat/{chat_id}/stats",
            "add_moderator": "POST /chat/{chat_id}/moderator",
            "chat_messages": "GET /chat/{chat_id}/messages"
        }
    }

# =========================
# Точка входа
# =========================
if __name__ == "__main__":
    logger.info("🚀 Запуск Чат-агента №1 с PostgreSQL...")
    uvicorn.run(
        app,
        host=config.API_HOST,
        port=config.API_PORT,
        reload=False,
        access_log=True,
        log_level="info",
    )