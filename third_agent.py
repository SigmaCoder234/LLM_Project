#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
АГЕНТ №3 — Mistral AI модератор (v2.0)
"""

import json
import redis
import time
from typing import Dict, Any, List
from datetime import datetime
import asyncio
from mistralai.client import MistralClient
from mistralai.models.chat_completion import ChatMessage

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

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ MISTRAL AI
# ============================================================================
mistral_client = MistralClient(api_key=MISTRAL_API_KEY)

# ============================================================================
# АНАЛИЗ ЧЕРЕЗ MISTRAL AI С НОВЫМ ПРОМПТОМ v2.0
# ============================================================================
def analyze_message_with_mistral(message: str, rules: List[str]) -> dict:
    """
    Анализ сообщения через Mistral AI с обновленным промптом v2.0
    """
    try:
        # Если правил нет, используем стандартные
        if not rules:
            rules = DEFAULT_RULES
            logger.info("Используются стандартные правила v2.0")
        
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

Если правила отсутствуют, используй стандартную настройку:
1. Запрещена расовая дискриминация
2. Запрещены ссылки"""
        
        user_message = f"Сообщение пользователя:\n\"{message}\""
        
        messages = [
            ChatMessage(role="system", content=system_message),
            ChatMessage(role="user", content=user_message)
        ]
        
        response = mistral_client.chat(
            model=MISTRAL_MODEL,
            messages=messages,
            temperature=MISTRAL_GENERATION_PARAMS["temperature"],
            max_tokens=MISTRAL_GENERATION_PARAMS["max_tokens"],
            top_p=MISTRAL_GENERATION_PARAMS["top_p"]
        )
        
        content = response.choices[0].message.content
        
        # Парсим ответ в новом формате
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
        confidence = 0.6  # По умолчанию
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
                    confidence = 0.6
        
        return {
            "ban": ban,
            "reason": content,
            "confidence": confidence,
            "rules_used": rules,
            "ai_response": True,
            "model": MISTRAL_MODEL,
            "status": "success"
        }
        
    except Exception as e:
        logger.error(f"Ошибка Mistral AI анализа: {e}")
        return {
            "ban": False,
            "reason": f"Вердикт: не банить\nПричина: Ошибка ИИ анализа: {e}\nУверенность: 0%",
            "confidence": 0.0,
            "rules_used": rules if rules else DEFAULT_RULES,
            "ai_response": False,
            "model": "error",
            "status": "error"
        }

# ============================================================================
# ОСНОВНАЯ ЛОГИКА АГЕНТА 3
# ============================================================================
def moderation_agent_3(input_data):
    """
    АГЕНТ 3 — Mistral AI модератор с новым промптом v2.0.
    Анализирует сообщения через Mistral AI API.
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
    
    # Анализируем сообщение через Mistral AI
    analysis_result = analyze_message_with_mistral(message, rules)
    
    # Formируем результат
    output = {
        "agent_id": 3,
        "ban": analysis_result["ban"],
        "reason": analysis_result["reason"],
        "confidence": analysis_result["confidence"],
        "message": message,
        "user_id": user_id,
        "username": username,
        "chat_id": chat_id,
        "message_id": message_id,
        "message_link": message_link,
        "rules_used": analysis_result["rules_used"],
        "ai_model": analysis_result["model"],
        "ai_provider": "Mistral AI",
        "prompt_version": "v2.0 - новый формат",
        "status": analysis_result["status"],
        "timestamp": datetime.now().isoformat()
    }
    
    if analysis_result["ban"]:
        logger.warning(f"БАН ⛔ для @{username}: {analysis_result['confidence']*100:.0f}% уверенности (Mistral AI)")
    else:
        logger.info(f"ОК ✅ для @{username}: {analysis_result['confidence']*100:.0f}% уверенности (Mistral AI)")
    
    return output

# ============================================================================
# РАБОТА С REDIS
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
            
            # Отправляем результат в выходную очередь Агента 3
            self.redis_client.rpush(QUEUE_AGENT_3_OUTPUT, result_json)
            
            # Отправляем результат в очередь Агента 5 (арбитр)
            self.redis_client.rpush(QUEUE_AGENT_5_INPUT, result_json)
            
            logger.info(f"✅ Результат отправлен в очереди")
            
        except Exception as e:
            logger.error(f"Не удалось отправить результат: {e}")
    
    def run(self):
        """Главный цикл обработки сообщений"""
        logger.info(f"✅ Агент 3 запущен (Mistral AI модератор v3.6)")
        logger.info(f"   Модель: {MISTRAL_MODEL}")
        logger.info(f"   Слушаю очередь: {QUEUE_AGENT_3_INPUT}")
        logger.info(f"   Отправляю результаты в: {QUEUE_AGENT_3_OUTPUT}")
        logger.info(f"   Отправляю в Агента 5: {QUEUE_AGENT_5_INPUT}")
        logger.info(f"   Стандартные правила v2.0: {DEFAULT_RULES}")
        logger.info(f"   ИИ провайдер: Mistral AI")
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
# HEALTH CHECK HTTP SERVER
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
                    "name": "Агент №3 (Mistral AI модератор)",
                    "version": "3.6 (Mistral)",
                    "ai_provider": f"Mistral AI ({MISTRAL_MODEL})",
                    "prompt_version": "v2.0 - новый формат",
                    "configuration": "Environment variables (.env)",
                    "default_rules": DEFAULT_RULES,
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
    
    server = HTTPServer(('localhost', AGENT_PORTS[3]), HealthCheckHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"✅ Health check сервер запущен на порту {AGENT_PORTS[3]}")

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
                print(f"Модель: {result.get('ai_model', 'N/A')}")
                print(f"Причина: {result['reason']}")
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