#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
АГЕНТ №6 — АНАЛИЗ МЕДИА (Фото, видео через ffmpeg, и другое)

✅ ФУНКЦИОНАЛ:
- Анализирует фотографии через Mistral Vision API
- Поддерживает: PNG, JPG, GIF, WebP
- Для видео: извлекает кадр через ffmpeg → анализирует как фото
- Определяет нарушения в изображениях (порно, насилие, etc.)
- Severity для медиа: 0-10

📸 ПОДДЕРЖИВАЕМЫЕ ФОРМАТЫ:
✅ Фото: PNG, JPG, GIF, WebP, TIFF
✅ Видео (через ffmpeg): MP4, MKV, WebM, AVI (извлекается первый кадр)
❌ Аудио: MP3, WAV, OGG (нужна ручная обработка)

⚠️ ТРЕБОВАНИЯ:
- pip install requests pillow ffmpeg-python
- ffmpeg должен быть установлен на машину
"""

import json
import redis
import time
import asyncio
import requests
import base64
import os
import subprocess
from typing import Dict, Any, Optional, List
from datetime import datetime
from pathlib import Path
import logging

try:
    from mistralai import Mistral
    from mistralai import UserMessage, SystemMessage
    MISTRAL_IMPORT_SUCCESS = True
    MISTRAL_IMPORT_VERSION = "v1.0+ (новый SDK)"
except ImportError:
    try:
        from mistralai.client import MistralClient as Mistral
        def UserMessage(content): 
            return {"role": "user", "content": content}
        def SystemMessage(content): 
            return {"role": "system", "content": content}
        MISTRAL_IMPORT_SUCCESS = True
        MISTRAL_IMPORT_VERSION = "v0.4.2 (legacy)"
    except ImportError:
        MISTRAL_IMPORT_SUCCESS = False
        MISTRAL_IMPORT_VERSION = "none"

from config import (
    MISTRAL_API_KEY, MISTRAL_MODEL, MISTRAL_GENERATION_PARAMS,
    get_redis_config, QUEUE_AGENT_6_INPUT, QUEUE_AGENT_5_INPUT,
    setup_logging
)

logger = setup_logging("АГЕНТ 6")

if MISTRAL_IMPORT_SUCCESS:
    logger.info(f"✅ Mistral AI импортирован успешно ({MISTRAL_IMPORT_VERSION})")
    try:
        mistral_client = Mistral(api_key=MISTRAL_API_KEY)
        logger.info("✅ Mistral AI клиент для Vision создан")
    except Exception as e:
        logger.error(f"❌ Ошибка создания клиента: {e}")
        mistral_client = None
else:
    logger.error("❌ Mistral AI не импортирован")
    mistral_client = None

# ============================================================================
# РАБОТА С ВИДЕО (ffmpeg)
# ============================================================================

def extract_first_frame_from_video(video_path: str, output_path: str = None) -> Optional[str]:
    """
    Извлекает первый кадр из видео через ffmpeg
    
    Args:
        video_path: путь к видеофайлу
        output_path: путь где сохранить фрейм (по умолчанию /tmp)
    
    Returns:
        Путь к сохранённому изображению или None если ошибка
    """
    
    if not os.path.exists(video_path):
        logger.error(f"❌ Видеофайл не найден: {video_path}")
        return None
    
    try:
        import ffmpeg
        logger.info(f"🎬 Извлекаю первый кадр из видео: {video_path}")
        
        if output_path is None:
            output_path = f"/tmp/video_frame_{int(time.time())}.jpg"
        
        # Используем ffmpeg-python
        (
            ffmpeg
            .input(video_path)
            .filter('scale', 1280, -1)  # Масштабируем до 1280px ширина
            .output(output_path, vframes=1)  # Берём первый кадр
            .run(capture_stdout=True, capture_stderr=True)
        )
        
        if os.path.exists(output_path):
            logger.info(f"✅ Кадр успешно извлечён: {output_path}")
            return output_path
        
    except ImportError:
        logger.warning("⚠️ ffmpeg-python не установлен, пытаю subprocess")
        
        # Fallback: использую subprocess напрямую
        try:
            output_path = f"/tmp/video_frame_{int(time.time())}.jpg"
            cmd = [
                "ffmpeg",
                "-i", video_path,
                "-vframes", "1",
                "-vf", "scale=1280:-1",
                "-y",  # Перезаписать если существует
                output_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            
            if result.returncode == 0 and os.path.exists(output_path):
                logger.info(f"✅ Кадр успешно извлечён: {output_path}")
                return output_path
            else:
                logger.error(f"❌ Ошибка ffmpeg: {result.stderr.decode()}")
                return None
        
        except FileNotFoundError:
            logger.error("❌ ffmpeg не установлен на машину")
            logger.info("   Установи: apt-get install ffmpeg")
            return None
        except subprocess.TimeoutExpired:
            logger.error("❌ Timeout при извлечении кадра (видео слишком большое?)")
            return None
    
    except Exception as e:
        logger.error(f"❌ Ошибка при извлечении кадра: {e}")
        return None

# ============================================================================
# АНАЛИЗ ИЗОБРАЖЕНИЙ ЧЕРЕЗ MISTRAL VISION
# ============================================================================

def analyze_image_with_mistral(image_path: str) -> Dict[str, Any]:
    """
    Анализирует изображение через Mistral Vision API
    
    Args:
        image_path: путь к файлу изображения
    
    Returns:
        Результат анализа с severity, type, action
    """
    
    if not os.path.exists(image_path):
        logger.error(f"❌ Изображение не найдено: {image_path}")
        return {
            "severity": 0,
            "confidence": 0,
            "type": "unknown",
            "action": "none",
            "reason": "Файл не найден",
            "is_violation": False,
            "status": "error"
        }
    
    if not mistral_client:
        logger.error("❌ Mistral Vision недоступен")
        return {
            "severity": 0,
            "confidence": 0,
            "type": "unknown",
            "action": "none",
            "reason": "Mistral Vision недоступен",
            "is_violation": False,
            "status": "error"
        }
    
    try:
        # Читаем изображение и кодируем в base64
        with open(image_path, "rb") as f:
            image_data = base64.standard_b64encode(f.read()).decode("utf-8")
        
        # Определяем тип медиа
        file_ext = Path(image_path).suffix.lower()
        media_type_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".tiff": "image/tiff"
        }
        media_type = media_type_map.get(file_ext, "image/jpeg")
        
        logger.info(f"📸 Анализирую изображение: {image_path} ({media_type})")
        
        # Создаем сообщение с изображением
        system_prompt = """Ты — АНАЛИТИК ВИЗУАЛЬНОГО КОНТЕНТА для модерации Telegram.

