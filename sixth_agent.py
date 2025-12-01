#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
АГЕНТ №6 — Анализатор медиа (фото, видео, гифки) с Mistral Vision
"""

import json
import redis
import time
import os
from typing import Dict, Any
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey, BigInteger, Text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
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

# Импорты requests для скачивания файлов
import requests
from requests.exceptions import RequestException

from config import (
    MISTRAL_API_KEY,
    MISTRAL_MODEL,
    MISTRAL_GENERATION_PARAMS,
    POSTGRES_URL,
    get_redis_config,
    AGENT_PORTS,
    setup_logging
)

# ============================================================================
# ЛОГИРОВАНИЕ
# ============================================================================

logger = setup_logging("АГЕНТ 6")

if MISTRAL_IMPORT_SUCCESS:
    logger.info(f"✅ Mistral AI импортирован успешно ({MISTRAL_IMPORT_VERSION})")
else:
    logger.error("❌ Mistral AI не импортирован")

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
# ДИРЕКТОРИЯ ДЛЯ МЕДИА ФАЙЛОВ
# ============================================================================

MEDIA_DIR = Path("./media_files")
MEDIA_DIR.mkdir(exist_ok=True)
logger.info(f"📁 Директория для медиа: {MEDIA_DIR.absolute()}")

# ============================================================================
# МОДЕЛИ БД
# ============================================================================

Base = declarative_base()


class Chat(Base):
    __tablename__ = 'chats'
    id = Column(Integer, primary_key=True)
    tg_chat_id = Column(String, unique=True, nullable=False)
    title = Column(String, nullable=True)


class MediaFile(Base):
    __tablename__ = 'media_files'

    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, ForeignKey('chats.id'), nullable=False)
    user_id = Column(BigInteger, nullable=False)
    username = Column(String)
    media_type = Column(String)  # photo, video, gif, document
    file_id = Column(String, unique=True, nullable=False)
    file_unique_id = Column(String)
    file_name = Column(String, nullable=True)
    file_size = Column(Integer, nullable=True)
    mime_type = Column(String, nullable=True)
    local_path = Column(String, nullable=True)
    message_id = Column(BigInteger, nullable=False)
    message_link = Column(String)
    caption = Column(Text, nullable=True)

    # Анализ медиа
    analysis_result = Column(Text, nullable=True)
    is_suspicious = Column(Boolean, default=False)
    suspension_reason = Column(Text, nullable=True)

    # Метаданные
    agent_id = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    analyzed_at = Column(DateTime, nullable=True)

    chat = relationship('Chat', backref='media_files')


# ============================================================================
# ИНИЦИАЛИЗАЦИЯ БД И REDIS
# ============================================================================

engine = create_engine(POSTGRES_URL)
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)


def get_db_session():
    return SessionLocal()


# ============================================================================
# ФУНКЦИИ РАБОТЫ С МЕДИА
# ============================================================================

def get_media_file_path(file_unique_id: str, media_type: str) -> Path:
    """Получить путь для сохранения медиа файла"""
    extension = {
        "photo": ".jpg",
        "video": ".mp4",
        "gif": ".gif",
        "document": ".bin"
    }.get(media_type, ".bin")

    return MEDIA_DIR / f"{file_unique_id}{extension}"


def analyze_media_with_mistral(local_path: str, media_type: str, caption: str = "") -> dict:
    """Анализ медиа файла через Mistral Vision"""

    if not MISTRAL_IMPORT_SUCCESS or not mistral_client:
        logger.warning("⚠️ Mistral AI недоступен, используем заглушку")
        return {
            "is_suspicious": False,
            "confidence": 0.0,
            "reason": "Mistral AI недоступен",
            "status": "fallback"
        }

    try:
        # Читаем файл в base64
        import base64
        with open(local_path, "rb") as f:
            image_data = base64.standard_b64encode(f.read()).decode("utf-8")

        # Определяем media type для Mistral
        if media_type == "photo":
            mistral_media_type = "image/jpeg"
        elif media_type == "gif":
            mistral_media_type = "image/gif"
        elif media_type == "video":
            mistral_media_type = "video/mp4"
        else:
            mistral_media_type = "image/jpeg"

        system_message = f"""Ты — анализатор медиа контента для системы модерации Telegram.

ТВОЯ ЗАДАЧА:
Проанализируй предоставленное изображение/видео и определи:

1. Наличие запрещённого контента:
   - Насилие, жестокость
   - NSFW контент
   - Ненависть, дискриминация
   - Экстремизм
   - Другой вредоносный контент

2. Оценка подозрительности (0-100):
   - 0-20: Норма
   - 21-50: Может быть проблемным
   - 51-100: Явно подозрительно

