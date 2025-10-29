#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TELEGRAM BOT с управлением агентами и тестированием (Исправлено - только групповые чаты)
"""

import logging
import asyncio
import json
import time
import redis
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String, ForeignKey, BigInteger, Boolean, DateTime, create_engine, Text
from sqlalchemy.orm import relationship, sessionmaker
import requests

# ============================================================================
# НАСТРОЙКИ
# ============================================================================
TOKEN = '8320009669:AAHiVLu-Em8EOXBNHYrJ0UhVX3mMMTm8S_g'
POSTGRES_URL = 'postgresql://tguser:mnvm7110@176.108.248.211:5432/teleguard_db?sslmode=disable'

# REDIS настройки
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [TELEGRAM BOT] %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN)
dp = Dispatcher()
Base = declarative_base()

# ============================================================================
# МОДЕЛИ БД (ОДИНАКОВЫЕ С АГЕНТАМИ)
# ============================================================================
class Chat(Base):
    __tablename__ = 'chats'
    id = Column(Integer, primary_key=True)
    tg_chat_id = Column(String, unique=True, nullable=False)
    title = Column(String, nullable=True)
    chat_type = Column(String, default='group')
    added_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    
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

# Подключение к Redis
try:
    redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
    redis_client.ping()
    logger.info(f"✅ Подключение к Redis успешно: {REDIS_HOST}:{REDIS_PORT}")
except Exception as e:
    logger.error(f"❌ Не удалось подключиться к Redis: {e}")
    redis_client = None

# ============================================================================
# ФУНКЦИИ ПРОВЕРКИ ТИПА ЧАТА
# ============================================================================
def is_group_chat(chat_type: str) -> bool:
    """Проверяет, является ли чат групповым"""
    return chat_type in ['group', 'supergroup', 'channel']

def should_process_chat(message: types.Message) -> bool:
    """Определяет, нужно ли обрабатывать сообщение из этого чата"""
    return is_group_chat(message.chat.type)

# ============================================================================
# ФУНКЦИИ ПРОВЕРКИ СОСТОЯНИЯ АГЕНТОВ
# ============================================================================
def check_agent_health(agent_id: int, port: int) -> dict:
    """Проверка состояния агента через health check"""
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
    """Получить статус всех агентов"""
    agents = {
        1: {"name": "Агент №1 (Координатор)", "port": 8001},
        2: {"name": "Агент №2 (Анализатор)", "port": 8002},
        3: {"name": "Агент №3 (GigaChat)", "port": 8003},
        4: {"name": "Агент №4 (Эвристический)", "port": 8004},
        5: {"name": "Агент №5 (Арбитр)", "port": 8005}
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
# ФУНКЦИИ ТЕСТИРОВАНИЯ АГЕНТОВ
# ============================================================================
def test_agents_with_message(test_message: str, user_id: int, username: str, chat_id: int) -> dict:
    """Тестирование агентов 3.2, 4 и 5 с сообщением"""
    if not redis_client:
        return {"error": "Redis не подключен"}
    
    # Подготавливаем тестовые данные
    test_data = {
        "message": test_message,
        "rules": [
            "Запрещена реклама сторонних сообществ",
            "Запрещены нецензурные выражения и оскорбления",
            "Запрещена дискриминация по любым признакам",
            "Запрещен спам и флуд"
        ],
        "user_id": user_id,
        "username": username,
        "chat_id": chat_id,
        "message_id": int(time.time()),  # Уникальный ID сообщения
        "message_link": f"https://t.me/test/{int(time.time())}"
    }
    
    try:
        # Отправляем в очереди агентов 3 и 4 НАПРЯМУЮ (минуя агент 1 и 2 для тестов)
        test_json = json.dumps(test_data, ensure_ascii=False)
        
        redis_client.rpush("queue:agent3:input", test_json)
        redis_client.rpush("queue:agent4:input", test_json)
        
        logger.info(f"📤 Тестовое сообщение отправлено агентам 3 и 4")
        
        results = {"sent": True, "message_id": test_data["message_id"]}
        
        return results
        
    except Exception as e:
        logger.error(f"❌ Ошибка тестирования агентов: {e}")
        return {"error": str(e)}

# ============================================================================
# ФУНКЦИИ РАБОТЫ С СООБЩЕНИЯМИ ИЗ БД (ТОЛЬКО ГРУППОВЫЕ ЧАТЫ)
# ============================================================================
def get_recent_messages(chat_id: int, limit: int = 10) -> list:
    """Получить последние сообщения из КОНКРЕТНОГО ГРУППОВОГО чата"""
    try:
        db_session = get_db_session()
        
        chat = db_session.query(Chat).filter_by(tg_chat_id=str(chat_id)).first()
        if not chat:
            return []
        
        # Проверяем, что это групповой чат
        if not is_group_chat(chat.chat_type):
            db_session.close()
            return []
        
        # Фильтруем сообщения только из ЭТОГО группового чата
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
                "message_text": msg.message_text[:100] + "..." if len(msg.message_text or "") > 100 else msg.message_text,
                "created_at": msg.created_at.strftime("%d.%m.%Y %H:%M:%S"),
                "ai_response": msg.ai_response[:50] + "..." if msg.ai_response and len(msg.ai_response) > 50 else msg.ai_response,
                "chat_id": chat_id,
                "chat_type": chat.chat_type
            })
        
        db_session.close()
        return result
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения сообщений: {e}")
        return []

def get_negative_messages(chat_id: int, limit: int = 10) -> list:
    """Получить негативные сообщения из КОНКРЕТНОГО ГРУППОВОГО чата"""
    try:
        db_session = get_db_session()
        
        chat = db_session.query(Chat).filter_by(tg_chat_id=str(chat_id)).first()
        if not chat:
            return []
        
        # Проверяем, что это групповой чат
        if not is_group_chat(chat.chat_type):
            db_session.close()
            return []
        
        # Фильтруем негативные сообщения только из ЭТОГО группового чата
        neg_messages = db_session.query(NegativeMessage).filter_by(chat_id=chat.id).order_by(
            NegativeMessage.created_at.desc()
        ).limit(limit).all()
        
        result = []
        for msg in neg_messages:
            result.append({
                "id": msg.id,
                "sender_username": msg.sender_username,
                "sender_id": msg.sender_id,
                "negative_reason": msg.negative_reason[:100] + "..." if len(msg.negative_reason or "") > 100 else msg.negative_reason,
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

# ============================================================================
# ФУНКЦИИ УПРАВЛЕНИЯ ЧАТАМИ И МОДЕРАТОРАМИ (ТОЛЬКО ГРУППОВЫЕ ЧАТЫ)
# ============================================================================
def add_chat_to_db(chat_id: int, title: str = None, chat_type: str = "group") -> bool:
    """Добавить новый ГРУППОВОЙ чат в базу данных"""
    # Проверяем, что это групповой чат
    if not is_group_chat(chat_type):
        logger.info(f"❌ Чат {chat_id} не добавлен - это не групповой чат (тип: {chat_type})")
        return False
    
    try:
        db_session = get_db_session()
        
        # Проверяем, существует ли уже такой чат
        existing_chat = db_session.query(Chat).filter_by(tg_chat_id=str(chat_id)).first()
        if existing_chat:
            db_session.close()
            return False  # Чат уже существует
        
        # Создаем новый групповой чат
        new_chat = Chat(
            tg_chat_id=str(chat_id),
            title=title or f"Групповой чат {chat_id}",
            chat_type=chat_type,
            is_active=True
        )
        
        db_session.add(new_chat)
        db_session.commit()
        db_session.close()
        
        logger.info(f"✅ Добавлен новый групповой чат: {chat_id} ({title}) - тип: {chat_type}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка добавления чата: {e}")
        return False

def add_moderator_to_chat(chat_id: int, user_id: int, username: str) -> bool:
    """Добавить модератора к ГРУППОВОМУ чату"""
    try:
        db_session = get_db_session()
        
        chat = db_session.query(Chat).filter_by(tg_chat_id=str(chat_id)).first()
        if not chat:
            db_session.close()
            return False
        
        # Проверяем, что это групповой чат
        if not is_group_chat(chat.chat_type):
            db_session.close()
            logger.info(f"❌ Модератор не добавлен - это не групповой чат (тип: {chat.chat_type})")
            return False
        
        # Проверяем, не является ли пользователь уже модератором
        existing_mod = db_session.query(Moderator).filter_by(
            chat_id=chat.id, telegram_user_id=user_id
        ).first()
        
        if existing_mod:
            existing_mod.is_active = True  # Реактивируем, если был деактивирован
        else:
            new_moderator = Moderator(
                chat_id=chat.id,
                username=username,
                telegram_user_id=user_id,
                is_active=True
            )
            db_session.add(new_moderator)
        
        db_session.commit()
        db_session.close()
        
        logger.info(f"✅ Добавлен модератор @{username} для группового чата {chat_id}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка добавления модератора: {e}")
        return False

# ============================================================================
# TELEGRAM BOT HANDLERS
# ============================================================================

@dp.message(Command('start'))
async def start_command(message: types.Message):
    """Команда /start"""
    # Проверяем тип чата
    if not is_group_chat(message.chat.type):
        await message.answer(
            "🤖 <b>TeleGuard Bot</b>\n\n"
            "ℹ️ Этот бот работает только в <b>групповых чатах</b>.\n"
            "Добавьте меня в групповой чат для модерации сообщений.",
            parse_mode='HTML'
        )
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Состояние агентов", callback_data="status_agents")],
        [InlineKeyboardButton(text="📝 Сообщения чата", callback_data="chat_messages")],
        [InlineKeyboardButton(text="⚠️ Негативные сообщения", callback_data="negative_messages")],
        [InlineKeyboardButton(text="🧪 Тест агентов", callback_data="test_agents")],
        [InlineKeyboardButton(text="➕ Добавить чат", callback_data="add_chat")]
    ])
    
    welcome_text = f"""
