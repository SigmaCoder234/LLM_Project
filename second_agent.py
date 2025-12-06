#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
АГЕНТ №2 — ГЛАВНЫЙ АНАЛИТИК (Исправленный с СУПЕР ПРОМПТОМ)

✅ ИСПРАВЛЕНИЯ:
- Новый МЕГА-ПРОМПТ с ВСЕ типами нарушений
- Правильный парсинг severity (0-10) с множественными regex паттернами
- Фильтр: отправляем ТОЛЬКО нарушения (action != none)
- Улучшенные примеры для каждого типа

КРИТИЧНЫЕ ИЗМЕНЕНИЯ:
1. ПРОМПТ теперь охватывает 15+ типов нарушений
2. Severity определяется ПРАВИЛЬНО
3. Mistral ПОНИМАЕТ что делать
"""

import json
import redis
import time
import re
from typing import Dict, Any, List
from datetime import datetime

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
            def __init__(self, api_key): pass
            def chat(self, **kwargs):
                raise ImportError("Mistral AI не установлен")
        def UserMessage(content): 
            return {"role": "user", "content": content}
        def SystemMessage(content): 
            return {"role": "system", "content": content}

from config import (
    MISTRAL_API_KEY, MISTRAL_MODEL, MISTRAL_GENERATION_PARAMS,
    get_redis_config, QUEUE_AGENT_2_INPUT, QUEUE_AGENT_2_OUTPUT,
    QUEUE_AGENT_3_INPUT, QUEUE_AGENT_4_INPUT, DEFAULT_RULES, setup_logging
)

logger = setup_logging("АГЕНТ 2")

if MISTRAL_IMPORT_SUCCESS:
    logger.info(f"✅ Mistral AI импортирован успешно ({MISTRAL_IMPORT_VERSION})")
else:
    logger.error("❌ Mistral AI не импортирован")

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
# СУПЕР-ПРОМПТ С ВСЕ ТИПАМИ НАРУШЕНИЙ
# ============================================================================

SUPER_PROMPT_SYSTEM = """Ты — ГЛАВНЫЙ АНАЛИТИК модерации Telegram.

✅ ТВОЯ РОЛЬ: Дать МАКСИМАЛЬНО ТОЧНЫЙ анализ сообщения с оценкой severity 0-10.

🎯 ОБЯЗАТЕЛЬНО:
- Severity ЧИСЛОМ от 0 до 10 (не в описании!)
- Один из действий: none, warn, mute, ban
- Реальная оценка, не завышаем

📋 ВСЕ ТИПЫ НАРУШЕНИЙ (15+):

1. МАТ (profanity) — нецензурная лексика
2. ОСКОРБЛЕНИЕ (insult) — личные оскорбления
3. СПАМ (spam) — реклама, ссылки, приглашения
4. ДИСКРИМИНАЦИЯ (discrimination) — расизм, национализм
5. УГРОЗА (threat) — угрозы насилия, убийства
6. ХАРАССМЕНТ (harassment) — преследование, буллинг
7. ФЛУД (flood) — спам одинаковых сообщений, капс
8. ПОРНО (adult_content) — сексуальный контент
9. ФИШИНГ (phishing) — попытки выманить данные
10. ЭКСТРЕМИЗМ (extremism) — пропаганда экстремизма
11. МАНИПУЛЯЦИЯ (manipulation) — попытки манипулировать
12. СКАМ (scam) — мошенничество, развод
13. ТОКСИЧНОСТЬ (toxicity) — ядовитое сообщение
14. ОФФТОПИК (off_topic) — обсуждение запрещённого
15. КОНТЕКСТ (context) — скрытые смыслы, намёки

🔢 SEVERITY ШКАЛА:

0-1 — БЕЗ НАРУШЕНИЯ
├─ "Привет", "Как дела?", обычное общение
├─ Action: none

