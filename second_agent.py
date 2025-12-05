#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
АГЕНТ №2 — КЛЮЧЕВОЙ АНАЛИТИК (Mistral AI) - ПОЛНОСТЬЮ ИСПРАВЛЕННАЯ ВЕРСИЯ
============================================================================
✅ ИСПРАВЛЕНО: 'dict' object has no attribute 'model_dump'

- Анализирует сообщение глубоко (контекст, семантика, скрытые смыслы)
- Выдает ЕДИНСТВЕННЫЙ вывод для всех остальных агентов
- Использует Mistral AI с оптимальными параметрами
- ИСПРАВЛЕНО: Правильный парсинг SDK (БЕЗ model_dump)
- Выдает JSON структурированный результат
"""

import json
import redis
import time
from typing import Dict, Any, List
from datetime import datetime

# Mistral AI импорты (с обработкой обеих версий SDK)
try:
    from mistralai import Mistral
    from mistralai import UserMessage, SystemMessage
    MISTRAL_IMPORT_SUCCESS = True
    MISTRAL_IMPORT_VERSION = "v1.0+ (новый SDK)"
except ImportError:
    try:
        from mistralai.client import MistralClient as Mistral
        from mistralai.models.chat_completion import ChatMessage
        def UserMessage(content): 
            return {"role": "user", "content": content}
        def SystemMessage(content): 
            return {"role": "system", "content": content}
        MISTRAL_IMPORT_SUCCESS = True
        MISTRAL_IMPORT_VERSION = "v0.4.2 (legacy)"
    except ImportError:
        print("❌ Не удалось импортировать Mistral AI")
        MISTRAL_IMPORT_SUCCESS = False
        MISTRAL_IMPORT_VERSION = "none"
        class Mistral:
            def __init__(self, api_key): 
                pass
            def chat(self, **kwargs):
                raise ImportError("Mistral AI не установлен")

# Импортируем конфигурацию
from config import (
    MISTRAL_API_KEY,
    MISTRAL_MODEL,
    get_redis_config,
    QUEUE_AGENT_2_INPUT,
    QUEUE_AGENT_2_OUTPUT,
    QUEUE_AGENT_3_INPUT,
    QUEUE_AGENT_4_INPUT,
    DEFAULT_RULES,
    setup_logging,
)

# ============================================================================
# ЛОГИРОВАНИЕ
# ============================================================================

logger = setup_logging("АГЕНТ 2")

if MISTRAL_IMPORT_SUCCESS:
    logger.info(f"✅ Mistral AI импортирован успешно ({MISTRAL_IMPORT_VERSION})")
else:
    logger.error("❌ Mistral AI не импортирован")

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ MISTRAL AI
# ============================================================================

if MISTRAL_IMPORT_SUCCESS and MISTRAL_API_KEY and MISTRAL_API_KEY != "your_mistral_key_here":
    try:
        mistral_client = Mistral(api_key=MISTRAL_API_KEY)
        logger.info("✅ Mistral AI клиент создан")
    except Exception as e:
        logger.error(f"❌ Ошибка создания Mistral AI клиента: {e}")
        mistral_client = None
else:
    mistral_client = None
    logger.warning("⚠️ Mistral AI клиент не создан")

# ============================================================================
# ГЛАВНЫЙ АНАЛИЗ MISTRAL AI (ОСНОВНАЯ ФУНКЦИЯ) - ПОЛНОСТЬЮ ИСПРАВЛЕНО
# ============================================================================

def analyze_with_mistral(message: str, rules: List[str]) -> Dict[str, Any]:
    """
    ГЛАВНЫЙ АНАЛИТИК - глубокий анализ сообщения через Mistral AI
    
    ✅ ПОЛНОСТЬЮ ИСПРАВЛЕНО: 
    - Правильное обращение к SDK ответу (БЕЗ model_dump())
    - Используем response.choices[0].message.content
    """

    if not MISTRAL_IMPORT_SUCCESS or not mistral_client:
        logger.warning("⚠️ Mistral AI недоступен, используем заглушку")
        return {
            "analysis": "Mistral AI недоступен",
            "type": "unknown",
            "severity": 0,
            "confidence": 0,
            "action": "none",
            "explanation": "API недоступен",
            "is_violation": False,
            "context_analysis": "",
            "status": "fallback"
        }

    try:
        if not rules:
            rules = DEFAULT_RULES
        
        rules_text = "\n".join([f"{i+1}. {rule}" for i, rule in enumerate(rules)])

        # ✅ УЛУЧШЕННЫЙ ПРОМПТ С ПРИМЕРАМИ И КОНТЕКСТОМ
        system_message = f"""Ты — ГЛАВНЫЙ АНАЛИТИК системы модерации Telegram.

