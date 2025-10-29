# -*- coding: utf-8 -*-
"""
АГЕНТ №4 - Альтернативная модерация (ГОТОВЫЙ ACCESS TOKEN)
Агент №4 работает параллельно с Агентом №3, предоставляя второе мнение.
- Агент №3 использует GigaChat API с готовым Access Token
- Агент №4 использует эвристический анализ и может дублировать с OpenAI API
"""

import requests
import json
import redis
import time
import re
from typing import Dict, Any, List, Optional

# === НАСТРОЙКИ (ГОТОВЫЙ ACCESS TOKEN) ===
# OpenAI API настройки - можете использовать вместо эвристики
OPENAI_API_KEY = "YOUR_OPENAI_API_KEY"  # Замените на ваш OpenAI API ключ
USE_OPENAI = False  # True для использования OpenAI вместо эвристики

# ГигаЧат настройки - ГОТОВЫЙ ACCESS TOKEN (если понадобится)
from token import TOKEN
GIGACHAT_ACCESS_TOKEN = TOKEN
# Redis настройки
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0
REDIS_PASSWORD = None  # None если пароль не установлен

# Redis очереди
QUEUE_AGENT4_INPUT = "queue:agent4_input"  # Очередь входящих сообщений для Агента 4
QUEUE_AGENT4_OUTPUT = "queue:agent4_output"  # Очередь исходящих сообщений от Агента 4

