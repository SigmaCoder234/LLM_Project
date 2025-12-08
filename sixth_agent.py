#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🤖 АГЕНТ №6 — АНАЛИЗ МЕДИА (PHOTO + VIDEO)
✅ Получает фото/видео из Redis
✅ Использует Mistral Vision для анализа
✅ ПИШЕТ РЕЗУЛЬТАТЫ В REDIS для БОТа
✅ Обнаруживает обнажённость, насилие, экстремизм
"""

import json
import redis
import time
import asyncio
import os
import base64
from typing import Dict, Any
from datetime import datetime
from pathlib import Path
import aiohttp

# Импортируем конфигурацию
from config import (
    get_redis_config,
    QUEUE_AGENT_6_INPUT,
    QUEUE_AGENT_6_OUTPUT,
    MISTRAL_API_KEY,
    setup_logging,
)

# ============================================================================
# ЛОГИРОВАНИЕ
# ============================================================================

logger = setup_logging("АГЕНТ 6")

# ============================================================================
# MISTRAL VISION API
# ============================================================================

MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"

async def analyze_image_with_mistral(image_path: str) -> Dict[str, Any]:
    """
    Анализирует изображение с помощью Mistral Vision
    """
    try:
        logger.info(f"🔍 Начинаю анализ изображения: {image_path}")
        
        # Читаем изображение и конвертируем в base64
        if not os.path.exists(image_path):
            logger.warning(f"⚠️ Файл не найден: {image_path}")
            return {
                "verdict": False,
                "reason": "Файл не скачан",
                "severity": 0,
                "confidence": 0
            }
        
        with open(image_path, "rb") as img_file:
            image_data = base64.b64encode(img_file.read()).decode("utf-8")
        
        logger.info(f"📸 Файл прочитан: {len(image_data)} байт")
        
        # Определяем тип файла
        file_ext = Path(image_path).suffix.lower()
        mime_type = "image/jpeg" if file_ext in [".jpg", ".jpeg"] else "image/png"
        
        logger.info(f"📋 MIME-type: {mime_type}")
        
        # Формируем запрос к Mistral Vision
        headers = {
            "Authorization": f"Bearer {MISTRAL_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "pixtral-12b-2409",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{image_data}"
                            }
                        },
                        {
                            "type": "text",
                            "text": """Проанализируй это изображение и ответь ТОЛЬКО JSON:
{
  "has_nudity": boolean,
  "has_violence": boolean,
  "has_extremism": boolean,
  "has_inappropriate": boolean,
  "severity": число 0-10,
  "description": "краткое описание",
  "confidence": число 0-100
}

Ищи следующие нарушения:
- Обнажённость (nude/sexual content)
- Насилие
- Экстремизм
- Оскорбительный контент

