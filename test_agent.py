import requests
import json

input_message = input()

# Тестовые данные
data = {
    "telegram_message": {
        "message_id": 1,
        "chat_id": -1001234567890,
        "sender_id": 12345,
        "message_text": f"{input_message}"
    },
    "prompt": "Обработай сообщение согласно правилам чата",
    "chat_rules": {
        "moderation_enabled": True,
        "max_message_length": 1000,
        "forbidden_words": ["спам", "реклама"]
    }
}

# Отправка запроса
try:
    response = requests.post(
        "http://localhost:8001/process_message",
        json=data,
        timeout=30
    )

    print(f"Статус: {response.status_code}")
    print(f"Ответ:")
    print(json.dumps(response.json(), ensure_ascii=False, indent=2))

except requests.exceptions.RequestException as e:
    print(f"Ошибка: {e}")
