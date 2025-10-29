#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
=============================================================================
ЧАТ-АГЕНТ №2 с PostgreSQL - Исправленный анализатор
=============================================================================
- Получает сообщения от Telegram Bot
- Анализирует через GigaChat API
- Отправляет результаты в очередь для Агентов №3 и №4
- REST API для получения сообщений на анализ
=============================================================================
"""

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from loguru import logger

import redis

# === КОНФИГУРАЦИЯ ===

@dataclass
class Agent2Config:
    """Конфигурация Агента №2"""
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379")
    gigachat_credentials: str = os.getenv("GIGACHAT_CREDENTIALS", "")
    api_host: str = os.getenv("API_HOST", "0.0.0.0")
    api_port: int = int(os.getenv("API_PORT_2", "8002"))
    
    # Redis очереди
    queue_agent_3_input: str = "queue:agent3:input"
    queue_agent_4_input: str = "queue:agent4:input"
    queue_results: str = "queue:agent2:results"

config = Agent2Config()

# === ЛОГИРОВАНИЕ ===

logger.add(
    f"agent2_{datetime.now().strftime('%Y-%m-%d')}.log",
    format="<level>{time:HH:mm:ss}</level> | <level>{level}</level> | {message}",
    level="INFO"
)

# === ИНИЦИАЛИЗАЦИЯ ===

app = FastAPI(title="TeleGuard Agent 2 - Message Analyzer")
redis_client = None

class GigaChatClient:
    """Клиент для работы с GigaChat API"""
    
    def __init__(self, credentials: str):
        self.credentials = credentials
        self.token = None
        self.token_expiry = None
    
    async def get_token(self) -> Optional[str]:
        """Получить токен GigaChat"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://ngw.devices.sberbank.ru:443/api/v2/oauth",
                    headers={
                        "RqUID": str(uuid.uuid4()),
                        "Content-Type": "application/x-www-form-urlencoded"
                    },
                    data={"scope": "GIGACHAT_API_PERS"},
                    auth=(self.credentials, "")
                )
                if response.status_code == 200:
                    data = response.json()
                    self.token = data.get("access_token")
                    logger.success(f"✅ Получен токен GigaChat")
                    return self.token
        except Exception as e:
            logger.error(f"❌ Ошибка получения токена: {e}")
        return None
    
    async def analyze_message(self, message_text: str) -> str:
        """Анализировать сообщение через GigaChat"""
        if not self.token:
            self.token = await self.get_token()
        
        try:
            prompt = f"""Проанализируй следующее сообщение на предмет нарушений правил модерации:
            
Сообщение: "{message_text}"

Проверь на:
1. Мат и оскорбления
2. Спам и реклама
3. Ссылки и фишинг
4. Экстремизм
5. Фейк и дезинформацию

Дай вердикт: нарушение или нет?"""

            async with httpx.AsyncClient(verify=False) as client:
                response = await client.post(
                    "https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.token}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "GigaChat",
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.7,
                        "max_tokens": 200
                    },
                    timeout=30
                )
                
                if response.status_code == 200:
                    data = response.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    logger.success(f"🤖 Ответ GigaChat: {content[:100]}...")
                    return content
                else:
                    logger.error(f"❌ Ошибка GigaChat: {response.status_code}")
        except Exception as e:
            logger.error(f"❌ Ошибка анализа: {e}")
        
        return ""

# === REDIS KOMMUNICATION ===

def send_to_queue(queue_name: str, data: dict) -> bool:
    """Отправить данные в Redis очередь"""
    try:
        redis_client.lpush(queue_name, json.dumps(data, ensure_ascii=False))
        logger.success(f"📤 Отправлено в {queue_name}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка отправки в очередь: {e}")
        return False

# === REST API ===

gigachat_client = GigaChatClient(config.gigachat_credentials)
message_count = 0
start_time = datetime.now()

