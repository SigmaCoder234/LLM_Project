#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
АГЕНТ №1 — Координатор системы (Mistral AI версия с конфигурацией из .env)
"""

import json
import redis
import time
from typing import Dict, Any
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import threading
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey, BigInteger, Text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

# Импортируем централизованную конфигурацию
from config import (
    POSTGRES_URL, 
    get_redis_config,
    QUEUE_AGENT_1_INPUT,
    QUEUE_AGENT_2_INPUT,
    AGENT_PORTS,
    DEFAULT_RULES,
    setup_logging
)

# ============================================================================
# ЛОГИРОВАНИЕ
# ============================================================================
logger = setup_logging("АГЕНТ 1")

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
    custom_rules = Column(Text, nullable=True)  # Новое поле для кастомных правил
    
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
# ФУНКЦИИ ФИЛЬТРАЦИИ И НОРМАЛИЗАЦИИ
# ============================================================================
def is_group_chat(chat_type: str) -> bool:
    """Проверяет, является ли чат групповым"""
    return chat_type in ['group', 'supergroup', 'channel']

def should_process_message(message_data: Dict[str, Any]) -> tuple:
    """
    Определяет, нужно ли обрабатывать сообщение.
    Возвращает (should_process: bool, reason: str)
    """
    # Проверяем наличие обязательных полей
    if not message_data.get("message"):
        return False, "Пустое сообщение"
    
    if not message_data.get("chat_id"):
        return False, "Отсутствует ID чата"
    
    if not message_data.get("user_id"):
        return False, "Отсутствует ID пользователя"
    
    # Проверяем длину сообщения
    message = message_data.get("message", "")
    if len(message) < 2:
        return False, "Сообщение слишком короткое (менее 2 символов)"
    
    if len(message) > 4000:
        return False, "Сообщение слишком длинное (более 4000 символов)"
    
    # Проверяем, что это не команда бота
    if message.startswith('/'):
        return False, "Команда бота"
    
    # Фильтруем служебные сообщения
    service_patterns = [
        "пользователь присоединился",
        "пользователь покинул",
        "changed the group photo",
        "pinned a message"
    ]
    
    message_lower = message.lower()
    for pattern in service_patterns:
        if pattern in message_lower:
            return False, f"Служебное сообщение ({pattern})"
    
    return True, "Сообщение пригодно для обработки"

def normalize_message_data(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Нормализует входящие данные сообщения и добавляет метаинформацию.
    """
    # Базовая нормализация
    normalized = {
        "message": str(input_data.get("message", "")).strip(),
        "user_id": int(input_data.get("user_id", 0)),
        "username": str(input_data.get("username", "")).replace("@", ""),
        "chat_id": int(input_data.get("chat_id", 0)),
        "message_id": int(input_data.get("message_id", 0)),
        "message_link": str(input_data.get("message_link", "")),
        "timestamp": datetime.now().isoformat()
    }
    
    # Добавляем анализ сообщения
    message = normalized["message"]
    message_analysis = {
        "length": len(message),
        "word_count": len(message.split()),
        "has_links": "http" in message.lower() or "t.me" in message.lower(),
        "has_mentions": "@" in message,
        "has_hashtags": "#" in message,
        "has_caps": any(c.isupper() for c in message),
        "caps_ratio": sum(1 for c in message if c.isupper()) / max(len(message), 1),
        "has_numbers": any(c.isdigit() for c in message),
        "has_special_chars": any(not c.isalnum() and not c.isspace() for c in message)
    }
    
    # Предварительная категоризация по сложности
    complexity_score = 0
    
    if message_analysis["has_links"]:
        complexity_score += 3
    if message_analysis["has_mentions"]:
        complexity_score += 2
    if message_analysis["caps_ratio"] > 0.5:
        complexity_score += 2
    if message_analysis["word_count"] > 50:
        complexity_score += 1
    if message_analysis["has_special_chars"]:
        complexity_score += 1
    
    # Определяем предварительную стратегию
    if complexity_score >= 5:
        suggested_strategy = "COMPLEX"  # Нужен ИИ анализ
    elif complexity_score >= 2:
        suggested_strategy = "BOTH"     # Нужны оба агента
    else:
        suggested_strategy = "SIMPLE"   # Достаточно эвристики
    
    normalized.update({
        "agent_1_analysis": {
            "message_analysis": message_analysis,
            "complexity_score": complexity_score,
            "suggested_strategy": suggested_strategy,
            "processor": "Агент №1 (Координатор)",
            "version": "1.4 (Mistral AI .env)",
            "processed_at": datetime.now().isoformat()
        }
    })
    
    return normalized

