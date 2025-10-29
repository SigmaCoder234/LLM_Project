#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
АГЕНТ №1 — Координатор и нормализатор (Обновленная версия)
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
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import threading

# Отключаем warning SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============================================================================
# ЛОГИРОВАНИЕ
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [АГЕНТ 1] %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# КОНФИГУРАЦИЯ БД (ОДИНАКОВАЯ С АГЕНТОМ 3.4)
# ============================================================================
POSTGRES_URL = 'postgresql://tguser:mnvm7110@176.108.248.211:5432/teleguard_db?sslmode=disable'

# ============================================================================
# КОНФИГУРАЦИЯ GIGACHAT
# ============================================================================
ACCESS_TOKEN = "eyJjdHkiOiJqd3QiLCJlbmMiOiJBMjU2Q0JDLUhTNTEyIiwiYWxnIjoiUlNBLU9BRVAtMjU2In0.cv8YybaNK-3R-ALyaWB-AY1LGRKY8SBOguCeMJBYw4lYG9hdr8TS9nzY2xzOfMP0vX7jKrQ3rqxLOgj8IoDjxD9UL3HZlO1jhH75DoxvU68jHA0_5w_WNr6A82d3qvm2-2bdNkUp9eGwblY4I56eKdodRjJ2vscy9GrITu1lOPgzqP0ZI7D8wt_mqQyZjPEyMhmBqZcW7rExwN8ILaU36KysispjvBHZWKAcF77F4WOvmN0VAbs1ifmHUkWZY3g9gTJdpET2IP0k6u5i78rIX58eOTkCosIG19Il4byFf20GcluSMpKAZkdFXTkK6LBDQK-CD18-ZGCsMWaKthWFWg.My7TQEvIVBXO5vRZkmFoXA.T61aZMMnfFKNy-LEtbwYXuSaQfia6b_kUYvaiuqmcgVcRzfwsqOG7EFyuc_c60HCXR3_TueE_MEr49z92SVUOuTponbfzf54vartyhqnmPzHQvdD-57Ko8gQxAKojRXWBGGKTeCLFwPRtjkPWhAel9M1y0G0exRcwFfnHkEBG2EFJDHvtnmlFnkGf-cfWDn9AliObQj7LA6WTO5j_xTIgpJMeIcgb0-KGonYw_UUfkUeFUC2-bwcZpGDDW1PvG05_Seh1tfu6J60U_xtB8TpxAlWpucUbmf71Ka1lFstkRhQcrEB2DkTOztPbErkX7XcHVM_BeYPm8jeFcSLF6C-euS4Z2YMYmmwzMuOOD1Th3DcKABpnAs9FrUUOLM2zGHXGJxKPx5JbYTRUrzibqqMk0d4xywjTpgY7I0Xc7mh2JkpFAUjnClS-x9QwwW0UXZ_tFjSoCovNmitDHkv9cXkkXhhFvQ-QBLQ7ittBVRUUG4LgdY8KtoHMVT6CsoCDz6fwO2Wc55XYvjFeI24hla2unWFdcGG8ab2KjVhlsFZq9i2XIp1LryLx3xGgGP_1K9txHCxSDlQf5M5uKmtnCPawnl2W1bkpthTSPaoV_xmeRIr465B8dDR29SjSHIAeMrOamYDncyWkLvA-wc93teYgJ1EBqrP6zkKF_HiDpTtKns5ZABjF0BzJAjc3f_FlLDQOCYWhrwcnjNBf600-IDGdAxVq6mflPIOBvbimZc_QxQ.3mGdrfeOVuD6xYscptelPxZ7VHE-cys6w4psXGX5V7I"
AUTH_TOKEN = "ODE5YTgxODUtMzY2MC00NDM5LTgxZWItYzU1NjVhODgwOGVkOmE0MzRhNjExLTE2NGYtNDdjYS1iNTM2LThlMGViMmU0YzVmNg=="

# ============================================================================
# КОНФИГУРАЦИЯ REDIS
# ============================================================================
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0
REDIS_PASSWORD = None

