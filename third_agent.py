# -*- coding: utf-8 -*-
"""
АГЕНТ №3 с GigaChat - Модерация контента (ГОТОВЫЙ ACCESS TOKEN)
"""
import requests
import json
import redis
import time
from typing import Dict, Any

# === НАСТРОЙКИ (ГОТОВЫЙ ACCESS TOKEN) ===
# ГигаЧат настройки - ГОТОВЫЙ ACCESS TOKEN
from token inport TOKEN
GIGACHAT_ACCESS_TOKEN = TOKEN
# Redis настройки
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0
REDIS_PASSWORD = None  # None если пароль не установлен

# Redis очереди
QUEUE_AGENT3_INPUT = "queue:agent3_input"  # Очередь входящих сообщений для Агента 3
QUEUE_AGENT3_OUTPUT = "queue:agent3_output"  # Очередь исходящих сообщений от Агента 3

# === GIGACHAT FUNCTIONS (ГОТОВЫЙ ACCESS TOKEN) ===
def check_message_with_gigachat(message, rules, prompt, access_token):
    """
    Проверка сообщения через GigaChat API с готовым Access Token.
    Анализирует содержимое сообщения на соответствие правилам чата.
    
    Args:
        message: Текст сообщения для проверки
        rules: Список правил чата
        prompt: Промпт для анализа
        access_token: Access Token для GigaChat API
    
    Returns:
        str: Ответ от GigaChat или сообщение об ошибке
    """
    url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
    
    rules_text = "\n".join(rules)
    system_msg = f"{rules_text}\n{prompt}"
    user_msg = f"{message}"
    
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    
    data = {
        'model': 'GigaChat',
        'messages': [
            {'role': 'system', 'content': system_msg},
            {'role': 'user', 'content': user_msg}
        ],
        'temperature': 0.2,
        'max_tokens': 256
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, verify=False, timeout=30)
        response.raise_for_status()
        result = response.json()
        content = result['choices'][0]['message']['content']
        return content
    except Exception as e:
        error_msg = f"❌ Ошибка GigaChat API: {e}"
        print(error_msg)
        return error_msg

def parse_gigachat_response(text):
    """
    Парсинг ответа GigaChat для определения нарушений.
    Возвращает решение о блокировке и причину.
    """
    text_lower = text.lower()
    
    # Ключевые слова для блокировки
    ban_keywords = ['запретить', 'заблокировать', 'бан', 'блокировать', 'нарушение']
    no_ban_keywords = ['разрешить', 'допустимо', 'нормально', 'можно']
    
    # Анализ ответа
    ban = False
    
    # Проверяем на слова "не блокировать"
    if any(word in text_lower for word in no_ban_keywords):
        ban = False
    # Проверяем на слова "блокировать"
    elif any(word in text_lower for word in ban_keywords):
        ban = True
    
    return {'ban': ban, 'reason': text.strip()}

def test_access_token(access_token):
    """
    Тестирование Access Token
    
    Args:
        access_token: Access Token для проверки
    
    Returns:
        bool: True если токен работает
    """
    test_url = "https://gigachat.devices.sberbank.ru/api/v1/models"
    
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json'
    }
    
    try:
        print(f"🧪 Тестируем готовый Access Token...")
        
        response = requests.get(test_url, headers=headers, verify=False, timeout=15)
        
        if response.status_code == 200:
            models = response.json()
            print(f"✅ Access Token работает! Доступно моделей: {len(models.get('data', []))}")
            return True
        else:
            print(f"❌ Access Token не работает. Статус: {response.status_code}")
            print(f"📄 Ответ: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Ошибка тестирования токена: {e}")
        return False

