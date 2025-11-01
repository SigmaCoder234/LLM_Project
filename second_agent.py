#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
АГЕНТ №2 — Анализатор с НОВЫМ Mistral AI API (SDK v1.0+)
"""

import json
import redis
import time
from typing import Dict, Any
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey, BigInteger, Text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import threading

# Новый Mistral AI импорт
try:
    from mistralai import Mistral
    from mistralai import UserMessage, SystemMessage, AssistantMessage
    MISTRAL_IMPORT_SUCCESS = True
    MISTRAL_IMPORT_VERSION = "v1.0+ (новый SDK)"
except ImportError:
    try:
        # Fallback для старой версии
        from mistralai.client import MistralClient as Mistral
        from mistralai.models.chat_completion import ChatMessage
        def UserMessage(content): return {"role": "user", "content": content}
        def SystemMessage(content): return {"role": "system", "content": content}
        def AssistantMessage(content): return {"role": "assistant", "content": content}
        MISTRAL_IMPORT_SUCCESS = True
        MISTRAL_IMPORT_VERSION = "v0.4.2 (legacy)"
    except ImportError:
        print("❌ Не удалось импортировать Mistral AI")
        MISTRAL_IMPORT_SUCCESS = False
        MISTRAL_IMPORT_VERSION = "none"
        # Заглушки
        class Mistral:
            def __init__(self, api_key): pass
            def chat(self, **kwargs): 
                raise ImportError("Mistral AI не установлен")
        def UserMessage(content): return {"role": "user", "content": content}
        def SystemMessage(content): return {"role": "system", "content": content}
        def AssistantMessage(content): return {"role": "assistant", "content": content}

# Импортируем централизованную конфигурацию
from config import (
    MISTRAL_API_KEY,
    MISTRAL_MODEL,
    MISTRAL_GENERATION_PARAMS,
    POSTGRES_URL,
    get_redis_config,
    QUEUE_AGENT_2_INPUT,
    QUEUE_AGENT_3_INPUT,
    QUEUE_AGENT_4_INPUT,
    AGENT_PORTS,
    DEFAULT_RULES,
    setup_logging
)

# ============================================================================
# ЛОГИРОВАНИЕ И ИНИЦИАЛИЗАЦИЯ
# ============================================================================
logger = setup_logging("АГЕНТ 2")

if MISTRAL_IMPORT_SUCCESS:
    logger.info(f"✅ Mistral AI импортирован успешно ({MISTRAL_IMPORT_VERSION})")
else:
    logger.error("❌ Mistral AI не импортирован, работа в режиме заглушки")

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ НОВОГО MISTRAL AI КЛИЕНТА
# ============================================================================
if MISTRAL_IMPORT_SUCCESS and MISTRAL_API_KEY:
    try:
        if MISTRAL_IMPORT_VERSION.startswith("v1.0"):
            # Новый API
            mistral_client = Mistral(api_key=MISTRAL_API_KEY)
        else:
            # Старый API  
            mistral_client = Mistral(api_key=MISTRAL_API_KEY)
        logger.info("✅ Mistral AI клиент создан")
    except Exception as e:
        logger.error(f"❌ Ошибка создания Mistral AI клиента: {e}")
        mistral_client = None
else:
    mistral_client = None
    logger.warning("⚠️ Mistral AI клиент не создан")

# ============================================================================
# МОДЕЛИ БД (СОКРАЩЕННАЯ ВЕРСИЯ)
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

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ БД И REDIS
# ============================================================================
engine = create_engine(POSTGRES_URL)
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)

def get_db_session():
    return SessionLocal()

# ============================================================================
# ФУНКЦИИ ДЛЯ РАБОТЫ С ПРАВИЛАМИ ЧАТА
# ============================================================================
def get_chat_rules(chat_id: int, db_session) -> list:
    """Получает правила для конкретного чата"""
    try:
        chat = db_session.query(Chat).filter_by(tg_chat_id=str(chat_id)).first()
        if chat and chat.custom_rules:
            rules_list = [rule.strip() for rule in chat.custom_rules.split('\n') if rule.strip()]
            return rules_list
        else:
            return DEFAULT_RULES
    except Exception as e:
        logger.error(f"Ошибка получения правил для чата {chat_id}: {e}")
        return DEFAULT_RULES

# ============================================================================
# АНАЛИЗ С НОВЫМ MISTRAL AI API
# ============================================================================
def analyze_message_with_mistral_new(message: str, rules: list) -> dict:
    """Анализ сообщения через новый Mistral AI API"""
    
    if not MISTRAL_IMPORT_SUCCESS or not mistral_client:
        logger.warning("⚠️ Mistral AI недоступен, используем заглушку")
        return {
            "severity": 5,
            "strategy": "BOTH",
            "priority": "MEDIUM", 
            "reasoning": "Mistral AI недоступен, используем консервативную стратегию",
            "rules_used": rules if rules else DEFAULT_RULES,
            "ai_model": "fallback",
            "status": "fallback"
        }
    
    try:
        if not rules:
            rules = DEFAULT_RULES
        
        rules_text = "\n".join([f"{i+1}. {rule}" for i, rule in enumerate(rules)]) 
        
        system_message = f"""Ты — анализатор сообщений для системы модерации Telegram чата.
        
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
        
        user_message_text = f"Сообщение: \"{message}\""
        
        # Создаем сообщения в новом формате
        if MISTRAL_IMPORT_VERSION.startswith("v1.0"):
            # Новый API - используем объекты сообщений
            messages = [
                SystemMessage(content=system_message),
                UserMessage(content=user_message_text)
            ]
        else:
            # Старый API - используем словари
            messages = [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message_text}
            ]
        
        # Вызываем API
        if MISTRAL_IMPORT_VERSION.startswith("v1.0"):
            # Новый API
            response = mistral_client.chat.complete(
                model=MISTRAL_MODEL,
                messages=messages,
                temperature=MISTRAL_GENERATION_PARAMS.get("temperature", 0.1),
                max_tokens=MISTRAL_GENERATION_PARAMS.get("max_tokens", 300)
            )
            content = response.choices[0].message.content
        else:
            # Старый API
            response = mistral_client.chat(
                model=MISTRAL_MODEL,  
                messages=messages,
                temperature=MISTRAL_GENERATION_PARAMS.get("temperature", 0.1),
                max_tokens=MISTRAL_GENERATION_PARAMS.get("max_tokens", 300)
            )
            content = response.choices[0].message.content
        
        # Парсим ответ
        content_lower = content.lower()
        
        # Определяем серьезность
        if "серьезность:" in content_lower:
            try:
                severity_line = [line for line in content.split('\n') if 'серьезность:' in line.lower()][0]
                severity = int(''.join(filter(str.isdigit, severity_line)))
            except:
                severity = 5
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
            strategy = "BOTH"
        
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
            "rules_used": rules,
            "ai_model": MISTRAL_MODEL,
            "import_version": MISTRAL_IMPORT_VERSION,
            "status": "success"
        }
        
    except Exception as e:
        logger.error(f"Ошибка Mistral AI анализа: {e}")
        return {
            "severity": 7,
            "strategy": "BOTH",
            "priority": "MEDIUM",
            "reasoning": f"Ошибка анализа Mistral AI: {e}. Используем полный анализ.",
            "rules_used": rules if rules else DEFAULT_RULES,
            "ai_model": "error",
            "import_version": MISTRAL_IMPORT_VERSION,
            "status": "error"
        }

