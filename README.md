# 🤖 TeleGuard - Многоагентная система модерации Telegram 

Интеллектуальная система модерации для Telegram-чатов с использованием **Mistral AI** и пяти специализированных агентов для анализа сообщений в реальном времени.


### 📋 **Новый промпт-формат для модерации:**
```
Вердикт: <банить/не банить>
Причина: <текст причины>
Уверенность: <число от 0 до 100>%
```

### 🛡️ **Кастомные правила для каждого чата:**
- Стандартные правила: "Запрещена расовая дискриминация" + "Запрещены ссылки"
- Администраторы могут задать свои правила через бота
- Правила сохраняются в базе данных для каждого чата


## 🧠 ИИ Провайдер: Mistral AI

Многие агенты теперь используют **Mistral AI API** с обновленными промптами:
- **Агент №2**: Mistral AI для анализа и распределения
- **Агент №3**: Полный анализ через Mistral AI с новым форматом
- **Агент №4**: DeepSeek для анализа текста сообщения
- **Агент №5**: Арбитр с обновленным промптом для OpenAI
- **Агент №6**: Анализ фотографий через Pixtral AI

Агенты 3, 4 и 5 используют разные модели, чтобы улучшить разнообразность мнений для принятия решения

### 🚀 **Поддерживаемые модели Mistral AI:**
- `mistral-large-latest` (рекомендуется)
- `mistral-medium-latest`
- `mistral-small-latest`
- `open-mistral-7b`
- `open-mistral-8x7b`
- `open-mistral-8x22b`

## ⚙️ Настройка с .env файлом (Mistral AI)

### 1. Создайте файл .env в корневой папке проекта:
```bash
cp .env.example .env
```

### 2. Заполните переменные окружения в .env:
```bash
# Mistral AI Configuration
MISTRAL_API_KEY=YOUR_API_KEY

# Telegram Bot Configuration  
TELEGRAM_BOT_TOKEN=YOUR_TELEGRAM_API_TOKEN

# Database Configuration
POSTGRES_URL=postgresql://user:password@host:port/database
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=YOUR_USER
POSTGRES_PASSWORD=YOUR_PASSWORD
POSTGRES_DB=YOUR_DB_NAME

# Redis Configuration
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=

# Application Configuration
DEBUG=False
LOG_LEVEL=INFO
TIMEZONE=Europe/Moscow

# AI Provider Configuration
AI_PROVIDER=mistral
MISTRAL_MODEL=mistral-large-latest
```

### 3. Установите зависимости:
```bash
pip install mistralai openai aiogram sqlalchemy psycopg2-binary redis requests fastapi uvicorn python-dotenv
```

### 4. Подготовьте базу данных:
```sql
-- Создайте базу данных и пользователя
CREATE DATABASE teleguard_db;
CREATE USER tguser WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE teleguard_db TO tguser;

-- Добавьте поле для кастомных правил (если обновляете)
ALTER TABLE chats ADD COLUMN IF NOT EXISTS custom_rules TEXT;
```

### 5. Проверьте конфигурацию:
```bash
python3 config.py
```

## 🚀 Запуск системы (Mistral AI версия)

### Способ 1: Последовательный запуск (рекомендуется)
```bash
# Терминал 1 - Агент №1 (Координатор Mistral AI)
python3 first_agent.py

# Терминал 2 - Агент №2 (Анализатор Mistral AI)
python3 second_agent.py

# Терминал 3 - Агент №3 (Модератор Mistral AI)
python3 third_agent.py

# Терминал 4 - Агент №4 (DeepSeek)
python3 fourth_agent.py

# Терминал 5 - Агент №5 (Арбитр OpenAI)
python3 fifth_agent.py

# Терминал 6 - Агент №6 (Анализ медиа файлов и аватарок юзеров Pixtral 12B-2409)

# Терминал 7 - Telegram Bot (Отображение в групповом чате)
python3 teleguard_bot.py
```