def moderation_agent3(input_data, access_token: str):
    """
    Функция Агента 3 для модерации сообщений с готовым Access Token.
    
    Args:
        input_data (от Агента 2): {
            'message': 'текст сообщения',
            'rules': ['правило 1', 'правило 2', ...],
            'user_id': 12345,  # ID пользователя
            'username': 'username',  # Имя пользователя
            'chat_id': -1001234567890,  # ID чата
            'message_id': 42  # ID сообщения
        }
        access_token: Готовый Access Token для GigaChat API
    
    Returns:
        dict: {
            'agent_id': 3,
            'ban': True/False,
            'reason': 'причина решения от Агента 3',
            'message': 'исходное сообщение',
            'user_id': 12345,
            'username': 'username',
            'chat_id': -1001234567890,
            'message_id': 42
        }
    """
    
    # Извлекаем данные
    message = input_data.get('message', '')
    rules = input_data.get('rules', [])
    
    # Извлекаем метаданные
    user_id = input_data.get('user_id')
    username = input_data.get('username')
    chat_id = input_data.get('chat_id')
    message_id = input_data.get('message_id')
    
    # Базовые проверки
    if not message:
        return {
            'agent_id': 3,
            'ban': False,
            'reason': 'Пустое сообщение',
            'message': '',
            'user_id': user_id,
            'username': username,
            'chat_id': chat_id,
            'message_id': message_id
        }
    
    if not rules:
        return {
            'agent_id': 3,
            'ban': False,
            'reason': 'Нет правил для проверки',
            'message': message,
            'user_id': user_id,
            'username': username,
            'chat_id': chat_id,
            'message_id': message_id
        }
    
    # Промпт для GigaChat
    prompt = """
    Ты — модератор Telegram-чата. Проанализируй сообщение на нарушение правил.
    Ответь одним словом: "запретить" если сообщение нарушает правила, "разрешить" если нет.
    1. Если есть реклама, спам, ссылки на подозрительные ресурсы - запретить
    2. Если есть оскорбления, мат, токсичность - запретить  
    3. Если есть призывы к нарушению закона - запретить
    4. Если сообщение нормальное - разрешить
    5. В сомнительных случаях лучше разрешить.
    """
    
    # Логируем начало обработки Агентом 3
    print(f"🔍 Агент 3 обрабатывает: '{message[:50]}...' с готовым токеном")
    
    # Проверяем сообщение через GigaChat
    verdict_text = check_message_with_gigachat(message, rules, prompt, access_token)
    
    # Парсим ответ GigaChat
    result = parse_gigachat_response(verdict_text)
    
    # Формируем итоговый ответ
    output = {
        'agent_id': 3,
        'ban': result['ban'],
        'reason': result['reason'],
        'message': message,
        # Метаданные
        'user_id': user_id,
        'username': username,
        'chat_id': chat_id,
        'message_id': message_id
    }
    
    print(f"✅ Агент 3: {'БЛОКИРОВАТЬ' if result['ban'] else 'РАЗРЕШИТЬ'}")
    return output

class Agent3RedisWorker:
    """
    Класс для работы Агента 3 с Redis очередями.
    """
    
    def __init__(self, access_token: str, redis_config=None):
        """
        Args:
            access_token: Готовый Access Token для ГигаЧата
            redis_config: Конфигурация для подключения к Redis
        """
        self.access_token = access_token
        
        # Настройки Redis
        if redis_config is None:
            redis_config = {
                'host': REDIS_HOST,
                'port': REDIS_PORT,
                'db': REDIS_DB,
                'password': REDIS_PASSWORD,
                'decode_responses': True
            }
        
        try:
            self.redis_client = redis.Redis(**redis_config)
            self.redis_client.ping()
            print(f"✅ Агент 3 подключен к Redis {REDIS_HOST}:{REDIS_PORT}")
        except Exception as e:
            print(f"❌ Ошибка подключения к Redis: {e}")
            raise
    
    def process_message(self, message_data):
        """
        Обработка одного сообщения.
        
        Args:
            message_data: JSON-строка с данными сообщения
        
        Returns:
            dict: Результат обработки
        """
        try:
            # Парсим данные из Redis
            input_data = json.loads(message_data)
            
            # Обрабатываем через модерацию
            result = moderation_agent3(input_data, self.access_token)
            return result
            
        except json.JSONDecodeError as e:
            print(f"❌ Ошибка парсинга JSON: {e}")
            return {
                'agent_id': 3,
                'ban': False,
                'reason': f'Ошибка JSON: {e}',
                'message': ''
            }
        except Exception as e:
            print(f"❌ Ошибка обработки: {e}")
            return {
                'agent_id': 3,
                'ban': False,
                'reason': f'Ошибка Агента 3: {e}',
                'message': ''
            }
    
    def send_result(self, result):
        """
        Отправка результата в Redis очередь выходных сообщений.
        
        Args:
            result: dict с результатом анализа
        """
        try:
            result_json = json.dumps(result, ensure_ascii=False)
            self.redis_client.rpush(QUEUE_AGENT3_OUTPUT, result_json)
            print(f"📤 Агент 3 отправил результат в {QUEUE_AGENT3_OUTPUT}")
        except Exception as e:
            print(f"❌ Ошибка отправки в Redis: {e}")
    
    def run(self):
        """
        Основной цикл работы Агента 3.
        Слушает очередь QUEUE_AGENT3_INPUT и обрабатывает сообщения.
        """
        print(f"🚀 Агент 3 запущен с готовым Access Token.")
        print(f"👂 Слушаем очередь: {QUEUE_AGENT3_INPUT}")
        print(f"📤 Отправляем результаты в: {QUEUE_AGENT3_OUTPUT}")
        print("⏹️  Остановка: Ctrl+C")
        
        while True:
            try:
                # Блокирующее чтение из очереди (timeout 1 сек)
                result = self.redis_client.blpop(QUEUE_AGENT3_INPUT, timeout=1)
                
                if result is None:
                    # Если BLPOP вернул None, значит таймаут истек
                    continue
                    
                queue_name, message_data = result
                print(f"📨 Агент 3 получил сообщение из {queue_name}")
                
                # Обрабатываем сообщение
                output = self.process_message(message_data)
                
                # Отправляем результат
                self.send_result(output)
                
                print(f"✅ Агент 3 завершил обработку")
                
            except KeyboardInterrupt:
                print("\n🛑 Агент 3 остановлен (Ctrl+C)")
                break
            except Exception as e:
                print(f"❌ Ошибка: {e}")
                time.sleep(1)
        
        print("👋 Агент 3 завершил работу")

