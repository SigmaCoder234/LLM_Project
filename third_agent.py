#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
АГЕНТ №3 — Полный модератор через Mistral AI (исправленная версия v0.4.2)
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

# Mistral AI импорты - исправленная версия для 0.4.2
try:
    from mistralai.client import MistralClient
    from mistralai.models.chat_completion import ChatMessage
    MISTRAL_IMPORT_SUCCESS = True
    MISTRAL_IMPORT_VERSION = "v0.4.2 (legacy)"
except ImportError:
    try:
        # Fallback для новой версии
        from mistralai import Mistral as MistralClient
        from mistralai import UserMessage, SystemMessage
        def ChatMessage(role, content): return {"role": role, "content": content}
        MISTRAL_IMPORT_SUCCESS = True
        MISTRAL_IMPORT_VERSION = "v1.0+ (новый SDK)"
    except ImportError:
        print("❌ Не удалось импортировать Mistral AI")
        MISTRAL_IMPORT_SUCCESS = False
        MISTRAL_IMPORT_VERSION = "none"
        # Заглушки
        class MistralClient:
            def __init__(self, api_key): pass
            def chat(self, **kwargs): 
                raise ImportError("Mistral AI не установлен")
        def ChatMessage(role, content): return {"role": role, "content": content}

# Импортируем централизованную конфигурацию
from config import (
    MISTRAL_API_KEY,
    MISTRAL_MODEL,
    MISTRAL_GENERATION_PARAMS,
    get_redis_config,
    QUEUE_AGENT_3_INPUT,
    QUEUE_AGENT_3_OUTPUT,
    QUEUE_AGENT_5_INPUT,
    AGENT_PORTS,
    DEFAULT_RULES,
    setup_logging
)

# ============================================================================
# ЛОГИРОВАНИЕ
# ============================================================================
logger = setup_logging("АГЕНТ 3")

# Проверяем импорты при запуске
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
# МОДЕРАЦИЯ ЧЕРЕЗ MISTRAL AI (ИСПРАВЛЕННАЯ ВЕРСИЯ)
# ============================================================================
def moderate_message_with_mistral(message: str, rules: List[str]) -> dict:
    """
    Полная модерация сообщения через Mistral AI с обновленным промптом v2.0
    """
    
    # Проверяем доступность Mistral AI
    if not MISTRAL_IMPORT_SUCCESS or not mistral_client:
        logger.warning("⚠️ Mistral AI недоступен, используем заглушку")
        return {
            "ban": False,
            "reason": "Вердикт: не банить\nПричина: Mistral AI недоступен\nУверенность: 0%",
            "confidence": 0.0,
            "method": "заглушка Mistral AI",
            "ai_response": False
        }
    
    try:
        # Если правил нет, используем стандартные
        if not rules:
            rules = DEFAULT_RULES
        
        rules_text = "\n".join([f"{i+1}. {rule}" for i, rule in enumerate(rules)])
        
        system_message = f"""Ты — модератор группового чата. Твоя задача — получать сообщения из чата и анализировать их с точки зрения соответствия правилам. По каждому сообщению выноси вердикт: «банить» или «не банить», указывая причину решения и степень уверенности в процентах.

ПРАВИЛА ЧАТА:
{rules_text}

Формат вывода:
Вердикт: <банить/не банить>
Причина: <текст причины>
Уверенность: <число от 0 до 100>%

ИНСТРУКЦИИ:
1. Анализируй сообщение строго по указанным правилам
2. Будь объективным в оценке
3. Указывай конкретную причину решения
4. Уверенность должна отражать степень нарушения (0-100%)

Это полный анализ сообщения модератором."""
        
        user_message = f"Сообщение пользователя:\n\"{message}\""
        
        messages = [
            ChatMessage(role="system", content=system_message),
            ChatMessage(role="user", content=user_message)
        ]
        
        response = mistral_client.chat(
            model=MISTRAL_MODEL,
            messages=messages,
            temperature=MISTRAL_GENERATION_PARAMS.get("temperature", 0.1),
            max_tokens=MISTRAL_GENERATION_PARAMS.get("max_tokens", 300),
            top_p=MISTRAL_GENERATION_PARAMS.get("top_p", 0.9)
        )
        
        content = response.choices[0].message.content
        
        # Парсим ответ в новом формате v2.0
        content_lower = content.lower()
        
        # Ищем вердикт
        ban = False
        if "вердикт:" in content_lower:
            verdict_line = [line for line in content.split('\n') if 'вердикт:' in line.lower()]
            if verdict_line:
                verdict_text = verdict_line[0].lower()
                if "банить" in verdict_text and "не банить" not in verdict_text:
                    ban = True
        
        # Ищем уверенность
        confidence = 0.75  # По умолчанию
        if "уверенность:" in content_lower:
            confidence_line = [line for line in content.split('\n') if 'уверенность:' in line.lower()]
            if confidence_line:
                try:
                    import re
                    numbers = re.findall(r'\d+', confidence_line[0])
                    if numbers:
                        confidence = int(numbers[0]) / 100.0
                        confidence = min(1.0, max(0.0, confidence))
                except:
                    confidence = 0.75
        
        return {
            "ban": ban,
            "reason": content,
            "confidence": confidence,
            "method": f"Mistral AI модератор ({MISTRAL_IMPORT_VERSION})",
            "ai_response": True
        }
        
    except Exception as e:
        logger.error(f"Ошибка Mistral AI модерации: {e}")
        return {
            "ban": False,
            "reason": f"Вердикт: не банить\nПричина: Ошибка ИИ анализа: {e}\nУверенность: 0%",
            "confidence": 0.0,
            "method": "ошибка Mistral AI",
            "ai_response": False
        }

