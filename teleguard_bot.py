#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🤖 TELEGUARD BOT - ИНТЕРФЕЙС ВЕРСИЯ
✅ ИСПРАВЛЕНО: Правильная схема БД из PostgreSQL
"""

import json
import redis
import asyncio
import os
import aiohttp
from datetime import datetime

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker

# ============================================================================
# ИМПОРТ КОНФИГА
# ============================================================================

try:
    from config import (
        TELEGRAM_BOT_TOKEN, 
        get_redis_config, 
        get_db_connection_string,
        QUEUE_AGENT_2_INPUT, 
        QUEUE_AGENT_2_OUTPUT,
        QUEUE_AGENT_6_INPUT, 
        QUEUE_AGENT_6_OUTPUT,
        setup_logging,
        DOWNLOADS_DIR
    )
except ImportError as e:
    print(f"❌ ОШИБКА ИМПОРТА: {e}")
    exit(1)

logger = setup_logging("TELEGUARD BOT")

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# ============================================================================
# БД (РЕАЛЬНАЯ СХЕМА ИЗ PostgreSQL)
# ============================================================================

engine = create_engine(get_db_connection_string())
Session = sessionmaker(bind=engine)
Base = declarative_base()

class Chat(Base):
    """Таблица chats - реальная схема"""
    __tablename__ = "chats"
    id = Column(Integer, primary_key=True)
    tg_chat_id = Column(String, unique=True, nullable=False)
    title = Column(String)
    chat_type = Column(String)
    added_at = Column(DateTime, default=datetime.now)
    is_active = Column(Boolean, default=True)
    custom_rules = Column(String)

class Moderator(Base):
    """Таблица moderators"""
    __tablename__ = "moderators"
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer)  # FK to chats.id
    moderator_id = Column(String)
    added_at = Column(DateTime, default=datetime.now)

Base.metadata.create_all(engine)
redis_client = redis.Redis(**get_redis_config())

# ============================================================================
# STATES
# ============================================================================

class RegisterState(StatesGroup):
    waiting_chat_id = State()
    waiting_mod_id = State()

# ============================================================================
# КЛАВИАТУРЫ
# ============================================================================

def get_main_keyboard():
    """Главное меню кнопок"""
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Регистрация чата")],
            [KeyboardButton(text="👥 Список модераторов")],
            [KeyboardButton(text="➕ Добавить модератора")],
            [KeyboardButton(text="📊 Статус"), KeyboardButton(text="ℹ️ Справка")],
        ],
        resize_keyboard=True
    )
    return kb

def get_cancel_keyboard():
    """Отмена"""
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True
    )
    return kb

def get_status_inline():
    """Инлайн кнопки для статуса"""
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="status_refresh")],
            [InlineKeyboardButton(text="📁 Скачанные фото", callback_data="photos_list")],
            [InlineKeyboardButton(text="📊 Redis статистика", callback_data="redis_stats")],
        ]
    )
    return kb

# ============================================================================
# ПОМОЩНИКИ
# ============================================================================

def get_chat_by_tg_id(tg_chat_id):
    """Получить чат по tg_chat_id"""
    session = Session()
    try:
        chat = session.query(Chat).filter_by(tg_chat_id=str(tg_chat_id)).first()
        return chat
    finally:
        session.close()

def get_moderators(tg_chat_id):
    """Получить модераторов чата по tg_chat_id"""
    session = Session()
    try:
        chat = session.query(Chat).filter_by(tg_chat_id=str(tg_chat_id)).first()
        if not chat:
            return []
        mods = session.query(Moderator).filter_by(chat_id=chat.id).all()
        return [m.moderator_id for m in mods]
    finally:
        session.close()

async def download_file(file_id, file_name):
    """Скачать файл с Telegram"""
    try:
        from config import TELEGRAM_API_BASE
        url = f"{TELEGRAM_API_BASE}/bot{TELEGRAM_BOT_TOKEN}/getFile?file_id={file_id}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    tg_path = data["result"]["file_path"]
                    dl_url = f"{TELEGRAM_API_BASE}/file/bot{TELEGRAM_BOT_TOKEN}/{tg_path}"
                    async with session.get(dl_url) as fr:
                        if fr.status == 200:
                            os.makedirs(DOWNLOADS_DIR, exist_ok=True)
                            local = os.path.join(DOWNLOADS_DIR, file_name)
                            with open(local, "wb") as f:
                                f.write(await fr.read())
                            logger.info(f"✅ Фото скачано: {local}")
                            return local
    except Exception as e:
        logger.error(f"❌ Ошибка скачивания: {e}")
    return None

async def notify_mods(chat_id, result):
    """Уведомить модераторов"""
    try:
        mods = get_moderators(str(chat_id))
        if not mods:
            logger.info(f"📬 Чат {chat_id}: модераторы не найдены")
            return
        
        logger.info(f"📬 Чат {chat_id}: найдено {len(mods)} модератор(ов)")
        
        action = result.get("action", "none")
        user = result.get("user", result.get("username", "unknown"))
        severity = result.get("severity", 0)
        reason = result.get("reason", "Нарушение")
        verdict = result.get("verdict", None)
        
        if action in ["ban", "mute", "warn"]:
            emoji = {"ban": "🚫", "mute": "🔇", "warn": "⚠️"}[action]
            text = f"{emoji} *{action.upper()}*\n👤 @{user}\n📝 {reason}\n📊 {severity}/10"
        elif verdict is not None:
            if verdict:
                text = f"🚨 *НАРУШЕНИЕ В ФОТО*\n👤 @{user}\n📝 {reason}\n📊 {severity}/10"
            else:
                text = f"✅ Фото от @{user} - нарушений не найдено"
        else:
            text = f"✅ @{user} - нарушений не найдено"
        
        sent = 0
        for mod_id in mods:
            try:
                await bot.send_message(int(mod_id), text, parse_mode="Markdown")
                logger.info(f"✅ Уведомление {mod_id}")
                sent += 1
            except Exception as e:
                logger.error(f"❌ Ошибка отправки {mod_id}: {e}")
        logger.info(f"📊 Отправлено: {sent}/{len(mods)}")
    except Exception as e:
        logger.error(f"❌ Ошибка уведомления: {e}")

# ============================================================================
# КОМАНДЫ И КНОПКИ
# ============================================================================

@dp.message(Command("start"))
async def start(msg: Message):
    """Стартовое меню"""
    text = """👋 *Добро пожаловать в TeleGuard Bot!*

