#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
ЧАТ-АГЕНТ №2 с PostgreSQL - Анализатор и Распределитель
=============================================================================
- Использует модели БД из first_agent.py
- Интеграция с PostgreSQL через SQLAlchemy ORM
- GigaChat интеграция для анализа сообщений
- Redis для коммуникации с другими агентами
- FastAPI REST API для управления
=============================================================================
"""

import asyncio
import json
import os
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
import redis

# SQLAlchemy imports из first_agent.py
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func

# Импортируем общие модели из first_agent.py
import sys
sys.path.append('.')
try:
    from first_agent import Base, Chat, Message, Moderator, NegativeMessage, DatabaseManager, Config
except ImportError:
    # Если не удается импортировать, создаем заново
    from sqlalchemy import Column, Integer, BigInteger, String, Text, Boolean, ForeignKey, DateTime, JSON
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.orm import relationship
    
    Base = declarative_base()
    
    class Chat(Base):
        __tablename__ = "chats"
        chat_id = Column(BigInteger, primary_key=True, index=True)
        title = Column(String(255), nullable=True)
        chat_type = Column(String(50), default="group")
        added_at = Column(DateTime(timezone=True), default=func.now())
        is_active = Column(Boolean, default=True)
        created_at = Column(DateTime(timezone=True), default=func.now())
        updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
        
        moderators = relationship("Moderator", back_populates="chat")
        messages = relationship("Message", back_populates="chat")
        
    class Message(Base):
        __tablename__ = "messages"
        id = Column(Integer, primary_key=True, autoincrement=True)
        chat_id = Column(BigInteger, ForeignKey("chats.chat_id"), nullable=False, index=True)
        message_id = Column(BigInteger, nullable=False, index=True)
        user_id = Column(BigInteger, nullable=False, index=True)
        username = Column(String(255), nullable=True)
        message_text = Column(Text, nullable=True)
        created_at = Column(DateTime(timezone=True), default=func.now(), index=True)
        processed_at = Column(DateTime(timezone=True), nullable=True)
        ai_response = Column(Text, nullable=True)
        
        chat = relationship("Chat", back_populates="messages")
        
    class Moderator(Base):
        __tablename__ = "moderators"
        chat_id = Column(BigInteger, ForeignKey("chats.chat_id"), primary_key=True)
        user_id = Column(BigInteger, primary_key=True, index=True)
        username = Column(String(255), nullable=True)
        telegram_user_id = Column(BigInteger, nullable=True)
        is_active = Column(Boolean, default=True)
        added_at = Column(DateTime(timezone=True), default=func.now())
        
        chat = relationship("Chat", back_populates="moderators")
        
    class NegativeMessage(Base):
        __tablename__ = "negative_messages"
        id = Column(Integer, primary_key=True, autoincrement=True)
        chat_id = Column(BigInteger, ForeignKey("chats.chat_id"), nullable=False)
        message_id = Column(BigInteger, nullable=True)
        sender_username = Column(String(255), nullable=True)
        sender_id = Column(BigInteger, nullable=True)
        message_text = Column(Text, nullable=True)
        negative_reason = Column(Text, nullable=True)
        is_sent_to_moderators = Column(Boolean, default=False)
        created_at = Column(DateTime(timezone=True), default=func.now())

# =========================
# Логирование
# =========================
from pathlib import Path
Path("logs").mkdir(exist_ok=True)

logger.remove()
logger.add(
    "logs/agent_2_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="30 days",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} | {message}"
)
logger.add(lambda msg: print(msg, end=""), level="INFO", format="{time:HH:mm:ss} | {level} | {message}")

# =========================
# Конфигурация
# =========================
class Agent2Config:
    # PostgreSQL настройки (используем те же, что в first_agent.py)
    POSTGRES_HOST = os.getenv("POSTGRES_HOST", "176.108.248.211")
    POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
    POSTGRES_DB = os.getenv("POSTGRES_DB", "teleguard_db")
    POSTGRES_USER = os.getenv("POSTGRES_USER", "tguser")
    POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "mnvm7110")
    
    # Redis настройки
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
    
    # API настройки
    API_HOST = os.getenv("API_HOST", "0.0.0.0")
    API_PORT = int(os.getenv("API_PORT", "8002"))  # Порт 8002 для агента 2
    
    # GigaChat
    GIGACHAT_AUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    GIGACHAT_API_URL = "https://gigachat.devices.sberbank.ru/api/v1"
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
# GigaChat Client
# =========================
class GigaChatClient:
    def __init__(self, credentials: str):
        self.credentials = credentials
        self.access_token: Optional[str] = None
        self.token_expires_at: Optional[datetime] = None
        logger.info("🔧 GigaChat клиент инициализирован")
    
    async def get_access_token(self) -> str:
        if (self.access_token and self.token_expires_at and 
            datetime.now() < self.token_expires_at):
            return self.access_token
        
        payload = {'scope': 'GIGACHAT_API_PERS'}
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json',
            'RqUID': str(uuid.uuid4()),
            'Authorization': f'Basic {self.credentials}'
        }
        
        try:
            async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
                response = await client.post(Agent2Config.GIGACHAT_AUTH_URL, headers=headers, data=payload)
                response.raise_for_status()
                token_data = response.json()
                
                self.access_token = token_data['access_token']
                expires_in = token_data.get('expires_in', 1800)
                self.token_expires_at = datetime.now() + datetime.timedelta(seconds=expires_in - 60)
                
                logger.success(f"🔑 Получен новый токен GigaChat")
                return self.access_token
        except Exception as e:
            logger.error(f"❌ Ошибка получения токена GigaChat: {e}")
            raise
    
    async def analyze_message(self, message_text: str, rules: List[str]) -> Dict[str, Any]:
        token = await self.get_access_token()
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        
        rules_text = "\n".join([f"{i+1}. {rule}" for i, rule in enumerate(rules)])
        system_prompt = f"""Ты — модератор Telegram-канала. 
        Анализируй сообщения и определяй нарушения.
        
        Правила чата:
        {rules_text}
        
        Ответь в формате: 'Вердикт: да/нет. Причина: [объяснение]'"""
        
        payload = {
            "model": "GigaChat",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Анализируй сообщение: {message_text}"}
            ],
            "temperature": 0.2,
            "max_tokens": 256,
            "stream": False,
        }
        
        try:
            async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
                response = await client.post(f"{Agent2Config.GIGACHAT_API_URL}/chat/completions", 
                                           headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()
                
                if result.get("choices") and len(result["choices"]) > 0:
                    content = result["choices"][0]["message"]["content"].strip()
                    
                    # Парсим ответ
                    is_violation = any(word in content.lower() for word in ["вердикт: да", "нарушение", "нарушает"])
                    
                    return {
                        "is_violation": is_violation,
                        "reasoning": content,
                        "confidence": 0.8 if is_violation else 0.7
                    }
                else:
                    return {"is_violation": False, "reasoning": "Не удалось получить ответ", "confidence": 0.0}
        except Exception as e:
            logger.error(f"❌ Ошибка анализа сообщения: {e}")
            return {"is_violation": False, "reasoning": f"Ошибка: {str(e)}", "confidence": 0.0}

# =========================
# Database Manager
# =========================
class Agent2DatabaseManager:
    def __init__(self, config: Agent2Config):
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
                pool_recycle=3600,
                pool_size=10,
                max_overflow=20
            )
            
            self.async_session_factory = async_sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False
            )
            
            logger.success(f"🗄️ PostgreSQL база данных инициализирована: {self.config.database_url}")
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации PostgreSQL: {e}")
            raise
    
    async def close_database(self):
        if self.engine:
            await self.engine.dispose()
            logger.info("🗄️ Соединение с PostgreSQL закрыто")
    
    def get_session(self) -> AsyncSession:
        if not self.async_session_factory:
            raise RuntimeError("PostgreSQL database not initialized")
        return self.async_session_factory()
    
    async def store_negative_message(self, chat_id: int, message_id: int, sender_id: int, 
                                   sender_username: str, message_text: str, reasoning: str) -> bool:
        """Сохранить негативное сообщение в БД"""
        try:
            async with self.get_session() as session:
                negative_msg = NegativeMessage(
                    chat_id=chat_id,
                    message_id=message_id,
                    sender_id=sender_id,
                    sender_username=sender_username,
                    message_text=message_text,
                    negative_reason=reasoning
                )
                
                session.add(negative_msg)
                await session.commit()
                logger.success(f"💾 Негативное сообщение сохранено в БД: {message_id}")
                return True
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения негативного сообщения: {e}")
            return False
    
    async def get_unprocessed_messages(self, limit: int = 100) -> List[Dict]:
        """Получить необработанные сообщения"""
        try:
            async with self.get_session() as session:
                result = await session.execute(
                    select(Message)
                    .where(Message.processed_at.is_(None))
                    .order_by(Message.created_at.desc())
                    .limit(limit)
                )
                
                messages = result.scalars().all()
                return [
                    {
                        "id": msg.id,
                        "chat_id": msg.chat_id,
                        "message_id": msg.message_id,
                        "user_id": msg.user_id,
                        "username": msg.username,
                        "message_text": msg.message_text,
                        "created_at": msg.created_at
                    }
                    for msg in messages
                ]
        except Exception as e:
            logger.error(f"❌ Ошибка получения сообщений: {e}")
            return []

# =========================
# Redis Communicator
# =========================
class RedisCommunicator:
    def __init__(self, redis_url: str):
        try:
            self.redis_client = redis.from_url(redis_url, decode_responses=True)
            self.redis_client.ping()
            logger.info(f"🔗 Redis подключен: {redis_url}")
        except Exception as e:
            logger.warning(f"⚠️ Не удалось подключиться к Redis: {e}")
            self.redis_client = None
    
    async def send_to_agent_3(self, data: Dict[str, Any]) -> bool:
        if not self.redis_client:
            return False
        
        try:
            message = json.dumps(data, ensure_ascii=False)
            await asyncio.to_thread(self.redis_client.lpush, "queue:agent3:input", message)
            logger.success(f"📤 Отправлено агенту 3: message_id={data.get('message_id')}")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка отправки агенту 3: {e}")
            return False
    
    async def send_to_agent_4(self, data: Dict[str, Any]) -> bool:
        if not self.redis_client:
            return False
        
        try:
            message = json.dumps(data, ensure_ascii=False)
            await asyncio.to_thread(self.redis_client.lpush, "queue:agent4:input", message)
            logger.success(f"📤 Отправлено агенту 4: message_id={data.get('message_id')}")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка отправки агенту 4: {e}")
            return False

# =========================
# Основной Агент №2
# =========================
class ChatAgent2:
    def __init__(self):
        self.config = Agent2Config()
        self.gigachat = GigaChatClient(
            os.getenv("GIGACHAT_CREDENTIALS", self.config.DEFAULT_GIGACHAT_CREDENTIALS)
        )
        self.db = Agent2DatabaseManager(self.config)
        self.redis = RedisCommunicator(self.config.REDIS_URL)
        self.processed_count = 0
        self.start_time = datetime.now()
        logger.info("🚀 Чат-агент №2 инициализирован")
    
    async def process_message(self, message_data: Dict[str, Any]) -> Dict[str, Any]:
        """Обработка одного сообщения"""
        try:
            chat_id = message_data.get("chat_id")
            message_id = message_data.get("message_id")
            user_id = message_data.get("user_id", message_data.get("sender_id"))
            username = message_data.get("username", message_data.get("sender_username", ""))
            message_text = message_data.get("message_text", "")
            
            if not message_text:
                return {"status": "error", "reason": "Пустое сообщение"}
            
            # Дефолтные правила чата
            rules = [
                "Запрещена реклама сторонних сообществ",
                "Запрещён флуд и спам",
                "Запрещены оскорбления участников",
                "Запрещена нецензурная лексика"
            ]
            
            # Анализ сообщения через GigaChat
            analysis = await self.gigachat.analyze_message(message_text, rules)
            
            # Подготовка данных для отправки агентам 3 и 4
            agent_data = {
                "message": message_text,
                "rules": rules,
                "user_id": user_id,
                "username": username,
                "chat_id": chat_id,
                "message_id": message_id,
                "timestamp": datetime.now().isoformat(),
                "agent_2_analysis": analysis
            }
            
            # Отправляем агентам 3 и 4 параллельно
            tasks = [
                self.redis.send_to_agent_3(agent_data),
                self.redis.send_to_agent_4(agent_data)
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Если сообщение определено как нарушение, сохраняем в БД
            if analysis["is_violation"]:
                await self.db.store_negative_message(
                    chat_id, message_id, user_id, username, 
                    message_text, analysis["reasoning"]
                )
            
            self.processed_count += 1
            
            return {
                "status": "processed",
                "message_id": message_id,
                "analysis": analysis,
                "sent_to_agent_3": isinstance(results[0], bool) and results[0],
                "sent_to_agent_4": isinstance(results[1], bool) and results[1]
            }
            
        except Exception as e:
            logger.error(f"❌ Ошибка обработки сообщения: {e}")
            return {"status": "error", "reason": str(e)}
    
    async def process_batch(self) -> Dict[str, Any]:
        """Обработка пакета необработанных сообщений"""
        messages = await self.db.get_unprocessed_messages(limit=50)
        
        if not messages:
            return {"status": "no_messages", "processed": 0}
        
        results = []
        for message in messages:
            result = await self.process_message(message)
            results.append(result)
        
        return {
            "status": "batch_processed",
            "total": len(messages),
            "results": results
        }
    
    def get_health_metrics(self) -> Dict[str, Any]:
        uptime = datetime.now() - self.start_time
        return {
            "agent_id": 2,
            "status": "healthy",
            "uptime_seconds": int(uptime.total_seconds()),
            "processed_messages": self.processed_count,
            "database_connected": self.db.engine is not None,
            "redis_connected": self.redis.redis_client is not None,
            "gigachat_token_valid": self.gigachat.access_token is not None,
        }

# =========================
# FastAPI приложение
# =========================
agent: Optional[ChatAgent2] = None

app = FastAPI(
    title="🤖 Чат-агент №2 с PostgreSQL",
    description="Агент №2: анализ сообщений, распределение между агентами 3 и 4",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

@app.on_event("startup")
async def startup_event():
    global agent
    agent = ChatAgent2()
    await agent.db.init_database()
    logger.success("✅ Агент №2 запущен и готов к работе")

@app.on_event("shutdown")
async def shutdown_event():
    if agent:
        await agent.db.close_database()
    logger.info("🛑 Агент №2 остановлен")

@app.post("/process_message")
async def process_message_endpoint(message_data: Dict[str, Any]):
    if not agent:
        raise HTTPException(status_code=500, detail="Агент не инициализирован")
    
    result = await agent.process_message(message_data)
    return result

@app.post("/process_batch")
async def process_batch_endpoint():
    if not agent:
        raise HTTPException(status_code=500, detail="Агент не инициализирован")
    
    result = await agent.process_batch()
    return result

@app.get("/health")
async def health_check():
    if not agent:
        return {"status": "error", "message": "Агент не инициализирован"}
    
    return agent.get_health_metrics()

@app.get("/")
async def root():
    return {
        "service": "Чат-агент №2 с PostgreSQL",
        "version": "2.0.0",
        "status": "running",
        "features": [
            "🗄️ PostgreSQL интеграция",
            "🤖 GigaChat анализ сообщений",
            "📨 Redis коммуникация с агентами 3 и 4",
            "📊 Обработка пакетов сообщений",
            "🔍 Детекция негативного контента"
        ]
    }

if __name__ == "__main__":
    logger.info("🚀 Запуск Чат-агента №2...")
    uvicorn.run(
        app,
        host=Agent2Config.API_HOST,
        port=Agent2Config.API_PORT,
        reload=False,
        access_log=True,
        log_level="info"
    )