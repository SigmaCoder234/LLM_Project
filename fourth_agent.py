"""
АГЕНТ 4 — Независимый модератор (Эксперт 2)

Этот агент работает параллельно с Агентом 3, но использует ДРУГОЙ метод анализа.
- Агент 3: использует GigaChat API
- Агент 4: использует эвристический анализ + паттерны + опционально OpenAI API

Формат данных полностью совместим с Агентом 3.
"""

import requests
import json
import redis
import time
import re
from typing import Dict, Any, List, Optional

# =============================================================================
# КОНФИГУРАЦИЯ
# =============================================================================

# OpenAI API (опционально - для альтернативного анализа)
OPENAI_API_KEY = "YOUR_OPENAI_API_KEY"  # Опционально
USE_OPENAI = False  # Установить True для использования OpenAI вместо эвристик

# Redis настройки
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0
REDIS_PASSWORD = None  # Если есть пароль, укажи здесь

# Названия очередей Redis
QUEUE_AGENT_4_INPUT = "queue:agent4:input"  # Очередь входящих сообщений для агента 4
QUEUE_AGENT_4_OUTPUT = "queue:agent4:output"  # Очередь исходящих результатов от агента 4


# =============================================================================
# ЭВРИСТИЧЕСКИЙ АНАЛИЗАТОР (ОСНОВНОЙ МЕТОД АГЕНТА 4)
# =============================================================================

class HeuristicAnalyzer:
    """
    Эвристический анализатор сообщений.
    Агент 4 использует набор правил, паттернов и эвристик для принятия решений.
    Это отличается от Агента 3, который использует нейросети.
    """

    def __init__(self):
        # Паттерны для обнаружения нарушений
        self.spam_patterns = [
            r'вступай(те)?\s+в\s+(наш|наш|мой)',
            r'подпис(ыв)?ай(ся|тесь)?\s+(на|в)',
            r'переход(и(те)?)?\s+по\s+ссылке',
            r'жми\s+(сюда|тут|на\s+ссылку)',
            r'@\w+',  # Упоминание других каналов
            r'https?://\S+',  # Ссылки
            r't\.me/\S+',  # Telegram ссылки
        ]

        self.insult_patterns = [
            r'\b(идиот|дурак|тупой|глупый|мудак)\b',
            r'\b(придурок|дебил|имбецил|кретин)\b',
        ]

        self.profanity_patterns = [
            r'\b(блять|бля|хуй|пизд|ебать|сука)\b',
        ]

        self.flood_indicators = [
            r'([А-Яа-я])\1{4,}',  # Повторяющиеся символы
            r'[!?]{3,}',  # Много знаков препинания
            r'[A-ZА-Я]{10,}',  # КАПС
        ]

    def check_spam(self, message: str) -> tuple:
        """Проверка на спам и рекламу"""
        message_lower = message.lower()

        for pattern in self.spam_patterns:
            if re.search(pattern, message_lower):
                return True, f"Обнаружена реклама/спам (паттерн: {pattern})"

        # Проверка на количество ссылок
        links_count = len(re.findall(r'https?://|t\.me/', message_lower))
        if links_count >= 2:
            return True, f"Множественные ссылки ({links_count} шт.) - признак спама"

        # Проверка на упоминание нескольких каналов
        mentions = re.findall(r'@\w+', message)
        if len(mentions) >= 2:
            return True, f"Упоминание нескольких каналов ({len(mentions)} шт.)"

        return False, ""

    def check_insults(self, message: str) -> tuple:
        """Проверка на оскорбления"""
        message_lower = message.lower()

        for pattern in self.insult_patterns:
            match = re.search(pattern, message_lower)
            if match:
                return True, f"Обнаружено оскорбление: '{match.group()}'"

        return False, ""

    def check_profanity(self, message: str) -> tuple:
        """Проверка на нецензурную лексику"""
        message_lower = message.lower()

        for pattern in self.profanity_patterns:
            match = re.search(pattern, message_lower)
            if match:
                return True, f"Обнаружена нецензурная лексика: '{match.group()}'"

        return False, ""

    def check_flood(self, message: str) -> tuple:
        """Проверка на флуд"""
        for pattern in self.flood_indicators:
            match = re.search(pattern, message)
            if match:
                return True, f"Обнаружен флуд: '{match.group()}'"

        # Проверка на очень короткие повторяющиеся сообщения
        if len(message) < 3:
            return True, "Слишком короткое сообщение (возможный флуд)"

        return False, ""

    def check_rules_match(self, message: str, rules: List[str]) -> tuple:
        """
        Проверяет сообщение на соответствие правилам чата.
        Возвращает (нарушение_найдено, причина)
        """
        violations = []

        # Проверяем каждое правило
        for rule in rules:
            rule_lower = rule.lower()

            # Проверка на спам/рекламу
            if any(keyword in rule_lower for keyword in ['спам', 'реклам', 'промо']):
                is_spam, reason = self.check_spam(message)
                if is_spam:
                    violations.append(f"Нарушение правила '{rule}': {reason}")

            # Проверка на оскорбления
            if any(keyword in rule_lower for keyword in ['оскорбл', 'унижен', 'хамств']):
                is_insult, reason = self.check_insults(message)
                if is_insult:
                    violations.append(f"Нарушение правила '{rule}': {reason}")

            # Проверка на мат
            if any(keyword in rule_lower for keyword in ['мат', 'нецензур', 'ругат']):
                is_profane, reason = self.check_profanity(message)
                if is_profane:
                    violations.append(f"Нарушение правила '{rule}': {reason}")

            # Проверка на флуд
            if any(keyword in rule_lower for keyword in ['флуд', 'спам']):
                is_flood, reason = self.check_flood(message)
                if is_flood:
                    violations.append(f"Нарушение правила '{rule}': {reason}")

        if violations:
            return True, " | ".join(violations)

        return False, "Нарушений не обнаружено. Сообщение соответствует правилам чата."

    def analyze(self, message: str, rules: List[str]) -> Dict[str, Any]:
        """
        Основной метод анализа сообщения.

        Returns:
            dict: {"ban": bool, "reason": str}
        """
        # Базовая валидация
        if not message or not message.strip():
            return {
                "ban": False,
                "reason": "Пустое сообщение - нет оснований для бана"
            }

        # Проверяем по правилам
        has_violation, reason = self.check_rules_match(message, rules)

        return {
            "ban": has_violation,
            "reason": reason
        }


