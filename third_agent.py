#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
АГЕНТ №3 — АРБИТР (Усовершенствованный анализ с улучшенным парсингом)
============================================================================
✅ ИСПРАВЛЕНИЯ:
- Правильный парсинг серьезности (severity)
- Фильтр: отправляет ТОЛЬКО нарушения (не все сообщения)
- Улучшенный prompt для Mistral
- JSON парсинг с fallback режимом

Severity определяется ПРАВИЛЬНО: от 0 до 10
Отправляются ТОЛЬКО нарушения (action != none)
"""

import json
import redis
import time
from typing import Dict, Any, List
from datetime import datetime
import re

try:
    from mistralai import Mistral
    from mistralai import UserMessage, SystemMessage
    MISTRAL_IMPORT_SUCCESS = True
    MISTRAL_IMPORT_VERSION = "v1.0 SDK"
except ImportError:
    try:
        from mistralai.client import MistralClient as Mistral
        from mistralai.models.chatcompletion import ChatMessage
        def UserMessage(content):
            return {"role": "user", "content": content}
        def SystemMessage(content):
            return {"role": "system", "content": content}
        MISTRAL_IMPORT_SUCCESS = True
        MISTRAL_IMPORT_VERSION = "v0.4.2 (legacy)"
    except ImportError:
        print("❌ Mistral AI не установлен!")
        MISTRAL_IMPORT_SUCCESS = False
        MISTRAL_IMPORT_VERSION = "none"

from config import (
    MISTRAL_API_KEY, MISTRAL_MODEL, MISTRAL_GENERATION_PARAMS,
    get_redis_config, QUEUE_AGENT_3_INPUT, QUEUE_AGENT_5_INPUT,
    DEFAULT_RULES, setup_logging, determine_action
)

logger = setup_logging("АГЕНТ 3")

if MISTRAL_IMPORT_SUCCESS:
    logger.info(f"✅ Mistral AI импортирован успешно ({MISTRAL_IMPORT_VERSION})")
else:
    logger.error(f"❌ Mistral AI не импортирован!")

if MISTRAL_IMPORT_SUCCESS and MISTRAL_API_KEY:
    try:
        mistral_client = Mistral(api_key=MISTRAL_API_KEY)
        logger.info("✅ Mistral AI клиент создан")
    except Exception as e:
        logger.error(f"❌ Ошибка создания клиента: {e}")
        mistral_client = None
else:
    mistral_client = None
    logger.warning("⚠️ Mistral API ключ не установлен!")

# ============================================================================
# ОБНАРУЖЕНИЕ ТИПА НАРУШЕНИЯ
# ============================================================================

def detect_violation_type(message: str, ai_reason: str) -> str:
    """Определяет тип нарушения на основе сообщения"""
    message_lower = message.lower()
    reason_lower = ai_reason.lower()
    
    # Проверяем по ключевым словам
    if any(word in reason_lower for word in ["оскорбление", "оскорбл", "ненав", "грубо", "матерн"]):
        return "profanity"
    elif any(word in reason_lower for word in ["спам", "реклама", "ссылка", "бот", "копирова"]):
        return "spam"
    elif any(word in reason_lower for word in ["дискримина", "расизм", "расовый", "национ"]):
        return "discrimination"
    elif any(word in reason_lower for word in ["харасс", "преслед", "угроза", "запугив"]):
        return "harassment"
    elif any(word in reason_lower for word in ["флуд", "капс", "ЗАГЛАВ"]):
        return "flood"
    
    # Прямой поиск в сообщении
    profanity_keywords = ["ебал", "мать", "пидор", "сука", "блядь", "хуй", "ублюдок", "ебать", "хуярить", "долб", "конч"]
    if any(keyword in message_lower for keyword in profanity_keywords):
        return "profanity"
    
    spam_keywords = ["купи", "подпис", "кликни", "переход", "ссылка", "бот", "клик"]
    if any(keyword in message_lower for keyword in spam_keywords):
        return "spam"
    
    discrimination_keywords = ["негр", "жид", "татар", "чечен", "турок", "араб", "цыган"]
    if any(keyword in message_lower for keyword in discrimination_keywords):
        return "discrimination"
    
    harassment_keywords = ["убью", "избью", "убий", "туда", "петли", "балкон"]
    if any(keyword in message_lower for keyword in harassment_keywords):
        return "harassment"
    
    return "spam"

# ============================================================================
# УЛУЧШЕННЫЙ ПАРСИНГ JSON
# ============================================================================

def parse_json_response(content: str) -> Dict[str, Any]:
    """
    Парсит ответ от Mistral с улучшенной обработкой ошибок
    """
    try:
        # Ищем JSON блок
        json_start = content.find('{')
        json_end = content.rfind('}') + 1
        
        if json_start != -1 and json_end > json_start:
            json_str = content[json_start:json_end]
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass
        
        # Если JSON блока нет, парсим текст вручную
        result = {}
        
        # Parsinj severity: ищем числа от 0 до 10
        severity_match = re.search(r'серьезность[:\s]*(\d+)', content.lower())
        if severity_match:
            result['severity'] = min(10, max(0, int(severity_match.group(1))))
        else:
            # Альтернативный поиск
            severity_match = re.search(r'(\d+)\s*/\s*10', content)
            if severity_match:
                result['severity'] = min(10, max(0, int(severity_match.group(1))))
            else:
                result['severity'] = 5
        
        # Parsing confidence
        conf_match = re.search(r'уверенность[:\s]*(\d+)', content.lower())
        if conf_match:
            result['confidence'] = min(100, max(0, int(conf_match.group(1))))
        else:
            result['confidence'] = 50
        
        # Парсинг action
        action = "none"
        if "ban" in content.lower():
            action = "ban"
        elif "mute" in content.lower():
            action = "mute"
        elif "warn" in content.lower():
            action = "warn"
        elif "delete" in content.lower():
            action = "delete"
        result['action'] = action
        
        result['reason'] = content[:200]  # Первые 200 символов как причина
        
        return result
    except Exception as e:
        logger.warning(f"⚠️ Ошибка парсинга JSON: {e}")
        return {
            'severity': 5,
            'confidence': 30,
            'action': 'warn',
            'reason': 'Ошибка парсинга'
        }

# ============================================================================
# АНАЛИЗ СООБЩЕНИЯ С MISTRAL
# ============================================================================

def analyze_message_with_mistral(message: str, rules: List[str]) -> dict:
    """
    Анализирует сообщение с Mistral и возвращает решение
    
    Returns:
        {
            'ban': bool,
            'action': 'ban' | 'mute' | 'warn' | 'delete' | 'none',
            'action_duration': int,
            'confidence': 0-100,
            'reason': str,
            'violation_type': str,
            'severity': 0-10,
            'status': 'success' | 'error' | 'fallback'
        }
    """
    
    if not MISTRAL_IMPORT_SUCCESS or not mistral_client:
        logger.warning("⚠️ Mistral AI недоступен, используется fallback")
        return {
            'ban': False,
            'action': 'none',
            'action_duration': 0,
            'confidence': 0.5,
            'reason': 'Mistral AI недоступен',
            'violation_type': 'unknown',
            'severity': 5,
            'status': 'fallback'
        }
    
    try:
        if not rules:
            rules = DEFAULT_RULES
        
        rules_text = "\n".join(f"{i+1}. {rule}" for i, rule in enumerate(rules))
        
        system_message = f"""Ты модератор Telegram чата. Анализируй сообщение и определи нарушает ли оно правила.

