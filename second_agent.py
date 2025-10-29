#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
АГЕНТ №2 — Анализатор и распределитель (Обновленные токены)
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
    format='[%(asctime)s] [АГЕНТ 2] %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# КОНФИГУРАЦИЯ БД (ОДИНАКОВАЯ С АГЕНТОМ 3.2)
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
QUEUE_AGENT_2_INPUT = "queue:agent2:input"
QUEUE_AGENT_3_INPUT = "queue:agent3:input"
QUEUE_AGENT_4_INPUT = "queue:agent4:input"

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
# АНАЛИЗ СООБЩЕНИЙ ЧЕРЕЗ GIGACHAT
# ============================================================================
def analyze_message_with_gigachat(message: str, rules: list, token: str) -> dict:
    """Детальный анализ сообщения через GigaChat для определения следующего шага"""
    url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
    
    rules_text = "\n".join([f"{i+1}. {rule}" for i, rule in enumerate(rules)])
    system_msg = f"""Ты — анализатор сообщений для системы модерации.
    
ПРАВИЛА ЧАТА:
{rules_text}

ТВОЯ ЗАДАЧА:
Проанализируй сообщение и определи стратегию дальнейшей обработки:

1. ОЦЕНИ серьезность потенциальных нарушений (0-10)
2. ОПРЕДЕЛИ тип анализа:
   - SIMPLE: простые нарушения, достаточно эвристического анализа (агент 4)
   - COMPLEX: сложные случаи, нужен ИИ анализ (агент 3)  
   - BOTH: неоднозначные случаи, нужны оба агента (3 и 4)

3. УКАЖИ приоритет: LOW/MEDIUM/HIGH

Формат ответа:
СЕРЬЕЗНОСТЬ: [0-10]
СТРАТЕГИЯ: [SIMPLE/COMPLEX/BOTH]
ПРИОРИТЕТ: [LOW/MEDIUM/HIGH]
ОБЪЯСНЕНИЕ: [краткое обоснование решения]"""
    
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
        "temperature": 0.2,
        "max_tokens": 200
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=20, verify=False)
        response.raise_for_status()
        result = response.json()
        content = result["choices"][0]["message"]["content"]
        
        # Парсим ответ
        content_lower = content.lower()
        
        # Определяем серьезность
        if "серьезность:" in content_lower:
            try:
                severity_line = [line for line in content.split('\n') if 'серьезность:' in line.lower()][0]
                severity = int(''.join(filter(str.isdigit, severity_line)))
            except:
                severity = 5  # По умолчанию средняя серьезность
        else:
            severity = 5
        
        # Определяем стратегию
        if "simple" in content_lower:
            strategy = "SIMPLE"
        elif "complex" in content_lower:
            strategy = "COMPLEX"
        elif "both" in content_lower:
            strategy = "BOTH"
        else:
            strategy = "BOTH"  # По умолчанию используем оба агента
        
        # Определяем приоритет
        if "high" in content_lower:
            priority = "HIGH"
        elif "low" in content_lower:
            priority = "LOW"
        else:
            priority = "MEDIUM"
            
        return {
            "severity": severity,
            "strategy": strategy,
            "priority": priority,
            "reasoning": content,
            "status": "success"
        }
        
    except Exception as e:
        logger.error(f"Ошибка GigaChat анализа: {e}")
        # При ошибке используем консервативный подход
        return {
            "severity": 7,
            "strategy": "BOTH",
            "priority": "MEDIUM",
            "reasoning": f"Ошибка анализа: {e}. Используем полный анализ.",
            "status": "error"
        }

