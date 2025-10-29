#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
АГЕНТ №4 — Эвристический модератор (Исправленная версия)
"""

import requests
import json
import redis
import time
import logging
import re
from typing import Dict, Any, List, Optional, Tuple
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
    format='[%(asctime)s] [АГЕНТ 4] %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# КОНФИГУРАЦИЯ БД (ОДИНАКОВАЯ С АГЕНТОМ 3.2)
# ============================================================================
POSTGRES_URL = 'postgresql://tguser:mnvm7110@176.108.248.211:5432/teleguard_db?sslmode=disable'

# ============================================================================
# КОНФИГУРАЦИЯ REDIS
# ============================================================================
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0
REDIS_PASSWORD = None

# Очереди для взаимодействия с другими агентами
QUEUE_AGENT_4_INPUT = "queue:agent4:input"
QUEUE_AGENT_4_OUTPUT = "queue:agent4:output"
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

# ============================================================================
# ЭВРИСТИЧЕСКИЙ АНАЛИЗАТОР
# ============================================================================
class HeuristicAnalyzer:
    """
    Эвристический анализатор сообщений для Агента 4.
    Использует правила, паттерны и regex для анализа без ИИ.
    """
    
    def __init__(self):
        # Паттерны для обнаружения спама/рекламы
        self.spam_patterns = [
            r'вступай(те)?\\s+в\\s+(наш|наша|мой)',
            r'подпис(ыв)?ай(ся|тесь)?\\s+(на|в)',
            r'переход(и(те)?)?\\s+по\\s+ссылке', 
            r'жми\\s+(сюда|тут|на\\s+ссылку)',
            r'@\\w+',  # Упоминание других каналов
            r'https?://\\S+',  # Ссылки
            r't\\.me/\\S+',  # Telegram ссылки
        ]
        
        # Паттерны оскорблений
        self.insult_patterns = [
            r'\\b(идиот|дурак|тупой|глупый|мудак)\\b',
            r'\\b(придурок|дебил|имбецил|кретин)\\b',
            r'\\b(урод|мразь|быдло|козел|свинья)\\b'
        ]
        
        # Паттерны нецензурной лексики
        self.profanity_patterns = [
            r'\\b(сука|хуй|пизд|ебать|бля|блять)\\b',
            r'\\b(гандон|уебок|чмо|долбоеб)\\b'
        ]
        
        # Паттерны дискриминации
        self.discrimination_patterns = [
            r'\\b(чурка|хохол|москаль|жид|негр)\\b',
            r'\\b(узкоглазый|черножопый|чучмек)\\b'
        ]
        
        # Паттерны флуда
        self.flood_patterns = [
            r'([А-Яа-я])\\1{4,}',  # Повторяющиеся символы
            r'[!?]{3,}',  # Много знаков препинания
            r'[A-ZА-Я]{10,}',  # КАПС
        ]
    
    def check_spam(self, message: str) -> Tuple[bool, str]:
        """Проверка на спам и рекламу"""
        message_lower = message.lower()
        for pattern in self.spam_patterns:
            if re.search(pattern, message_lower):
                return True, f"Обнаружена реклама/спам (паттерн: {pattern})"
        
        # Проверка на количество ссылок
        links_count = len(re.findall(r'https?://|t\\.me/', message_lower))
        if links_count >= 2:
            return True, f"Множественные ссылки ({links_count} шт.) - признак спама"
        
        # Проверка на упоминание нескольких каналов
        mentions = re.findall(r'@\\w+', message)
        if len(mentions) >= 2:
            return True, f"Упоминание нескольких каналов ({len(mentions)} шт.)"
        
        return False, ""
    
    def check_insults(self, message: str) -> Tuple[bool, str]:
        """Проверка на оскорбления"""
        message_lower = message.lower()
        for pattern in self.insult_patterns:
            match = re.search(pattern, message_lower)
            if match:
                return True, f"Обнаружено оскорбление: '{match.group()}'"
        return False, ""
    
    def check_profanity(self, message: str) -> Tuple[bool, str]:
        """Проверка на нецензурную лексику"""
        message_lower = message.lower()
        for pattern in self.profanity_patterns:
            match = re.search(pattern, message_lower)
            if match:
                return True, f"Обнаружена нецензурная лексика: '{match.group()}'"
        return False, ""
    
    def check_discrimination(self, message: str) -> Tuple[bool, str]:
        """Проверка на дискриминацию"""
        message_lower = message.lower()
        for pattern in self.discrimination_patterns:
            match = re.search(pattern, message_lower)
            if match:
                return True, f"Обнаружена дискриминация: '{match.group()}'"
        return False, ""
    
    def check_flood(self, message: str) -> Tuple[bool, str]:
        """Проверка на флуд"""
        for pattern in self.flood_patterns:
            match = re.search(pattern, message)
            if match:
                return True, f"Обнаружен флуд: '{match.group()}'"
        
        # Проверка на очень короткие повторяющиеся сообщения
        if len(message) < 3:
            return True, "Слишком короткое сообщение (возможный флуд)"
        
        return False, ""
    
    def analyze(self, message: str, rules: List[str]) -> Dict[str, Any]:
        """
        Основной метод анализа сообщения.
        """
        if not message or not message.strip():
            return {
                "ban": False,
                "reason": "Пустое сообщение - нет оснований для бана"
            }
        
        violations = []
        
        # Проверяем все типы нарушений способом, который НАХОДИТ все нарушения тестов
        checks = [
            ("спам/реклама", self.check_spam),
            ("оскорбления", self.check_insults),
            ("нецензурная лексика", self.check_profanity),
            ("дискриминация", self.check_discrimination),
            ("флуд", self.check_flood)
        ]
        
        for check_name, check_func in checks:
            is_violation, reason = check_func(message)
            if is_violation:
                violations.append(f"[{check_name.upper()}] {reason}")
        
        if violations:
            return {
                "ban": True,
                "reason": f"Вердикт: да. Обнаружены нарушения: {' | '.join(violations)}"
            }
        else:
            return {
                "ban": False,
                "reason": "Вердикт: нет. Нарушений не обнаружено. Сообщение соответствует правилам чата."
            }

# ============================================================================
# ОСНОВНАЯ ЛОГИКА АГЕНТА 4
# ============================================================================
def moderation_agent_4(input_data, db_session):
    """
    АГЕНТ 4 — Эвристический модератор.
    Использует правила и паттерны для анализа без ИИ.
    """
    message = input_data.get("message", "")
    rules = input_data.get("rules", [])
    user_id = input_data.get("user_id")
    username = input_data.get("username")
    chat_id = input_data.get("chat_id")
    message_id = input_data.get("message_id")
    message_link = input_data.get("message_link", "")
    
    logger.info(f"Анализирую сообщение от @{username} в чате {chat_id} (эвристический анализ)")
    
    if not message:
        return {
            "agent_id": 4,
            "ban": False,
            "reason": "Ошибка: пустое сообщение",
            "message": "",
            "user_id": user_id,
            "username": username,
            "chat_id": chat_id,
            "message_id": message_id,
            "status": "error"
        }
    
    # Эвристический анализ
    analyzer = HeuristicAnalyzer()
    result = analyzer.analyze(message, rules)
    
    output = {
        "agent_id": 4,
        "ban": result["ban"],
        "reason": result["reason"],
        "message": message,
        "user_id": user_id,
        "username": username,
        "chat_id": chat_id,
        "message_id": message_id,
        "message_link": message_link,
        "status": "success",
        "confidence": 0.75 if result["ban"] else 0.8,  # Эвристика менее уверена чем ИИ
        "timestamp": datetime.now().isoformat()
    }
    
    # Сохраняем в БД (аналогично Агенту 3)
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
            existing_response = existing_message.ai_response or ""
            existing_message.ai_response = f"{existing_response}\n[АГЕНТ 4] {result['reason']}"
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
                agent_id=4,
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
# РАБОТА С REDIS
# ============================================================================
class Agent4Worker:
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
            result = moderation_agent_4(input_data, db_session)
            return result
        except json.JSONDecodeError as e:
            logger.error(f"Невалидный JSON: {e}")
            return {
                "agent_id": 4,
                "ban": False,
                "reason": f"Ошибка парсинга данных: {e}",
                "message": "",
                "status": "json_error"
            }
        except Exception as e:
            logger.error(f"Ошибка обработки сообщения: {e}")
            return {
                "agent_id": 4,
                "ban": False,
                "reason": f"Внутренняя ошибка агента 4: {e}",
                "message": "",
                "status": "error"
            }
    
    def send_result(self, result):
        """Отправляет результат в выходную очередь"""
        try:
            result_json = json.dumps(result, ensure_ascii=False)
            # Отправляем результат в очередь Агента 4
            self.redis_client.rpush(QUEUE_AGENT_4_OUTPUT, result_json)
            
            # Если обнаружено нарушение, отправляем также в очередь Агента 5
            if result.get("ban"):
                self.redis_client.rpush(QUEUE_AGENT_5_INPUT, result_json)
                logger.info(f"✅ Результат отправлен Агенту 5")
            
            logger.info(f"✅ Результат отправлен в очередь")
            
        except Exception as e:
            logger.error(f"Не удалось отправить результат: {e}")
    
    def run(self):
        """Главный цикл обработки сообщений"""
        logger.info(f"✅ Запущен. Ожидаю сообщения из: {QUEUE_AGENT_4_INPUT}")
        logger.info(f"   Отправляю результаты в: {QUEUE_AGENT_4_OUTPUT}")
        logger.info(f"   Отправляю в Агента 5: {QUEUE_AGENT_5_INPUT}")
        logger.info("   Нажмите Ctrl+C для остановки\n")
        
        db_session = None
        try:
            while True:
                try:
                    result = self.redis_client.blpop(QUEUE_AGENT_4_INPUT, timeout=1)
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
            logger.info("\n❌ Агент 4 остановлен (Ctrl+C)")
        finally:
            if db_session:
                db_session.close()
            logger.info("Агент 4 завершил работу")

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
                    "agent_id": 4,
                    "name": "Агент №4 (Эвристический)",
                    "version": "4.0",
                    "timestamp": datetime.now().isoformat(),
                    "redis_queue": QUEUE_AGENT_4_INPUT,
                    "uptime_seconds": int(time.time())
                }
                self.wfile.write(json.dumps(health_info, ensure_ascii=False).encode())
            else:
                self.send_response(404)
                self.end_headers()
        
        def log_message(self, format, *args):
            # Подавляем логирование HTTP запросов
            pass
    
    server = HTTPServer(('localhost', 8004), HealthCheckHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("✅ Health check сервер запущен на порту 8004")

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
                "message": "Идиот, сука, хуй тебе в жопу!",
                "rules": [
                    "Запрещена реклама",
                    "Запрещены нецензурные выражения",
                    "Запрещены оскорбления",
                    "Запрещена дискриминация"
                ],
                "user_id": 456,
                "username": "toxic_user",
                "chat_id": -200,
                "message_id": 2,
                "message_link": "https://t.me/test/2"
            }
            
            db_session = get_db_session()
            result = moderation_agent_4(test_input, db_session)
            db_session.close()
            print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        # Запуск основного цикла обработки
        try:
            create_health_check_server()
            worker = Agent4Worker()
            worker.run()
        except KeyboardInterrupt:
            logger.info("Выход из программы")
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")