#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ЧАТ-АГЕНТ №1 с PostgreSQL - Координатор и Нормализатор (ГОТОВЫЙ ACCESS TOKEN)
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
# Конфигурация (ГОТОВЫЙ ACCESS TOKEN)
# =========================
class Config:
    GIGACHAT_API_URL = "https://gigachat.devices.sberbank.ru/api/v1"
    
    # PostgreSQL настройки
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
    
    # ГигаЧат настройки - ГОТОВЫЙ ACCESS TOKEN
    from token inport TOKEN
    GIGACHAT_ACCESS_TOKEN = TOKEN
    @property
    def database_url(self) -> str:
        """Асинхронный URL для PostgreSQL"""
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
    
    @property
    def sync_database_url(self) -> str:
        """Синхронный URL для создания таблиц PostgreSQL"""
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

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
    
    __table_args__ = (UniqueConstraint('chat_id', 'message_id', name='uq_chat_message'),)

# =========================
# GigaChat клиент (ГОТОВЫЙ ACCESS TOKEN)
# =========================
class GigaChatClient:
    def __init__(self, access_token: str):
        self.access_token = access_token
        self._request_count = 0
        self._last_request_time = 0.0
        logger.info("🔧 GigaChat клиент инициализирован с готовым Access Token")
    
    async def _ensure_rate_limit(self):
        now = time.time()
        min_interval = 1.0 / Config.MAX_REQUESTS_PER_SECOND
        delta = now - self._last_request_time
        if delta < min_interval:
            await asyncio.sleep(min_interval - delta)
        self._last_request_time = time.time()
    
    async def test_token(self) -> bool:
        """Тестирование Access Token"""
        test_url = f"{Config.GIGACHAT_API_URL}/models"
        
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        }
        
        try:
            async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
                response = await client.get(test_url, headers=headers)
                
                if response.status_code == 200:
                    models = response.json()
                    logger.success(f"✅ Access Token работает! Доступно моделей: {len(models.get('data', []))}")
                    return True
                else:
                    logger.error(f"❌ Access Token не работает. Статус: {response.status_code}")
                    return False
        except Exception as e:
            logger.error(f"❌ Ошибка тестирования токена: {e}")
            return False
    
    async def chat_completion(self, messages: List[Dict[str, str]], model: str = "GigaChat") -> Dict[str, Any]:
        """Отправка запроса к GigaChat API с готовым токеном"""
        await self._ensure_rate_limit()
        
        headers = {
            "Authorization": f"Bearer {self.access_token}",
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

# =========================
# Основной Агент №1 (ГОТОВЫЙ ACCESS TOKEN)
# =========================
class ChatAgent1:
    def __init__(self, access_token: str, redis_url: str, database_manager):
        self.gigachat = GigaChatClient(access_token)
        self.db = database_manager
        self.agent_id = "agent_1"
        self.start_time = datetime.now()
        self.processed_messages_count = 0
        self.error_count = 0
        logger.info("🚀 Чат-агент №1 с PostgreSQL запущен с готовым Access Token")

# =========================
# Глобальные переменные
# =========================
agent: Optional[ChatAgent1] = None
database_manager = None
config = Config()

# =========================
# Современный lifespan FastAPI (ГОТОВЫЙ ACCESS TOKEN)
# =========================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global agent, database_manager
    
    access_token = config.GIGACHAT_ACCESS_TOKEN
    
    logger.info(f"🔑 Используем готовый Access Token: {access_token[:50]}...")
    logger.info(f"🗄️ Подключаемся к PostgreSQL: {config.database_url}")
    
    # Инициализация PostgreSQL
    database_manager = DatabaseManager(config.database_url, config.sync_database_url)
    await database_manager.init_database()
    
    # Инициализация агента
    agent = ChatAgent1(access_token, config.REDIS_URL, database_manager)
    
    # Тестируем токен
    if await agent.gigachat.test_token():
        logger.success("✅ Агент №1 с PostgreSQL запущен и готов к работе (с готовым Access Token)")
    else:
        logger.error("❌ Access Token не работает!")
        raise RuntimeError("Invalid Access Token")
    
    yield
    
    # Shutdown
    if database_manager:
        await database_manager.close_database()
    logger.info("🛑 Агент №1 остановлен")

# =========================
# FastAPI приложение (ГОТОВЫЙ ACCESS TOKEN)
# =========================
app = FastAPI(
    title="🤖 Чат-агент №1 с PostgreSQL (Готовый Access Token)",
    description="Агент №1: нормализация, правила, GigaChat с готовым Access Token, PostgreSQL",
    version="7.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

@app.get("/")
async def root():
    return {
        "service": "Чат-агент №1 с PostgreSQL (Готовый Access Token)",
        "version": "7.0.0",
        "status": "running",
        "updates": [
            "🔑 Использует готовый Access Token вместо динамического получения",
            "⚡ Упрощенная авторизация без дополнительных запросов",
            "📝 Access Token встроен в код",
            "🧪 Поддержка проверки сообщений из бота"
        ],
        "features": [
            "🗄️ PostgreSQL база данных с SQLAlchemy ORM",
            "🔧 Современный lifespan FastAPI",
            "🔑 GigaChat с готовым Access Token",
            "📊 Полный мониторинг и метрики",
            "🛡️ Расширенные правила модерации"
        ],
        "database": {
            "type": "postgresql",
            "host": config.POSTGRES_HOST,
            "port": config.POSTGRES_PORT,
            "database": config.POSTGRES_DB,
            "orm": "SQLAlchemy 2.0 + async sessions"
        },
        "gigachat_auth": {
            "method": "ready_access_token",
            "token_length": len(config.GIGACHAT_ACCESS_TOKEN),
            "note": "Токен встроен в код"
        }
    }

@app.get("/health")
async def health():
    if not agent:
        return {"status": "error", "message": "Агент не инициализирован"}
    
    # Проверяем токен
    token_valid = await agent.gigachat.test_token()
    
    return {
        "status": "healthy" if token_valid else "degraded",
        "agent_id": agent.agent_id,
        "uptime_seconds": int((datetime.now() - agent.start_time).total_seconds()),
        "processed_messages": agent.processed_messages_count,
        "error_count": agent.error_count,
        "gigachat_auth": "ready_access_token",
        "token_valid": token_valid,
        "database": "postgresql",
        "version": "7.0.0"
    }

# =========================
# Точка входа (ГОТОВЫЙ ACCESS TOKEN)
# =========================
if __name__ == "__main__":
    print("=" * 70)
    print("🚀 ЧАТ-АГЕНТ №1 с PostgreSQL - READY ACCESS TOKEN")
    print("=" * 70)
    print("🔑 Access Token встроен в код и готов к использованию")
    print("⚡ Упрощенная авторизация без дополнительных запросов")
    print("🧪 Поддержка проверки сообщений из Telegram бота")
    print("⏰ Примечание: Access Token может истечь через ~30 минут")
    print()
    print("🔄 При необходимости обновите токен через:")
    print("   python get_gigachat_token.py")
    print()
    print("🚀 Запускаем Агент №1...")
    print("=" * 70)
    
    uvicorn.run(
        app,
        host=config.API_HOST,
        port=config.API_PORT,
        reload=False,
        access_log=True,
        log_level="info",
    )
