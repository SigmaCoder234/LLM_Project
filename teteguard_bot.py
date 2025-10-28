import logging
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String, ForeignKey, BigInteger, Boolean, DateTime, create_engine
from sqlalchemy.orm import relationship, sessionmaker
from datetime import datetime

# === НАСТРОЙКИ ===
TOKEN = '8320009669:AAHiVLu-Em8EOXBNHYrJ0UhVX3mMMTm8S_g'
POSTGRES_URL = 'postgresql://tguser:mnvm7110@176.108.248.211:5432/teleguard_db?sslmode=disable'
# Формат: postgresql://user:password@host:port/database

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

Base = declarative_base()

# === МОДЕЛИ БД ===
class Chat(Base):
    __tablename__ = 'chats'
    id = Column(Integer, primary_key=True)
    tg_chat_id = Column(String, unique=True, nullable=False)
    messages = relationship('Message', back_populates='chat', cascade="all, delete")
    moderators = relationship('Moderator', back_populates='chat', cascade="all, delete")
    negative_messages = relationship('NegativeMessage', back_populates='chat', cascade="all, delete")

class Message(Base):
    __tablename__ = 'messages'
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, ForeignKey('chats.id'), nullable=False)
    sender_username = Column(String)
    sender_id = Column(BigInteger)
    message_text = Column(String)
    message_link = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    chat = relationship('Chat', back_populates='messages')

class Moderator(Base):
    __tablename__ = 'moderators'
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, ForeignKey('chats.id'), nullable=False)
    username = Column(String)
    telegram_user_id = Column(BigInteger)  # для отправки уведомлений
    chat = relationship('Chat', back_populates='moderators')

class NegativeMessage(Base):
    __tablename__ = 'negative_messages'
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, ForeignKey('chats.id'), nullable=False)
    message_link = Column(String)
    sender_username = Column(String)
    negative_reason = Column(String)  # причина негатива от нейросети
    is_sent_to_moderators = Column(Boolean, default=False)  # отправлено ли модераторам
    created_at = Column(DateTime, default=datetime.utcnow)
    chat = relationship('Chat', back_populates='negative_messages')

# === ПОДКЛЮЧЕНИЕ К БД ===
engine = create_engine(POSTGRES_URL)
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)
def get_session():
    return SessionLocal()

user_state = dict()

# === ХЭНДЛЕРЫ ===
@dp.message(Command("start"))
async def start_bot(message: types.Message):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Список чатов", callback_data="list_chats")]
        ]
    )
    await message.answer("✅ Бот запущен!\nВыберите действие:", reply_markup=kb)

@dp.message(lambda m: m.content_type == types.ContentType.NEW_CHAT_MEMBERS)
async def on_bot_added(message: types.Message):
    session = get_session()
    chat_id = str(message.chat.id)
    if not session.query(Chat).filter_by(tg_chat_id=chat_id).first():
        chat = Chat(tg_chat_id=chat_id)
        session.add(chat)
        session.commit()
        await message.reply("✅ Бот успешно подключен к этому чату и начал логирование сообщений!")
    session.close()

# === ЛОГИРОВАНИЕ ВСЕХ СООБЩЕНИЙ ===
@dp.message(lambda m: m.chat.type in ("group", "supergroup"))
async def log_message(message: types.Message):
    print(f"🔵 Логирование: '{message.text}' в чате {message.chat.id}")
    if not hasattr(message, 'text') or message.text is None:
        return
    session = get_session()
    chat = session.query(Chat).filter_by(tg_chat_id=str(message.chat.id)).first()
    if not chat:
        chat = Chat(tg_chat_id=str(message.chat.id))
        session.add(chat)
        session.commit()
    
    if message.chat.username:
        msg_link = f"https://t.me/{message.chat.username}/{message.message_id}"
    else:
        chat_id_str = str(message.chat.id)
        if chat_id_str.startswith('-100'):
            msg_link = f"https://t.me/c/{chat_id_str[4:]}/{message.message_id}"
        else:
            msg_link = f"chat_id:{message.chat.id}/message_id:{message.message_id}"
    
    entry = Message(
        chat_id=chat.id,
        sender_username=message.from_user.username or f"user_id_{message.from_user.id}",
        sender_id=message.from_user.id,
        message_text=message.text,
        message_link=msg_link
    )
    session.add(entry)
    session.commit()
    session.close()

