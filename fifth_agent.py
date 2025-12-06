#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🤖 АГЕНТ №5 — АРБИТР И МОДЕРАТОР (ИСПРАВЛЕНО!)

✅ Получает решения от агентов 3+4
✅ Применяет действие (ban/mute/warn)
✅ ПИШЕТ РЕЗУЛЬТАТЫ В REDIS (не отправляет сам!)
✅ БОТ читает результаты и отправляет модераторам конкретного чата
"""

import json
import redis
import time
import asyncio
from typing import Dict, Any
from datetime import datetime
import aiohttp

# Импортируем конфигурацию
from config import (
    get_redis_config,
    QUEUE_AGENT_5_INPUT,
    QUEUE_AGENT_5_OUTPUT,
    TELEGRAM_BOT_TOKEN,
    setup_logging,
)

# ============================================================================
# ЛОГИРОВАНИЕ
# ============================================================================

logger = setup_logging("АГЕНТ 5")

# ============================================================================
# TELEGRAM API
# ============================================================================

TELEGRAM_API_URL = "https://api.telegram.org"

async def apply_moderation_action(chat_id: int, user_id: int,
                                  action: str, duration: int = 0) -> bool:
    """
    Применяет действие модерации (ban/mute/warn)
    """
    try:
        url = f"{TELEGRAM_API_URL}/bot{TELEGRAM_BOT_TOKEN}"
        
        if action.lower() == "ban":
            # Блокируем пользователя
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{url}/banChatMember",
                    json={
                        "chat_id": chat_id,
                        "user_id": user_id,
                        "revoke_messages": True
                    },
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        logger.info(f"🚫 Пользователь {user_id} забанен в чате {chat_id}")
                        return True
        
        elif action.lower() == "mute":
            # Мучим пользователя на время
            until_date = int(time.time()) + (duration * 60)
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{url}/restrictChatMember",
                    json={
                        "chat_id": chat_id,
                        "user_id": user_id,
                        "permissions": {
                            "can_send_messages": False,
                            "can_send_media_messages": False,
                            "can_send_other_messages": False,
                            "can_add_web_page_previews": False
                        },
                        "until_date": until_date
                    },
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        logger.info(f"🔇 Пользователь {user_id} замучен на {duration} мин")
                        return True
        
        elif action.lower() == "warn":
            # Просто логируем предупреждение
            logger.warning(f"⚠️ Предупреждение для {user_id} в чате {chat_id}")
            return True
        
        return False
    
    except Exception as e:
        logger.error(f"❌ Ошибка при применении действия: {e}")
        return False

# ============================================================================
# ОСНОВНАЯ ФУНКЦИЯ АГЕНТА 5
# ============================================================================

async def process_moderation_result(result_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Обрабатывает результат от агентов 3+4
    Применяет действие
    ПИШЕТ РЕЗУЛЬТАТЫ В REDIS для БОТа
    """
    try:
        # Получаем данные
        message = result_data.get("message", "")
        action = result_data.get("action", "none").lower()
        chat_id = result_data.get("chat_id", 0)
        user_id = result_data.get("user_id", 0)
        username = result_data.get("username", "unknown")
        message_id = result_data.get("message_id", 0)
        severity = result_data.get("severity", 0)
        confidence = result_data.get("confidence", 0)
        reason = result_data.get("explanation", "Нарушение правил чата")
        
        logger.info(f"🔍 Обрабатываю результат: действие={action}, серьезность={severity}/10")
        
        # Если нарушение обнаружено
        if action in ["ban", "mute", "warn"]:
            # ✅ ПРИМЕНЯЕМ ДЕЙСТВИЕ В ЧАТЕ
            await apply_moderation_action(
                chat_id=chat_id,
                user_id=user_id,
                action=action,
                duration=1440 if action == "mute" else 0
            )
            
            logger.info(f"✅ Действие {action} применено для {username}")
            
            # ✅ ПИШЕМ РЕЗУЛЬТАТ В REDIS для БОТа
            output = {
                "agent_id": 5,
                "status": "processed",
                "action": action,
                "user": username,
                "user_id": user_id,
                "chat_id": chat_id,
                "message_id": message_id,
                "message_text": message,
                "severity": severity,
                "confidence": confidence,
                "reason": reason,
                "timestamp": datetime.now().isoformat()
            }
            
            return output
        
        else:
            logger.info(f"✅ Сообщение от {username} в порядке (нет нарушений)")
            
            # ✅ ТАКЖЕ ОТПРАВЛЯЕМ "ОК" РЕЗУЛЬТАТ В REDIS
            output = {
                "agent_id": 5,
                "status": "ok",
                "action": "none",
                "user": username,
                "user_id": user_id,
                "chat_id": chat_id,
                "message_id": message_id,
                "message_text": message,
                "severity": 0,
                "confidence": confidence,
                "reason": "Нарушений не обнаружено",
                "timestamp": datetime.now().isoformat()
            }
            
            return output
    
    except Exception as e:
        logger.error(f"❌ Ошибка обработки: {e}")
        return {
            "agent_id": 5,
            "status": "error",
            "error": str(e)
        }

# ============================================================================
# REDIS WORKER
# ============================================================================

class Agent5Worker:
    def __init__(self):
        try:
            redis_config = get_redis_config()
            self.redis_client = redis.Redis(**redis_config)
            self.redis_client.ping()
            logger.info("✅ Подключение к Redis успешно")
        except Exception as e:
            logger.error(f"❌ Не удалось подключиться к Redis: {e}")
            raise
    
    def run(self):
        """Главный цикл обработки сообщений"""
        logger.info("✅ Агент 5 запущен (Арбитр + Модератор)")
        logger.info(f"📬 Слушаю очередь: {QUEUE_AGENT_5_INPUT}")
        logger.info(f"📤 Результаты в очередь: queue:agent2:output")
        logger.info("⏱️  Нажмите Ctrl+C для остановки\n")
        
        try:
            while True:
                try:
                    result = self.redis_client.blpop(QUEUE_AGENT_5_INPUT, timeout=1)
                    
                    if result is None:
                        continue
                    
                    queue_name, message_data = result
                    logger.info("📨 Получено новое решение от Агента 4")
                    
                    # Парсим JSON
                    try:
                        input_data = json.loads(message_data)
                    except json.JSONDecodeError as e:
                        logger.error(f"❌ Невалидный JSON: {e}")
                        continue
                    
                    # Обрабатываем асинхронно
                    output = asyncio.run(process_moderation_result(input_data))
                    
                    # ✅ ПИШЕМ РЕЗУЛЬТАТ В REDIS для БОТа
                    try:
                        result_json = json.dumps(output, ensure_ascii=False)
                        # Пишем в ту же очередь, где БОТ их читает!
                        self.redis_client.rpush("queue:agent2:output", result_json)
                        logger.info(f"📤 ✅ Результат отправлен в Redis: action={output.get('action')}")
                    except Exception as e:
                        logger.error(f"❌ Ошибка отправки результата в Redis: {e}")
                    
                    logger.info("✅ Обработка завершена\n")
                
                except Exception as e:
                    logger.error(f"❌ Ошибка в цикле: {e}")
                    time.sleep(1)
        
        except KeyboardInterrupt:
            logger.info("\n❌ Агент 5 остановлен (Ctrl+C)")
        finally:
            logger.info("Агент 5 завершил работу")

# ============================================================================
# ТОЧКА ВХОДА
# ============================================================================

if __name__ == "__main__":
    try:
        worker = Agent5Worker()
        worker.run()
    except KeyboardInterrupt:
        logger.info("Выход")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
