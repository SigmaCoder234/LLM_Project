#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
АГЕНТ №6 — Анализатор медиа контента с Mistral Vision
"""

import json
import base64
import requests
import redis
import time
from pathlib import Path
from typing import Dict, Any
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import threading
import logging

# Импорт конфигурации и БД
from config import (
    MISTRAL_API_KEY,
    MISTRAL_MODEL,
    MISTRAL_GENERATION_PARAMS,
    get_redis_config,
    MEDIA_DIR,
    POSTGRES_URL,
    AGENT_PORTS,
    setup_logging,
    TELEGRAM_BOT_TOKEN,
)

from sqlalchemy.orm import sessionmaker
from your_models import Chat, MediaFile, get_db_engine  # Импорт моделей и движка БД (адаптируй под свой проект)

logger = setup_logging("АГЕНТ 6")

engine = get_db_engine()
SessionLocal = sessionmaker(bind=engine)

# Инициализация Redis и Mistral
redis_client = redis.Redis(**get_redis_config())

try:
    from mistralai import Mistral, ChatMessage
    from mistralai import UserMessage, SystemMessage
    mistral_client = Mistral(api_key=MISTRAL_API_KEY)
    logger.info(f"✅ Mistral AI Vision клиент создан")
except Exception as e:
    logger.error(f"❌ Не удалось инициализировать Mistral Vision: {e}")
    mistral_client = None

def download_telegram_file(file_id: str, local_path: Path):
    """Скачивает файл из Telegram по file_id и сохраняет в local_path"""
    try:
        # Получаем путь файла
        resp = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile?file_id={file_id}"
        )
        resp.raise_for_status()
        file_path = resp.json()['result']['file_path']
        # Скачиваем файл напрямую
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
        file_resp = requests.get(file_url)
        file_resp.raise_for_status()
        with open(local_path, 'wb') as f:
            f.write(file_resp.content)
        logger.info(f"✅ Файл Telegram {file_id} сохранён в {local_path}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка скачивания файла {file_id}: {e}")
        return False

def analyze_media_with_mistral(local_path: str, media_type: str, caption: str = "") -> dict:
    """Анализирует медиа файл через Mistral Vision с передачей base64 изображения"""
    if mistral_client is None:
        logger.warning("⚠️ Mistral Vision не доступен")
        return {"is_suspicious": False, "reason": "Mistral Vision недоступен", "status": "error"}

    try:
        with open(local_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode()

        # Определяем mime type для передачи (пример)
        if media_type in ['photo', 'image']:
            mistral_media_type = "image/jpeg"
        elif media_type == 'video':
            mistral_media_type = "video/mp4"
        else:
            mistral_media_type = "application/octet-stream"

        system_message = f"Ты — модератор медиа контента в Telegram. Проанализируй данное {media_type} на нарушение правил."

        messages = [
            SystemMessage(content=system_message),
            UserMessage(content=[
                {"type": "text", "text": f"Описание: {caption}"},
                {"type": "image_url", "image_url": {"url": f"data:{mistral_media_type};base64,{image_data}"}}
            ]),
        ]

        response = mistral_client.chat.complete(
            model=MISTRAL_MODEL,
            messages=messages,
            temperature=MISTRAL_GENERATION_PARAMS.get("temperature", 0.1),
            max_tokens=MISTRAL_GENERATION_PARAMS.get("max_tokens", 300),
            top_p=MISTRAL_GENERATION_PARAMS.get("top_p", 0.9),
        )
        content = response.choices[0].message.content
        content_lower = content.lower()

        suspicion_score = 0
        if "подозрительность:" in content_lower:
            try:
                line = [l for l in content.split('\n') if 'подозрительность:' in l.lower()][0]
                suspicion_score = int(''.join(filter(str.isdigit, line))) if any(c.isdigit() for c in line) else 0
            except:
                suspicion_score = 0

        recommendation = "ALLOW"
        if "block" in content_lower:
            recommendation = "BLOCK"
        elif "review" in content_lower:
            recommendation = "REVIEW"

        is_suspicious = recommendation in ["BLOCK", "REVIEW"]
        confidence = 0.75
        if "уверенность:" in content_lower:
            try:
                line = [l for l in content.split('\n') if 'уверенность:' in l.lower()][0]
                confidence = int(''.join(filter(str.isdigit, line))) / 100.0 if any(c.isdigit() for c in line) else 0.75
            except:
                confidence = 0.75

        return {
            "suspicion_score": suspicion_score,
            "recommendation": recommendation,
            "is_suspicious": is_suspicious,
            "reason": content,
            "confidence": confidence,
            "ai_model": MISTRAL_MODEL,
            "status": "success"
        }

    except Exception as e:
        logger.error(f"❌ Ошибка анализа Mistral Vision: {e}")
        return {"is_suspicious": False, "reason": f"Ошибка анализа: {e}", "status": "error"}

def media_analysis_agent_6(input_data: Dict[str, Any], db_session):
    """Анализатор медиа контента"""
    media_type = input_data.get("media_type")
    file_id = input_data.get("file_id")
    user_id = input_data.get("user_id")
    username = input_data.get("username", "unknown")
    chat_id = input_data.get("chat_id")
    message_id = input_data.get("message_id")
    message_link = input_data.get("message_link", "")
    caption = input_data.get("caption", "")

    logger.info(f"🎬 Анализирую {media_type} от @{username} в чате {chat_id}")

    try:
        chat = db_session.query(Chat).filter_by(tg_chat_id=str(chat_id)).first()
        if not chat:
            chat = Chat(tg_chat_id=str(chat_id), title=f"Chat {chat_id}")
            db_session.add(chat)
            db_session.commit()
        
        media_dir = Path(MEDIA_DIR)
        media_dir.mkdir(parents=True, exist_ok=True)
        file_name = f"{file_id}_{media_type}"
        file_ext = ".jpg" if media_type == "photo" else ".mp4"  # пример расширения
        file_path = media_dir / (file_name + file_ext)

        # Скачиваем файл
        if not file_path.exists():
            success = download_telegram_file(file_id, file_path)
            if not success:
                raise RuntimeError(f"Не удалось скачать файл {file_id}")

        analysis = analyze_media_with_mistral(str(file_path), media_type, caption)

        media_obj = MediaFile(
            chat_id=chat.id,
            user_id=user_id,
            username=username,
            media_type=media_type,
            file_id=file_id,
            file_unique_id=input_data.get("file_unique_id"),
            file_name=input_data.get("file_name"),
            file_size=input_data.get("file_size"),
            mime_type=input_data.get("mime_type"),
            local_path=str(file_path),
            message_id=message_id,
            message_link=message_link,
            caption=caption,
            analysis_result=json.dumps(analysis, ensure_ascii=False),
            is_suspicious=analysis.get("is_suspicious", False),
            suspension_reason=analysis.get("reason", ""),
            agent_id=6,
            analyzed_at=datetime.utcnow()
        )
        db_session.add(media_obj)
        db_session.commit()

        logger.info(f"✅ {media_type.upper()} сохранён в БД, ID: {media_obj.id}")

        output = {
            "agent_id": 6,
            "action": "analyzed",
            "media_type": media_type,
            "file_id": file_id,
            "user_id": user_id,
            "username": username,
            "chat_id": chat_id,
            "message_id": message_id,
            "message_link": message_link,
            "media_id": media_obj.id,
            "is_suspicious": analysis.get("is_suspicious", False),
            "suspicion_score": analysis.get("suspicion_score", 0),
            "recommendation": analysis.get("recommendation", "ALLOW"),
            "analysis": analysis,
            "status": "success",
            "timestamp": datetime.now().isoformat(),
        }

        if analysis.get("is_suspicious"):
            logger.warning(f"⚠️ ПОДОЗРИТЕЛЬНЫЙ {media_type}: @{username} в чате {chat_id}")

        return output

    except Exception as e:
        logger.error(f"❌ Ошибка обработки {media_type}: {e}")
        return {"agent_id": 6, "action": "error", "reason": str(e), "status": "error"}

class Agent6Worker:
    def __init__(self):
        try:
            redis_config = get_redis_config()
            self.redis_client = redis.Redis(**redis_config)
            self.redis_client.ping()
            logger.info("✅ Подключение к Redis успешно")
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к Redis: {e}")
            raise

    def process_message(self, message_data, db_session):
        try:
            input_data = json.loads(message_data)
            result = media_analysis_agent_6(input_data, db_session)
            return result
        except json.JSONDecodeError as e:
            logger.error(f"❌ Ошибка парсинга JSON: {e}")
            return {"agent_id": 6, "action": "error", "reason": f"JSON error: {e}", "status": "json_error"}
        except Exception as e:
            logger.error(f"❌ Ошибка обработки: {e}")
            return {"agent_id": 6, "action": "error", "reason": str(e), "status": "error"}

    def run(self):
        logger.info("✅ Агент 6 запущен (Медиа анализатор с Mistral Vision)")
        logger.info(" Слушаю очередь: queue:agent6:input")
        db_session = None
        try:
            while True:
                try:
                    result = self.redis_client.blpop("queue:agent6:input", timeout=1)
                    if result is None:
                        continue
                    queue_name, message_data = result
                    logger.info("📨 Получено медиа")
                    db_session = SessionLocal()
                    output = self.process_message(message_data, db_session)
                    db_session.close()
                    logger.info("✅ Обработка завершена\n")
                except Exception as e:
                    logger.error(f"❌ Ошибка в цикле: {e}")
                    if db_session:
                        db_session.close()
                    time.sleep(1)
        except KeyboardInterrupt:
            logger.info("\n❌ Агент 6 остановлен (Ctrl+C)")
        finally:
            if db_session:
                db_session.close()

# Запуск FastAPI сервера идёт по необходимости (пример)
app = FastAPI(
    title="🎬 Агент №6 - Анализатор медиа (Mistral Vision)",
    description="Анализ фото, видео, гифок и документов",
    version="1.0"
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/health")
async def health_check():
    db_session = SessionLocal()
    try:
        total_media = db_session.query(MediaFile).count()
        suspicious_media = db_session.query(MediaFile).filter_by(is_suspicious=True).count()
    finally:
        db_session.close()
    return {
        "status": "online",
        "agent_id": 6,
        "name": "Агент №6 (Медиа анализатор)",
        "version": "1.0 (Mistral Vision)",
        "ai_provider": f"Mistral AI Vision ({MISTRAL_MODEL})" if mistral_client else "недоступен",
        "total_media_analyzed": total_media,
        "suspicious_media_found": suspicious_media,
        "redis_queue": "queue:agent6:input",
        "timestamp": datetime.now().isoformat(),
    }

def run_fastapi():
    uvicorn.run(app, host="localhost", port=AGENT_PORTS.get(6, 8006), log_level="info")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "api":
        run_fastapi()
    else:
        worker = Agent6Worker()
        worker.run()
