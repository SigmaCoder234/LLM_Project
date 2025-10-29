# TeleGuard Bot - Многоагентная система модерации Telegram

## Описание проекта

TeleGuard Bot - это современная многоагентная система для автоматической модерации Telegram-чатов, построенная на базе PostgreSQL, Redis и искусственного интеллекта. Система состоит из 5 независимых агентов, каждый из которых выполняет специализированную задачу в процессе модерации сообщений.

## Архитектура системы

### Основные компоненты:

1. **TeleGuard Bot** (`teteguard_bot.py`) - Основной Telegram бот
2. **Agent 1** (`first_agent.py`) - Координатор и нормализатор
3. **Agent 2** (`second_agent.py`) - Анализатор и распределитель  
4. **Agent 3** (`third_agent.py`) - Модератор на базе GigaChat
5. **Agent 4** (`fourth_agent.py`) - Модератор с эвристическим анализом
6. **Agent 5** (`fifth_agent.py`) - Арбитр и финальный судья

### Схема работы:

```
Telegram Chat → TeleGuard Bot → Agent 1 → Agent 2 → Agent 3 & Agent 4 → Agent 5 → Moderators
```

## Структура файлов

```
teleguard_project/
├── teteguard_bot.py           # Основной Telegram бот
├── first_agent.py             # Агент №1 - Координатор
├── second_agent.py            # Агент №2 - Анализатор  
├── third_agent.py             # Агент №3 - Модератор (GigaChat)
├── fourth_agent.py            # Агент №4 - Модератор (эвристика)
├── fifth_agent.py             # Агент №5 - Арбитр
├── README.md                  # Этот файл
├── requirements.txt           # Зависимости проекта
├── .env                       # Переменные окружения (создать)
└── logs/                      # Директория для логов (создается автоматически)
```

## Технологический стек

### Backend:
- **Python 3.10+** - Основной язык программирования
- **FastAPI** - REST API фреймворк для агентов
- **SQLAlchemy 2.0** - ORM для работы с базой данных
- **asyncio** - Асинхронное программирование
- **Loguru** - Продвинутое логирование

### Database:
- **PostgreSQL** - Основная база данных
- **asyncpg** - Асинхронный драйвер PostgreSQL

### Message Queue:
- **Redis** - Очереди сообщений между агентами

### Telegram:
- **aiogram 3.x** - Telegram Bot API фреймворк

### AI/ML:
- **GigaChat API** - Анализ сообщений через нейросети Сбербанка
- **Эвристические алгоритмы** - Альтернативный анализ паттернов

### HTTP Client:
- **httpx** - Асинхронный HTTP клиент
- **aiohttp** - HTTP клиент/сервер

## База данных PostgreSQL

### Схема БД:

```sql
-- Чаты
CREATE TABLE chats (
    id INTEGER PRIMARY KEY,
    tg_chat_id VARCHAR UNIQUE NOT NULL,
    title VARCHAR(255),
    chat_type VARCHAR(50) DEFAULT 'group',
    added_at TIMESTAMP DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE
);

-- Сообщения
CREATE TABLE messages (
    id INTEGER PRIMARY KEY,
    chat_id INTEGER REFERENCES chats(id) ON DELETE CASCADE,
    sender_username VARCHAR,
    sender_id BIGINT,
    message_text TEXT,
    message_link VARCHAR,
    created_at TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP,
    ai_response TEXT
);

-- Модераторы
CREATE TABLE moderators (
    id INTEGER PRIMARY KEY,
    chat_id INTEGER REFERENCES chats(id) ON DELETE CASCADE,
    username VARCHAR,
    telegram_user_id BIGINT,
    is_active BOOLEAN DEFAULT TRUE,
    added_at TIMESTAMP DEFAULT NOW()
);

-- Негативные сообщения
CREATE TABLE negative_messages (
    id INTEGER PRIMARY KEY,
    chat_id INTEGER REFERENCES chats(id) ON DELETE CASCADE,
    message_link VARCHAR,
    sender_username VARCHAR,
    negative_reason TEXT,
    is_sent_to_moderators BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);
```