# ============================================================================
# ОСНОВНАЯ ЛОГИКА АГЕНТА 2
# ============================================================================
def analysis_agent_2(input_data, db_session):
    """
    АГЕНТ 2 — Анализатор и распределитель.
    Получает данные от Агента 1 и решает, какие агенты использовать для модерации.
    """
    message = input_data.get("message", "")
    rules = input_data.get("rules", [])
    user_id = input_data.get("user_id")
    username = input_data.get("username", "")
    chat_id = input_data.get("chat_id")
    message_id = input_data.get("message_id")
    message_link = input_data.get("message_link", "")
    agent_1_analysis = input_data.get("agent_1_analysis", {})
    
    logger.info(f"Анализирую и распределяю сообщение от @{username} в чате {chat_id}")
    
    if not message:
        return {
            "agent_id": 2,
            "action": "skip",
            "reason": "Пустое сообщение",
            "message": "",
            "user_id": user_id,
            "username": username,
            "chat_id": chat_id,
            "message_id": message_id,
            "status": "skipped"
        }
    
    if not rules:
        rules = [
            "Запрещена реклама сторонних сообществ",
            "Запрещены нецензурные выражения и оскорбления",
            "Запрещена дискриминация по любым признакам",
            "Запрещен спам и флуд"
        ]
    
    # Детальный анализ через GigaChat
    analysis = analyze_message_with_gigachat(message, rules, ACCESS_TOKEN)
    
    # Подготавливаем данные для агентов 3 и 4
    moderation_data = {
        "message": message,
        "rules": rules,
        "user_id": user_id,
        "username": username,
        "chat_id": chat_id,
        "message_id": message_id,
        "message_link": message_link,
        "agent_1_analysis": agent_1_analysis,
        "agent_2_analysis": analysis,
        "timestamp": datetime.now().isoformat()
    }
    
    # Сохраняем анализ в БД
    try:
        chat = db_session.query(Chat).filter_by(tg_chat_id=str(chat_id)).first()
        if chat:
            # Обновляем AI response
            message_obj = db_session.query(Message).filter_by(
                chat_id=chat.id, 
                message_id=message_id
            ).first()
            
            if message_obj:
                existing_response = message_obj.ai_response or ""
                message_obj.ai_response = f"{existing_response}\n[АГЕНТ 2] {analysis['reasoning']}"
                db_session.commit()
                
    except Exception as e:
        logger.error(f"Ошибка обновления БД: {e}")
    
    output = {
        "agent_id": 2,
        "action": "distribute",
        "strategy": analysis["strategy"],
        "severity": analysis["severity"],
        "priority": analysis["priority"],
        "reason": analysis["reasoning"],
        "message": message,
        "user_id": user_id,
        "username": username,
        "chat_id": chat_id,
        "message_id": message_id,
        "message_link": message_link,
        "rules": rules,
        "moderation_data": moderation_data,
        "send_to_agent_3": analysis["strategy"] in ["COMPLEX", "BOTH"],
        "send_to_agent_4": analysis["strategy"] in ["SIMPLE", "BOTH"],
        "status": analysis["status"],
        "timestamp": datetime.now().isoformat()
    }
    
    logger.info(f"📊 Стратегия: {analysis['strategy']}, Серьезность: {analysis['severity']}/10, Приоритет: {analysis['priority']}")
    
    return output

