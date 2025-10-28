import requests
import json
import redis
import time
from typing import Dict, Any

# =============================================================================
# КОНФИГУРАЦИЯ
# =============================================================================

# GigaChat авторизация
AUTH_KEY = "YOUR_GIGACHAT_AUTH_KEY"

# Redis настройки
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0
REDIS_PASSWORD = None  # Если есть пароль, укажи здесь

# Названия очередей Redis
QUEUE_AGENT_3_INPUT = "queue:agent3:input"   # Очередь входящих сообщений для агента 3
QUEUE_AGENT_3_OUTPUT = "queue:agent3:output" # Очередь исходящих результатов от агента 3

# =============================================================================
# РАБОТА С GIGACHAT API
# =============================================================================

def get_gigachat_token(auth_key):
    """
    Получает access_token для работы с GigaChat API (действует ~30 минут).
    """
    url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    headers = {
        "Authorization": f"Basic {auth_key}"
    }
    try:
        response = requests.post(url, headers=headers, timeout=10)
        response.raise_for_status()
        token = response.json().get("access_token", "")
        return token
    except Exception as e:
        print(f"[ОШИБКА] Не удалось получить токен GigaChat: {e}")
        return None

def check_message_with_gigachat(message, rules, prompt, token):
    """
    Отправляет запрос в GigaChat API для анализа сообщения по правилам чата.
    Возвращает текстовый вывод нейросети.
    """
    url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
    rules_text = "\n".join(rules)
    system_msg = f"Правила чата:\n{rules_text}\n\n{prompt}"
    user_msg = f"Сообщение:\n{message}"
    
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
        "temperature": 0.2,  # Низкая температура для стабильности решений
        "max_tokens": 256
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        result = response.json()
        content = result["choices"][0]["message"]["content"]
        return content
    except Exception as e:
        error_msg = f"Ошибка при запросе к GigaChat: {e}"
        print(f"[ОШИБКА] {error_msg}")
        return error_msg

def parse_gigachat_response(text):
    """
    Парсит ответ GigaChat и определяет, нужен ли бан.
    Ищет ключевые слова в ответе нейросети.
    """
    text_lower = text.lower()
    
    # Ключевые слова для определения вердикта
    ban_keywords = ["вердикт: да", "нарушение обнаружено", "нарушает правила", "забанить", "блокировать"]
    no_ban_keywords = ["вердикт: нет", "нет нарушений", "не нарушает", "правила соблюдены", "нарушений не найдено"]
    
    # Определяем вердикт
    ban = False
    
    # Сначала проверяем на отсутствие нарушений (приоритет)
    if any(word in text_lower for word in no_ban_keywords):
        ban = False
    # Затем проверяем на наличие нарушений
    elif any(word in text_lower for word in ban_keywords):
        ban = True
    
    return {
        "ban": ban,
        "reason": text.strip()
    }

# =============================================================================
# АГЕНТ 3 — МОДЕРАЦИЯ
# =============================================================================

