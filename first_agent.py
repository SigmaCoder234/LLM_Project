#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🤖 АГЕНТ №1 — КООРДИНАТОР
✅ ВСЕ сообщения → ТОЛЬКО В АГЕНТА 2
✅ Минимальное изменение (одна строка!)
"""

import json
import redis
import time
import threading
from datetime import datetime
from typing import Dict, Any, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

try:
    from mistralai.client import MistralClient
    from mistralai.models.chat_completion import ChatMessage
    MISTRAL_IMPORT_SUCCESS = True
    MISTRAL_IMPORT_VERSION = "v0.4.2 (legacy)"
except ImportError:
    try:
        from mistralai import Mistral as MistralClient
        from mistralai import UserMessage, SystemMessage
        def ChatMessage(role, content):
            return role, content, role == "user"
        MISTRAL_IMPORT_SUCCESS = True
        MISTRAL_IMPORT_VERSION = "v1.0+ (новый SDK)"
    except Exception as e:
        MISTRAL_IMPORT_SUCCESS = False
        MISTRAL_IMPORT_VERSION = "none"
        class MistralClient:
            def __init__(self, api_key=None): 
                pass
            def chat(self, **kwargs):
                raise ImportError("Mistral AI не установлен")

from config import (
    MISTRAL_API_KEY, MISTRAL_MODEL, MISTRAL_GENERATION_PARAMS,
    get_redis_config, QUEUE_AGENT_1_OUTPUT, QUEUE_AGENT_2_INPUT,
    AGENT_PORTS, DEFAULT_RULES, setup_logging
)

logger = setup_logging("АГЕНТ 1")

if MISTRAL_IMPORT_SUCCESS:
    logger.info(f"✅ Mistral AI импортирован ({MISTRAL_IMPORT_VERSION})")
else:
    logger.error("❌ Mistral AI не импортирован")

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ MISTRAL
# ============================================================================

if MISTRAL_IMPORT_SUCCESS and MISTRAL_API_KEY:
    try:
        mistral_client = MistralClient(api_key=MISTRAL_API_KEY)
        logger.info("✅ Mistral AI клиент создан")
    except Exception as e:
        logger.error(f"❌ Ошибка создания Mistral AI клиента: {e}")
        mistral_client = None
else:
    mistral_client = None
    logger.warning("⚠️ Mistral AI клиент не создан")

# ============================================================================
# ФУНКЦИЯ КООРДИНАЦИИ
# ============================================================================

def coordinate_with_mistral(message: str, rules: List[str]) -> Dict[str, Any]:
    """Координирует сообщение через Mistral"""
    
    if not MISTRAL_IMPORT_SUCCESS or not mistral_client:
        logger.warning("⚠️ Mistral недоступен, используется fallback")
        return {
            "route": "BOTH",
            "priority": "MEDIUM",
            "strategy": "BOTH",
            "confidence": 0.5,
            "reasoning": "Mistral недоступен"
        }
    
    try:
        if not rules:
            rules = DEFAULT_RULES
        
        rules_text = "\n".join([f"- {rule}" for rule in rules])
        
        system_message = f"""Telegram чат модератор. Правила:
{rules_text}

Определи:
1. SIMPLE - 4 короткие проверки (эвристика)
2. COMPLEX - 3 сложные проверки (AI анализ)
3. BOTH - обе проверки