### Способ 2: С использованием screen/tmux (Mistral AI)
```bash
#!/bin/bash
# start_mistral_system.sh

# Проверяем наличие .env файла
if [ ! -f .env ]; then
    echo "❌ Файл .env не найден! Создайте его на основе .env.example"
    exit 1
fi

# Проверяем Mistral API ключ
if ! grep -q "MISTRAL_API_KEY=" .env; then
    echo "❌ MISTRAL_API_KEY не найден в .env файле!"
    exit 1
fi

echo "🚀 Запуск TeleGuard с Mistral AI..."

screen -dmS agent1 python3 first_agent.py
screen -dmS agent2 python3 second_agent.py
screen -dmS agent3 python3 third_agent.py
screen -dmS agent4 python3 fourth_agent.py
screen -dmS agent5 python3 fifth_agent.py

sleep 5
screen -dmS bot python3 teleguard_bot.py

echo "✅ Все агенты запущены с Mistral AI!"
echo "🧠 ИИ провайдер: Mistral AI"
screen -list
```

## 🔧 Проверка работы (Mistral AI версия)

### Health Check агентов
```bash
curl http://localhost:8001/health  # Агент 1
curl http://localhost:8002/health  # Агент 2 (Mistral AI)
curl http://localhost:8003/health  # Агент 3 (Mistral AI)
curl http://localhost:8004/health  # Агент 4 (DeepSeek)
curl http://localhost:8005/health  # Агент 5 (OpenAI)
```

Ответ теперь содержит информацию о Mistral AI (Для агентов, использующих данную модель):
```json
{
  "status": "online",
  "agent_id": 3,
  "ai_provider": "Mistral AI (mistral-large-latest)",
  "prompt_version": "v2.0",
  "configuration": "Environment variables (.env)",
  "default_rules": ["Запрещена расовая дискриминация", "Запрещены ссылки"],
  "uptime_seconds": 1234
}
```

### Тестирование Mistral AI конфигурации
```bash
# Проверка загрузки .env с Mistral AI
python3 -c "from config import get_config_summary; print(get_config_summary())"

# Тест отдельных агентов с Mistral AI
python3 third_agent.py test
```

## 📁 Структура файлов (Mistral AI версия)

```
TeleGuard-Mistral/
├── .env                # 🆕 Переменные окружения
├── config.py           # 🆕 Централизованная конфигурация
├── first_agent.py      # Агент №1 - Координатор (.env)
├── second_agent.py     # Агент №2 - Анализатор (Mistral AI)
├── third_agent.py      # Агент №3 - Mistral AI модератор
├── fourth_agent.py     # Агент №4 - DeepSeek
├── fifth_agent.py      # Агент №5 - Арбитр OpenAI
├── sixth_agent.py      # Агент №6 - Анализ медиа файлов и аватарок юзеров
├── teleguard_bot.py    # Telegram бот
├── README.md           # Документация
└── requirements.txt    # Зависимости (Все необходимые библиотеки)
```

## 📋 Особенности Mistral AI конфигурации

### ✅ Преимущества Mistral AI:
- **Производительность**: Быстрые ответы и низкая латентность
- **Качество**: Отличное понимание русского языка
- **Безопасность**: Без safe_mode для точной модерации
- **Гибкость**: Поддержка разных моделей от 7B до Large

### 🔧 Поддерживаемые переменные:

#### AI API Keys:
- `MISTRAL_API_KEY` - ключ Mistral AI API
- `MISTRAL_MODEL` - модель (по умолчанию mistral-large-latest)
- `AI_PROVIDER` - провайдер ИИ (mistral)

#### Telegram:
- `TELEGRAM_BOT_TOKEN` - токен Telegram бота

#### База данных:
- `POSTGRES_URL` - полная строка подключения
- `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`

#### Redis:
- `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB`, `REDIS_PASSWORD`

#### Приложение:
- `DEBUG` - режим отладки (true/false)
- `LOG_LEVEL` - уровень логирования (INFO, DEBUG, WARNING, ERROR)
- `TIMEZONE` - часовой пояс (по умолчанию Europe/Moscow)