# ============================================================================
# ОСНОВНАЯ ЛОГИКА АГЕНТА 3
# ============================================================================
def moderation_agent_3(input_data):
    """
    АГЕНТ 3 — Полный модератор через Mistral AI (исправленная версия v3.7).
    Глубокий анализ сообщения с использованием ИИ.
    """
    message = input_data.get("message", "")
    rules = input_data.get("rules", [])
    user_id = input_data.get("user_id")
    username = input_data.get("username")
    chat_id = input_data.get("chat_id")
    message_id = input_data.get("message_id")
    message_link = input_data.get("message_link", "")
    
    logger.info(f"Модерирую сообщение от @{username} в чате {chat_id}")
    
    if not message:
        return {
            "agent_id": 3,
            "ban": False,
            "reason": "Вердикт: не банить\nПричина: Пустое сообщение\nУверенность: 0%",
            "confidence": 0,
            "message": "",
            "user_id": user_id,
            "username": username,
            "chat_id": chat_id,
            "message_id": message_id,
            "status": "error"
        }
    
    # Если правил нет, используем стандартные
    if not rules:
        rules = DEFAULT_RULES
        logger.info("Используются стандартные правила v2.0")
    
    # Модерация через Mistral AI
    moderation_result = moderate_message_with_mistral(message, rules)
    
    output = {
        "agent_id": 3,
        "ban": moderation_result["ban"],
        "reason": moderation_result["reason"],
        "confidence": moderation_result["confidence"],
        "message": message,
        "user_id": user_id,
        "username": username,
        "chat_id": chat_id,
        "message_id": message_id,
        "message_link": message_link,
        "method": moderation_result["method"],
        "rules_used": rules,
        "ai_provider": f"Mistral AI ({MISTRAL_MODEL})",
        "import_version": MISTRAL_IMPORT_VERSION,
        "status": "success",
        "timestamp": datetime.now().isoformat()
    }
    
    if moderation_result["ban"]:
        logger.warning(f"БАН ⛔ для @{username}: {moderation_result['confidence']*100:.0f}% уверенности ({moderation_result['method']})")
    else:
        logger.info(f"ОК ✅ для @{username}: {moderation_result['confidence']*100:.0f}% уверенности ({moderation_result['method']})")
    
    return output

# ============================================================================
# РАБОТА С REDIS И ВЗАИМОДЕЙСТВИЕ МЕЖДУ АГЕНТАМИ
# ============================================================================
class Agent3Worker:
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
            result = moderation_agent_3(input_data)
            return result
        except json.JSONDecodeError as e:
            logger.error(f"Невалидный JSON: {e}")
            return {
                "agent_id": 3,
                "ban": False,
                "reason": f"Ошибка парсинга данных: {e}",
                "confidence": 0,
                "message": "",
                "status": "json_error"
            }
        except Exception as e:
            logger.error(f"Ошибка обработки сообщения: {e}")
            return {
                "agent_id": 3,
                "ban": False,
                "reason": f"Внутренняя ошибка агента 3: {e}",
                "confidence": 0,
                "message": "",
                "status": "error"
            }
    
    def send_result(self, result):
        """Отправляет результат в выходную очередь"""
        try:
            result_json = json.dumps(result, ensure_ascii=False)
            # Отправляем результат в очередь Агента 3
            self.redis_client.rpush(QUEUE_AGENT_3_OUTPUT, result_json)
            
            # Отправляем результат в очередь Агента 5
            self.redis_client.rpush(QUEUE_AGENT_5_INPUT, result_json)
            
            logger.info(f"✅ Результат отправлен в очереди")
            
        except Exception as e:
            logger.error(f"Не удалось отправить результат: {e}")
    
    def run(self):
        """Главный цикл обработки сообщений"""
        logger.info(f"✅ Агент 3 запущен (Mistral AI модератор исправленный v3.7)")
        logger.info(f"   Модель: {MISTRAL_MODEL}")
        logger.info(f"   Импорт: {MISTRAL_IMPORT_VERSION}")
        logger.info(f"   Статус Mistral AI: {'✅ Доступен' if mistral_client else '❌ Недоступен'}")
        logger.info(f"   Слушаю очередь: {QUEUE_AGENT_3_INPUT}")
        logger.info(f"   Отправляю результаты в: {QUEUE_AGENT_3_OUTPUT}")
        logger.info(f"   Отправляю в Агента 5: {QUEUE_AGENT_5_INPUT}")
        logger.info(f"   Стандартные правила v2.0: {DEFAULT_RULES}")
        logger.info("   Нажмите Ctrl+C для остановки\n")
        
        try:
            while True:
                try:
                    result = self.redis_client.blpop(QUEUE_AGENT_3_INPUT, timeout=1)
                    if result is None:
                        continue
                    
                    queue_name, message_data = result
                    logger.info(f"📨 Получено сообщение")
                    
                    output = self.process_message(message_data)
                    self.send_result(output)
                    
                    logger.info(f"✅ Обработка завершена\n")
                    
                except Exception as e:
                    logger.error(f"Ошибка в цикле: {e}")
                    time.sleep(1)
                    
        except KeyboardInterrupt:
            logger.info("\n❌ Агент 3 остановлен (Ctrl+C)")
        finally:
            logger.info("Агент 3 завершил работу")