# === УПРАВЛЕНИЕ ЧАТАМИ ===
@dp.callback_query(lambda c: c.data == "list_chats")
async def cb_list_chats(callback: types.CallbackQuery):
    session = get_session()
    chats = session.query(Chat).all()
    if not chats:
        await callback.message.answer("Чаты ещё не добавлены.")
        session.close()
        await callback.answer()
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=chat.tg_chat_id, callback_data=f"select_chat_{chat.id}"),
                InlineKeyboardButton(text="❌", callback_data=f"delete_chat_{chat.id}")
            ] for chat in chats
        ]
    )
    await callback.message.answer("Список чатов:", reply_markup=kb)
    session.close()
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("delete_chat_"))
async def cb_delete_chat(callback: types.CallbackQuery):
    chat_id = int(callback.data.split("_")[-1])
    session = get_session()
    chat = session.query(Chat).filter_by(id=chat_id).first()
    if chat:
        session.delete(chat)
        session.commit()
        await callback.message.answer(f"Чат {chat.tg_chat_id} удалён.")
    else:
        await callback.message.answer("Чат не найден.")
    session.close()
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("select_chat_"))
async def cb_select_chat(callback: types.CallbackQuery):
    chat_id = int(callback.data.split("_")[-1])
    session = get_session()
    chat = session.query(Chat).filter_by(id=chat_id).first()
    if not chat:
        await callback.message.answer("Чат не найден.")
        session.close()
        await callback.answer()
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Посмотреть модераторов", callback_data=f"show_mods_{chat.id}")],
            [InlineKeyboardButton(text="Добавить модераторов", callback_data=f"add_mods_{chat.id}")]
        ]
    )
    await callback.message.answer(f"Выбран чат: {chat.tg_chat_id}", reply_markup=kb)
    session.close()
    await callback.answer()

# === УПРАВЛЕНИЕ МОДЕРАТОРАМИ ===
@dp.callback_query(lambda c: c.data.startswith("show_mods_"))
async def cb_show_mods(callback: types.CallbackQuery):
    chat_id = int(callback.data.split("_")[-1])
    session = get_session()
    chat = session.query(Chat).filter_by(id=chat_id).first()
    if chat and chat.moderators:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text=f"@{mod.username}", callback_data=f"ignore"),
                    InlineKeyboardButton(text="❌", callback_data=f"delete_mod_{mod.id}")
                ] for mod in chat.moderators
            ]
        )
        await callback.message.answer("Модераторы чата:", reply_markup=kb)
    else:
        await callback.message.answer("Модераторы не найдены.")
    session.close()
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("delete_mod_"))
async def cb_delete_mod(callback: types.CallbackQuery):
    mod_id = int(callback.data.split("_")[-1])
    session = get_session()
    mod = session.query(Moderator).filter_by(id=mod_id).first()
    if mod:
        session.delete(mod)
        session.commit()
        await callback.message.answer(f"Модератор @{mod.username} удалён.")
    else:
        await callback.message.answer("Модератор не найден.")
    session.close()
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("add_mods_"))
async def cb_add_mods(callback: types.CallbackQuery):
    chat_id = int(callback.data.split("_")[-1])
    user_state[callback.from_user.id] = {'action': 'add_mods', 'chat_id': chat_id}
    await callback.message.answer("Введи ник(и) модераторов через пробел (@username):")
    await callback.answer()

@dp.message()
async def user_text_handler(message: types.Message):
    st = user_state.get(message.from_user.id)
    if not st:
        return
    session = get_session()
    if st['action'] == 'add_mods':
        chat = session.query(Chat).filter_by(id=st['chat_id']).first()
        if not chat:
            user_state.pop(message.from_user.id)
            session.close()
            return
        usernames = [u.lstrip("@") for u in message.text.strip().split()]
        added = []
        for username in usernames:
            if not session.query(Moderator).filter_by(chat_id=chat.id, username=username).first():
                session.add(Moderator(chat_id=chat.id, username=username, telegram_user_id=None))
                added.append(username)
        session.commit()
        if added:
            await message.answer(f"✅ Добавлены модераторы: {', '.join(added)}")
        else:
            await message.answer("Такие модераторы уже есть.")
        user_state.pop(message.from_user.id)
    session.close()

# === ФОНОВАЯ ЗАДАЧА: ОТПРАВКА НЕГАТИВНЫХ СООБЩЕНИЙ МОДЕРАТОРАМ ===
async def check_and_send_negative_messages():
    while True:
        try:
            session = get_session()
            # Найти все неотправленные негативные сообщения
            negative_msgs = session.query(NegativeMessage).filter_by(is_sent_to_moderators=False).all()
            
            for neg_msg in negative_msgs:
                chat = session.query(Chat).filter_by(id=neg_msg.chat_id).first()
                if not chat:
                    continue
                
                notification = (
                    f"🚨 Обнаружено негативное сообщение!\n\n"
                    f"Причина: {neg_msg.negative_reason}\n"
                    f"Автор: {neg_msg.sender_username}\n"
                    f"Ссылка: {neg_msg.message_link}"
                )
                
                # Отправка всем модераторам
                for mod in chat.moderators:
                    try:
                        if mod.telegram_user_id:
                            await bot.send_message(mod.telegram_user_id, notification)
                        else:
                            logging.warning(f"У модератора @{mod.username} нет telegram_user_id")
                    except Exception as e:
                        logging.error(f"Ошибка отправки @{mod.username}: {e}")
                
                # Пометить как отправленное
                neg_msg.is_sent_to_moderators = True
                session.commit()
            
            session.close()
        except Exception as e:
            logging.error(f"Ошибка в check_and_send_negative_messages: {e}")
        
        await asyncio.sleep(10)  # Проверка каждые 10 секунд

# === ЗАПУСК ===
async def main():
    # Запуск фоновой задачи
    asyncio.create_task(check_and_send_negative_messages())
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
