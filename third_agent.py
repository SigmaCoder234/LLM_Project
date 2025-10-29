import requests
import json
import redis
import time
from typing import Dict, Any
import urllib3

# Отключаем warning SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# =============================================================================
# КОНФИГУРАЦИЯ
# =============================================================================

# Access Token для GigaChat API
ACCESS_TOKEN = "eyJjdHkiOiJqd3QiLCJlbmMiOiJBMjU2Q0JDLUhTNTEyIiwiYWxnIjoiUlNBLU9BRVAtMjU2In0.wESCCGpAKhedFyZu53Xe8StqCwL22Wv4o0SWl_kRARYe1ReHdpsESOCx8wjyI-mKMyrXT-_GWdebs0xSBR3ocZFEeK-Nh6DURnxxHoVDKABhHaAKarA_MNpjU1OO1YSV69Pxu2qb1kxn4KZZvbiDl1sDi-nUt0J9fViU9I38fdGEwTJkCxU6b9zhcK3AHtKIQEA3KbHRYCb0w5J4xYc40GZeLvlSg41YqqGAQDX0SnefcxxVJDkdL4PwINiGoSpQMUHlFJ-OnHdCMNF2aJHyZZxmh9SDQoEhlZpxw72Q4rQz9gDr215MPIB1a8ujLdJ3_qagzauRAaJSVH-2Rd3E5Q.K5PFOlabJf9FehG7e8xl9w.G_JyR9VYnvrzexaE0JJV0nwN0ERnUzmlyYopyPNyAkGyvNneb85gnjaVvueWIJyeVw1FCSFtXD_zGwpTRdMVCCLGbVG-J4yesQF3M37tmQRHv1bnmX3c5bn2nRx1dG0V9UYhJlJPu6z99foBPN3ql_OoLdVDkezePvJRx2DmRZ5gF1mnZJ_4G377XRPbFIF9VbOdjKOoZmFH9TFp1Yf1g1piY_S8kQkftjcRKfkH_uTtnxtND52m5MqKt5MUuMRZkDUFs_xcfpBCM62_HkrvT4SH25YcocuVlG_7DKQNG6DIQL3kVPzIGgHYgkajJ5NzDfzfLrfgzTQWhIv1wv3Gt-JonAESyVrdSJM8bMZkJwQ4bYJSYs-wTv_QHGkdmLgt8MI56p35rtWgh9UqFORqvWebuNdRCmfIeFUDMXAtWPyHd6rP0gwLFKND0Hs2YB8vDd5znT-MmoIj4iOHJGmQoDAx3hN1Ix7_EAeL_xTbVB5W9mUlYwbphHL94h1OY9BEEDPT2urePVrt6r83d7poVATDbande88IvFbIIzLcCaOtoi6ACIPOdMKtrFWZclBf0PT8JIDOzxQpmcVVPbRLX79_YUW0OIhVzSBm4swfYcUUf6c7fz-EP-mozxkuVbeyf6lh64VRKQpSviSXlye-ypBRZgW4JWBSDl2TLiX91K_GpuVTvr7ujvVsq56OYI3u5Oy3mOnFbF1F5vnpEmERTWPnAF98f1Cuwv_cglIm0dQ.Ibhh5i_xa9wc_wfJlqv9lm8hED2eHyzewglZAJ8JKZQ"

AUTH_TOKEN = "ODE5YTgxODUtMzY2MC00NDM5LTgxZWItYzU1NjVhODgwOGVkOmE5NzBiNjJmLWNkYzMtNDM2Yy1iODA5LTc2YjhmZTI4YzBhMQ=="

# Redis настройки
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0
REDIS_PASSWORD = None

QUEUE_AGENT_3_INPUT = "queue:agent3:input"
QUEUE_AGENT_3_OUTPUT = "queue:agent3:output"

# =============================================================================
# СПИСОК НЕЦЕНЗУРНЫХ СЛОВ (для дополнительной проверки)
# =============================================================================

PROFANITY_WORDS = [
    "сука", "чурка", "дурак", "идиот", "тупой", "долбоеб", "мудак", 
    "хуй", "пизд", "ебан", "бля", "гандон", "уебок", "чмо", "дебил",
    "даун", "урод", "мразь", "быдло", "козел", "свинья", "сволочь"
]

DISCRIMINATION_WORDS = [
    "чурка", "хохол", "москаль", "жид", "негр", "азиат",
    "узкоглазый", "черножопый", "чучмек", "чучмек"
]

# =============================================================================
# РАБОТА С GIGACHAT API
# =============================================================================

