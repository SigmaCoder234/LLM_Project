#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
АГЕНТ №3 — Анализатор Mistral AI с определением действия модерации
"""

import json
import redis
import time
from typing import Dict, Any, List
from datetime import datetime

# Mistral AI импорты
try:
    from mistralai import Mistral
    from mistralai import UserMessage, SystemMessage
    MISTRAL_IMPORT_SUCCESS = True
    MISTRAL_IMPORT_VERSION = "v1.0+ (новый SDK)"
except ImportError:
    try:
        from mistralai.client import MistralClient as Mistral
        from mistralai.models.chat_completion import ChatMessage
        def UserMessage(content): return {"role": "user", "content": content}
        def SystemMessage(content): return {"role": "system", "content": content}
        MISTRAL_IMPORT_SUCCESS = True
        MISTRAL_IMPORT_VERSION = "v0.4.2 (legacy)"
    except ImportError:
        print("❌ Не удалось импортировать Mistral AI")
        MISTRAL_IMPORT_SUCCESS = False
        MISTRAL_IMPORT_VERSION = "none"
        class Mistral:
            def __init__(self, api_key): pass
            def chat(self, **kwargs):
                raise ImportError("Mistral AI не установлен")
        def UserMessage(content): return {"role": "user", "content": content}
        def SystemMessage(content): return {"role": "system", "content": content}

# Импортируем конфигурацию
from config import (
    MISTRAL_API_KEY,
    MISTRAL_MODEL,
    MISTRAL_GENERATION_PARAMS,
    POSTGRES_URL,
    get_redis_config,
    QUEUE_AGENT_3_INPUT,
    QUEUE_AGENT_5_INPUT,
    AGENT_PORTS,
    DEFAULT_RULES,
    setup_logging,
    determine_action
)

# ============================================================================
# ЛОГИРОВАНИЕ И ИНИЦИАЛИЗАЦИЯ
# ============================================================================

logger = setup_logging("АГЕНТ 3")

if MISTRAL_IMPORT_SUCCESS:
    logger.info(f"✅ Mistral AI импортирован успешно ({MISTRAL_IMPORT_VERSION})")
else:
    logger.error("❌ Mistral AI не импортирован, работа в режиме заглушки")

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ MISTRAL AI КЛИЕНТА
# ============================================================================

if MISTRAL_IMPORT_SUCCESS and MISTRAL_API_KEY:
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
# ОПРЕДЕЛЕНИЕ ТИПА НАРУШЕНИЯ
# ============================================================================

def detect_violation_type(message: str, ai_reason: str) -> str:
    """Определяет тип нарушения по сообщению и ответу ИИ"""
    
    message_lower = message.lower()
    reason_lower = ai_reason.lower()
    
    # Проверяем по ключевым словам в ответе ИИ
    if "мат" in reason_lower or "нецензур" in reason_lower or "ругань" in reason_lower:
        return "profanity"
    elif "спам" in reason_lower or "реклам" in reason_lower or "ссылк" in reason_lower:
        return "spam"
    elif "дискриминац" in reason_lower or "расовый" in reason_lower or "национальн" in reason_lower:
        return "discrimination"
    elif "оскорбление" in reason_lower or "оскорб" in reason_lower or "оскорби" in reason_lower:
        return "harassment"
    elif "флуд" in reason_lower or "повтор" in reason_lower or "спам_символ" in reason_lower:
        return "flood"
    
    # Проверяем по содержимому сообщения
    spam_keywords = ['купить', 'скидка', 'заработок', 'кликай', 'переходи', 'вступай', 'подписывайся']
    if any(keyword in message_lower for keyword in spam_keywords):
        return "spam"
    
    profanity_keywords = ['хуй', 'пизд', 'ебать', 'сука', 'блять', 'долбоёб', 'мудак']
    if any(keyword in message_lower for keyword in profanity_keywords):
        return "profanity"
    
    discrimination_keywords = ['негр', 'еврей', 'цыган', 'узбек', 'таджик', 'киргиз', 'кавказ']
    if any(keyword in message_lower for keyword in discrimination_keywords):
        return "discrimination"
    
    # По умолчанию спам
    return "spam"

# ============================================================================
# АНАЛИЗ С MISTRAL AI
# ============================================================================

def analyze_message_with_mistral(message: str, rules: List[str], severity_hint: int = 5) -> dict:
    """
    Анализирует сообщение через Mistral AI с определением действия.
    
    Возвращает:
    {
        "ban": bool,
        "action": "ban" | "mute" | "warn" | "delete" | "none",
        "action_duration": int (минуты, 0 = навсегда),
        "confidence": float,
        "reason": str,
        "violation_type": str,
        "severity": int (0-10),
        "status": "success" | "fallback"
    }
    """
    
    if not MISTRAL_IMPORT_SUCCESS or not mistral_client:
        logger.warning("⚠️ Mistral AI недоступен, используем заглушку")
        return {
            "ban": False,
            "action": "none",
            "action_duration": 0,
            "confidence": 0.5,
            "reason": "Mistral AI недоступен",
            "violation_type": "unknown",
            "severity": 5,
            "status": "fallback"
        }
    
    try:
        if not rules:
            rules = DEFAULT_RULES
        
        rules_text = "\n".join([f"{i+1}. {rule}" for i, rule in enumerate(rules)])
        
        system_message = f"""Ты — модератор Telegram чата.

