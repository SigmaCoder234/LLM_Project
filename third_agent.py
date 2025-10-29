#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
ЧАТ-АГЕНТ №3 с PostgreSQL - Модератор (GigaChat)
=============================================================================
- Использует модели БД из first_agent.py  
- Интеграция с PostgreSQL через SQLAlchemy ORM
- GigaChat для анализа нарушений
- Redis для получения задач от агента 2
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
import redis
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
    "logs/agent_3_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="30 days", 
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} | {message}"
)
logger.add(lambda msg: print(msg, end=""), level="INFO", format="{time:HH:mm:ss} | {level} | {message}")

# =========================
# Конфигурация
# =========================
class Agent3Config:
    # PostgreSQL настройки - те же что в teteguard_bot.py
    POSTGRES_HOST = "176.108.248.211"
    POSTGRES_PORT = 5432
    POSTGRES_DB = "teleguard_db" 
    POSTGRES_USER = "tguser"
    POSTGRES_PASSWORD = "mnvm7110"
    
    # Redis настройки
    REDIS_HOST = "localhost"
    REDIS_PORT = 6379
    REDIS_DB = 0
    REDIS_PASSWORD = None
    
    # Очереди Redis
    QUEUE_INPUT = "queue:agent3:input"
    QUEUE_OUTPUT = "queue:agent3:output"
    
    # GigaChat
    GIGACHAT_AUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    GIGACHAT_API_URL = "https://gigachat.devices.sberbank.ru/api/v1"
    DEFAULT_GIGACHAT_CREDENTIALS = "MDE5YTJhZjEtYjhjOS03OTViLWFlZjEtZTg4MTgxNjQzNzdjOmE0MzRhNjExLTE2NGYtNDdjYS1iNTM2LThlMGViMmU0YzVmNg=="
    
    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
    
    @property  
    def sync_database_url(self) -> str:
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