# === ЭВРИСТИЧЕСКИЙ АНАЛИЗАТОР ===
class HeuristicAnalyzer:
    """
    Эвристический анализатор для Агента 4.
    Использует регулярные выражения и простые правила для анализа сообщений.
    Работает быстрее чем AI, но менее точно.
    """
    
    def __init__(self):
        # Паттерны для обнаружения спама
        self.spam_patterns = [
            r'дешев[оые]',  # дешево, дешевые
            r'скидк[аи]',   # скидка, скидки  
            r'купи[тье]',   # купить, купите
            r'продаж[аи]',  # продажа, продажи
            r'реклам[аы]',  # реклама, рекламы
            r'https?://',   # ссылки http/https
            r't\.me/',      # Telegram ссылки
            r'заработ[ак]', # заработок, заработать
            r'бесплатн[оы]', # бесплатно, бесплатный
            r'акци[яи]',    # акция, акции
        ]
        
        # Паттерны для обнаружения оскорблений
        self.insult_patterns = [
            r'идиот',
            r'дурак',
            r'тупой',
            r'урод',
            r'козёл',
            r'свинья',
        ]
        
        # Паттерны для обнаружения мата (базовые)
        self.profanity_patterns = [
            r'бля[дь]?',
            r'х[уy]й',
            r'п[иеё]зд',
            r'[её]б[ауе]',
        ]
        
        # Паттерны для обнаружения флуда
        self.flood_indicators = [
            r'(.)\1{4,}',        # Повторение символа 5+ раз подряд
            r'[!?]{3,}',         # Много восклицательных/вопросительных знаков
            r'[A-ZА-Я]{10,}',    # Много заглавных букв подряд
            r'(.{1,3})\1{3,}',   # Повторение коротких фрагментов
        ]
    
    def check_spam(self, message: str) -> tuple:
        """Проверка на спам - возвращает (True/False, причина)"""
        message_lower = message.lower()
        
        for pattern in self.spam_patterns:
            if re.search(pattern, message_lower):
                return True, f"Обнаружен спам паттерн: {pattern}"
        
        # Проверяем количество ссылок
        links_count = len(re.findall(r'https?://|t\.me/', message_lower))
        if links_count > 2:
            return True, f"Слишком много ссылок: {links_count}. Возможно спам"
        
        # Проверяем упоминания пользователей
        mentions = re.findall(r'@\w+', message)
        if len(mentions) > 3:
            return True, f"Слишком много упоминаний: {len(mentions)}. Возможно спам"
        
        return False, ""
    
    def check_insults(self, message: str) -> tuple:
        """Проверка на оскорбления - возвращает (True/False, причина)"""
        message_lower = message.lower()
        
        for pattern in self.insult_patterns:
            match = re.search(pattern, message_lower)
            if match:
                return True, f"Обнаружено оскорбление: {match.group()}"
        
        return False, ""
    
    def check_profanity(self, message: str) -> tuple:
        """Проверка на мат - возвращает (True/False, причина)"""
        message_lower = message.lower()
        
        for pattern in self.profanity_patterns:
            match = re.search(pattern, message_lower)
            if match:
                return True, f"Обнаружена ненормативная лексика: {match.group()}"
        
        return False, ""
    
    def check_flood(self, message: str) -> tuple:
        """Проверка на флуд - возвращает (True/False, причина)"""
        for pattern in self.flood_indicators:
            match = re.search(pattern, message)
            if match:
                return True, f"Обнаружен флуд: {match.group()}"
        
        # Проверяем общую длину сообщения  
        if len(message) < 2:
            return True, "Слишком короткое сообщение"
        
        if len(message) > 3000:
            return True, "Слишком длинное сообщение - возможно флуд"
        
        return False, ""
    
    def check_rules_match(self, message: str, rules: List[str]) -> tuple:
        """
        Проверка соответствия правилам чата.
        Возвращает (есть_нарушения, список_нарушений)
        """
        violations = []
        
        # Проверяем каждое правило
        for rule in rules:
            rule_lower = rule.lower()
            
            # Если правило содержит слова о спаме
            if any(keyword in rule_lower for keyword in ['спам', 'реклам', 'ссылк']):
                is_spam, reason = self.check_spam(message)
                if is_spam:
                    violations.append(f"Правило '{rule}': {reason}")
            
            # Если правило содержит слова об оскорблениях
            if any(keyword in rule_lower for keyword in ['оскорбл', 'мат', 'ругат']):
                is_insult, reason = self.check_insults(message)
                if is_insult:
                    violations.append(f"Правило '{rule}': {reason}")
            
            # Если правило содержит слова о мате
            if any(keyword in rule_lower for keyword in ['мат', 'ненормат', 'нецензур']):
                is_profane, reason = self.check_profanity(message)
                if is_profane:
                    violations.append(f"Правило '{rule}': {reason}")
            
            # Если правило содержит слова о флуде
            if any(keyword in rule_lower for keyword in ['флуд', 'спам']):
                is_flood, reason = self.check_flood(message)
                if is_flood:
                    violations.append(f"Правило '{rule}': {reason}")
        
        if violations:
            return True, ". ".join(violations)
        return False, "Сообщение соответствует правилам."
    
    def analyze(self, message: str, rules: List[str]) -> Dict[str, Any]:
        """
        Основной метод анализа сообщения.
        
        Returns:
            dict: {'ban': bool, 'reason': str}
        """
        # Базовая проверка
        if not message or not message.strip():
            return {'ban': False, 'reason': 'Пустое сообщение - пропускаем'}
        
        # Проверяем на соответствие правилам
        has_violation, reason = self.check_rules_match(message, rules)
        
        return {
            'ban': has_violation,
            'reason': reason
        }