def check_profanity_simple(message):
    """
    Простая проверка на нецензурные слова (дополнительная фильтрация).
    Возвращает True если найдена нецензурщина.
    """
    message_lower = message.lower()
    
    for word in PROFANITY_WORDS + DISCRIMINATION_WORDS:
        if word in message_lower:
            return True, f"Обнаружено запрещённое слово: '{word}'"
    
    return False, ""

def check_message_with_gigachat(message, rules, prompt, token):
    """
    Отправляет запрос в GigaChat API для анализа сообщения.
    """
    url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
    rules_text = "\n".join([f"{i+1}. {rule}" for i, rule in enumerate(rules)])
    
    system_msg = f"""Ты — строгий модератор Telegram-канала.

ПРАВИЛА ЧАТА:
{rules_text}

{prompt}"""
    
    user_msg = f"Сообщение пользователя:\n\"{message}\""
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": "GigaChat",
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ],
        "temperature": 0.1,  # ⬅️ Ещё НИЖЕ для более строгих решений
        "max_tokens": 300
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=30, verify=False)
        response.raise_for_status()
        result = response.json()
        content = result["choices"][0]["message"]["content"]
        return content
    except Exception as e:
        error_msg = f"Ошибка при запросе к GigaChat: {e}"
        print(f"[ОШИБКА] {error_msg}")
        return error_msg

def parse_gigachat_response(text, message):
    """
    Парсит ответ GigaChat и определяет, нужен ли бан.
    Добавлена дополнительная логика для строгости.
    """
    text_lower = text.lower()
    
    # Сначала проверяем простым поиском по словам
    has_profanity, profanity_reason = check_profanity_simple(message)
    if has_profanity:
        return {
            "ban": True,
            "reason": f"Вердикт: да. {profanity_reason} (Автоматическая фильтрация)"
        }
    
    # Ключевые слова для BAN
    ban_keywords = [
        "вердикт: да", "вердикт:да", "вердикт да",
        "нарушение", "нарушает", "забанить", "блокировать",
        "оскорбление", "мат", "нецензурн", "дискриминация"
    ]
    
    # Ключевые слова для НЕТ BAN
    no_ban_keywords = [
        "вердикт: нет", "вердикт:нет", "вердикт нет",
        "нет нарушений", "не нарушает", "правила соблюдены",
        "нарушений не", "не обнаружено"
    ]
    
    # Проверяем ответ GigaChat
    has_ban_words = any(word in text_lower for word in ban_keywords)
    has_no_ban_words = any(word in text_lower for word in no_ban_keywords)
    
    # Логика принятия решения
    if has_no_ban_words and not has_ban_words:
        ban = False
    elif has_ban_words:
        ban = True
    else:
        # Если непонятно — по умолчанию НЕ БАНИТЬ (презумпция невиновности)
        ban = False
    
    return {
        "ban": ban,
        "reason": text.strip()
    }

# =============================================================================
# АГЕНТ 3 — МОДЕРАЦИЯ
# =============================================================================

def moderation_agent_3(input_data):
    """
    АГЕНТ 3 — Независимый модератор с усиленной проверкой.
    """
    
    message = input_data.get("message", "")
    rules = input_data.get("rules", [])
    
    user_id = input_data.get("user_id")
    username = input_data.get("username")
    chat_id = input_data.get("chat_id")
    message_id = input_data.get("message_id")
    
    if not message:
        return {
            "agent_id": 3,
            "ban": False,
            "reason": "Ошибка: пустое сообщение",
            "message": "",
            "user_id": user_id,
            "username": username,
            "chat_id": chat_id,
            "message_id": message_id
        }
    
    if not rules:
        return {
            "agent_id": 3,
            "ban": False,
            "reason": "Ошибка: правила не переданы",
            "message": message,
            "user_id": user_id,
            "username": username,
            "chat_id": chat_id,
            "message_id": message_id
        }
    
    token = ACCESS_TOKEN
    
    if not token:
        return {
            "agent_id": 3,
            "ban": False,
            "reason": "Ошибка: отсутствует access token",
            "message": message,
            "user_id": user_id,
            "username": username,
            "chat_id": chat_id,
            "message_id": message_id
        }
    
    # ⬇️ УЛУЧШЕННЫЙ ПРОМПТ
    prompt = """
ТВОЯ ЗАДАЧА:
Проанализируй сообщение и определи, нарушает ли оно ЛЮБОЕ из правил выше.

КРИТЕРИИ ПРОВЕРКИ:
✓ Нецензурные слова, маты, оскорбления
✓ Дискриминация по национальности, расе, религии
✓ Реклама сторонних каналов/групп
✓ Спам, флуд
✓ Агрессия, угрозы

ИНСТРУКЦИИ:
1. Если в сообщении есть ХОТЯ БЫ ОДНО нарушение — вердикт "да"
2. Будь СТРОГИМ: даже завуалированные оскорбления — это нарушение
3. Если сомневаешься — лучше забанить (безопасность чата важнее)

ФОРМАТ ОТВЕТА (строго):
Вердикт: да/нет
Причина: [конкретное объяснение]

НАЧИНАЙ АНАЛИЗ:"""
    
    print(f"[АГЕНТ 3] Анализирую сообщение: {message[:50]}...")
    
    # Получаем вердикт от GigaChat
    verdict_text = check_message_with_gigachat(message, rules, prompt, token)
    
    print(f"[АГЕНТ 3] Ответ GigaChat: {verdict_text[:100]}...")
    
    # Парсим ответ с дополнительной проверкой
    result = parse_gigachat_response(verdict_text, message)
    
    output = {
        "agent_id": 3,
        "ban": result["ban"],
        "reason": result["reason"],
        "message": message,
        "user_id": user_id,
        "username": username,
        "chat_id": chat_id,
        "message_id": message_id
    }
    
    print(f"[АГЕНТ 3] Вердикт: {'БАН ⛔' if result['ban'] else 'ОК ✅'}")
    
    return output

