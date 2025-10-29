import logging
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String, ForeignKey, BigInteger, Boolean, DateTime, create_engine, select
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from datetime import datetime
import httpx
import json

# === НАСТРОЙКИ ===
TOKEN = '8320009669:AAHiVLu-Em8EOXBNHYrJ0UhVX3mMMTm8S_g'
POSTGRES_URL = 'postgresql://tguser:mnvm7110@176.108.248.211:5432/teleguard_db?sslmode=disable'
POSTGRES_ASYNC_URL = 'postgresql+asyncpg://tguser:mnvm7110@176.108.248.211:5432/teleguard_db'
AGENT2_URL = 'http://176.108.248.211:8002'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN)
dp = Dispatcher()

Base = declarative_base()

# === МОДЕЛИ БД ===

class Chat(Base):
    __tablename__ = 'chats'
    id = Column(Integer, primary_key=True)
    tg_chat_id = Column(String, unique=True, nullable=False)
    messages = relationship('Message', back_populates='chat', cascade="all, delete-orphan")
    moderators = relationship('Moderator', back_populates='chat', cascade="all, delete-orphan")
    negative_messages = relationship('NegativeMessage', back_populates='chat', cascade="all, delete-orphan")

class Message(Base):
    __tablename__ = 'messages'
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, ForeignKey('chats.id'), nullable=False)
    sender_id = Column(BigInteger, nullable=False)
    sender_username = Column(String, nullable=True)
    message_text = Column(String, nullable=True)
    message_link = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    chat = relationship('Chat', back_populates='messages')

class NegativeMessage(Base):
    __tablename__ = 'negative_messages'
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, ForeignKey('chats.id'), nullable=False)
    sender_username = Column(String, nullable=True)
    negative_reason = Column(String, nullable=True)
    is_sent_to_moderators = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    chat = relationship('Chat', back_populates='negative_messages')

