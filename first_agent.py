#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
=============================================================================
ЧАТ-АГЕНТ №1 (исправленная версия) - Координатор и Нормализатор
=============================================================================
- Использует современный lifespan FastAPI
- Встроенная поддержка GIGACHAT_CREDENTIALS
- Исправлены все deprecation warnings
=============================================================================
"""

import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
import redis

# =========================
# Логирование
# =========================
Path("logs").mkdir(exist_ok=True)
logger.remove()
logger.add(
    "logs/agent_1_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="30 days",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} | {message}"
)
logger.add(lambda msg: print(msg, end=""), level="INFO", format="{time:HH:mm:ss} | {level} | {message}")


# =========================
# Конфигурация
# =========================
class Config:
    GIGACHAT_AUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    GIGACHAT_API_URL = "https://gigachat.devices.sberbank.ru/api/v1"

    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
    API_HOST = os.getenv("API_HOST", "0.0.0.0")
    API_PORT = int(os.getenv("API_PORT", "8001"))

    # Redis очереди/каналы
    QUEUE_TO_AGENT_2 = "queue:agent1_to_agent2"
    CHANNEL_STATUS_UPDATES = "channel:status_updates"
    CHANNEL_ERROR_NOTIFICATIONS = "channel:errors"
    CHANNEL_HEALTH_CHECKS = "channel:health_checks"

    # Лимиты GigaChat
    MAX_TOKENS_PER_REQUEST = 1024
    MAX_REQUESTS_PER_SECOND = 8
    TOKEN_REFRESH_MARGIN_MINUTES = 5

    # Дефолтный ключ GigaChat (можно переопределить через переменную окружения)
    DEFAULT_GIGACHAT_CREDENTIALS = "MDE5YTJhZjEtYjhjOS03OTViLWFlZjEtZTg4MTgxNjQzNzdjOmE0MzRhNjExLTE2NGYtNDdjYS1iNTM2LThlMGViMmU0YzVmNg=="


# =========================
# Простые структуры данных
# =========================
@dataclass
class TelegramMessage:
    message_id: int
    chat_id: int
    sender_id: int
    message_text: str
    timestamp: datetime


@dataclass
class ChatRules:
    max_message_length: Optional[int] = 4000
    forbidden_words: List[str] = field(default_factory=list)
    allowed_commands: List[str] = field(default_factory=list)
    moderation_enabled: bool = True
    spam_detection: bool = True
    auto_reply: bool = True


@dataclass
class ProcessedData:
    originalMessage: str
    processedPrompt: str
    responseText: str
    message_id: int
    chat_id: int
    sender_id: int
    timestamp: datetime
    normalized_text: str
    rules_applied: List[str] = field(default_factory=list)
    confidence_score: float = 0.8
    processing_time_ms: int = 0
    agent_chain: List[str] = field(default_factory=lambda: ["agent_1"])
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class AgentMessage:
    agent_id: str
    message_type: str
    timestamp: str
    correlation_id: str
    data: Dict[str, Any]
    target_agent: str = "agent_2"
    priority: int = 1


# =========================
# Валидаторы
# =========================
def validate_telegram_message(d: Dict[str, Any]) -> TelegramMessage:
    try:
        msg_id = int(d["message_id"])
        chat_id = int(d["chat_id"])
        sender_id = int(d["sender_id"])
        text = str(d["message_text"]).strip()
        if not text:
            raise ValueError("message_text is empty")
        ts_raw = d.get("timestamp")
        if isinstance(ts_raw, str):
            ts = datetime.fromisoformat(ts_raw.replace('Z', '+00:00'))
        elif isinstance(ts_raw, (int, float)):
            ts = datetime.fromtimestamp(ts_raw)
        elif isinstance(ts_raw, datetime):
            ts = ts_raw
        else:
            ts = datetime.now()
        return TelegramMessage(
            message_id=msg_id,
            chat_id=chat_id,
            sender_id=sender_id,
            message_text=text,
            timestamp=ts
        )
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"Missing field: {e}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid telegram_message: {e}")


def validate_chat_rules(d: Optional[Dict[str, Any]]) -> ChatRules:
    if not d:
        return ChatRules()
    try:
        max_len = d.get("max_message_length", 4000)
        max_len = int(max_len) if max_len is not None else None
        forbidden = [str(w).lower().strip() for w in d.get("forbidden_words", []) if str(w).strip()]
        allowed = []
        for cmd in d.get("allowed_commands", []):
            cmd = str(cmd).strip()
            if cmd and not cmd.startswith("/"):
                cmd = "/" + cmd
            if cmd:
                allowed.append(cmd)
        return ChatRules(
            max_message_length=max_len,
            forbidden_words=forbidden,
            allowed_commands=allowed,
            moderation_enabled=bool(d.get("moderation_enabled", True)),
            spam_detection=bool(d.get("spam_detection", True)),
            auto_reply=bool(d.get("auto_reply", True)),
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid chat_rules: {e}")


def validate_prompt(value: Optional[str]) -> str:
    p = (value or "").strip()
    return p if p else "Обработай сообщение согласно правилам чата"


# =========================
# GigaChat клиент
# =========================
class GigaChatClient:
    def __init__(self, credentials: str):
        self.credentials = credentials
        self.access_token: Optional[str] = None
        self.token_expires_at: Optional[datetime] = None
        self._request_count = 0
        self._last_request_time = 0.0
        logger.info("🔧 GigaChat клиент инициализирован")

    async def _ensure_rate_limit(self):
        now = time.time()
        min_interval = 1.0 / Config.MAX_REQUESTS_PER_SECOND
        delta = now - self._last_request_time
        if delta < min_interval:
            await asyncio.sleep(min_interval - delta)
        self._last_request_time = time.time()

    async def get_access_token(self) -> str:
        if (self.access_token and self.token_expires_at and
                datetime.now() + timedelta(minutes=Config.TOKEN_REFRESH_MARGIN_MINUTES) < self.token_expires_at):
            return self.access_token

        await self._ensure_rate_limit()

        payload = {'scope': 'GIGACHAT_API_PERS'}
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json',
            'RqUID': str(uuid.uuid4()),
            'Authorization': f'Basic {self.credentials}'
        }

        try:
            async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
                response = await client.post(Config.GIGACHAT_AUTH_URL, headers=headers, data=payload)
                logger.debug(f"🔑 GigaChat auth request: status={response.status_code}")
                response.raise_for_status()
                token_data = response.json()

                if 'access_token' not in token_data:
                    logger.error(f"❌ Отсутствует access_token в ответе: {token_data}")
                    raise ValueError("access_token not found in response")

                self.access_token = token_data['access_token']
                expires_in = token_data.get('expires_in', 1800)
                self.token_expires_at = datetime.now() + timedelta(seconds=expires_in - 60)

                logger.success(
                    f"🔑 Получен новый токен GigaChat (expires: {self.token_expires_at.strftime('%H:%M:%S')})")
                return self.access_token

        except httpx.HTTPStatusError as e:
            response_text = ""
            try:
                response_text = e.response.text
            except:
                pass
            logger.error(f"❌ HTTP ошибка получения токена GigaChat: {e.response.status_code} - {response_text}")
            raise
        except Exception as e:
            logger.error(f"❌ Ошибка получения токена GigaChat: {e}")
            raise

    async def chat_completion(self, messages: List[Dict[str, str]], model: str = "GigaChat") -> Dict[str, Any]:
        await self._ensure_rate_limit()
        token = await self.get_access_token()

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": Config.MAX_TOKENS_PER_REQUEST,
            "stream": False,
        }

        try:
            async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
                response = await client.post(f"{Config.GIGACHAT_API_URL}/chat/completions", headers=headers,
                                             json=payload)
                logger.debug(f"🧠 GigaChat completion request: status={response.status_code}")
                response.raise_for_status()
                result = response.json()
                self._request_count += 1
                logger.debug(f"✅ GigaChat запрос #{self._request_count} выполнен успешно")
                return result

        except httpx.HTTPStatusError as e:
            response_text = ""
            try:
                response_text = e.response.text
            except:
                pass
            logger.error(f"❌ HTTP ошибка GigaChat completion: {e.response.status_code} - {response_text}")
            raise
        except Exception as e:
            logger.error(f"❌ Ошибка GigaChat API: {e}")
            raise


# =========================
# Коммуникатор с агентами (Redis)
# =========================
class AgentCommunicator:
    def __init__(self, redis_url: str):
        try:
            self.redis_client = redis.from_url(redis_url, decode_responses=True)
            self.agent_id = "agent_1"
            logger.info(f"🔗 Коммуникатор подключен к Redis: {redis_url}")
        except Exception as e:
            logger.warning(f"⚠️ Не удалось подключиться к Redis: {e}")
            self.redis_client = None

    async def send_to_agent_2(self, processed_data: ProcessedData) -> bool:
        if not self.redis_client:
            logger.warning("⚠️ Redis недоступен, пропускаем отправку в Агент 2")
            return False

        try:
            agent_message = AgentMessage(
                agent_id=self.agent_id,
                message_type="process_request",
                timestamp=datetime.now().isoformat(),
                correlation_id=processed_data.correlation_id,
                data=asdict(processed_data),
                target_agent="agent_2",
                priority=1,
            )
            message_json = json.dumps(asdict(agent_message), ensure_ascii=False)
            result = await asyncio.to_thread(self.redis_client.lpush, Config.QUEUE_TO_AGENT_2, message_json)

            logger.success(
                f"📤 Отправлено Агенту 2 | msg_id={processed_data.message_id} | corr={processed_data.correlation_id[:8]}...")

            status_msg = {
                "agent_id": self.agent_id,
                "status": "message_sent_to_agent_2",
                "timestamp": datetime.now().isoformat(),
                "data": {"message_id": processed_data.message_id, "correlation_id": processed_data.correlation_id,
                         "queue_size": result},
            }
            await asyncio.to_thread(self.redis_client.publish, Config.CHANNEL_STATUS_UPDATES, json.dumps(status_msg))
            return True

        except Exception as e:
            logger.error(f"❌ Ошибка отправки Агенту 2: {e}")
            return False

    async def send_health_status(self, metrics: Dict[str, Any]) -> bool:
        if not self.redis_client:
            return False
        try:
            health_message = {
                "agent_id": self.agent_id,
                "status": "healthy",
                "metrics": metrics,
                "timestamp": datetime.now().isoformat(),
            }
            await asyncio.to_thread(self.redis_client.publish, Config.CHANNEL_HEALTH_CHECKS, json.dumps(health_message))
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка отправки health: {e}")
            return False


# =========================
# Основной Агент №1
# =========================
class ChatAgent1:
    def __init__(self, gigachat_credentials: str, redis_url: str):
        self.gigachat = GigaChatClient(gigachat_credentials)
        self.communicator = AgentCommunicator(redis_url)
        self.agent_id = "agent_1"
        self.start_time = datetime.now()
        self.processed_messages_count = 0
        self.error_count = 0
        logger.info("🚀 Чат-агент №1 инициализирован")

    async def normalize_message(self, text: str) -> str:
        if not text:
            return ""
        normalized = " ".join(text.split())
        if len(normalized) > 4000:
            normalized = normalized[:4000] + "..."
            logger.warning("✂️ Сообщение обрезано до 4000 символов")
        return normalized

    async def apply_chat_rules(self, message: str, rules: ChatRules) -> Tuple[str, List[str]]:
        applied: List[str] = []
        processed = message

        if not rules.moderation_enabled:
            return processed, applied

        lowered = processed.lower()
        for w in rules.forbidden_words:
            if w and w in lowered:
                processed = processed.replace(w, "*" * len(w))
                applied.append(f"filtered_word_{w}")

        if rules.max_message_length and len(processed) > rules.max_message_length:
            processed = processed[:rules.max_message_length] + "..."
            applied.append("length_limit")

        if processed.startswith("/"):
            cmd = processed.split()[0]
            if rules.allowed_commands and cmd not in rules.allowed_commands:
                applied.append("unauthorized_command")

        return processed, applied

    async def generate_response(self, message: str, prompt: str, rules: ChatRules) -> str:
        system_prompt = f"""