Приоритет: HIGH/MEDIUM/LOW
Уверенность: 0-100"""

        user_message = f"Сообщение: '{message}'"
        
        messages = [
            ChatMessage(role="system", content=system_message),
            ChatMessage(role="user", content=user_message)
        ]
        
        response = mistral_client.chat(
            model=MISTRAL_MODEL,
            messages=messages,
            **MISTRAL_GENERATION_PARAMS
        )
        
        content = response.choices[0].message.content.lower()
        
        # Определяем маршрут
        route = "BOTH"
        if "simple" in content and "complex" not in content:
            route = "SIMPLE"
        elif "complex" in content and "simple" not in content:
            route = "COMPLEX"
        
        # Приоритет
        priority = "MEDIUM"
        if "high" in content:
            priority = "HIGH"
        elif "low" in content:
            priority = "LOW"
        
        # Уверенность
        confidence = 0.7
        for i in range(100, 0, -10):
            if str(i) in content:
                confidence = i / 100.0
                break
        
        return {
            "route": route,
            "priority": priority,
            "strategy": route,
            "confidence": confidence,
            "reasoning": content[:200]
        }
    
    except Exception as e:
        logger.error(f"❌ Ошибка Mistral: {e}")
        return {
            "route": "BOTH",
            "priority": "MEDIUM",
            "strategy": "BOTH",
            "confidence": 0.5,
            "reasoning": f"Ошибка: {str(e)[:50]}"
        }

# ============================================================================
# ОСНОВНОЙ WORKER
# ============================================================================

class Agent1Worker:
    def __init__(self):
        try:
            redis_config = get_redis_config()
            self.redis_client = redis.Redis(**redis_config)
            self.redis_client.ping()
            logger.info("✅ Подключение к Redis успешно")
        except Exception as e:
            logger.error(f"❌ Не удалось подключиться к Redis: {e}")
            raise

    def send_to_agents(self, original_data):
        """✅ ИСПРАВКА: ВСЕ сообщения → ТОЛЬКО в Агента 2"""
        
        agent_input = {
            "message": original_data.get("message"),
            "rules": original_data.get("rules", DEFAULT_RULES),
            "user_id": original_data.get("user_id"),
            "username": original_data.get("username"),
            "chat_id": original_data.get("chat_id"),
            "message_id": original_data.get("message_id"),
            "message_link": original_data.get("message_link", ""),
            "media_type": original_data.get("media_type", "")
        }
        
        agent_input_json = json.dumps(agent_input, ensure_ascii=False)
        
        # ✅ ИСПРАВКА: ТОЛЬКО в Агента 2 (вместо 3 и 4)
        self.redis_client.rpush(QUEUE_AGENT_2_INPUT, agent_input_json)
        logger.info(f"📤 Сообщение отправлено В АГЕНТА 2")

    def run(self):
        """Главный цикл"""
        logger.info("="*80)
        logger.info("✅ АГЕНТ 1 ЗАПУЩЕН (Координатор v1.8)")
        logger.info(f"📊 Модель: {MISTRAL_MODEL}")
        logger.info(f"📥 Импорт: {MISTRAL_IMPORT_VERSION}")
        logger.info(f"🔔 Очередь входа: {QUEUE_AGENT_1_OUTPUT}")
        logger.info(f"📤 Отправляю ТОЛЬКО в: {QUEUE_AGENT_2_INPUT}")
        logger.info("⏱️  Нажмите Ctrl+C для остановки")
        logger.info("="*80 + "\n")
        
        try:
            while True:
                try:
                    result = self.redis_client.blpop(QUEUE_AGENT_1_OUTPUT, timeout=1)
                    
                    if result is None:
                        continue
                    
                    queue_name, message_data = result
                    
                    try:
                        input_data = json.loads(message_data)
                    except json.JSONDecodeError as e:
                        logger.error(f"❌ Невалидный JSON: {e}")
                        continue
                    
                    logger.info(f"📨 Получено сообщение")
                    
                    # Координируем через Mistral
                    message = input_data.get("message", "")
                    rules = input_data.get("rules", DEFAULT_RULES)
                    coord_result = coordinate_with_mistral(message, rules)
                    
                    # Отправляем в Агента 2
                    self.send_to_agents(input_data)
                    logger.info(f"✅ Маршрутизация завершена\n")
                    
                except Exception as e:
                    logger.error(f"❌ Ошибка в цикле: {e}")
                    time.sleep(1)
        
        except KeyboardInterrupt:
            logger.info("\n🛑 Агент 1 остановлен (Ctrl+C)")
        finally:
            logger.info("Агент 1 завершил работу")

# ============================================================================
# FASTAPI
# ============================================================================

app = FastAPI(
    title="🤖 Агент №1 - Координатор",
    description="Координирует многоагентную систему модерации",
    version="1.8"
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
        "name": "Агент 1 (Координатор)",
        "version": "1.8",
        "ai_provider": f"Mistral AI ({MISTRAL_MODEL})" if mistral_client else "Mistral AI (недоступен)",
        "import_version": MISTRAL_IMPORT_VERSION,
        "timestamp": datetime.now().isoformat()
    }

# ============================================================================
# ТОЧКА ВХОДА
# ============================================================================

if __name__ == "__main__":
    # FastAPI в отдельном потоке
    fastapi_thread = threading.Thread(
        target=lambda: uvicorn.run(app, host="localhost", port=AGENT_PORTS[1], log_level="info"),
        daemon=True
    )
    fastapi_thread.start()
    logger.info(f"✅ FastAPI запущен на порту {AGENT_PORTS[1]}")
    
    # Redis worker
    try:
        worker = Agent1Worker()
        worker.run()
    except KeyboardInterrupt:
        logger.info("Выход")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
        exit(1)