# =============================================================================
# OPENAI API (АЛЬТЕРНАТИВНЫЙ МЕТОД)
# =============================================================================

def check_message_with_openai(message: str, rules: List[str], api_key: str) -> Dict[str, Any]:
    """
    Альтернативный метод: использует OpenAI API для анализа.
    Это отличается от GigaChat, который использует Агент 3.
    """
    url = "https://api.openai.com/v1/chat/completions"

    rules_text = "\n".join([f"{i + 1}. {rule}" for i, rule in enumerate(rules)])

    system_msg = f"""Ты — AI модератор Telegram-канала. 
Твоя задача: анализировать сообщения пользователей и определять нарушения.

Правила чата:
{rules_text}

Будь объективным и справедливым. Анализируй контекст сообщения.
Ответь в формате: "Вердикт: да/нет. Причина: [объяснение]"""

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": f"Проанализируй сообщение: {message}"}
        ],
        "temperature": 0.3,
        "max_tokens": 256
    }

    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        result = response.json()
        content = result["choices"][0]["message"]["content"]

        # Парсим ответ
        content_lower = content.lower()
        ban = any(word in content_lower for word in ["вердикт: да", "нарушение", "забанить"])

        return {
            "ban": ban,
            "reason": content.strip()
        }

    except Exception as e:
        error_msg = f"Ошибка при запросе к OpenAI: {e}"
        print(f"[ОШИБКА] {error_msg}")
        return {
            "ban": False,
            "reason": error_msg
        }


# =============================================================================
# АГЕНТ 4 — МОДЕРАЦИЯ
# =============================================================================