# ============================================================================
# ОСНОВНАЯ ЛОГИКА АГЕНТА 1
# ============================================================================
def coordination_agent_1(input_data, db_session):
    """
    АГЕНТ 1 — Координатор системы.
    Получает сырые данные, фильтрует, нормализует и отправляет в Агент 2.
    """
    logger.info(f"Получено сообщение от пользователя: {input_data.get('username', 'unknown')}")
    
    # Проверяем, нужно ли обрабатывать сообщение
    should_process, reason = should_process_message(input_data)
    
    if not should_process:
        logger.info(f"Сообщение пропущено: {reason}")
        return {
            "agent_id": 1,
            "action": "skip",
            "reason": reason,
            "message": input_data.get("message", "")[:50] + "...",
            "user_id": input_data.get("user_id"),
            "username": input_data.get("username"),
            "chat_id": input_data.get("chat_id"),
            "message_id": input_data.get("message_id"),
            "status": "skipped"
        }
    
    # Нормализуем данные
    normalized_data = normalize_message_data(input_data)
    
    # Сохраняем базовую информацию в БД
    try:
        chat = db_session.query(Chat).filter_by(tg_chat_id=str(normalized_data["chat_id"])).first()
        if not chat:
            # Создаем новый чат, если его нет
            chat = Chat(
                tg_chat_id=str(normalized_data["chat_id"]),
                title=f"Чат {normalized_data['chat_id']}",
                chat_type="group",
                is_active=True
            )
            db_session.add(chat)
            db_session.commit()
            logger.info(f"Создан новый чат: {normalized_data['chat_id']}")
        
        # Проверяем, есть ли уже такое сообщение
        existing_message = db_session.query(Message).filter_by(
            chat_id=chat.id,
            message_id=normalized_data["message_id"]
        ).first()
        
        if not existing_message:
            # Создаем новое сообщение
            message_obj = Message(
                chat_id=chat.id,
                message_id=normalized_data["message_id"],
                sender_username=normalized_data["username"],
                sender_id=normalized_data["user_id"],
                message_text=normalized_data["message"],
                message_link=normalized_data["message_link"],
                ai_response="[АГЕНТ 1] Сообщение принято к обработке"
            )
            db_session.add(message_obj)
            db_session.commit()
            logger.info(f"Сообщение сохранено в БД: ID {normalized_data['message_id']}")
        
    except Exception as e:
        logger.error(f"Ошибка сохранения в БД: {e}")
    
    # Формируем результат для отправки в Агент 2
    output = {
        "agent_id": 1,
        "action": "forward",
        "message": normalized_data["message"],
        "user_id": normalized_data["user_id"],
        "username": normalized_data["username"],
        "chat_id": normalized_data["chat_id"],
        "message_id": normalized_data["message_id"],
        "message_link": normalized_data["message_link"],
        "agent_1_analysis": normalized_data["agent_1_analysis"],
        "status": "processed",
        "next_agent": 2,
        "timestamp": normalized_data["timestamp"]
    }
    
    analysis = normalized_data["agent_1_analysis"]
    logger.info(f"📊 Анализ: длина={analysis['message_analysis']['length']}, "
               f"сложность={analysis['complexity_score']}, стратегия={analysis['suggested_strategy']}")
    
    return output

