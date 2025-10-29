#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
АГЕНТ №1 — Координатор и нормализатор (Исправлено - только групповые чаты)
"""

import requests
import json
import redis
import time
import logging
from typing import Dict, Any
import urllib3
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey, BigInteger, Text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import threading

# Отключаем warning SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============================================================================
# ЛОГИРОВАНИЕ
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [АГЕНТ 1] %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# КОНФИГУРАЦИЯ БД (ОДИНАКОВАЯ С АГЕНТОМ 3.2)
# ============================================================================
POSTGRES_URL = 'postgresql://tguser:mnvm7110@176.108.248.211:5432/teleguard_db?sslmode=disable'

# ============================================================================
# КОНФИГУРАЦИЯ REDIS
# ============================================================================
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0
REDIS_PASSWORD = None

# Очереди для взаимодействия с другими агентами
QUEUE_AGENT_1_INPUT = "queue:agent1:input"
QUEUE_AGENT_2_INPUT = "queue:agent2:input"
QUEUE_TELEGRAM_INPUT = "queue:telegram:input"

# ============================================================================
# МОДЕЛИ БД (ЕДИНЫЕ ДЛЯ ВСЕХ АГЕНТОВ)
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
# ФУНКЦИИ ПРОВЕРКИ ТИПА ЧАТА
# ============================================================================
def is_group_chat(chat_type: str) -> bool:
    """Проверяет, является ли чат групповым"""
    return chat_type in ['group', 'supergroup', 'channel']

def is_group_chat_id(chat_id: int) -> bool:
    """Проверяет, является ли chat_id групповым (отрицательные ID)"""
    return chat_id < 0

# ============================================================================
# ОСНОВНАЯ ЛОГИКА АГЕНТА 1 (ТОЛЬКО ГРУППОВЫЕ ЧАТЫ)
# ============================================================================
def coordination_agent_1(input_data, db_session):
    """
    АГЕНТ 1 — Координатор и нормализатор.
    Принимает сообщения ТОЛЬКО из групповых чатов и готовит их для дальнейшей обработки.
    """
    message = input_data.get("message", "")
    user_id = input_data.get("user_id")
    username = input_data.get("username", "")
    chat_id = input_data.get("chat_id")
    message_id = input_data.get("message_id")
    message_link = input_data.get("message_link", "")
    
    logger.info(f"Координирую сообщение от @{username} в чате {chat_id}")
    
    # ПРОВЕРЯЕМ: обрабатываем только групповые чаты
    if not is_group_chat_id(chat_id):
        logger.info(f"🚫 Сообщение из личного чата {chat_id} пропущено")
        return {
            "agent_id": 1,
            "action": "skip",
            "reason": f"Личные чаты не обрабатываются. Chat ID: {chat_id}",
            "message": message,
            "user_id": user_id,
            "username": username,
            "chat_id": chat_id,
            "message_id": message_id,
            "status": "skipped_private_chat"
        }
    
    if not message:
        return {
            "agent_id": 1,
            "action": "skip",
            "reason": "Пустое сообщение",
            "message": "",
            "user_id": user_id,
            "username": username,
            "chat_id": chat_id,
            "message_id": message_id,
            "status": "skipped"
        }
    
    # Дефолтные правила чата
    rules = [
        "Запрещена реклама сторонних сообществ и каналов",
        "Запрещены нецензурные выражения и оскорбления участников",
        "Запрещена дискриминация по любым признакам (национальность, раса, религия)",
        "Запрещен спам, флуд и бессмысленные сообщения",
        "Запрещены угрозы и призывы к насилию"
    ]
    
    # Сохраняем сообщение в БД (только групповые чаты)
    try:
        chat = db_session.query(Chat).filter_by(tg_chat_id=str(chat_id)).first()
        if not chat:
            # Определяем тип чата по ID
            chat_type = "supergroup" if chat_id < -1000000000000 else "group"
            
            chat = Chat(
                tg_chat_id=str(chat_id),
                chat_type=chat_type
            )
            db_session.add(chat)
            db_session.commit()
        
        # Проверяем еще раз что это групповой чат по типу из БД
        if not is_group_chat(chat.chat_type):
            logger.info(f"🚫 Чат {chat_id} не является групповым (тип: {chat.chat_type})")
            return {
                "agent_id": 1,
                "action": "skip",
                "reason": f"Чат не является групповым. Тип: {chat.chat_type}",
                "message": message,
                "user_id": user_id,
                "username": username,
                "chat_id": chat_id,
                "message_id": message_id,
                "status": "skipped_non_group"
            }
        
        # Проверяем, есть ли уже такое сообщение
        existing_message = db_session.query(Message).filter_by(
            chat_id=chat.id, 
            message_id=message_id
        ).first()
        
        if not existing_message:
            msg = Message(
                chat_id=chat.id,
                message_id=message_id,
                sender_username=username,
                sender_id=user_id,
                message_text=message,
                message_link=message_link,
                processed_at=datetime.utcnow()
            )
            db_session.add(msg)
            db_session.commit()
            logger.info("💾 Сообщение из группового чата сохранено в БД")
        
    except Exception as e:
        logger.error(f"Ошибка сохранения в БД: {e}")
    
    # Подготавливаем данные для Агента 2
    agent_data = {
        "message": message,
        "rules": rules,
        "user_id": user_id,
        "username": username,
        "chat_id": chat_id,
        "message_id": message_id,
        "message_link": message_link,
        "timestamp": datetime.now().isoformat()
    }
    
    output = {
        "agent_id": 1,
        "action": "forward",
        "reason": "Сообщение из группового чата направлено агенту 2 для анализа",
        "message": message,
        "user_id": user_id,
        "username": username,
        "chat_id": chat_id,
        "message_id": message_id,
        "message_link": message_link,
        "rules": rules,
        "agent_data": agent_data,
        "status": "success",
        "timestamp": datetime.now().isoformat()
    }
    
    logger.info(f"📋 Сообщение из группового чата {chat_id} направлено для дальнейшей обработки")
    return output

# ============================================================================
# REDIS WORKER
# ============================================================================
class Agent1Worker:
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
    
    def process_message(self, message_data, db_session):
        """Обрабатывает сообщение от входной очереди"""
        try:
            input_data = json.loads(message_data)
            result = coordination_agent_1(input_data, db_session)
            return result
        except json.JSONDecodeError as e:
            logger.error(f"Невалидный JSON: {e}")
            return {
                "agent_id": 1,
                "action": "error",
                "reason": f"Ошибка парсинга данных: {e}",
                "message": "",
                "status": "json_error"
            }
        except Exception as e:
            logger.error(f"Ошибка обработки сообщения: {e}")
            return {
                "agent_id": 1,
                "action": "error",
                "reason": f"Внутренняя ошибка агента 1: {e}",
                "message": "",
                "status": "error"
            }
    
    def send_to_agent_2(self, result):
        """Отправляет сообщение агенту 2 (только если это групповой чат)"""
        if result.get("action") == "forward":
            try:
                agent_data = result.get("agent_data", {})
                result_json = json.dumps(agent_data, ensure_ascii=False)
                self.redis_client.rpush(QUEUE_AGENT_2_INPUT, result_json)
                logger.info(f"✅ Отправлено агенту 2")
                return True
            except Exception as e:
                logger.error(f"Не удалось отправить агенту 2: {e}")
                return False
        elif result.get("action") == "skip":
            logger.info(f"⏭️ Сообщение пропущено: {result.get('reason', 'Неизвестная причина')}")
        return False
    
    def run(self):
        """Главный цикл обработки сообщений"""
        logger.info(f"✅ Агент 1 запущен (только групповые чаты)")
        logger.info(f"   Слушаю очередь: {QUEUE_AGENT_1_INPUT}")
        logger.info(f"   Отправляю в Агента 2: {QUEUE_AGENT_2_INPUT}")
        logger.info("   Нажмите Ctrl+C для остановки\n")
        
        db_session = None
        try:
            while True:
                try:
                    result = self.redis_client.blpop(QUEUE_AGENT_1_INPUT, timeout=1)
                    if result is None:
                        continue
                    
                    queue_name, message_data = result
                    logger.info(f"📨 Получено сообщение")
                    
                    # Создаем новую сессию БД для каждого сообщения
                    db_session = get_db_session()
                    output = self.process_message(message_data, db_session)
                    
                    # Отправляем агенту 2 (только групповые чаты)
                    sent_to_agent2 = self.send_to_agent_2(output)
                    
                    db_session.close()
                    
                    logger.info(f"✅ Обработка завершена\n")
                    
                except Exception as e:
                    logger.error(f"Ошибка в цикле: {e}")
                    if db_session:
                        db_session.close()
                    time.sleep(1)
                    
        except KeyboardInterrupt:
            logger.info("\n❌ Агент 1 остановлен (Ctrl+C)")
        finally:
            if db_session:
                db_session.close()
            logger.info("Агент 1 завершил работу")

# ============================================================================
# FASTAPI ПРИЛОЖЕНИЕ
# ============================================================================
app = FastAPI(
    title="🤖 Агент №1 - Координатор",
    description="Координация и нормализация сообщений (только групповые чаты)",
    version="1.1"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "online",
        "agent_id": 1,
        "name": "Агент №1 (Координатор)",
        "version": "1.1",
        "description": "Обрабатывает только групповые чаты",
        "timestamp": datetime.now().isoformat(),
        "redis_queue": QUEUE_AGENT_1_INPUT,
        "uptime_seconds": int(time.time())
    }

@app.post("/process_message")
async def process_message_endpoint(message_data: dict):
    """Обработка сообщения через API"""
    db_session = get_db_session()
    try:
        result = coordination_agent_1(message_data, db_session)
        return result
    finally:
        db_session.close()

@app.get("/stats")
async def get_stats():
    """Статистика работы агента (только групповые чаты)"""
    db_session = get_db_session()
    try:
        # Считаем только сообщения из групповых чатов
        group_chats = db_session.query(Chat).filter(
            Chat.chat_type.in_(['group', 'supergroup', 'channel'])
        ).all()
        
        total_messages = 0
        processed_today = 0
        
        for chat in group_chats:
            chat_messages = db_session.query(Message).filter_by(chat_id=chat.id).count()
            total_messages += chat_messages
            
            today_messages = db_session.query(Message).filter(
                Message.chat_id == chat.id,
                Message.processed_at >= datetime.now().date()
            ).count()
            processed_today += today_messages
        
        return {
            "total_messages": total_messages,
            "processed_today": processed_today,
            "group_chats_count": len(group_chats),
            "agent_id": 1,
            "timestamp": datetime.now().isoformat()
        }
    finally:
        db_session.close()

# ============================================================================
# ЗАПУСК FASTAPI В ОТДЕЛЬНОМ ПОТОКЕ
# ============================================================================
def run_fastapi():
    """Запуск FastAPI сервера"""
    uvicorn.run(app, host="localhost", port=8001, log_level="info")

# ============================================================================
# ТОЧКА ВХОДА
# ============================================================================
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        mode = sys.argv[1]
        if mode == "test":
            # Тестирование с групповым чатом
            test_input = {
                "message": "Привет всем! Как дела?",
                "user_id": 123,
                "username": "test_user",
                "chat_id": -1001234567890,  # Групповой чат (отрицательный ID)
                "message_id": 1,
                "message_link": "https://t.me/test/1"
            }
            
            db_session = get_db_session()
            result = coordination_agent_1(test_input, db_session)
            db_session.close()
            print(json.dumps(result, ensure_ascii=False, indent=2))
            
            # Тест с личным чатом (должен быть пропущен)
            test_private = {
                "message": "Привет из личного чата!",
                "user_id": 123,
                "username": "test_user",
                "chat_id": 1234567890,  # Личный чат (положительный ID)
                "message_id": 2,
                "message_link": "https://t.me/test/2"
            }
            
            db_session = get_db_session()
            result_private = coordination_agent_1(test_private, db_session)
            db_session.close()
            print("\n--- Тест личного чата ---")
            print(json.dumps(result_private, ensure_ascii=False, indent=2))
            
        elif mode == "api":
            # Запуск только FastAPI
            run_fastapi()
    else:
        # Запуск FastAPI в отдельном потоке
        fastapi_thread = threading.Thread(target=run_fastapi, daemon=True)
        fastapi_thread.start()
        logger.info("✅ FastAPI сервер запущен на порту 8001")
        
        # Запуск основного Redis worker
        try:
            worker = Agent1Worker()
            worker.run()
        except KeyboardInterrupt:
            logger.info("Выход из программы")
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")