def moderation_agent_4(input_ Dict[str, Any]

) -> Dict[str, Any]:
"""
АГЕНТ 4 — Независимый модератор (альтернативный подход).

ФОРМАТ ВХОДНЫХ ДАННЫХ (СОВМЕСТИМ С АГЕНТОМ 3):
input_data = {
    "message": "текст сообщения пользователя",  # ОБЯЗАТЕЛЬНО
    "rules": ["правило 1", "правило 2", ...],   # ОБЯЗАТЕЛЬНО
    "user_id": 12345,          # ⬅️ ВПИСЫВАЕТСЯ АГЕНТОМ 2
    "username": "@username",   # ⬅️ ВПИСЫВАЕТСЯ АГЕНТОМ 2
    "chat_id": -1001234567890, # ⬅️ ВПИСЫВАЕТСЯ АГЕНТОМ 2
    "message_id": 42           # ⬅️ ВПИСЫВАЕТСЯ АГЕНТОМ 2
}

ФОРМАТ ВЫХОДНЫХ ДАННЫХ (СОВМЕСТИМ С АГЕНТОМ 3):
{
    "agent_id": 4,
    "ban": True/False,
    "reason": "Вердикт агента 4 с объяснением",
    "message": "оригинальное сообщение",
    "user_id": 12345,          # ⬅️ ПЕРЕДАЕТСЯ ОБРАТНО
    "username": "@username",   # ⬅️ ПЕРЕДАЕТСЯ ОБРАТНО
    "chat_id": -1001234567890, # ⬅️ ПЕРЕДАЕТСЯ ОБРАТНО
    "message_id": 42           # ⬅️ ПЕРЕДАЕТСЯ ОБРАТНО
}
"""
# Извлекаем данные
message = input_data.get("message", "")
rules = input_data.get("rules", [])

# ⬇️ МЕТАДАННЫЕ ПОЛЬЗОВАТЕЛЯ (ПЕРЕДАЮТСЯ ОТ АГЕНТА 2)
user_id = input_data.get("user_id")
username = input_data.get("username")
chat_id = input_data.get("chat_id")
message_id = input_data.get("message_id")

# Валидация входных данных
if not message:
    return {
        "agent_id": 4,
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
        "agent_id": 4,
        "ban": False,
        "reason": "Ошибка: правила не переданы",
        "message": message,
        "user_id": user_id,
        "username": username,
        "chat_id": chat_id,
        "message_id": message_id
    }

print(f"[АГЕНТ 4] Анализирую сообщение: {message[:50]}...")

# Выбираем метод анализа
if USE_OPENAI and OPENAI_API_KEY != "YOUR_OPENAI_API_KEY":
    # Используем OpenAI API
    print("[АГЕНТ 4] Метод анализа: OpenAI API")
    result = check_message_with_openai(message, rules, OPENAI_API_KEY)
else:
    # Используем эвристический анализ (по умолчанию)
    print("[АГЕНТ 4] Метод анализа: Эвристический анализатор")
    analyzer = HeuristicAnalyzer()
    result = analyzer.analyze(message, rules)

# Формируем выходные данные
output = {
    "agent_id": 4,
    "ban": result["ban"],
    "reason": result["reason"],
    "message": message,
    # ⬇️ ПЕРЕДАЕМ МЕТАДАННЫЕ ОБРАТНО АГЕНТУ 2
    "user_id": user_id,
    "username": username,
    "chat_id": chat_id,
    "message_id": message_id
}

print(f"[АГЕНТ 4] Вердикт: {'БАН' if result['ban'] else 'НЕ БАНИТЬ'}")

return output


# =============================================================================
# РАБОТА С REDIS
# =============================================================================

class Agent4RedisWorker:
    """
    Воркер агента 4, который слушает очередь Redis и обрабатывает сообщения.
    Структура полностью аналогична Agent3RedisWorker, но с другой логикой.
    """

    def __init__(self, redis_config: Optional[Dict] = None):
        """
        Инициализация воркера.

        Args:
            redis_config: Настройки Redis (опционально)
        """
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
            print(f"[АГЕНТ 4] Подключение к Redis успешно: {REDIS_HOST}:{REDIS_PORT}")
        except Exception as e:
            print(f"[ОШИБКА] Не удалось подключиться к Redis: {e}")
            raise

    def process_message(self, message_ str

    ) -> Dict[str, Any]:
    """
    Обрабатывает одно сообщение из очереди.

    Args:
        message_ JSON-строка с данными сообщения

    Returns:
        dict: Результат обработки
    """
    try:
        # Парсим JSON
        input_data = json.loads(message_data)

        # Обрабатываем через агента 4
        result = moderation_agent_4(input_data)

        return result

    except json.JSONDecodeError as e:
        print(f"[ОШИБКА] Невалидный JSON: {e}")
        return {
            "agent_id": 4,
            "ban": False,
            "reason": f"Ошибка парсинга данных: {e}",
            "message": ""
        }

    except Exception as e:
        print(f"[ОШИБКА] Ошибка обработки сообщения: {e}")
        return {
            "agent_id": 4,
            "ban": False,
            "reason": f"Внутренняя ошибка агента 4: {e}",
            "message": ""
        }


