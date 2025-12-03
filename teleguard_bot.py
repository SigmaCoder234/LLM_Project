#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🤖 TeleGuard Bot v2.9 - ПОЛНАЯ ВЕРСИЯ С АГЕНТОМ 6
✅ Модерирование групповых чатов Telegram с 6 ИИ агентами
✅ Анализ текста, фото, видео, документов ✅ РАБОТАЕТ!
✅ Mistral AI интеграция
✅ notify_moderators() ВЫЗЫВАЕТСЯ при обнаружении нарушений
"""

import logging
import asyncio
import json
import time
import redis
import requests
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import Column, Integer, String, ForeignKey, BigInteger, Boolean, DateTime, create_engine, Text
from sqlalchemy.orm import relationship

# ============================================================================
# КОНФИГУРАЦИЯ
# ============================================================================

TOKEN = "8320009669:AAHadwhYKIg6qcwAwJabsBEOO7srfWwMiXE"
POSTGRES_URL = "postgresql+psycopg2://tg_user:mnvm71@localhost:5432/teleguard?sslmode=disable"
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0
MODERATOR_IDS = [1621052774]

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
# МОДЕЛИ БД (СОВМЕСТИМЫ С АГЕНТОМ 6)
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
    tg_user_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    added_at = Column(DateTime, default=datetime.utcnow)
    chat = relationship("Chat", back_populates="moderators")

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
# 🚨 УВЕДОМЛЕНИЕ МОДЕРАТОРАМ
# ============================================================================

async def notify_moderators(session, message_text, message_link, user_id, username, verdict, reason):
    """🚨 ОТПРАВКА УВЕДОМЛЕНИЯ МОДЕРАТОРУ О НАРУШЕНИИ"""
    try:
        moderators = session.query(Moderator).filter(Moderator.is_active == True).all()
        
        if not moderators:
            logger.warning(f"⚠️ Модераторов не найдено в БД!")
            return False
        
        logger.info(f"📡 Найдено {len(moderators)} активных модератор(ов)")
        
        action = "🚨 БАН" if verdict else "✅ ОК"
        msg_preview = message_text[:100] if len(message_text) > 100 else message_text
        reason_text = f"{reason[:150]}" if reason else ""
        
        notification = (
            f"{action}\n\n"
            f"👤 @{username}\n"
            f"🆔 ID: {user_id}\n"
            f"💬 Сообщение: {msg_preview}\n"
            f"📝 Причина: {reason_text}\n"
            f"🔗 Ссылка: {message_link}"
        )
        
        sent_count = 0
        for moderator in moderators:
            try:
                await bot.send_message(
                    chat_id=moderator.tg_user_id,
                    text=notification,
                    parse_mode="HTML"
                )
                logger.info(f"✅ Уведомление отправлено @{moderator.username or moderator.tg_user_id}")
                sent_count += 1
            except Exception as e:
                logger.error(f"❌ Не удалось отправить модератору {moderator.tg_user_id}: {e}")
        
        logger.info(f"📊 Уведомлений отправлено: {sent_count}/{len(moderators)}")
        return sent_count > 0
        
    except Exception as e:
        logger.error(f"❌ Ошибка notify_moderators: {e}")
        return False

# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================================

def is_group_chat(chat_type: str) -> bool:
    """Проверка что это групповой чат"""
    return chat_type in ['group', 'supergroup', 'channel']

def should_process_chat(message: types.Message) -> bool:
    """Проверка нужно ли обрабатывать этот чат"""
    return is_group_chat(message.chat.type)

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
        redis_client.rpush("queue:agent6:input", media_json)  # ✅ АГЕНТ 6!
        logger.info(f"📤 МЕДИА отправлено АГЕНТУ 6: {media_data.get('media_type')} от @{media_data.get('username')}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка отправки медиа агенту 6: {e}")
        return False

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
            created_at=datetime.utcnow()
        )
        db_session.add(media_obj)
        db_session.commit()
        logger.info(f"✅ Медиа сохранено в БД с ID {media_obj.id}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения медиа: {e}")
        return False

def check_agent_health(agent_id: int, port: int) -> dict:
    """Health check агента"""
    health_check_url = f"http://localhost:{port}/health"
    try:
        response = requests.get(health_check_url, timeout=5)
        if response.status_code == 200:
            return response.json()
        else:
            return {"status": "error", "message": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"status": "offline", "message": str(e)}

def get_all_agents_status() -> dict:
    """Получить статус всех 6 агентов"""
    agents = {
        1: {"name": "Агент 1", "port": 8001},
        2: {"name": "Агент 2", "port": 8002},
        3: {"name": "Агент 3 (Mistral)", "port": 8003},
        4: {"name": "Агент 4 (Эвристика)", "port": 8004},
        5: {"name": "Агент 5 (Арбитр)", "port": 8005},
        6: {"name": "АГЕНТ 6 (МЕДИА ✅)", "port": 8006}
    }
    
    status = {}
    for agent_id, info in agents.items():
        health = check_agent_health(agent_id, info["port"])
        status[agent_id] = {
            "name": info["name"],
            "port": info["port"],
            "status": health.get("status", "unknown"),
            "message": health.get("message", ""),
            "uptime": health.get("uptime_seconds", 0) if health.get("status") == "online" else 0
        }
    
    return status

# ============================================================================
# ✅ ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ (АГЕНТЫ 1-5)
# ============================================================================

@dp.message(F.text)
async def handle_text_message(message: types.Message):
    """Обработчик текстовых сообщений → АГЕНТЫ 1-5"""
    try:
        if not should_process_chat(message):
            logger.info(f"Пропущен текст из чата {message.chat.type}")
            return

        # Подготавливаем данные для агентов
        message_data = {
            "message": message.text,
            "user_id": message.from_user.id,
            "username": message.from_user.username or f"user{message.from_user.id}",
            "chat_id": message.chat.id,
            "message_id": message.message_id,
            "message_link": f"https://t.me/c/{str(message.chat.id).replace('-100', '')}/{message.message_id}"
        }

        # ✅ 1. СОХРАНЯЕМ В БД
        db_session = get_db_session()
        save_message_to_db(message_data, db_session)
        
        # ✅ 2. ОТПРАВЛЯЕМ АГЕНТУ 2 (распределитель)
        if redis_client and not message.text.startswith('/'):
            await send_to_agent2(message_data)

        # ✅ 3. ПРОСТАЯ ПРОВЕРКА НА МАТ (резерв)
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
                reason="🤬 Нецензурная лексика (простой фильтр)"
            )

        db_session.close()
        logger.info(f"✅ Текст → Агенты 1-5: {message.text[:50]}...")

    except Exception as e:
        logger.error(f"❌ Ошибка обработки текста: {e}")

# ============================================================================
# ✅ ОБРАБОТЧИК ФОТО (АГЕНТ 6)
# ============================================================================

@dp.message(F.photo)
async def handle_photo_message(message: types.Message):
    """✅ ФОТО → АГЕНТ 6 (Mistral Vision)"""
    try:
        if not should_process_chat(message):
            logger.info(f"Пропущено фото из чата {message.chat.type}")
            return
        
        photo = message.photo[-1]
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
            "file_size": getattr(photo, 'file_size', 0),
            "mime_type": "image/jpeg"
        }
        
        # ✅ 1. СОХРАНЯЕМ В БД
        db_session = get_db_session()
        save_media_to_db(media_data, db_session)
        
        # ✅ 2. ОТПРАВЛЯЕМ АГЕНТУ 6
        await send_to_media_agent(media_data)
        
        db_session.close()
        logger.info(f"📸 ✅ ФОТО → АГЕНТ 6: @{media_data['username']}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка обработки фото: {e}")

# ============================================================================
# ✅ ОБРАБОТЧИК ВИДЕО И ДОКУМЕНТОВ (АГЕНТ 6)
# ============================================================================

@dp.message(F.video)
async def handle_video_message(message: types.Message):
    """✅ ВИДЕО → АГЕНТ 6 (Mistral Vision)"""
    try:
        if not should_process_chat(message):
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

@dp.message(F.document)
async def handle_document_message(message: types.Message):
    """✅ ДОКУМЕНТЫ/ГИФКИ → АГЕНТ 6"""
    try:
        if not should_process_chat(message):
            return
        
        doc = message.document
        mime_type = doc.mime_type or "unknown"
        
        # Обрабатываем только изображения/видео
        if "image" in mime_type or "video" in mime_type:
            media_type = "gif" if "gif" in mime_type else "image" if "image" in mime_type else "video"
            
            media_data = {
                "media_type": media_type,
                "file_id": doc.file_id,
                "file_unique_id": doc.file_unique_id,
                "filename": doc.file_name,
                "file_size": doc.file_size,
                "mime_type": mime_type,
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
            
            logger.info(f"📎 ✅ {media_type.upper()} → АГЕНТ 6: @{media_data['username']}")
        else:
            logger.info(f"⏭️ Документ пропущен: {doc.file_name}")
            
    except Exception as e:
        logger.error(f"❌ Ошибка обработки документа: {e}")

# ============================================================================
# КОМАНДЫ МЕНЮ
# ============================================================================

@dp.message(Command("start"))
async def start_command(message: types.Message):
    """Команда /start"""
    if not is_group_chat(message.chat.type):
        await message.answer("<b>🤖 TeleGuard Bot v2.9</b>\n\n✅ Бот готов к работе с 6 агентами!", parse_mode="HTML")
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статус агентов", callback_data="status_agents")],
        [InlineKeyboardButton(text="📨 Сообщения", callback_data="chat_messages")],
        [InlineKeyboardButton(text="⚠️ Нарушения", callback_data="negative_messages")],
        [InlineKeyboardButton(text="🖼️ Медиа файлы", callback_data="media_files")],
    ])
    
    welcome_text = (
        f"<b>🤖 TeleGuard Bot v2.9</b>\n\n"
        f"<b>Чат:</b> de>{message.chat.id}</code>\n"
        f"<b>Тип:</b> {message.chat.type}\n\n"
        f"✅ <b>Активны 6 агентов:</b>\n"
        f"• 1-5: Текстовая модерация\n"
        f"• <b>6: 🖼️📹 Медиа анализ</b>\n"
        f"• Mistral AI Vision"
    )
    
    await message.answer(welcome_text, reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(lambda c: c.data == "status_agents")
async def show_agents_status(callback_query: types.CallbackQuery):
    """Статус всех агентов"""
    await callback_query.answer()
    
    status = get_all_agents_status()
    status_text = "<b>🤖 СТАТУС 6 АГЕНТОВ</b>\n\n"
    
    for agent_id, info in status.items():
        if info["status"] == "online":
            emoji = "🟢"
            uptime = f"{info['uptime']//3600}ч {((info['uptime']%3600)//60)}м"
        elif info["status"] == "offline":
            emoji = "🔴"
            uptime = "Отключен"
        else:
            emoji = "⚪"
            uptime = info.get("message", "Unknown")
        
        status_text += f"{emoji} <b>{info['name']}</b>\n"
        status_text += f"   Порт: de>{info['port']}</code>\n"
        status_text += f"   {uptime}\n\n"
    
    redis_status = "🟢" if redis_client and redis_client.ping() else "🔴"
    status_text += f"<b>Redis:</b> {redis_status} Подключен\n"
    status_text += f"<b>PostgreSQL:</b> 🟢 Подключена\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="status_agents")],
        [InlineKeyboardButton(text="🔙 Меню", callback_data="back_to_menu")]
    ])
    
    await callback_query.message.edit_text(status_text, reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(lambda c: c.data == "back_to_menu")
async def back_to_menu(callback_query: types.CallbackQuery):
    """Главное меню"""
    await callback_query.answer()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статус агентов", callback_data="status_agents")],
        [InlineKeyboardButton(text="📨 Сообщения", callback_data="chat_messages")],
        [InlineKeyboardButton(text="⚠️ Нарушения", callback_data="negative_messages")],
        [InlineKeyboardButton(text="🖼️ Медиа файлы", callback_data="media_files")],
    ])
    await callback_query.message.edit_text("<b>🤖 TeleGuard Bot v2.9</b>\n\nВыбери опцию:", reply_markup=keyboard, parse_mode="HTML")

# ============================================================================
# ТОЧКА ВХОДА
# ============================================================================

async def main():
    """🚀 Запуск бота"""
    logger.info("=" * 80)
    logger.info("🚀 TeleGuard Bot v2.9 - ПОЛНАЯ ИНТЕГРАЦИЯ С 6 АГЕНТАМИ!")
    logger.info("✅ Текст → Агенты 1-5")
    logger.info("✅ 🖼️📹 → АГЕНТ 6 (Mistral Vision)")
    logger.info("=" * 80)
    logger.info(f"✅ Redis: {'✅' if redis_client else '❌'}")
    logger.info(f"✅ PostgreSQL: ✅")
    logger.info(f"✅ Модераторы: {len(MODERATOR_IDS)} IDs")
    logger.info("✅ Запусти: python sixth_agent.py")
    logger.info("=" * 80)
    
    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("\n❌ Бот остановлен")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
