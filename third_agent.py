#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
АГЕНТ 3.2 — Модерация с GigaChat (Обновленные токены)
"""

import requests
import json
import redis
import time
import logging
from typing import Dict, Any
import urllib3
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey, BigInteger, Text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
import asyncio

# Отключаем warning SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============================================================================
# ЛОГИРОВАНИЕ
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [АГЕНТ 3] %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# КОНФИГУРАЦИЯ БД
# ============================================================================
POSTGRES_URL = 'postgresql://tguser:mnvm7110@176.108.248.211:5432/teleguard_db?sslmode=disable'

# ============================================================================
# КОНФИГУРАЦИЯ GIGACHAT (ОБНОВЛЕННЫЕ ТОКЕНЫ)
# ============================================================================
ACCESS_TOKEN = "eyJjdHkiOiJqd3QiLCJlbmMiOiJBMjU2Q0JDLUhTNTEyIiwiYWxnIjoiUlNBLU9BRVAtMjU2In0.rDxqb5-B5a_phZFd_mbBuuOMjeIpHbBOAssZ1M0j3K9F7wbJyn4wFxURTUKhZo8XKc4bUlW5V0LAI3QkwkGQIHJtznCS7Ij8PH41S1eWyHySMFo9u96zcFJApzKuoxXgmzsGk1Ibx5sEt8yQzqVcgqcXecM-S2rjifP849RZPbwbe1AAWP_8fIyasrQ7eNXXCYKgqfuCh6GWYuKglyC3ZSxnvjgRikGgWASbGG5qW5QzVg-dxqWel61rNuvZUUletTYlwY049WVoMgw1ziKQc6LlglqWul6IrTmKF-dcQYs_BB7GIfsRKVAitc3PA_zbpCOKJ-GdolYi0H3hhvgjbA.YuvTziLeup589XJTMqbv0A.NFbeLLa6eNvXCfhUW4DoqFhoZN-svSrNRt6v3qDnVDWuQTHT_AjddmtWa2ANIELs9dnuNPeuwVLM01pK8I8cgdAuWc1RtPsaok7ESx9CYvQBb3VWZAOy5h9p32Khg2B1yyZbL1kuEnEblvBJQTUUkzj3qNO2bIyb0InTdHIDLessLW_RIfWkhZWc7eia_I92MVvMem0WGl9iynlPl-hmsqOB_tGmzRDTH-aqv2f76EHOWFE1DMxcgh7EJLhHNrDHwygA_1jrylvhjLBJEfJWEbLMAThQ1emaJu9Dx30Kb8alCUz0nB6Bfw9E9xG5iQJPyX19s3WdcBPe9DAno3NrjkYDVgCh9G9qCDLYhx4pvhhh3mtd_IXaUstqPPk-vMOqAhVv64Yy-ZeYBnXEhcqXLt5UgD41Cm-ETCqAoGNVWpN-IYziuRRavN3AAivg-FZIRobN2OOhlahPkLyvOaLyVC5oCnEFSxZfkofnC5yafUs3dsQZ7X4Bmhx199k9cvLRBToFyTkWg6doJlSt_0Tg2cUm-4z-4JO1V48GoFlg7Tco8Sg3pLbH2teZMg8x3pR2EuJi7tS6W_JBEo-X3mUEdvOOcpw6j9VWDQ-nDAz6BHOdf6xKW_jqj64RdeGNbXzPDVwtsia2kZPvf0KhhhlHDKwVupgoPgxC4a6aE8Bl_8R71AW2x45U9rCnyTl050CBg1ufapBTfIY4j88zo2-3nNqAVdvDCLuhj4szO4ovg-Y.dwx2dXz4CSDmkDlUzkzee_NpyZJY7No-RyOq6VupZwE"
AUTH_TOKEN = "ODE5YTgxODUtMzY2MC00NDM5LTgxZWItYzU1NjVhODgwOGVkOmZmNWEyN2RjLWFlZmMtNGY0NC1hNmJlLTAzZmNiOTc0MjJkMg=="

# ============================================================================
# КОНФИГУРАЦИЯ REDIS
# ============================================================================
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0
REDIS_PASSWORD = None

# Очереди для взаимодействия с другими агентами
QUEUE_AGENT_3_INPUT = "queue:agent3:input"
QUEUE_AGENT_3_OUTPUT = "queue:agent3:output"
QUEUE_AGENT_4_INPUT = "queue:agent4:input"
QUEUE_AGENT_5_INPUT = "queue:agent5:input"

# ============================================================================
# МОДЕЛИ БД (ЕДИНЫЕ ДЛЯ ВСЕХ АГЕНТОВ)
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
    agent_id = Column(Integer) # Какой агент отметил как негативное
    
    chat = relationship('Chat', back_populates='negative_messages')

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ БД И REDIS
# ============================================================================
engine = create_engine(POSTGRES_URL)
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)

def get_db_session():
    return SessionLocal()

# ============================================================================
# СПИСОК НЕЦЕНЗУРНЫХ СЛОВ (для дополнительной проверки)
# ============================================================================
PROFANITY_WORDS = [
    "сука", "чурка", "дурак", "идиот", "тупой", "долбоеб", "мудак",
    "хуй", "пизд", "ебан", "бля", "гандон", "уебок", "чмо", "дебил",
    "даун", "урод", "мразь", "быдло", "козел", "свинья", "сволочь"
]

DISCRIMINATION_WORDS = [
    "чурка", "хохол", "москаль", "жид", "негр", "азиат",
    "узкоглазый", "черножопый", "чучмек"
]

# ============================================================================
# РАБОТА С GIGACHAT API
# ============================================================================
def check_profanity_simple(message):
    """
    Простая проверка на нецензурные слова (дополнительная фильтрация).
    Возвращает True если найдена нецензурщина.
    """
    message_lower = message.lower()
    for word in PROFANITY_WORDS + DISCRIMINATION_WORDS:
        if word in message_lower:
            return True, f"Обнаружено запрещённое слово: '{word}'"
    return False, ""

def check_message_with_gigachat(message, rules, prompt, token):
    """
    Отправляет запрос в GigaChat API для анализа сообщения.
    """
    url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
    
    rules_text = "\n".join([f"{i+1}. {rule}" for i, rule in enumerate(rules)])
    system_msg = f"""Ты — строгий модератор Telegram-канала.
