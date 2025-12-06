#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🤖 TeleGuard Bot v3.0 - ПОЛНАЯ ВЕРСИЯ С МОДЕРАТОРАМИ ПО ЧАТАМ
✅ Модерирование групповых чатов Telegram с 6 ИИ агентами
✅ Система модераторов (по чатам) - ИСПРАВЛЕНО!
✅ Анализ текста, фото, видео, документов
✅ Mistral AI интеграция
✅ ИСПРАВЛЕНО: Уведомления только для модераторов конкретного чата
✅ ИСПРАВЛЕНО: Чтение фото из Redis
"""

import logging
import asyncio
import json
import time
import redis
import requests
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import Column, Integer, String, ForeignKey, BigInteger, Boolean, DateTime, create_engine, Text, UniqueConstraint
from sqlalchemy.orm import relationship

# ============================================================================
# КОНФИГУРАЦИЯ
# ============================================================================

TOKEN = "8320009669:AAHadwhYKIg6qcwAwJabsBEOO7srfWwMiXE"
POSTGRES_URL = "postgresql+psycopg2://tg_user:mnvm71@localhost:5432/teleguard?sslmode=disable"
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0

# ============================================================================
# ЛОГИРОВАНИЕ
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [TELEGRAM BOT] %(levelname)s - %(message)s'
)
logger = logging.getLogger("TeleGuard")

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ AIOGRAM
# ============================================================================

bot = Bot(token=TOKEN)
dp = Dispatcher()

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
    custom_rules = Column(Text, nullable=True)
    messages = relationship("Message", back_populates="chat", cascade="all, delete")
    moderators = relationship("Moderator", back_populates="chat", cascade="all, delete")
    negative_messages = relationship("NegativeMessage", back_populates="chat", cascade="all, delete")
    media_files = relationship("MediaFile", back_populates="chat", cascade="all, delete")

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
    chat = relationship("Chat", back_populates="messages")

class Moderator(Base):
    __tablename__ = 'moderators'
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, ForeignKey('chats.id'), nullable=True)
    tg_user_id = Column(BigInteger, nullable=False)
    username = Column(String, nullable=True)
    is_owner = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    added_at = Column(DateTime, default=datetime.utcnow)
    chat = relationship("Chat", back_populates="moderators")
    
    __table_args__ = (
        UniqueConstraint('chat_id', 'tg_user_id', name='unique_mod_per_chat'),
    )

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
    chat = relationship("Chat", back_populates="negative_messages")

class MediaFile(Base):
    __tablename__ = 'media_files'
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, ForeignKey('chats.id'), nullable=False)
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
    caption = Column(Text, nullable=True)
    analysis_result = Column(Text, nullable=True)
    is_suspicious = Column(Boolean, default=False)
    suspension_reason = Column(Text, nullable=True)
    agent_id = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    analyzed_at = Column(DateTime, nullable=True)
    chat = relationship("Chat", back_populates="media_files")

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ БД И REDIS
# ============================================================================

engine = create_engine(POSTGRES_URL)
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)

def get_db_session():
    return SessionLocal()

try:
    redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
    redis_client.ping()
    logger.info(f"✅ Redis подключен {REDIS_HOST}:{REDIS_PORT}")
except Exception as e:
    logger.error(f"❌ Ошибка Redis: {e}")
    redis_client = None

# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================================

def is_group_chat(chat_type: str) -> bool:
    """✅ Проверка что это групповой чат"""
    return chat_type in ['group', 'supergroup', 'channel']

def get_chat_moderators(chat_id_str: str, db_session):
    """✅ ПОЛУЧИТЬ МОДЕРАТОРОВ КОНКРЕТНОГО ЧАТА"""
    try:
        chat = db_session.query(Chat).filter_by(tg_chat_id=chat_id_str).first()
        if not chat:
            logger.warning(f"⚠️ Чат {chat_id_str} не найден в БД")
            return []
        
        moderators = db_session.query(Moderator).filter_by(
            chat_id=chat.id,
            is_active=True
        ).all()
        
        logger.info(f"📍 Найдено модераторов для чата {chat_id_str}: {len(moderators)}")
        return moderators
    except Exception as e:
        logger.error(f"❌ Ошибка получения модераторов: {e}")
        return []

# ============================================================================
# 🚨 УВЕДОМЛЕНИЕ МОДЕРАТОРАМ (ИСПРАВЛЕНО!)
# ============================================================================

async def notify_moderators(session, message_text, message_link, user_id, username, verdict, reason, severity=0, chat_id_str=None):
    """🚨 ОТПРАВКА УВЕДОМЛЕНИЯ МОДЕРАТОРАМ КОНКРЕТНОГО ЧАТА"""
    try:
        # ✅ КРИТИЧНО: Если чат указан - берем ТОЛЬКО его модераторов
        if chat_id_str:
            moderators = get_chat_moderators(str(chat_id_str), session)
            logger.info(f"🔍 Чат {chat_id_str}: найдено {len(moderators)} модератор(ов)")
        else:
            logger.warning(f"⚠️ chat_id_str не передан! Уведомление НЕ отправляется")
            return False
        
        if not moderators:
            logger.warning(f"⚠️ Модераторов для чата {chat_id_str} не найдено!")
            return False
        
        # ✅ ШАГ 2: Формируем уведомление
        action = "🚨 НАРУШЕНИЕ" if verdict else "✅ ОК"
        msg_preview = message_text[:100] if len(message_text) > 100 else message_text
        reason_text = f"{reason[:150]}" if reason else ""
        
        if severity > 0:
            severity_bar = "🔴" * min(int(severity / 10), 10)
            notification = (
                f"{action}\n"
                f"{severity_bar} ({severity}/10)\n\n"
                f"👤 @{username}\n"
                f"🆔 ID: {user_id}\n"
                f"💬 Сообщение: {msg_preview}\n"
                f"📝 Причина: {reason_text}\n"
                f"🔗 Ссылка: {message_link}"
            )
        else:
            notification = (
                f"{action}\n\n"
                f"👤 @{username}\n"
                f"🆔 ID: {user_id}\n"
                f"💬 Сообщение: {msg_preview}\n"
                f"📝 Причина: {reason_text}\n"
                f"🔗 Ссылка: {message_link}"
            )
        
        # ✅ ШАГ 3: Отправляем ТОЛЬКО нужным модераторам
        sent_count = 0
        for moderator in moderators:
            try:
                await bot.send_message(
                    chat_id=moderator.tg_user_id,
                    text=notification,
                    parse_mode="HTML"
                )
                logger.info(f"✅ Уведомление отправлено модератору {moderator.tg_user_id} (@{moderator.username})")
                sent_count += 1
            except Exception as e:
                logger.error(f"❌ Не удалось отправить модератору {moderator.tg_user_id}: {e}")
        
        logger.info(f"📊 Уведомлений отправлено: {sent_count}/{len(moderators)}")
        return sent_count > 0
        
    except Exception as e:
        logger.error(f"❌ Ошибка notify_moderators: {e}")
        return False

# ============================================================================
# СОХРАНЕНИЕ В БД
# ============================================================================

def save_message_to_db(message_data: dict, db_session):
    """Сохранение текстового сообщения в БД"""
    try:
        chat = db_session.query(Chat).filter_by(tg_chat_id=str(message_data['chat_id'])).first()
        if not chat:
            chat = Chat(
                tg_chat_id=str(message_data['chat_id']),
                title=f"Chat {message_data['chat_id']}"
            )
            db_session.add(chat)
            db_session.commit()
        
        msg = Message(
            chat_id=chat.id,
            message_id=message_data['message_id'],
            sender_username=message_data['username'],
            sender_id=message_data['user_id'],
            message_text=message_data['message'],
            message_link=message_data['message_link']
        )
        db_session.add(msg)
        db_session.commit()
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения сообщения: {e}")
        return False

def save_media_to_db(media_data: dict, db_session):
    """Сохранение медиа файла в БД"""
    try:
        chat = db_session.query(Chat).filter_by(tg_chat_id=str(media_data['chat_id'])).first()
        if not chat:
            chat = Chat(
                tg_chat_id=str(media_data['chat_id']),
                title=f"Chat {media_data['chat_id']}",
                chat_type='group'
            )
            db_session.add(chat)
            db_session.commit()
        
        media_obj = MediaFile(
            chat_id=chat.id,
            user_id=media_data['user_id'],
            username=media_data['username'],
            media_type=media_data['media_type'],
            file_id=media_data['file_id'],
            file_unique_id=media_data.get('file_unique_id'),
            filename=media_data.get('filename'),
            file_size=media_data.get('file_size'),
            mime_type=media_data.get('mime_type'),
            message_id=media_data['message_id'],
            message_link=media_data['message_link'],
            caption=media_data.get('caption', ''),
            local_path=media_data.get('local_path'),
            created_at=datetime.utcnow()
        )
        db_session.add(media_obj)
        db_session.commit()
        logger.info(f"✅ Медиа сохранено в БД с ID {media_obj.id}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения медиа: {e}")
        return False

# ============================================================================
# ОТПРАВКА АГЕНТАМ
# ============================================================================

async def send_to_agent2(message_data: dict):
    """Отправка текста агенту 2 через Redis"""
    try:
        if not redis_client:
            logger.error("❌ Redis не доступен")
            return False
        
        message_json = json.dumps(message_data, ensure_ascii=False)
        redis_client.rpush("queue:agent2:input", message_json)
        logger.info(f"📤 Текст отправлено агенту 2")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка отправки агенту 2: {e}")
        return False

async def send_to_media_agent(media_data: dict):
    """✅ ОТПРАВКА МЕДИА АГЕНТУ 6 через Redis"""
    try:
        if not redis_client:
            logger.error("❌ Redis не доступен")
            return False
        
        media_json = json.dumps(media_data, ensure_ascii=False)
        redis_client.rpush("queue:agent6:input", media_json)
        logger.info(f"📤 МЕДИА отправлено АГЕНТУ 6: {media_data.get('media_type')} от @{media_data.get('username')}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка отправки медиа агенту 6: {e}")
        return False

# ============================================================================
# 📡 ЧИТАЕМ РЕЗУЛЬТАТЫ ОТ АГЕНТОВ (НОВОЕ!)
# ============================================================================

async def read_agent_results():
    """🔄 СЛУШАЕМ РЕЗУЛЬТАТЫ ОТ АГЕНТОВ 2 И 6"""
    while True:
        try:
            if not redis_client:
                await asyncio.sleep(1)
                continue
            
            # ✅ ЧИТАЕМ РЕЗУЛЬТАТЫ ОТ АГЕНТА 2 (ТЕКСТ)
            try:
                result_text = redis_client.lpop("queue:agent2:output")
                if result_text:
                    data = json.loads(result_text)
                    logger.info(f"📥 РЕЗУЛЬТАТ ОТ АГЕНТА 2/5: {data.get('action')} от @{data.get('username')}")
                    
                    # ✅ ПЕРЕДАЕМ CHAT_ID В notify_moderators
                    db_session = get_db_session()
                    await notify_moderators(
                        session=db_session,
                        message_text=data.get('message_text', ''),
                        message_link=data.get('message_link', ''),
                        user_id=data.get('user_id', 0),
                        username=data.get('username', 'unknown'),
                        verdict=data.get('action') != 'none',
                        reason=data.get('reason', ''),
                        severity=data.get('severity', 0),
                        chat_id_str=str(data.get('chat_id', ''))  # ✅ КРИТИЧНО!
                    )
                    db_session.close()
            except Exception as e:
                logger.error(f"❌ Ошибка обработки результата агента 2: {e}")
            
            # ✅ ЧИТАЕМ РЕЗУЛЬТАТЫ ОТ АГЕНТА 6 (МЕДИА)
            try:
                result_media = redis_client.lpop("queue:agent6:output")
                if result_media:
                    data = json.loads(result_media)
                    logger.info(f"📥 РЕЗУЛЬТАТ ОТ АГЕНТА 6: {data.get('media_type')} от @{data.get('username')}")
                    
                    # ✅ ПЕРЕДАЕМ CHAT_ID В notify_moderators
                    db_session = get_db_session()
                    await notify_moderators(
                        session=db_session,
                        message_text=f"📸 {data.get('media_type', 'media').upper()}: {data.get('caption', '')}",
                        message_link=data.get('message_link', ''),
                        user_id=data.get('user_id', 0),
                        username=data.get('username', 'unknown'),
                        verdict=data.get('verdict', False),
                        reason=data.get('reason', ''),
                        severity=data.get('severity', 0),
                        chat_id_str=str(data.get('chat_id', ''))  # ✅ КРИТИЧНО!
                    )
                    db_session.close()
            except Exception as e:
                logger.error(f"❌ Ошибка обработки результата агента 6: {e}")
            
            await asyncio.sleep(0.5)  # Не перегружаем CPU
            
        except Exception as e:
            logger.error(f"❌ Критическая ошибка в read_agent_results: {e}")
            await asyncio.sleep(1)

# ============================================================================
# СИСТЕМА МОДЕРАТОРОВ ПО ЧАТАМ
# ============================================================================

async def register_chat(user_id: int, username: str, chat_id: int, db_session):
    """✅ РЕГИСТРАЦИЯ ЧАТА И ВЛАДЕЛЬЦА"""
    try:
        chat = db_session.query(Chat).filter_by(tg_chat_id=str(chat_id)).first()
        
        if not chat:
            chat = Chat(
                tg_chat_id=str(chat_id),
                title=f"Chat {chat_id}",
                chat_type='group',
                is_active=True
            )
            db_session.add(chat)
            db_session.flush()
            logger.info(f"✅ Новый чат зарегистрирован: {chat_id}")
        
        moderator = db_session.query(Moderator).filter_by(
            chat_id=chat.id,
            tg_user_id=user_id
        ).first()
        
        if not moderator:
            moderator = Moderator(
                chat_id=chat.id,
                tg_user_id=user_id,
                username=username,
                is_owner=True,
                is_active=True
            )
            db_session.add(moderator)
            db_session.commit()
            logger.info(f"✅ Модератор {user_id} добавлен как ВЛАДЕЛЕЦ чата {chat_id}")
            return True, f"✅ Чат {chat_id} успешно зарегистрирован!\n🔑 Ты владелец чата."
        else:
            return False, f"⚠️ Чат {chat_id} уже зарегистрирован!"
            
    except Exception as e:
        logger.error(f"❌ Ошибка регистрации чата: {e}")
        db_session.rollback()
        return False, f"❌ Ошибка: {e}"

async def add_moderator(owner_user_id: int, new_mod_id: int, chat_id_str: str, db_session):
    """✅ ДОБАВИТЬ МОДЕРАТОРА К ЧАТУ (ТОЛЬКО ВЛАДЕЛЬЦУ)"""
    try:
        chat = db_session.query(Chat).filter_by(tg_chat_id=chat_id_str).first()
        if not chat:
            return False, "❌ Чат не зарегистрирован"
        
        owner = db_session.query(Moderator).filter_by(
            chat_id=chat.id,
            tg_user_id=owner_user_id,
            is_owner=True
        ).first()
        
        if not owner:
            return False, "❌ Ты не владелец этого чата"
        
        existing = db_session.query(Moderator).filter_by(
            chat_id=chat.id,
            tg_user_id=new_mod_id
        ).first()
        
        if existing:
            return False, "⚠️ Этот пользователь уже модератор"
        
        new_moderator = Moderator(
            chat_id=chat.id,
            tg_user_id=new_mod_id,
            is_owner=False,
            is_active=True
        )
        db_session.add(new_moderator)
        db_session.commit()
        
        logger.info(f"✅ Модератор {new_mod_id} добавлен к чату {chat_id_str}")
        return True, f"✅ Модератор {new_mod_id} добавлен!"
        
    except Exception as e:
        logger.error(f"❌ Ошибка добавления модератора: {e}")
        db_session.rollback()
        return False, f"❌ Ошибка: {e}"

# ============================================================================
# КОМАНДЫ (ПЕРВЫЕ! ВЫСШИЙ ПРИОРИТЕТ)
# ============================================================================

@dp.message(Command("register"))
async def register_command(message: types.Message):
    """Регистрация чата: /register CHAT_ID"""
    try:
        if message.chat.type != 'private':
            await message.answer("❌ Команда работает только в ЛС!")
            return
        
        args = message.text.split()
        if len(args) < 2:
            await message.answer(
                "📝 <b>Использование:</b> /register CHAT_ID\n\n"
                "Пример: /register -1001234567890\n\n"
                "1️⃣ Добавь бота в чат\n"
                "2️⃣ Напиши эту команду в ЛС",
                parse_mode="HTML"
            )
            return
        
        chat_id_str = args[1]
        db_session = get_db_session()
        
        success, message_text = await register_chat(
            user_id=message.from_user.id,
            username=message.from_user.username or f"user{message.from_user.id}",
            chat_id=int(chat_id_str),
            db_session=db_session
        )
        
        db_session.close()
        await message.answer(message_text, parse_mode="HTML")
            
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}", parse_mode="HTML")
        logger.error(f"❌ Ошибка команды /register: {e}")

@dp.message(Command("addmod"))
async def addmod_command(message: types.Message):
    """Добавить модератора: /addmod CHAT_ID MOD_ID"""
    try:
        if message.chat.type != 'private':
            await message.answer("❌ Команда работает только в ЛС!")
            return
        
        args = message.text.split()
        if len(args) < 3:
            await message.answer(
                "📝 <b>Использование:</b> /addmod CHAT_ID MOD_ID\n\n"
                "Пример: /addmod -1001234567890 987654321",
                parse_mode="HTML"
            )
            return
        
        chat_id_str = args[1]
        mod_id = int(args[2])
        
        db_session = get_db_session()
        success, response_text = await add_moderator(
            owner_user_id=message.from_user.id,
            new_mod_id=mod_id,
            chat_id_str=chat_id_str,
            db_session=db_session
        )
        db_session.close()
        
        await message.answer(response_text, parse_mode="HTML")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}", parse_mode="HTML")
        logger.error(f"❌ Ошибка команды /addmod: {e}")

@dp.message(Command("listmods"))
async def listmods_command(message: types.Message):
    """Список модераторов чата: /listmods CHAT_ID"""
    try:
        if message.chat.type != 'private':
            await message.answer("❌ Команда работает только в ЛС!")
            return
        
        args = message.text.split()
        if len(args) < 2:
            await message.answer("📝 Использование: /listmods CHAT_ID", parse_mode="HTML")
            return
        
        chat_id_str = args[1]
        db_session = get_db_session()
        
        moderators = get_chat_moderators(chat_id_str, db_session)
        db_session.close()
        
        if not moderators:
            await message.answer("❌ Модераторов не найдено", parse_mode="HTML")
            return
        
        text = f"<b>👥 Модераторы чата {chat_id_str}:</b>\n\n"
        for mod in moderators:
            crown = "👑" if mod.is_owner else "🛡️"
            text += f"{crown} ID: {mod.tg_user_id} (@{mod.username or 'unknown'})\n"
        
        await message.answer(text, parse_mode="HTML")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}", parse_mode="HTML")

@dp.message(Command("start"))
async def start_command(message: types.Message):
    """Команда /start"""
    if is_group_chat(message.chat.type):
        await message.answer("<b>🤖 TeleGuard Bot v3.0</b>\n\n✅ Бот готов к работе с 6 агентами!", parse_mode="HTML")
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статус агентов", callback_data="status_agents")],
        [InlineKeyboardButton(text="📨 Сообщения", callback_data="chat_messages")],
        [InlineKeyboardButton(text="⚠️ Нарушения", callback_data="negative_messages")],
        [InlineKeyboardButton(text="🖼️ Медиа файлы", callback_data="media_files")],
    ])
    
    welcome_text = (
        f"<b>🤖 TeleGuard Bot v3.0</b>\n\n"
        f"<b>Чат:</b> {message.chat.id}\n"
        f"<b>Тип:</b> {message.chat.type}\n\n"
        f"✅ <b>Активны 6 агентов:</b>\n"
        f"• 1-5: Текстовая модерация\n"
        f"• <b>6: 🖼️📹 Медиа анализ</b>"
    )
    
    await message.answer(welcome_text, reply_markup=keyboard, parse_mode="HTML")

# ============================================================================
# ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ
# ============================================================================

@dp.message(F.text)
async def handle_text_message(message: types.Message):
    """Обработчик текстовых сообщений → АГЕНТЫ 1-5"""
    try:
        if is_group_chat(message.chat.type):
            message_data = {
                "message": message.text,
                "user_id": message.from_user.id,
                "username": message.from_user.username or f"user{message.from_user.id}",
                "chat_id": message.chat.id,
                "message_id": message.message_id,
                "message_link": f"https://t.me/c/{str(message.chat.id).replace('-100', '')}/{message.message_id}"
            }

            db_session = get_db_session()
            save_message_to_db(message_data, db_session)
            
            if redis_client and not message.text.startswith('/'):
                await send_to_agent2(message_data)

            # ✅ ПРОСТАЯ ПРОВЕРКА НА МАТ (резерв)
            bad_words = ['хуй', 'пизда', 'блядь', 'хер', 'ебать', 'дерьмо', 'шлюха']
            message_lower = message.text.lower()
            
            if any(word in message_lower for word in bad_words):
                logger.warning(f"🚨 ПРОСТОЙ ФИЛЬТР: {message.text[:50]}...")
                await notify_moderators(
                    session=db_session,
                    message_text=message.text,
                    message_link=message_data['message_link'],
                    user_id=message.from_user.id,
                    username=message_data['username'],
                    verdict=True,
                    reason="🤬 Нецензурная лексика (простой фильтр)",
                    severity=70,
                    chat_id_str=str(message.chat.id)  # ✅ ВАЖНО!
                )

            db_session.close()
            logger.info(f"✅ Текст → Агенты 1-5: {message.text[:50]}...")

    except Exception as e:
        logger.error(f"❌ Ошибка обработки текста: {e}")

# ============================================================================
# ОБРАБОТЧИК ФОТО (АГЕНТ 6)
# ============================================================================

@dp.message(F.photo)
async def handle_photo_message(message: types.Message):
    """✅ ФОТО → АГЕНТ 6 (Mistral Vision)"""
    try:
        if not is_group_chat(message.chat.type):
            return
        
        photo = message.photo[-1]
        
        logger.info(f"📸 ФОТО получено: {photo.file_id}")
        
        try:
            file_info = await bot.get_file(photo.file_id)
            download_path = f"downloads/{photo.file_unique_id}.jpg"
            os.makedirs("downloads", exist_ok=True)
            await bot.download_file(file_info.file_path, download_path)
            logger.info(f"✅ Фото скачано: {download_path}")
        except Exception as e:
            logger.error(f"⚠️ Не удалось скачать фото: {e}")
            download_path = None
        
        media_data = {
            "media_type": "photo",
            "file_id": photo.file_id,
            "file_unique_id": photo.file_unique_id,
            "user_id": message.from_user.id,
            "username": message.from_user.username or message.from_user.first_name or "unknown",
            "chat_id": message.chat.id,
            "message_id": message.message_id,
            "message_link": f"https://t.me/c/{str(message.chat.id).replace('-100', '')}/{message.message_id}",
            "caption": message.caption or "",
            "file_size": photo.file_size,
            "mime_type": "image/jpeg",
            "local_path": download_path
        }
        
        db_session = get_db_session()
        save_media_to_db(media_data, db_session)
        await send_to_media_agent(media_data)
        db_session.close()
        
        logger.info(f"📸 ✅ ФОТО → АГЕНТ 6: @{media_data['username']}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка обработки фото: {e}")

# ============================================================================
# ОБРАБОТЧИК ВИДЕО (АГЕНТ 6)
# ============================================================================

@dp.message(F.video)
async def handle_video_message(message: types.Message):
    """✅ ВИДЕО → АГЕНТ 6"""
    try:
        if not is_group_chat(message.chat.type):
            return
        
        video = message.video
        media_data = {
            "media_type": "video",
            "file_id": video.file_id,
            "file_unique_id": video.file_unique_id,
            "filename": getattr(video, 'file_name', None),
            "file_size": video.file_size,
            "mime_type": video.mime_type or "video/mp4",
            "user_id": message.from_user.id,
            "username": message.from_user.username or message.from_user.first_name or "unknown",
            "chat_id": message.chat.id,
            "message_id": message.message_id,
            "message_link": f"https://t.me/c/{str(message.chat.id).replace('-100', '')}/{message.message_id}",
            "caption": message.caption or ""
        }
        
        db_session = get_db_session()
        save_media_to_db(media_data, db_session)
        await send_to_media_agent(media_data)
        db_session.close()
        
        logger.info(f"🎬 ✅ ВИДЕО → АГЕНТ 6: @{media_data['username']}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка обработки видео: {e}")

# ============================================================================
# ТОЧКА ВХОДА
# ============================================================================

async def main():
    """🚀 Запуск бота"""
    logger.info("=" * 80)
    logger.info("🚀 TeleGuard Bot v3.0 - СИСТЕМА МОДЕРАТОРОВ ПО ЧАТАМ!")
    logger.info("✅ Текст → Агенты 1-5")
    logger.info("✅ 🖼️📹 → АГЕНТ 6 (Mistral Vision)")
    logger.info("✅ МОДЕРАТОРЫ → По чатам (ИСПРАВЛЕНО!)")
    logger.info("=" * 80)
    logger.info(f"✅ Redis: {'✅' if redis_client else '❌'}")
    logger.info(f"✅ PostgreSQL: ✅")
    logger.info("=" * 80)
    
    # ✅ ЗАПУСКАЕМ ЗАДАЧУ ЧТЕНИЯ РЕЗУЛЬТАТОВ ОТ АГЕНТОВ
    asyncio.create_task(read_agent_results())
    
    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("\n❌ Бот остановлен")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