🤖 <b>TeleGuard Bot - Многоагентная система модерации</b>

📋 <b>Групповой чат:</b> {message.chat.title or 'Без названия'}
🆔 <b>ID чата:</b> {message.chat.id}
📊 <b>Тип:</b> {message.chat.type}

Доступные функции:
📊 <b>Состояние агентов</b> - проверка работы всех агентов (1-5)
📝 <b>Сообщения чата</b> - последние сообщения из этого чата
⚠️ <b>Негативные сообщения</b> - найденные нарушения в этом чате
🧪 <b>Тест агентов</b> - проверка работы системы модерации
➕ <b>Добавить чат</b> - регистрация этого чата для модерации

<i>Выберите действие из меню ниже:</i>
    """
    
    await message.answer(welcome_text, reply_markup=keyboard, parse_mode='HTML')

@dp.callback_query(lambda c: c.data == "status_agents")
async def show_agents_status(callback_query: types.CallbackQuery):
    """Показать состояние агентов"""
    await callback_query.answer()
    
    # Проверяем тип чата
    if not is_group_chat(callback_query.message.chat.type):
        await callback_query.message.edit_text(
            "ℹ️ Эта функция доступна только в групповых чатах."
        )
        return
    
    status = get_all_agents_status()
    
    status_text = "📊 <b>Состояние агентов:</b>\n\n"
    
    for agent_id, info in status.items():
        if info["status"] == "online":
            emoji = "🟢"
            uptime_hours = info["uptime"] // 3600
            uptime_minutes = (info["uptime"] % 3600) // 60
            details = f"Работает {uptime_hours}ч {uptime_minutes}м"
        elif info["status"] == "offline":
            emoji = "🔴"
            details = "Не отвечает"
        else:
            emoji = "🟡"
            details = info.get("message", "Неизвестно")
        
        status_text += f"{emoji} <b>{info['name']}</b>\n"
        status_text += f"   Порт: {info['port']}\n"
        status_text += f"   Статус: {details}\n\n"
    
    # Проверяем Redis
    if redis_client:
        try:
            redis_client.ping()
            redis_status = "🟢 Подключен"
        except:
            redis_status = "🔴 Ошибка"
    else:
        redis_status = "🔴 Не подключен"
    
    status_text += f"📡 <b>Redis:</b> {redis_status}\n"
    status_text += f"🗄️ <b>PostgreSQL:</b> 🟢 Подключен"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="status_agents")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])
    
    await callback_query.message.edit_text(status_text, reply_markup=keyboard, parse_mode='HTML')

@dp.callback_query(lambda c: c.data == "chat_messages")
async def show_chat_messages(callback_query: types.CallbackQuery):
    """Показать сообщения ЭТОГО ГРУППОВОГО чата"""
    await callback_query.answer()
    
    # Проверяем тип чата
    if not is_group_chat(callback_query.message.chat.type):
        await callback_query.message.edit_text(
            "ℹ️ Эта функция доступна только в групповых чатах."
        )
        return
    
    chat_id = callback_query.message.chat.id
    messages = get_recent_messages(chat_id, limit=5)
    
    if not messages:
        text = f"📝 <b>Сообщения группового чата {chat_id}:</b>\n\nСообщений в базе данных не найдено."
    else:
        text = f"📝 <b>Последние сообщения из группового чата {chat_id}:</b>\n\n"
        
        for i, msg in enumerate(messages, 1):
            text += f"<b>{i}.</b> @{msg['sender_username'] or 'unknown'}\n"
            text += f"   💬 {msg['message_text'] or 'Пустое сообщение'}\n"
            text += f"   🕐 {msg['created_at']}\n"
            if msg['ai_response']:
                text += f"   🤖 {msg['ai_response']}\n"
            text += "\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="chat_messages")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])
    
    await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode='HTML')

@dp.callback_query(lambda c: c.data == "negative_messages")
async def show_negative_messages(callback_query: types.CallbackQuery):
    """Показать негативные сообщения ЭТОГО ГРУППОВОГО чата"""
    await callback_query.answer()
    
    # Проверяем тип чата
    if not is_group_chat(callback_query.message.chat.type):
        await callback_query.message.edit_text(
            "ℹ️ Эта функция доступна только в групповых чатах."
        )
        return
    
    chat_id = callback_query.message.chat.id
    neg_messages = get_negative_messages(chat_id, limit=5)
    
    if not neg_messages:
        text = f"⚠️ <b>Негативные сообщения группового чата {chat_id}:</b>\n\nНарушений не найдено."
    else:
        text = f"⚠️ <b>Найденные нарушения в групповом чате {chat_id}:</b>\n\n"
        
        for i, msg in enumerate(neg_messages, 1):
            agent_name = f"Агент #{msg['agent_id']}" if msg['agent_id'] else "Неизвестно"
            sent_status = "✅ Отправлено" if msg['is_sent_to_moderators'] else "⏳ Ожидает"
            
            text += f"<b>{i}.</b> @{msg['sender_username'] or 'unknown'}\n"
            text += f"   🚫 {msg['negative_reason'] or 'Нет причины'}\n"
            text += f"   🤖 {agent_name}\n"
            text += f"   📨 {sent_status}\n"
            text += f"   🕐 {msg['created_at']}\n\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="negative_messages")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])
    
    await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode='HTML')

@dp.callback_query(lambda c: c.data == "test_agents")
async def test_agents_menu(callback_query: types.CallbackQuery):
    """Меню тестирования агентов"""
    await callback_query.answer()
    
    # Проверяем тип чата
    if not is_group_chat(callback_query.message.chat.type):
        await callback_query.message.edit_text(
            "ℹ️ Эта функция доступна только в групповых чатах."
        )
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Тест: нормальное сообщение", callback_data="test_normal")],
        [InlineKeyboardButton(text="🚫 Тест: мат и оскорбления", callback_data="test_profanity")],
        [InlineKeyboardButton(text="📢 Тест: реклама и спам", callback_data="test_spam")],
        [InlineKeyboardButton(text="⚡ Тест: дискриминация", callback_data="test_discrimination")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])
    
    text = """