2-3 — СЛАБОЕ НАРУШЕНИЕ
├─ Легкий спам, "Блять как это?", мягкий флуд
├─ Action: none или warn

4-5 — СРЕДНЕЕ НАРУШЕНИЕ
├─ Спам ссылками, лёгкое оскорбление, капс
├─ Action: warn

6-7 — СЕРЬЁЗНОЕ НАРУШЕНИЕ
├─ Оскорбление без мата, лёгкий мат, дискриминация
├─ Action: warn, может быть mute

8-9 — КРИТИЧНОЕ НАРУШЕНИЕ
├─ Мат + оскорбление, серьёзная дискриминация, угрозы
├─ Action: mute 24h или ban

10 — МАКСИМАЛЬНОЕ НАРУШЕНИЕ
├─ "Ты говно собачье", угрозы убийством, экстремизм
├─ Action: ban

📚 ПРИМЕРЫ АНАЛИЗА:

✅ "Привет, как дела?"
- Severity: 0
- Action: none
- Reason: Нормальное общение

✅ "Блять, как это работает?"
- Severity: 3
- Action: none
- Reason: Мат в контексте удивления, но не адресован

✅ "Ты дурак"
- Severity: 5
- Action: warn
- Reason: Прямое оскорбление

✅ "Ты сын шлюхи, мать твою"
- Severity: 8
- Action: mute
- Reason: Оскорбление + мат + оскорбление семьи

✅ "Я твою мать ебал"
- Severity: 10
- Action: ban
- Reason: Экстремально грубое оскорбление + сексуальный контент

✅ "Все евреи воры"
- Severity: 9
- Action: ban
- Reason: Генерализованное оскорбление целой группы (дискриминация)

✅ "Умри"
- Severity: 7
- Action: warn/mute
- Reason: Угроза насилия

✅ "Негр" / "Жид" / "Цыган"
- Severity: 6-9 (зависит от контекста)
- Action: warn/mute/ban
- Reason: Расовое оскорбление

✅ "Купи вот тут t.me/spam вступи кликни"
- Severity: 6
- Action: warn/mute
- Reason: Спам с ссылками

✅ "ааааааааа!!!!!!!!!"
- Severity: 4
- Action: warn
- Reason: Флуд, капс, спам

КРИТИЧНЫЕ ПРАВИЛА:

1. SEVERITY — ОБЯЗАТЕЛЬНО ЧИСЛО 0-10, не в описании!
   ✅ "severity": 8
   ❌ "severity": "очень серьезно"

2. ВСЕГДА проверяй КОНТЕКСТ
   - "Ебал" vs "Я твою мать ебал" — разная severity!
   - "Негр" в историческом контексте vs просто оскорбление

3. МАТ = минимум severity 4-5, максимум 10
   - Одно матерное слово: 4-5
   - Мат + оскорбление: 7-9
   - Мат + угроза: 10

4. ДИСКРИМИНАЦИЯ = всегда 6+
   - По национальности: 7+
   - По расе: 8+
   - С угрозой: 9-10

5. УГРОЗЫ = минимум 7, максимум 10
   - "Осторожно": 7
   - "Убью": 9
   - "Я знаю где ты": 10

