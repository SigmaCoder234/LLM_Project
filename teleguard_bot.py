import logging
import asyncio
import aiohttp
import json
import requests
import uuid
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String, ForeignKey, BigInteger, Boolean, DateTime, create_engine
from sqlalchemy.orm import relationship, sessionmaker
from datetime import datetime

# === НАСТРОЙКИ (ГОТОВЫЙ ACCESS TOKEN) ===
TOKEN = '8320009669:AAHiVLu-Em8EOXBNHYrJ0UhVX3mMMTm8S_g'
POSTGRES_URL = 'postgresql://tguser:mnvm7110@176.108.248.211:5432/teleguard_db?sslmode=disable'

# ГигаЧат настройки - ГОТОВЫЙ ACCESS TOKEN
from token inport TOKEN
GIGACHAT_ACCESS_TOKEN = TOKEN
# Конфигурация агентов
AGENTS_CONFIG = {
    'agent_1': {'url': 'http://localhost:8001/health', 'name': 'Агент №1 (Координатор)', 'port': 8001},
    'agent_2': {'url': 'http://localhost:8002/health', 'name': 'Агент №2 (Обработчик)', 'port': 8002}, 
    'agent_3': {'url': 'http://localhost:8003/health', 'name': 'Агент №3 (GigaChat)', 'port': 8003},
    'agent_4': {'url': 'http://localhost:8004/health', 'name': 'Агент №4 (Эвристика)', 'port': 8004},
    'agent_5': {'url': 'http://localhost:8005/health', 'name': 'Агент №5 (Координатор)', 'port': 8005}
}

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

