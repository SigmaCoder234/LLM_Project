#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🤖 SECOND AGENT - ГЛАВНЫЙ MISTRAL АНАЛИЗЕР (v3.2 - УЛУЧШЕННЫЙ ПАРСИНГ)

✅ ИСПРАВЛЕНО: Парсинг JSON от Mistral
✅ ИСПРАВЛЕНО: Fallback парсинг при ошибке
✅ ИСПРАВЛЕНО: Гарантированные значения severity, confidence
"""

import os
import json
import redis
import re
from datetime import datetime
from typing import Dict, Any

try:
    from mistralai.client import MistralClient
    from mistralai.models.chat_message import ChatMessage
except ImportError:
    print("❌ mistralai не установлена! pip install mistralai")
    exit(1)

try:
    from config import (
        MISTRAL_API_KEY,
        get_redis_config,
        QUEUE_AGENT_2_INPUT,
        QUEUE_AGENT_2_OUTPUT,
        QUEUE_AGENT_3_INPUT,
        QUEUE_AGENT_4_INPUT,
        setup_logging,
    )
except ImportError as e:
    print(f"❌ Ошибка импорта: {e}")
    exit(1)

logger = setup_logging("АГЕНТ 2")

# Инициализация Redis
redis_client = redis.Redis(**get_redis_config())

# Инициализация Mistral
try:
    mistral_client = MistralClient(api_key=MISTRAL_API_KEY)
    logger.info("✅ Mistral AI клиент создан")
    logger.info(f"📊 Модель: mistral-large-latest")
except Exception as e:
    logger.error(f"❌ Ошибка инициализации Mistral: {e}")
    exit(1)

# ============================================================================
# ПАРСИНГ JSON - УЛУЧШЕННЫЙ
# ============================================================================

def extract_json_from_text(text: str) -> Dict[str, Any]:
    """Извлечь JSON из текста Mistral с fallback парсингом"""
    
    try:
        # Попытка 1: Найти JSON блок в тройных кавычках
        json_match = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1).strip()
            result = json.loads(json_str)
            logger.info("✅ JSON найден в блоке ```json```")
            return result
    except (json.JSONDecodeError, AttributeError) as e:
        logger.debug(f"⚠️  Блок ```json``` не удалось распарсить: {e}")
    
    try:
        # Попытка 2: Прямой парсинг всего текста
        result = json.loads(text)
        logger.info("✅ JSON распарсен прямо")
        return result
    except json.JSONDecodeError as e:
        logger.debug(f"⚠️  Прямой парсинг не сработал: {e}")
    
    # Попытка 3: Найти JSON объект регулярным выражением
    try:
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            json_str = json_match.group(0)
            result = json.loads(json_str)
            logger.info("✅ JSON найден через regex")
            return result
    except (json.JSONDecodeError, AttributeError) as e:
        logger.debug(f"⚠️  Regex парсинг не сработал: {e}")
    
    # Попытка 4: Fallback парсинг - вытащить значения из текста
    logger.warning(f"⚠️  JSON парсинг полностью не сработал, использую fallback")
    logger.debug(f"📝 Текст для fallback: {text[:200]}")
    
    return parse_json_fallback(text)


def parse_json_fallback(text: str) -> Dict[str, Any]:
    """Fallback парсинг - извлечение значений из текста"""
    
    result = {
        "is_violation": False,
        "action": "none",
        "severity": 0,
        "confidence": 0,
        "reason": "Не удалось распарсить ответ Mistral"
    }
    
    text_lower = text.lower()
    
    # Ищем is_violation
    if re.search(r'is_violation["\s:]*true', text, re.IGNORECASE):
        result["is_violation"] = True
        logger.debug("✅ Fallback: is_violation = True")
    
    # Ищем action
    for action in ["ban", "mute", "warn"]:
        if f'"{action}"' in text_lower or f"action: {action}" in text_lower:
            result["action"] = action
            logger.debug(f"✅ Fallback: action = {action}")
            break
    
    # Ищем severity (число от 0 до 10)
    severity_match = re.search(r'severity["\s:]*(\d+)', text, re.IGNORECASE)
    if severity_match:
        severity = int(severity_match.group(1))
        result["severity"] = min(10, max(0, severity))
        logger.debug(f"✅ Fallback: severity = {result['severity']}")
    
    # Ищем confidence (число от 0 до 100)
    confidence_match = re.search(r'confidence["\s:]*(\d+)', text, re.IGNORECASE)
    if confidence_match:
        confidence = int(confidence_match.group(1))
        result["confidence"] = min(100, max(0, confidence))
        logger.debug(f"✅ Fallback: confidence = {result['confidence']}")
    
    # Ищем reason
    reason_match = re.search(r'reason["\s:]*["\']?([^"\'}\n]+)', text, re.IGNORECASE)
    if reason_match:
        result["reason"] = reason_match.group(1).strip()[:100]
        logger.debug(f"✅ Fallback: reason = {result['reason'][:50]}")
    
    return result


# ============================================================================
# АНАЛИЗ С MISTRAL
# ============================================================================

def analyze_with_mistral(text: str) -> Dict[str, Any]:
    """Анализ сообщения с Mistral API"""
    
    system_prompt = """Ты модератор контента. Анализируй текст и ответь JSON:
{
    "is_violation": bool (true если нарушение),
    "action": "none" | "warn" | "mute" | "ban",
    "severity": число от 0 до 10,
    "confidence": число от 0 до 100,
    "reason": "причина нарушения"
}