def send_result(self, result: Dict[str, Any]) -> None:
    """
    Отправляет результат в выходную очередь Redis.

    Args:
        result: dict с результатом обработки
    """
    try:
        result_json = json.dumps(result, ensure_ascii=False)
        self.redis_client.rpush(QUEUE_AGENT_4_OUTPUT, result_json)
        print(f"[АГЕНТ 4] Результат отправлен в {QUEUE_AGENT_4_OUTPUT}")
    except Exception as e:
        print(f"[ОШИБКА] Не удалось отправить результат в Redis: {e}")


def run(self) -> None:
    """
    Основной цикл обработки сообщений из Redis.
    Слушает очередь QUEUE_AGENT_4_INPUT и обрабатывает сообщения.
    """
    print(f"[АГЕНТ 4] Запущен. Ожидаю сообщения из очереди: {QUEUE_AGENT_4_INPUT}")
    print(f"[АГЕНТ 4] Результаты отправляются в очередь: {QUEUE_AGENT_4_OUTPUT}")
    print("[АГЕНТ 4] Нажмите Ctrl+C для остановки\n")

    while True:
        try:
            # Блокирующее чтение из очереди (timeout=1 секунда)
            # BLPOP возвращает (queue_name, message) или None
            result = self.redis_client.blpop(QUEUE_AGENT_4_INPUT, timeout=1)

            if result is None:
                # Таймаут, сообщений нет — продолжаем ждать
                continue

            queue_name, message_data = result
            print(f"\n[АГЕНТ 4] Получено новое сообщение из {queue_name}")

            # Обрабатываем сообщение
            output = self.process_message(message_data)

            # Отправляем результат в выходную очередь
            self.send_result(output)

            print(f"[АГЕНТ 4] Обработка завершена\n")

        except KeyboardInterrupt:
            print("\n[АГЕНТ 4] Получен сигнал остановки (Ctrl+C)")
            break

        except Exception as e:
            print(f"[ОШИБКА] Неожиданная ошибка в основном цикле: {e}")
            time.sleep(1)  # Пауза перед повтором

    print("[АГЕНТ 4] Остановлен")


# =============================================================================
# ТЕСТИРОВАНИЕ
# =============================================================================

def test_agent_4_local():
    """
    Локальный тест агента 4 без Redis (для отладки).
    """
    print("=== ТЕСТ АГЕНТА 4 (БЕЗ REDIS) ===\n")

    # Тестовые данные
    test_input = {
        "message": "Вступайте в наш чат @spamchannel! Крутые предложения! https://t.me/spam",
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

    # Запускаем агента 4
    result = moderation_agent_4(test_input)

    # Выводим результат
    print("\n=== РЕЗУЛЬТАТ АГЕНТА 4 ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def test_agent_4_with_redis():
    """
    Тест агента 4 с Redis: отправляем тестовое сообщение в очередь.
    """
    print("=== ТЕСТ АГЕНТА 4 (С REDIS) ===\n")

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
        "message": "Идиот, дурак! Иди на хуй!",
        "rules": [
            "Запрещена реклама сторонних сообществ",
            "Запрещён флуд и спам",
            "Запрещены оскорбления участников",
            "Запрещена нецензурная лексика"
        ],
        "user_id": 987654321,
        "username": "@toxic_user",
        "chat_id": -1009876543210,
        "message_id": 100
    }

    # Отправляем в очередь агента 4
    test_json = json.dumps(test_input, ensure_ascii=False)
    r.rpush(QUEUE_AGENT_4_INPUT, test_json)

    print(f"Тестовое сообщение отправлено в очередь: {QUEUE_AGENT_4_INPUT}")
    print("Запустите агента 4 командой: python agent4.py")
    print(f"\nРезультат появится в очереди: {QUEUE_AGENT_4_OUTPUT}")


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
            test_agent_4_local()
        elif mode == "send-test":
            # Отправить тестовое сообщение в Redis
            test_agent_4_with_redis()
        else:
            print("Неизвестный режим. Используйте:")
            print("  python agent4.py           - запустить агента 4")
            print("  python agent4.py test      - локальный тест без Redis")
            print("  python agent4.py send-test - отправить тестовое сообщение")
    else:
        # Основной режим: запуск воркера
        worker = Agent4RedisWorker()
        worker.run()