ТВОЯ РОЛЬ: Дать МАКСИМАЛЬНО ТОЧНЫЙ анализ сообщения.

ПРАВИЛА ЧАТА:
{rules_text}

ТИПЫ НАРУШЕНИЙ:
1. мат (нецензурная лексика)
2. оскорбление (личные оскорбления, унижение)
3. спам (реклама, ссылки, сообщения для привлечения)
4. дискриминация (по расе, национальности, религии, полу)
5. угроза (угрозы насилия, убийства, избиения)
6. порно (сексуальный контент)
7. флуд (повторяющиеся сообщения, капс)
8. нет (нормальное сообщение)

ПРИМЕРЫ АНАЛИЗА:

✅ Пример 1: "Хуй"
- Анализ: одно матерное слово
- Тип: мат
- Серьезность: 7/10
- Уверенность: 99%
- Действие: mute
- Объяснение: Нецензурная лексика, прямое нарушение

✅ Пример 2: "Ты сын шлюхи"
- Анализ: прямое оскорбление с матом
- Тип: оскорбление
- Серьезность: 9/10
- Уверенность: 99%
- Действие: ban
- Объяснение: Прямое оскорбление + нецензурная лексика

✅ Пример 3: "Я твою мать ебал"
- Анализ: сексуальный контент + оскорбление семьи
- Тип: оскорбление
- Серьезность: 10/10
- Уверенность: 99%
- Действие: ban
- Объяснение: Экстремально грубое оскорбление семьи

✅ Пример 4: "Блять, как это работает?"
- Анализ: мат в контексте удивления
- Тип: мат
- Серьезность: 4/10
- Уверенность: 90%
- Действие: warn
- Объяснение: Нецензурная лексика, но без агрессии

✅ Пример 5: "Все евреи воры"
- Анализ: генерализованное оскорбление этнической группы
- Тип: дискриминация
- Серьезность: 9/10
- Уверенность: 98%
- Действие: ban
- Объяснение: Расовая дискриминация

✅ Пример 6: "Привет всем, как дела?"
- Анализ: нормальное приветствие
- Тип: нет
- Серьезность: 0/10
- Уверенность: 100%
- Действие: none
- Объяснение: Нормальное сообщение

ВАЖНО:
- Не пропускай матерные слова в любом контексте
- Если уверенность < 50% - пиши честно об этом
- Если сомневаешься - выбери более серьезный тип
- Будь ОБЪЕКТИВНЫМ

ВЫДАЙ РЕЗУЛЬТАТ ТОЛЬКО В ФОРМАТЕ JSON (без доп. текста):

