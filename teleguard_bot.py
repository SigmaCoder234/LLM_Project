#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🤖 TELEGUARD BOT - ПРОФЕССИОНАЛЬНАЯ ВЕРСИЯ С ИНТЕРФЕЙСОМ
✅ Кнопки (ReplyKeyboardMarkup) + инлайн-кнопки (InlineKeyboardMarkup)
✅ Удобный интерфейс
✅ Полная проверка работоспособности
✅ Фото + Текст
"""

import json
import redis
import asyncio
import os
import aiohttp
from datetime import datetime

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, PhotoSize, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_API_BASE, get_redis_config, get_db_connection_string,
    QUEUE_AGENT_2_INPUT, QUEUE_AGENT_6_INPUT, DOWNLOADS_DIR, setup_logging
)

logger = setup_logging("TELEGUARD BOT")

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# ============================================================================
# БД
# ============================================================================

engine = create_engine(get_db_connection_string())
Session = sessionmaker(bind=engine)
Base = declarative_base()

class Chat(Base):
    __tablename__ = "chats"
    id = Column(Integer, primary_key=True)
    chat_id = Column(String, unique=True)
    owner_id = Column(String)
    created_at = Column(DateTime, default=datetime.now)

class Moderator(Base):
    __tablename__ = "moderators"
    id = Column(Integer, primary_key=True)
    chat_id = Column(String)
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
            [InlineKeyboardButton(text="📊 Статистика Redis", callback_data="redis_stats")],
        ]
    )
    return kb

# ============================================================================
# ПОМОЩНИКИ
# ============================================================================

def get_moderators(chat_id):
    session = Session()
    mods = session.query(Moderator).filter_by(chat_id=str(chat_id)).all()
    session.close()
    return [m.moderator_id for m in mods]

async def download_file(file_id, file_name):
    try:
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
        logger.error(f"❌ Ошибка: {e}")
    return None

async def notify_mods(chat_id, result):
    try:
        mods = get_moderators(str(chat_id))
        if not mods:
            return
        
        logger.info(f"📬 Чат {chat_id}: найдено {len(mods)} модератор(ов)")
        
        action = result.get("action", "none")
        user = result.get("user", result.get("username", "unknown"))
        severity = result.get("severity", 0)
        confidence = result.get("confidence", 0)
        reason = result.get("reason", "Нарушение")
        verdict = result.get("verdict", None)
        
        if action in ["ban", "mute", "warn"]:
            emoji = {"ban": "🚫", "mute": "🔇", "warn": "⚠️"}[action]
            text = f"{emoji} *{action.upper()}*\n👤 @{user}\n📝 {reason}\n📊 {severity}/10 ({confidence:.0%})\n🕐 {datetime.now().strftime('%H:%M:%S')}"
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
            except:
                pass
        logger.info(f"📊 Отправлено: {sent}/{len(mods)}")
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")

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
        "📝 Введи ID чата (начинается с минуса, например: -5081077172)\n\n💡 Как узнать ID?\n/id в групповом чате (нужен @GroupHelpBot)",
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
        chat_id = str(int(msg.text))  # Проверяем, что это число
    except:
        await msg.answer("❌ Неверный ID! Должно быть число. Попробуй ещё:")
        return
    
    session = Session()
    if session.query(Chat).filter_by(chat_id=chat_id).first():
        await msg.answer(f"✅ Чат {chat_id} уже зарегистрирован!", reply_markup=get_main_keyboard())
        session.close()
        await state.clear()
        return
    
    try:
        session.add(Chat(chat_id=chat_id, owner_id=str(msg.from_user.id)))
        session.add(Moderator(chat_id=chat_id, moderator_id=str(msg.from_user.id)))
        session.commit()
        logger.info(f"✅ Чат {chat_id} зарегистрирован")
        await msg.answer(f"✅ Чат {chat_id} успешно зарегистрирован!\nТы - модератор.\n\n👇 Что дальше?", reply_markup=get_main_keyboard())
    except Exception as e:
        await msg.answer(f"❌ Ошибка: {e}")
    finally:
        session.close()
    
    await state.clear()

@dp.message(F.text == "👥 Список модераторов")
async def list_mods(msg: Message, state: FSMContext):
    """Список модераторов"""
    await msg.answer("📝 Введи ID чата:", reply_markup=get_cancel_keyboard())
    await state.set_state(RegisterState.waiting_chat_id)  # Переиспользуем состояние для простоты
    
    # Но обработаем по-другому
    @dp.message(RegisterState.waiting_chat_id, F.text != "❌ Отмена")
    async def list_mods_get(m: Message, s: FSMContext):
        chat_id = m.text
        mods = get_moderators(chat_id)
        
        if not mods:
            await m.answer(f"❌ Чат {chat_id} не найден", reply_markup=get_main_keyboard())
        else:
            text = f"👥 *Модераторы чата {chat_id}:*\n\n"
            for i, mod_id in enumerate(mods, 1):
                text += f"{i}. `{mod_id}`\n"
            await m.answer(text, reply_markup=get_main_keyboard(), parse_mode="Markdown")
        
        await s.clear()

@dp.message(F.text == "➕ Добавить модератора")
async def add_mod_start(msg: Message, state: FSMContext):
    """Добавить модератора"""
    await msg.answer("📝 Введи ID чата:", reply_markup=get_cancel_keyboard())
    await state.set_state(RegisterState.waiting_chat_id)

@dp.message(RegisterState.waiting_chat_id, F.text != "❌ Отмена")
async def add_mod_id(msg: Message, state: FSMContext):
    """Получаем ID чата, потом ID модератора"""
    await state.update_data(chat_id=msg.text)
    await msg.answer("👤 Введи ID модератора:", reply_markup=get_cancel_keyboard())
    await state.set_state(RegisterState.waiting_mod_id)

@dp.message(RegisterState.waiting_mod_id)
async def add_mod_final(msg: Message, state: FSMContext):
    """Добавляем модератора"""
    if msg.text == "❌ Отмена":
        await msg.answer("❌ Отмена", reply_markup=get_main_keyboard())
        await state.clear()
        return
    
    data = await state.get_data()
    chat_id = data.get("chat_id")
    mod_id = msg.text
    
    session = Session()
    if session.query(Moderator).filter_by(chat_id=chat_id, moderator_id=mod_id).first():
        await msg.answer(f"⚠️ {mod_id} уже модератор!", reply_markup=get_main_keyboard())
    else:
        session.add(Moderator(chat_id=chat_id, moderator_id=mod_id))
        session.commit()
        await msg.answer(f"✅ Модератор {mod_id} добавлен в чат {chat_id}!", reply_markup=get_main_keyboard())
        logger.info(f"✅ Модератор {mod_id} добавлен")
    
    session.close()
    await state.clear()

@dp.message(F.text == "📊 Статус")
async def status(msg: Message):
    """Статус системы"""
    try:
        # Проверяем Redis
        redis_ping = redis_client.ping()
        redis_status = "✅ OK" if redis_ping else "❌ ERROR"
        
        # Проверяем БД
        session = Session()
        chats_count = session.query(Chat).count()
        mods_count = session.query(Moderator).count()
        session.close()
        
        # Очереди
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

🤖 *Как это работает:*
1️⃣ Регистрируешь чат
2️⃣ Добавляешь модераторов
3️⃣ Бот анализирует сообщения и фото
4️⃣ Модераторы получают уведомления

🚨 *Действия модерации:*
🚫 BAN - полная блокировка
🔇 MUTE - запрет на сообщения на 24ч
⚠️ WARN - предупреждение

📸 *Анализ фото:*
Бот проверяет фото на:
• Обнажённость
• Насилие
• Экстремизм

❓ *Вопросы?*
Свяжись с администратором"""
    
    await msg.answer(text, reply_markup=get_main_keyboard(), parse_mode="Markdown")