# Очереди для взаимодействия с другими агентами
QUEUE_AGENT_1_INPUT = "queue:agent1:input"
QUEUE_AGENT_2_INPUT = "queue:agent2:input"
QUEUE_TELEGRAM_INPUT = "queue:telegram:input"

# ============================================================================
# МОДЕЛИ БД (ТОЧНО ТЕ ЖЕ ЧТО В АГЕНТЕ 3.4)
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
# НОРМАЛИЗАЦИЯ И ОБРАБОТКА ТЕКСТА
# ============================================================================
def normalize_text(text: str) -> str:
    """Нормализует текст для лучшего анализа"""
    if not text:
        return ""
    
    # Базовая нормализация
    text = text.strip().lower()
    
    # Убираем лишние пробелы
    import re
    text = re.sub(r'\s+', ' ', text)
    
    return text

def extract_rules_from_chat(chat_id: int, db_session) -> list:
    """Извлекает правила чата из БД или использует дефолтные"""
    try:
        chat = db_session.query(Chat).filter_by(tg_chat_id=str(chat_id)).first()
        if chat:
            # В будущем здесь можно добавить поле с правилами в модель Chat
            # Пока используем дефолтные правила
            pass
    except:
        pass
    
    # Дефолтные правила
    return [
        "Запрещена реклама сторонних сообществ и каналов",
        "Запрещены нецензурные выражения и оскорбления участников",
        "Запрещена дискриминация по любым признакам (национальность, раса, религия)",
        "Запрещен спам, флуд и бессмысленные сообщения",
        "Запрещены угрозы и призывы к насилию"
    ]

# ============================================================================
# GIGACHAT ИНТЕГРАЦИЯ ДЛЯ ПРЕДВАРИТЕЛЬНОГО АНАЛИЗА
# ============================================================================
def analyze_with_gigachat(message: str, rules: list, token: str) -> dict:
    """Предварительный анализ сообщения через GigaChat"""
    url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
    
    rules_text = "\n".join([f"{i+1}. {rule}" for i, rule in enumerate(rules)])
    system_msg = f"""Ты — предварительный анализатор сообщений для модерации.
    
ПРАВИЛА ЧАТА:
{rules_text}

ТВОЯ ЗАДАЧА:
Сделай БЫСТРУЮ предварительную оценку сообщения и дай рекомендацию:
- SKIP - сообщение точно безопасно, дальнейший анализ не нужен
- ANALYZE - сообщение нуждается в детальном анализе агентами 3 и 4
- PRIORITY - срочное нарушение, высокий приоритет для анализа

КРИТЕРИИ:
- Очевидно безопасные сообщения (приветствия, вопросы по теме) → SKIP
- Подозрительные или неоднозначные → ANALYZE  
- Явные нарушения (мат, угрозы, реклама) → PRIORITY

Ответ строго в формате: "РЕКОМЕНДАЦИЯ: [SKIP/ANALYZE/PRIORITY] - [краткое объяснение]"""
    
    user_msg = f"Сообщение: \"{message}\""
    
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
        "max_tokens": 150
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=15, verify=False)
        response.raise_for_status()
        result = response.json()
        content = result["choices"][0]["message"]["content"]
        
        # Парсим рекомендацию
        content_lower = content.lower()
        if "skip" in content_lower:
            recommendation = "SKIP"
            priority = 0
        elif "priority" in content_lower:
            recommendation = "PRIORITY"
            priority = 2
        else:
            recommendation = "ANALYZE"
            priority = 1
            
        return {
            "recommendation": recommendation,
            "priority": priority,
            "reasoning": content,
            "status": "success"
        }
        
    except Exception as e:
        logger.error(f"Ошибка GigaChat анализа: {e}")
        # При ошибке всегда анализируем
        return {
            "recommendation": "ANALYZE",
            "priority": 1,
            "reasoning": f"Ошибка предварительного анализа: {e}",
            "status": "error"
        }