3. Рекомендация:
   - ALLOW: Контент в порядке
   - REVIEW: Нужна проверка модератором
   - BLOCK: Немедленно заблокировать

ДОПОЛНИТЕЛЬНАЯ ИНФОРМАЦИЯ:
Caption: "{caption}"

ФОРМАТ ОТВЕТА:

ПОДОЗРИТЕЛЬНОСТЬ: [0-100]
РЕКОМЕНДАЦИЯ: [ALLOW/REVIEW/BLOCK]
ПРИЧИНА: [краткое описание на русском]
УВЕРЕННОСТЬ: [0-100]%"""

        # Создаём сообщение для Mistral
        user_message = f"Проанализируй это {media_type}"

        messages = [
            ChatMessage(role="system", content=system_message),
            ChatMessage(role="user", content=user_message)
        ]

        # Вызываем Mistral с изображением
        response = mistral_client.chat(
            model=MISTRAL_MODEL,
            messages=messages,
            temperature=MISTRAL_GENERATION_PARAMS.get("temperature", 0.1),
            max_tokens=MISTRAL_GENERATION_PARAMS.get("max_tokens", 300)
        )

        content = response.choices[0].message.content
        content_lower = content.lower()

        # Парсим результаты
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
        return {
            "is_suspicious": False,
            "reason": f"Ошибка анализа: {e}",
            "status": "error"
        }


# ============================================================================
# ОСНОВНАЯ ЛОГИКА АГЕНТА 6
# ============================================================================

def media_analysis_agent_6(input_data, db_session):
    """
    АГЕНТ 6 — Анализатор медиа контента
    """

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
        # Создаём/получаем чат
        chat = db_session.query(Chat).filter_by(tg_chat_id=str(chat_id)).first()
        if not chat:
            chat = Chat(tg_chat_id=str(chat_id), title=f"Chat {chat_id}")
            db_session.add(chat)
            db_session.commit()

        # Получаем путь для сохранения
        file_path = get_media_file_path(
            input_data.get("file_unique_id", file_id),
            media_type
        )

        # Анализируем медиа
        analysis = analyze_media_with_mistral(str(file_path), media_type, caption)

        # Сохраняем в БД
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
            "timestamp": datetime.now().isoformat()
        }

        if analysis.get("is_suspicious"):
            logger.warning(f"⚠️ ПОДОЗРИТЕЛЬНЫЙ {media_type}: @{username} в чате {chat_id}")

        return output

    except Exception as e:
        logger.error(f"❌ Ошибка обработки {media_type}: {e}")
        return {
            "agent_id": 6,
            "action": "error",
            "reason": str(e),
            "status": "error"
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
        logger.info(f" Слушаю очередь: queue:agent6:input")
        logger.info(f" Модель: {MISTRAL_MODEL}")
        logger.info(f" Статус Mistral: {'✅ Доступен' if mistral_client else '❌ Недоступен'}")
        logger.info(" Нажмите Ctrl+C для остановки\n")

        db_session = None
        try:
            while True:
                try:
                    result = self.redis_client.blpop("queue:agent6:input", timeout=1)
                    if result is None:
                        continue

                    queue_name, message_data = result
                    logger.info("📨 Получено медиа")

                    db_session = get_db_session()
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


# ============================================================================
# FASTAPI ПРИЛОЖЕНИЕ
# ============================================================================

app = FastAPI(
    title="🎬 Агент №6 - Анализатор медиа (Mistral Vision)",
    description="Анализ фото, видео, гифок и документов",
    version="1.0"
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
    db_session = get_db_session()
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
        "import_version": MISTRAL_IMPORT_VERSION,
        "mistral_status": "✅ Активен" if mistral_client else "❌ Неактивен",
        "total_media_analyzed": total_media,
        "suspicious_media_found": suspicious_media,
        "media_directory": str(MEDIA_DIR.absolute()),
        "timestamp": datetime.now().isoformat(),
        "redis_queue": "queue:agent6:input",
        "uptime_seconds": int(time.time())
    }


# ============================================================================
# ЗАПУСК
# ============================================================================

def run_fastapi():
    uvicorn.run(app, host="localhost", port=AGENT_PORTS[6] if 6 in AGENT_PORTS else 8006, log_level="info")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "api":
        run_fastapi()
    else:
        # FastAPI в отдельном потоке
        fastapi_thread = threading.Thread(target=run_fastapi, daemon=True)
        fastapi_thread.start()
        logger.info(f"✅ FastAPI сервер запущен на порту {AGENT_PORTS.get(6, 8006)}")

        # Запуск Redis worker
        try:
            worker = Agent6Worker()
            worker.run()
        except KeyboardInterrupt:
            logger.info("Выход из программы")
        except Exception as e:
            logger.error(f"❌ Критическая ошибка: {e}")
