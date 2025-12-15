#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""

АГЕНТ №4 — МОДЕРАТОР НА ОСНОВЕ AI (DEEPSEEK)

================================================

Роль: Анализирует сообщения с помощью DeepSeek ИИ-модели
- Использует AI для определения нарушений правил (DEFAULT_RULES и другие)
- Возвращает оценку серьезности и рекомендуемое действие
- Заменяет старый алгоритм обнаружения плохих слов на интеллектуальный анализ

Схема: Берет данные сообщения → запрашивает анализ у DeepSeek → отправляет в Агента 5

"""

import json
import redis
import time
from typing import Dict, Any, List
from datetime import datetime
import requests

from config import (
    get_redis_config,
    QUEUE_AGENT_4_INPUT,
    QUEUE_AGENT_5_INPUT,
    DEFAULT_RULES,
    setup_logging,
    determine_action,
    DEEPSEEK_TOKEN,
)


logger = setup_logging("АГЕНТ 4")

# Конфигурация DeepSeek
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_API_KEY = DEEPSEEK_TOKEN  # Замените на реальный ключ


# ============================================================================

# СИСТЕМА ПРОМПТОВ ДЛЯ AI

# ============================================================================

def build_moderation_prompt(message: str, rules: str) -> str:
    """
    Строит промпт для DeepSeek для анализа нарушений правил
    """
    prompt = f"""Ты модератор контента. Проанализируй следующее сообщение на предмет нарушений правил сообщества.

ПРАВИЛА СООБЩЕСТВА:
{rules}

СООБЩЕНИЕ ДЛЯ АНАЛИЗА:
"{message}"

Дай ответ в формате JSON со следующей структурой:
{{
    "is_violation": true/false,
    "type": "спам|оскорбления|hate_speech|nsfw|мошенничество|none",
    "severity": число от 0 до 10,
    "confidence": число от 0 до 100,
    "action": "none|warn|mute|ban",
    "explanation": "краткое объяснение решения",
    "violated_rules": ["правило1", "правило2"]
}}