def test_agent3_local():
    """Тест работы Агента 3 без Redis."""
    print("🧪 Тестирование Агента 3 БЕЗ REDIS")
    
    # Тестовые данные
    test_input = {
        'message': 'Купите дешевые айфоны! Скидки!!!',
        'rules': ['Запрещена реклама', 'Запрещен спам', 'Запрещены ссылки'],
        'user_id': 123456789,
        'username': 'testuser',
        'chat_id': -1001234567890,
        'message_id': 42
    }
    
    # Тестируем Агент 3
    result = moderation_agent3(test_input, GIGACHAT_ACCESS_TOKEN)
    
    # Выводим результат
    print("📊 Результат Агента 3:")
    print(json.dumps(result, ensure_ascii=False, indent=2))

def test_agent3_with_redis():
    """Тест работы Агента 3 С Redis."""
    print("🧪 Тестирование Агента 3 С REDIS")
    
    # Подключаемся к Redis
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, password=REDIS_PASSWORD, decode_responses=True)
    
    # Тестовые данные
    test_input = {
        'message': 'Привет всем! Как дела?',
        'rules': ['Запрещена реклама', 'Запрещен спам'],
        'user_id': 987654321,
        'username': 'normaluser',
        'chat_id': -1009876543210,
        'message_id': 100
    }
    
    # Отправляем в очередь
    test_json = json.dumps(test_input, ensure_ascii=False)
    r.rpush(QUEUE_AGENT3_INPUT, test_json)
    print(f"📤 Тестовое сообщение отправлено в {QUEUE_AGENT3_INPUT}")
    
    print("🔄 Теперь запустите: python third_agent.py")
    print(f"📥 Результат будет в очереди: {QUEUE_AGENT3_OUTPUT}")

if __name__ == "__main__":
    import sys
    
    print("=" * 60)
    print("🔧 АГЕНТ №3 - ГОТОВЫЙ ACCESS TOKEN")
    print("=" * 60)
    print("🔑 Access Token встроен в код")
    print(f"📏 Длина токена: {len(GIGACHAT_ACCESS_TOKEN)} символов")
    print("🧪 Поддерживает проверку из Telegram бота")
    print()
    
    # Проверяем токен
    if not test_access_token(GIGACHAT_ACCESS_TOKEN):
        print("❌ Access Token не работает! Проверьте токен.")
        exit(1)
    
    # Проверяем аргументы командной строки
    if len(sys.argv) > 1:
        mode = sys.argv[1]
        
        if mode == "test":
            # Локальный тест без Redis
            test_agent3_local()
        elif mode == "send-test":
            # Отправка тестового сообщения в Redis
            test_agent3_with_redis()
        else:
            print("❓ Неизвестный режим.")
            print("python third_agent.py - запуск Агента 3")
            print("python third_agent.py test - локальный тест без Redis")  
            print("python third_agent.py send-test - отправка тестового сообщения в Redis")
    else:
        # Основной режим работы с Redis
        print("🚀 Запускаем Агент 3 с готовым Access Token...")
        print("=" * 60)
        worker = Agent3RedisWorker(access_token=GIGACHAT_ACCESS_TOKEN)
        worker.run()
