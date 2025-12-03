#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🚀 ИНИЦИАЛИЗАЦИЯ БД - СОЗДАНИЕ ТАБЛИЦ И ДОБАВЛЕНИЕ МОДЕРАТОРОВ
"""

import logging
from sqlalchemy import create_engine, text
from config import POSTGRES_URL, MODERATOR_IDS

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def init_database():
    """Инициализирует БД: создаёт таблицы и добавляет модераторов"""
    
    try:
        logger.info("🚀 Инициализация БД...")
        
        # Подключаемся к БД в одной сессии для всех операций
        engine = create_engine(POSTGRES_URL)
        
        with engine.begin() as connection:
            # SQL для создания таблиц
            create_tables_sql = """
            CREATE TABLE IF NOT EXISTS moderators (
                id SERIAL PRIMARY KEY,
                tg_user_id BIGINT UNIQUE NOT NULL,
                username VARCHAR(255),
                first_name VARCHAR(255),
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS chats (
                id SERIAL PRIMARY KEY,
                tg_chat_id BIGINT UNIQUE NOT NULL,
                title VARCHAR(255),
                chat_type VARCHAR(50),
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE,
                custom_rules TEXT
            );

            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                message_id BIGINT NOT NULL,
                sender_username VARCHAR(255),
                sender_id BIGINT NOT NULL,
                message_text TEXT,
                message_link VARCHAR(500),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP,
                ai_response TEXT,
                FOREIGN KEY (chat_id) REFERENCES chats(id)
            );

            CREATE TABLE IF NOT EXISTS violations (
                id SERIAL PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                message_id BIGINT NOT NULL,
                sender_id BIGINT NOT NULL,
                violation_type VARCHAR(100),
                description TEXT,
                severity VARCHAR(50),
                action_taken VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id) REFERENCES chats(id)
            );

            CREATE TABLE IF NOT EXISTS agent_logs (
                id SERIAL PRIMARY KEY,
                agent_id INTEGER,
                event_type VARCHAR(100),
                message_id BIGINT,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS media_files (
                id SERIAL PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                message_id BIGINT NOT NULL,
                file_type VARCHAR(50),
                file_id VARCHAR(255),
                analysis_result TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id) REFERENCES chats(id)
            );
            CREATE TABLE IF NOT EXISTS violations (
    			id SERIAL PRIMARY KEY,
  				chat_id INTEGER NOT NULL,
    			message_id BIGINT NOT NULL,
    			sender_id BIGINT NOT NULL,
    			violation_type VARCHAR(100),
    			description TEXT,
    			severity VARCHAR(50),
    			action_taken VARCHAR(50),  # ← уже есть
    			action_duration INTEGER DEFAULT 0,  # ← ДОБАВИТЬ
        		action_reason VARCHAR(255),  # ← ДОБАВИТЬ
   			    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
		        FOREIGN KEY (chat_id) REFERENCES chats(id)
			);
            """
            
            # Выполняем создание таблиц
            for statement in create_tables_sql.split(';'):
                statement = statement.strip()
                if statement:
                    connection.execute(text(statement))
            
            logger.info("✅ Таблицы созданы успешно!")
            
            # ДОБАВЛЯЕМ МОДЕРАТОРОВ В ТОЙ ЖЕ СЕССИИ
            added_count = 0
            for moderator_id in MODERATOR_IDS:
                # Проверяем есть ли уже такой модератор
                result = connection.execute(
                    text("SELECT COUNT(*) FROM moderators WHERE tg_user_id = :id"),
                    {"id": moderator_id}
                )
                exists = result.scalar() > 0
                
                if not exists:
                    connection.execute(
                        text("""
                            INSERT INTO moderators (tg_user_id, is_active)
                            VALUES (:id, TRUE)
                        """),
                        {"id": moderator_id}
                    )
                    added_count += 1
            
            # Подсчитываем общее количество
            result = connection.execute(text("SELECT COUNT(*) FROM moderators"))
            total_moderators = result.scalar()
            
            logger.info(f"✅ ИНИЦИАЛИЗАЦИЯ ЗАВЕРШЕНА УСПЕШНО!")
            logger.info(f"✅ Добавлено новых модераторов: {added_count}")
            logger.info(f"✅ Всего модераторов в БД: {total_moderators}")
            
    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}")
        logger.error(f"❌ Проверь:")
        logger.error(f"  1. PostgreSQL запущена? (psql -U postgres)")
        logger.error(f"  2. Правильный пароль в POSTGRES_URL?")
        logger.error(f"  3. БД 'teleguard' существует?")
        raise

if __name__ == "__main__":
    init_database()
