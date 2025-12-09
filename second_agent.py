#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🤖 SECOND AGENT - ГЛАВНЫЙ MISTRAL АНАЛИЗЕР (v3.3 - С ДИАГНОСТИКОЙ)

✅ ИСПРАВЛЕНО: Добавлены проверки на импорты
✅ ИСПРАВЛЕНО: Старая логика Mistral (без legacy)
✅ ИСПРАВЛЕНО: Много диагностических логов
"""

import os
import json
import redis
import re
from datetime import datetime
from typing import Dict, Any

# ============================================================================
# ПРОВЕРКА ИМПОРТОВ С ДИАГНОСТИКОЙ
# ============================================================================

print("=" * 80)
print("🔍 ДИАГНОСТИКА АГЕНТА 2")
print("=" * 80)

# Проверка 1: mistralai
print("\n1️⃣ Проверка mistralai...")
try:
    from mistralai.client import MistralClient
    from mistralai.models.chat_message import ChatMessage
    print("   ✅ mistralai импортирован успешно")
except ImportError as e:
    print(f"   ❌ ОШИБКА: mistralai не найдена!")
    print(f"   📝 Деталь ошибки: {e}")
    print(f"\n   🔧 РЕШЕНИЕ:")
    print(f"   pip install mistralai")
    print(f"   или")
    print(f"   pip install mistralai==0.0.20")
    print("\n" + "=" * 80)
    exit(1)

# Проверка 2: redis
print("2️⃣ Проверка redis...")
try:
    import redis as redis_module
    print("   ✅ redis импортирован успешно")
except ImportError as e:
    print(f"   ❌ ОШИБКА: redis не найдена!")
    print(f"   🔧 РЕШЕНИЕ: pip install redis")
    exit(1)

# Проверка 3: config
print("3️⃣ Проверка config.py...")
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
    print("   ✅ config.py импортирован успешно")
except ImportError as e:
    print(f"   ❌ ОШИБКА: config.py не найден или неполный!")
    print(f"   📝 Деталь ошибки: {e}")
    print(f"   🔧 РЕШЕНИЕ: Проверьте config.py в папке проекта")
    print("\n" + "=" * 80)
    exit(1)

# Проверка 4: MISTRAL_API_KEY
print("4️⃣ Проверка MISTRAL_API_KEY...")
if not MISTRAL_API_KEY or MISTRAL_API_KEY == "your_mistral_key_here":
    print(f"   ❌ ОШИБКА: MISTRAL_API_KEY не установлен или пустой!")
    print(f"   🔧 РЕШЕНИЕ:")
    print(f"   • Откройте config.py")
    print(f"   • Установите MISTRAL_API_KEY = 'ваш_ключ_из_mistral.ai'")
    print(f"   • Или установите переменную окружения:")
    print(f"     export MISTRAL_API_KEY='ваш_ключ'")
    print("\n" + "=" * 80)
    exit(1)

api_key_masked = MISTRAL_API_KEY[:10] + "..." + MISTRAL_API_KEY[-5:]
print(f"   ✅ MISTRAL_API_KEY установлен: {api_key_masked}")

# Проверка 5: Redis подключение
print("5️⃣ Проверка Redis подключения...")
try:
    redis_config = get_redis_config()
    test_redis = redis.Redis(**redis_config)
    test_redis.ping()
    print(f"   ✅ Redis доступен: {redis_config['host']}:{redis_config['port']}")
except Exception as e:
    print(f"   ❌ ОШИБКА: Redis не доступен!")
    print(f"   📝 Деталь ошибки: {e}")
    print(f"   🔧 РЕШЕНИЕ:")
    print(f"   • Убедитесь что Redis запущен")
    print(f"   • redis-server (для запуска)")
    print(f"   • redis-cli ping (для проверки)")
    print("\n" + "=" * 80)
    exit(1)

# Проверка 6: Логирование
print("6️⃣ Проверка логирования...")
try:
    logger = setup_logging("АГЕНТ 2")
    print("   ✅ Логирование инициализировано")
except Exception as e:
    print(f"   ❌ ОШИБКА: Логирование не инициализировано!")
    print(f"   📝 Деталь ошибки: {e}")
    exit(1)

print("\n" + "=" * 80)
print("✅ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ УСПЕШНО!")
print("=" * 80 + "\n")

# Инициализация Redis
redis_client = redis.Redis(**get_redis_config())

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ MISTRAL (СТАРАЯ ЛОГИКА)
# ============================================================================

print("🚀 Инициализация Mistral API...")

try:
    # Старая логика - просто создаем клиент
    mistral_client = MistralClient(api_key=MISTRAL_API_KEY)
    logger.info("✅ Mistral AI клиент создан")
    print("✅ Mistral клиент успешно создан")
    
    # Пробуем первый запрос для проверки
    print("🧪 Тестовый запрос к Mistral...")
    test_response = mistral_client.chat(
        model="mistral-large-latest",
        messages=[ChatMessage(role="user", content="test")],
        max_tokens=10
    )
    logger.info("✅ Тестовый запрос прошел успешно")
    print("✅ Mistral API работает!")
    
except Exception as e:
    logger.error(f"❌ Ошибка инициализации Mistral: {e}")
    print(f"❌ ОШИБКА Mistral: {e}")
    print(f"\n🔧 ВОЗМОЖНЫЕ РЕШЕНИЯ:")
    print(f"1. Проверьте MISTRAL_API_KEY (откройте config.py)")
    print(f"2. Проверьте интернет соединение")
    print(f"3. Проверьте статус mistral.ai (может быть недоступен)")
    print(f"4. Переустановите mistralai: pip install --upgrade mistralai")
    print("\n" + "=" * 80)
    exit(1)

# ============================================================================
# ПАРСИНГ JSON - УЛУЧШЕННЫЙ
# ============================================================================

def extract_json_from_text(text: str) -> Dict[str, Any]:
    """Извлечь JSON из текста Mistral с fallback парсингом"""
    
    logger.debug(f"🔍 Попытка распарсить JSON из текста: {text[:100]}...")
    
    try:
        # Попытка 1: Найти JSON блок в тройных кавычках
        json_match = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1).strip()
            result = json.loads(json_str)
            logger.info("✅ JSON найден в блоке ```json```")
            return result
    except (json.JSONDecodeError, AttributeError) as e:
        logger.debug(f"⚠️  Попытка 1 не сработала: {e}")
    
    try:
        # Попытка 2: Прямой парсинг всего текста
        result = json.loads(text)
        logger.info("✅ JSON распарсен прямо (попытка 2)")
        return result
    except json.JSONDecodeError as e:
        logger.debug(f"⚠️  Попытка 2 не сработала: {e}")
    
    # Попытка 3: Найти JSON объект регулярным выражением
    try:
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            json_str = json_match.group(0)
            result = json.loads(json_str)
            logger.info("✅ JSON найден через regex (попытка 3)")
            return result
    except (json.JSONDecodeError, AttributeError) as e:
        logger.debug(f"⚠️  Попытка 3 не сработала: {e}")
    
    # Попытка 4: Fallback парсинг - вытащить значения из текста
    logger.warning(f"⚠️  4 попытки парсинга не сработали, использую fallback")
    logger.debug(f"📝 Текст для fallback: {text[:300]}")
    
    return parse_json_fallback(text)


def parse_json_fallback(text: str) -> Dict[str, Any]:
    """Fallback парсинг - извлечение значений из текста"""
    
    logger.info("🔍 Fallback парсинг: ищу значения в тексте")
    
    result = {
        "is_violation": False,
        "action": "none",
        "severity": 0,
        "confidence": 0,
        "reason": "Не удалось распарсить ответ Mistral, но текст проанализирован"
    }
    
    text_lower = text.lower()
    
    # Ищем is_violation
    if re.search(r'is_violation["\s:]*true', text, re.IGNORECASE):
        result["is_violation"] = True
        logger.info("✅ Fallback: is_violation = True")
    
    # Ищем action
    for action in ["ban", "mute", "warn"]:
        if f'"{action}"' in text_lower or f"action: {action}" in text_lower or f"action {action}" in text_lower:
            result["action"] = action
            logger.info(f"✅ Fallback: action = {action}")
            break
    
    # Ищем severity (число от 0 до 10)
    severity_match = re.search(r'severity["\s:]*(\d+)', text, re.IGNORECASE)
    if severity_match:
        severity = int(severity_match.group(1))
        result["severity"] = min(10, max(0, severity))
        logger.info(f"✅ Fallback: severity = {result['severity']}")
    
    # Ищем confidence (число от 0 до 100)
    confidence_match = re.search(r'confidence["\s:]*(\d+)', text, re.IGNORECASE)
    if confidence_match:
        confidence = int(confidence_match.group(1))
        result["confidence"] = min(100, max(0, confidence))
        logger.info(f"✅ Fallback: confidence = {result['confidence']}")
    
    # Ищем reason
    reason_match = re.search(r'reason["\s:]*["\']?([^"\'}\n]+)', text, re.IGNORECASE)
    if reason_match:
        result["reason"] = reason_match.group(1).strip()[:200]
        logger.info(f"✅ Fallback: reason = {result['reason'][:50]}")
    
    logger.info(f"✅ Fallback завершен: {result}")
    return result


# ============================================================================
# АНАЛИЗ С MISTRAL (СТАРАЯ ЛОГИКА)
# ============================================================================

def analyze_with_mistral(text: str) -> Dict[str, Any]:
    """Анализ сообщения с Mistral API (старая логика)"""
    
    system_prompt = """Ты модератор контента. Анализируй текст и ответь JSON в одной строке:
{"is_violation": true/false, "action": "none"/"warn"/"mute"/"ban", "severity": 0-10, "confidence": 0-100, "reason": "текст"}