🤖 Я помогу модерировать ваш чат:
• Анализирую сообщения и фото
• Применяю действия (warn, mute, ban)
• Уведомляю модераторов

👇 Выбери действие из меню ниже"""
    
    await msg.answer(text, reply_markup=get_main_keyboard(), parse_mode="Markdown")
    logger.info(f"👤 Пользователь {msg.from_user.id} запустил бота")

@dp.message(F.text == "📋 Регистрация чата")
async def register_start(msg: Message, state: FSMContext):
    """Начало регистрации"""
    await msg.answer(
        "📝 Введи ID чата (начинается с минуса, например: -5081077172)\n\n💡 Как узнать ID?\n/id в групповом чате",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(RegisterState.waiting_chat_id)

@dp.message(RegisterState.waiting_chat_id)
async def register_chat_id(msg: Message, state: FSMContext):
    """Получаем ID чата"""
    if msg.text == "❌ Отмена":
        await msg.answer("❌ Отмена", reply_markup=get_main_keyboard())
        await state.clear()
        return
    
    try:
        chat_id = str(int(msg.text))
    except:
        await msg.answer("❌ Неверный ID! Должно быть число. Попробуй ещё:")
        return
    
    session = Session()
    try:
        existing_chat = session.query(Chat).filter_by(tg_chat_id=chat_id).first()
        if existing_chat:
            await msg.answer(f"✅ Чат {chat_id} уже зарегистрирован!", reply_markup=get_main_keyboard())
            await state.clear()
            return
        
        # Добавляем чат
        new_chat = Chat(tg_chat_id=chat_id, is_active=True)
        session.add(new_chat)
        session.flush()  # Получаем ID
        
        # Добавляем модератора
        moderator = Moderator(chat_id=new_chat.id, moderator_id=str(msg.from_user.id))
        session.add(moderator)
        session.commit()
        
        logger.info(f"✅ Чат {chat_id} зарегистрирован")
        await msg.answer(f"✅ Чат {chat_id} успешно зарегистрирован!\nТы - модератор.", reply_markup=get_main_keyboard())
    except Exception as e:
        logger.error(f"❌ Ошибка БД: {e}")
        await msg.answer(f"❌ Ошибка: {e}")
        session.rollback()
    finally:
        session.close()
    
    await state.clear()

@dp.message(F.text == "👥 Список модераторов")
async def list_mods(msg: Message, state: FSMContext):
    """Список модераторов"""
    await msg.answer("📝 Введи ID чата:", reply_markup=get_cancel_keyboard())
    await state.set_state(RegisterState.waiting_chat_id)

@dp.message(F.text == "➕ Добавить модератора")
async def add_mod_start(msg: Message, state: FSMContext):
    """Добавить модератора"""
    await msg.answer("📝 Введи ID чата:", reply_markup=get_cancel_keyboard())
    await state.set_state(RegisterState.waiting_chat_id)

@dp.message(RegisterState.waiting_chat_id, F.text != "❌ Отмена")
async def handle_chat_id(msg: Message, state: FSMContext):
    """Обработка ID чата"""
    tg_chat_id = msg.text
    mods = get_moderators(tg_chat_id)
    
    if not mods:
        await msg.answer(f"❌ Чат {tg_chat_id} не найден", reply_markup=get_main_keyboard())
    else:
        text = f"👥 *Модераторы чата {tg_chat_id}:*\n\n"
        for i, mod_id in enumerate(mods, 1):
            text += f"{i}. `{mod_id}`\n"
        await msg.answer(text, reply_markup=get_main_keyboard(), parse_mode="Markdown")
    
    await state.clear()

@dp.message(F.text == "📊 Статус")
async def status(msg: Message):
    """Статус системы"""
    try:
        redis_ping = redis_client.ping()
        redis_status = "✅ OK" if redis_ping else "❌ ERROR"
        
        session = Session()
        try:
            chats_count = session.query(Chat).count()
            mods_count = session.query(Moderator).count()
        finally:
            session.close()
        
        q2_len = redis_client.llen(QUEUE_AGENT_2_INPUT)
        q6_len = redis_client.llen(QUEUE_AGENT_6_INPUT)
        
        text = f"""📊 *СТАТУС СИСТЕМЫ*