🧪 <b>Тестирование агентов модерации</b>

Выберите тип сообщения для тестирования:

✅ <b>Нормальное сообщение</b> - должно пройти модерацию
🚫 <b>Мат и оскорбления</b> - должно быть заблокировано
📢 <b>Реклама и спам</b> - должно быть заблокировано  
⚡ <b>Дискриминация</b> - должно быть заблокировано

Тест активирует агентов 3.2, 4 и 5 для анализа.
    """
    
    await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode='HTML')

@dp.callback_query(lambda c: c.data == "add_chat")
async def add_chat_menu(callback_query: types.CallbackQuery):
    """Меню добавления ГРУППОВОГО чата"""
    await callback_query.answer()
    
    # Проверяем тип чата
    if not is_group_chat(callback_query.message.chat.type):
        text = f"""
ℹ️ <b>Только групповые чаты</b>

TeleGuard Bot работает только с групповыми чатами для модерации сообщений.

📋 <b>Текущий чат:</b>
🆔 <b>ID:</b> {callback_query.message.chat.id}
📊 <b>Тип:</b> {callback_query.message.chat.type}

Добавьте бота в групповой чат для использования системы модерации.
        """
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
        ])
        
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode='HTML')
        return
    
    chat_id = callback_query.message.chat.id
    chat_title = getattr(callback_query.message.chat, 'title', f'Групповой чат {chat_id}')
    chat_type = callback_query.message.chat.type
    
    # Добавляем текущий групповой чат в базу данных
    success = add_chat_to_db(chat_id, chat_title, chat_type)
    
    if success:
        # Также добавляем текущего пользователя как модератора
        user_id = callback_query.from_user.id
        username = callback_query.from_user.username or f"user_{user_id}"
        add_moderator_to_chat(chat_id, user_id, username)
        
        text = f"""