### 🔒 Безопасность .env (Mistral AI):

#### Пример .env.example для Mistral AI:
```bash
# .env.example (без реальных значений)
MISTRAL_API_KEY=your-mistral-api-key
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
POSTGRES_URL=postgresql://user:password@host:port/database
AI_PROVIDER=mistral
MISTRAL_MODEL=mistral-large-latest
# ... остальные переменные
```

## 📊 Мониторинг системы (Mistral AI версия)

### Команды для проверки:
```bash
# Проверка конфигурации Mistral AI
python3 -c "from config import validate_config; validate_config(); print('✅ Конфигурация Mistral AI корректна')"

# Статус всех агентов с информацией о Mistral AI
for port in 8001 8002 8003 8004 8005; do
  echo "Агент на порту $port:"
  curl -s http://localhost:$port/health | jq '.ai_provider'
done

# Проверка логов с информацией о Mistral AI
tail -f *.log | grep -E "(Mistral|AI|модель)"
```

### Логи содержат информацию о Mistral AI:
```
[2025-10-31 10:03:13] [АГЕНТ 2] INFO: ✅ Агент 2 запущен (Mistral AI API, v2.4)
[2025-10-31 10:03:13] [АГЕНТ 2] INFO:    Модель: mistral-large-latest
[2025-10-31 10:03:13] [АГЕНТ 3] INFO: ✅ Агент 3 запущен (Mistral AI модератор v3.6)
[2025-10-31 10:03:13] [АГЕНТ 5] INFO: ✅ Агент 5 запущен (Mistral AI арбитр v5.4)
```

## 🐛 Диагностика проблем (Mistral AI версия)

### Проблема: Ошибки Mistral AI API
```bash
# Проверьте Mistral API ключ
python3 -c "
from config import MISTRAL_API_KEY
print('Mistral API Key:', 'OK' if MISTRAL_API_KEY else 'MISSING')
print('Length:', len(MISTRAL_API_KEY) if MISTRAL_API_KEY else 0)
"

# Проверьте доступность Mistral AI
python3 -c "
from mistralai.client import MistralClient
from config import MISTRAL_API_KEY
try:
    client = MistralClient(api_key=MISTRAL_API_KEY)
    print('✅ Mistral AI клиент создан успешно')
except Exception as e:
    print(f'❌ Ошибка Mistral AI: {e}')
"
```

### Проблема: Неправильная модель Mistral AI
```bash
# Проверка поддерживаемых моделей
python3 -c "
from config import MISTRAL_MODEL, MISTRAL_SUPPORTED_MODELS
print(f'Текущая модель: {MISTRAL_MODEL}')
print(f'Поддерживается: {MISTRAL_MODEL in MISTRAL_SUPPORTED_MODELS}')
print('Доступные модели:')
for model in MISTRAL_SUPPORTED_MODELS:
    print(f'  - {model}')
"
```

### Проблема: Конфликт провайдеров ИИ
```bash
# Убедитесь что используется Mistral AI
python3 -c "
from config import AI_PROVIDER, MISTRAL_MODEL
print(f'ИИ провайдер: {AI_PROVIDER}')
print(f'Модель: {MISTRAL_MODEL}')
if AI_PROVIDER != 'mistral':
    print('⚠️ Внимание: AI_PROVIDER должен быть mistral')
"
```

## 🔄 Миграция с OpenAI на Mistral AI

### Если у вас есть OpenAI версия:
```bash
# 1. Обновите .env файл
sed -i 's/OPENAI_API_KEY/MISTRAL_API_KEY/g' .env
echo "AI_PROVIDER=mistral" >> .env
echo "MISTRAL_MODEL=mistral-large-latest" >> .env

# 2. Установите Mistral AI библиотеку
pip uninstall openai
pip install mistralai

# 3. Замените файлы агентов на Mistral AI версии
# 4. Запустите систему
python3 config.py  # Проверьте конфигурацию
```
Лицензия: MIT