🤖 *Компоненты:*
Redis: {redis_status}
БД Chats: {chats_count}
БД Mods: {mods_count}

📬 *Очереди:*
Agent 2: {q2_len} сообщений
Agent 6: {q6_len} фото

🕐 {datetime.now().strftime('%H:%M:%S')}"""
        
        await msg.answer(text, reply_markup=get_status_inline(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"❌ Ошибка статуса: {e}")
        await msg.answer(f"❌ Ошибка: {e}", reply_markup=get_main_keyboard())

@dp.message(F.text == "ℹ️ Справка")
async def help_cmd(msg: Message):
    """Справка"""
    text = """ℹ️ *СПРАВКА*

📋 *Команды меню:*
• Регистрация чата - зарегистрировать чат
• Список модераторов - показать модераторов
• Добавить модератора - добавить нового модератора
• Статус - показать статус системы

🚨 *Действия:*
🚫 BAN | 🔇 MUTE | ⚠️ WARN

📸 *Проверка:*
Текст + Фото анализируются автоматически"""
    
    await msg.answer(text, reply_markup=get_main_keyboard(), parse_mode="Markdown")

# ============================================================================
# ОБРАБОТКА СООБЩЕНИЙ И ФОТО
# ============================================================================

@dp.message(F.text & ~F.text.startswith("/"))
async def handle_text(msg: Message):
    """Обработка текста"""
    try:
        if msg.chat.type == "private":
            return
        
        logger.info(f"📨 Сообщение от @{msg.from_user.username or msg.from_user.id}: '{msg.text[:50]}'")
        
        data = {
            "message": msg.text,
            "username": msg.from_user.username or "unknown",
            "user_id": msg.from_user.id,
            "chat_id": msg.chat.id,
            "message_id": msg.message_id,
            "timestamp": datetime.now().isoformat()
        }
        
        redis_client.rpush(QUEUE_AGENT_2_INPUT, json.dumps(data, ensure_ascii=False))
        logger.info(f"📤 Сообщение отправлено в очередь агента 2")
    except Exception as e:
        logger.error(f"❌ Ошибка текста: {e}")

@dp.message(F.photo)
async def handle_photo(msg: Message):
    """Обработка фото"""
    try:
        photo = msg.photo[-1]
        logger.info(f"📸 ФОТО: {photo.file_id}")
        
        file_name = f"photo_{msg.from_user.id}_{msg.message_id}.jpg"
        local_path = await download_file(photo.file_id, file_name)
        
        if not local_path:
            return
        
        data = {
            "media_type": "photo",
            "local_path": local_path,
            "username": msg.from_user.username or "unknown",
            "user_id": msg.from_user.id,
            "chat_id": msg.chat.id,
            "message_id": msg.message_id,
            "caption": msg.caption or "",
            "timestamp": datetime.now().isoformat()
        }
        
        redis_client.rpush(QUEUE_AGENT_6_INPUT, json.dumps(data, ensure_ascii=False))
        logger.info(f"📤 ФОТО отправлено АГЕНТУ 6")
    except Exception as e:
        logger.error(f"❌ Ошибка фото: {e}")

@dp.callback_query(F.data == "status_refresh")
async def status_refresh(query):
    """Обновить статус"""
    await query.answer("🔄 Обновляю...")
    await status(query.message)

@dp.callback_query(F.data == "photos_list")
async def photos_list(query):
    """Список скачанных фото"""
    try:
        if not os.path.exists(DOWNLOADS_DIR):
            await query.answer("📁 Нет фото")
            return
        
        files = os.listdir(DOWNLOADS_DIR)
        if not files:
            await query.answer("📁 Папка пуста")
            return
        
        text = f"📁 *Скачано {len(files)} фото:*\n\n"
        for f in files[:10]:
            size = os.path.getsize(os.path.join(DOWNLOADS_DIR, f)) / 1024
            text += f"• {f} ({size:.1f}KB)\n"
        
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=get_status_inline())
    except Exception as e:
        logger.error(f"❌ Ошибка списка: {e}")
        await query.answer(f"❌ {e}")

@dp.callback_query(F.data == "redis_stats")
async def redis_stats(query):
    """Статистика Redis"""
    try:
        info = redis_client.info()
        text = f"""📊 *REDIS СТАТИСТИКА*

