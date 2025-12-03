#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TeleGuard - TELEGRAM BOT с поддержкой медиа (версия 2.6)
Добавлена обработка фото, видео, гифок и документов
"""

import logging
import asyncio
import json
import time
import redis
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String, ForeignKey, BigInteger, Boolean, DateTime, create_engine, Text
from sqlalchemy.orm import relationship, sessionmaker
import requests


async def safe_edit_message(callback_query, text, reply_markup=None, parse_mode="HTML"):
    """
    Безопасное редактирование сообщения с обработкой дублирования контента
    """
    try:
        await callback_query.message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        if "message is not modified" in str(e):
            await callback_query.answer("ℹ️ Данные актуальны", show_alert=False)
        else:
            raise e


# ============================================================================
# КОНФИГУРАЦИЯ
# ============================================================================
TOKEN = '8320009669:AAHiVLu-Em8EOXBNHYrJ0UhVX3mMMTm8S_g'
POSTGRES_URL = 'postgresql://tguser:mnvm7110@176.108.248.211:5432/teleguard_db?sslmode=disable'

# Redis конфигурация
REDIS_HOST = 'localhost'
REDIS_PORT = 6379
REDIS_DB = 0

# ============================================================================
# ЛОГИРОВАНИЕ
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [TELEGRAM BOT] %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ
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

    messages = relationship('Message', back_populates='chat', cascade="all, delete")
    moderators = relationship('Moderator', back_populates='chat', cascade="all, delete")
    negative_messages = relationship('NegativeMessage', back_populates='chat', cascade="all, delete")
    media_files = relationship('MediaFile', back_populates='chat', cascade="all, delete")


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


class MediaFile(Base):
    """✅ НОВАЯ ТАБЛИЦА: Таблица для хранения медиа файлов"""
    __tablename__ = 'media_files'

    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, ForeignKey('chats.id'), nullable=False)
    user_id = Column(BigInteger, nullable=False)
    username = Column(String)
    media_type = Column(String)  # photo, video, gif, document
    file_id = Column(String, unique=True, nullable=False)
    file_unique_id = Column(String)
    file_name = Column(String, nullable=True)
    file_size = Column(Integer, nullable=True)
    mime_type = Column(String, nullable=True)
    local_path = Column(String, nullable=True)
    message_id = Column(BigInteger, nullable=False)
    message_link = Column(String)
    caption = Column(Text, nullable=True)

    # Анализ медиа
    analysis_result = Column(Text, nullable=True)
    is_suspicious = Column(Boolean, default=False)
    suspension_reason = Column(Text, nullable=True)

    # Метаданные
    agent_id = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    analyzed_at = Column(DateTime, nullable=True)

    chat = relationship('Chat', back_populates='media_files')


# ============================================================================
# ИНИЦИАЛИЗАЦИЯ БД
# ============================================================================
engine = create_engine(POSTGRES_URL)
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)


def get_db_session():
    return SessionLocal()


# ============================================================================
# ИНИЦИАЛИЗАЦИЯ REDIS
# ============================================================================
try:
    redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
    redis_client.ping()
    logger.info(f"✅ Подключение к Redis успешно ({REDIS_HOST}:{REDIS_PORT})")
except Exception as e:
    logger.error(f"❌ Не удалось подключиться к Redis: {e}")
    redis_client = None


# ============================================================================
# ФУНКЦИЯ УВЕДОМЛЕНИЯ МОДЕРАТОРОВ (НОВАЯ!)
# ============================================================================

async def notify_moderators(session, message_text, message_link, user_id, username, verdict, reason=""):
    """
    Отправляет уведомление всем модераторам чата при обнаружении нарушений

    Args:
        session: SQLAlchemy сессия БД
        message_text: текст нарушительского сообщения
        message_link: ссылка на сообщение
        user_id: Telegram ID пользователя
        username: username пользователя (@username)
        verdict: True если БАН, False если предупреждение
        reason: причина нарушения
    """
    try:
        # Получаем всех модераторов из БД
        from sqlalchemy.orm import Session
        moderators = session.query(Moderator).filter(Moderator.is_active == True).all()

        if not moderators:
            logger.warning("⚠️ Модераторы не установлены в БД!")
            return

        # Формируем сообщение
        action = "🚨 БАН" if verdict else "⚠️ ПРЕДУПРЕЖДЕНИЕ"
        msg_preview = message_text[:100] if len(message_text) > 100 else message_text
        reason_text = f"\n📝 Причина: {reason[:150]}" if reason else ""

        notification = (
            f"{action}\n\n"
            f"👤 @{username}\n"
            f"🆔 ID: {user_id}\n"
            f"💬 Сообщение: {msg_preview}\n"
            f"{reason_text}\n"
            f"🔗 Ссылка: {message_link}"
        )

        # Отправляем каждому модератору
        for moderator in moderators:
            try:
                await bot.send_message(
                    chat_id=moderator.telegram_user_id,
                    text=notification,
                    parse_mode="HTML"
                )
                logger.info(f"✅ Уведомление отправлено модератору @{moderator.username} (ID: {moderator.telegram_user_id})")
            except Exception as e:
                logger.error(f"❌ Не удалось отправить уведомление модератору {moderator.telegram_user_id}: {e}")

    except Exception as e:
        logger.error(f"❌ Ошибка в notify_moderators: {e}")


# ============================================================================
# ФУНКЦИИ ФИЛЬТРАЦИИ
# ============================================================================
def is_group_chat(chat_type: str) -> bool:
    """Проверяет, является ли чат групповым"""
    return chat_type in ['group', 'supergroup', 'channel']


def should_process_chat(message: types.Message) -> bool:
    """Проверяет, нужно ли обрабатывать чат"""
    return is_group_chat(message.chat.type)


# ============================================================================
# ✅ ФУНКЦИИ РАБОТЫ С МЕДИА
# ============================================================================

async def send_to_media_agent(media_data: dict):
    """✅ Отправка медиа данных в Агент 6 через Redis"""
    try:
        if not redis_client:
            logger.error("❌ Redis не подключен")
            return False

        media_json = json.dumps(media_data, ensure_ascii=False)
        redis_client.rpush("queue:agent6:input", media_json)
        logger.info(f"📤 Медиа отправлено в Агент 6: {media_data.get('media_type')}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка отправки медиа в Агент 6: {e}")
        return False


def save_media_to_db(media_data: dict, db_session):
    """✅ Сохранение информации о медиа в БД"""
    try:
        # Получаем или создаём чат
        chat = db_session.query(Chat).filter_by(tg_chat_id=str(media_data['chat_id'])).first()
        if not chat:
            chat = Chat(
                tg_chat_id=str(media_data['chat_id']),
                title=f"Chat {media_data['chat_id']}",
                chat_type='group'
            )
            db_session.add(chat)
            db_session.commit()

        # Создаём запись о медиа файле
        media_obj = MediaFile(
            chat_id=chat.id,
            user_id=media_data['user_id'],
            username=media_data['username'],
            media_type=media_data['media_type'],
            file_id=media_data['file_id'],
            file_unique_id=media_data.get('file_unique_id'),
            file_name=media_data.get('file_name'),
            file_size=media_data.get('file_size'),
            mime_type=media_data.get('mime_type'),
            message_id=media_data['message_id'],
            message_link=media_data['message_link'],
            caption=media_data.get('caption', ''),
            created_at=datetime.utcnow()
        )

        db_session.add(media_obj)
        db_session.commit()
        logger.info(f"✅ Медиа сохранено в БД: ID {media_obj.id}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения медиа в БД: {e}")
        return False


# ============================================================================
# ✅ ОБРАБОТЧИКИ МЕДИА
# ============================================================================

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    """✅ Обработка фото из чата"""
    try:
        # Проверяем групповой чат
        if not should_process_chat(message):
            logger.info(f"Фото пропущено - не групповой чат ({message.chat.type})")
            return

        # Получаем самое большое фото
        photo = message.photo[-1]

        media_data = {
            "media_type": "photo",
            "file_id": photo.file_id,
            "file_unique_id": photo.file_unique_id,
            "user_id": message.from_user.id,
            "username": message.from_user.username or message.from_user.first_name,
            "chat_id": message.chat.id,
            "message_id": message.message_id,
            "message_link": f"https://t.me/c/{str(message.chat.id).replace('-100', '')}/{message.message_id}",
            "caption": message.caption or "",
            "timestamp": message.date.isoformat()
        }

        # Сохраняем в БД
        db_session = get_db_session()
        save_media_to_db(media_data, db_session)
        db_session.close()

        # Отправляем в Агент 6
        await send_to_media_agent(media_data)
        logger.info(f"📸 Фото от @{media_data['username']} обработано")

    except Exception as e:
        logger.error(f"❌ Ошибка обработки фото: {e}")


@dp.message(F.document)
async def handle_document(message: types.Message):
    """✅ Обработка документов (видео, гифки, файлы)"""
    try:
        # Проверяем групповой чат
        if not should_process_chat(message):
            logger.info(f"Документ пропущен - не групповой чат ({message.chat.type})")
            return

        doc = message.document

        # Определяем тип медиа по MIME type
        mime_type = doc.mime_type or "unknown"
        if "video" in mime_type:
            media_type = "video"
        elif "image" in mime_type or mime_type == "image/gif":
            media_type = "gif"
        else:
            media_type = "document"

        # Пропускаем документы которые не являются медиа
        if media_type == "document":
            logger.info(f"Документ пропущен (не медиа): {doc.file_name}")
            return

        media_data = {
            "media_type": media_type,
            "file_id": doc.file_id,
            "file_unique_id": doc.file_unique_id,
            "file_name": doc.file_name,
            "file_size": doc.file_size,
            "mime_type": mime_type,
            "user_id": message.from_user.id,
            "username": message.from_user.username or message.from_user.first_name,
            "chat_id": message.chat.id,
            "message_id": message.message_id,
            "message_link": f"https://t.me/c/{str(message.chat.id).replace('-100', '')}/{message.message_id}",
            "caption": message.caption or "",
            "timestamp": message.date.isoformat()
        }

        # Сохраняем в БД
        db_session = get_db_session()
        save_media_to_db(media_data, db_session)
        db_session.close()

        # Отправляем в Агент 6
        await send_to_media_agent(media_data)
        logger.info(f"📁 {media_type.upper()} от @{media_data['username']} обработано")

    except Exception as e:
        logger.error(f"❌ Ошибка обработки документа: {e}")


# ============================================================================
# ФУНКЦИИ ДЛЯ РАБОТЫ С АГЕНТАМИ
# ============================================================================
def check_agent_health(agent_id: int, port: int) -> dict:
    """Проверка health check агента"""
    try:
        url = f"http://localhost:{port}/health"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.json()
        else:
            return {"status": "error", "message": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"status": "offline", "message": str(e)}


def get_all_agents_status() -> dict:
    """Получает статус всех агентов (включая Агент 6)"""
    agents = {
        1: {"name": "Агент №1 (Координатор)", "port": 8001},
        2: {"name": "Агент №2 (Анализатор)", "port": 8002},
        3: {"name": "Агент №3 (Mistral AI Модератор)", "port": 8003},
        4: {"name": "Агент №4 (Эвристика + Mistral AI)", "port": 8004},
        5: {"name": "Агент №5 (Mistral AI Арбитр)", "port": 8005},
        6: {"name": "Агент №6 (Медиа анализатор)", "port": 8006}  # ✅ НОВЫЙ АГЕНТ
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


def test_agents_with_message(test_message: str, user_id: int, username: str, chat_id: int) -> dict:
    """Тестирует агенты 3, 4 и 5 с сообщением"""
    if not redis_client:
        return {"error": "Redis не подключен"}

    # Подготавливаем тестовые данные
    test_data = {
        "message": test_message,
        "rules": [
            "Запрещена расовая дискриминация",
            "Запрещены ссылки",
            "Запрещена нецензурная лексика и оскорбления"
        ],
        "user_id": user_id,
        "username": username,
        "chat_id": chat_id,
        "message_id": int(time.time()),
        "message_link": f"https://t.me/test/{int(time.time())}"
    }

    try:
        # Отправляем тестовое сообщение в очереди агентов 3 и 4
        test_json = json.dumps(test_data, ensure_ascii=False)
        redis_client.rpush("queue:agent3:input", test_json)
        redis_client.rpush("queue:agent4:input", test_json)

        logger.info(f"📤 Тестовое сообщение отправлено агентам 3 и 4")

        return {
            "results": "sent",
            "message_id": test_data["message_id"]
        }
    except Exception as e:
        logger.error(f"❌ Ошибка тестирования агентов: {e}")
        return {"error": str(e)}


# ============================================================================
# ФУНКЦИИ ДЛЯ РАБОТЫ С БД
# ============================================================================
def get_recent_messages(chat_id: int, limit: int = 10) -> list:
    """Получает последние сообщения из чата"""
    try:
        db_session = get_db_session()
        chat = db_session.query(Chat).filter_by(tg_chat_id=str(chat_id)).first()

        if not chat:
            db_session.close()
            return []

        if not is_group_chat(chat.chat_type):
            db_session.close()
            return []

        messages = db_session.query(Message).filter_by(chat_id=chat.id).order_by(
            Message.created_at.desc()
        ).limit(limit).all()

        result = []
        for msg in messages:
            result.append({
                "id": msg.id,
                "message_id": msg.message_id,
                "sender_username": msg.sender_username,
                "sender_id": msg.sender_id,
                "message_text": msg.message_text[:100] + "..." if (
                            msg.message_text and len(msg.message_text) > 100) else msg.message_text,
                "created_at": msg.created_at.strftime("%d.%m.%Y %H:%M:%S"),
                "ai_response": msg.ai_response[:50] + "..." if (
                            msg.ai_response and len(msg.ai_response) > 50) else msg.ai_response,
                "chat_id": chat_id,
                "chat_type": chat.chat_type
            })

        db_session.close()
        return result

    except Exception as e:
        logger.error(f"❌ Ошибка получения сообщений: {e}")
        return []


def get_negative_messages(chat_id: int, limit: int = 10) -> list:
    """Получает негативные сообщения из чата"""
    try:
        db_session = get_db_session()
        chat = db_session.query(Chat).filter_by(tg_chat_id=str(chat_id)).first()

        if not chat:
            db_session.close()
            return []

        if not is_group_chat(chat.chat_type):
            db_session.close()
            return []

        neg_messages = db_session.query(NegativeMessage).filter_by(chat_id=chat.id).order_by(
            NegativeMessage.created_at.desc()
        ).limit(limit).all()

        result = []
        for msg in neg_messages:
            result.append({
                "id": msg.id,
                "sender_username": msg.sender_username,
                "sender_id": msg.sender_id,
                "negative_reason": msg.negative_reason[:100] + "..." if (
                            msg.negative_reason and len(msg.negative_reason) > 100) else msg.negative_reason,
                "agent_id": msg.agent_id,
                "created_at": msg.created_at.strftime("%d.%m.%Y %H:%M:%S"),
                "is_sent_to_moderators": msg.is_sent_to_moderators,
                "chat_id": chat_id,
                "chat_type": chat.chat_type
            })

        db_session.close()
        return result

    except Exception as e:
        logger.error(f"❌ Ошибка получения негативных сообщений: {e}")
        return []


def add_chat_to_db(chat_id: int, title: str = None, chat_type: str = "group") -> bool:
    """Добавляет чат в БД"""
    if not is_group_chat(chat_type):
        logger.info(f"Чат {chat_id} пропущен - не групповой чат ({chat_type})")
        return False

    try:
        db_session = get_db_session()

        # Проверяем, есть ли уже такой чат
        existing_chat = db_session.query(Chat).filter_by(tg_chat_id=str(chat_id)).first()
        if existing_chat:
            db_session.close()
            return False

        # Создаем новый чат
        new_chat = Chat(
            tg_chat_id=str(chat_id),
            title=title or f"Чат {chat_id}",
            chat_type=chat_type,
            is_active=True
        )
        db_session.add(new_chat)
        db_session.commit()
        db_session.close()

        logger.info(f"✅ Чат {chat_id} добавлен: {title} - {chat_type}")
        return True

    except Exception as e:
        logger.error(f"❌ Ошибка добавления чата: {e}")
        return False


def add_moderator_to_chat(chat_id: int, user_id: int, username: str) -> bool:
    """Добавляет модератора в чат"""
    try:
        db_session = get_db_session()
        chat = db_session.query(Chat).filter_by(tg_chat_id=str(chat_id)).first()

        if not chat:
            db_session.close()
            return False

        if not is_group_chat(chat.chat_type):
            db_session.close()
            logger.info(f"Пропущен чат {chat_id} - не групповой чат ({chat.chat_type})")
            return False

        # Проверяем, есть ли уже модератор
        existing_mod = db_session.query(Moderator).filter_by(
            chat_id=chat.id,
            telegram_user_id=user_id
        ).first()

        if existing_mod:
            existing_mod.is_active = True
        else:
            # Добавляем нового модератора
            new_moderator = Moderator(
                chat_id=chat.id,
                username=username,
                telegram_user_id=user_id,
                is_active=True
            )
            db_session.add(new_moderator)

        db_session.commit()
        db_session.close()

        logger.info(f"✅ Модератор {username} добавлен в чат {chat_id}")
        return True

    except Exception as e:
        logger.error(f"❌ Ошибка добавления модератора: {e}")
        return False


# ============================================================================
# ОБРАБОТЧИКИ КОМАНД
# ============================================================================
@dp.message(Command("start"))
async def start_command(message: types.Message):
    """Команда /start"""
    if not is_group_chat(message.chat.type):
        await message.answer(
            "<b>TeleGuard Bot</b>\n\n"
            "<b>Ошибка:</b> Этот бот работает только в групповых чатах.",
            parse_mode="HTML"
        )
        return

    # Создаем клавиатуру
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Состояние агентов", callback_data="status_agents")],
        [InlineKeyboardButton(text="💬 Сообщения чата", callback_data="chat_messages")],
        [InlineKeyboardButton(text="⚠️ Нарушения", callback_data="negative_messages")],
        [InlineKeyboardButton(text="🧪 Тест агентов", callback_data="test_agents")],
        [InlineKeyboardButton(text="➕ Добавить чат", callback_data="add_chat")]
    ])

    welcome_text = (
        f"<b>🤖 TeleGuard Bot - Система модерации</b>\n\n"
        f"<b>📍 Чат:</b> {message.chat.title or 'Без названия'}\n"
        f"<b>🆔 ID:</b> <code>{message.chat.id}</code>\n"
        f"<b>📝 Тип:</b> {message.chat.type}\n\n"
        f"<b>🔧 Функции:</b>\n"
        f"• <b>📊 Состояние агентов</b> - проверка работы агентов 1-6\n"
        f"• <b>💬 Сообщения чата</b> - последние обработанные сообщения\n"
        f"• <b>⚠️ Нарушения</b> - найденные нарушения\n"
        f"• <b>🧪 Тест агентов</b> - тестирование с примерами\n"
        f"• <b>➕ Добавить чат</b> - регистрация для модерации\n\n"
        f"<i>🤖 Работает на Mistral AI + Агент 6 (медиа анализ)</i>"
    )

    await message.answer(welcome_text, reply_markup=keyboard, parse_mode="HTML")


# ============================================================================
# ОБРАБОТЧИКИ CALLBACK QUERY
# ============================================================================
@dp.callback_query(lambda c: c.data == "status_agents")
async def show_agents_status(callback_query: types.CallbackQuery):
    """Показывает состояние агентов"""
    await callback_query.answer()

    if not is_group_chat(callback_query.message.chat.type):
        await callback_query.message.edit_text("❌ Этот бот работает только в групповых чатах.")
        return

    status = get_all_agents_status()

    status_text = "<b>📊 Состояние агентов</b>\n\n"

    for agent_id, info in status.items():
        if info["status"] == "online":
            emoji = "🟢"
            uptime_hours = info["uptime"] // 3600
            uptime_minutes = (info["uptime"] % 3600) // 60
            details = f"⏱ {uptime_hours}ч {uptime_minutes}м"
        elif info["status"] == "offline":
            emoji = "🔴"
            details = "Не отвечает"
        else:
            emoji = "🟡"
            details = info.get("message", "Неизвестно")

        status_text += f"{emoji} <b>{info['name']}</b>\n"
        status_text += f"   🔌 Порт: {info['port']}\n"
        status_text += f"   📊 {details}\n\n"

    # Проверяем Redis
    if redis_client:
        try:
            redis_client.ping()
            redis_status = "🟢 Подключен"
        except:
            redis_status = "🔴 Ошибка"
    else:
        redis_status = "🔴 Не настроен"

    status_text += f"<b>📡 Redis:</b> {redis_status}\n"
    status_text += f"<b>🗄️ PostgreSQL:</b> 🟢 Подключен"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="status_agents")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

    await callback_query.message.edit_text(status_text, reply_markup=keyboard, parse_mode="HTML")


@dp.callback_query(lambda c: c.data == "chat_messages")
async def show_chat_messages(callback_query: types.CallbackQuery):
    """Показывает сообщения чата"""
    await callback_query.answer()

    if not is_group_chat(callback_query.message.chat.type):
        await callback_query.message.edit_text("❌ Этот бот работает только в групповых чатах.")
        return

    chat_id = callback_query.message.chat.id
    messages = get_recent_messages(chat_id, limit=5)

    if not messages:
        text = f"<b>💬 Сообщения чата {chat_id}</b>\n\n❌ Сообщений не найдено."
    else:
        text = f"<b>💬 Последние сообщения чата {chat_id}</b>\n\n"

        for i, msg in enumerate(messages, 1):
            text += f"<b>{i}.</b> <b>@{msg['sender_username'] or 'unknown'}</b>:\n"
            text += f"   📝 {msg['message_text'] or 'Пустое сообщение'}\n"
            text += f"   📅 {msg['created_at']}\n"
            if msg['ai_response']:
                text += f"   🤖 {msg['ai_response']}\n"
            text += "\n"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="chat_messages")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

    await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


@dp.callback_query(lambda c: c.data == "negative_messages")
async def show_negative_messages(callback_query: types.CallbackQuery):
    """Показывает нарушения"""
    await callback_query.answer()

    if not is_group_chat(callback_query.message.chat.type):
        await callback_query.message.edit_text("❌ Этот бот работает только в групповых чатах.")
        return

    chat_id = callback_query.message.chat.id
    neg_messages = get_negative_messages(chat_id, limit=5)

    if not neg_messages:
        text = f"<b>⚠️ Нарушения в чате {chat_id}</b>\n\n✅ Нарушений не найдено."
    else:
        text = f"<b>⚠️ Последние нарушения в чате {chat_id}</b>\n\n"

        for i, msg in enumerate(neg_messages, 1):
            agent_name = f"Агент #{msg['agent_id']}" if msg['agent_id'] else "Неизвестный агент"
            sent_status = "✅ Отправлено" if msg['is_sent_to_moderators'] else "⏳ В обработке"

            text += f"<b>{i}.</b> <b>@{msg['sender_username'] or 'unknown'}</b>:\n"
            text += f"   ⚠️ {msg['negative_reason'] or 'Причина не указана'}\n"
            text += f"   🤖 {agent_name}\n"
            text += f"   📬 {sent_status}\n"
            text += f"   📅 {msg['created_at']}\n\n"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="negative_messages")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

    await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


@dp.callback_query(lambda c: c.data == "test_agents")
async def test_agents_menu(callback_query: types.CallbackQuery):
    """Меню тестирования агентов"""
    await callback_query.answer()

    if not is_group_chat(callback_query.message.chat.type):
        await callback_query.message.edit_text("❌ Этот бот работает только в групповых чатах.")
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Нормальное сообщение", callback_data="test_normal")],
        [InlineKeyboardButton(text="🤬 Мат и оскорбления", callback_data="test_profanity")],
        [InlineKeyboardButton(text="📢 Спам со ссылкой", callback_data="test_spam")],
        [InlineKeyboardButton(text="⚡ Расовая дискриминация", callback_data="test_discrimination")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

    text = (
        "<b>🧪 Тестирование агентов</b>\n\n"
        "<b>Выберите тип тестового сообщения:</b>\n\n"
        "• <b>✅ Нормальное</b> - обычное безопасное сообщение\n"
        "• <b>🤬 Мат</b> - сообщение с нецензурной лексикой\n"
        "• <b>📢 Спам</b> - рекламное сообщение со ссылкой\n"
        "• <b>⚡ Дискриминация</b> - расово дискриминационное сообщение\n\n"
        "<i>Сообщения будут отправлены агентам 3, 4 и 5 для анализа.</i>"
    )

    await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


@dp.callback_query(lambda c: c.data == "add_chat")
async def add_chat_menu(callback_query: types.CallbackQuery):
    """Добавление чата в систему"""
    await callback_query.answer()

    if not is_group_chat(callback_query.message.chat.type):
        text = (
            f"<b>❌ Ошибка добавления чата</b>\n\n"
            f"TeleGuard Bot работает только в <b>групповых чатах</b>.\n\n"
            f"<b>🆔 ID:</b> <code>{callback_query.message.chat.id}</code>\n"
            f"<b>📝 Тип:</b> {callback_query.message.chat.type}\n\n"
            f"Добавьте бота в групповой чат и повторите попытку."
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
        ])

        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        return

    chat_id = callback_query.message.chat.id
    chat_title = getattr(callback_query.message.chat, 'title', f"Чат {chat_id}")
    chat_type = callback_query.message.chat.type

    # Пытаемся добавить чат
    success = add_chat_to_db(chat_id, chat_title, chat_type)

    if success:
        # Добавляем пользователя как модератора
        user_id = callback_query.from_user.id
        username = callback_query.from_user.username or f"user{user_id}"
        add_moderator_to_chat(chat_id, user_id, username)

        text = (
            f"<b>✅ Чат успешно добавлен!</b>\n\n"
            f"<b>📍 Название:</b> {chat_title}\n"
            f"<b>🆔 ID:</b> <code>{chat_id}</code>\n"
            f"<b>📝 Тип:</b> {chat_type}\n"
            f"<b>👤 Модератор:</b> @{username}\n\n"
            f"Теперь TeleGuard будет модерировать этот чат (включая медиа)."
        )
    else:
        text = (
            f"<b>⚠️ Чат уже зарегистрирован</b>\n\n"
            f"<b>📍 Название:</b> {chat_title}\n"
            f"<b>🆔 ID:</b> <code>{chat_id}</code>\n"
            f"<b>📝 Тип:</b> {chat_type}\n\n"
            f"Этот чат уже находится под защитой TeleGuard."
        )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

    await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


# ============================================================================
# ОБРАБОТЧИКИ ТЕСТОВЫХ СООБЩЕНИЙ
# ============================================================================
@dp.callback_query(lambda c: c.data == "test_normal")
async def test_normal_message(callback_query: types.CallbackQuery):
    await run_agent_test(callback_query, "Привет всем! Как дела?", "Нормальное сообщение")


@dp.callback_query(lambda c: c.data == "test_profanity")
async def test_profanity_message(callback_query: types.CallbackQuery):
    await run_agent_test(callback_query, "Ты дурак и идиот! Хуй тебе!", "Мат и оскорбления")


@dp.callback_query(lambda c: c.data == "test_spam")
async def test_spam_message(callback_query: types.CallbackQuery):
    await run_agent_test(callback_query, "Переходи по ссылке t.me/spam_channel! Заработок от 100$ в день!",
                         "Спам со ссылкой")


@dp.callback_query(lambda c: c.data == "test_discrimination")
async def test_discrimination_message(callback_query: types.CallbackQuery):
    await run_agent_test(callback_query, "Все эти негры должны убираться отсюда!", "Расовая дискриминация")


async def run_agent_test(callback_query: types.CallbackQuery, test_message: str, test_type: str):
    """Запускает тест агентов с сообщением"""
    await callback_query.answer()

    if not is_group_chat(callback_query.message.chat.type):
        await callback_query.message.edit_text("❌ Этот бот работает только в групповых чатах.")
        return

    # Показываем процесс тестирования
    await callback_query.message.edit_text(
        f"<b>🧪 Тестирование: {test_type}</b>\n\n"
        f"<b>📝 Сообщение:</b>\n<i>{test_message}</i>\n\n"
        f"⏳ Отправляем агентам 3, 4 и 5...",
        parse_mode="HTML"
    )

    # Запускаем тест
    user_id = callback_query.from_user.id
    username = callback_query.from_user.username or "test_user"
    chat_id = callback_query.message.chat.id

    result = test_agents_with_message(test_message, user_id, username, chat_id)

    if "error" in result:
        result_text = f"<b>❌ Ошибка тестирования</b>\n\n{result['error']}"
    else:
        result_text = (
            f"<b>✅ Тест запущен!</b>\n\n"
            f"<b>📝 Тип:</b> {test_type}\n"
            f"<b>💬 Сообщение:</b>\n<i>{test_message[:100]}{'...' if len(test_message) > 100 else ''}</i>\n\n"
            f"<b>🆔 ID теста:</b> <code>{result.get('message_id', 'N/A')}</code>\n\n"
            f"Сообщение отправлено агентам 3, 4 и 5 для анализа.\n"
            f"Результаты будут видны в разделе \"Нарушения\" через несколько секунд."
        )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚠️ Посмотреть нарушения", callback_data="negative_messages")],
        [InlineKeyboardButton(text="🧪 Другие тесты", callback_data="test_agents")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

    await callback_query.message.edit_text(result_text, reply_markup=keyboard, parse_mode="HTML")


@dp.callback_query(lambda c: c.data == "back_to_menu")
async def back_to_menu(callback_query: types.CallbackQuery):
    """Возврат в главное меню"""
    await callback_query.answer()

    if not is_group_chat(callback_query.message.chat.type):
        await callback_query.message.edit_text(
            "<b>TeleGuard Bot</b>\n\n"
            "<b>Ошибка:</b> Этот бот работает только в групповых чатах.",
            parse_mode="HTML"
        )
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Состояние агентов", callback_data="status_agents")],
        [InlineKeyboardButton(text="💬 Сообщения чата", callback_data="chat_messages")],
        [InlineKeyboardButton(text="⚠️ Нарушения", callback_data="negative_messages")],
        [InlineKeyboardButton(text="🧪 Тест агентов", callback_data="test_agents")],
        [InlineKeyboardButton(text="➕ Добавить чат", callback_data="add_chat")]
    ])

    chat_title = getattr(callback_query.message.chat, 'title', "Без названия")

    welcome_text = (
        f"<b>🤖 TeleGuard Bot - Система модерации</b>\n\n"
        f"<b>📍 Чат:</b> {chat_title}\n"
        f"<b>🆔 ID:</b> <code>{callback_query.message.chat.id}</code>\n"
        f"<b>📝 Тип:</b> {callback_query.message.chat.type}\n\n"
        f"<b>🔧 Функции:</b>\n"
        f"• <b>📊 Состояние агентов</b> - проверка работы агентов 1-6\n"
        f"• <b>💬 Сообщения чата</b> - последние обработанные сообщения\n"
        f"• <b>⚠️ Нарушения</b> - найденные нарушения\n"
        f"• <b>🧪 Тест агентов</b> - тестирование с примерами\n"
        f"• <b>➕ Добавить чат</b> - регистрация для модерации\n\n"
        f"<i>🤖 Работает на Mistral AI + Агент 6 (медиа анализ)</i>"
    )

    await callback_query.message.edit_text(welcome_text, reply_markup=keyboard, parse_mode="HTML")


# ============================================================================
# ОБРАБОТЧИК СООБЩЕНИЙ (ОСНОВНАЯ ЛОГИКА)
# ============================================================================
@dp.message()
async def handle_message(message: types.Message):
    """Обработчик всех сообщений"""
    try:
        # Добавляем чат в БД если его нет
        db_session = get_db_session()
        chat = db_session.query(Chat).filter_by(tg_chat_id=str(message.chat.id)).first()
        if not chat:
            chat = Chat(
                tg_chat_id=str(message.chat.id),
                title=getattr(message.chat, 'title', None),
                chat_type=message.chat.type
            )
            db_session.add(chat)
            db_session.commit()

        # Обрабатываем только групповые чаты
        if not should_process_chat(message):
            logger.info(f"Пропущен чат {message.chat.id} - не групповой")
            db_session.close()
            return

        # Отправляем сообщение в очередь агента 1 через Redis
        if redis_client and message.text and not message.text.startswith('/'):
            test_data = {
                "message": message.text,
                "user_id": message.from_user.id,
                "username": message.from_user.username or f"user{message.from_user.id}",
                "chat_id": message.chat.id,
                "message_id": message.message_id,
                "message_link": f"https://t.me/c/{str(message.chat.id).replace('-100', '')}/{message.message_id}"
            }

            test_json = json.dumps(test_data, ensure_ascii=False)
            redis_client.rpush("queue:agent1:input", test_json)
            logger.info(f"📤 Сообщение от {message.chat.id} отправлено агенту 1")

        # Сохраняем сообщение в БД
        msg = Message(
            chat_id=chat.id,
            message_id=message.message_id,
            sender_username=message.from_user.username,
            sender_id=message.from_user.id,
            message_text=message.text,
            message_link=f"https://t.me/c/{str(message.chat.id).replace('-100', '')}/{message.message_id}"
        )
        db_session.add(msg)
        db_session.commit()

        db_session.close()

        logger.info(
            f"✅ Обработано сообщение из чата {message.chat.id}: {message.text[:50] if message.text else 'No text'}...")

    except Exception as e:
        logger.error(f"❌ Ошибка обработки сообщения: {e}")


# ============================================================================
# ПРОВЕРКА ПОДКЛЮЧЕНИЙ
# ============================================================================
async def startup_checks():
    """Проверки при запуске"""
    try:
        db_session = get_db_session()
        db_session.close()
        logger.info("✅ Подключение к PostgreSQL успешно")
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к PostgreSQL: {e}")


# ============================================================================
# ГЛАВНАЯ ФУНКЦИЯ
# ============================================================================
async def main():
    logger.info("🚀 Запуск TeleGuard Bot (версия 2.6 - с поддержкой медиа)...")

    # Проверки при запуске
    await startup_checks()

    # Запуск бота
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())