✅ <b>Групповой чат успешно добавлен!</b>

📋 <b>Информация о чате:</b>
🆔 <b>ID:</b> {chat_id}
📝 <b>Название:</b> {chat_title}
📊 <b>Тип:</b> {chat_type}
👤 <b>Модератор:</b> @{username}

Теперь система TeleGuard будет отслеживать сообщения в этом групповом чате и уведомлять модераторов о нарушениях.
        """
    else:
        text = f"""
ℹ️ <b>Групповой чат уже существует в системе</b>

📋 <b>Информация о чате:</b>
🆔 <b>ID:</b> {chat_id}
📝 <b>Название:</b> {chat_title}
📊 <b>Тип:</b> {chat_type}

Групповой чат уже зарегистрирован в системе TeleGuard.
        """
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])
    
    await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode='HTML')

# Тесты для разных типов сообщений
@dp.callback_query(lambda c: c.data == "test_normal")
async def test_normal_message(callback_query: types.CallbackQuery):
    await run_agent_test(callback_query, "Привет всем! Как дела? Хорошая погода сегодня!", "✅ Нормальное сообщение")

@dp.callback_query(lambda c: c.data == "test_profanity")  
async def test_profanity_message(callback_query: types.CallbackQuery):
    await run_agent_test(callback_query, "Ты идиот и дурак! Хуй тебе в жопу, сука!", "🚫 Мат и оскорбления")

@dp.callback_query(lambda c: c.data == "test_spam")
async def test_spam_message(callback_query: types.CallbackQuery):
    await run_agent_test(callback_query, "Вступайте в наш канал @spamchannel! Переходите по ссылке t.me/spam", "📢 Реклама и спам")

@dp.callback_query(lambda c: c.data == "test_discrimination")
async def test_discrimination_message(callback_query: types.CallbackQuery):
    await run_agent_test(callback_query, "Все эти чурки и хохлы должны убираться отсюда!", "⚡ Дискриминация")

async def run_agent_test(callback_query: types.CallbackQuery, test_message: str, test_type: str):
    """Запуск теста агентов (только в групповых чатах)"""
    await callback_query.answer()
    
    # Проверяем тип чата
    if not is_group_chat(callback_query.message.chat.type):
        await callback_query.message.edit_text(
            "ℹ️ Тестирование доступно только в групповых чатах."
        )
        return
    
    # Показываем что тест запущен
    await callback_query.message.edit_text(
        f"🧪 <b>Запуск теста: {test_type}</b>\n\n"
        f"📝 <b>Тестовое сообщение:</b>\n<i>{test_message}</i>\n\n"
        f"⏳ Отправляю агентам 3.2 и 4...",
        parse_mode='HTML'
    )
    
    # Запускаем тест
    user_id = callback_query.from_user.id
    username = callback_query.from_user.username or "test_user"
    chat_id = callback_query.message.chat.id
    
    result = test_agents_with_message(test_message, user_id, username, chat_id)
    
    if "error" in result:
        result_text = f"❌ <b>Ошибка теста:</b> {result['error']}"
    else:
        result_text = (
            f"✅ <b>Тест запущен успешно!</b>\n\n"
            f"📝 <b>Сообщение:</b> <i>{test_message[:100]}...</i>\n"
            f"🆔 <b>ID сообщения:</b> {result.get('message_id', 'N/A')}\n\n"
            f"🤖 Агенты 3.2 и 4 получили сообщение для анализа\n"
            f"⚖️ Агент 5 примет окончательное решение\n\n"
            f"📊 Проверьте раздел 'Негативные сообщения' через несколько секунд\n"
            f"📋 Результаты также появятся в логах агентов"
        )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚠️ Проверить результаты", callback_data="negative_messages")],
        [InlineKeyboardButton(text="🔄 Другой тест", callback_data="test_agents")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])
    
    await callback_query.message.edit_text(result_text, reply_markup=keyboard, parse_mode='HTML')

@dp.callback_query(lambda c: c.data == "back_to_menu")
async def back_to_menu(callback_query: types.CallbackQuery):
    """Возврат в главное меню"""
    await callback_query.answer()
    
    # Проверяем тип чата
    if not is_group_chat(callback_query.message.chat.type):
        await callback_query.message.edit_text(
            "🤖 <b>TeleGuard Bot</b>\n\n"
            "ℹ️ Этот бот работает только в <b>групповых чатах</b>.\n"
            "Добавьте меня в групповой чат для модерации сообщений.",
            parse_mode='HTML'
        )
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Состояние агентов", callback_data="status_agents")],
        [InlineKeyboardButton(text="📝 Сообщения чата", callback_data="chat_messages")],
        [InlineKeyboardButton(text="⚠️ Негативные сообщения", callback_data="negative_messages")],
        [InlineKeyboardButton(text="🧪 Тест агентов", callback_data="test_agents")],
        [InlineKeyboardButton(text="➕ Добавить чат", callback_data="add_chat")]
    ])
    
    chat_title = getattr(callback_query.message.chat, 'title', 'Без названия')
    
    welcome_text = f"""
