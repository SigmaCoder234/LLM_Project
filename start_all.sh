#!/bin/bash

# ============================================================================
# 🚀 start_all.sh — Запуск всех 6 агентов и бота одной командой
# ============================================================================

PROJECT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$PROJECT_DIR"

echo "================================================================================"
echo "🚀 TeleGuard Bot v2.9 - Запуск всех компонентов"
echo "================================================================================"

# Цвета для логирования
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Функция для запуска процесса в фоне с логированием
start_process() {
    local name=$1
    local command=$2
    local log_file=$3
    
    echo -e "${BLUE}▶ Запускаю: $name${NC}"
    nohup python3 "$command" > "$log_file" 2>&1 &
    local pid=$!
    echo -e "${GREEN}✅ $name запущен (PID: $pid)${NC}"
    
    # Сохраняем PID для последующей остановки
    echo $pid >> /tmp/teleguard_pids.txt
}

# Удаляем старый файл с PIDs
rm -f /tmp/teleguard_pids.txt

echo ""
echo -e "${YELLOW}⏳ Проверка Redis...${NC}"
redis-cli ping > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Redis не запущен! Запусти: redis-server${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Redis подключен${NC}"

echo ""
echo -e "${YELLOW}⏳ Проверка PostgreSQL...${NC}"
psql -U tg_user -d teleguard -c "SELECT 1;" > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo -e "${RED}❌ PostgreSQL не запущена или БД недоступна!${NC}"
    echo -e "${RED}   Проверь: sudo systemctl status postgresql${NC}"
    exit 1
fi
echo -e "${GREEN}✅ PostgreSQL подключена${NC}"

echo ""
echo -e "${YELLOW}⏳ Инициализация БД...${NC}"
python3 init_db.py
if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Ошибка инициализации БД!${NC}"
    exit 1
fi
echo -e "${GREEN}✅ БД инициализирована${NC}"

# Создаем папку логов если её нет
mkdir -p logs

echo ""
echo "================================================================================"
echo -e "${YELLOW}🤖 Запуск 6 агентов + Бот...${NC}"
echo "================================================================================"

# Запускаем агентов с задержкой для правильной инициализации
start_process "АГЕНТ 1 (Распределитель)" "first_agent.py" "logs/agent1.log"
sleep 2

start_process "АГЕНТ 2 (Входная очередь)" "second_agent.py" "logs/agent2.log"
sleep 2

start_process "АГЕНТ 3 (Mistral AI текст)" "third_agent.py" "logs/agent3.log"
sleep 2

start_process "АГЕНТ 4 (Эвристика)" "fourth_agent.py" "logs/agent4.log"
sleep 2

start_process "АГЕНТ 5 (Арбитр)" "fifth_agent.py" "logs/agent5.log"
sleep 2

start_process "АГЕНТ 6 (Медиа анализ)" "sixth_agent.py" "logs/agent6.log"
sleep 2

start_process "🤖 TELEGRAM БОТ" "teleguard_bot.py" "logs/bot.log"

echo ""
echo "================================================================================"
echo -e "${GREEN}✅ ВСЕ КОМПОНЕНТЫ ЗАПУЩЕНЫ!${NC}"
echo "================================================================================"
echo ""
echo -e "${BLUE}📊 Логи находятся в папке: logs/${NC}"
echo -e "${BLUE}📝 Просмотр логов:${NC}"
echo "   tail -f logs/agent1.log"
echo "   tail -f logs/agent2.log"
echo "   tail -f logs/bot.log"
echo ""
echo -e "${BLUE}🛑 Остановка всех процессов:${NC}"
echo "   ./stop_all.sh"
echo ""
echo -e "${BLUE}📌 Проверка статуса агентов:${NC}"
echo "   ps aux | grep python3"
echo ""
echo "================================================================================"