# =============================================================================
# РАБОТА С REDIS
# =============================================================================

class Agent3RedisWorker:
    
    def __init__(self, redis_config=None):
        if redis_config is None:
            redis_config = {
                "host": REDIS_HOST,
                "port": REDIS_PORT,
                "db": REDIS_DB,
                "password": REDIS_PASSWORD,
                "decode_responses": True
            }
        
        try:
            self.redis_client = redis.Redis(**redis_config)
            self.redis_client.ping()
            print(f"[АГЕНТ 3] ✅ Подключение к Redis успешно: {REDIS_HOST}:{REDIS_PORT}")
        except Exception as e:
            print(f"[ОШИБКА] Не удалось подключиться к Redis: {e}")
            raise
    
    def process_message(self, message_data):
        try:
            input_data = json.loads(message_data)
            result = moderation_agent_3(input_data)
            return result
        
        except json.JSONDecodeError as e:
            print(f"[ОШИБКА] Невалидный JSON: {e}")
            return {
                "agent_id": 3,
                "ban": False,
                "reason": f"Ошибка парсинга данных: {e}",
                "message": ""
            }
        except Exception as e:
            print(f"[ОШИБКА] Ошибка обработки сообщения: {e}")
            return {
                "agent_id": 3,
                "ban": False,
                "reason": f"Внутренняя ошибка агента 3: {e}",
                "message": ""
            }
    
    def send_result(self, result):
        try:
            result_json = json.dumps(result, ensure_ascii=False)
            self.redis_client.rpush(QUEUE_AGENT_3_OUTPUT, result_json)
            print(f"[АГЕНТ 3] ✅ Результат отправлен")
        except Exception as e:
            print(f"[ОШИБКА] Не удалось отправить результат: {e}")
    
    def run(self):
        print(f"[АГЕНТ 3] ✅ Запущен. Ожидаю сообщения из: {QUEUE_AGENT_3_INPUT}")
        print(f"[АГЕНТ 3] Результаты в: {QUEUE_AGENT_3_OUTPUT}")
        print("[АГЕНТ 3] Нажмите Ctrl+C для остановки\n")
        
        while True:
            try:
                result = self.redis_client.blpop(QUEUE_AGENT_3_INPUT, timeout=1)
                
                if result is None:
                    continue
                
                queue_name, message_data = result
                
                print(f"\n[АГЕНТ 3] Получено сообщение из {queue_name}")
                
                output = self.process_message(message_data)
                self.send_result(output)
                
                print(f"[АГЕНТ 3] Обработка завершена\n")
            
            except KeyboardInterrupt:
                print("\n[АГЕНТ 3] Остановлен (Ctrl+C)")
                break
            
            except Exception as e:
                print(f"[ОШИБКА] {e}")
                time.sleep(1)
        
        print("[АГЕНТ 3] Остановлен")

# =============================================================================
# ТОЧКА ВХОДА
# =============================================================================

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        mode = sys.argv[1]
        
        if mode == "test":
            test_input = {
                "message": "сука чурка",
                "rules": [
                    "Запрещена реклама",
                    "Запрещены нецензурные выражения",
                    "Запрещена дискриминация"
                ],
                "user_id": 123,
                "username": "@test",
                "chat_id": -100,
                "message_id": 1
            }
            result = moderation_agent_3(test_input)
            print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        worker = Agent3RedisWorker()
        worker.run()

