#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
АГЕНТ №4 — Эвристический модератор + OpenAI резерв (с конфигурацией из .env)
"""

import json
import redis
import time
import re
from typing import Dict, Any, List
from datetime import datetime
from openai import OpenAI

# Импортируем централизованную конфигурацию
from config import (
    OPENAI_API_KEY,
    get_redis_config,
    QUEUE_AGENT_4_INPUT,
    QUEUE_AGENT_4_OUTPUT,
    QUEUE_AGENT_5_INPUT,
    AGENT_PORTS,
    DEFAULT_RULES,
    setup_logging
)

# ============================================================================
# ЛОГИРОВАНИЕ
# ============================================================================
logger = setup_logging("АГЕНТ 4")

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ OPENAI
# ============================================================================
client = OpenAI(api_key=OPENAI_API_KEY)

# ============================================================================
# ЭВРИСТИЧЕСКИЕ ПРАВИЛА И ПАТТЕРНЫ
# ============================================================================

# Список матерных и токсичных слов (расширенный)
PROFANITY_PATTERNS = [
    # Основные нецензурные слова
    r'\b(хуй|хуя|хуё|хуи|хую)\b',
    r'\b(пизд[аеиоу]|пиздец|пиздёж)\b', 
    r'\b(ебать|ебал|ебёт|ебут|ебали|ебаный|ебучий)\b',
    r'\b(сука|суки|сучка|сучий)\b',
    r'\b(блядь|блять|бля|блея)\b',
    r'\b(долбоёб|долбаёб|мудак|мудила)\b',
    r'\b(пидор|пидар|пидр|гомик)\b',
    r'\b(говно|говнюк|говняшка)\b',
    
    # Оскорбления
    r'\b(дурак|дура|дебил|идиот|тупой|тупица)\b',
    r'\b(кретин|придурок|дундук|балбес)\b',
    r'\b(урод|уродина|уебок|уёбок)\b',
    r'\b(тварь|сволочь|гад|падла)\b',
    
    # Вариации с заменой букв
    r'\b(х[уy][йi]|п[иi][зs][дd]|[еe]б[аa])\b',
    r'\b(с[уy]к[аa]|бл[яy][дd]ь?)\b',
]

# Паттерны спама и рекламы
SPAM_PATTERNS = [
    # Призывы к действию
    r'\b(переходи|кликай|жми|нажимай|вступай|подписывайся)\b',
    r'\b(заходи|регистрируйся|скачивай|покупай)\b',
    
    # Коммерческие термины
    r'\b(скидка|акция|распродажа|дешево|выгодно)\b',
    r'\b(заработок|доход|прибыль|инвестиции)\b',
    r'\b(продам|куплю|обмен|торговля)\b',
    
    # Ссылки и каналы (согласно новым правилам v2.0)
    r'@[a-zA-Z0-9_]+',  # Упоминания каналов/пользователей
    r't\.me/[a-zA-Z0-9_]+',  # Telegram ссылки
    r'https?://[^\s]+',  # HTTP ссылки
    r'www\.[^\s]+',  # Веб-сайты
    
    # Эмодзи спам
    r'[📢📣🎉💰🔥⚡]{3,}',  # 3+ одинаковых эмодзи
]

# Паттерны дискриминации (согласно новым правилам v2.0)
DISCRIMINATION_PATTERNS = [
    # Расовые термины
    r'\b(негр|ниггер|черножоп|чурка|хач|хохол)\b',
    r'\b(жид|еврей[а-я]*\s*(плохо|хуйово))\b',
    r'\b(цыган|цыганё|цыганка)\s*[а-я]*\b',
    r'\b(узкогляз|косоглаз|раскосый)\b',
    
    # Национальная дискриминация  
    r'\b(москаль|кацап|бандера|укроп)\b',
    r'\b(чурбан|лицо кавказской национальности)\b',
    r'\b(азиат|узбек|таджик|киргиз)\s+[а-я]*\b',
    
    # Обобщающие дискриминационные высказывания
    r'все\s+(евреи|негры|цыгане|[а-я]+ы)\s+(плохие|воры|дураки)',
    r'эти\s+(черные|желтые|белые)\s+должны',
]

# Флуд паттерны
FLOOD_PATTERNS = [
    r'(.)\1{10,}',  # 10+ одинаковых символов подряд
    r'([а-яё])\1{5,}',  # 5+ одинаковых русских букв
    r'[!]{5,}|[?]{5,}|[.]{5,}',  # 5+ знаков препинания
]

# ============================================================================
# ЭВРИСТИЧЕСКИЙ АНАЛИЗ
# ============================================================================
def check_profanity(message: str) -> tuple:
    """Проверка на нецензурную лексику"""
    message_lower = message.lower()
    violations = []
    
    for pattern in PROFANITY_PATTERNS:
        matches = re.findall(pattern, message_lower, re.IGNORECASE)
        if matches:
            violations.extend(matches)
    
    if violations:
        confidence = min(0.9, 0.6 + len(violations) * 0.1)  # 60-90%
        return True, f"Обнаружена нецензурная лексика: {', '.join(set(violations))}", confidence
    
    return False, "", 0.0

def check_spam(message: str) -> tuple:
    """Проверка на спам и рекламу"""
    message_lower = message.lower()
    violations = []
    
    for pattern in SPAM_PATTERNS:
        matches = re.findall(pattern, message_lower, re.IGNORECASE)
        if matches:
            violations.extend(matches)
    
    if violations:
        confidence = min(0.85, 0.5 + len(violations) * 0.1)  # 50-85%
        return True, f"Обнаружен спам/реклама: {', '.join(set(violations))}", confidence
    
    return False, "", 0.0

def check_discrimination(message: str) -> tuple:
    """Проверка на дискриминацию (согласно правилам v2.0)"""
    message_lower = message.lower()
    violations = []
    
    for pattern in DISCRIMINATION_PATTERNS:
        matches = re.findall(pattern, message_lower, re.IGNORECASE)
        if matches:
            violations.extend(matches)
    
    if violations:
        confidence = min(0.95, 0.7 + len(violations) * 0.1)  # 70-95%
        return True, f"Обнаружена дискриминация: {', '.join(set(violations))}", confidence
    
    return False, "", 0.0

def check_flood(message: str) -> tuple:
    """Проверка на флуд"""
    violations = []
    
    for pattern in FLOOD_PATTERNS:
        matches = re.findall(pattern, message, re.IGNORECASE)
        if matches:
            violations.extend(matches)
    
    if violations:
        confidence = 0.75  # Средняя уверенность для флуда
        return True, f"Обнаружен флуд: повторяющиеся символы", confidence
    
    return False, "", 0.0

def heuristic_analysis(message: str, rules: List[str]) -> dict:
    """
    Комплексный эвристический анализ сообщения.
    Возвращает результат в новом формате v2.0
    """
    violations = []
    max_confidence = 0.0
    main_reason = ""
    
    # Проверяем все виды нарушений
    checks = [
        check_profanity(message),
        check_spam(message), 
        check_discrimination(message),
        check_flood(message)
    ]
    
    for has_violation, reason, confidence in checks:
        if has_violation:
            violations.append(reason)
            if confidence > max_confidence:
                max_confidence = confidence
                main_reason = reason
    
    # Определяем финальный вердикт
    if violations:
        verdict = "банить"
        confidence_percent = int(max_confidence * 100)
        combined_reason = f"Вердикт: {verdict}\nПричина: {main_reason}\nУверенность: {confidence_percent}%"
        
        return {
            "ban": True,
            "reason": combined_reason,
            "confidence": max_confidence,
            "method": "эвристический анализ",
            "violations_count": len(violations),
            "all_violations": violations
        }
    else:
        return {
            "ban": False,
            "reason": "Вердикт: не банить\nПричина: Нарушений не обнаружено\nУверенность: 80%",
            "confidence": 0.8,
            "method": "эвристический анализ",
            "violations_count": 0,
            "all_violations": []
        }

# ============================================================================
# OPENAI РЕЗЕРВНЫЙ АНАЛИЗ (с новым промптом v2.0)
# ============================================================================
def openai_fallback_analysis(message: str, rules: List[str]) -> dict:
    """
    Резервный анализ через OpenAI с обновленным промптом v2.0
    """
    try:
        # Если правил нет, используем стандартные
        if not rules:
            rules = DEFAULT_RULES
        
        rules_text = "\n".join([f"{i+1}. {rule}" for i, rule in enumerate(rules)])
        
        system_msg = f"""Ты — модератор группового чата. Твоя задача — получать сообщения из чата и анализировать их с точки зрения соответствия правилам. По каждому сообщению выноси вердикт: «банить» или «не банить», указывая причину решения и степень уверенности в процентах.

