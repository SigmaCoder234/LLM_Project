#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
АГЕНТ №1 — Координатор Telegram бота (исправленная полная версия 1.8)
"""

import json
import redis
import time
from typing import Dict, Any, List
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import threading

# Mistral AI импорты
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
            return {"role": role, "content": content}


        MISTRAL_IMPORT_SUCCESS = True
        MISTRAL_IMPORT_VERSION = "v1.0+ (новый SDK)"
    except ImportError:
        print("❌ Не удалось импортировать Mistral AI")
        MISTRAL_IMPORT_SUCCESS = False
        MISTRAL_IMPORT_VERSION = "none"


        class MistralClient:
            def __init__(self, api_key): pass

            def chat(self, **kwargs):
                raise ImportError("Mistral AI не установлен")


        def ChatMessage(role, content):
            return {"role": role, "content": content}

from config import (
    MISTRAL_API_KEY,
    MISTRAL_MODEL,
    MISTRAL_GENERATION_PARAMS,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_API_URL,
    get_redis_config,
    QUEUE_AGENT_1_OUTPUT,
    QUEUE_AGENT_2_INPUT,
    QUEUE_AGENT_3_INPUT,
    QUEUE_AGENT_4_INPUT,
    AGENT_PORTS,
    DEFAULT_RULES,
    setup_logging
)

# ============================================================================
# ЛОГИРОВАНИЕ
# ============================================================================

logger = setup_logging("АГЕНТ 1")

if MISTRAL_IMPORT_SUCCESS:
    logger.info(f"✅ Mistral AI импортирован успешно ({MISTRAL_IMPORT_VERSION})")
else:
    logger.error("❌ Mistral AI не импортирован, работа в режиме заглушки")

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ MISTRAL AI
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
# ФУНКЦИЯ КООРДИНАЦИИ С MISTRAL AI (ИСПРАВЛЕННАЯ - ПОЛНАЯ ВЕРСИЯ)
# ============================================================================

def coordinate_with_mistral(message: str, rules: List[str] = None) -> dict:
    """
    Координирует обработку сообщения с помощью Mistral AI.
    Определяет маршрутизацию: какой из агентов должен обработать сообщение.
    """
    if not MISTRAL_IMPORT_SUCCESS or not mistral_client:
        logger.warning("⚠️ Mistral AI недоступен, используем заглушку")
        return {
            "route": "BOTH",
            "priority": "MEDIUM",
            "strategy": "BOTH",
            "confidence": 0.5,
            "reasoning": "Mistral AI недоступен, консервативная стратегия",
            "ai_model": "fallback"
        }

    try:
        if not rules:
            rules = DEFAULT_RULES

        rules_text = "\n".join([f"{i + 1}. {rule}" for i, rule in enumerate(rules)])

        system_message = f"""Ты — координатор системы модерации Telegram чата.

ПРАВИЛА ЧАТА:

{rules_text}

ТВОЯ ЗАДАЧА:

Проанализируй сообщение и определи оптимальную стратегию обработки:

1. SIMPLE - только эвристический анализ (Агент 4)
2. COMPLEX - только ИИ анализ (Агент 3)  
3. BOTH - оба агента (для неоднозначных случаев)

Также определи приоритет: LOW/MEDIUM/HIGH

Формат ответа:

МАРШРУТ: [SIMPLE/COMPLEX/BOTH]
ПРИОРИТЕТ: [LOW/MEDIUM/HIGH]
УВЕРЕННОСТЬ: [0-100]%
ОБОСНОВАНИЕ: [краткое объяснение]"""

        user_message = f"Сообщение: \"{message}\""

        messages = [
            ChatMessage(role="system", content=system_message),
            ChatMessage(role="user", content=user_message)
        ]

        response = mistral_client.chat(
            model=MISTRAL_MODEL,
            messages=messages,
            temperature=MISTRAL_GENERATION_PARAMS.get("temperature", 0.1),
            max_tokens=MISTRAL_GENERATION_PARAMS.get("max_tokens", 300)
        )

        content = response.choices[0].message.content
        content_lower = content.lower()

        # Парсим маршрут
        route = "BOTH"
        if "simple" in content_lower and "complex" not in content_lower:
            route = "SIMPLE"
        elif "complex" in content_lower and "simple" not in content_lower:
            route = "COMPLEX"
        else:
            route = "BOTH"

        # Парсим приоритет
        priority = "MEDIUM"
        if "high" in content_lower:
            priority = "HIGH"
        elif "low" in content_lower:
            priority = "LOW"

        # Парсим уверенность
        confidence = 0.7
        if "уверенность:" in content_lower:
            try:
                line = [l for l in content.split('\n') if 'уверенность:' in l.lower()][0]
                numbers = [int(n) for n in line.split() if n.isdigit()]
                if numbers:
                    confidence = numbers[0] / 100.0
            except:
                confidence = 0.7

        return {
            "route": route,
            "priority": priority,
            "strategy": route,
            "confidence": confidence,
            "reasoning": content,
            "ai_model": MISTRAL_MODEL,
            "status": "success"
        }

    except Exception as e:
        logger.error(f"❌ Ошибка координации Mistral: {e}")
        return {
            "route": "BOTH",
            "priority": "MEDIUM",
            "strategy": "BOTH",
            "confidence": 0.5,
            "reasoning": f"Ошибка ИИ координации: {e}",
            "ai_model": "fallback",
            "status": "error"
        }


# ============================================================================
# ОСНОВНАЯ ФУНКЦИЯ АГЕНТА 1
# ============================================================================

def coordination_agent_1(input_data):
    """
    АГЕНТ 1 — Координатор (маршрутизатор) многоагентной системы.
    Получает сообщения от Telegram бота и маршрутизирует их к соответствующим агентам.
    """

    message = input_data.get("message", "")
    rules = input_data.get("rules", [])
    user_id = input_data.get("user_id")
    username = input_data.get("username", "unknown")
    chat_id = input_data.get("chat_id")
    message_id = input_data.get("message_id")
    message_link = input_data.get("message_link", "")

    logger.info(f"📨 Получено сообщение от @{username} в чате {chat_id}")

    if not message:
        return {
            "agent_id": 1,
            "action": "error",
            "reason": "Пустое сообщение",
            "status": "error"
        }

    if not rules:
        rules = DEFAULT_RULES

    # Координация через Mistral
    coordination_result = coordinate_with_mistral(message, rules)

    routing_strategy = coordination_result.get("route", "BOTH")

    output = {
        "agent_id": 1,
        "action": "coordinate",
        "message": message,
        "user_id": user_id,
        "username": username,
        "chat_id": chat_id,
        "message_id": message_id,
        "message_link": message_link,
        "routing_strategy": routing_strategy,
        "priority": coordination_result.get("priority", "MEDIUM"),
        "confidence": coordination_result.get("confidence", 0.5),
        "reasoning": coordination_result.get("reasoning", ""),
        "rules": rules,
        "ai_model": MISTRAL_MODEL,
        "coordination_method": coordination_result.get("ai_model", "unknown"),
        "status": "success",
        "timestamp": datetime.now().isoformat()
    }

    logger.info(f"✅ Маршрут: {routing_strategy}, Приоритет: {output['priority']}")

    return output


# ============================================================================
# REDIS WORKER
# ============================================================================

class Agent1Worker:
    def __init__(self):
        try:
            redis_config = get_redis_config()
            self.redis_client = redis.Redis(**redis_config)
            self.redis_client.ping()
            logger.info(f"✅ Подключение к Redis успешно")
        except Exception as e:
            logger.error(f"❌ Не удалось подключиться к Redis: {e}")
            raise

    def process_message(self, message_data):
        """Обрабатывает сообщение от входной очереди"""
        try:
            input_data = json.loads(message_data)
            result = coordination_agent_1(input_data)
            return result
        except json.JSONDecodeError as e:
            logger.error(f"Невалидный JSON: {e}")
            return {"agent_id": 1, "action": "error", "reason": f"JSON error: {e}", "status": "json_error"}
        except Exception as e:
            logger.error(f"Ошибка обработки сообщения: {e}")
            return {"agent_id": 1, "action": "error", "reason": str(e), "status": "error"}

    def send_to_agents(self, coordination_result, original_data):
        """Отправляет сообщение нужным агентам на основе маршрутизации"""
        routing_strategy = coordination_result.get("routing_strategy", "BOTH")

        # Формируем данные для отправки
        agent_input = {
            "message": original_data.get("message"),
            "rules": original_data.get("rules", []),
            "user_id": original_data.get("user_id"),
            "username": original_data.get("username"),
            "chat_id": original_data.get("chat_id"),
            "message_id": original_data.get("message_id"),
            "message_link": original_data.get("message_link", ""),
            "priority": coordination_result.get("priority", "MEDIUM"),
            "routing_from_agent": 1
        }

        agent_input_json = json.dumps(agent_input, ensure_ascii=False)

        # Отправляем в соответствии со стратегией
        if routing_strategy in ["SIMPLE", "BOTH"]:
            self.redis_client.rpush(QUEUE_AGENT_4_INPUT, agent_input_json)
            logger.info(f"➡️ Отправлено Агенту 4 (эвристика)")

        if routing_strategy in ["COMPLEX", "BOTH"]:
            self.redis_client.rpush(QUEUE_AGENT_3_INPUT, agent_input_json)
            logger.info(f"➡️ Отправлено Агенту 3 (ИИ анализ)")

    def run(self):
        """Главный цикл обработки сообщений"""
        logger.info(f"✅ Агент 1 запущен (Координатор v1.8 с Mistral AI)")
        logger.info(f" Модель: {MISTRAL_MODEL}")
        logger.info(f" Импорт: {MISTRAL_IMPORT_VERSION}")
        logger.info(f" Статус Mistral: {'✅ Доступен' if mistral_client else '❌ Недоступен'}")
        logger.info(f" Слушаю очередь: {QUEUE_AGENT_1_OUTPUT}")
        logger.info(f" Стандартные правила: {DEFAULT_RULES}")
        logger.info(" Нажмите Ctrl+C для остановки\n")

        try:
            while True:
                try:
                    result = self.redis_client.blpop(QUEUE_AGENT_1_OUTPUT, timeout=1)
                    if result is None:
                        continue

                    queue_name, message_data = result
                    logger.info(f"📨 Получено сообщение")

                    input_data = json.loads(message_data)
                    coordination_result = self.process_message(message_data)

                    self.send_to_agents(coordination_result, input_data)

                    logger.info(f"✅ Маршрутизация завершена\n")

                except Exception as e:
                    logger.error(f"Ошибка в цикле: {e}")
                    time.sleep(1)

        except KeyboardInterrupt:
            logger.info("\n❌ Агент 1 остановлен (Ctrl+C)")
        finally:
            logger.info("Агент 1 завершил работу")


# ============================================================================
# FASTAPI ПРИЛОЖЕНИЕ
# ============================================================================

app = FastAPI(
    title="🤖 Агент №1 - Координатор (Mistral AI)",
    description="Координация многоагентной системы модерации",
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
        "name": "Агент №1 (Координатор)",
        "version": "1.8 (Mistral AI исправленный)",
        "ai_provider": f"Mistral AI ({MISTRAL_MODEL})" if mistral_client else "Mistral AI (недоступен)",
        "import_version": MISTRAL_IMPORT_VERSION,
        "import_success": MISTRAL_IMPORT_SUCCESS,
        "client_status": "✅ Создан" if mistral_client else "❌ Не создан",
        "prompt_version": "v2.0 - обновленный формат",
        "configuration": "Environment variables (.env)",
        "default_rules": DEFAULT_RULES,
        "timestamp": datetime.now().isoformat(),
        "redis_queue": QUEUE_AGENT_1_OUTPUT,
        "uptime_seconds": int(time.time())
    }


def run_fastapi():
    """Запуск FastAPI сервера"""
    uvicorn.run(app, host="localhost", port=AGENT_PORTS[1], log_level="info")


# ============================================================================
# ТОЧКА ВХОДА
# ============================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        mode = sys.argv[1]

        if mode == "test":
            # Тестирование координации
            test_cases = [
                {
                    "message": "Привет всем! Как дела?",
                    "description": "Нормальное сообщение"
                },
                {
                    "message": "Ты дурак! Хуй тебе!",
                    "description": "Мат и оскорбления"
                },
                {
                    "message": "Все негры должны убираться!",
                    "description": "Дискриминация"
                }
            ]

            for i, test_case in enumerate(test_cases, 1):
                print(f"\n--- Тест {i}: {test_case['description']} ---")
                test_input = {
                    "message": test_case["message"],
                    "rules": DEFAULT_RULES,
                    "user_id": 123 + i,
                    "username": f"test_user_{i}",
                    "chat_id": -100,
                    "message_id": i,
                    "message_link": f"https://t.me/test/{i}"
                }

                result = coordination_agent_1(test_input)
                print(f"Маршрут: {result.get('routing_strategy', 'N/A')}")
                print(f"Приоритет: {result.get('priority', 'N/A')}")
                print(f"Уверенность: {result.get('confidence', 0) * 100:.0f}%")

        elif mode == "api":
            run_fastapi()

        else:
            # Запуск FastAPI в отдельном потоке
            fastapi_thread = threading.Thread(target=run_fastapi, daemon=True)
            fastapi_thread.start()
            logger.info(f"✅ FastAPI сервер запущен на порту {AGENT_PORTS[1]}")

            # Запуск основного Redis worker
            try:
                worker = Agent1Worker()
                worker.run()
            except KeyboardInterrupt:
                logger.info("Выход из программы")
            except Exception as e:
                logger.error(f"Критическая ошибка: {e}")

    else:
        # Запуск FastAPI в отдельном потоке
        fastapi_thread = threading.Thread(target=run_fastapi, daemon=True)
        fastapi_thread.start()
        logger.info(f"✅ FastAPI сервер запущен на порту {AGENT_PORTS[1]}")

        # Запуск основного Redis worker
        try:
            worker = Agent1Worker()
            worker.run()
        except KeyboardInterrupt:
            logger.info("Выход из программы")
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")