class Moderator(Base):
    __tablename__ = 'moderators'
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, ForeignKey('chats.id'), nullable=False)
    username = Column(String, nullable=False)
    telegram_user_id = Column(BigInteger, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    chat = relationship('Chat', back_populates='moderators')

# === ИНИЦИАЛИЗАЦИЯ БД ===
engine = create_engine(POSTGRES_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
async_engine = create_async_engine(POSTGRES_ASYNC_URL)
AsyncSessionLocal = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

Base.metadata.create_all(engine)

def get_session():
    return SessionLocal()

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===

async def send_to_agent2(message_text: str, sender_id: int, username: str, chat_id: int, message_id: int) -> dict:
    """Отправить сообщение на анализ в Агент №2"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{AGENT2_URL}/process_message",
                json={
                    "message": message_text,
                    "user_id": sender_id,
                    "username": username,
                    "chat_id": chat_id,
                    "message_id": message_id
                },
                timeout=30
            )
            if response.status_code == 200:
                return response.json()
    except Exception as e:
        logger.error(f"Ошибка подключения к Агенту №2: {e}")
    return None

async def notify_moderators(chat_id: int, message_text: str, sender_username: str, reason: str, message_id: int):
    """Отправить уведомление всем модераторам чата"""
    session = get_session()
    try:
        chat = session.query(Chat).filter_by(tg_chat_id=str(chat_id)).first()
        if not chat:
            return

        for moderator in chat.moderators:
            if moderator.telegram_user_id:
                try:
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm_delete_{message_id}"),
                         InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_delete_{message_id}")]
                    ])
                    
                    notification = f"""⚠️ Найдено потенциальное нарушение!

👤 Отправитель: {sender_username}
📝 Сообщение: {message_text[:100]}...
🚨 Причина: {reason}

Что делать?"""
                    
                    await bot.send_message(
                        moderator.telegram_user_id,
                        notification,
                        reply_markup=keyboard
                    )
                except Exception as e:
                    logger.error(f"Ошибка отправки уведомления модератору {moderator.username}: {e}")
    finally:
        session.close()

# === ОБРАБОТЧИКИ КОМАНД ===

@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Команда /start - главное меню"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Список чатов", callback_data="list_chats")],
        [InlineKeyboardButton(text="👤 Мой ID", callback_data="my_id")],
        [InlineKeyboardButton(text="🔧 Статус системы", callback_data="system_status")]
    ])
    await message.answer(
        "👋 Добро пожаловать в TeleGuard!\n\n"
        "Я система автоматической модерации для Telegram групп.\n\n"
        "Что вы хотите сделать?",
        reply_markup=keyboard
    )

@dp.message(Command("help"))
async def cmd_help(message: Message):
    """Команда /help - справка"""
    help_text = """🤖 Справка по TeleGuard

Доступные команды:
/start - Главное меню
/help - Эта справка
/chats - Список моих чатов
/status - Статус системы
/messages - Вывести все сообщения

Как добавить бота в группу:
1. Добавьте меня в группу
2. Дайте мне права администратора
3. Запустите /start в группе
4. Выберите пункт меню

Система автоматически:
✅ Логирует все сообщения
✅ Анализирует на нарушения
✅ Уведомляет модераторов
✅ Предлагает действия"""
    
    await message.answer(help_text)

@dp.message(Command("messages"))
async def cmd_messages(message: Message):
    """Вывести последние сообщения"""
    session = get_session()
    try:
        messages = session.query(Message).order_by(Message.created_at.desc()).limit(20).all()
        
        if not messages:
            await message.answer("📭 Нет сообщений в базе данных")
            return
        
        text = "📋 Последние 20 сообщений:\n\n"
        for msg in reversed(messages):
            text += f"👤 @{msg.sender_username or 'unknown'}\n"
            text += f"💬 {msg.message_text[:50]}...\n"
            text += f"⏰ {msg.created_at.strftime('%H:%M:%S')}\n"
            text += "---\n"
        
        await message.answer(text)
    finally:
        session.close()

@dp.message(Command("status"))
async def cmd_status(message: Message):
    """Статус системы"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{AGENT2_URL}/health", timeout=5)
            if response.status_code == 200:
                health = response.json()
                status_text = f"""✅ Система работает!

Агент №2: 🟢 Online
⏱️ Uptime: {health.get('uptime_seconds', 0)}s
📊 Обработано сообщений: {health.get('processed_messages', 0)}
🗄️ БД подключена: {'✅' if health.get('database_connected') else '❌'}
🔴 Redis подключен: {'✅' if health.get('redis_connected') else '❌'}
🤖 GigaChat готов: {'✅' if health.get('gigachat_token_valid') else '⏳'}"""
                await message.answer(status_text)
                return
    except:
        pass
    
    await message.answer("❌ Система недоступна или Агент №2 не запущен")

@dp.message(Command("chats"))
async def cmd_chats(message: Message):
    """Список чатов и управление ими"""
    session = get_session()
    try:
        chats = session.query(Chat).all()
        
        if not chats:
            await message.answer("📭 Чатов не найдено")
            return
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"💬 {chat.tg_chat_id}", callback_data=f"chat_menu_{chat.id}")]
            for chat in chats
        ])
        
        await message.answer(f"📋 Найдено чатов: {len(chats)}", reply_markup=keyboard)
    finally:
        session.close()

# === ОБРАБОТЧИКИ CALLBACK КНОПОК ===