# ============================================================================
# FASTAPI ПРИЛОЖЕНИЕ
# ============================================================================
app = FastAPI(
    title="🤖 Агент №3 - Модератор (Mistral AI исправленный)",
    description="Полная модерация сообщений через Mistral AI",
    version="3.7"
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
        "agent_id": 3,
        "name": "Агент №3 (Mistral AI Модератор)",
        "version": "3.7 (исправленный)",
        "ai_provider": f"Mistral AI ({MISTRAL_MODEL})" if mistral_client else "Mistral AI (недоступен)",
        "import_version": MISTRAL_IMPORT_VERSION,
        "import_success": MISTRAL_IMPORT_SUCCESS,
        "client_status": "✅ Создан" if mistral_client else "❌ Не создан",
        "prompt_version": "v2.0 - новый формат",
        "configuration": "Environment variables (.env)",
        "default_rules": DEFAULT_RULES,
        "timestamp": datetime.now().isoformat(),
        "redis_queue": QUEUE_AGENT_3_INPUT,
        "uptime_seconds": int(time.time())
    }

@app.post("/process_message")
async def process_message_endpoint(message_data: dict):
    """Обработка сообщения через API"""
    result = moderation_agent_3(message_data)
    return result

# ============================================================================
# ЗАПУСК FASTAPI В ОТДЕЛЬНОМ ПОТОКЕ
# ============================================================================
def run_fastapi():
    """Запуск FastAPI сервера"""
    uvicorn.run(app, host="localhost", port=AGENT_PORTS[3], log_level="info")

# ============================================================================
# ТОЧКА ВХОДА
# ============================================================================
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        mode = sys.argv[1]
        if mode == "test":
            # Тестирование с новым форматом v2.0
            test_cases = [
                {
                    "message": "Привет всем! Как дела?",
                    "rules": [],
                    "description": "Нормальное сообщение"
                },
                {
                    "message": "Ты дурак и идиот! Хуй тебе!",
                    "rules": DEFAULT_RULES,
                    "description": "Мат и оскорбления"
                },
                {
                    "message": "Переходи по ссылке t.me/spam_channel! Заработок от 100$ в день!",
                    "rules": DEFAULT_RULES,
                    "description": "Спам с ссылкой"
                },
                {
                    "message": "Все эти негры должны убираться отсюда!",
                    "rules": DEFAULT_RULES,
                    "description": "Расовая дискриминация"
                }
            ]
            
            for i, test_case in enumerate(test_cases, 1):
                print(f"\n--- Тест {i}: {test_case['description']} ---")
                
                test_input = {
                    "message": test_case["message"],
                    "rules": test_case["rules"],
                    "user_id": 123 + i,
                    "username": f"test_user_{i}",
                    "chat_id": -100,
                    "message_id": i,
                    "message_link": f"https://t.me/test/{i}"
                }
                
                result = moderation_agent_3(test_input)
                
                print(f"Вердикт: {'БАН' if result['ban'] else 'ОК'}")
                print(f"Уверенность: {result['confidence']*100:.0f}%")
                print(f"Метод: {result.get('method', 'N/A')}")
                print(f"Причина: {result['reason']}")
                
        elif mode == "api":
            # Запуск только FastAPI
            run_fastapi()
    else:
        # Запуск FastAPI в отдельном потоке
        fastapi_thread = threading.Thread(target=run_fastapi, daemon=True)
        fastapi_thread.start()
        logger.info(f"✅ FastAPI сервер запущен на порту {AGENT_PORTS[3]}")
        
        # Запуск основного Redis worker
        try:
            worker = Agent3Worker()
            worker.run()
        except KeyboardInterrupt:
            logger.info("Выход из программы")
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")