def moderation_agent_3(input_data, auth_key):
    """
    АГЕНТ 3 — Независимый модератор.
    
    Получает на вход через Redis:
        input_data = {
            "message": "текст сообщения пользователя",  # ОБЯЗАТЕЛЬНО
            "rules": ["правило 1", "правило 2", ...],   # ОБЯЗАТЕЛЬНО
            "user_id": 12345,                           # ⬅️ ВПИСЫВАЕТСЯ АГЕНТОМ 2
            "username": "@username",                    # ⬅️ ВПИСЫВАЕТСЯ АГЕНТОМ 2
            "chat_id": -1001234567890,                  # ⬅️ ВПИСЫВАЕТСЯ АГЕНТОМ 2
            "message_id": 42                            # ⬅️ ВПИСЫВАЕТСЯ АГЕНТОМ 2
        }
    
    Возвращает через Redis:
        {
            "agent_id": 3,
            "ban": True/False,
            "reason": "Вердикт агента 3 с объяснением",
            "message": "оригинальное сообщение",
            "user_id": 12345,                           # ⬅️ ПЕРЕДАЕТСЯ ОБРАТНО
            "username": "@username",                    # ⬅️ ПЕРЕДАЕТСЯ ОБРАТНО
            "chat_id": -1001234567890,                  # ⬅️ ПЕРЕДАЕТСЯ ОБРАТНО
            "message_id": 42                            # ⬅️ ПЕРЕДАЕТСЯ ОБРАТНО
        }
    """
    
    # Извлекаем данные
    message = input_data.get("message", "")
    rules = input_data.get("rules", [])
    
    # ⬇️ МЕТАДАННЫЕ ПОЛЬЗОВАТЕЛЯ (ПЕРЕДАЮТСЯ ОТ АГЕНТА 2)
    user_id = input_data.get("user_id")          # ID пользователя
    username = input_data.get("username")        # Username пользователя
    chat_id = input_data.get("chat_id")          # ID чата
    message_id = input_data.get("message_id")    # ID сообщения
    
    # Валидация входных данных
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
    
    # Получаем токен GigaChat
    token = get_gigachat_token(auth_key)
    if not token:
        return {
            "agent_id": 3,
            "ban": False,
            "reason": "Ошибка: не удалось получить токен GigaChat",
            "message": message,
            "user_id": user_id,
            "username": username,
            "chat_id": chat_id,
            "message_id": message_id
        }
    
    # Формируем промпт для агента 3
    # ВАЖНО: Агент 3 НЕ знает о вердикте агента 2 — анализирует независимо
    prompt = """Ты — строгий, но справедливый модератор Telegram-канала. 
Твоя задача: проанализировать сообщение пользователя и определить, нарушает ли оно правила чата.

ИНСТРУКЦИЯ:
1. Внимательно изучи сообщение
2. Сравни его с каждым правилом
3. Если найдено нарушение — укажи конкретное правило и объясни почему
4. Если сомневаешься — лучше не банить (презумпция невиновности)
5. Будь объективным

Ответь СТРОГО в формате: 'Вердикт: да/нет. Причина: [подробное объяснение]'"""
    
    # Получаем вердикт от GigaChat
    print(f"[АГЕНТ 3] Анализирую сообщение: {message[:50]}...")
    verdict_text = check_message_with_gigachat(message, rules, prompt, token)
    
    # Парсим ответ
    result = parse_gigachat_response(verdict_text)
    
    # Формируем выходные данные
    output = {
        "agent_id": 3,
        "ban": result["ban"],
        "reason": result["reason"],
        "message": message,
        # ⬇️ ПЕРЕДАЕМ МЕТАДАННЫЕ ОБРАТНО АГЕНТУ 2
        "user_id": user_id,
        "username": username,
        "chat_id": chat_id,
        "message_id": message_id
    }
    
    print(f"[АГЕНТ 3] Вердикт: {'БАН' if result['ban'] else 'НЕ БАНИТЬ'}")
    
    return output

# =============================================================================
# РАБОТА С REDIS
# =============================================================================

class Agent3RedisWorker:
    """
    Воркер агента 3, который слушает очередь Redis и обрабатывает сообщения.
    """
    
    def __init__(self, auth_key, redis_config=None):
        """
        Инициализация воркера.
        
        Args:
            auth_key: Ключ авторизации GigaChat
            redis_config: Настройки Redis (опционально)
        """
        self.auth_key = auth_key
        
        # Подключение к Redis
        if redis_config is None:
            redis_config = {
                "host": REDIS_HOST,
                "port": REDIS_PORT,
                "db": REDIS_DB,
                "password": REDIS_PASSWORD,
                "decode_responses": True  # Автоматическая декодировка в строки
            }
        
        try:
            self.redis_client = redis.Redis(**redis_config)
            self.redis_client.ping()  # Проверка соединения
            print(f"[АГЕНТ 3] Подключение к Redis успешно: {REDIS_HOST}:{REDIS_PORT}")
        except Exception as e:
            print(f"[ОШИБКА] Не удалось подключиться к Redis: {e}")
            raise
    
    def process_message(self, message_data):
        """
        Обрабатывает одно сообщение из очереди.
        
        Args:
            message_data: JSON-строка с данными сообщения
        
        Returns:
            dict: Результат обработки
        """
        try:
            # Парсим JSON
            input_data = json.loads(message_data)
            
            # Обрабатываем через агента 3
            result = moderation_agent_3(input_data, self.auth_key)
            
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
        """
        Отправляет результат в выходную очередь Redis.
        
        Args:
            result: dict с результатом обработки
        """
        try:
            result_json = json.dumps(result, ensure_ascii=False)
            self.redis_client.rpush(QUEUE_AGENT_3_OUTPUT, result_json)
            print(f"[АГЕНТ 3] Результат отправлен в {QUEUE_AGENT_3_OUTPUT}")
        except Exception as e:
            print(f"[ОШИБКА] Не удалось отправить результат в Redis: {e}")
    
    def run(self):
        """
        Основной цикл обработки сообщений из Redis.
        Слушает очередь QUEUE_AGENT_3_INPUT и обрабатывает сообщения.
        """
        print(f"[АГЕНТ 3] Запущен. Ожидаю сообщения из очереди: {QUEUE_AGENT_3_INPUT}")
        print(f"[АГЕНТ 3] Результаты отправляются в очередь: {QUEUE_AGENT_3_OUTPUT}")
        print("[АГЕНТ 3] Нажмите Ctrl+C для остановки\n")
        
        while True:
            try:
                # Блокирующее чтение из очереди (timeout=1 секунда)
                # BLPOP возвращает (queue_name, message) или None
                result = self.redis_client.blpop(QUEUE_AGENT_3_INPUT, timeout=1)
                
                if result is None:
                    # Таймаут, сообщений нет — продолжаем ждать
                    continue
                
                queue_name, message_data = result
                
                print(f"\n[АГЕНТ 3] Получено новое сообщение из {queue_name}")
                
                # Обрабатываем сообщение
                output = self.process_message(message_data)
                
                # Отправляем результат в выходную очередь
                self.send_result(output)
                
                print(f"[АГЕНТ 3] Обработка завершена\n")
            
            except KeyboardInterrupt:
                print("\n[АГЕНТ 3] Получен сигнал остановки (Ctrl+C)")
                break
            
            except Exception as e:
                print(f"[ОШИБКА] Неожиданная ошибка в основном цикле: {e}")
                time.sleep(1)  # Пауза перед повтором
        
        print("[АГЕНТ 3] Остановлен")