{{
  "analysis": "подробное описание",
  "type": "основной тип (мат/оскорбление/спам/дискриминация/угроза/порно/флуд/нет)",
  "severity": число_0_до_10,
  "confidence": число_0_до_100,
  "action": "none/warn/mute/ban",
  "explanation": "почему это нарушение",
  "is_violation": true_или_false,
  "context_analysis": "анализ контекста"
}}"""

        user_message_text = f'Сообщение для анализа: "{message}"'

        # Создаем сообщения
        if MISTRAL_IMPORT_VERSION.startswith("v1.0"):
            messages = [
                SystemMessage(content=system_message),
                UserMessage(content=user_message_text)
            ]
        else:
            messages = [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message_text}
            ]

        # ✅ ИСПРАВЛЕНО: Правильный вызов API и получение ответа
        if MISTRAL_IMPORT_VERSION.startswith("v1.0"):
            response = mistral_client.chat.complete(
                model=MISTRAL_MODEL,
                messages=messages,
                temperature=0.3,
                max_tokens=600,
                top_p=0.95
            )
        else:
            response = mistral_client.chat(
                model=MISTRAL_MODEL,
                messages=messages,
                temperature=0.3,
                max_tokens=600,
                top_p=0.95
            )

        # ✅✅✅ ИСПРАВЛЕНО: БЕЗ model_dump()!
        # Используем правильный способ получения контента
        content = response.choices[0].message.content

        # ✅ УЛУЧШЕННЫЙ ПАРСИНГ JSON
        try:
            # Пытаемся найти JSON в ответе
            json_start = content.find('{')
            json_end = content.rfind('}') + 1

            if json_start != -1 and json_end > json_start:
                json_str = content[json_start:json_end]
                result = json.loads(json_str)

                # Валидируем и нормализуем результат
                result = {
                    "analysis": result.get("analysis", ""),
                    "type": result.get("type", "unknown"),
                    "severity": min(10, max(0, int(result.get("severity", 0)))),
                    "confidence": min(100, max(0, int(result.get("confidence", 0)))),
                    "action": result.get("action", "none"),
                    "explanation": result.get("explanation", ""),
                    "is_violation": result.get("is_violation", False),
                    "context_analysis": result.get("context_analysis", ""),
                    "status": "success"
                }

                return result
            else:
                raise ValueError("JSON не найден в ответе")

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"⚠️ Ошибка парсинга JSON: {e}")
            logger.warning(f"Ответ был: {content[:200]}")
            
            # Возвращаем fallback результат
            return {
                "analysis": content[:500],
                "type": "unknown",
                "severity": 5,
                "confidence": 30,
                "action": "warn",
                "explanation": "Ошибка парсинга ответа Mistral",
                "is_violation": False,
                "context_analysis": "",
                "status": "parse_error"
            }

    except Exception as e:
        logger.error(f"❌ Ошибка анализа Mistral: {e}")
        import traceback
        traceback.print_exc()
        return {
            "analysis": str(e),
            "type": "unknown",
            "severity": 0,
            "confidence": 0,
            "action": "none",
            "explanation": f"Ошибка Mistral: {e}",
            "is_violation": False,
            "context_analysis": "",
            "status": "error"
        }

# ============================================================================
# ОСНОВНАЯ ФУНКЦИЯ АГЕНТА 2
# ============================================================================

def moderation_agent_2(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    АГЕНТ 2 — Главный аналитик (Mistral AI)
    Получает текст сообщения и дает полный анализ.
    """

    message = input_data.get("message", "")
    rules = input_data.get("rules", [])
    user_id = input_data.get("user_id")
    username = input_data.get("username", "unknown")
    chat_id = input_data.get("chat_id")
    message_id = input_data.get("message_id")
    message_link = input_data.get("message_link", "")

    logger.info(f"🔍 Анализирую сообщение от @{username}: '{message[:50]}...'")

    if not message or not message.strip():
        return {
            "agent_id": 2,
            "status": "error",
            "message": "",
            "analysis": "Пустое сообщение"
        }

    if not rules:
        rules = DEFAULT_RULES

    # ГЛАВНЫЙ АНАЛИЗ
    analysis_result = analyze_with_mistral(message, rules)

    # Формируем выход
    output = {
        "agent_id": 2,
        "message": message,
        "user_id": user_id,
        "username": username,
        "chat_id": chat_id,
        "message_id": message_id,
        "message_link": message_link,
        "rules": rules,
        # ✅ ОСНОВНОЙ АНАЛИЗ
        "analysis": analysis_result["analysis"],
        "type": analysis_result["type"],
        "severity": analysis_result["severity"],
        "confidence": analysis_result["confidence"],
        "action": analysis_result["action"],
        "explanation": analysis_result["explanation"],
        "is_violation": analysis_result["is_violation"],
        "context_analysis": analysis_result["context_analysis"],
        "status": analysis_result.get("status", "success"),
        "ai_model": MISTRAL_MODEL,
        "timestamp": datetime.now().isoformat()
    }

    # Логирование результата
    if analysis_result["is_violation"]:
        logger.warning(
            f"⚠️ НАРУШЕНИЕ: тип={analysis_result['type']}, "
            f"серьезность={analysis_result['severity']}/10, "
            f"уверенность={analysis_result['confidence']}%, "
            f"действие={analysis_result['action']}"
        )
    else:
        logger.info(f"✅ ОК: {analysis_result['confidence']}% уверенности")

    return output