ТВОЯ РОЛЬ: Анализировать изображения и определять нарушения.

🚫 ТИПЫ НАРУШЕНИЙ В ИЗОБРАЖЕНИЯХ:

1. ПОРНО (adult_content) — сексуальный, порнографический контент
2. НАСИЛИЕ (violence) — кровь, избиения, убийства, пытки
3. ЭКСТРЕМИЗМ (extremism) — символы нацизма, пропаганда
4. НЕНАВИСТЬ (hate) — оскорбительные символы, знаки
5. ЖЕСТОКОСТЬ (cruelty) — издевательство над животными
6. ОРУЖИЕ (weapons) — демонстрация оружия, взрывчатки
7. НАРКОТИКИ (drugs) — демонстрация наркотиков
8. МОШЕННИЧЕСТВО (fraud) — поддельные документы, QR коды
9. БЕЗ НАРУШЕНИЙ (none) — нормальное изображение

🔢 SEVERITY ШКАЛА:

0-2: БЕЗ НАРУШЕНИЙ
├─ Нормальные фото, природа, люди без нарушений

3-4: СЛАБОЕ НАРУШЕНИЕ
├─ Слегка оскорбительные изображения

5-6: СРЕДНЕЕ НАРУШЕНИЕ
├─ Явные нарушения, но не экстремальные

7-8: СЕРЬЁЗНОЕ НАРУШЕНИЕ
├─ Сильный контент (насилие, порно, экстремизм)

9-10: КРИТИЧНОЕ НАРУШЕНИЕ
├─ Экстремальный контент