Ответь ТОЛЬКО JSON, без других текстов!"""
                        }
                    ]
                }
            ],
            "max_tokens": 300
        }
        
        logger.info("🌐 Отправляю запрос к Mistral API...")
        
        async with aiohttp.ClientSession() as session:
            async with session.post(MISTRAL_API_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                logger.info(f"📡 Ответ от API: статус {resp.status}")
                
                if resp.status == 200:
                    result = await resp.json()
                    
                    # Парсим ответ
                    try:
                        response_text = result["choices"][0]["message"]["content"]
                        logger.info(f"📝 Ответ Mistral: {response_text[:200]}")
                        
                        # Пытаемся найти JSON в ответе
                        json_start = response_text.find("{")
                        json_end = response_text.rfind("}") + 1
                        
                        if json_start >= 0 and json_end > json_start:
                            json_str = response_text[json_start:json_end]
                            analysis = json.loads(json_str)
                            
                            severity = int(analysis.get("severity", 0))
                            severity = min(10, max(0, severity))
                            
                            confidence = int(analysis.get("confidence", 50))
                            confidence = min(100, max(0, confidence))
                            
                            logger.info(f"✅ Анализ: severity={severity}, nudity={analysis.get('has_nudity', False)}, confidence={confidence}%")
                            
                            return {
                                "verdict": any([
                                    analysis.get("has_nudity", False),
                                    analysis.get("has_violence", False),
                                    analysis.get("has_extremism", False),
                                    analysis.get("has_inappropriate", False)
                                ]),
                                "reason": analysis.get("description", "Контент нарушает правила"),
                                "severity": severity,
                                "confidence": confidence,
                                "details": analysis
                            }
                    except Exception as e:
                        logger.error(f"⚠️ Ошибка парсинга JSON: {e}")
                        return {
                            "verdict": False,
                            "reason": f"Ошибка анализа: {str(e)}",
                            "severity": 0,
                            "confidence": 0.5
                        }
                else:
                    error_text = await resp.text()
                    logger.error(f"❌ API ошибка: {resp.status} - {error_text[:200]}")
                    return {
                        "verdict": False,
                        "reason": f"API ошибка: {resp.status}",
                        "severity": 0,
                        "confidence": 0
                    }
    
    except Exception as e:
        logger.error(f"❌ Ошибка при анализе изображения: {e}")
        return {
            "verdict": False,
            "reason": f"Ошибка: {str(e)}",
            "severity": 0,
            "confidence": 0
        }

# ============================================================================
# ОСНОВНАЯ ФУНКЦИЯ АГЕНТА 6
# ============================================================================

async def process_media(media_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Обрабатывает медиа файл (фото/видео)
    """
    try:
        media_type = media_data.get("media_type", "unknown")
        local_path = media_data.get("local_path")
        username = media_data.get("username", "unknown")
        chat_id = media_data.get("chat_id", 0)
        user_id = media_data.get("user_id", 0)
        message_id = media_data.get("message_id", 0)
        caption = media_data.get("caption", "")
        message_link = media_data.get("message_link", "")
        
        logger.info(f"🔍 Анализирую {media_type}: {local_path}")
        
        verdict = False
        reason = "Контент в порядке"
        severity = 0
        confidence = 0
        
        # Анализируем фото
        if media_type == "photo" and local_path:
            analysis = await analyze_image_with_mistral(local_path)
            verdict = analysis.get("verdict", False)
            reason = analysis.get("reason", "Контент в порядке")
            severity = analysis.get("severity", 0)
            confidence = analysis.get("confidence", 0)
            
            if verdict:
                logger.warning(f"🚨 НАРУШЕНИЕ В ФОТО: severity={severity}, reason={reason}")
            else:
                logger.info(f"✅ Фото OK: {username}")
        
        # Видео - просто логируем (сложнее анализировать)
        elif media_type == "video":
            logger.info(f"📹 Видео получено: {local_path[:50]}")
            reason = "Видео получено и зарегистрировано"
            severity = 2  # Low priority
        
        # ✅ ВОЗВРАЩАЕМ РЕЗУЛЬТАТ В БОТ
        output = {
            "agent_id": 6,
            "media_type": media_type,
            "user_id": user_id,
            "username": username,
            "chat_id": chat_id,
            "message_id": message_id,
            "message_link": message_link,
            "caption": caption,
            "verdict": verdict,
            "action": "ban" if verdict else "none",
            "reason": reason,
            "severity": severity,
            "confidence": confidence,
            "is_violation": verdict,
            "timestamp": datetime.now().isoformat()
        }
        
        logger.info(f"📤 Выход готов: action={output.get('action')}, severity={severity}")
        
        return output
    
    except Exception as e:
        logger.error(f"❌ Ошибка обработки медиа: {e}")
        return {
            "agent_id": 6,
            "media_type": media_data.get("media_type", "unknown"),
            "user_id": media_data.get("user_id", 0),
            "username": media_data.get("username", "unknown"),
            "chat_id": media_data.get("chat_id", 0),
            "message_id": media_data.get("message_id", 0),
            "message_link": media_data.get("message_link", ""),
            "verdict": False,
            "action": "none",
            "reason": f"Ошибка: {str(e)}",
            "severity": 0,
            "confidence": 0,
            "is_violation": False,
            "timestamp": datetime.now().isoformat()
        }

# ============================================================================
# REDIS WORKER
# ============================================================================

class Agent6Worker:
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
        """Главный цикл обработки медиа"""
        logger.info("✅ Агент 6 запущен (Анализ медиа)")
        logger.info(f"📬 Слушаю очередь: {QUEUE_AGENT_6_INPUT}")
        logger.info(f"📤 Результаты в очередь: {QUEUE_AGENT_6_OUTPUT}")
        logger.info("⏱️ Нажмите Ctrl+C для остановки\n")
        
        try:
            while True:
                try:
                    result = self.redis_client.blpop(QUEUE_AGENT_6_INPUT, timeout=1)
                    
                    if result is None:
                        continue
                    
                    queue_name, message_data = result
                    logger.info("📨 Получено новое медиа")
                    
                    # Парсим JSON
                    try:
                        input_data = json.loads(message_data)
                    except json.JSONDecodeError as e:
                        logger.error(f"❌ Невалидный JSON: {e}")
                        continue
                    
                    logger.info(f"📄 Данные медиа: media_type={input_data.get('media_type')}")
                    
                    # Обрабатываем асинхронно
                    output = asyncio.run(process_media(input_data))
                    
                    # ✅ ПИШЕМ РЕЗУЛЬТАТ В REDIS для БОТа
                    try:
                        result_json = json.dumps(output, ensure_ascii=False)
                        
                        # ОЧЕРЕДЬ ДЛЯ БОТа
                        self.redis_client.rpush(QUEUE_AGENT_6_OUTPUT, result_json)
                        
                        logger.info(f"📤 ✅ Результат отправлен в БОТ: verdict={output.get('verdict')}, severity={output.get('severity')}")
                    except Exception as e:
                        logger.error(f"❌ Ошибка отправки результата в Redis: {e}")
                    
                    logger.info("✅ Обработка завершена\n")
                
                except Exception as e:
                    logger.error(f"❌ Ошибка в цикле: {e}")
                    time.sleep(1)
        
        except KeyboardInterrupt:
            logger.info("\n❌ Агент 6 остановлен (Ctrl+C)")
        finally:
            logger.info("Агент 6 завершил работу")

# ============================================================================
# ТОЧКА ВХОДА
# ============================================================================

if __name__ == "__main__":
    try:
        worker = Agent6Worker()
        worker.run()
    except KeyboardInterrupt:
        logger.info("Выход")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
