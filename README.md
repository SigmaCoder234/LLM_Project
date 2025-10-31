# 🤖 TeleGuard - Многоагентная система модерации Telegram (Mistral AI версия)

Интеллектуальная система модерации для Telegram-чатов с использованием **Mistral AI** и пяти специализированных агентов для анализа сообщений в реальном времени.

## 🆕 Что нового в Mistral AI версии

### 🧠 **ИИ провайдер: Mistral AI**
- ✅ Использует **Mistral AI API** вместо OpenAI
- ✅ Модель по умолчанию: `mistral-large-latest`
- ✅ Поддержка всех Mistral моделей (от `open-mistral-7b` до `mistral-large-latest`)
- ✅ Отключен safe_mode для более точной модерации

### ⚙️ **Централизованная конфигурация (.env):**
- ✅ Все настройки в файле `.env`
- ✅ Единый файл `config.py` для всех агентов
- ✅ Автоматическая валидация Mistral API ключа
- ✅ Безопасное хранение токенов и паролей

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

### 🔒 **Доступ только администраторам:**
- Все функции бота доступны только администраторам групповых чатов
- Обычные пользователи видят: "Тебе тут делать нечего"
- Автоматическая проверка прав при каждом действии

## 🧠 ИИ Провайдер: Mistral AI

Все агенты используют **Mistral AI API** с обновленными промптами:
- **Агент №2**: Mistral AI для анализа и распределения
- **Агент №3**: Полный анализ через Mistral AI с новым форматом
- **Агент №4**: Эвристический анализ + Mistral AI резерв
- **Агент №5**: Mistral AI арбитр с обновленным промптом

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
# Скопируйте содержимое файла .env из проекта
cp .env.example .env
```

### 2. Заполните переменные окружения в .env:
```bash
# Mistral AI Configuration
MISTRAL_API_KEY=ygeDdoQrYFW5iM8aVw2p18pPZ1se30ow

# Telegram Bot Configuration  
TELEGRAM_BOT_TOKEN=ваш-telegram-bot-token

# Database Configuration
POSTGRES_URL=postgresql://user:password@host:port/database
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=tguser
POSTGRES_PASSWORD=ваш_пароль
POSTGRES_DB=teleguard_db

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
pip install mistralai aiogram sqlalchemy psycopg2-binary redis requests fastapi uvicorn python-dotenv
```

### 4. Подготовьте базу данных:
```sql
-- Создайте базу данных и пользователя
CREATE DATABASE teleguard_db;
CREATE USER tguser WITH PASSWORD 'ваш_пароль';
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
# Терминал 1 - Агент №1 (Координатор)
python3 first_agent.py

# Терминал 2 - Агент №2 (Анализатор Mistral AI v2.0)
python3 second_agent.py

# Терминал 3 - Агент №3 (Mistral AI модератор v2.0)
python3 third_agent.py

# Терминал 4 - Агент №4 (Эвристический + Mistral AI)
python3 fourth_agent.py

# Терминал 5 - Агент №5 (Арбитр Mistral AI v2.0)
python3 fifth_agent.py

# Терминал 6 - Telegram Bot (только админы)
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

### Health Check агентов (с информацией о Mistral AI)
```bash
curl http://localhost:8001/health  # Агент 1
curl http://localhost:8002/health  # Агент 2 (Mistral AI)
curl http://localhost:8003/health  # Агент 3 (Mistral AI)
curl http://localhost:8004/health  # Агент 4 (Mistral AI резерв)
curl http://localhost:8005/health  # Агент 5 (Mistral AI арбитр)
```

Ответ теперь содержит информацию о Mistral AI:
```json
{
  "status": "online",
  "agent_id": 3,
  "ai_provider": "Mistral AI (mistral-large-latest)",
  "prompt_version": "v2.0 - новый формат",
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
python3 fifth_agent.py test
```

## 📁 Структура файлов (Mistral AI версия)