# === ФУНКЦИИ ПРОВЕРКИ СООБЩЕНИЯ ===
async def check_message_with_agents(message_text: str):
    """
    Проверка сообщения через агентов 3 и 4, получение финального вердикта
    
    Args:
        message_text: Текст сообщения для проверки
    
    Returns:
        dict: Результат проверки с финальным вердиктом
    """
    
    # Правила по умолчанию для проверки
    default_rules = [
        'Запрещена реклама',
        'Запрещен спам', 
        'Запрещена ненормативная лексика',
        'Запрещены оскорбления',
        'Запрещены угрозы',
        'Запрещен флуд'
    ]
    
    try:
        # Проверяем через Агент 3 (GigaChat)
        agent3_result = await check_with_gigachat(message_text, default_rules)
        
        # Проверяем через Агент 4 (Эвристика)
        agent4_result = check_with_heuristics(message_text, default_rules)
        
        # Получаем финальное решение
        final_verdict = make_final_decision(agent3_result, agent4_result, message_text)
        
        return {
            'message': message_text,
            'agent3_result': agent3_result,
            'agent4_result': agent4_result,
            'final_verdict': final_verdict,
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logging.error(f"Ошибка проверки сообщения: {e}")
        return {
            'message': message_text,
            'agent3_result': {'ban': False, 'reason': f'Ошибка Агента 3: {e}'},
            'agent4_result': {'ban': False, 'reason': f'Ошибка Агента 4: {e}'},
            'final_verdict': {'ban': False, 'reason': f'Ошибка системы: {e}', 'confidence': 0.0},
            'timestamp': datetime.now().isoformat()
        }

async def check_with_gigachat(message: str, rules: list):
    """
    Проверка сообщения через GigaChat API (Агент 3)
    """
    url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
    
    rules_text = "\n".join(rules)
    system_msg = f"{rules_text}\n\nТы модератор чата. Анализируй сообщение и ответь 'запретить' если нарушает правила или 'разрешить' если не нарушает."
    
    headers = {
        'Authorization': f'Bearer {GIGACHAT_ACCESS_TOKEN}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    
    data = {
        'model': 'GigaChat',
        'messages': [
            {'role': 'system', 'content': system_msg},
            {'role': 'user', 'content': message}
        ],
        'temperature': 0.2,
        'max_tokens': 256
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, verify=False, timeout=30)
        response.raise_for_status()
        result = response.json()
        content = result['choices'][0]['message']['content']
        
        # Парсим ответ
        content_lower = content.lower()
        ban = any(word in content_lower for word in ['запретить', 'заблокировать', 'бан', 'нарушение'])
        
        return {
            'ban': ban,
            'reason': content.strip(),
            'confidence': 0.85 if ban else 0.80
        }
        
    except Exception as e:
        return {
            'ban': False,
            'reason': f'Ошибка GigaChat API: {e}',
            'confidence': 0.0
        }

def check_with_heuristics(message: str, rules: list):
    """
    Проверка сообщения через эвристику (Агент 4)
    """
    import re
    
    message_lower = message.lower()
    violations = []
    
    # Паттерны для проверки
    spam_patterns = [r'дешев[оые]', r'скидк[аи]', r'купи[тье]', r'продаж[аи]', r'реклам[аы]', r'https?://', r't\.me/']
    profanity_patterns = [r'бля[дь]?', r'х[уy]й', r'п[иеё]зд', r'[её]б[ауе]']
    insult_patterns = [r'идиот', r'дурак', r'тупой', r'урод', r'козёл']
    
    # Проверяем спам
    spam_count = sum(1 for pattern in spam_patterns if re.search(pattern, message_lower))
    if spam_count > 0:
        violations.append(f"Спам: найдено {spam_count} паттернов")
    
    # Проверяем мат
    profanity_count = sum(1 for pattern in profanity_patterns if re.search(pattern, message_lower))
    if profanity_count > 0:
        violations.append(f"Мат: найдено {profanity_count} слов")
    
    # Проверяем оскорбления
    insult_count = sum(1 for pattern in insult_patterns if re.search(pattern, message_lower))
    if insult_count > 0:
        violations.append(f"Оскорбления: найдено {insult_count} слов")
    
    # Проверяем длину (флуд)
    if len(message) > 2000:
        violations.append("Слишком длинное сообщение (флуд)")
    
    ban = len(violations) > 0
    reason = ". ".join(violations) if violations else "Сообщение прошло эвристическую проверку"
    
    return {
        'ban': ban,
        'reason': reason,
        'confidence': 0.75 if ban else 0.70
    }

def make_final_decision(agent3_result: dict, agent4_result: dict, message: str):
    """
    Принятие финального решения на основе результатов агентов (Агент 5)
    """
    agent3_ban = agent3_result['ban']
    agent4_ban = agent4_result['ban']
    agent3_conf = agent3_result['confidence']
    agent4_conf = agent4_result['confidence']
    
    # Логика принятия решения
    if agent3_ban and agent4_ban:
        # Оба агента за бан
        final_ban = True
        confidence = (agent3_conf + agent4_conf) / 2
        reason = f"Оба агента рекомендуют блокировку. Agent3: {agent3_result['reason']}. Agent4: {agent4_result['reason']}"
    elif agent3_ban and not agent4_ban:
        # Только Агент 3 за бан
        if agent3_conf > 0.8:
            final_ban = True
            confidence = agent3_conf * 0.9
            reason = f"Агент 3 уверенно рекомендует блокировку: {agent3_result['reason']}"
        else:
            final_ban = False
            confidence = 0.6
            reason = f"Конфликт агентов, но уверенность Агента 3 низкая ({agent3_conf:.2f})"
    elif not agent3_ban and agent4_ban:
        # Только Агент 4 за бан
        if agent4_conf > 0.8:
            final_ban = True
            confidence = agent4_conf * 0.9
            reason = f"Агент 4 уверенно рекомендует блокировку: {agent4_result['reason']}"
        else:
            final_ban = False
            confidence = 0.6
            reason = f"Конфликт агентов, но уверенность Агента 4 низкая ({agent4_conf:.2f})"
    else:
        # Оба агента против бана
        final_ban = False
        confidence = (agent3_conf + agent4_conf) / 2
        reason = "Оба агента считают сообщение допустимым"
    
    return {
        'ban': final_ban,
        'reason': reason,
        'confidence': confidence,
        'agents_agree': agent3_ban == agent4_ban
    }

# === ФУНКЦИИ МОНИТОРИНГА АГЕНТОВ ===
async def check_agent_status(agent_id, agent_info):
    """
    Проверка статуса одного агента
    """
    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(agent_info['url']) as response:
                if response.status == 200:
                    data = await response.json()
                    return {
                        'agent_id': agent_id,
                        'name': agent_info['name'],
                        'status': '🟢 ONLINE',
                        'port': agent_info['port'],
                        'response_time': '< 5s',
                        'details': data
                    }
                else:
                    return {
                        'agent_id': agent_id,
                        'name': agent_info['name'],
                        'status': f'🟡 ERROR {response.status}',
                        'port': agent_info['port'],
                        'response_time': 'N/A',
                        'details': {}
                    }
    except asyncio.TimeoutError:
        return {
            'agent_id': agent_id,
            'name': agent_info['name'],
            'status': '🔴 TIMEOUT',
            'port': agent_info['port'],
            'response_time': '> 5s',
            'details': {}
        }
    except Exception as e:
        return {
            'agent_id': agent_id,
            'name': agent_info['name'],
            'status': '🔴 OFFLINE',
            'port': agent_info['port'],
            'response_time': 'N/A',
            'details': {'error': str(e)}
        }

async def get_all_agents_status():
    """
    Получение статуса всех агентов
    """
    tasks = []
    for agent_id, agent_info in AGENTS_CONFIG.items():
        task = check_agent_status(agent_id, agent_info)
        tasks.append(task)
    
    results = await asyncio.gather(*tasks)
    return results

def format_agent_status_message(agents_status):
    """
    Форматирование сообщения со статусом всех агентов
    """
    lines = ["🤖 СТАТУС ВСЕХ АГЕНТОВ TeleGuard", "=" * 40]
    
    online_count = sum(1 for agent in agents_status if '🟢' in agent['status'])
    total_count = len(agents_status)
    
    lines.append(f"📊 Сводка: {online_count}/{total_count} агентов онлайн")
    lines.append("")
    
    for agent in agents_status:
        lines.append(f"{agent['status']} {agent['name']}")
        lines.append(f"    🌐 Порт: {agent['port']}")
        lines.append(f"    ⏱️  Ответ: {agent['response_time']}")
        
        # Дополнительная информация из health check
        if agent['details']:
            details = agent['details']
            if 'version' in details:
                lines.append(f"    📦 Версия: {details['version']}")
            if 'uptime_seconds' in details:
                uptime_min = details['uptime_seconds'] // 60
                lines.append(f"    ⏰ Время работы: {uptime_min} мин")
            if 'processed_messages' in details:
                lines.append(f"    📝 Обработано сообщений: {details['processed_messages']}")
            if 'error_count' in details:
                lines.append(f"    ❌ Ошибок: {details['error_count']}")
        
        lines.append("")
    
    # Добавляем рекомендации
    offline_agents = [agent for agent in agents_status if '🔴' in agent['status']]
    if offline_agents:
        lines.append("⚠️  РЕКОМЕНДАЦИИ:")
        for agent in offline_agents:
            lines.append(f"   • Запустите {agent['name']} на порту {agent['port']}")
        lines.append("")
    
    lines.append(f"🔄 Обновлено: {datetime.now().strftime('%H:%M:%S')}")
    
    return "\n".join(lines)

# === ХЭНДЛЕРЫ ===
@dp.message(Command("start"))
async def start_bot(message: types.Message):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Список чатов", callback_data="list_chats")],
            [InlineKeyboardButton(text="Статус агентов", callback_data="agents_status")],
            [InlineKeyboardButton(text="🧪 Проверить сообщение", callback_data="check_message")],
            [InlineKeyboardButton(text="Системная информация", callback_data="system_info")]
        ]
    )
    await message.answer("✅ TeleGuard Bot запущен!\nВыберите действие:", reply_markup=kb)