# ============================================================================
# REDIS WORKER
# ============================================================================
class Agent2Worker:
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
            result = analysis_agent_2(input_data, db_session)
            return result
        except json.JSONDecodeError as e:
            logger.error(f"Невалидный JSON: {e}")
            return {
                "agent_id": 2,
                "action": "error",
                "reason": f"Ошибка парсинга данных: {e}",
                "message": "",
                "status": "json_error"
            }
        except Exception as e:
            logger.error(f"Ошибка обработки сообщения: {e}")
            return {
                "agent_id": 2,
                "action": "error",
                "reason": f"Внутренняя ошибка агента 2: {e}",
                "message": "",
                "status": "error"
            }
    
    def distribute_to_agents(self, result):
        """Распределяет сообщение агентам 3 и/или 4"""
        sent_count = 0
        
        if result.get("send_to_agent_3", False):
            try:
                moderation_data = result.get("moderation_data", {})
                result_json = json.dumps(moderation_data, ensure_ascii=False)
                self.redis_client.rpush(QUEUE_AGENT_3_INPUT, result_json)
                logger.info(f"✅ Отправлено агенту 3")
                sent_count += 1
            except Exception as e:
                logger.error(f"Не удалось отправить агенту 3: {e}")
        
        if result.get("send_to_agent_4", False):
            try:
                moderation_data = result.get("moderation_data", {})
                result_json = json.dumps(moderation_data, ensure_ascii=False)
                self.redis_client.rpush(QUEUE_AGENT_4_INPUT, result_json)
                logger.info(f"✅ Отправлено агенту 4")
                sent_count += 1
            except Exception as e:
                logger.error(f"Не удалось отправить агенту 4: {e}")
        
        return sent_count
    
    def run(self):
        """Главный цикл обработки сообщений"""
        logger.info(f"✅ Агент 2 запущен")
        logger.info(f"   Слушаю очередь: {QUEUE_AGENT_2_INPUT}")
        logger.info(f"   Отправляю в Агента 3: {QUEUE_AGENT_3_INPUT}")
        logger.info(f"   Отправляю в Агента 4: {QUEUE_AGENT_4_INPUT}")
        logger.info("   Нажмите Ctrl+C для остановки\n")
        
        db_session = None
        try:
            while True:
                try:
                    result = self.redis_client.blpop(QUEUE_AGENT_2_INPUT, timeout=1)
                    if result is None:
                        continue
                    
                    queue_name, message_data = result
                    logger.info(f"📨 Получено сообщение")
                    
                    # Создаем новую сессию БД для каждого сообщения
                    db_session = get_db_session()
                    output = self.process_message(message_data, db_session)
                    
                    # Распределяем сообщение агентам
                    sent_count = self.distribute_to_agents(output)
                    
                    db_session.close()
                    
                    logger.info(f"✅ Обработка завершена, отправлено {sent_count} агентам\n")
                    
                except Exception as e:
                    logger.error(f"Ошибка в цикле: {e}")
                    if db_session:
                        db_session.close()
                    time.sleep(1)
                    
        except KeyboardInterrupt:
            logger.info("\n❌ Агент 2 остановлен (Ctrl+C)")
        finally:
            if db_session:
                db_session.close()
            logger.info("Агент 2 завершил работу")

# ============================================================================
# FASTAPI ПРИЛОЖЕНИЕ
# ============================================================================
app = FastAPI(
    title="🤖 Агент №2 - Анализатор",
    description="Анализ и распределение сообщений между модераторами",
    version="2.0"
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
        "agent_id": 2,
        "name": "Агент №2 (Анализатор)",
        "version": "2.0",
        "timestamp": datetime.now().isoformat(),
        "redis_queue": QUEUE_AGENT_2_INPUT,
        "uptime_seconds": int(time.time())
    }

@app.post("/process_message")
async def process_message_endpoint(message_data: dict):
    """Обработка сообщения через API"""
    db_session = get_db_session()
    try:
        result = analysis_agent_2(message_data, db_session)
        return result
    finally:
        db_session.close()

@app.get("/stats")
async def get_stats():
    """Статистика работы агента"""
    db_session = get_db_session()
    try:
        total_messages = db_session.query(Message).count()
        negative_messages = db_session.query(NegativeMessage).count()
        
        return {
            "total_messages": total_messages,
            "negative_messages": negative_messages,
            "agent_id": 2,
            "timestamp": datetime.now().isoformat()
        }
    finally:
        db_session.close()

# ============================================================================
# ЗАПУСК FASTAPI В ОТДЕЛЬНОМ ПОТОКЕ
# ============================================================================
def run_fastapi():
    """Запуск FastAPI сервера"""
    uvicorn.run(app, host="localhost", port=8002, log_level="info")

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
                "message": "Идиот, сука, вступайте в наш канал @spam!",
                "rules": [
                    "Запрещена реклама",
                    "Запрещены нецензурные выражения",
                    "Запрещены оскорбления"
                ],
                "user_id": 456,
                "username": "test_user",
                "chat_id": -200,
                "message_id": 2,
                "message_link": "https://t.me/test/2"
            }
            
            db_session = get_db_session()
            result = analysis_agent_2(test_input, db_session)
            db_session.close()
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif mode == "api":
            # Запуск только FastAPI
            run_fastapi()
    else:
        # Запуск FastAPI в отдельном потоке
        fastapi_thread = threading.Thread(target=run_fastapi, daemon=True)
        fastapi_thread.start()
        logger.info("✅ FastAPI сервер запущен на порту 8002")
        
        # Запуск основного Redis worker
        try:
            worker = Agent2Worker()
            worker.run()
        except KeyboardInterrupt:
            logger.info("Выход из программы")
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")