## Установка и настройка

### 1. Системные требования:

- Python 3.10 или выше
- PostgreSQL 13+ 
- Redis 6+
- Ubuntu 20.04+ / Windows 10+ / macOS 12+
- Минимум 4GB RAM
- 10GB свободного места на диске

### 2. Установка зависимостей:

```bash
# Клонирование репозитория
git clone <repository-url>
cd LLM_project

# Создание виртуального окружения
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate   # Windows

# Установка зависимостей
pip install -r requirements.txt
```

### 3. Создание файла requirements.txt:

```txt
# FastAPI и сервер
fastapi==0.104.1
uvicorn[standard]==0.24.0

# База данных
sqlalchemy[asyncio]==2.0.23
asyncpg==0.29.0
alembic==1.12.1

# Telegram Bot
aiogram==3.2.0

# Redis
redis==5.0.1

# HTTP клиенты
httpx==0.25.2
aiohttp==3.9.1

# Утилиты
python-dotenv==1.0.0
loguru==0.7.2
python-multipart==0.0.6

# Дополнительные зависимости
pydantic==2.5.0
typing-extensions==4.8.0
```

### 4. Настройка PostgreSQL:

```bash
# Подключение к PostgreSQL
sudo -u postgres psql

# Создание пользователя и базы данных
CREATE USER tguser WITH PASSWORD 'mnvm7110';
CREATE DATABASE teleguard_db OWNER tguser;
GRANT ALL PRIVILEGES ON DATABASE teleguard_db TO tguser;
```

### 5. Настройка Redis:

```bash
# Установка Redis (Ubuntu)
sudo apt update
sudo apt install redis-server

# Запуск Redis
sudo systemctl start redis-server
sudo systemctl enable redis-server

# Проверка работы
redis-cli ping
# Должно вернуть: PONG
```

## Запуск системы

### Последовательность запуска:

1. **Запуск PostgreSQL и Redis:**
```bash
sudo systemctl start postgresql redis-server
```

2. **Запуск Agent 1 (Координатор):**
```bash
python first_agent.py
# Порт: 8001
```

3. **Запуск Agent 2 (Анализатор):**
```bash
python second_agent.py  
# Порт: 8002
```

4. **Запуск Agent 3 (GigaChat модератор):**
```bash
python third_agent.py
# Redis worker, без веб-интерфейса
```

5. **Запуск Agent 4 (Эвристический модератор):**
```bash
python fourth_agent.py
# Redis worker, без веб-интерфейса
```

6. **Запуск Agent 5 (Арбитр):**
```bash
python fifth_agent.py
# Standalone процесс
```

7. **Запуск основного Telegram бота:**
```bash
python teteguard_bot.py
# Основной бот
```

### Альтернативный запуск через Docker Compose:

```yaml
version: '3.8'
services:
  postgresql:
    image: postgres:15
    environment:
      POSTGRES_DB: teleguard_db
      POSTGRES_USER: tguser
      POSTGRES_PASSWORD: mnvm7110
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  agent1:
    build: .
    command: python first_agent.py
    ports:
      - "8001:8001"
    depends_on:
      - postgresql
      - redis

  agent2:
    build: .
    command: python second_agent.py
    ports:
      - "8002:8002"
    depends_on:
      - postgresql
      - redis

  agent3:
    build: .
    command: python third_agent.py
    depends_on:
      - redis

  agent4:
    build: .
    command: python fourth_agent.py
    depends_on:
      - redis

  agent5:
    build: .
    command: python fifth_agent.py
    depends_on:
      - postgresql

  telegram-bot:
    build: .
    command: python teteguard_bot.py
    depends_on:
      - postgresql

volumes:
  postgres_data:
```

## API Endpoints

