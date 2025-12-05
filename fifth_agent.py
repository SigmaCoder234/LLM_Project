#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
АГЕНТ №5 — АРБИТР И МОДЕРАТОР (Отправка результатов модераторам)
============================================================================
✅ ИСПРАВЛЕНО: Получает решения от агентов 3+4 и отправляет модератору

- Получает решение от Агента 5 (арбитра)
- Отправляет результаты модератору в Telegram
- Применяет действие (ban/mute/warn)
- Логирует все действия
"""

import json
import redis
import time
import asyncio
from typing import Dict, Any, List
from datetime import datetime
import aiohttp

# Импортируем конфигурацию
from config import (
    get_redis_config,
    QUEUE_AGENT_5_INPUT,
    QUEUE_AGENT_5_OUTPUT,
    TELEGRAM_BOT_TOKEN,
    MODERATOR_IDS,
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

async def send_to_moderator(chat_id: int, message_id: int, action: str, 
                           username: str, severity: int, confidence: int,
                           reason: str, message_text: str) -> bool:
    """
    Отправляет уведомление модератору о нарушении
    """
    try:
        # Формируем сообщение для модератора
        notification = f"""
🚨 <b>НАРУШЕНИЕ ОБНАРУЖЕНО</b>

👤 <b>Пользователь:</b> @{username}
💬 <b>Сообщение:</b> <code>{message_text[:100]}</code>
⚠️ <b>Серьезность:</b> {severity}/10
📊 <b>Уверенность:</b> {confidence}%
🔨 <b>Действие:</b> <b>{action.upper()}</b>

📝 <b>Причина:</b>
{reason}

🔗 <b>Ссылка:</b> https://t.me/c/{str(chat_id).replace("-100", "")}/{message_id}

⏰ <b>Время:</b> {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""

        url = f"{TELEGRAM_API_URL}/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        
        # Отправляем каждому модератору
        sent_count = 0
        for moderator_id in MODERATOR_IDS:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        url,
                        json={
                            "chat_id": moderator_id,
                            "text": notification,
                            "parse_mode": "HTML"
                        },
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as resp:
                        if resp.status == 200:
                            sent_count += 1
                            logger.info(f"📤 Отправлено модератору {moderator_id}")
                        else:
                            logger.error(f"❌ Ошибка отправки {moderator_id}: {resp.status}")
            except Exception as e:
                logger.error(f"❌ Ошибка при отправке модератору {moderator_id}: {e}")
        
        return sent_count > 0

    except Exception as e:
        logger.error(f"❌ Ошибка при подготовке сообщения: {e}")
        return False

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
            # Муджим пользователя на время
            import calendar
            until_date = int(time.time()) + (duration * 60)  # duration в минутах
            
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
                        logger.info(f"🔇 Пользователь {user_id} замужен на {duration} мин")
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
    Обрабатывает результат от Агента 5 (арбитра)
    и отправляет модератору
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
            # Отправляем модератору
            await send_to_moderator(
                chat_id=chat_id,
                message_id=message_id,
                action=action,
                username=username,
                severity=severity,
                confidence=confidence,
                reason=reason,
                message_text=message
            )

            # Применяем действие в чате
            await apply_moderation_action(
                chat_id=chat_id,
                user_id=user_id,
                action=action,
                duration=1440 if action == "mute" else 0
            )

            logger.info(f"✅ Действие {action} применено для {username}")
            return {
                "agent_id": 5,
                "status": "processed",
                "action": action,
                "user": username,
                "timestamp": datetime.now().isoformat()
            }
        else:
            logger.info(f"✅ Сообщение от {username} в порядке (нет нарушений)")
            return {
                "agent_id": 5,
                "status": "ok",
                "action": "none",
                "user": username,
                "timestamp": datetime.now().isoformat()
            }

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
        logger.info("✅ Агент 5 запущен (Модератор)")
        logger.info(f" Слушаю очередь: {QUEUE_AGENT_5_INPUT}")
        logger.info(f" Модераторы: {len(MODERATOR_IDS)} человек")
        logger.info(" Нажмите Ctrl+C для остановки\n")

        try:
            while True:
                try:
                    result = self.redis_client.blpop(QUEUE_AGENT_5_INPUT, timeout=1)
                    if result is None:
                        continue

                    queue_name, message_data = result
                    logger.info("📨 Получено новое решение")

                    # Парсим JSON
                    try:
                        input_data = json.loads(message_data)
                    except json.JSONDecodeError as e:
                        logger.error(f"❌ Невалидный JSON: {e}")
                        continue

                    # Обрабатываем асинхронно
                    output = asyncio.run(process_moderation_result(input_data))
                    
                    # Отправляем результат в очередь
                    try:
                        result_json = json.dumps(output, ensure_ascii=False)
                        self.redis_client.rpush(QUEUE_AGENT_5_OUTPUT, result_json)
                    except Exception as e:
                        logger.error(f"❌ Ошибка отправки результата: {e}")

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
