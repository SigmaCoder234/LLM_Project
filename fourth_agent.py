#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
ЧАТ-АГЕНТ №4 с PostgreSQL - Модератор (Эвристический анализ)
=============================================================================
- Использует модели БД из first_agent.py
- Интеграция с PostgreSQL через SQLAlchemy ORM  
- Эвристический анализ паттернов нарушений
- Redis для получения задач от агента 2
=============================================================================
"""

import asyncio
import json
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

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
    "logs/agent_4_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="30 days",
    level="INFO", 
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} | {message}"
)
logger.add(lambda msg: print(msg, end=""), level="INFO", format="{time:HH:mm:ss} | {level} | {message}")

# =========================
# Конфигурация
# =========================
class Agent4Config:
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
    QUEUE_INPUT = "queue:agent4:input"
    QUEUE_OUTPUT = "queue:agent4:output"
    
    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
    
    @property
    def sync_database_url(self) -> str:
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

# =========================
# Эвристический анализатор
# =========================
class HeuristicAnalyzer:
    """
    Эвристический анализатор сообщений.
    Агент 4 использует набор правил, паттернов и эвристик для принятия решений.
    Это отличается от Агента 3, который использует нейросети.
    """
    
    def __init__(self):
        # Паттерны для обнаружения нарушений
        self.spam_patterns = [
            r'вступай(те)?\\s+в\\s+(наш|наш|мой)',
            r'подпис(ыв)?ай(ся|тесь)?\\s+(на|в)',
            r'переход(и(те)?)?\\s+по\\s+ссылке', 
            r'жми\\s+(сюда|тут|на\\s+ссылку)',
            r'@\\w+',  # Упоминание других каналов
            r'https?://\\S+',  # Ссылки
            r't\\.me/\\S+',  # Telegram ссылки
        ]
        
        self.insult_patterns = [
            r'\\b(идиот|дурак|тупой|глупый|мудак)\\b',
            r'\\b(придурок|дебил|имбецил|кретин)\\b',
        ]
        
        self.profanity_patterns = [
            r'\\b(блять|бля|хуй|пизд|ебать|сука)\\b',
        ]
        
        self.flood_indicators = [
            r'([А-Яа-я])\\1{4,}',  # Повторяющиеся символы
            r'[!?]{3,}',  # Много знаков препинания
            r'[A-ZА-Я]{10,}',  # КАПС
        ]
    
    def check_spam(self, message: str) -> Tuple[bool, str]:
        """Проверка на спам и рекламу"""
        message_lower = message.lower()
        for pattern in self.spam_patterns:
            if re.search(pattern, message_lower):
                return True, f"Обнаружена реклама/спам (паттерн: {pattern})"
        
        # Проверка на количество ссылок
        links_count = len(re.findall(r'https?://|t\\.me/', message_lower))
        if links_count >= 2:
            return True, f"Множественные ссылки ({links_count} шт.) - признак спама"
        
        # Проверка на упоминание нескольких каналов
        mentions = re.findall(r'@\\w+', message)
        if len(mentions) >= 2:
            return True, f"Упоминание нескольких каналов ({len(mentions)} шт.)"
        
        return False, ""
    
    def check_insults(self, message: str) -> Tuple[bool, str]:
        """Проверка на оскорбления"""
        message_lower = message.lower()
        for pattern in self.insult_patterns:
            match = re.search(pattern, message_lower)
            if match:
                return True, f"Обнаружено оскорбление: '{match.group()}'"
        return False, ""
    
    def check_profanity(self, message: str) -> Tuple[bool, str]:
        """Проверка на нецензурную лексику"""
        message_lower = message.lower()
        for pattern in self.profanity_patterns:
            match = re.search(pattern, message_lower)
            if match:
                return True, f"Обнаружена нецензурная лексика: '{match.group()}'"
        return False, ""
    
    def check_flood(self, message: str) -> Tuple[bool, str]:
        """Проверка на флуд"""
        for pattern in self.flood_indicators:
            match = re.search(pattern, message)
            if match:
                return True, f"Обнаружен флуд: '{match.group()}'"
        
        # Проверка на очень короткие повторяющиеся сообщения
        if len(message) < 3:
            return True, "Слишком короткое сообщение (возможный флуд)"
        
        return False, ""
    
    def check_rules_match(self, message: str, rules: List[str]) -> Tuple[bool, str]:
        """
        Проверяет сообщение на соответствие правилам чата.
        Возвращает (нарушение_найдено, причина)
        """
        violations = []
        
        # Проверяем каждое правило
        for rule in rules:
            rule_lower = rule.lower()
            
            # Проверка на спам/рекламу
            if any(keyword in rule_lower for keyword in ['спам', 'реклам', 'промо']):
                is_spam, reason = self.check_spam(message)
                if is_spam:
                    violations.append(f"Нарушение правила '{rule}': {reason}")
            
            # Проверка на оскорбления
            if any(keyword in rule_lower for keyword in ['оскорбл', 'унижен', 'хамств']):
                is_insult, reason = self.check_insults(message)
                if is_insult:
                    violations.append(f"Нарушение правила '{rule}': {reason}")
            
            # Проверка на мат
            if any(keyword in rule_lower for keyword in ['мат', 'нецензур', 'ругат']):
                is_profane, reason = self.check_profanity(message)
                if is_profane:
                    violations.append(f"Нарушение правила '{rule}': {reason}")
            
            # Проверка на флуд
            if any(keyword in rule_lower for keyword in ['флуд', 'спам']):
                is_flood, reason = self.check_flood(message)
                if is_flood:
                    violations.append(f"Нарушение правила '{rule}': {reason}")
        
        if violations:
            return True, " | ".join(violations)
        return False, "Нарушений не обнаружено. Сообщение соответствует правилам чата."
    
    def analyze(self, message: str, rules: List[str]) -> Dict[str, Any]:
        """
        Основной метод анализа сообщения.
        Returns:
            dict: {"ban": bool, "reason": str}
        """
        # Базовая валидация
        if not message or not message.strip():
            return {
                "ban": False,
                "reason": "Пустое сообщение - нет оснований для бана"
            }
        
        # Проверяем по правилам
        has_violation, reason = self.check_rules_match(message, rules)
        return {
            "ban": has_violation,
            "reason": reason
        }

# =========================
# Database Manager
# =========================
class Agent4DatabaseManager:
    def __init__(self, config: Agent4Config):
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
            
            logger.success(f"🗄️ Агент 4: PostgreSQL БД инициализирована")
        except Exception as e:
            logger.error(f"❌ Агент 4: Ошибка инициализации PostgreSQL: {e}")
            raise
    
    async def close_database(self):
        if self.engine:
            await self.engine.dispose()
            logger.info("🗄️ Агент 4: Соединение с PostgreSQL закрыто")
    
    def get_session(self) -> AsyncSession:
        if not self.async_session_factory:
            raise RuntimeError("PostgreSQL database not initialized")
        return self.async_session_factory()

# =========================
# Redis Worker
# =========================
class Agent4RedisWorker:
    def __init__(self, config: Agent4Config):
        self.config = config
        self.analyzer = HeuristicAnalyzer()
        self.db = Agent4DatabaseManager(config)
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
            logger.success(f"🔗 Агент 4: Redis подключен {config.REDIS_HOST}:{config.REDIS_PORT}")
        except Exception as e:
            logger.error(f"❌ Агент 4: Не удалось подключиться к Redis: {e}")
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
                    "agent_id": 4,
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
                    "agent_id": 4,
                    "ban": False,
                    "reason": "Ошибка: правила не переданы",
                    "message": message,
                    "user_id": user_id,
                    "username": username,
                    "chat_id": chat_id,
                    "message_id": message_id
                }
            
            logger.info(f"[АГЕНТ 4] Анализирую сообщение: {message[:50]}...")
            logger.info("[АГЕНТ 4] Метод анализа: Эвристический анализатор")
            
            # Эвристический анализ
            analysis_result = self.analyzer.analyze(message, rules)
            
            # Формируем результат
            result = {
                "agent_id": 4,
                "ban": analysis_result["ban"],
                "reason": analysis_result["reason"],
                "message": message,
                "user_id": user_id,
                "username": username,
                "chat_id": chat_id,
                "message_id": message_id,
                "confidence": 0.75 if analysis_result["ban"] else 0.8,  # Эвристика менее уверена чем ИИ
                "timestamp": datetime.now().isoformat()
            }
            
            self.processed_count += 1
            logger.success(f"[АГЕНТ 4] Вердикт: {'БАН' if analysis_result['ban'] else 'НЕ БАНИТЬ'}")
            
            return result
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Агент 4: Невалидный JSON: {e}")
            return {
                "agent_id": 4,
                "ban": False,
                "reason": f"Ошибка парсинга данных: {e}",
                "message": ""
            }
        except Exception as e:
            logger.error(f"❌ Агент 4: Ошибка обработки сообщения: {e}")
            return {
                "agent_id": 4,
                "ban": False,
                "reason": f"Внутренняя ошибка агента 4: {e}",
                "message": ""
            }
    
    def send_result(self, result: Dict[str, Any]) -> None:
        """Отправка результата в выходную очередь"""
        try:
            result_json = json.dumps(result, ensure_ascii=False)
            self.redis_client.rpush(self.config.QUEUE_OUTPUT, result_json)
            logger.success(f"📤 Агент 4: Результат отправлен в {self.config.QUEUE_OUTPUT}")
        except Exception as e:
            logger.error(f"❌ Агент 4: Не удалось отправить результат: {e}")
    
    async def run(self):
        """Основной цикл обработки сообщений"""
        await self.db.init_database()
        
        logger.info(f"🚀 Агент 4 запущен")
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
                    logger.info(f"\n📨 Агент 4: Получено новое сообщение из {queue_name}")
                    
                    # Обрабатываем сообщение
                    output = await self.process_message(message_data)
                    
                    # Отправляем результат
                    self.send_result(output)
                    
                    logger.info(f"✅ Агент 4: Обработка завершена (всего: {self.processed_count})\n")
                    
                except KeyboardInterrupt:
                    logger.info("\n🛑 Агент 4: Получен сигнал остановки")
                    break
                except Exception as e:
                    logger.error(f"❌ Агент 4: Неожиданная ошибка: {e}")
                    await asyncio.sleep(1)
                    
        finally:
            await self.db.close_database()
            logger.info("👋 Агент 4 остановлен")

# =========================
# Тестирование
# =========================
async def test_agent_4():
    """Локальный тест агента 4"""
    logger.info("=== ТЕСТ АГЕНТА 4 ===")
    
    config = Agent4Config()
    worker = Agent4RedisWorker(config)
    
    # Тестовые данные
    test_data = {
        "message": "Идиот, дурак! Иди на хуй!",
        "rules": [
            "Запрещена реклама сторонних сообществ",
            "Запрещён флуд и спам",
            "Запрещены оскорбления участников",
            "Запрещена нецензурная лексика"
        ],
        "user_id": 987654321,
        "username": "@toxic_user",
        "chat_id": -1009876543210,
        "message_id": 100
    }
    
    test_json = json.dumps(test_data, ensure_ascii=False)
    result = await worker.process_message(test_json)
    
    logger.info("Результат:")
    print(json.dumps(result, ensure_ascii=False, indent=2))

# =========================
# Точка входа
# =========================
async def main():
    config = Agent4Config()
    worker = Agent4RedisWorker(config)
    await worker.run()

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        asyncio.run(test_agent_4())
    else:
        asyncio.run(main())