# ============================================================================
# ОСНОВНАЯ ЛОГИКА АГЕНТА 2
# ============================================================================
def analysis_agent_2(input_data, db_session):
    """
    АГЕНТ 2 — Анализатор и распределитель (Новый Mistral AI API)
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
    
    # Получаем правила для конкретного чата
    if not rules:
        rules = get_chat_rules(chat_id, db_session)
    
    # Анализ через новый Mistral AI API
    analysis = analyze_message_with_mistral_new(message, rules)
    
    # Подготавливаем данные для агентов 3 и 4
    moderation_data = {
        "message": message,
        "rules": analysis["rules_used"],
        "user_id": user_id,
        "username": username,
        "chat_id": chat_id,
        "message_id": message_id,
        "message_link": message_link,
        "agent_1_analysis": agent_1_analysis,
        "agent_2_analysis": analysis,
        "timestamp": datetime.now().isoformat()
    }
    
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
        "rules": analysis["rules_used"],
        "moderation_data": moderation_data,
        "send_to_agent_3": analysis["strategy"] in ["COMPLEX", "BOTH"],
        "send_to_agent_4": analysis["strategy"] in ["SIMPLE", "BOTH"],
        "ai_model": analysis["ai_model"],
        "import_version": analysis.get("import_version", MISTRAL_IMPORT_VERSION),
        "status": analysis["status"],
        "timestamp": datetime.now().isoformat()
    }
    
    logger.info(f"📊 Стратегия: {analysis['strategy']}, Серьезность: {analysis['severity']}/10, Приоритет: {analysis['priority']}")
    logger.info(f"🔧 Импорт версия: {analysis.get('import_version', MISTRAL_IMPORT_VERSION)}")
    
    return output

# ============================================================================
# REDIS WORKER
# ============================================================================
class Agent2Worker:
    def __init__(self):
        try:
            redis_config = get_redis_config()
            self.redis_client = redis.Redis(**redis_config)
            self.redis_client.ping()
            logger.info(f"✅ Подключение к Redis успешно")
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
                logger.info(f"✅ Отправлено агенту 3 (Mistral)")
                sent_count += 1
            except Exception as e:
                logger.error(f"Не удалось отправить агенту 3: {e}")
        
        if result.get("send_to_agent_4", False):
            try:
                moderation_data = result.get("moderation_data", {})
                result_json = json.dumps(moderation_data, ensure_ascii=False)
                self.redis_client.rpush(QUEUE_AGENT_4_INPUT, result_json)
                logger.info(f"✅ Отправлено агенту 4 (Эвристика + Mistral)")
                sent_count += 1
            except Exception as e:
                logger.error(f"Не удалось отправить агенту 4: {e}")
        
        return sent_count
    
    def run(self):
        """Главный цикл обработки сообщений"""
        logger.info(f"✅ Агент 2 запущен (Новый Mistral AI API v2.6)")
        logger.info(f"   Модель: {MISTRAL_MODEL}")
        logger.info(f"   Импорт: {MISTRAL_IMPORT_VERSION}")
        logger.info(f"   Статус Mistral AI: {'✅ Доступен' if mistral_client else '❌ Недоступен'}")
        logger.info(f"   Слушаю очередь: {QUEUE_AGENT_2_INPUT}")
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
                    
                    db_session = get_db_session()
                    output = self.process_message(message_data, db_session)
                    
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
    title="🤖 Агент №2 - Анализатор (Новый Mistral AI)",
    description="Анализ и распределение с новым Mistral AI API",
    version="2.6"
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
        "version": "2.6 (Новый Mistral AI API)",
        "ai_provider": f"Mistral AI ({MISTRAL_MODEL})" if mistral_client else "Mistral AI (недоступен)",
        "import_version": MISTRAL_IMPORT_VERSION,
        "import_success": MISTRAL_IMPORT_SUCCESS,
        "client_status": "✅ Создан" if mistral_client else "❌ Не создан",
        "api_type": "Новый SDK v1.0+" if MISTRAL_IMPORT_VERSION.startswith("v1.0") else "Legacy v0.4.2",
        "configuration": "Environment variables (.env)",
        "default_rules": DEFAULT_RULES,
        "timestamp": datetime.now().isoformat(),
        "redis_queue": QUEUE_AGENT_2_INPUT,
        "uptime_seconds": int(time.time())
    }

# ============================================================================
# ЗАПУСК FASTAPI В ОТДЕЛЬНОМ ПОТОКЕ
# ============================================================================
def run_fastapi():
    """Запуск FastAPI сервера"""
    uvicorn.run(app, host="localhost", port=AGENT_PORTS[2], log_level="info")

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
                "message": "Все эти черные должны убираться отсюда!",
                "rules": [],
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
            run_fastapi()
    else:
        # Запуск FastAPI в отдельном потоке
        fastapi_thread = threading.Thread(target=run_fastapi, daemon=True)
        fastapi_thread.start()
        logger.info(f"✅ FastAPI сервер запущен на порту {AGENT_PORTS[2]}")
        
        # Запуск основного Redis worker
        try:
            worker = Agent2Worker()
            worker.run()
        except KeyboardInterrupt:
            logger.info("Выход из программы")
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")