Будь точен и объективен. Вернул ТОЛЬКО JSON без дополнительного текста."""
    
    return prompt


# ============================================================================

# ВЫЗОВ DEEPSEEK API

# ============================================================================

def call_deepseek_api(message: str, rules: str) -> Dict[str, Any]:
    """
    Отправляет запрос к DeepSeek API и получает анализ сообщения
    """
    try:
        prompt = build_moderation_prompt(message, rules)
        
        payload = {
            "model": DEEPSEEK_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": "Ты помощник по модерации контента. Анализируй сообщения на основе правил и возвращай результаты в JSON формате."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.3,  # Низкая температура для более консистентных результатов
            "max_tokens": 500
        }
        
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        
        logger.info("🤖 Отправляю запрос к DeepSeek...")
        response = requests.post(DEEPSEEK_API_URL, json=payload, headers=headers, timeout=10)
        
        if response.status_code != 200:
            logger.error(f"❌ DeepSeek API ошибка: {response.status_code}")
            raise Exception(f"API error: {response.status_code}")
        
        response_data = response.json()
        ai_response = response_data["choices"][0]["message"]["content"]
        
        # Парсим JSON из ответа
        try:
            analysis = json.loads(ai_response)
            logger.info(f"✅ Получен анализ от DeepSeek: {analysis['type']}")
            return analysis
        except json.JSONDecodeError:
            logger.error(f"❌ Не удалось распарсить JSON из ответа DeepSeek: {ai_response}")
            raise Exception("Failed to parse AI response as JSON")
            
    except requests.exceptions.Timeout:
        logger.error("❌ Timeout при обращении к DeepSeek API")
        raise Exception("API timeout")
    except Exception as e:
        logger.error(f"❌ Ошибка при вызове DeepSeek: {e}")
        raise


# ============================================================================

# ПРИМЕНЕНИЕ АНАЛИЗА ИИ

# ============================================================================

def apply_ai_moderation(message: str, rules: str) -> Dict[str, Any]:
    """
    Применяет ИИ-модель DeepSeek для анализа нарушений правил.
    
    Заменяет старый алгоритм обнаружения плохих слов на интеллектуальный анализ.
    """
    try:
        # Вызываем DeepSeek API
        ai_analysis = call_deepseek_api(message, rules)
        
        # Извлекаем данные из анализа
        is_violation = ai_analysis.get("is_violation", False)
        violation_type = ai_analysis.get("type", "none")
        severity = ai_analysis.get("severity", 0)
        confidence = ai_analysis.get("confidence", 0)
        recommended_action = ai_analysis.get("action", "none")
        explanation = ai_analysis.get("explanation", "")
        violated_rules = ai_analysis.get("violated_rules", [])
        
        logger.info(
            f"🔍 ИИ анализ: тип={violation_type}, "
            f"серьезность={severity}/10, уверенность={confidence}%"
        )
        
        # Логика для уточнения действия на основе серьезности
        final_action = recommended_action
        
        # Усиливаем действие если серьезность очень высокая
        if severity >= 9 and final_action == "warn":
            final_action = "mute"
            logger.info(f"📈 Серьезность {severity}/10, усиливаем warn на mute")
        elif severity >= 9 and final_action == "mute":
            final_action = "ban"
            logger.info(f"📈 Серьезность {severity}/10, усиливаем mute на ban")
        
        # Определяем длительность для mute
        if final_action == "mute":
            if severity >= 8:
                final_duration = 1440  # 24 часа
            elif severity >= 6:
                final_duration = 360   # 6 часов
            else:
                final_duration = 120   # 2 часа
        else:
            final_duration = 0
        
        return {
            "agent4_action": final_action,
            "agent4_action_duration": final_duration,
            "agent4_reason": f"ИИ анализ: {explanation}",
            "agent4_confidence": min(confidence, 100),
            "agent4_violation_type": violation_type,
            "agent4_severity": severity,
            "agent4_violated_rules": violated_rules,
            "is_violation": is_violation
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка при ИИ анализе: {e}")
        # В случае ошибки API - возвращаем консервативный результат
        return {
            "agent4_action": "none",
            "agent4_action_duration": 0,
            "agent4_reason": f"Ошибка при анализе: {str(e)}",
            "agent4_confidence": 0,
            "agent4_violation_type": "none",
            "agent4_severity": 0,
            "agent4_violated_rules": [],
            "is_violation": False
        }


# ============================================================================

# ОСНОВНАЯ ФУНКЦИЯ АГЕНТА 4

# ============================================================================

def moderation_agent_4(message: str, user_id: int = None, username: str = "unknown",
                       chat_id: int = None, message_id: int = None, 
                       message_link: str = "") -> Dict[str, Any]:
    """
    АГЕНТ 4 — Модератор на основе DeepSeek ИИ
    
    Анализирует сообщение с использованием ИИ-модели
    """
    
    logger.info(f"📋 ИИ анализ от @{username}: '{message[:50]}...'")
    
    # Формируем правила в строковый формат
    rules_text = "\n".join([f"- {rule}" for rule in DEFAULT_RULES])
    
    # Применяем ИИ анализ
    ai_result = apply_ai_moderation(message, rules_text)
    
    # Формируем выход
    output = {
        "agent_id": 4,
        "agent_name": "ИИ модератор (DeepSeek)",
        "message": message,
        "user_id": user_id,
        "username": username,
        "chat_id": chat_id,
        "message_id": message_id,
        "message_link": message_link,
        
        # Результаты ИИ анализа
        "violation_type": ai_result["agent4_violation_type"],
        "severity": ai_result["agent4_severity"],
        "confidence": ai_result["agent4_confidence"],
        "violated_rules": ai_result["agent4_violated_rules"],
        "is_violation": ai_result["is_violation"],
        
        # Финальное решение
        "action": ai_result["agent4_action"],
        "action_duration": ai_result["agent4_action_duration"],
        "reason": ai_result["agent4_reason"],
        "moderation_style": "ai_based",
        "status": "success",
        "timestamp": datetime.now().isoformat()
    }
    
    logger.info(f"✅ ИИ решение: {ai_result['agent4_action']}")
    return output


# ============================================================================

# REDIS WORKER

# ============================================================================

class Agent4Worker:
    def __init__(self):
        try:
            redis_config = get_redis_config()
            self.redis_client = redis.Redis(**redis_config)
            self.redis_client.ping()
            logger.info("✅ Подключение к Redis успешно")
        except Exception as e:
            logger.error(f"❌ Не удалось подключиться к Redis: {e}")
            raise
    
    def process_message(self, message_data: str) -> Dict[str, Any]:
        """Обрабатывает данные о сообщении"""
        try:
            data = json.loads(message_data)
            
            # Извлекаем необходимые данные
            message = data.get("message", "")
            user_id = data.get("user_id")
            username = data.get("username", "unknown")
            chat_id = data.get("chat_id")
            message_id = data.get("message_id")
            message_link = data.get("message_link", "")
            
            # Вызываем основную функцию
            result = moderation_agent_4(
                message=message,
                user_id=user_id,
                username=username,
                chat_id=chat_id,
                message_id=message_id,
                message_link=message_link
            )
            
            return result
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Невалидный JSON: {e}")
            return {"agent_id": 4, "status": "json_error", "error": str(e)}
        except Exception as e:
            logger.error(f"❌ Ошибка обработки: {e}")
            return {"agent_id": 4, "status": "error", "error": str(e)}
    
    def send_result(self, result: Dict[str, Any]) -> bool:
        """Отправляет результат в Агента 5"""
        try:
            result_json = json.dumps(result, ensure_ascii=False)
            self.redis_client.rpush(QUEUE_AGENT_5_INPUT, result_json)
            logger.info("📤 Результат отправлен в Агента 5")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {e}")
            return False
    
    def run(self):
        """Главный цикл"""
        logger.info("✅ Агент 4 запущен (ИИ модератор DeepSeek)")
        logger.info(f" Слушаю очередь: {QUEUE_AGENT_4_INPUT}")
        logger.info(" Нажмите Ctrl+C для остановки\n")
        
        try:
            while True:
                try:
                    result = self.redis_client.blpop(QUEUE_AGENT_4_INPUT, timeout=1)
                    if result is None:
                        continue
                    
                    queue_name, message_data = result
                    logger.info("📨 Получено сообщение для анализа")
                    
                    output = self.process_message(message_data)
                    
                    if output.get("status") != "error":
                        self.send_result(output)
                    
                    logger.info("✅ ИИ анализ завершен\n")
                    
                except Exception as e:
                    logger.error(f"❌ Ошибка в цикле: {e}")
                    time.sleep(1)
                    
        except KeyboardInterrupt:
            logger.info("\n❌ Агент 4 остановлен (Ctrl+C)")


if __name__ == "__main__":
    try:
        worker = Agent4Worker()
        worker.run()
    except KeyboardInterrupt:
        logger.info("Выход")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")