Типы нарушений: оскорбления, мат, угрозы, спам.
Severity: 0-3 низко, 4-6 средне, 7-10 высоко.
Ответь ТОЛЬКО JSON."""

    try:
        logger.debug(f"🔄 Отправляю запрос Mistral для: {text[:40]}...")
        
        response = mistral_client.chat(
            model="mistral-large-latest",
            messages=[
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content=text)
            ],
            temperature=0.3,
            max_tokens=300
        )
        
        response_text = response.choices[0].message.content
        logger.debug(f"📥 Ответ от Mistral: {response_text[:200]}")
        
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
        
        logger.debug(f"✅ Финальный результат: is_violation={result['is_violation']}, "
                    f"action={result['action']}, severity={result['severity']}, "
                    f"confidence={result['confidence']}")
        
        return result
        
    except Exception as e:
        logger.error(f"❌ Ошибка при анализе: {e}")
        # Возвращаем безопасные значения
        return {
            "is_violation": False,
            "action": "none",
            "severity": 0,
            "confidence": 0,
            "reason": f"Ошибка при анализе: {str(e)[:50]}"
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
    
    logger.info(f"📨 Получено новое сообщение")
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
        logger.info("⏱️  Нажмите Ctrl+C для остановки\n")
        
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
                    logger.error(f"❌ Ошибка парсинга JSON из очереди: {e}")
                except Exception as e:
                    logger.error(f"❌ Ошибка обработки сообщения: {e}")
                    
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
        logger.info("=" * 80)
        logger.info("✅ Агент 2 ЗАПУЩЕН")
        logger.info("📊 Модель: mistral-large-latest")
        logger.info("=" * 80)
        
        worker = Agent2Worker()
        worker.run()
    except KeyboardInterrupt:
        logger.info("🛑 ОСТАНОВЛЕНО")
    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}")
        import traceback
        logger.error(traceback.format_exc())
        exit(1)