```
TeleGuard-Mistral/
├── .env                 # 🆕 Переменные окружения (Mistral AI)
├── config.py           # 🆕 Централизованная конфигурация (Mistral AI)
├── first_agent.py      # Агент №1 - Координатор (.env)
├── second_agent.py     # Агент №2 - Анализатор (Mistral AI)
├── third_agent.py      # Агент №3 - Mistral AI модератор
├── fourth_agent.py     # Агент №4 - Эвристика + Mistral AI
├── fifth_agent.py      # Агент №5 - Арбитр Mistral AI
├── teleguard_bot.py    # Telegram бот (.env + Mistral AI)
├── README.md           # Документация (Mistral AI версия)
└── requirements.txt    # Зависимости Python (Mistral AI)
```

## 📋 Особенности Mistral AI конфигурации

### ✅ Преимущества Mistral AI:
- **Производительность**: Быстрые ответы и низкая латентность
- **Качество**: Отличное понимание русского языка
- **Безопасность**: Отключен safe_mode для точной модерации
- **Гибкость**: Поддержка разных моделей от 7B до Large
- **Стоимость**: Конкурентные цены по сравнению с OpenAI

### 🔧 Поддерживаемые переменные (Mistral AI):

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
MISTRAL_API_KEY=your-mistral-api-key-here
TELEGRAM_BOT_TOKEN=your-telegram-bot-token-here
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

## 💰 Стоимость использования Mistral AI

### Примерные цены (на октябрь 2025):
- **mistral-large-latest**: ~$8/1M токенов (input), ~$24/1M токенов (output)
- **mistral-medium-latest**: ~$2.7/1M токенов (input), ~$8.1/1M токенов (output)
- **mistral-small-latest**: ~$1/1M токенов (input), ~$3/1M токенов (output)
- **open-mistral-7b**: ~$0.25/1M токенов (input), ~$0.25/1M токенов (output)

### Оптимизация расходов:
- Используйте `mistral-small-latest` для простых задач
- `mistral-large-latest` для сложной модерации
- Настройте `max_tokens` в конфигурации
- Мониторьте использование через Mistral AI Dashboard

## 🆘 Поддержка (Mistral AI версия)

### Часто задаваемые вопросы:

**Q: Какую модель Mistral AI выбрать?**
A: Для продакшна рекомендуется `mistral-large-latest`. Для тестов подойдет `mistral-small-latest`.

**Q: Как получить Mistral API ключ?**
A: Зарегистрируйтесь на https://console.mistral.ai/ и получите API ключ в разделе API Keys.

**Q: Можно ли смешивать OpenAI и Mistral AI?**
A: Нет, система использует один провайдер ИИ. Для смешивания нужна кастомная разработка.

**Q: Mistral AI поддерживает русский язык?**
A: Да, все модели Mistral AI отлично работают с русским языком.

**Q: Как мониторить расходы на Mistral AI?**
A: Используйте Mistral AI Dashboard или интегрируйте мониторинг через API.

### Техническая поддержка (Mistral AI версия):
- 📧 Email: support@teleguard.bot
- 💬 Telegram: @teleguard_support  
- 🐛 Issues: GitHub Issues
- 📖 Docs: README.md (Mistral AI version)
- 🧠 Mistral AI Docs: https://docs.mistral.ai/

---

**Версия:** 2.0 Mistral AI (.env конфигурация)  
**Дата обновления:** 31.10.2025  
**ИИ провайдер:** Mistral AI (mistral-large-latest)  
**Новые функции:** Mistral AI интеграция, .env конфигурация, улучшенная производительность  
**Конфигурация:** Environment variables (.env файл)  
**Лицензия:** MIT

## 🚀 **Готово к запуску с Mistral AI!**

Система полностью переведена на **Mistral AI** и готова к продакшн развертыванию. Все агенты используют единую конфигурацию из `.env` файла и обеспечивают высокое качество модерации с отличной производительностью.