### Agent 1 (http://localhost:8001):
- `POST /process_message` - Обработка одного сообщения
- `POST /process_batch` - Обработка пакета сообщений
- `GET /health` - Проверка здоровья
- `GET /metrics` - Метрики производительности
- `GET /chat/{chat_id}/stats` - Статистика чата
- `POST /chat/{chat_id}/moderator` - Добавить модератора
- `GET /chat/{chat_id}/messages` - Сообщения чата

### Agent 2 (http://localhost:8002):
- `POST /process_message` - Анализ сообщения
- `POST /process_batch` - Обработка пакета
- `GET /health` - Состояние системы

## Мониторинг и логирование

### Структура логов:

```
logs/
├── agent_1_2025-01-01.log    # Логи агента 1
├── agent_2_2025-01-01.log    # Логи агента 2  
├── agent_3_2025-01-01.log    # Логи агента 3
├── agent_4_2025-01-01.log    # Логи агента 4
├── agent_5_2025-01-01.log    # Логи агента 5
└── telegram_bot_2025-01-01.log # Логи Telegram бота
```

### Мониторинг через API:

```bash
# Проверка здоровья агента 1
curl http://localhost:8001/health

# Метрики агента 1  
curl http://localhost:8001/metrics

# Статистика чата
curl http://localhost:8001/chat/-1001234567890/stats
```

## Тестирование

### Запуск тестов:

```bash
# Тест агента 3
python third_agent.py test

# Тест агента 4
python fourth_agent.py test

# Тест агента 5
python fifth_agent.py test

# Отправка тестовых данных в Redis
python third_agent.py send-test
python fourth_agent.py send-test
```

### Ручное тестирование:

```bash
# Отправка тестового сообщения агенту 1
curl -X POST http://localhost:8001/process_message \
  -H "Content-Type: application/json" \
  -d '{
    "telegram_message": {
      "message_id": 123,
      "chat_id": -1001234567890, 
      "sender_id": 123456789,
      "message_text": "Тестовое сообщение для модерации",
      "timestamp": "2025-01-01T12:00:00Z"
    },
    "prompt": "Проанализируй сообщение на нарушения",
    "chat_rules": {
      "max_message_length": 1000,
      "forbidden_words": ["спам", "реклама"],
      "moderation_enabled": true
    }
  }'
```

## Безопасность

### Рекомендации:
1. **Не храните токены в коде** - используйте переменные окружения
2. **Ограничьте доступ к PostgreSQL** - только нужные IP
3. **Используйте HTTPS** для production
4. **Регулярно обновляйте зависимости**
5. **Мониторьте логи на подозрительную активность**

### Переменные окружения:
```bash
export POSTGRES_PASSWORD="strong_password_here"
export TELEGRAM_BOT_TOKEN="your_bot_token_here"  
export GIGACHAT_CREDENTIALS="your_gigachat_credentials"
```

## Решение проблем (Troubleshooting)

### Частые проблемы:

1. **Ошибка подключения к PostgreSQL:**
```bash
# Проверка статуса
sudo systemctl status postgresql

# Перезапуск
sudo systemctl restart postgresql
```

2. **Ошибка подключения к Redis:**
```bash
# Проверка Redis
redis-cli ping

# Перезапуск
sudo systemctl restart redis-server
```

3. **Ошибка токена GigaChat:**
- Проверьте правильность GIGACHAT_CREDENTIALS
- Убедитесь что токен не истек
- Проверьте лимиты API

4. **Бот не отвечает в Telegram:**
- Проверьте TELEGRAM_BOT_TOKEN
- Убедитесь что бот добавлен в чат как администратор
- Проверьте логи teteguard_bot.py

### Полезные команды:

```bash
# Просмотр активных процессов
ps aux | grep python

# Проверка портов
netstat -tlnp | grep :8001

# Просмотр логов
tail -f logs/agent_1_$(date +%Y-%m-%d).log

# Очистка Redis
redis-cli FLUSHALL

# Проверка таблиц PostgreSQL
sudo -u postgres psql teleguard_db -c "\dt"
```

- **Автор:** TeleGuard Team

---

**Версия:** 1.0.0  
**Дата обновления:** 29 октября 2025  
**Статус:** Testing
