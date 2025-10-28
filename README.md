# 🤖 Многоагентная система модерации Telegram

Система автоматической модерации сообщений в Telegram с использованием искусственного интеллекта на базе GigaChat API.

## 📋 Оглавление

- [Архитектура системы](#архитектура-системы)
- [Требования](#требования)
- [Установка](#установка)
- [Конфигурация](#конфигурация)
- [Запуск Агента №1](#запуск-агента-1)
- [Тестирование API](#тестирование-api)
- [Мониторинг и логи](#мониторинг-и-логи)
- [Устранение проблем](#устранение-проблем)

## 🏗️ Архитектура системы

Система состоит из 5 агентов, работающих асинхронно:

```
Telegram Bot → Агент №1 → Агент №2 → Агент №3 → Агент №4 → Агент №5
     ↓             ↓           ↓           ↓           ↓           ↓
  База данных   Нормализация Анализ    Действия    Аудит     Эскалация
   (SQLite)      + GigaChat   контента  модерации  отчеты    спорные
```

### Агент №1 - Координатор и Нормализатор
- ✅ **Реализован** - нормализация текста, применение правил чата
- ✅ **GigaChat интеграция** - генерация ответов через ИИ
- ✅ **Redis коммуникация** - передача данных в очередь для других агентов
- ✅ **REST API** - обработка сообщений и batch запросов
- ✅ **Мониторинг** - health checks, метрики, логирование

## 📦 Требования

### Системные требования
- **Python 3.8+**
- **Windows 10/11** (инструкция для Windows)
- **4 ГБ RAM** (минимум)
- **100 МБ** свободного места

### Python библиотеки
```txt
fastapi==0.104.1
uvicorn[standard]==0.24.0
httpx==0.25.2
loguru==0.7.2
redis==5.0.1
```

### Внешние сервисы
- **Redis Server** (для очередей между агентами)
- **GigaChat API** (для генерации ответов)

## 🔧 Установка

### 1. Клонирование проекта
```bash
git clone <repository-url>
cd telegram-moderation-system
```

### 2. Установка Python зависимостей
```bash
pip install fastapi uvicorn[standard] httpx loguru redis
```

### 3. Установка Redis Server

#### Скачивание и установка:
1. Перейдите на https://github.com/microsoftarchive/redis/releases
2. Скачайте `Redis-x64-3.0.504.msi`
3. Запустите установщик
4. **Важно**: При установке оставьте порт **6379** (по умолчанию)
5. Включите опцию **"Add Redis to the Windows Firewall exception list"**

#### Проверка установки Redis:
```bash
# Откройте CMD и выполните:
redis-cli ping
# Должно вернуть: PONG
```

### 4. Получение GigaChat API ключа

#### Регистрация:
1. Откройте https://giga.chat
2. Войдите через **Сбер ID**
3. Перейдите в **"Профиль"** → **"GigaChat API"** → **"Личный кабинет"**
4. Попадете в https://developers.sber.ru/studio

#### Создание проекта:
1. Нажмите **"Создать проект"**
2. Выберите **"GigaChat API"**
3. Введите название проекта
4. В секции **"Доступ к API"** нажмите **"Получить доступ"**
5. Нажмите **"Получить новый ключ"**

#### Сохранение ключей:
Скопируйте и сохраните:
- **Authorization Key** - это ваш `GIGACHAT_CREDENTIALS`
- **Client ID** и **Client Secret** (для справки)

⚠️ **Внимание**: Ключи показываются только один раз!

## ⚙️ Конфигурация

### Переменные окружения

#### Windows CMD:
```cmd
set GIGACHAT_CREDENTIALS=MDE5YTJhZjEtYjhjOS03OTViLWFlZjEtZTg4MTgxNjQzNzdjOmE0MzRhNjExLTE2NGYtNDdjYS1iNTM2LThlMGViMmU0YzVmNg==
set REDIS_URL=redis://localhost:6379
set API_HOST=127.0.0.1
set API_PORT=8001
```

#### Windows PowerShell:
```powershell
$env:GIGACHAT_CREDENTIALS="MDE5YTJhZjEtYjhjOS03OTViLWFlZjEtZTg4MTgxNjQzNzdjOmE0MzRhNjExLTE2NGYtNDdjYS1iNTM2LThlMGViMmU0YzVmNg=="
$env:REDIS_URL="redis://localhost:6379"
$env:API_HOST="127.0.0.1"
$env:API_PORT="8001"
```

### Создание bat-файла (рекомендуется)

Создайте `run_agent1.bat`:
```bat
@echo off
set GIGACHAT_CREDENTIALS=ваш_authorization_key_сюда
set REDIS_URL=redis://localhost:6379
set API_HOST=127.0.0.1
set API_PORT=8001
python agent1_fixed.py
pause
```

## 🚀 Запуск Агента №1

### Метод 1: Через bat-файл
```cmd
run_agent1.bat
```

### Метод 2: Прямой запуск
```cmd
python agent1_fixed.py
```

### Ожидаемый вывод при успешном запуске:
```
17:56:01 | INFO | 🚀 Запуск Чат-агента №1 (исправленная версия)...
17:56:01 | INFO | 🔑 Используем GIGACHAT_CREDENTIALS: MDE5YTJhZjEt...
17:56:01 | INFO | 🔧 GigaChat клиент инициализирован
17:56:01 | INFO | 🔗 Коммуникатор подключен к Redis: redis://localhost:6379
17:56:01 | INFO | 🚀 Чат-агент №1 инициализирован
17:56:01 | SUCCESS | ✅ Агент №1 запущен и готов к работе
INFO:     Uvicorn running on http://127.0.0.1:8001 (Press CTRL+C to quit)
```

⚠️ **Если видите ошибку Redis** - это нормально при первом запуске без Redis

## 🧪 Тестирование API

### Проверка здоровья системы
Откройте в браузере: http://localhost:8001/health

Ожидаемый ответ:
```json
{
  "agent_id": "agent_1",
  "status": "healthy",
  "redis_status": "connected",
  "gigachat_token_status": "not_obtained",
  "api_status": "healthy"
}
```

### Главная страница API
http://localhost:8001/

### Метрики системы
http://localhost:8001/metrics

### Тест обработки сообщения

#### Через Python (рекомендуется):
Создайте `test_agent1.py`:
```python
import requests
import json

# Тестовые данные
data = {
    "telegram_message": {
        "message_id": 1,
        "chat_id": -1001234567890,
        "sender_id": 12345,
        "message_text": "Привет! Как дела?"
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
    print("Результат обработки:")
    print(json.dumps(response.json(), ensure_ascii=False, indent=2))
    
except requests.exceptions.RequestException as e:
    print(f"Ошибка: {e}")
```

Запуск:
```cmd
python test_agent1.py
```

#### Через PowerShell:
```powershell
Invoke-RestMethod -Uri "http://localhost:8001/process_message" -Method POST -ContentType "application/json" -Body '{
  "telegram_message": {
    "message_id": 1,
    "chat_id": -1001234567890,
    "sender_id": 12345,
    "message_text": "Привет! Как дела?"
  },
  "prompt": "Обработай сообщение согласно правилам чата"
}'
```

### Ожидаемый результат теста:
```json
{
  "originalMessage": "Привет! Как дела?",
  "processedPrompt": "Обработай сообщение согласно правилам чата",
  "responseText": "Привет! У меня всё хорошо, спасибо!",
  "message_id": 1,
  "chat_id": -1001234567890,
  "sender_id": 12345,
  "normalized_text": "Привет! Как дела?",
  "rules_applied": [],
  "confidence_score": 0.85,
  "processing_time_ms": 1250,
  "correlation_id": "abc123-def456-ghi789"
}
```

## 📊 Мониторинг и логи

### Структура логов
```
logs/
├── agent_1_2025-10-28.log  # Ежедневные логи
├── agent_1_2025-10-29.log
└── ...
```

### Консольные логи в реальном времени:
```
17:56:05 | SUCCESS | 🔑 Получен новый токен GigaChat
17:56:06 | SUCCESS | 🤖 GigaChat ответ: 'Привет! Как дела?' (17 символов)
17:56:06 | SUCCESS | 📤 Отправлено Агенту 2 | msg_id=1 | corr=abc123...
17:56:06 | SUCCESS | 🎯 Сообщение 1 успешно передано Агенту 2
```

### Ключевые метрики для мониторинга:
- **processed_messages** - количество обработанных сообщений
- **error_rate** - процент ошибок
- **gigachat_requests** - количество запросов к GigaChat
- **queue_to_agent_2_size** - размер очереди к Агенту 2
- **uptime_seconds** - время работы агента

### API endpoints для мониторинга:
- `GET /health` - базовый health check
- `GET /metrics` - расширенные метрики
- `GET /` - информация о сервисе

## 🔧 Устранение проблем

### Ошибка: "GIGACHAT_CREDENTIALS is required"
**Решение**: Установите переменную окружения или используйте bat-файл
```cmd
set GIGACHAT_CREDENTIALS=ваш_ключ_сюда
```

### Ошибка: "Error 10061 connecting to localhost:6379"
**Причина**: Redis не запущен  
**Решение**:
1. Запустите Redis Server
2. Или проверьте, что сервис Redis запущен в Windows
3. Или проигнорируйте - агент работает и без Redis

### Ошибка: HTTP 401 при запросе к GigaChat
**Причина**: Неверный Authorization Key  
**Решение**: Проверьте правильность `GIGACHAT_CREDENTIALS`

### Агент не отвечает на порту 8001
**Решение**:
1. Проверьте, что порт не занят: `netstat -an | findstr 8001`
2. Измените порт: `set API_PORT=8002`
3. Запустите от администратора

### Токен GigaChat не получается
**Решение**:
1. Проверьте интернет-соединение
2. Убедитесь, что ключ скопирован полностью
3. Попробуйте пересоздать ключ в личном кабинете

## 🎯 Что дальше?

После успешного запуска Агента №1 можно переходить к:

1. **Разработке остальных агентов** (2-5)
2. **Интеграции с Telegram Bot API**
3. **Настройке базы данных SQLite**
4. **Конфигурации правил модерации**

---

## 📞 Поддержка

Если возникают проблемы:
1. Проверьте логи в папке `logs/`
2. Убедитесь, что все зависимости установлены
3. Проверьте статус через `/health` endpoint
4. Перезапустите все сервисы (Redis, Агент)

**Версия документации**: 1.0  
**Дата создания**: 28 октября 2025  
**Статус Агента №1**: ✅ Полностью функционален