@dp.callback_query(lambda c: c.data == "check_message")
async def cb_check_message(callback: types.CallbackQuery):
    """Начало процедуры проверки сообщения"""
    user_state[callback.from_user.id] = {'action': 'check_message'}
    await callback.answer()
    
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="main_menu")]
        ]
    )
    
    await callback.message.answer(
        "🧪 ПРОВЕРКА СООБЩЕНИЯ\n\n"
        "Введите текст сообщения, которое хотите проверить на нарушения.\n\n"
        "Система проанализирует сообщение через:\n"
        "• 🤖 Агент №3 (GigaChat AI)\n"
        "• 🔧 Агент №4 (Эвристический анализ)\n"
        "• ⚖️ Агент №5 (Финальное решение)\n\n"
        "💬 Отправьте сообщение для проверки:",
        reply_markup=kb
    )

async def process_message_check(message: types.Message):
    """Обработка сообщения для проверки"""
    
    # Показываем что начали проверку
    processing_msg = await message.answer(
        "🔄 Анализирую сообщение...\n\n"
        "⏳ Проверяю через Агент №3 (GigaChat)...\n"
        "⏳ Проверяю через Агент №4 (Эвристика)...\n"
        "⏳ Получаю финальное решение от Агента №5..."
    )
    
    try:
        # Проверяем сообщение
        result = await check_message_with_agents(message.text)
        
        # Формируем детальный ответ
        agent3 = result['agent3_result']
        agent4 = result['agent4_result']
        final = result['final_verdict']
        
        # Определяем эмодзи для вердикта
        verdict_emoji = "🚫" if final['ban'] else "✅"
        verdict_text = "БАНИТЬ" if final['ban'] else "НЕ БАНИТЬ"
        confidence_stars = "⭐" * min(5, max(1, int(final['confidence'] * 5)))
        
        response_lines = [
            "🧪 РЕЗУЛЬТАТ ПРОВЕРКИ СООБЩЕНИЯ",
            "=" * 40,
            f"💬 Сообщение: \"{message.text[:100]}{'...' if len(message.text) > 100 else ''}\"",
            "",
            f"{verdict_emoji} ФИНАЛЬНЫЙ ВЕРДИКТ: {verdict_text}",
            f"🎯 Уверенность: {final['confidence']:.0%} {confidence_stars}",
            f"📝 Обоснование: {final['reason']}",
            "",
            "📊 ДЕТАЛЬНЫЙ АНАЛИЗ:",
            "",
            "🤖 Агент №3 (GigaChat AI):",
            f"   {'🚫 Заблокировать' if agent3['ban'] else '✅ Разрешить'}",
            f"   🎯 Уверенность: {agent3['confidence']:.0%}",
            f"   💭 Причина: {agent3['reason']}",
            "",
            "🔧 Агент №4 (Эвристический анализ):",
            f"   {'🚫 Заблокировать' if agent4['ban'] else '✅ Разрешить'}",
            f"   🎯 Уверенность: {agent4['confidence']:.0%}",
            f"   💭 Причина: {agent4['reason']}",
            "",
            f"🤝 Согласованность: {'✅ Агенты согласны' if final['agents_agree'] else '⚠️ Есть разногласия'}",
            "",
            f"🕐 Время проверки: {datetime.now().strftime('%H:%M:%S')}"
        ]
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🧪 Проверить ещё", callback_data="check_message")],
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
            ]
        )
        
        # Обновляем сообщение с результатом
        await processing_msg.edit_text("\n".join(response_lines), reply_markup=kb)
        
    except Exception as e:
        error_msg = (
            "❌ ОШИБКА ПРОВЕРКИ\n\n"
            f"Произошла ошибка при анализе сообщения:\n{str(e)}\n\n"
            "Попробуйте еще раз или обратитесь к администратору."
        )
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="check_message")],
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
            ]
        )
        
        await processing_msg.edit_text(error_msg, reply_markup=kb)
        logging.error(f"Ошибка проверки сообщения: {e}")