ПРАВИЛА ЧАТА:
{rules_text}

{prompt}"""
    
    user_msg = f"Сообщение пользователя:\n\"{message}\""
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": "GigaChat",
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ],
        "temperature": 0.1,
        "max_tokens": 300
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=30, verify=False)
        response.raise_for_status()
        result = response.json()
        content = result["choices"][0]["message"]["content"]
        return content
    except Exception as e:
        error_msg = f"Ошибка при запросе к GigaChat: {e}"
        logger.error(error_msg)
        return error_msg

def parse_gigachat_response(text, message):
    """
    Парсит ответ GigaChat и определяет, нужен ли бан.
    """
    text_lower = text.lower()
    
    # Сначала проверяем простым поиском по словам
    has_profanity, profanity_reason = check_profanity_simple(message)
    if has_profanity:
        return {
            "ban": True,
            "reason": f"Вердикт: да. {profanity_reason} (Автоматическая фильтрация)"
        }
    
    # Ключевые слова для BAN
    ban_keywords = [
        "вердикт: да", "вердикт:да", "вердикт да",
        "нарушение", "нарушает", "забанить", "блокировать",
        "оскорбление", "мат", "нецензурн", "дискриминация"
    ]
    
    # Ключевые слова для НЕТ BAN
    no_ban_keywords = [
        "вердикт: нет", "вердикт:нет", "вердикт нет",
        "нет нарушений", "не нарушает", "правила соблюдены",
        "нарушений не", "не обнаружено"
    ]
    
    # Проверяем ответ GigaChat
    has_ban_words = any(word in text_lower for word in ban_keywords)
    has_no_ban_words = any(word in text_lower for word in no_ban_keywords)
    
    # Логика принятия решения
    if has_no_ban_words and not has_ban_words:
        ban = False
    elif has_ban_words:
        ban = True
    else:
        # Если непонятно — по умолчанию НЕ БАНИТЬ
        ban = False
    
    return {
        "ban": ban,
        "reason": text.strip()
    }

# ============================================================================
# ОСНОВНАЯ ЛОГИКА АГЕНТА 3
# ============================================================================
def moderation_agent_3(input_data, db_session):
    """
    АГЕНТ 3 — Независимый модератор с усиленной проверкой.
    Сохраняет результаты в БД и отправляет в Redis для других агентов.
    """
    message = input_data.get("message", "")
    rules = input_data.get("rules", [])
    user_id = input_data.get("user_id")
    username = input_data.get("username")
    chat_id = input_data.get("chat_id")
    message_id = input_data.get("message_id")
    message_link = input_data.get("message_link", "")
    
    logger.info(f"Анализирую сообщение от @{username} в чате {chat_id}")
    
    if not message:
        return {
            "agent_id": 3,
            "ban": False,
            "reason": "Ошибка: пустое сообщение",
            "message": "",
            "user_id": user_id,
            "username": username,
            "chat_id": chat_id,
            "message_id": message_id,
            "status": "error"
        }
    
    if not rules:
        return {
            "agent_id": 3,
            "ban": False,
            "reason": "Ошибка: правила не переданы",
            "message": message,
            "user_id": user_id,
            "username": username,
            "chat_id": chat_id,
            "message_id": message_id,
            "status": "error"
        }
    
    token = ACCESS_TOKEN
    if not token:
        return {
            "agent_id": 3,
            "ban": False,
            "reason": "Ошибка: отсутствует access token",
            "message": message,
            "user_id": user_id,
            "username": username,
            "chat_id": chat_id,
            "message_id": message_id,
            "status": "error"
        }
    
    # Промпт для GigaChat
    prompt = """