# ============================================================================
# ОСНОВНАЯ ЛОГИКА АГЕНТА 1
# ============================================================================
def coordination_agent_1(input_data, db_session):
    """
    АГЕНТ 1 — Координатор и нормализатор.
    Принимает сообщения, нормализует их и принимает решение о дальнейшей обработке.
    """
    message = input_data.get("message", "")
    user_id = input_data.get("user_id")
    username = input_data.get("username", "")
    chat_id = input_data.get("chat_id")
    message_id = input_data.get("message_id")
    message_link = input_data.get("message_link", "")
    
    logger.info(f"Координирую сообщение от @{username} в чате {chat_id}")
    
    if not message:
        return {
            "agent_id": 1,
            "action": "skip",
            "reason": "Пустое сообщение",
            "message": "",
            "user_id": user_id,
            "username": username,
            "chat_id": chat_id,
            "message_id": message_id,
            "status": "skipped"
        }
    
    # Нормализация текста
    normalized_message = normalize_text(message)
    
    # Получаем правила чата
    rules = extract_rules_from_chat(chat_id, db_session)
    
    # Предварительный анализ через GigaChat
    analysis = analyze_with_gigachat(message, rules, ACCESS_TOKEN)
    
    # Сохраняем сообщение в БД
    try:
        chat = db_session.query(Chat).filter_by(tg_chat_id=str(chat_id)).first()
        if not chat:
            chat = Chat(tg_chat_id=str(chat_id))
            db_session.add(chat)
            db_session.commit()
        
        # Обновляем время обработки
        existing_message = db_session.query(Message).filter_by(
            chat_id=chat.id, 
            message_id=message_id
        ).first()
        
        if existing_message:
            existing_message.processed_at = datetime.utcnow()
            existing_message.ai_response = analysis["reasoning"]
        else:
            msg = Message(
                chat_id=chat.id,
                message_id=message_id,
                sender_username=username,
                sender_id=user_id,
                message_text=message,
                message_link=message_link,
                processed_at=datetime.utcnow(),
                ai_response=analysis["reasoning"]
            )
            db_session.add(msg)
        
        db_session.commit()
        
    except Exception as e:
        logger.error(f"Ошибка сохранения в БД: {e}")
    
    # Подготавливаем данные для следующих агентов
    agent_data = {
        "message": message,
        "normalized_message": normalized_message,
        "rules": rules,
        "user_id": user_id,
        "username": username,
        "chat_id": chat_id,
        "message_id": message_id,
        "message_link": message_link,
        "agent_1_analysis": analysis,
        "timestamp": datetime.now().isoformat()
    }
    
    output = {
        "agent_id": 1,
        "action": analysis["recommendation"].lower(),
        "priority": analysis["priority"],
        "reason": analysis["reasoning"],
        "message": message,
        "normalized_message": normalized_message,
        "user_id": user_id,
        "username": username,
        "chat_id": chat_id,
        "message_id": message_id,
        "message_link": message_link,
        "rules": rules,
        "agent_data": agent_data,
        "status": analysis["status"],
        "timestamp": datetime.now().isoformat()
    }
    
    if analysis["recommendation"] == "SKIP":
        logger.info(f"✅ Сообщение безопасно, пропускаем")
    else:
        logger.info(f"📋 Сообщение отправляется для анализа (приоритет: {analysis['priority']})")
    
    return output

