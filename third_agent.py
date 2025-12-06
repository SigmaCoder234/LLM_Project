#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🤖 АГЕНТ №3 — CONTEXTUAL ANALYZER (ИСПРАВЛЕННЫЙ)

✅ Получает сообщения от Агента 2
✅ Анализирует контекст (Mistral или FALLBACK)
✅ Пишет результаты в Redis
✅ НИКОГДА не падает - всегда есть fallback!
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
    QUEUE_AGENT_3_INPUT,
    QUEUE_AGENT_3_OUTPUT,
    MISTRAL_API_KEY,
    setup_logging,
)

# ============================================================================
# ЛОГИРОВАНИЕ
# ============================================================================

logger = setup_logging("АГЕНТ 3")

# ============================================================================
# MISTRAL API (С FALLBACK!)
# ============================================================================

MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"

async def analyze_with_mistral(message: str, violation_type: str = "unknown") -> Dict[str, Any]:
    """
    Анализирует сообщение с помощью Mistral
    ЕСЛИ НЕ РАБОТАЕТ - используется FALLBACK!
    """
    try:
        if not MISTRAL_API_KEY:
            logger.warning("⚠️ Mistral API Key не установлен, используется fallback")
            return use_fallback_analysis(message, violation_type)
        
        headers = {
            "Authorization": f"Bearer {MISTRAL_API_KEY}",
            "Content-Type": "application/json"
        }
        
        prompt = f"""Анализ сообщения Telegram:
"{message}"

Тип нарушения: {violation_type}

Определи:
1. severity (0-10)
2. confidence (0-1)
3. Действительно ли это нарушение? (yes/no)

Ответ JSON:
{{
  "is_violation": boolean,
  "severity": int,
  "confidence": float,
  "reasoning": "короткое объяснение"
}}"""
        
        payload = {
            "model": "mistral-large-latest",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 200
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                MISTRAL_API_URL, 
                json=payload, 
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    response_text = result["choices"][0]["message"]["content"]
                    
                    # Парсим JSON из ответа
                    json_start = response_text.find("{")
                    json_end = response_text.rfind("}") + 1
                    if json_start >= 0:
                        analysis = json.loads(response_text[json_start:json_end])
                        logger.info(f"✅ Mistral анализ: severity={analysis.get('severity', 0)}")
                        return analysis
                else:
                    logger.warning(f"⚠️ Mistral API ошибка: {resp.status}")
                    return use_fallback_analysis(message, violation_type)
    
    except Exception as e:
        logger.warning(f"⚠️ Ошибка Mistral: {e}, используется fallback")
        return use_fallback_analysis(message, violation_type)

def use_fallback_analysis(message: str, violation_type: str = "unknown") -> Dict[str, Any]:
    """
    FALLBACK анализ - когда Mistral недоступен
    Используется простая логика без API
    """
    logger.info("🔄 Использую FALLBACK анализ")
    
    # Простая эвристика
    if violation_type == "profanity":
        return {
            "is_violation": True,
            "severity": 5,
            "confidence": 0.6,
            "reasoning": "Fallback: матерные слова обнаружены"
        }
    elif violation_type == "insult":
        return {
            "is_violation": True,
            "severity": 4,
            "confidence": 0.6,
            "reasoning": "Fallback: оскорбления обнаружены"
        }
    elif violation_type == "discrimination":
        return {
            "is_violation": True,
            "severity": 8,
            "confidence": 0.7,
            "reasoning": "Fallback: дискриминация обнаружена"
        }
    else:
        return {
            "is_violation": False,
            "severity": 0,
            "confidence": 0.5,
            "reasoning": "Fallback: нарушений не обнаружено"
        }

# ============================================================================
# ОСНОВНАЯ ФУНКЦИЯ АГЕНТА 3
# ============================================================================

async def process_contextual_analysis(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Анализирует контекст сообщения
    """
    try:
        message = data.get("message", "")
        violation_type = data.get("violation_type", "unknown")
        severity_from_agent2 = data.get("severity", 0)
        confidence_from_agent2 = data.get("confidence", 0)
        
        logger.info(f"🔍 Анализирую сообщение: {message[:50]}")
        
        # Получаем анализ (Mistral или fallback)
        analysis = await analyze_with_mistral(message, violation_type)
        
        is_violation = analysis.get("is_violation", False)
        severity = analysis.get("severity", severity_from_agent2)
        confidence = analysis.get("confidence", confidence_from_agent2)
        
        # CRITICAL: Агент 3 пропускает слабые нарушения (severity < 3)
        if severity < 3:
            logger.info(f"✅ OK: severity={severity}/10, confidence={confidence:.1%}")
            return {
                "agent_id": 3,
                "status": "ok",
                "message": message,
                "severity": severity,
                "confidence": confidence,
                "skip_to_agent5": False  # НЕ отправляем в агента 5
            }
        else:
            logger.warning(f"⚠️ VIOLATION: severity={severity}/10, type={violation_type}")
            return {
                "agent_id": 3,
                "status": "violation",
                "message": message,
                "violation_type": violation_type,
                "severity": severity,
                "confidence": confidence,
                "skip_to_agent5": True  # ОТПРАВЛЯЕМ в агента 5
            }
    
    except Exception as e:
        logger.error(f"❌ Ошибка анализа: {e}")
        return {
            "agent_id": 3,
            "status": "error",
            "error": str(e),
            "skip_to_agent5": False
        }

# ============================================================================
# REDIS WORKER
# ============================================================================

class Agent3Worker:
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
        logger.info("✅ Агент 3 запущен (Contextual Analyzer)")
        logger.info(f"📬 Слушаю очередь: {QUEUE_AGENT_3_INPUT}")
        logger.info(f"📤 Результаты в очередь: {QUEUE_AGENT_3_OUTPUT}")
        logger.info(f"💡 Ждёшь только РЕАЛЬНЫЕ нарушения (severity >= 3)")
        logger.info("⏱️  Нажмите Ctrl+C для остановки\n")
        
        try:
            while True:
                try:
                    result = self.redis_client.blpop(QUEUE_AGENT_3_INPUT, timeout=1)
                    
                    if result is None:
                        continue
                    
                    queue_name, message_data = result
                    logger.info("📨 Получено новое сообщение")
                    
                    # Парсим JSON
                    try:
                        input_data = json.loads(message_data)
                    except json.JSONDecodeError as e:
                        logger.error(f"❌ Невалидный JSON: {e}")
                        continue
                    
                    # Обрабатываем асинхронно
                    output = asyncio.run(process_contextual_analysis(input_data))
                    
                    # ✅ ПИШЕМ РЕЗУЛЬТАТ В REDIS
                    try:
                        result_json = json.dumps(output, ensure_ascii=False)
                        self.redis_client.rpush(QUEUE_AGENT_3_OUTPUT, result_json)
                        
                        if output.get("skip_to_agent5"):
                            logger.info(f"📤 ✅ Результаты отправлены Агенту 5")
                        else:
                            logger.info(f"📤 ✅ OK результат (severity < 3)")
                    
                    except Exception as e:
                        logger.error(f"❌ Ошибка отправки результата в Redis: {e}")
                    
                    logger.info("✅ Анализ завершен\n")
                
                except Exception as e:
                    logger.error(f"❌ Ошибка в цикле: {e}")
                    time.sleep(1)
        
        except KeyboardInterrupt:
            logger.info("\n❌ Агент 3 остановлен (Ctrl+C)")
        finally:
            logger.info("Агент 3 завершил работу")

# ============================================================================
# ТОЧКА ВХОДА
# ============================================================================

if __name__ == "__main__":
    try:
        worker = Agent3Worker()
        worker.run()
    except KeyboardInterrupt:
        logger.info("Выход")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