ТВОЯ ЗАДАЧА:
Проанализируй сообщение и определи, нарушает ли оно ЛЮБОЕ из правил выше.

КРИТЕРИИ ПРОВЕРКИ:
✓ Нецензурные слова, маты, оскорбления
✓ Дискриминация по национальности, расе, религии
✓ Реклама сторонних каналов/групп
✓ Спам, флуд
✓ Агрессия, угрозы

ИНСТРУКЦИИ:
1. Если в сообщении есть ХОТЯ БЫ ОДНО нарушение — вердикт "да"
2. Будь СТРОГИМ: даже завуалированные оскорбления — это нарушение
3. Если сомневаешься — лучше забанить (безопасность чата важнее)

ФОРМАТ ОТВЕТА (строго):
Вердикт: да/нет
Причина: [конкретное объяснение]

НАЧИНАЙ АНАЛИЗ:"""
    
    # Получаем вердикт от GigaChat
    verdict_text = check_message_with_gigachat(message, rules, prompt, token)
    logger.info(f"Ответ GigaChat получен")
    
    # Парсим ответ
    result = parse_gigachat_response(verdict_text, message)
    
    output = {
        "agent_id": 3,
        "ban": result["ban"],
        "reason": result["reason"],
        "message": message,
        "user_id": user_id,
        "username": username,
        "chat_id": chat_id,
        "message_id": message_id,
        "message_link": message_link,
        "status": "success",
        "confidence": 0.85 if result["ban"] else 0.8,
        "timestamp": datetime.now().isoformat()
    }
    
    # Сохраняем исходное сообщение в БД
    try:
        chat = db_session.query(Chat).filter_by(tg_chat_id=str(chat_id)).first()
        if not chat:
            chat = Chat(tg_chat_id=str(chat_id))
            db_session.add(chat)
            db_session.commit()
        
        # Проверяем существующее сообщение
        existing_message = db_session.query(Message).filter_by(
            chat_id=chat.id, 
            message_id=message_id
        ).first()
        
        if existing_message:
            # Обновляем AI response
            existing_message.ai_response = result["reason"]
            existing_message.processed_at = datetime.utcnow()
        else:
            # Создаем новое сообщение
            message_obj = Message(
                chat_id=chat.id,
                message_id=message_id,
                sender_username=username,
                sender_id=user_id,
                message_text=message,
                message_link=message_link,
                ai_response=result["reason"],
                processed_at=datetime.utcnow()
            )
            db_session.add(message_obj)
        
        db_session.commit()
        
        # Если обнаружено нарушение — сохраняем в negative_messages
        if result["ban"]:
            negative_msg = NegativeMessage(
                chat_id=chat.id,
                message_link=message_link,
                sender_username=username,
                sender_id=user_id,
                negative_reason=result["reason"],
                agent_id=3,
                is_sent_to_moderators=False
            )
            db_session.add(negative_msg)
            db_session.commit()
            logger.warning(f"БАН ⛔ для @{username}: {result['reason'][:50]}...")
        else:
            logger.info(f"ОК ✅ для @{username}")
            
    except Exception as e:
        logger.error(f"Ошибка при сохранении в БД: {e}")
        output["db_error"] = str(e)
    
    return output

# ============================================================================
# РАБОТА С REDIS И ВЗАИМОДЕЙСТВИЕ МЕЖДУ АГЕНТАМИ
# ============================================================================
class Agent3Worker:
    def __init__(self):
        try:
            redis_config = {
                "host": REDIS_HOST,
                "port": REDIS_PORT,
                "db": REDIS_DB,
                "password": REDIS_PASSWORD,
                "decode_responses": True
            }
            self.redis_client = redis.Redis(**redis_config)
            self.redis_client.ping()
            logger.info(f"✅ Подключение к Redis успешно: {REDIS_HOST}:{REDIS_PORT}")
        except Exception as e:
            logger.error(f"❌ Не удалось подключиться к Redis: {e}")
            raise
    
    def process_message(self, message_data, db_session):
        """Обрабатывает сообщение от входной очереди"""
        try:
            input_data = json.loads(message_data)
            result = moderation_agent_3(input_data, db_session)
            return result
        except json.JSONDecodeError as e:
            logger.error(f"Невалидный JSON: {e}")
            return {
                "agent_id": 3,
                "ban": False,
                "reason": f"Ошибка парсинга данных: {e}",
                "message": "",
                "status": "json_error"
            }
        except Exception as e:
            logger.error(f"Ошибка обработки сообщения: {e}")
            return {
                "agent_id": 3,
                "ban": False,
                "reason": f"Внутренняя ошибка агента 3: {e}",
                "message": "",
                "status": "error"
            }
    
    def send_result(self, result):
        """Отправляет результат в выходную очередь"""
        try:
            result_json = json.dumps(result, ensure_ascii=False)
            # Отправляем результат в очередь Агента 3
            self.redis_client.rpush(QUEUE_AGENT_3_OUTPUT, result_json)
            
            # Если обнаружено нарушение, отправляем также в очередь Агента 5
            if result.get("ban"):
                self.redis_client.rpush(QUEUE_AGENT_5_INPUT, result_json)
                logger.info(f"✅ Результат отправлен Агенту 5")
            
            logger.info(f"✅ Результат отправлен в очередь")
            
        except Exception as e:
            logger.error(f"Не удалось отправить результат: {e}")
    
    def run(self):
        """Главный цикл обработки сообщений"""
        logger.info(f"✅ Запущен. Ожидаю сообщения из: {QUEUE_AGENT_3_INPUT}")
        logger.info(f"   Отправляю результаты в: {QUEUE_AGENT_3_OUTPUT}")
        logger.info(f"   Отправляю в Агента 5: {QUEUE_AGENT_5_INPUT}")
        logger.info("   Нажмите Ctrl+C для остановки\n")
        
        db_session = None
        try:
            while True:
                try:
                    result = self.redis_client.blpop(QUEUE_AGENT_3_INPUT, timeout=1)
                    if result is None:
                        continue
                    
                    queue_name, message_data = result
                    logger.info(f"📨 Получено сообщение")
                    
                    # Создаем новую сессию БД для каждого сообщения
                    db_session = get_db_session()
                    output = self.process_message(message_data, db_session)
                    self.send_result(output)
                    db_session.close()
                    
                    logger.info(f"✅ Обработка завершена\n")
                    
                except Exception as e:
                    logger.error(f"Ошибка в цикле: {e}")
                    if db_session:
                        db_session.close()
                    time.sleep(1)
                    
        except KeyboardInterrupt:
            logger.info("\n❌ Агент 3 остановлен (Ctrl+C)")
        finally:
            if db_session:
                db_session.close()
            logger.info("Агент 3 завершил работу")

# ============================================================================
# HEALTH CHECK ENDPOINT
# ============================================================================
def create_health_check_server():
    """Создает простой HTTP сервер для проверки здоровья агента"""
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import threading
    
    class HealthCheckHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/health':
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                health_info = {
                    "status": "online",
                    "agent_id": 3,
                    "name": "Агент №3 (GigaChat)",
                    "version": "3.2",
                    "timestamp": datetime.now().isoformat(),
                    "redis_queue": QUEUE_AGENT_3_INPUT,
                    "uptime_seconds": int(time.time())
                }
                self.wfile.write(json.dumps(health_info, ensure_ascii=False).encode())
            else:
                self.send_response(404)
                self.end_headers()
        
        def log_message(self, format, *args):
            # Подавляем логирование HTTP запросов
            pass
    
    server = HTTPServer(('localhost', 8003), HealthCheckHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("✅ Health check сервер запущен на порту 8003")

# ============================================================================
# ТОЧКА ВХОДА
# ============================================================================
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        mode = sys.argv[1]
        if mode == "test":
            # Тестирование
            test_input = {
                "message": "сука чурка",
                "rules": [
                    "Запрещена реклама",
                    "Запрещены нецензурные выражения",
                    "Запрещена дискриминация"
                ],
                "user_id": 123,
                "username": "test_user",
                "chat_id": -100,
                "message_id": 1,
                "message_link": "https://t.me/test/1"
            }
            
            db_session = get_db_session()
            result = moderation_agent_3(test_input, db_session)
            db_session.close()
            print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        # Запуск основного цикла обработки
        try:
            create_health_check_server()
            worker = Agent3Worker()
            worker.run()
        except KeyboardInterrupt:
            logger.info("Выход из программы")
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")