# ============================================================================
# REDIS WORKER
# ============================================================================
class Agent1Worker:
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
            result = coordination_agent_1(input_data, db_session)
            return result
        except json.JSONDecodeError as e:
            logger.error(f"Невалидный JSON: {e}")
            return {
                "agent_id": 1,
                "action": "error",
                "reason": f"Ошибка парсинга данных: {e}",
                "message": "",
                "status": "json_error"
            }
        except Exception as e:
            logger.error(f"Ошибка обработки сообщения: {e}")
            return {
                "agent_id": 1,
                "action": "error",
                "reason": f"Внутренняя ошибка агента 1: {e}",
                "message": "",
                "status": "error"
            }
    
    def send_to_agent_2(self, result):
        """Отправляет сообщение агенту 2 для дальнейшего анализа"""
        if result.get("action") in ["analyze", "priority"]:
            try:
                agent_data = result.get("agent_data", {})
                result_json = json.dumps(agent_data, ensure_ascii=False)
                self.redis_client.rpush(QUEUE_AGENT_2_INPUT, result_json)
                logger.info(f"✅ Отправлено агенту 2")
                return True
            except Exception as e:
                logger.error(f"Не удалось отправить агенту 2: {e}")
                return False
        return False
    
    def run(self):
        """Главный цикл обработки сообщений"""
        logger.info(f"✅ Агент 1 запущен")
        logger.info(f"   Слушаю очередь: {QUEUE_AGENT_1_INPUT}")
        logger.info(f"   Отправляю в Агента 2: {QUEUE_AGENT_2_INPUT}")
        logger.info("   Нажмите Ctrl+C для остановки\n")
        
        db_session = None
        try:
            while True:
                try:
                    result = self.redis_client.blpop(QUEUE_AGENT_1_INPUT, timeout=1)
                    if result is None:
                        continue
                    
                    queue_name, message_data = result
                    logger.info(f"📨 Получено сообщение")
                    
                    # Создаем новую сессию БД для каждого сообщения
                    db_session = get_db_session()
                    output = self.process_message(message_data, db_session)
                    
                    # Отправляем агенту 2 если нужно
                    sent_to_agent2 = self.send_to_agent_2(output)
                    
                    db_session.close()
                    
                    logger.info(f"✅ Обработка завершена\n")
                    
                except Exception as e:
                    logger.error(f"Ошибка в цикле: {e}")
                    if db_session:
                        db_session.close()
                    time.sleep(1)
                    
        except KeyboardInterrupt:
            logger.info("\n❌ Агент 1 остановлен (Ctrl+C)")
        finally:
            if db_session:
                db_session.close()
            logger.info("Агент 1 завершил работу")

# ============================================================================
# FASTAPI ПРИЛОЖЕНИЕ
# ============================================================================
app = FastAPI(
    title="🤖 Агент №1 - Координатор",
    description="Координация и нормализация сообщений",
    version="1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "online",
        "agent_id": 1,
        "name": "Агент №1 (Координатор)",
        "version": "1.0",
        "timestamp": datetime.now().isoformat(),
        "redis_queue": QUEUE_AGENT_1_INPUT,
        "uptime_seconds": int(time.time())
    }

@app.post("/process_message")
async def process_message_endpoint(message_data: dict):
    """Обработка сообщения через API"""
    db_session = get_db_session()
    try:
        result = coordination_agent_1(message_data, db_session)
        return result
    finally:
        db_session.close()

@app.get("/stats")
async def get_stats():
    """Статистика работы агента"""
    db_session = get_db_session()
    try:
        total_messages = db_session.query(Message).count()
        processed_today = db_session.query(Message).filter(
            Message.processed_at >= datetime.now().date()
        ).count()
        
        return {
            "total_messages": total_messages,
            "processed_today": processed_today,
            "agent_id": 1,
            "timestamp": datetime.now().isoformat()
        }
    finally:
        db_session.close()

# ============================================================================
# ЗАПУСК FASTAPI В ОТДЕЛЬНОМ ПОТОКЕ
# ============================================================================
def run_fastapi():
    """Запуск FastAPI сервера"""
    uvicorn.run(app, host="localhost", port=8001, log_level="info")

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
                "message": "Привет всем! Как дела?",
                "user_id": 123,
                "username": "test_user",
                "chat_id": -100,
                "message_id": 1,
                "message_link": "https://t.me/test/1"
            }
            
            db_session = get_db_session()
            result = coordination_agent_1(test_input, db_session)
            db_session.close()
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif mode == "api":
            # Запуск только FastAPI
            run_fastapi()
    else:
        # Запуск FastAPI в отдельном потоке
        fastapi_thread = threading.Thread(target=run_fastapi, daemon=True)
        fastapi_thread.start()
        logger.info("✅ FastAPI сервер запущен на порту 8001")
        
        # Запуск основного Redis worker
        try:
            worker = Agent1Worker()
            worker.run()
        except KeyboardInterrupt:
            logger.info("Выход из программы")
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")