🤖 <b>TeleGuard Bot - Многоагентная система модерации</b>

📋 <b>Групповой чат:</b> {chat_title}
🆔 <b>ID чата:</b> {callback_query.message.chat.id}
📊 <b>Тип:</b> {callback_query.message.chat.type}

Доступные функции:
📊 <b>Состояние агентов</b> - проверка работы всех агентов (1-5)
📝 <b>Сообщения чата</b> - последние сообщения из этого чата
⚠️ <b>Негативные сообщения</b> - найденные нарушения в этом чате
🧪 <b>Тест агентов</b> - проверка работы системы модерации
➕ <b>Добавить чат</b> - регистрация этого чата для модерации

<i>Выберите действие из меню ниже:</i>
    """
    
    await callback_query.message.edit_text(welcome_text, reply_markup=keyboard, parse_mode='HTML')

# ============================================================================
# ОБРАБОТКА ОБЫЧНЫХ СООБЩЕНИЙ (ТОЛЬКО ГРУППОВЫЕ ЧАТЫ)
# ============================================================================
@dp.message()
async def handle_message(message: types.Message):
    """Обработка всех сообщений (только из групповых чатов)"""
    try:
        # ПРОВЕРЯЕМ: обрабатываем только сообщения из групповых чатов
        if not should_process_chat(message):
            logger.info(f"🚫 Сообщение из личного чата {message.chat.id} пропущено")
            return
        
        # Сохраняем сообщение в базу данных ТОЛЬКО если это групповой чат
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
        
        # Сохраняем сообщение
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
        
        # Отправляем в очередь Агента 1 для обработки (если это не команда)
        if redis_client and message.text and not message.text.startswith('/'):
            test_data = {
                "message": message.text,
                "user_id": message.from_user.id,
                "username": message.from_user.username or f"user_{message.from_user.id}",
                "chat_id": message.chat.id,
                "message_id": message.message_id,
                "message_link": f"https://t.me/c/{str(message.chat.id).replace('-100', '')}/{message.message_id}"
            }
            
            test_json = json.dumps(test_data, ensure_ascii=False)
            redis_client.rpush("queue:agent1:input", test_json)
            logger.info(f"📤 Сообщение из группового чата {message.chat.id} отправлено в очередь агента 1")
        
        db_session.close()
        
        logger.info(f"💾 Сообщение из группового чата {message.chat.id} сохранено в БД: {message.text[:50] if message.text else 'No text'}...")
        
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения сообщения: {e}")

# ============================================================================
# ЗАПУСК БОТА
# ============================================================================
async def main():
    logger.info("🚀 Запуск TeleGuard Bot (только групповые чаты)...")
    
    # Проверяем подключения
    try:
        db_session = get_db_session()
        db_session.close()
        logger.info("✅ Подключение к PostgreSQL работает")
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к PostgreSQL: {e}")
    
    # Запускаем бота
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())