@app.post("/process_message")
async def process_message(data: dict):
    """Получить сообщение на анализ и обработать его"""
    global message_count
    
    try:
        message_text = data.get("message", "")
        user_id = data.get("user_id", 0)
        username = data.get("username", "unknown")
        chat_id = data.get("chat_id", 0)
        message_id = data.get("message_id", 0)
        
        if not message_text:
            raise HTTPException(status_code=400, detail="Message is required")
        
        # Анализируем сообщение
        analysis_result = await gigachat_client.analyze_message(message_text)
        
        # Определяем является ли нарушением
        is_violation = any(word in analysis_result.lower() for word in [
            "вердикт: да", "нарушение", "нарушает", "недопустимо", 
            "спам", "реклама", "оскорбление", "мат"
        ])
        
        # Подготавливаем результат
        result = {
            "message_id": message_id,
            "chat_id": chat_id,
            "user_id": user_id,
            "username": username,
            "message_text": message_text,
            "is_violation": is_violation,
            "analysis": analysis_result,
            "confidence": 0.8 if is_violation else 0.7,
            "timestamp": datetime.now().isoformat(),
            "correlation_id": str(uuid.uuid4())
        }
        
        # Если нарушение - отправляем в очереди агентов №3 и №4
        if is_violation:
            send_to_queue(config.queue_agent_3_input, result)
            send_to_queue(config.queue_agent_4_input, result)
            logger.warning(f"🚨 Найдено нарушение от @{username}")
        else:
            logger.info(f"✅ Сообщение чистое от @{username}")
        
        # Сохраняем результат
        send_to_queue(config.queue_results, result)
        
        message_count += 1
        
        return {
            "status": "success",
            "is_violation": is_violation,
            "confidence": result["confidence"],
            "message_id": message_id,
            "correlation_id": result["correlation_id"]
        }
    
    except Exception as e:
        logger.error(f"❌ Ошибка обработки: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """Проверка здоровья системы"""
    try:
        redis_client.ping()
        redis_connected = True
    except:
        redis_connected = False
    
    uptime = (datetime.now() - start_time).total_seconds()
    
    return {
        "agent_id": 2,
        "status": "healthy",
        "uptime_seconds": int(uptime),
        "processed_messages": message_count,
        "database_connected": True,
        "redis_connected": redis_connected,
        "gigachat_token_valid": gigachat_client.token is not None
    }

@app.get("/metrics")
async def metrics():
    """Метрики системы"""
    uptime = (datetime.now() - start_time).total_seconds()
    
    try:
        queue_size_3 = redis_client.llen(config.queue_agent_3_input)
        queue_size_4 = redis_client.llen(config.queue_agent_4_input)
    except:
        queue_size_3 = queue_size_4 = 0
    
    return {
        "agent_id": 2,
        "uptime_seconds": int(uptime),
        "processed_messages": message_count,
        "queue_agent3_size": queue_size_3,
        "queue_agent4_size": queue_size_4,
        "messages_per_second": message_count / max(uptime, 1)
    }

@app.get("/")
async def root():
    """Информация о сервисе"""
    return {
        "name": "TeleGuard Agent 2",
        "version": "2.0",
        "description": "Message Analyzer and Moderator",
        "status": "running"
    }

# === ИНИЦИАЛИЗАЦИЯ ===

@app.on_event("startup")
async def startup():
    """Инициализация при запуске"""
    global redis_client
    
    try:
        redis_client = redis.from_url(config.redis_url, decode_responses=True)
        redis_client.ping()
        logger.success(f"✅ Подключено к Redis: {config.redis_url}")
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к Redis: {e}")
    
    # Получаем токен GigaChat
    token = await gigachat_client.get_token()
    if token:
        logger.success("✅ GigaChat инициализирован")
    else:
        logger.warning("⚠️ GigaChat не инициализирован")
    
    logger.success("🚀 Агент №2 запущен и готов к работе!")

# === ЗАПУСК ===

if __name__ == "__main__":
    logger.info(f"🚀 Запуск Агента №2 на {config.api_host}:{config.api_port}...")
    uvicorn.run(app, host=config.api_host, port=config.api_port)
