#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🚀 ИНИЦИАЛИЗАЦИЯ БД TELEGUARD (БЕЗ psql)
Работает через SQLAlchemy напрямую
"""

import sys
from pathlib import Path

# Добавляем текущую директорию в path
sys.path.insert(0, str(Path(__file__).parent))

from config import get_db_connection_string
from sqlalchemy import create_engine, text

print("=" * 70)
print("🚀 ИНИЦИАЛИЗАЦИЯ БД TELEGUARD")
print("=" * 70)

try:
    # Подключаемся к БД
    db_url = get_db_connection_string()
    print(f"📍 Подключение: {db_url.split('@')[1]}")
    
    engine = create_engine(db_url)
    
    # Пытаемся подключиться
    with engine.begin() as conn:
        print("✅ Подключение успешно!")
        
        # Удаляем старые таблицы
        print("\n🗑️ Удаление старых таблиц...")
        try:
            conn.execute(text("DROP TABLE IF EXISTS moderators CASCADE;"))
            conn.execute(text("DROP TABLE IF EXISTS chats CASCADE;"))
            print("✅ Старые таблицы удалены")
        except Exception as e:
            print(f"⚠️ Таблицы не существовали или уже удалены")
        
        # Создаём новые таблицы
        print("\n📝 Создание новых таблиц...")
        
        # Таблица chats
        print("  ├─ chats...", end=" ")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS chats (
                id SERIAL PRIMARY KEY,
                tg_chat_id VARCHAR(100) UNIQUE NOT NULL,
                title VARCHAR(255),
                chat_type VARCHAR(50),
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE,
                custom_rules TEXT
            );
        """))
        print("✅")
        
        # Таблица moderators (ИСПРАВЛЕННАЯ)
        print("  └─ moderators (ИСПРАВЛЕННАЯ)...", end=" ")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS moderators (
                id SERIAL PRIMARY KEY,
                tg_user_id BIGINT UNIQUE NOT NULL,
                username VARCHAR(255),
                first_name VARCHAR(255),
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))
        print("✅")
        
        # Проверяем структуру таблицы
        print("\n🔍 Проверка структуры moderators:")
        result = conn.execute(text("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns 
            WHERE table_name = 'moderators'
            ORDER BY ordinal_position;
        """))
        
        for col_name, col_type, nullable in result:
            nullable_str = "NOT NULL" if nullable == "NO" else "nullable"
            print(f"  ├─ {col_name:15} {col_type:20} ({nullable_str})")
        
        print("\n" + "=" * 70)
        print("✅ ИНИЦИАЛИЗАЦИЯ ЗАВЕРШЕНА УСПЕШНО!")
        print("=" * 70)
        print("\n🎉 БД ГОТОВА К ИСПОЛЬЗОВАНИЮ!")
        print("\nЧто дальше:")
        print("  1. Заменить teleguard_bot.py на teleguard_bot_fixed.py:")
        print("     $ cp teleguard_bot_fixed.py teleguard_bot.py")
        print("\n  2. Остановить и запустить бота:")
        print("     $ bash stop_all.sh && sleep 2 && bash start_all.sh")
        print("\n  3. Протестировать:")
        print("     - Отправь боту /start")
        print("     - Нажми '📊 Статус' (должно работать БЕЗ ошибок!)")
        print("     - Нажми '📋 Регистрация чата' и введи ID")
        print("\n" + "=" * 70)
        
except Exception as e:
    print(f"\n❌ ОШИБКА: {e}")
    print("\nПроверь:")
    print("  1. PostgreSQL запущена?")
    print("     $ sudo systemctl status postgresql")
    print("\n  2. Пользователь tg_user создан?")
    print("     $ psql -U postgres -c \"SELECT usename FROM pg_user;\"")
    print("\n  3. БД teleguard создана?")
    print("     $ psql -U tg_user -h localhost -d teleguard -c \"SELECT 1;\"")
    print("\n  4. Пароль правильный в config.py? (должен быть: mnvm71)")
    sys.exit(1)