@dp.callback_query(lambda c: c.data == "agents_status")
async def cb_agents_status(callback: types.CallbackQuery):
    """Обработка запроса статуса агентов"""
    await callback.answer("Проверяю статус всех агентов...")
    
    # Получаем статус всех агентов
    agents_status = await get_all_agents_status()
    
    # Форматируем сообщение
    status_message = format_agent_status_message(agents_status)
    
    # Кнопки для дополнительных действий
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="agents_status")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
        ]
    )
    
    await callback.message.answer(status_message, reply_markup=kb)

@dp.callback_query(lambda c: c.data == "system_info")
async def cb_system_info(callback: types.CallbackQuery):
    """Системная информация"""
    await callback.answer()
    
    session = get_session()
    total_chats = session.query(Chat).count()
    total_messages = session.query(Message).count()
    total_negative = session.query(NegativeMessage).count()
    total_moderators = session.query(Moderator).count()
    session.close()
    
    info_lines = [
        "🔧 СИСТЕМНАЯ ИНФОРМАЦИЯ TeleGuard",
        "=" * 40,
        f"💬 Всего чатов: {total_chats}",
        f"📝 Всего сообщений: {total_messages}",
        f"🚨 Негативных сообщений: {total_negative}",
        f"👥 Всего модераторов: {total_moderators}",
        "",
        "🔑 ГигаЧат:",
        f"   📏 Длина токена: {len(GIGACHAT_ACCESS_TOKEN)} символов",
        f"   🟢 Токен установлен: {'Да' if GIGACHAT_ACCESS_TOKEN != 'your_access_token_here' else 'Нет'}",
        "",
        "🗄️ База данных:",
        f"   🐘 PostgreSQL: {POSTGRES_URL.split('@')[1].split('/')[0]}",
        f"   📊 DB: {POSTGRES_URL.split('/')[-1].split('?')[0]}",
        "",
        f"🕐 Текущее время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    ]
    
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🤖 Статус агентов", callback_data="agents_status")],
            [InlineKeyboardButton(text="🧪 Проверить сообщение", callback_data="check_message")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
        ]
    )
    
    await callback.message.answer("\n".join(info_lines), reply_markup=kb)