Ты - помощник модерации чата. Анализируй сообщения и давай краткие ответы.

Правила чата:
- Максимальная длина: {rules.max_message_length or 'не ограничено'}
- Модерация: {'включена' if rules.moderation_enabled else 'отключена'}
- Детекция спама: {'включена' if rules.spam_detection else 'отключена'}
- Запрещенные слова: {', '.join(rules.forbidden_words) if rules.forbidden_words else 'нет'}
- Разрешенные команды: {', '.join(rules.allowed_commands) if rules.allowed_commands else 'любые'}

Инструкции: {prompt}

Отвечай кратко и по делу. Не более 200 символов.
""".strip()

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ]

        try:
            response = await self.gigachat.chat_completion(messages)
            if response.get("choices") and len(response["choices"]) > 0:
                generated_text = response["choices"][0]["message"]["content"].strip()
                logger.success(f"✅ GigaChat сгенерировал ответ: {len(generated_text)} символов")
                return generated_text
            else:
                logger.warning("⚠️ GigaChat вернул пустой ответ")
                return "Не удалось сгенерировать ответ."
        except Exception as e:
            self.error_count += 1
            logger.error(f"❌ Ошибка генерации ответа: {e}")
            return "Произошла ошибка при генерации ответа."

    async def process_message(self, tmsg: TelegramMessage, prompt: str, rules: ChatRules) -> ProcessedData:
        start = time.time()
        corr = str(uuid.uuid4())

        try:
            normalized = await self.normalize_message(tmsg.message_text)
            processed_text, applied_rules = await self.apply_chat_rules(normalized, rules)
            response_text = await self.generate_response(processed_text, prompt, rules)
            processing_time_ms = int((time.time() - start) * 1000)

            pdata = ProcessedData(
                originalMessage=tmsg.message_text,
                processedPrompt=prompt,
                responseText=response_text,
                message_id=tmsg.message_id,
                chat_id=tmsg.chat_id,
                sender_id=tmsg.sender_id,
                timestamp=tmsg.timestamp,
                normalized_text=normalized,
                rules_applied=applied_rules,
                confidence_score=0.85 if not applied_rules else 0.75,
                processing_time_ms=processing_time_ms,
                agent_chain=["agent_1"],
                correlation_id=corr,
            )

            self.processed_messages_count += 1
            return pdata

        except Exception as e:
            self.error_count += 1
            processing_time_ms = int((time.time() - start) * 1000)
            logger.error(f"❌ Ошибка обработки сообщения: {e}")

            return ProcessedData(
                originalMessage=tmsg.message_text,
                processedPrompt=prompt,
                responseText="❌ Ошибка обработки сообщения.",
                message_id=tmsg.message_id,
                chat_id=tmsg.chat_id,
                sender_id=tmsg.sender_id,
                timestamp=tmsg.timestamp,
                normalized_text=tmsg.message_text,
                rules_applied=["error_occurred"],
                confidence_score=0.0,
                processing_time_ms=processing_time_ms,
                agent_chain=["agent_1"],
                correlation_id=corr,
            )

    async def process_and_forward(self, tmsg: TelegramMessage, prompt: str, rules: ChatRules) -> ProcessedData:
        pdata = await self.process_message(tmsg, prompt, rules)
        success = await self.communicator.send_to_agent_2(pdata)
        if success:
            logger.success(f"🎯 Сообщение {pdata.message_id} успешно передано Агенту 2")
        else:
            logger.error(f"❌ Не удалось передать сообщение {pdata.message_id} Агенту 2")
        return pdata

    def get_health_metrics(self) -> Dict[str, Any]:
        uptime = datetime.now() - self.start_time
        return {
            "agent_id": self.agent_id,
            "status": "healthy",
            "uptime_seconds": int(uptime.total_seconds()),
            "processed_messages": self.processed_messages_count,
            "error_count": self.error_count,
            "error_rate": self.error_count / max(self.processed_messages_count, 1),
            "gigachat_requests": getattr(self.gigachat, "_request_count", 0),
            "last_activity": datetime.now().isoformat(),
        }


# =========================
# Глобальная переменная агента
# =========================
agent: Optional[ChatAgent1] = None


# =========================
# Современный lifespan FastAPI
# =========================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global agent

    # Получаем credentials из переменной окружения или используем дефолтный
    creds = os.getenv("GIGACHAT_CREDENTIALS", Config.DEFAULT_GIGACHAT_CREDENTIALS)

    if not creds:
        logger.critical("❌ Не задан GIGACHAT_CREDENTIALS")
        raise RuntimeError("GIGACHAT_CREDENTIALS is required")

    logger.info(f"🔑 Используем GIGACHAT_CREDENTIALS: {creds[:20]}...")

    agent = ChatAgent1(creds, Config.REDIS_URL)

    # Отправляем начальный health status
    await agent.communicator.send_health_status(agent.get_health_metrics())
    logger.success("✅ Агент №1 запущен и готов к работе")

    yield

    # Shutdown
    if agent:
        metrics = agent.get_health_metrics()
        metrics["status"] = "shutting_down"
        await agent.communicator.send_health_status(metrics)
    logger.info("🛑 Агент №1 остановлен")


# =========================
# FastAPI приложение
# =========================
app = FastAPI(
    title="🤖 Чат-агент №1 (исправленная версия)",
    description="Агент №1: нормализация, правила, GigaChat, передача в Агент 2",
    version="2.2.0",
    lifespan=lifespan  # Современный способ
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


# -------------------------
# API endpoints
# -------------------------
@app.post("/process_message")
async def process_message_endpoint(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not agent:
        raise HTTPException(status_code=500, detail="Агент не инициализирован")

    try:
        telegram_message = validate_telegram_message(payload.get("telegram_message", {}))
        prompt = validate_prompt(payload.get("prompt"))
        chat_rules = validate_chat_rules(payload.get("chat_rules"))
        processed_data = await agent.process_and_forward(telegram_message, prompt, chat_rules)
        return asdict(processed_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка API /process_message: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/process_batch")
async def process_batch_endpoint(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not agent:
        raise HTTPException(status_code=500, detail="Агент не инициализирован")

    messages = payload.get("messages", [])
    if not isinstance(messages, list) or not messages:
        raise HTTPException(status_code=400, detail="messages must be a non-empty list")
    if len(messages) > 10:
        raise HTTPException(status_code=400, detail="Максимум 10 сообщений за раз")

    try:
        tasks = []
        for item in messages:
            telegram_message = validate_telegram_message(item.get("telegram_message", {}))
            prompt = validate_prompt(item.get("prompt"))
            chat_rules = validate_chat_rules(item.get("chat_rules"))
            tasks.append(agent.process_and_forward(telegram_message, prompt, chat_rules))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        output: List[Dict[str, Any]] = []
        for result in results:
            if isinstance(result, ProcessedData):
                output.append(asdict(result))
        return output

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка /process_batch: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    if not agent:
        return {"status": "error", "message": "Агент не инициализирован"}

    metrics = agent.get_health_metrics()

    # Проверка Redis
    try:
        if agent.communicator.redis_client:
            await asyncio.to_thread(agent.communicator.redis_client.ping)
            metrics["redis_status"] = "connected"
        else:
            metrics["redis_status"] = "not_configured"
    except Exception as e:
        metrics["redis_status"] = "disconnected"
        metrics["redis_error"] = str(e)

    # Проверка GigaChat
    try:
        if agent.gigachat.access_token and agent.gigachat.token_expires_at:
            time_left = agent.gigachat.token_expires_at - datetime.now()
            metrics["gigachat_token_expires_in_minutes"] = int(time_left.total_seconds() / 60)
            metrics["gigachat_token_status"] = "valid" if time_left.total_seconds() > 0 else "expired"
        else:
            metrics["gigachat_token_status"] = "not_obtained"
    except Exception as e:
        metrics["gigachat_token_status"] = "error"
        metrics["gigachat_error"] = str(e)

    metrics["api_status"] = "healthy"
    return metrics


@app.get("/metrics")
async def metrics():
    if not agent:
        raise HTTPException(status_code=500, detail="Агент не инициализирован")

    metrics = agent.get_health_metrics()

    try:
        if agent.communicator.redis_client:
            queue_size = await asyncio.to_thread(agent.communicator.redis_client.llen, Config.QUEUE_TO_AGENT_2)
            metrics["queue_to_agent_2_size"] = int(queue_size or 0)

        metrics["gigachat_token_valid"] = agent.gigachat.access_token is not None
        if agent.gigachat.token_expires_at:
            time_left = agent.gigachat.token_expires_at - datetime.now()
            metrics["gigachat_token_expires_in_minutes"] = int(time_left.total_seconds() / 60)

    except Exception as e:
        logger.warning(f"⚠️ Не удалось собрать дополнительные метрики: {e}")
        metrics["metrics_collection_error"] = str(e)

    return metrics


@app.get("/")
async def root():
    return {
        "service": "Чат-агент №1 (исправленная версия)",
        "version": "2.2.0",
        "status": "running",
        "features": [
            "🔧 Современный lifespan FastAPI",
            "🔑 Встроенный GIGACHAT_CREDENTIALS",
            "📊 Полный мониторинг и метрики",
            "🛡️ Расширенные правила модерации",
            "📨 Redis коммуникация с Агентом 2"
        ],
        "endpoints": {
            "process_message": "POST /process_message",
            "process_batch": "POST /process_batch",
            "health": "GET /health",
            "metrics": "GET /metrics",
        },
        "notes": [
            "Работает без Redis (с предупреждениями)",
            "GIGACHAT_CREDENTIALS встроен по умолчанию",
            "Все deprecation warnings исправлены"
        ]
    }


# =========================
# Точка входа
# =========================
if __name__ == "__main__":
    logger.info("🚀 Запуск Чат-агента №1 (исправленная версия)...")
    uvicorn.run(
        app,  # Прямая ссылка на app объект
        host=Config.API_HOST,
        port=Config.API_PORT,
        reload=False,
        access_log=True,
        log_level="info",
    )