💾 Memory: {info['used_memory_human']}
📊 Clients: {info['connected_clients']}
📈 Keys: {redis_client.dbsize()}"""
        
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=get_status_inline())
    except Exception as e:
        logger.error(f"❌ Ошибка Redis: {e}")
        await query.answer(f"❌ {e}")

# ============================================================================
# RESULT READER
# ============================================================================

async def result_reader():
    """Читает результаты и уведомляет"""
    logger.info("📥 READER: Слушаю результаты")
    
    while True:
        try:
            result = redis_client.blpop(QUEUE_AGENT_2_OUTPUT, timeout=1)
            if result:
                _, data = result
                try:
                    j = json.loads(data)
                    await notify_mods(j.get("chat_id"), j)
                except Exception as e:
                    logger.error(f"❌ Ошибка обработки результата: {e}")
            
            result = redis_client.blpop(QUEUE_AGENT_6_OUTPUT, timeout=1)
            if result:
                _, data = result
                try:
                    j = json.loads(data)
                    await notify_mods(j.get("chat_id"), j)
                except Exception as e:
                    logger.error(f"❌ Ошибка обработки результата: {e}")
            
            await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"❌ Reader: {e}")
            await asyncio.sleep(1)

# ============================================================================
# MAIN
# ============================================================================

async def main():
    logger.info("✅ БОТ ЗАПУЩЕН!")
    
    reader_task = asyncio.create_task(result_reader())
    
    try:
        await dp.start_polling(bot)
    finally:
        reader_task.cancel()
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 БОТ ОСТАНОВЛЕН")
    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}")