Тип нарушения: оскорбления, мат, угрозы, спам.
Severity: 0-3 низкое, 4-6 среднее, 7-10 высокое.
Ответь ТОЛЬКО JSON без доп текста."""

    try:
        logger.debug(f"🔄 Запрашиваю Mistral для текста: {text[:50]}...")
        
        response = mistral_client.chat(
            model="mistral-large-latest",
            messages=[
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content=text)
            ],
            temperature=0.3,
            max_tokens=500
        )
        
        response_text = response.choices[0].message.content
        logger.debug(f"📥 Ответ Mistral: {response_text[:200]}")
        
        # Парсим JSON
        result = extract_json_from_text(response_text)
        
        # ✅ Гарантируем правильные типы данных
        result["is_violation"] = bool(result.get("is_violation", False))
        result["action"] = str(result.get("action", "none")).lower()
        
        try:
            result["severity"] = int(result.get("severity", 0))
            result["severity"] = min(10, max(0, result["severity"]))
        except (ValueError, TypeError):
            result["severity"] = 0
        
        try:
            result["confidence"] = int(result.get("confidence", 0))
            result["confidence"] = min(100, max(0, result["confidence"]))
        except (ValueError, TypeError):
            result["confidence"] = 0
        
        result["reason"] = str(result.get("reason", "Неизвестно"))[:200]
        
        logger.debug(f"✅ Результат: is_violation={result['is_violation']}, "
                    f"action={result['action']}, severity={result['severity']}, "
                    f"confidence={result['confidence']}")
        
        return result
        
    except Exception as e:
        logger.error(f"❌ Ошибка Mistral: {e}")
        # Возвращаем безопасные значения
        return {
            "is_violation": False,
            "action": "none",
            "severity": 0,
            "confidence": 0,
            "reason": "Ошибка при анализе"
        }


# ============================================================================
# МОДЕРАЦИЯ
# ============================================================================

def moderation_agent_2(message_data: Dict[str, Any]) -> None:
    """Главная функция модерации текста"""
    
    text = message_data.get("message", "")
    username = message_data.get("username", "unknown")
    chat_id = message_data.get("chat_id")
    
    if not text:
        logger.warning("⚠️  Пустое сообщение")
        return
    
    logger.info(f"🔍 Анализирую сообщение от @{username}: '{text[:40]}'...")
    
    # Анализируем
    analysis = analyze_with_mistral(text)
    
    # ✅ ПРОВЕРКА: НЕ отправляем OK-сообщения дальше
    if not analysis.get("is_violation") and analysis.get("action") == "none":
        logger.info(f"✅ ОК: {analysis['confidence']}% уверенности")
        logger.info("✅ Сообщение OK - не отправляем дальше")
        logger.info("✅ Анализ завершен\n")
        return
    
    # Если нарушение - отправляем дальше
    logger.warning(f"⚠️  НАРУШЕНИЕ: action={analysis['action']}, severity={analysis['severity']}/10")
    
    # Подготавливаем результат
    result = {
        "message": text,
        "username": username,
        "user_id": message_data.get("user_id"),
        "chat_id": chat_id,
        "message_id": message_data.get("message_id"),
        "is_violation": analysis["is_violation"],
        "action": analysis["action"],
        "severity": analysis["severity"],
        "confidence": analysis["confidence"],
        "reason": analysis["reason"],
        "timestamp": datetime.now().isoformat(),
        "message_link": message_data.get("message_link", ""),
        "media_type": ""
    }
    
    result_json = json.dumps(result, ensure_ascii=False)
    
    # Отправляем Агентам 3, 4, 5
    redis_client.rpush(QUEUE_AGENT_3_INPUT, result_json)
    redis_client.rpush(QUEUE_AGENT_4_INPUT, result_json)
    
    logger.info(f"📤 Отправлено Агентам 3, 4")
    logger.info("✅ Анализ завершен\n")


# ============================================================================
# ГЛАВНЫЙ РАБОЧИЙ ЦИКЛ
# ============================================================================

class Agent2Worker:
    def __init__(self):
        self.redis_client = redis_client
    
    def run(self):
        """Главный цикл обработки"""
        logger.info("📥 Импорт: v0.4.2 (legacy)")
        logger.info(f"🔔 Слушаю очередь: {QUEUE_AGENT_2_INPUT}")
        logger.info("⏱️ Нажмите Ctrl+C для остановки\n")
        
        while True:
            try:
                # Читаем из очереди
                result = self.redis_client.blpop(QUEUE_AGENT_2_INPUT, timeout=1)
                
                if not result:
                    continue
                
                _, data = result
                
                try:
                    message_data = json.loads(data)
                    moderation_agent_2(message_data)
                except json.JSONDecodeError as e:
                    logger.error(f"❌ Ошибка парсинга JSON: {e}")
                except Exception as e:
                    logger.error(f"❌ Ошибка обработки: {e}")
                    
            except KeyboardInterrupt:
                logger.info("🛑 Агент 2 остановлен")
                break
            except Exception as e:
                logger.error(f"❌ Ошибка в цикле: {e}")
                import time
                time.sleep(1)


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    try:
        logger.info("✅ Агент 2 ЗАПУЩЕН")
        worker = Agent2Worker()
        worker.run()
    except KeyboardInterrupt:
        logger.info("🛑 ОСТАНОВЛЕНО")
    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}")
        exit(1)