# ============================================================================
# СООБЩЕНИЯ И ФОТО
# ============================================================================

@dp.message(F.text & ~F.text.startswith("/") & ~F.text.startswith("📋") & ~F.text.startswith("👥") & ~F.text.startswith("➕") & ~F.text.startswith("📊") & ~F.text.startswith("ℹ️"))
async def handle_text(msg: Message):
    """Обработка текста"""
    try:
        if msg.chat.type == "private":
            return  # Пропускаем личные сообщения
        
        logger.info(f"📨 Сообщение от @{msg.from_user.username}: '{msg.text[:50]}'")
        
        data = {
            "message": msg.text,
            "username": msg.from_user.username or "unknown",
            "user_id": msg.from_user.id,
            "chat_id": msg.chat.id,
            "message_id": msg.message_id,
            "timestamp": datetime.now().isoformat()
        }
        
        redis_client.rpush(QUEUE_AGENT_2_INPUT, json.dumps(data, ensure_ascii=False))
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")

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
        for f in files[:10]:  # Показываем первые 10
            size = os.path.getsize(os.path.join(DOWNLOADS_DIR, f)) / 1024
            text += f"• {f} ({size:.1f}KB)\n"
        
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=get_status_inline())
    except Exception as e:
        await query.answer(f"❌ {e}")

@dp.callback_query(F.data == "redis_stats")
async def redis_stats(query):
    """Статистика Redis"""
    try:
        info = redis_client.info()
        text = f"""📊 *REDIS СТАТИСТИКА*

💾 Memory: {info['used_memory_human']}
📊 Connected Clients: {info['connected_clients']}
📬 Commands: {info['total_commands_processed']}
📈 Keys: {redis_client.dbsize()}

🔄 Последние очереди:
Agent 2: {redis_client.llen(QUEUE_AGENT_2_INPUT)}
Agent 6: {redis_client.llen(QUEUE_AGENT_6_INPUT)}"""
        
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=get_status_inline())
    except Exception as e:
        await query.answer(f"❌ {e}")

# ============================================================================
# RESULT READER
# ============================================================================

async def result_reader():
    """Читает результаты и уведомляет"""
    logger.info("📥 READER: Слушаю результаты")
    
    while True:
        try:
            result = redis_client.blpop("queue:agent2:output", timeout=1)
            if result:
                _, data = result
                try:
                    j = json.loads(data)
                    await notify_mods(j.get("chat_id"), j)
                except:
                    pass
            
            result = redis_client.blpop("queue:agent6:output", timeout=1)
            if result:
                _, data = result
                try:
                    j = json.loads(data)
                    await notify_mods(j.get("chat_id"), j)
                except:
                    pass
            
            await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"❌ Reader: {e}")
            await asyncio.sleep(1)

# ============================================================================
# MAIN
# ============================================================================

async def main():
    logger.info("✅ БОТ ЗАПУЩЕН С ИНТЕРФЕЙСОМ!")
    
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
