#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🗄️ ИНИЦИАЛИЗАЦИЯ БД И ДОБАВЛЕНИЕ МОДЕРАТОРОВ
Запусти один раз перед первым запуском бота!
"""

import logging
from sqlalchemy import create_engine, Column, Integer, BigInteger, String, Boolean, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("init_db")

# ============================================================================
# КОНФИГУРАЦИЯ
# ============================================================================

POSTGRES_URL = "postgresql+psycopg2://tg_user:mnvm71@176.108.248.211:5432/teleguard?sslmode=disable"
MODERATOR_IDS = [1621052774]  # ДОБАВЬ СВОИХ МОДЕРАТОРОВ СЮДА!

# ============================================================================
# МОДЕЛИ БД
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

class Message(Base):
    __tablename__ = 'messages'
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, nullable=False)
    message_id = Column(BigInteger, nullable=False)
    sender_username = Column(String)
    sender_id = Column(BigInteger)
    message_text = Column(String)
    message_link = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

class Moderator(Base):
    __tablename__ = 'moderators'
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, nullable=True)
    tg_user_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    added_at = Column(DateTime, default=datetime.utcnow)

class NegativeMessage(Base):
    __tablename__ = 'negative_messages'
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, nullable=False)
    message_link = Column(String)
    sender_username = Column(String)
    sender_id = Column(BigInteger)
    negative_reason = Column(String)
    is_sent_to_moderators = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    agent_id = Column(Integer)

class MediaFile(Base):
    __tablename__ = 'media_files'
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, nullable=False)
    user_id = Column(BigInteger, nullable=False)
    username = Column(String)
    media_type = Column(String)
    file_id = Column(String, unique=True, nullable=False)
    file_unique_id = Column(String)
    filename = Column(String, nullable=True)
    file_size = Column(Integer, nullable=True)
    mime_type = Column(String, nullable=True)
    local_path = Column(String, nullable=True)
    message_id = Column(BigInteger, nullable=False)
    message_link = Column(String)
    caption = Column(String, nullable=True)
    analysis_result = Column(String, nullable=True)
    is_suspicious = Column(Boolean, default=False)
    suspension_reason = Column(String, nullable=True)
    agent_id = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    analyzed_at = Column(DateTime, nullable=True)

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ БД
# ============================================================================

def initialize_database():
    """Инициализация БД и добавление модераторов"""
    try:
        logger.info("🚀 Инициализация БД...")
        
        # Создаём подключение
        engine = create_engine(POSTGRES_URL)
        
        # Создаём все таблицы
        Base.metadata.create_all(engine)
        logger.info("✅ Таблицы БД созданы/обновлены")
        
        # Создаём сессию
        Session = sessionmaker(bind=engine)
        session = Session()
        
        # Добавляем модераторов
        logger.info(f"📍 Добавляю {len(MODERATOR_IDS)} модератор(ов)...")
        
        added_count = 0
        for mod_id in MODERATOR_IDS:
            # Проверяем есть ли уже такой модератор
            existing = session.query(Moderator).filter_by(tg_user_id=mod_id).first()
            
            if existing:
                logger.info(f"⏭️  Модератор {mod_id} уже в БД, пропускаю")
                continue
            
            # Добавляем нового модератора
            moderator = Moderator(
                tg_user_id=mod_id,
                username=f"moderator_{mod_id}",
                is_active=True
            )
            session.add(moderator)
            added_count += 1
            logger.info(f"✅ Добавлен модератор: ID={mod_id}")
        
        # Сохраняем изменения
        session.commit()
        session.close()
        
        logger.info("=" * 70)
        logger.info(f"✅ ИНИЦИАЛИЗАЦИЯ ЗАВЕРШЕНА УСПЕШНО!")
        logger.info(f"✅ Добавлено новых модераторов: {added_count}")
        logger.info(f"✅ Всего модераторов в БД: {len(MODERATOR_IDS)}")
        logger.info("=" * 70)
        
        return True
        
    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}")
        logger.error("❌ Проверь:")
        logger.error("  1. PostgreSQL запущена? (psql -U postgres)")
        logger.error("  2. Правильный пароль в POSTGRES_URL?")
        logger.error("  3. БД 'teleguard' существует?")
        return False

if __name__ == "__main__":
    initialize_database()