# =========================
# GigaChat Client
# =========================
class GigaChatClient:
    def __init__(self, credentials: str):
        self.credentials = credentials
        self.access_token: Optional[str] = None
        self.token_expires_at: Optional[datetime] = None
        logger.info("🔧 GigaChat клиент агента 3 инициализирован")
    
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
                response = await client.post(Agent3Config.GIGACHAT_AUTH_URL, headers=headers, data=payload)
                response.raise_for_status()
                token_data = response.json()
                
                self.access_token = token_data['access_token']
                expires_in = token_data.get('expires_in', 1800)
                from datetime import timedelta
                self.token_expires_at = datetime.now() + timedelta(seconds=expires_in - 60)
                
                logger.success(f"🔑 Агент 3 получил новый токен GigaChat")
                return self.access_token
        except Exception as e:
            logger.error(f"❌ Агент 3: Ошибка получения токена GigaChat: {e}")
            raise
    
    async def moderate_message(self, message_text: str, rules: List[str]) -> Dict[str, Any]:
        """Модерация сообщения через GigaChat"""
        token = await self.get_access_token()
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        
        rules_text = "\n".join([f"{i+1}. {rule}" for i, rule in enumerate(rules)])
        system_prompt = f"""Ты — строгий, но справедливый модератор Telegram-канала.
        Твоя задача: проанализировать сообщение пользователя и определить, нарушает ли оно правила чата.
        
        ИНСТРУКЦИЯ:
        1. Внимательно изучи сообщение
        2. Сравни его с каждым правилом
        3. Если найдено нарушение — укажи конкретное правило и объясни почему
        4. Если сомневаешься — лучше не банить (презумпция невиновности)
        5. Будь объективным
        
        Правила чата:
        {rules_text}
        
        Ответь СТРОГО в формате: 'Вердикт: да/нет. Причина: [подробное объяснение]'"""
        
        payload = {
            "model": "GigaChat",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Анализируй сообщение: {message_text}"}
            ],
            "temperature": 0.2,  # Низкая температура для стабильности
            "max_tokens": 256,
            "stream": False,
        }
        
        try:
            async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
                response = await client.post(f"{Agent3Config.GIGACHAT_API_URL}/chat/completions", 
                                           headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()
                
                if result.get("choices") and len(result["choices"]) > 0:
                    content = result["choices"][0]["message"]["content"].strip()
                    
                    # Парсим ответ GigaChat
                    content_lower = content.lower()
                    
                    # Ключевые слова для определения вердикта
                    ban_keywords = ["вердикт: да", "нарушение обнаружено", "нарушает правила", "забанить", "блокировать"]
                    no_ban_keywords = ["вердикт: нет", "нет нарушений", "не нарушает", "правила соблюдены", "нарушений не найдено"]
                    
                    ban = False
                    # Сначала проверяем на отсутствие нарушений (приоритет)
                    if any(word in content_lower for word in no_ban_keywords):
                        ban = False
                    # Затем проверяем на наличие нарушений
                    elif any(word in content_lower for word in ban_keywords):
                        ban = True
                    
                    return {
                        "ban": ban,
                        "reason": content,
                        "confidence": 0.85 if ban else 0.8
                    }
                else:
                    return {"ban": False, "reason": "Не удалось получить ответ от GigaChat", "confidence": 0.0}
        except Exception as e:
            logger.error(f"❌ Агент 3: Ошибка модерации сообщения: {e}")
            return {"ban": False, "reason": f"Ошибка GigaChat: {str(e)}", "confidence": 0.0}

# =========================
# Database Manager
# =========================
class Agent3DatabaseManager:
    def __init__(self, config: Agent3Config):
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
            
            logger.success(f"🗄️ Агент 3: PostgreSQL БД инициализирована")
        except Exception as e:
            logger.error(f"❌ Агент 3: Ошибка инициализации PostgreSQL: {e}")
            raise
    
    async def close_database(self):
        if self.engine:
            await self.engine.dispose()
            logger.info("🗄️ Агент 3: Соединение с PostgreSQL закрыто")
    
    def get_session(self) -> AsyncSession:
        if not self.async_session_factory:
            raise RuntimeError("PostgreSQL database not initialized")
        return self.async_session_factory()

# =========================
# Redis Worker
# =========================  
class Agent3RedisWorker:
    def __init__(self, config: Agent3Config):
        self.config = config
        self.gigachat = GigaChatClient(
            os.getenv("GIGACHAT_CREDENTIALS", config.DEFAULT_GIGACHAT_CREDENTIALS)
        )
        self.db = Agent3DatabaseManager(config)
        self.processed_count = 0
        
        # Подключение к Redis
        try:
            self.redis_client = redis.Redis(
                host=config.REDIS_HOST,
                port=config.REDIS_PORT,
                db=config.REDIS_DB,
                password=config.REDIS_PASSWORD,
                decode_responses=True
            )
            self.redis_client.ping()
            logger.success(f"🔗 Агент 3: Redis подключен {config.REDIS_HOST}:{config.REDIS_PORT}")
        except Exception as e:
            logger.error(f"❌ Агент 3: Не удалось подключиться к Redis: {e}")
            raise
    
    async def process_message(self, message_data: str) -> Dict[str, Any]:
        """Обработка одного сообщения из очереди"""
        try:
            # Парсим JSON
            input_data = json.loads(message_data)
            
            # Извлекаем данные
            message = input_data.get("message", "")
            rules = input_data.get("rules", [])
            user_id = input_data.get("user_id")
            username = input_data.get("username")
            chat_id = input_data.get("chat_id")
            message_id = input_data.get("message_id")
            
            # Валидация
            if not message:
                return {
                    "agent_id": 3,
                    "ban": False,
                    "reason": "Ошибка: пустое сообщение",
                    "message": "",
                    "user_id": user_id,
                    "username": username,
                    "chat_id": chat_id,
                    "message_id": message_id
                }
            
            if not rules:
                return {
                    "agent_id": 3,
                    "ban": False,
                    "reason": "Ошибка: правила не переданы",
                    "message": message,
                    "user_id": user_id,
                    "username": username,
                    "chat_id": chat_id,
                    "message_id": message_id
                }
            
            logger.info(f"[АГЕНТ 3] Анализирую сообщение: {message[:50]}...")
            
            # Модерация через GigaChat
            moderation_result = await self.gigachat.moderate_message(message, rules)
            
            # Формируем результат
            result = {
                "agent_id": 3,
                "ban": moderation_result["ban"],
                "reason": moderation_result["reason"],
                "message": message,
                "user_id": user_id,
                "username": username,
                "chat_id": chat_id,
                "message_id": message_id,
                "confidence": moderation_result["confidence"],
                "timestamp": datetime.now().isoformat()
            }
            
            self.processed_count += 1
            logger.success(f"[АГЕНТ 3] Вердикт: {'БАН' if moderation_result['ban'] else 'НЕ БАНИТЬ'}")
            
            return result
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Агент 3: Невалидный JSON: {e}")
            return {
                "agent_id": 3,
                "ban": False,
                "reason": f"Ошибка парсинга данных: {e}",
                "message": ""
            }
        except Exception as e:
            logger.error(f"❌ Агент 3: Ошибка обработки сообщения: {e}")
            return {
                "agent_id": 3,
                "ban": False,
                "reason": f"Внутренняя ошибка агента 3: {e}",
                "message": ""
            }
    
    def send_result(self, result: Dict[str, Any]) -> None:
        """Отправка результата в выходную очередь"""
        try:
            result_json = json.dumps(result, ensure_ascii=False)
            self.redis_client.rpush(self.config.QUEUE_OUTPUT, result_json)
            logger.success(f"📤 Агент 3: Результат отправлен в {self.config.QUEUE_OUTPUT}")
        except Exception as e:
            logger.error(f"❌ Агент 3: Не удалось отправить результат: {e}")
    
    async def run(self):
        """Основной цикл обработки сообщений"""
        await self.db.init_database()
        
        logger.info(f"🚀 Агент 3 запущен")
        logger.info(f"📥 Слушаю очередь: {self.config.QUEUE_INPUT}")  
        logger.info(f"📤 Отправляю в очередь: {self.config.QUEUE_OUTPUT}")
        logger.info("🛑 Нажмите Ctrl+C для остановки\n")
        
        try:
            while True:
                try:
                    # Блокирующее чтение из очереди (timeout=1 секунда)
                    result = self.redis_client.blpop(self.config.QUEUE_INPUT, timeout=1)
                    
                    if result is None:
                        # Таймаут, продолжаем ждать
                        continue
                    
                    queue_name, message_data = result
                    logger.info(f"\n📨 Агент 3: Получено новое сообщение из {queue_name}")
                    
                    # Обрабатываем сообщение
                    output = await self.process_message(message_data)
                    
                    # Отправляем результат
                    self.send_result(output)
                    
                    logger.info(f"✅ Агент 3: Обработка завершена (всего: {self.processed_count})\n")
                    
                except KeyboardInterrupt:
                    logger.info("\n🛑 Агент 3: Получен сигнал остановки")
                    break
                except Exception as e:
                    logger.error(f"❌ Агент 3: Неожиданная ошибка: {e}")
                    await asyncio.sleep(1)
                    
        finally:
            await self.db.close_database()
            logger.info("👋 Агент 3 остановлен")

# =========================
# Тестирование
# =========================
async def test_agent_3():
    """Локальный тест агента 3"""
    logger.info("=== ТЕСТ АГЕНТА 3 ===")
    
    config = Agent3Config()
    worker = Agent3RedisWorker(config)
    
    # Тестовые данные
    test_data = {
        "message": "Вступайте в наш чат! 🎉 Только у нас крутые предложения!",
        "rules": [
            "Запрещена реклама сторонних сообществ",
            "Запрещён флуд и спам",
            "Запрещены оскорбления участников"
        ],
        "user_id": 123456789,
        "username": "@test_user",
        "chat_id": -1001234567890,
        "message_id": 42
    }
    
    test_json = json.dumps(test_data, ensure_ascii=False)
    result = await worker.process_message(test_json)
    
    logger.info("Результат:")
    print(json.dumps(result, ensure_ascii=False, indent=2))

# =========================
# Точка входа
# =========================
async def main():
    config = Agent3Config()
    worker = Agent3RedisWorker(config)
    await worker.run()

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        asyncio.run(test_agent_3())
    else:
        asyncio.run(main())