Правила чата:
{rules_text}

ВАЖНО! Отвечай ТОЛЬКО JSON без лишних объяснений:
{{
  "violation_type": "profanity" | "spam" | "discrimination" | "harassment" | "flood" | "none",
  "severity": <число от 0 до 10, где 10 это максимальное нарушение>,
  "confidence": <число от 0 до 100, уверенность в определении>,
  "action": "ban" | "mute" | "warn" | "delete" | "none",
  "reason": "<краткая причина>"
}}

ПРИМЕРЫ SEVERITY:
- 0-2: Нет нарушения
- 3-4: Слабое нарушение (спам, флуд)
- 5-6: Среднее нарушение (оскорбление без матов)
- 7-8: Серьёзное нарушение (оскорбление с матами, лёгкая дискриминация)
- 9-10: Критическое нарушение (сильное оскорбление, угрозы, экстремизм)

ПРИМЕРЫ ДЕЙСТВИЙ:
- severity 0-3: none (ничего не делать)
- severity 4-5: warn (предупреждение)
- severity 6-7: mute (молчание на 24 часа)
- severity 8-10: ban (бан)
"""

        user_message_text = f"""Проверь это сообщение на нарушение правил:

"{message}"

Помни: severity ОБЯЗАТЕЛЬНО число от 0 до 10!
"""
        
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
        
        if MISTRAL_IMPORT_VERSION.startswith("v1.0"):
            response = mistral_client.chat.complete(
                model=MISTRAL_MODEL,
                messages=messages,
                temperature=MISTRAL_GENERATION_PARAMS.get("temperature", 0.1),
                max_tokens=MISTRAL_GENERATION_PARAMS.get("max_tokens", 400)
            )
        else:
            response = mistral_client.chat(
                model=MISTRAL_MODEL,
                messages=messages,
                temperature=MISTRAL_GENERATION_PARAMS.get("temperature", 0.1),
                max_tokens=MISTRAL_GENERATION_PARAMS.get("max_tokens", 400)
            )
        
        content = response.choices[0].message.content
        
        # Парсим JSON
        try:
            json_start = content.find('{')
            json_end = content.rfind('}') + 1
            
            if json_start != -1 and json_end > json_start:
                json_str = content[json_start:json_end]
                result = json.loads(json_str)
                
                # ВАЛИДАЦИЯ И КОРРЕКЦИЯ
                severity = int(result.get('severity', 5))
                severity = min(10, max(0, severity))  # Гарантируем 0-10
                
                confidence = int(result.get('confidence', 50))
                confidence = min(100, max(0, confidence))  # Гарантируем 0-100
                
                violation_type = result.get('violation_type', 'unknown')
                action = result.get('action', 'none').lower()
                reason = result.get('reason', 'Нарушение правил чата')
                
                # ФИЛЬТР: Если severity < 3 и action == none → no violation
                if severity < 3 and action == 'none':
                    violation_type = 'none'
                
                # Если violation_type == 'none' → action должен быть 'none'
                if violation_type == 'none':
                    action = 'none'
                
                # Определяем action по severity если не указан
                if action == 'none' and severity >= 3:
                    if severity >= 8:
                        action = 'ban'
                    elif severity >= 6:
                        action = 'mute'
                    elif severity >= 4:
                        action = 'warn'
                    else:
                        action = 'none'
                
                return {
                    'ban': action in ['ban'],
                    'action': action,
                    'action_duration': 1440 if action == 'mute' else 0,
                    'confidence': confidence,
                    'reason': reason,
                    'violation_type': violation_type,
                    'severity': severity,
                    'status': 'success'
                }
            else:
                # JSON не найден, парсим текст
                parsed = parse_json_response(content)
                return {
                    'ban': parsed.get('action') in ['ban'],
                    'action': parsed.get('action', 'none'),
                    'action_duration': 1440 if parsed.get('action') == 'mute' else 0,
                    'confidence': parsed.get('confidence', 30),
                    'reason': parsed.get('reason', 'Анализ Mistral'),
                    'violation_type': detect_violation_type(message, content),
                    'severity': parsed.get('severity', 5),
                    'status': 'parse_error'
                }
        
        except json.JSONDecodeError as e:
            logger.warning(f"⚠️ Ошибка парсинга JSON: {e}")
            parsed = parse_json_response(content)
            return {
                'ban': False,
                'action': parsed.get('action', 'warn'),
                'action_duration': 0,
                'confidence': parsed.get('confidence', 30),
                'reason': 'Ошибка парсинга',
                'violation_type': detect_violation_type(message, content),
                'severity': parsed.get('severity', 5),
                'status': 'parse_error'
            }
    
    except Exception as e:
        logger.error(f"❌ Ошибка Mistral: {e}")
        return {
            'ban': False,
            'action': 'warn',
            'action_duration': 0,
            'confidence': 30,
            'reason': f'Ошибка: {str(e)}',
            'violation_type': 'unknown',
            'severity': 5,
            'status': 'error'
        }

# ============================================================================
# ОСНОВНОЙ ОБРАБОТЧИК АГЕНТА 3
# ============================================================================

def moderation_agent_3(input_data: Dict[str, Any]):
    """Основная функция модерации Агента 3"""
    
    message = input_data.get('message', '')
    rules = input_data.get('rules', [])
    user_id = input_data.get('user_id')
    username = input_data.get('username', 'unknown')
    chat_id = input_data.get('chat_id')
    message_id = input_data.get('message_id')
    message_link = input_data.get('message_link', '')
    
    logger.info(f"🔍 Анализирую сообщение от @{username}: '{message[:50]}...'")
    
    if not message:
        return {
            'agent_id': 3,
            'ban': False,
            'action': 'none',
            'action_duration': 0,
            'reason': 'Пустое сообщение',
            'confidence': 0,
            'message': '',
            'user_id': user_id,
            'username': username,
            'chat_id': chat_id,
            'message_id': message_id,
            'violation_type': 'none',
            'severity': 0,
            'status': 'error'
        }
    
    if not rules:
        rules = DEFAULT_RULES
    
    logger.info(f"Mistral AI клиент создан" if mistral_client else "Mistral AI недоступен")
    
    # Анализируем с Mistral
    analysis_result = analyze_message_with_mistral(message, rules)
    
    output = {
        'agent_id': 3,
        'ban': analysis_result['ban'],
        'action': analysis_result['action'],
        'action_duration': analysis_result['action_duration'],
        'reason': analysis_result['reason'],
        'confidence': analysis_result['confidence'],
        'message': message,
        'user_id': user_id,
        'username': username,
        'chat_id': chat_id,
        'message_id': message_id,
        'message_link': message_link,
        'violation_type': analysis_result['violation_type'],
        'severity': analysis_result['severity'],
        'rules_used': rules,
        'method': 'Mistral AI (улучшенный)',
        'ai_model': MISTRAL_MODEL,
        'import_version': MISTRAL_IMPORT_VERSION,
        'status': analysis_result['status'],
        'timestamp': datetime.now().isoformat()
    }
    
    # ЛОГИРОВАНИЕ
    if analysis_result['action'] != 'none':
        logger.warning(f"⚠️ {analysis_result['action'].upper()}: @{username} | "
                      f"Severity={analysis_result['severity']}/10 | "
                      f"Confidence={analysis_result['confidence']}% | "
                      f"Type={analysis_result['violation_type']}")
    else:
        logger.info(f"✅ OK: @{username} | Severity={analysis_result['severity']}/10 | Confidence={analysis_result['confidence']}%")
    
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
            logger.info("✅ Подключение к Redis успешно")
        except Exception as e:
            logger.error(f"❌ Не удалось подключиться к Redis: {e}")
            raise

    def process_message(self, message_data: str):
        try:
            input_data = json.loads(message_data)
            result = moderation_agent_3(input_data)
            return result
        except json.JSONDecodeError as e:
            logger.error(f"❌ Ошибка парсинга JSON: {e}")
            return {'agent_id': 3, 'status': 'json_error', 'error': str(e)}
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}")
            return {'agent_id': 3, 'status': 'error', 'error': str(e)}

    def send_result(self, result):
        try:
            result_json = json.dumps(result, ensure_ascii=False)
            self.redis_client.rpush(QUEUE_AGENT_5_INPUT, result_json)
            logger.info(f"📤 Результаты отправлены Агенту 5")
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {e}")

    def run(self):
        logger.info("✅ Агент 3 запущен (Арбитр - улучшенная версия)")
        logger.info(f"📊 Модель: {MISTRAL_MODEL}")
        logger.info(f"📥 Импорт: {MISTRAL_IMPORT_VERSION}")
        logger.info(f"🔔 Слушаю очередь: {QUEUE_AGENT_3_INPUT}")
        logger.info("💡 Ждёшь только РЕАЛЬНЫЕ нарушения (severity >= 3)")
        logger.info("⏸️ Нажмите Ctrl+C для остановки\n")

        try:
            while True:
                try:
                    result = self.redis_client.blpop(QUEUE_AGENT_3_INPUT, timeout=1)
                    if result is None:
                        continue

                    queue_name, message_data = result
                    logger.info("📨 Получено новое сообщение")

                    output = self.process_message(message_data)
                    self.send_result(output)

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