# =============================================================================
# ТЕСТИРОВАНИЕ (для отладки)
# =============================================================================

def test_agent_3_local():
    """
    Локальный тест агента 3 без Redis (для отладки).
    """
    print("=== ТЕСТ АГЕНТА 3 (БЕЗ REDIS) ===\n")
    
    # Тестовые данные
    test_input = {
        "message": "Вступайте в наш чат! 🎉 Только у нас крутые предложения!",
        "rules": [
            "Запрещена реклама сторонних сообществ",
            "Запрещён флуд и спам",
            "Запрещены оскорбления участников",
            "Запрещена нецензурная лексика"
        ],
        # ⬇️ МЕТАДАННЫЕ (ПЕРЕДАЮТСЯ ОТ АГЕНТА 2)
        "user_id": 123456789,
        "username": "@test_user",
        "chat_id": -1001234567890,
        "message_id": 42
    }
    
    # Запускаем агента 3
    result = moderation_agent_3(test_input, AUTH_KEY)
    
    # Выводим результат
    print("\n=== РЕЗУЛЬТАТ АГЕНТА 3 ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))

def test_agent_3_with_redis():
    """
    Тест агента 3 с Redis: отправляем тестовое сообщение в очередь.
    """
    print("=== ТЕСТ АГЕНТА 3 (С REDIS) ===\n")
    
    # Подключаемся к Redis
    r = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        password=REDIS_PASSWORD,
        decode_responses=True
    )
    
    # Тестовые данные
    test_input = {
        "message": "Приглашаю всех в свой новый канал @spam_channel!",
        "rules": [
            "Запрещена реклама сторонних сообществ",
            "Запрещён флуд и спам"
        ],
        "user_id": 987654321,
        "username": "@spammer",
        "chat_id": -1009876543210,
        "message_id": 100
    }
    
    # Отправляем в очередь агента 3
    test_json = json.dumps(test_input, ensure_ascii=False)
    r.rpush(QUEUE_AGENT_3_INPUT, test_json)
    
    print(f"Тестовое сообщение отправлено в очередь: {QUEUE_AGENT_3_INPUT}")
    print("Запустите агента 3 командой: python agent3.py")
    print(f"\nРезультат появится в очереди: {QUEUE_AGENT_3_OUTPUT}")

# =============================================================================
# ТОЧКА ВХОДА
# =============================================================================

if __name__ == "__main__":
    import sys
    
    # Выбираем режим работы
    if len(sys.argv) > 1:
        mode = sys.argv[1]
        
        if mode == "test":
            # Локальный тест без Redis
            test_agent_3_local()
        
        elif mode == "send-test":
            # Отправить тестовое сообщение в Redis
            test_agent_3_with_redis()
        
        else:
            print("Неизвестный режим. Используйте:")
            print("  python agent3.py         - запустить агента 3")
            print("  python agent3.py test    - локальный тест без Redis")
            print("  python agent3.py send-test - отправить тестовое сообщение")
    
    else:
        # Основной режим: запуск воркера
        worker = Agent3RedisWorker(auth_key=AUTH_KEY)
        worker.run()