@dp.callback_query(lambda c: c.data == "list_chats")
async def cb_list_chats(callback: types.CallbackQuery):
    """Список чатов"""
    session = get_session()
    try:
        chats = session.query(Chat).all()
        
        if not chats:
            await callback.message.answer("📭 Чатов не найдено. Добавьте бота в группу!")
            await callback.answer()
            return
        
        text = "📋 Ваши чаты:\n\n"
        for chat in chats:
            text += f"💬 {chat.tg_chat_id}\n"
            text += f"   Модераторов: {len(chat.moderators)}\n"
            text += f"   Сообщений: {len(chat.messages)}\n\n"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🔧 {chat.tg_chat_id}", callback_data=f"chat_menu_{chat.id}")]
            for chat in chats
        ] + [[InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")]])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    finally:
        session.close()
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("chat_menu_"))
async def cb_chat_menu(callback: types.CallbackQuery):
    """Меню управления чатом"""
    chat_id = int(callback.data.split("_")[-1])
    session = get_session()
    try:
        chat = session.query(Chat).filter_by(id=chat_id).first()
        if not chat:
            await callback.answer("Чат не найден")
            return
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 Модераторы", callback_data=f"show_mods_{chat_id}")],
            [InlineKeyboardButton(text="📝 Сообщения", callback_data=f"show_msgs_{chat_id}")],
            [InlineKeyboardButton(text="🚨 Нарушения", callback_data=f"show_violations_{chat_id}")],
            [InlineKeyboardButton(text="➕ Добавить модератора", callback_data=f"add_mod_{chat_id}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="list_chats")]
        ])
        
        await callback.message.edit_text(
            f"⚙️ Управление чатом: {chat.tg_chat_id}\n\n"
            f"Модераторов: {len(chat.moderators)}\n"
            f"Сообщений: {len(chat.messages)}\n"
            f"Нарушений: {len(chat.negative_messages)}",
            reply_markup=keyboard
        )
    finally:
        session.close()
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("show_msgs_"))
async def cb_show_messages(callback: types.CallbackQuery):
    """Показать сообщения чата"""
    chat_id = int(callback.data.split("_")[-1])
    session = get_session()
    try:
        chat = session.query(Chat).filter_by(id=chat_id).first()
        if not chat or not chat.messages:
            await callback.message.edit_text("📭 Нет сообщений")
            await callback.answer()
            return
        
        text = f"📋 Сообщения чата {chat.tg_chat_id}:\n\n"
        for msg in chat.messages[-10:]:  # Последние 10
            text += f"👤 @{msg.sender_username}\n"
            text += f"💬 {msg.message_text[:80]}{'...' if len(msg.message_text) > 80 else ''}\n"
            text += f"⏰ {msg.created_at.strftime('%H:%M:%S')}\n---\n"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"chat_menu_{chat_id}")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    finally:
        session.close()
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("show_violations_"))
async def cb_show_violations(callback: types.CallbackQuery):
    """Показать нарушения"""
    chat_id = int(callback.data.split("_")[-1])
    session = get_session()
    try:
        chat = session.query(Chat).filter_by(id=chat_id).first()
        if not chat or not chat.negative_messages:
            await callback.message.edit_text("✅ Нарушений не найдено")
            await callback.answer()
            return
        
        text = f"🚨 Нарушения в {chat.tg_chat_id}:\n\n"
        for neg_msg in chat.negative_messages[-10:]:  # Последние 10
            text += f"👤 @{neg_msg.sender_username}\n"
            text += f"⚠️ {neg_msg.negative_reason}\n"
            text += f"⏰ {neg_msg.created_at.strftime('%H:%M:%S')}\n---\n"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"chat_menu_{chat_id}")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    finally:
        session.close()
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("show_mods_"))
async def cb_show_mods(callback: types.CallbackQuery):
    """Показать модераторов"""
    chat_id = int(callback.data.split("_")[-1])
    session = get_session()
    try:
        chat = session.query(Chat).filter_by(id=chat_id).first()
        if not chat or not chat.moderators:
            await callback.message.edit_text("👥 Модераторы не добавлены")
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Добавить", callback_data=f"add_mod_{chat_id}")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data=f"chat_menu_{chat_id}")]
            ])
            await callback.message.edit_reply_markup(reply_markup=keyboard)
            await callback.answer()
            return
        
        text = f"👥 Модераторы {chat.tg_chat_id}:\n\n"
        for mod in chat.moderators:
            status = "✅ ID установлен" if mod.telegram_user_id else "⏳ Ожидание /start"
            text += f"@{mod.username} {status}\n"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"❌ @{mod.username}", callback_data=f"delete_mod_{mod.id}")]
            for mod in chat.moderators
        ] + [
            [InlineKeyboardButton(text="➕ Добавить модератора", callback_data=f"add_mod_{chat_id}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"chat_menu_{chat_id}")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
    finally:
        session.close()
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("add_mod_"))
async def cb_add_mod(callback: types.CallbackQuery):
    """Добавить модератора"""
    chat_id = int(callback.data.split("_")[-1])
    await callback.message.answer(
        "👤 Введите ники модераторов через пробел:\n"
        "Пример: @moderator1 @moderator2 @moderator3"
    )
    await callback.answer()

@dp.message()
async def handle_message(message: Message):
    """Основной обработчик всех сообщений"""
    
    # Пропускаем команды
    if message.text and message.text.startswith("/"):
        return
    
    session = get_session()
    try:
        # Получаем или создаем чат
        chat = session.query(Chat).filter_by(tg_chat_id=str(message.chat.id)).first()
        if not chat:
            chat = Chat(tg_chat_id=str(message.chat.id))
            session.add(chat)
            session.commit()
        
        # Логируем сообщение
        msg = Message(
            chat_id=chat.id,
            sender_id=message.from_user.id,
            sender_username=message.from_user.username or "unknown",
            message_text=message.text or "[медиа]",
            message_link=f"https://t.me/c/{message.chat.id}/{message.message_id}"
        )
        session.add(msg)
        session.commit()
        
        logger.info(f"Сообщение логировано: {message.from_user.username} - {message.text[:50]}")
        
        # Отправляем на анализ в Агент №2
        if message.text:
            asyncio.create_task(send_to_agent2(
                message.text,
                message.from_user.id,
                message.from_user.username or "unknown",
                message.chat.id,
                message.message_id
            ))
        
    except Exception as e:
        logger.error(f"Ошибка обработки сообщения: {e}")
    finally:
        session.close()

@dp.callback_query(lambda c: c.data == "my_id")
async def cb_my_id(callback: types.CallbackQuery):
    """Показать мой Telegram ID"""
    session = get_session()
    try:
        # Ищем или создаем запись модератора
        mod = session.query(Moderator).filter_by(telegram_user_id=callback.from_user.id).first()
        
        if not mod:
            # Создаем нового модератора если его нет
            mod = Moderator(
                chat_id=1,  # Основной чат
                username=callback.from_user.username or "unknown",
                telegram_user_id=callback.from_user.id,
                is_active=True
            )
            session.add(mod)
            session.commit()
        
        await callback.message.answer(
            f"👤 Ваш Telegram ID: <code>{callback.from_user.id}</code>\n\n"
            f"Username: @{callback.from_user.username or 'не установлено'}\n\n"
            f"✅ ID сохранен в системе и вы будете получать уведомления о нарушениях!"
        )
    finally:
        session.close()
    await callback.answer()

@dp.callback_query(lambda c: c.data == "system_status")
async def cb_system_status(callback: types.CallbackQuery):
    """Статус системы"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{AGENT2_URL}/health", timeout=5)
            if response.status_code == 200:
                health = response.json()
                status_text = f"""✅ Система работает!

🤖 Агент №2: 🟢 Online
⏱️ Uptime: {health.get('uptime_seconds', 0)}s
📊 Обработано: {health.get('processed_messages', 0)} сообщений
🗄️ БД: {'✅ Подключена' if health.get('database_connected') else '❌ Ошибка'}
🔴 Redis: {'✅ Работает' if health.get('redis_connected') else '❌ Ошибка'}
🤖 GigaChat: {'✅ Готов' if health.get('gigachat_token_valid') else '⏳ Инициализация'}"""
                await callback.message.answer(status_text)
                await callback.answer()
                return
    except:
        pass
    
    await callback.message.answer("❌ Агент недоступен")
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_main")
async def cb_back_main(callback: types.CallbackQuery):
    """Вернуться в главное меню"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Список чатов", callback_data="list_chats")],
        [InlineKeyboardButton(text="👤 Мой ID", callback_data="my_id")],
        [InlineKeyboardButton(text="🔧 Статус системы", callback_data="system_status")]
    ])
    await callback.message.edit_text(
        "👋 Главное меню TeleGuard\n\n"
        "Что вы хотите сделать?",
        reply_markup=keyboard
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("delete_mod_"))
async def cb_delete_mod(callback: types.CallbackQuery):
    """Удалить модератора"""
    mod_id = int(callback.data.split("_")[-1])
    session = get_session()
    try:
        mod = session.query(Moderator).filter_by(id=mod_id).first()
        if mod:
            chat_id = mod.chat_id
            session.delete(mod)
            session.commit()
            await callback.message.answer("✅ Модератор удален")
            # Возвращаемся в меню чата
            await cb_show_mods(callback)
            callback.data = f"show_mods_{chat_id}"
    finally:
        session.close()
    await callback.answer()

# === ЗАПУСК БОТА ===

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    logger.info("🚀 TeleGuard Bot запущен!")
    asyncio.run(main())