# ============================================================================
# РАБОТА С REDIS
# ============================================================================
class Agent1Worker:
    def __init__(self):
        try:
            redis_config = get_redis_config()
            self.redis_client = redis.Redis(**redis_config)
            self.redis_client.ping()
            logger.info(f"✅ Подключение к Redis успешно")
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
        """Отправляет обработанное сообщение в очередь Агента 2"""
        if result.get("action") != "forward":
            logger.info(f"Сообщение не отправлено в Агент 2: {result.get('reason', 'неизвестная причина')}")
            return
        
        try:
            result_json = json.dumps(result, ensure_ascii=False)
            self.redis_client.rpush(QUEUE_AGENT_2_INPUT, result_json)
            logger.info(f"✅ Сообщение отправлено Агенту 2 (Mistral AI)")
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение Агенту 2: {e}")
    
    def run(self):
        """Главный цикл обработки сообщений"""
        logger.info(f"✅ Агент 1 запущен (Координатор v1.4 с Mistral AI)")
        logger.info(f"   Слушаю очередь: {QUEUE_AGENT_1_INPUT}")
        logger.info(f"   Отправляю в Агента 2: {QUEUE_AGENT_2_INPUT}")
        logger.info(f"   Стандартные правила v2.0: {DEFAULT_RULES}")
        logger.info(f"   ИИ провайдер: Mistral AI (через Агент 2)")
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
                    
                    # Отправляем в Агент 2
                    self.send_to_agent_2(output)
                    
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
    title="🤖 Агент №1 - Координатор (Mistral AI)",
    description="Фильтрация, нормализация и координация сообщений",
    version="1.4"
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
        "version": "1.4 (Mistral AI)",
        "ai_provider": "Не использует ИИ (только логика)",
        "next_agents_ai": "Mistral AI (Агенты 2-5)",
        "default_rules_v2": DEFAULT_RULES,
        "configuration": "Environment variables (.env)",
        "features": [
            "Фильтрация групповых чатов",
            "Нормализация данных",
            "Анализ сложности сообщений",
            "Поддержка кастомных правил v2.0",
            "Подготовка для Mistral AI"
        ],
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
    """Статистика работы агента"""
    db_session = get_db_session()
    try:
        total_messages = db_session.query(Message).count()
        total_chats = db_session.query(Chat).count()
        chats_with_custom_rules = db_session.query(Chat).filter(Chat.custom_rules.isnot(None)).count()
        
        return {
            "total_messages": total_messages,
            "total_chats": total_chats,
            "chats_with_custom_rules": chats_with_custom_rules,
            "agent_id": 1,
            "version": "1.4 (Mistral AI)",
            "default_rules_v2": DEFAULT_RULES,
            "configuration": "Environment variables",
            "ai_provider": "Логика + передача в Mistral AI агенты",
            "timestamp": datetime.now().isoformat()
        }
    finally:
        db_session.close()

@app.get("/test_filter")
async def test_filter(message: str = "Тестовое сообщение"):
    """Тестирование фильтра сообщений"""
    test_data = {
        "message": message,
        "user_id": 123,
        "username": "test_user",
        "chat_id": -100,
        "message_id": 1,
        "message_link": "https://t.me/test/1"
    }
    
    should_process, reason = should_process_message(test_data)
    
    return {
        "should_process": should_process,
        "reason": reason,
        "test_message": message,
        "agent_version": "1.4 (Mistral AI)",
        "will_be_processed_by": "Mistral AI агенты (2-5)" if should_process else "Никем (отфильтровано)"
    }

# ============================================================================
# ЗАПУСК FASTAPI В ОТДЕЛЬНОМ ПОТОКЕ
# ============================================================================
def run_fastapi():
    """Запуск FastAPI сервера"""
    uvicorn.run(app, host="localhost", port=AGENT_PORTS[1], log_level="info")

# ============================================================================
# ТОЧКА ВХОДА
# ============================================================================
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        mode = sys.argv[1]
        if mode == "test":
            # Тестирование
            test_input = {
                "message": "Привет всем! Как дела?",
                "user_id": 123,
                "username": "test_user",
                "chat_id": -100,
                "message_id": 1,
                "message_link": "https://t.me/test/1"
            }
            
            db_session = get_db_session()
            result = coordination_agent_1(test_input, db_session)
            db_session.close()
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif mode == "api":
            # Запуск только FastAPI
            run_fastapi()
    else:
        # Запуск FastAPI в отдельном потоке
        fastapi_thread = threading.Thread(target=run_fastapi, daemon=True)
        fastapi_thread.start()
        logger.info(f"✅ FastAPI сервер запущен на порту {AGENT_PORTS[1]}")
        
        # Запуск основного Redis worker
        try:
            worker = Agent1Worker()
            worker.run()
        except KeyboardInterrupt:
            logger.info("Выход из программы")
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")