ПРАВИЛА ЧАТА:
{rules_text}

Формат вывода:
Вердикт: <банить/не банить>
Причина: <текст причины>
Уверенность: <число от 0 до 100>%

ИНСТРУКЦИИ:
1. Анализируй сообщение строго по указанным правилам
2. Будь объективным в оценке
3. Указывай конкретную причину решения
4. Уверенность должна отражать степень нарушения (0-100%)

Это резервный анализ после эвристической проверки."""
        
        user_msg = f"Сообщение пользователя:\n\"{message}\""
        
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg}
            ],
            temperature=0.1,
            max_tokens=300
        )
        
        content = response.choices[0].message.content
        
        # Парсим ответ в новом формате
        content_lower = content.lower()
        
        # Ищем вердикт
        ban = False
        if "вердикт:" in content_lower:
            verdict_line = [line for line in content.split('\n') if 'вердикт:' in line.lower()]
            if verdict_line:
                verdict_text = verdict_line[0].lower()
                if "банить" in verdict_text and "не банить" not in verdict_text:
                    ban = True
        
        # Ищем уверенность
        confidence = 0.6  # По умолчанию
        if "уверенность:" in content_lower:
            confidence_line = [line for line in content.split('\n') if 'уверенность:' in line.lower()]
            if confidence_line:
                try:
                    import re
                    numbers = re.findall(r'\d+', confidence_line[0])
                    if numbers:
                        confidence = int(numbers[0]) / 100.0
                        confidence = min(1.0, max(0.0, confidence))
                except:
                    confidence = 0.6
        
        return {
            "ban": ban,
            "reason": content,
            "confidence": confidence,
            "method": "OpenAI резервный анализ",
            "ai_response": True
        }
        
    except Exception as e:
        logger.error(f"Ошибка OpenAI резервного анализа: {e}")
        return {
            "ban": False,
            "reason": f"Вердикт: не банить\nПричина: Ошибка ИИ анализа: {e}\nУверенность: 0%",
            "confidence": 0.0,
            "method": "ошибка OpenAI",
            "ai_response": False
        }

# ============================================================================
# ОСНОВНАЯ ЛОГИКА АГЕНТА 4
# ============================================================================
def moderation_agent_4(input_data):
    """
    АГЕНТ 4 — Эвристический модератор + OpenAI резерв (v2.0).
    Сначала применяет эвристические правила, при неуверенности — OpenAI.
    """
    message = input_data.get("message", "")
    rules = input_data.get("rules", [])
    user_id = input_data.get("user_id")
    username = input_data.get("username")
    chat_id = input_data.get("chat_id")
    message_id = input_data.get("message_id")
    message_link = input_data.get("message_link", "")
    
    logger.info(f"Анализирую сообщение от @{username} в чате {chat_id}")
    
    if not message:
        return {
            "agent_id": 4,
            "ban": False,
            "reason": "Вердикт: не банить\nПричина: Пустое сообщение\nУверенность: 0%",
            "confidence": 0,
            "message": "",
            "user_id": user_id,
            "username": username,
            "chat_id": chat_id,
            "message_id": message_id,
            "status": "error"
        }
    
    # Если правил нет, используем стандартные
    if not rules:
        rules = DEFAULT_RULES
        logger.info("Используются стандартные правила v2.0")
    
    # Сначала эвристический анализ
    heuristic_result = heuristic_analysis(message, rules)
    
    # Определяем, нужен ли OpenAI резерв
    use_openai_fallback = False
    
    if heuristic_result["confidence"] < 0.7:  # Низкая уверенность
        use_openai_fallback = True
        logger.info(f"Низкая уверенность эвристики ({heuristic_result['confidence']:.2f}), используем OpenAI резерв")
    elif not heuristic_result["ban"] and any(keyword in message.lower() for keyword in ['сложный', 'неоднозначный', 'спорный']):
        use_openai_fallback = True
        logger.info("Потенциально сложное сообщение, используем OpenAI резерв")
    
    # Применяем OpenAI резерв если нужно
    if use_openai_fallback:
        openai_result = openai_fallback_analysis(message, rules)
        
        # Комбинируем результаты (приоритет у OpenAI при конфликте)
        if openai_result["confidence"] > heuristic_result["confidence"]:
            final_result = openai_result
            final_result["method"] = f"OpenAI резерв (эвристика: {heuristic_result['confidence']:.2f})"
            logger.info(f"Использован OpenAI резерв (уверенность: {openai_result['confidence']:.2f})")
        else:
            final_result = heuristic_result
            final_result["fallback_attempted"] = True
            logger.info(f"Остался с эвристикой (OpenAI: {openai_result['confidence']:.2f})")
    else:
        final_result = heuristic_result
        final_result["fallback_attempted"] = False
        logger.info(f"Использована только эвристика (уверенность: {heuristic_result['confidence']:.2f})")
    
    output = {
        "agent_id": 4,
        "ban": final_result["ban"],
        "reason": final_result["reason"],
        "confidence": final_result["confidence"],
        "message": message,
        "user_id": user_id,
        "username": username,
        "chat_id": chat_id,
        "message_id": message_id,
        "message_link": message_link,
        "method": final_result["method"],
        "rules_used": rules,
        "status": "success",
        "timestamp": datetime.now().isoformat()
    }
    
    if final_result["ban"]:
        logger.warning(f"БАН ⛔ для @{username}: {final_result['confidence']*100:.0f}% уверенности ({final_result['method']})")
    else:
        logger.info(f"ОК ✅ для @{username}: {final_result['confidence']*100:.0f}% уверенности ({final_result['method']})")
    
    return output

# ============================================================================
# РАБОТА С REDIS И ВЗАИМОДЕЙСТВИЕ МЕЖДУ АГЕНТАМИ
# ============================================================================
class Agent4Worker:
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
            result = moderation_agent_4(input_data)
            return result
        except json.JSONDecodeError as e:
            logger.error(f"Невалидный JSON: {e}")
            return {
                "agent_id": 4,
                "ban": False,
                "reason": f"Ошибка парсинга данных: {e}",
                "confidence": 0,
                "message": "",
                "status": "json_error"
            }
        except Exception as e:
            logger.error(f"Ошибка обработки сообщения: {e}")
            return {
                "agent_id": 4,
                "ban": False,
                "reason": f"Внутренняя ошибка агента 4: {e}",
                "confidence": 0,
                "message": "",
                "status": "error"
            }
    
    def send_result(self, result):
        """Отправляет результат в выходную очередь"""
        try:
            result_json = json.dumps(result, ensure_ascii=False)
            # Отправляем результат в очередь Агента 4
            self.redis_client.rpush(QUEUE_AGENT_4_OUTPUT, result_json)
            
            # Отправляем результат в очередь Агента 5
            self.redis_client.rpush(QUEUE_AGENT_5_INPUT, result_json)
            
            logger.info(f"✅ Результат отправлен в очереди")
            
        except Exception as e:
            logger.error(f"Не удалось отправить результат: {e}")
    
    def run(self):
        """Главный цикл обработки сообщений"""
        logger.info(f"✅ Агент 4 запущен (Эвристика + OpenAI резерв v4.3 с .env)")
        logger.info(f"   Слушаю очередь: {QUEUE_AGENT_4_INPUT}")
        logger.info(f"   Отправляю результаты в: {QUEUE_AGENT_4_OUTPUT}")
        logger.info(f"   Отправляю в Агента 5: {QUEUE_AGENT_5_INPUT}")
        logger.info(f"   Стандартные правила v2.0: {DEFAULT_RULES}")
        logger.info("   Нажмите Ctrl+C для остановки\n")
        
        try:
            while True:
                try:
                    result = self.redis_client.blpop(QUEUE_AGENT_4_INPUT, timeout=1)
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
            logger.info("\n❌ Агент 4 остановлен (Ctrl+C)")
        finally:
            logger.info("Агент 4 завершил работу")

# ============================================================================
# HEALTH CHECK ENDPOINT
# ============================================================================
def create_health_check_server():
    """Создает простой HTTP сервер для проверки здоровья агента"""
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import threading
    
    class HealthCheckHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/health':
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                health_info = {
                    "status": "online",
                    "agent_id": 4,
                    "name": "Агент №4 (Эвристика + OpenAI)",
                    "version": "4.3 (.env)",
                    "ai_provider": "Эвристика + OpenAI API резерв",
                    "prompt_version": "v2.0 - новый формат",
                    "configuration": "Environment variables (.env)",
                    "default_rules": DEFAULT_RULES,
                    "heuristic_patterns": {
                        "profanity": len(PROFANITY_PATTERNS),
                        "spam": len(SPAM_PATTERNS),
                        "discrimination": len(DISCRIMINATION_PATTERNS),
                        "flood": len(FLOOD_PATTERNS)
                    },
                    "timestamp": datetime.now().isoformat(),
                    "redis_queue": QUEUE_AGENT_4_INPUT,
                    "uptime_seconds": int(time.time())
                }
                self.wfile.write(json.dumps(health_info, ensure_ascii=False).encode())
            else:
                self.send_response(404)
                self.end_headers()
        
        def log_message(self, format, *args):
            # Подавляем логирование HTTP запросов
            pass
    
    server = HTTPServer(('localhost', AGENT_PORTS[4]), HealthCheckHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"✅ Health check сервер запущен на порту {AGENT_PORTS[4]}")

# ============================================================================
# ТОЧКА ВХОДА
# ============================================================================
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        mode = sys.argv[1]
        if mode == "test":
            # Тестирование с новым форматом v2.0
            test_cases = [
                {
                    "message": "Привет всем! Как дела?",
                    "rules": [],
                    "description": "Нормальное сообщение"
                },
                {
                    "message": "Ты дурак и идиот! Хуй тебе!",
                    "rules": DEFAULT_RULES,
                    "description": "Мат и оскорбления"
                },
                {
                    "message": "Переходи по ссылке t.me/spam_channel! Заработок от 100$ в день!",
                    "rules": DEFAULT_RULES,
                    "description": "Спам с ссылкой"
                },
                {
                    "message": "Все эти негры должны убираться отсюда!",
                    "rules": DEFAULT_RULES,
                    "description": "Расовая дискриминация"
                }
            ]
            
            for i, test_case in enumerate(test_cases, 1):
                print(f"\n--- Тест {i}: {test_case['description']} ---")
                
                test_input = {
                    "message": test_case["message"],
                    "rules": test_case["rules"],
                    "user_id": 123 + i,
                    "username": f"test_user_{i}",
                    "chat_id": -100,
                    "message_id": i,
                    "message_link": f"https://t.me/test/{i}"
                }
                
                result = moderation_agent_4(test_input)
                
                print(f"Вердикт: {'БАН' if result['ban'] else 'ОК'}")
                print(f"Уверенность: {result['confidence']*100:.0f}%")
                print(f"Метод: {result.get('method', 'N/A')}")
                print(f"Причина: {result['reason']}")
                
    else:
        # Запуск основного цикла обработки
        try:
            create_health_check_server()
            worker = Agent4Worker()
            worker.run()
        except KeyboardInterrupt:
            logger.info("Выход из программы")
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")