ПРАВИЛА ЧАТА:
{rules_text}

ТВОЯ ЗАДАЧА:
1. Проанализируй сообщение
2. Определи тип нарушения (если есть): мат, спам, дискриминация, оскорбление, флуд или нет
3. Оцени СЕРЬЕЗНОСТЬ (0-10): 0=норма, 10=тяжелое нарушение
4. Определи УВЕРЕННОСТЬ (0-100%): насколько ты уверен
5. Предложи ДЕЙСТВИЕ: ban/mute/warn/delete/none

Формат ответа:
ВЕРДИКТ: [банить/не банить]
ТИП НАРУШЕНИЯ: [мат/спам/дискриминация/оскорбление/флуд/нет]
СЕРЬЕЗНОСТЬ: [0-10]
УВЕРЕННОСТЬ: [0-100]
ДЕЙСТВИЕ: [ban/mute/warn/delete/none]
ДЛИТЕЛЬНОСТЬ: [0=навсегда / минуты]
ПРИЧИНА: [текст причины]"""
        
        user_message_text = f'Сообщение: "{message}"'
        
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
        
        # Вызываем API
        if MISTRAL_IMPORT_VERSION.startswith("v1.0"):
            response = mistral_client.chat.complete(
                model=MISTRAL_MODEL,
                messages=messages,
                temperature=MISTRAL_GENERATION_PARAMS.get("temperature", 0.1),
                max_tokens=MISTRAL_GENERATION_PARAMS.get("max_tokens", 400)
            )
            content = response.choices[0].message.content
        else:
            response = mistral_client.chat(
                model=MISTRAL_MODEL,
                messages=messages,
                temperature=MISTRAL_GENERATION_PARAMS.get("temperature", 0.1),
                max_tokens=MISTRAL_GENERATION_PARAMS.get("max_tokens", 400)
            )
            content = response.choices[0].message.content
        
        # Парсим ответ
        content_lower = content.lower()
        
        # Вердикт (банить или нет)
        should_ban = "банить" in content_lower and "не банить" not in content_lower
        
        # Определяем серьезность
        severity = 5
        if "серьезность:" in content_lower:
            try:
                severity_line = [line for line in content.split('\n') if 'серьезность:' in line.lower()][0]
                severity = int(''.join(filter(str.isdigit, severity_line.split(':')[1])))
                severity = min(10, max(0, severity))
            except:
                pass
        
        # Определяем тип нарушения
        violation_type = "spam"
        if "тип нарушения:" in content_lower:
            try:
                violation_line = [line for line in content.split('\n') if 'тип нарушения:' in line.lower()][0]
                violation_text = violation_line.lower()
                if "мат" in violation_text:
                    violation_type = "profanity"
                elif "спам" in violation_text:
                    violation_type = "spam"
                elif "дискриминац" in violation_text:
                    violation_type = "discrimination"
                elif "оскорбление" in violation_text:
                    violation_type = "harassment"
                elif "флуд" in violation_text:
                    violation_type = "flood"
                else:
                    violation_type = "spam"
            except:
                pass
        else:
            violation_type = detect_violation_type(message, content)
        
        # Определяем уверенность
        confidence = 0.7
        if "уверенность:" in content_lower:
            try:
                confidence_line = [line for line in content.split('\n') if 'уверенность:' in line.lower()][0]
                conf_str = ''.join(filter(str.isdigit, confidence_line))
                if conf_str:
                    confidence = int(conf_str) / 100.0
                    confidence = min(1.0, max(0.0, confidence))
            except:
                pass
        
        # Определяем действие и длительность
        action = "none"
        action_duration = 0
        
        if "действие:" in content_lower:
            try:
                action_line = [line for line in content.split('\n') if 'действие:' in line.lower()][0]
                action_text = action_line.lower()
                if "ban" in action_text:
                    action = "ban"
                elif "mute" in action_text:
                    action = "mute"
                elif "warn" in action_text:
                    action = "warn"
                elif "delete" in action_text:
                    action = "delete"
            except:
                pass
        
        # Определяем длительность если это mute
        if action == "mute" and "длительность:" in content_lower:
            try:
                duration_line = [line for line in content.split('\n') if 'длительность:' in line.lower()][0]
                duration_str = ''.join(filter(str.isdigit, duration_line))
                if duration_str and "навсегда" not in duration_line.lower():
                    action_duration = int(duration_str)
            except:
                pass
        
        # Если ИИ не определил действие, используем функцию determine_action
        if action == "none" or not action:
            action_info = determine_action(violation_type, severity, confidence)
            action = action_info["action"]
            action_duration = action_info["duration"]
        
        reason_text = f"Вердикт: {action.upper()}\nПричина: {content}\nУверенность: {int(confidence * 100)}%"
        
        return {
            "ban": action in ["ban", "mute"],
            "action": action,
            "action_duration": action_duration,
            "confidence": confidence,
            "reason": reason_text,
            "violation_type": violation_type,
            "severity": severity,
            "status": "success"
        }
    
    except Exception as e:
        logger.error(f"Ошибка Mistral AI анализа: {e}")
        return {
            "ban": True,
            "action": "none",
            "action_duration": 0,
            "confidence": 0.5,
            "reason": f"Ошибка анализа: {e}",
            "violation_type": "unknown",
            "severity": 5,
            "status": "error"
        }

# ============================================================================
# ОСНОВНАЯ ФУНКЦИЯ АГЕНТА 3
# ============================================================================

def moderation_agent_3(input_data):
    """
    АГЕНТ 3 — Mistral AI анализатор с определением действия
    """
    
    message = input_data.get("message", "")
    rules = input_data.get("rules", [])
    user_id = input_data.get("user_id")
    username = input_data.get("username", "unknown")
    chat_id = input_data.get("chat_id")
    message_id = input_data.get("message_id")
    message_link = input_data.get("message_link", "")
    
    logger.info(f"🔍 Mistral AI анализ сообщения от @{username} в чате {chat_id}")
    
    if not message:
        return {
            "agent_id": 3,
            "ban": False,
            "action": "none",
            "action_duration": 0,
            "reason": "Пустое сообщение",
            "confidence": 0,
            "message": "",
            "user_id": user_id,
            "username": username,
            "chat_id": chat_id,
            "message_id": message_id,
            "violation_type": "none",
            "severity": 0,
            "status": "error"
        }
    
    if not rules:
        rules = DEFAULT_RULES
        logger.info("Используются стандартные правила")
    
    # Анализ через Mistral AI
    analysis_result = analyze_message_with_mistral(message, rules)
    
    output = {
        "agent_id": 3,
        "ban": analysis_result["ban"],
        "action": analysis_result["action"],
        "action_duration": analysis_result["action_duration"],
        "reason": analysis_result["reason"],
        "confidence": analysis_result["confidence"],
        "message": message,
        "user_id": user_id,
        "username": username,
        "chat_id": chat_id,
        "message_id": message_id,
        "message_link": message_link,
        "violation_type": analysis_result["violation_type"],
        "severity": analysis_result["severity"],
        "rules_used": rules,
        "method": "Mistral AI анализ",
        "ai_model": MISTRAL_MODEL,
        "import_version": MISTRAL_IMPORT_VERSION,
        "status": analysis_result["status"],
        "timestamp": datetime.now().isoformat()
    }
    
    if analysis_result["ban"]:
        logger.warning(
            f"⛔ {analysis_result['action'].upper()} для @{username}: "
            f"{analysis_result['confidence'] * 100:.0f}% уверенности "
            f"(тип: {analysis_result['violation_type']}, серьезность: {analysis_result['severity']}/10)"
        )
    else:
        logger.info(
            f"✅ ОК для @{username}: "
            f"{analysis_result['confidence'] * 100:.0f}% уверенности "
            f"(метод: Mistral AI)"
        )
    
    return output

# ============================================================================
# REDIS WORKER
# ============================================================================

class Agent3Worker:
    def __init__(self):
        try:
            redis_config = get_redis_config()
            self.redis_client = redis.Redis(**redis_config)
            self.redis_client.ping()
            logger.info(f"✅ Подключение к Redis успешно")
        except Exception as e:
            logger.error(f"❌ Не удалось подключиться к Redis: {e}")
            raise
    
    def process_message(self, message_data):
        """Обрабатывает сообщение от входной очереди"""
        try:
            input_data = json.loads(message_data)
            result = moderation_agent_3(input_data)
            return result
        except json.JSONDecodeError as e:
            logger.error(f"Невалидный JSON: {e}")
            return {
                "agent_id": 3,
                "ban": False,
                "action": "none",
                "reason": f"Ошибка парсинга: {e}",
                "status": "json_error"
            }
        except Exception as e:
            logger.error(f"Ошибка обработки: {e}")
            return {
                "agent_id": 3,
                "ban": False,
                "action": "none",
                "reason": f"Ошибка агента 3: {e}",
                "status": "error"
            }
    
    def send_result(self, result):
        """Отправляет результат в выходные очереди"""
        try:
            result_json = json.dumps(result, ensure_ascii=False)
            self.redis_client.rpush(QUEUE_AGENT_5_INPUT, result_json)
            logger.info(f"✅ Результат отправлен в очередь Агента 5")
        except Exception as e:
            logger.error(f"Не удалось отправить результат: {e}")
    
    def run(self):
        """Главный цикл обработки сообщений"""
        logger.info(f"✅ Агент 3 запущен (Mistral AI v3.5)")
        logger.info(f" Модель: {MISTRAL_MODEL}")
        logger.info(f" Импорт: {MISTRAL_IMPORT_VERSION}")
        logger.info(f" Статус: {'✅ Доступен' if mistral_client else '❌ Недоступен'}")
        logger.info(f" Слушаю очередь: {QUEUE_AGENT_3_INPUT}")
        logger.info(" Нажмите Ctrl+C для остановки\n")
        
        try:
            while True:
                try:
                    result = self.redis_client.blpop(QUEUE_AGENT_3_INPUT, timeout=1)
                    if result is None:
                        continue
                    
                    queue_name, message_data = result
                    logger.info(f"📨 Получено сообщение")
                    
                    output = self.process_message(message_data)
                    self.send_result(output)
                    
                    logger.info(f"✅ Обработка завершена\n")
                except Exception as e:
                    logger.error(f"Ошибка в цикле: {e}")
                    time.sleep(1)
        except KeyboardInterrupt:
            logger.info("\n❌ Агент 3 остановлен (Ctrl+C)")
        finally:
            logger.info("Агент 3 завершил работу")

# ============================================================================
# ТОЧКА ВХОДА
# ============================================================================

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # Тестирование
        test_cases = [
            {
                "message": "Привет всем! Как дела?",
                "description": "Нормальное сообщение"
            },
            {
                "message": "Ты дурак и идиот! Хуй тебе!",
                "description": "Мат и оскорбления"
            },
            {
                "message": "Переходи по ссылке t.me/spam! Заработок 100$ в день!",
                "description": "Спам с ссылкой"
            },
            {
                "message": "Все негры должны убираться отсюда!",
                "description": "Расовая дискриминация"
            }
        ]
        
        for i, test_case in enumerate(test_cases, 1):
            print(f"\n--- Тест {i}: {test_case['description']} ---")
            test_input = {
                "message": test_case["message"],
                "rules": DEFAULT_RULES,
                "user_id": 123 + i,
                "username": f"test_user_{i}",
                "chat_id": -100,
                "message_id": i,
                "message_link": f"https://t.me/test/{i}"
            }
            
            result = moderation_agent_3(test_input)
            print(f"Действие: {result['action']}")
            print(f"Серьезность: {result['severity']}/10")
            print(f"Уверенность: {result['confidence'] * 100:.0f}%")
            print(f"Тип нарушения: {result['violation_type']}")
    else:
        try:
            worker = Agent3Worker()
            worker.run()
        except KeyboardInterrupt:
            logger.info("Выход")
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")