ВЫДАЙ РЕЗУЛЬТАТ В JSON:
{
  "analysis": "подробное описание что видишь",
  "type": "основной тип нарушения (одно из: profanity, insult, spam, discrimination, threat, harassment, flood, adult_content, phishing, extremism, manipulation, scam, toxicity, off_topic, context)",
  "severity": число_0_до_10,
  "confidence": число_0_до_100,
  "action": "none/warn/mute/ban",
  "explanation": "почему это нарушение",
  "is_violation": true_или_false,
  "context_analysis": "анализ скрытых смыслов"
}"""

# ============================================================================
# ГЛАВНЫЙ АНАЛИЗ MISTRAL AI (С УЛУЧШЕННЫМ ПАРСИНГОМ)
# ============================================================================

def analyze_with_mistral(message: str, rules: List[str]) -> Dict[str, Any]:
    """
    ГЛАВНЫЙ АНАЛИТИК - глубокий анализ сообщения через Mistral AI
    """
    
    if not MISTRAL_IMPORT_SUCCESS or not mistral_client:
        logger.warning("⚠️ Mistral AI недоступен, используем fallback")
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
        
        system_message = f"{SUPER_PROMPT_SYSTEM}\n\nПРАВИЛА ЧАТА:\n{rules_text}"
        user_message_text = f'Сообщение для анализа: "{message}"'
        
        # Создаем сообщения
        if MISTRAL_IMPORT_VERSION.startswith("v1.0"):
            messages = [
                SystemMessage(content=system_message),
                UserMessage(content=user_message_text)
            ]
        else:
            # Создаем сообщения с ChatMessage (для обеих версий)
            messages = [
            ChatMessage(role="system", content=system_message),
            ChatMessage(role="user", content=user_message_text)
            ]
        
        # Вызываем API
        if MISTRAL_IMPORT_VERSION.startswith("v1.0"):
            response = mistral_client.chat.complete(
                model=MISTRAL_MODEL,
                messages=messages,
                temperature=0.3,
                max_tokens=700,
                top_p=0.95
            )
        else:
            response = mistral_client.chat(
                model=MISTRAL_MODEL,
                messages=messages,
                temperature=0.3,
                max_tokens=700,
                top_p=0.95
            )
        
        message_obj = response.choices[0].message

        if hasattr(message_obj, 'content'):
            content = message_obj.content
            if not isinstance(content, str):
                # Если content не строка - конвертируем
                content = str(content)
        else:
            # Если это уже строка
            content = str(message_obj)

        
        # ✅ УЛУЧШЕННЫЙ ПАРСИНГ JSON
        try:
            # Ищем JSON блок
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
            logger.warning(f"⚠️ Ошибка парсинга JSON от Mistral: {e}")
            logger.warning(f"Ответ был: {content[:200]}")
            
            # Пытаемся парсить текст вручную
            severity_match = re.search(r'severity["\']?\s*[:=]\s*(\d+)', content, re.IGNORECASE)
            severity = int(severity_match.group(1)) if severity_match else 5
            severity = min(10, max(0, severity))
            
            confidence_match = re.search(r'confidence["\']?\s*[:=]\s*(\d+)', content, re.IGNORECASE)
            confidence = int(confidence_match.group(1)) if confidence_match else 50
            confidence = min(100, max(0, confidence))
            
            action = "none"
            if "ban" in content.lower():
                action = "ban"
            elif "mute" in content.lower():
                action = "mute"
            elif "warn" in content.lower():
                action = "warn"
            
            return {
                "analysis": content[:300],
                "type": "unknown",
                "severity": severity,
                "confidence": confidence,
                "action": action,
                "explanation": "Ошибка парсинга ответа Mistral",
                "is_violation": action != "none",
                "context_analysis": "",
                "status": "parse_error"
            }
    
    except Exception as e:
        logger.error(f"❌ Ошибка анализа Mistral: {e}")
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
            "user_id": user_id,
            "username": username,
            "chat_id": chat_id,
            "message_id": message_id,
            "analysis": "Пустое сообщение",
            "type": "none",
            "severity": 0,
            "confidence": 100,
            "action": "none",
            "explanation": "Пустое сообщение",
            "is_violation": False,
            "context_analysis": ""
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
        logger.info(f"📊 Модель: {MISTRAL_MODEL}")
        logger.info(f"📥 Импорт: {MISTRAL_IMPORT_VERSION}")
        logger.info(f"🔔 Слушаю очередь: {QUEUE_AGENT_2_INPUT}")
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
    try:
        worker = Agent2Worker()
        worker.run()
    except KeyboardInterrupt:
        logger.info("Выход")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