# === OpenAI API FUNCTION (альтернатива GigaChat) ===
def check_message_with_openai(message: str, rules: List[str], api_key: str) -> Dict[str, Any]:
    """
    Проверка сообщения через OpenAI API.
    Альтернатива GigaChat для Агента 4.
    """
    url = "https://api.openai.com/v1/chat/completions"
    
    rules_text = "\n".join([f"{i+1}. {rule}" for i, rule in enumerate(rules)])
    system_msg = f"""Ты — AI модератор Telegram-чата. Анализируй сообщения на нарушения правил.
    
Правила чата:
{rules_text}

Ответь коротко: разреши или запрети сообщение, и укажи причину."""
    
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }
    
    data = {
        'model': 'gpt-3.5-turbo',
        'messages': [
            {'role': 'system', 'content': system_msg},
            {'role': 'user', 'content': f"Сообщение: {message}"}
        ],
        'temperature': 0.3,
        'max_tokens': 256
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        result = response.json()
        content = result['choices'][0]['message']['content']
        
        # Парсим ответ OpenAI
        content_lower = content.lower()
        ban = any(word in content_lower for word in ['запрет', 'блок', 'нарушен'])
        
        return {'ban': ban, 'reason': content.strip()}
        
    except Exception as e:
        error_msg = f"❌ Ошибка OpenAI API: {e}"
        print(error_msg)
        return {'ban': False, 'reason': error_msg}

# === MAIN AGENT 4 FUNCTION ===
def moderation_agent4(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Функция Агента 4 для альтернативной модерации.
    
    Входные данные (от Агента 3):
    {
        'message': 'текст сообщения',
        'rules': ['правило 1', 'правило 2', ...],
        'user_id': 12345,  # ID пользователя
        'username': 'username',  # Имя пользователя  
        'chat_id': -1001234567890,  # ID чата
        'message_id': 42  # ID сообщения
    }
    
    Возвращает (в Redis):
    {
        'agent_id': 4,
        'ban': True/False,
        'reason': 'причина решения от Агента 4',
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
            'agent_id': 4,
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
            'agent_id': 4,
            'ban': False,
            'reason': 'Нет правил для проверки',
            'message': message,
            'user_id': user_id,
            'username': username,
            'chat_id': chat_id,
            'message_id': message_id
        }
    
    print(f"🔍 Агент 4 обрабатывает: '{message[:50]}...'")
    
    # Выбираем метод анализа
    if USE_OPENAI and OPENAI_API_KEY != "YOUR_OPENAI_API_KEY":
        # Используем OpenAI API
        print("🧠 Агент 4 анализирует через OpenAI API")
        result = check_message_with_openai(message, rules, OPENAI_API_KEY)
    else:
        # Используем эвристический анализ (без OpenAI API)
        print("🔧 Агент 4 использует эвристический анализ")
        analyzer = HeuristicAnalyzer()
        result = analyzer.analyze(message, rules)
    
    # Формируем итоговый ответ
    output = {
        'agent_id': 4,
        'ban': result['ban'],
        'reason': result['reason'],
        'message': message,
        # Метаданные
        'user_id': user_id,
        'username': username,
        'chat_id': chat_id,
        'message_id': message_id
    }
    
    print(f"✅ Агент 4: {'БЛОКИРОВАТЬ' if result['ban'] else 'РАЗРЕШИТЬ'}")
    return output

class Agent4RedisWorker:
    """
    Класс для работы Агента 4 с Redis очередями.
    Аналогичен Agent3RedisWorker, но для Агента 4.
    """
    
    def __init__(self, redis_config: Optional[Dict] = None):
        """
        Args:
            redis_config: Конфигурация для подключения к Redis
        """
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
            print(f"✅ Агент 4 подключен к Redis {REDIS_HOST}:{REDIS_PORT}")
        except Exception as e:
            print(f"❌ Ошибка подключения к Redis: {e}")
            raise
    
    def process_message(self, message_data: str) -> Dict[str, Any]:
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
            result = moderation_agent4(input_data)
            return result
            
        except json.JSONDecodeError as e:
            print(f"❌ Ошибка парсинга JSON: {e}")
            return {
                'agent_id': 4,
                'ban': False,
                'reason': f'Ошибка JSON: {e}',
                'message': ''
            }
        except Exception as e:
            print(f"❌ Ошибка обработки: {e}")
            return {
                'agent_id': 4,
                'ban': False,
                'reason': f'Ошибка Агента 4: {e}',
                'message': ''
            }
    
    def send_result(self, result: Dict[str, Any]) -> None:
        """
        Отправка результата в Redis очередь выходных сообщений.
        
        Args:
            result: dict с результатом анализа
        """
        try:
            result_json = json.dumps(result, ensure_ascii=False)
            self.redis_client.rpush(QUEUE_AGENT4_OUTPUT, result_json)
            print(f"📤 Агент 4 отправил результат в {QUEUE_AGENT4_OUTPUT}")
        except Exception as e:
            print(f"❌ Ошибка отправки в Redis: {e}")
    
    def run(self) -> None:
        """
        Основной цикл работы Агента 4.
        Слушает очередь QUEUE_AGENT4_INPUT и обрабатывает сообщения.
        """
        print(f"🚀 Агент 4 запущен.")
        print(f"👂 Слушаем очередь: {QUEUE_AGENT4_INPUT}")
        print(f"📤 Отправляем результаты в: {QUEUE_AGENT4_OUTPUT}")
        print("⏹️  Остановка: Ctrl+C")
        
        while True:
            try:
                # Блокирующее чтение из очереди (timeout 1 сек)
                result = self.redis_client.blpop(QUEUE_AGENT4_INPUT, timeout=1)
                
                if result is None:
                    # Если BLPOP вернул None, значит таймаут истек
                    continue
                    
                queue_name, message_data = result
                print(f"📨 Агент 4 получил сообщение из {queue_name}")
                
                # Обрабатываем сообщение
                output = self.process_message(message_data)
                
                # Отправляем результат
                self.send_result(output)
                
                print(f"✅ Агент 4 завершил обработку")
                
            except KeyboardInterrupt:
                print("\n🛑 Агент 4 остановлен (Ctrl+C)")
                break
            except Exception as e:
                print(f"❌ Ошибка: {e}")
                time.sleep(1)
        
        print("👋 Агент 4 завершил работу")

def test_agent4_local():
    """Тест работы Агента 4 без Redis."""
    print("🧪 Тестирование Агента 4 БЕЗ REDIS")
    
    # Тестовые данные
    test_input = {
        'message': 'Купите дешевые товары! Скидки!!! https://t.me/spam',
        'rules': ['Запрещена реклама', 'Запрещен спам', 'Запрещены ссылки'],
        # Метаданные
        'user_id': 123456789,
        'username': 'testuser',
        'chat_id': -1001234567890,
        'message_id': 42
    }
    
    # Тестируем Агент 4
    result = moderation_agent4(test_input)
    
    # Выводим результат
    print("📊 Результат Агента 4:")
    print(json.dumps(result, ensure_ascii=False, indent=2))

def test_agent4_with_redis():
    """Тест работы Агента 4 С Redis."""
    print("🧪 Тестирование Агента 4 С REDIS")
    
    # Подключаемся к Redis
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, password=REDIS_PASSWORD, decode_responses=True)
    
    # Тестовые данные
    test_input = {
        'message': 'Идиоты, дураки! Покупайте мой товар!!!',
        'rules': ['Запрещена реклама', 'Запрещены оскорбления', 'Запрещен мат', 'Запрещен флуд'],
        'user_id': 987654321,
        'username': 'toxicuser',
        'chat_id': -1009876543210,
        'message_id': 100
    }
    
    # Отправляем в очередь
    test_json = json.dumps(test_input, ensure_ascii=False)
    r.rpush(QUEUE_AGENT4_INPUT, test_json)
    print(f"📤 Тестовое сообщение отправлено в {QUEUE_AGENT4_INPUT}")
    
    print("🔄 Теперь запустите: python fourth_agent.py")
    print(f"📥 Результат будет в очереди: {QUEUE_AGENT4_OUTPUT}")

if __name__ == "__main__":
    import sys
    
    print("=" * 60)
    print("🔧 АГЕНТ №4 - ГОТОВЫЙ ACCESS TOKEN (ЭВРИСТИЧЕСКИЙ)")
    print("=" * 60)
    print("🔧 Использует эвристический анализ (без AI)")
    print("🧠 Может дополнительно использовать OpenAI API")
    print(f"🔑 GigaChat токен готов ({len(GIGACHAT_ACCESS_TOKEN)} символов)")
    print("🧪 Поддерживает проверку из Telegram бота")
    print()
    
    # Проверяем аргументы командной строки
    if len(sys.argv) > 1:
        mode = sys.argv[1]
        
        if mode == "test":
            # Локальный тест без Redis
            test_agent4_local()
        elif mode == "send-test":
            # Отправка тестового сообщения в Redis  
            test_agent4_with_redis()
        else:
            print("❓ Неизвестный режим.")
            print("python fourth_agent.py - запуск Агента 4")
            print("python fourth_agent.py test - локальный тест без Redis")
            print("python fourth_agent.py send-test - отправка тестового сообщения в Redis")
    else:
        # Основной режим работы с Redis
        print("🚀 Запускаем Агент 4 с эвристическим анализом...")
        print("=" * 60)
        worker = Agent4RedisWorker()
        worker.run()