# ============================================================================
# REDIS WORKER
# ============================================================================

class Agent2Worker:
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
        """Обрабатывает сообщение из входной очереди"""
        try:
            input_data = json.loads(message_data)
            result = moderation_agent_2(input_data)
            return result
        except json.JSONDecodeError as e:
            logger.error(f"❌ Невалидный JSON: {e}")
            return {"agent_id": 2, "status": "json_error", "error": str(e)}
        except Exception as e:
            logger.error(f"❌ Ошибка обработки: {e}")
            return {"agent_id": 2, "status": "error", "error": str(e)}

    def send_results(self, result: Dict[str, Any]) -> bool:
        """Отправляет результаты в очереди агентов 3 и 4"""
        try:
            result_json = json.dumps(result, ensure_ascii=False)
            self.redis_client.rpush(QUEUE_AGENT_3_INPUT, result_json)
            self.redis_client.rpush(QUEUE_AGENT_4_INPUT, result_json)
            logger.info("📤 Результаты отправлены Агентам 3 и 4")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка отправки результата: {e}")
            return False

    def run(self):
        """Главный цикл обработки сообщений"""
        logger.info("✅ Агент 2 запущен (Главный аналитик)")
        logger.info(f" Модель: {MISTRAL_MODEL}")
        logger.info(f" Импорт: {MISTRAL_IMPORT_VERSION}")
        logger.info(f" Слушаю очередь: {QUEUE_AGENT_2_INPUT}")
        logger.info(" Нажмите Ctrl+C для остановки\n")

        try:
            while True:
                try:
                    result = self.redis_client.blpop(QUEUE_AGENT_2_INPUT, timeout=1)
                    if result is None:
                        continue

                    queue_name, message_data = result
                    logger.info("📨 Получено новое сообщение")

                    # Обрабатываем
                    output = self.process_message(message_data)

                    # Отправляем результаты
                    if output.get("status") != "error":
                        self.send_results(output)

                    logger.info("✅ Анализ завершен\n")

                except Exception as e:
                    logger.error(f"❌ Ошибка в цикле: {e}")
                    time.sleep(1)

        except KeyboardInterrupt:
            logger.info("\n❌ Агент 2 остановлен (Ctrl+C)")
        finally:
            logger.info("Агент 2 завершил работу")

# ============================================================================
# ТОЧКА ВХОДА
# ============================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # Локальное тестирование
        print("\n=== ТЕСТ АГЕНТА 2 ===\n")

        test_cases = [
            ("Привет всем! Как дела?", "Нормальное сообщение"),
            ("Ты дурак! Хуй тебе!", "Мат и оскорбления"),
            ("Я твою мать ебал", "Критичное оскорбление семьи"),
            ("Ты сын шлюхи", "Оскорбление + мат"),
            ("Блять, как это работает?", "Мат в контексте"),
            ("Все евреи воры", "Дискриминация"),
            ("Вступайте в наш чат! t.me/spam", "Спам"),
        ]

        for message, description in test_cases:
            print(f"\n{'='*60}")
            print(f"ТЕСТ: {description}")
            print(f"Сообщение: '{message}'")
            print('='*60)

            test_input = {
                "message": message,
                "rules": DEFAULT_RULES,
                "user_id": 123,
                "username": "test_user",
                "chat_id": -100,
                "message_id": 1,
                "message_link": "https://t.me/test/1"
            }

            result = moderation_agent_2(test_input)
            print(f"Тип: {result['type']}")
            print(f"Серьезность: {result['severity']}/10")
            print(f"Уверенность: {result['confidence']}%")
            print(f"Действие: {result['action']}")
            print(f"Объяснение: {result['explanation']}")

    else:
        # Нормальный запуск
        try:
            worker = Agent2Worker()
            worker.run()
        except KeyboardInterrupt:
            logger.info("Выход")
        except Exception as e:
            logger.error(f"❌ Критическая ошибка: {e}")