@dp.callback_query(lambda c: c.data == "main_menu")
async def cb_main_menu(callback: types.CallbackQuery):
    """Возврат в главное меню"""
    await callback.answer()
    
    # Очищаем состояние пользователя
    if callback.from_user.id in user_state:
        del user_state[callback.from_user.id]
    
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Список чатов", callback_data="list_chats")],
            [InlineKeyboardButton(text="Статус агентов", callback_data="agents_status")],
            [InlineKeyboardButton(text="🧪 Проверить сообщение", callback_data="check_message")],
            [InlineKeyboardButton(text="Системная информация", callback_data="system_info")]
        ]
    )
    
    await callback.message.answer("🏠 Главное меню TeleGuard Bot:", reply_markup=kb)

@dp.message(lambda m: m.content_type == types.ContentType.NEW_CHAT_MEMBERS)
async def on_bot_added(message: types.Message):
    session = get_session()
    chat_id = str(message.chat.id)
    if not session.query(Chat).filter_by(tg_chat_id=chat_id).first():
        chat = Chat(tg_chat_id=chat_id)
        session.add(chat)
        session.commit()
    await message.reply("✅ TeleGuard Bot успешно подключен к этому чату и начал логирование сообщений!")
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
        ] + [[InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]]
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
            [InlineKeyboardButton(text="Добавить модераторов", callback_data=f"add_mods_{chat.id}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="list_chats")]
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
            ] + [[InlineKeyboardButton(text="🔙 Назад", callback_data=f"select_chat_{chat_id}")]]
        )
        await callback.message.answer("Модераторы чата:", reply_markup=kb)
    else:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад", callback_data=f"select_chat_{chat_id}")]
            ]
        )
        await callback.message.answer("Модераторы не найдены.", reply_markup=kb)
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
    await callback.message.answer("Введите ник(и) модераторов через пробел (@username):")
    await callback.answer()

@dp.message()
async def user_text_handler(message: types.Message):
    st = user_state.get(message.from_user.id)
    if not st:
        return
    
    # Проверка сообщения
    if st['action'] == 'check_message':
        user_state.pop(message.from_user.id)
        await process_message_check(message)
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
    print("=" * 60)
    print("🔧 TELEGUARD BOT - ГОТОВЫЙ ACCESS TOKEN + ПРОВЕРКА СООБЩЕНИЙ")
    print("=" * 60)
    print("🔑 Access Token встроен в код и готов к использованию!")
    print(f"📏 Длина токена: {len(GIGACHAT_ACCESS_TOKEN)} символов")
    print()
    print("🤖 Возможности:")
    print("   • Мониторинг всех 5 агентов")
    print("   • Статус каждого агента в реальном времени")
    print("   • 🧪 НОВИНКА: Проверка сообщений на банить/не банить")
    print("   • Подробная системная информация")
    print("   • Улучшенный интерфейс с кнопками")
    print()
    print("🧪 Новая функция 'Проверить сообщение':")
    print("   • Анализ через Агент №3 (GigaChat AI)")
    print("   • Анализ через Агент №4 (Эвристика)")
    print("   • Финальное решение от Агента №5")
    print("   • Детальный отчет с уверенностью")
    print()
    print("🌐 Порты агентов:")
    for agent_id, agent_info in AGENTS_CONFIG.items():
        print(f"   • {agent_info['name']}: порт {agent_info['port']}")
    print()
    print("⏰ Примечание: Access Token может истечь через ~30 минут")
    print("🔄 При истечении получите новый токен через get_gigachat_token.py")
    print()
    print("🚀 Запускаем бота...")
    print("=" * 60)
    
    asyncio.run(main())