ВЫДАЙ JSON:
{
  "analysis": "подробное описание что видишь",
  "type": "основной тип нарушения (одно из: adult_content, violence, extremism, hate, cruelty, weapons, drugs, fraud, none)",
  "severity": число_0_до_10,
  "confidence": число_0_до_100,
  "action": "none/warn/mute/ban",
  "explanation": "почему это нарушение",
  "is_violation": true_или_false,
  "visual_details": "то что видишь на фото"
}"""
        
        user_prompt = "Проанализируй это изображение на предмет нарушений правил модерации"
        
        # Используем Vision API
        if MISTRAL_IMPORT_VERSION.startswith("v1.0"):
            messages = [
                SystemMessage(content=system_prompt),
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{media_type};base64,{image_data}"
                            }
                        },
                        {
                            "type": "text",
                            "text": user_prompt
                        }
                    ]
                }
            ]
            
            response = mistral_client.chat.complete(
                model="mistral-vision-latest",
                messages=messages,
                temperature=0.3,
                max_tokens=500
            )
        else:
            # Legacy API
            return {
                "severity": 5,
                "confidence": 30,
                "type": "unknown",
                "action": "warn",
                "reason": "Vision API недоступна в legacy версии",
                "is_violation": False,
                "status": "unsupported"
            }
        
        content = response.choices[0].message.content
        logger.info(f"✅ Mistral Vision ответил: {content[:100]}")
        
        # Парсим JSON
        try:
            import json as json_module
            json_start = content.find('{')
            json_end = content.rfind('}') + 1
            
            if json_start != -1 and json_end > json_start:
                json_str = content[json_start:json_end]
                result = json_module.loads(json_str)
                
                result = {
                    "analysis": result.get("analysis", ""),
                    "type": result.get("type", "unknown"),
                    "severity": min(10, max(0, int(result.get("severity", 5)))),
                    "confidence": min(100, max(0, int(result.get("confidence", 50)))),
                    "action": result.get("action", "warn"),
                    "explanation": result.get("explanation", ""),
                    "is_violation": result.get("is_violation", False),
                    "visual_details": result.get("visual_details", ""),
                    "status": "success"
                }
                
                return result
        except Exception as e:
            logger.warning(f"⚠️ Ошибка парсинга Vision API: {e}")
        
        # Fallback при ошибке парсинга
        return {
            "severity": 5,
            "confidence": 30,
            "type": "unknown",
            "action": "warn",
            "reason": "Ошибка парсинга Vision API",
            "is_violation": False,
            "status": "parse_error"
        }
    
    except Exception as e:
        logger.error(f"❌ Ошибка анализа изображения: {e}")
        return {
            "severity": 0,
            "confidence": 0,
            "type": "unknown",
            "action": "none",
            "reason": f"Ошибка: {e}",
            "is_violation": False,
            "status": "error"
        }

# ============================================================================
# ОСНОВНАЯ ФУНКЦИЯ АГЕНТА 6
# ============================================================================

async def process_media(media_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Обрабатывает медиафайл (фото, видео)
    """
    
    try:
        media_path = media_data.get("media_path", "")
        media_type = media_data.get("media_type", "photo").lower()  # photo, video
        
        user_id = media_data.get("user_id", 0)
        username = media_data.get("username", "unknown")
        chat_id = media_data.get("chat_id", 0)
        message_id = media_data.get("message_id", 0)
        
        logger.info(f"🎬 Получено медиа от @{username}: {media_type}")
        
        # Проверяем существование файла
        if not os.path.exists(media_path):
            logger.error(f"❌ Файл не найден: {media_path}")
            return {
                "agent_id": 6,
                "status": "error",
                "error": "Файл не найден",
                "user_id": user_id,
                "username": username
            }
        
        # Если это видео - извлекаем кадр
        image_to_analyze = media_path
        if media_type == "video":
            frame_path = extract_first_frame_from_video(media_path)
            if frame_path is None:
                return {
                    "agent_id": 6,
                    "status": "error",
                    "error": "Не удалось извлечь кадр из видео",
                    "user_id": user_id,
                    "username": username
                }
            image_to_analyze = frame_path
        
        # Анализируем изображение
        analysis_result = analyze_image_with_mistral(image_to_analyze)
        
        # Очищаем временные файлы
        if media_type == "video" and image_to_analyze != media_path:
            try:
                os.remove(image_to_analyze)
                logger.info(f"🗑️ Удалён временный файл: {image_to_analyze}")
            except:
                pass
        
        # Формируем выход
        output = {
            "agent_id": 6,
            "media_type": media_type,
            "media_path": media_path,
            "user_id": user_id,
            "username": username,
            "chat_id": chat_id,
            "message_id": message_id,
            "analysis": analysis_result["analysis"],
            "type": analysis_result["type"],
            "severity": analysis_result["severity"],
            "confidence": analysis_result["confidence"],
            "action": analysis_result["action"],
            "explanation": analysis_result["explanation"],
            "is_violation": analysis_result["is_violation"],
            "visual_details": analysis_result.get("visual_details", ""),
            "status": analysis_result.get("status", "success"),
            "timestamp": datetime.now().isoformat()
        }
        
        if analysis_result["is_violation"]:
            logger.warning(
                f"⚠️ НАРУШЕНИЕ В МЕДИА: тип={analysis_result['type']}, "
                f"severity={analysis_result['severity']}/10, "
                f"action={analysis_result['action']}"
            )
        else:
            logger.info(f"✅ Медиа в порядке (severity={analysis_result['severity']})")
        
        return output
    
    except Exception as e:
        logger.error(f"❌ Ошибка обработки медиа: {e}")
        return {
            "agent_id": 6,
            "status": "error",
            "error": str(e),
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
        logger.info(f"📸 Формат: фото (PNG, JPG, GIF, WebP)")
        logger.info(f"🎬 Видео: MP4, MKV, WebM (через ffmpeg)")
        logger.info(f"🔔 Слушаю очередь: {QUEUE_AGENT_6_INPUT}")
        logger.info(" Нажмите Ctrl+C для остановки\n")
        
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
                    
                    # Обрабатываем асинхронно
                    output = asyncio.run(process_media(input_data))
                    
                    # Отправляем результат в Агента 5
                    try:
                        result_json = json.dumps(output, ensure_ascii=False)
                        self.redis_client.rpush(QUEUE_AGENT_5_INPUT, result_json)
                        logger.info("📤 Результаты отправлены Агенту 5")
                    except Exception as e:
                        logger.error(f"❌ Ошибка отправки результата: {e}")
                    
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
