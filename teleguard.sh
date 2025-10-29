#!/bin/bash

###############################################################################
# 🚀 TeleGuard Automation Script
# Полный скрипт для управления системой модерации Telegram
# 
# Использование:
#   bash teleguard.sh start      - Запустить всю систему
#   bash teleguard.sh stop       - Остановить всю систему
#   bash teleguard.sh restart    - Перезагрузить систему
#   bash teleguard.sh status     - Проверить статус
#   bash teleguard.sh logs       - Показать логи
#   bash teleguard.sh clean      - Очистить базы данных
#   bash teleguard.sh delete     - Удалить папку LLM_Project
#   bash teleguard.sh clone      - Клонировать репо
#   bash teleguard.sh full-setup - Полная установка с нуля
###############################################################################

set -e

# === ЦВЕТА ДЛЯ ВЫВОДА ===
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# === КОНФИГУРАЦИЯ ===
PROJECT_DIR="$HOME/LLM_Project"
REPO_URL="https://github.com/SigmaCoder234/LLM_Project.git"
POSTGRES_HOST="176.108.248.211"
POSTGRES_PORT="5432"
POSTGRES_DB="teleguard_db"
POSTGRES_USER="tguser"
POSTGRES_PASS="mnvm7110"
REDIS_HOST="localhost"
REDIS_PORT="6379"

# === ФУНКЦИИ ===

print_header() {
    echo -e "${BLUE}================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}================================${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

# === ПРОВЕРКА ЗАВИСИМОСТЕЙ ===

check_dependencies() {
    print_header "Проверка зависимостей"
    
    # Проверка Python
    if ! command -v python3 &> /dev/null; then
        print_error "Python 3 не установлен"
        exit 1
    fi
    print_success "Python 3 установлен: $(python3 --version)"
    
    # Проверка PostgreSQL клиента
    if ! command -v psql &> /dev/null; then
        print_warning "psql не установлен. Установите: sudo apt install postgresql-client"
    else
        print_success "psql установлен"
    fi
    
    # Проверка Redis CLI
    if ! command -v redis-cli &> /dev/null; then
        print_warning "redis-cli не установлен. Установите: sudo apt install redis-tools"
    else
        print_success "redis-cli установлен"
    fi
}

# === ПРОВЕРКА ПОДКЛЮЧЕНИЯ ===

check_postgres() {
    print_info "Проверка подключения к PostgreSQL..."
    if psql -h $POSTGRES_HOST -U $POSTGRES_USER -d $POSTGRES_DB -c "SELECT 1" &> /dev/null; then
        print_success "PostgreSQL доступен"
        return 0
    else
        print_error "PostgreSQL не доступен"
        return 1
    fi
}

check_redis() {
    print_info "Проверка подключения к Redis..."
    if redis-cli -h $REDIS_HOST -p $REDIS_PORT ping &> /dev/null; then
        print_success "Redis доступен"
        return 0
    else
        print_error "Redis не доступен"
        return 1
    fi
}

# === УСТАНОВКА ЗАВИСИМОСТЕЙ PYTHON ===

install_dependencies() {
    print_header "Установка зависимостей Python"
    
    cd $PROJECT_DIR
    pip install aiogram sqlalchemy psycopg2-binary fastapi "uvicorn[standard]" httpx loguru redis aiohttp requests
    
    print_success "Все зависимости установлены"
}

# === ПОДГОТОВКА БД ===

prepare_database() {
    print_header "Подготовка PostgreSQL базы данных"
    
    sudo -u postgres psql -d $POSTGRES_DB << EOF
GRANT ALL PRIVILEGES ON SCHEMA public TO $POSTGRES_USER;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO $POSTGRES_USER;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO $POSTGRES_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO $POSTGRES_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO $POSTGRES_USER;
EOF
    
    print_success "БД готова"
}

# === ЗАПУСК КОМПОНЕНТОВ ===

start_postgres() {
    print_info "Проверка PostgreSQL..."
    if sudo systemctl is-active --quiet postgresql; then
        print_success "PostgreSQL уже запущен"
    else
        print_info "Запуск PostgreSQL..."
        sudo systemctl start postgresql
        sleep 2
        print_success "PostgreSQL запущен"
    fi
}

start_redis() {
    print_info "Проверка Redis..."
    if sudo systemctl is-active --quiet redis-server; then
        print_success "Redis уже запущен"
    else
        print_info "Запуск Redis..."
        sudo systemctl start redis-server
        sleep 1
        print_success "Redis запущен"
    fi
}

start_all_agents() {
    print_header "Запуск всех агентов и бота"
    
    cd $PROJECT_DIR
    
    # Убедимся что не запущены старые процессы
    pkill -f teteguard_bot.py || true
    pkill -f first_agent.py || true
    pkill -f second_agent.py || true
    pkill -f third_agent.py || true
    pkill -f fourth_agent.py || true
    pkill -f fifth_agent.py || true
    
    sleep 1
    
    # Запускаем все агенты
    print_info "Запуск Telegram Bot..."
    nohup python3 teteguard_bot.py > bot.log 2>&1 &
    BOT_PID=$!
    print_success "Telegram Bot запущен (PID: $BOT_PID)"
    
    print_info "Запуск Агента №1..."
    nohup python3 first_agent.py > agent1.log 2>&1 &
    AGENT1_PID=$!
    print_success "Агент №1 запущен (PID: $AGENT1_PID)"
    
    print_info "Запуск Агента №2..."
    nohup python3 second_agent.py > agent2.log 2>&1 &
    AGENT2_PID=$!
    print_success "Агент №2 запущен (PID: $AGENT2_PID)"
    
    print_info "Запуск Агента №3..."
    nohup python3 third_agent.py > agent3.log 2>&1 &
    AGENT3_PID=$!
    print_success "Агент №3 запущен (PID: $AGENT3_PID)"
    
    print_info "Запуск Агента №4..."
    nohup python3 fourth_agent.py > agent4.log 2>&1 &
    AGENT4_PID=$!
    print_success "Агент №4 запущен (PID: $AGENT4_PID)"
    
    print_info "Запуск Агента №5..."
    nohup python3 fifth_agent.py > agent5.log 2>&1 &
    AGENT5_PID=$!
    print_success "Агент №5 запущен (PID: $AGENT5_PID)"
    
    sleep 2
    
    # Проверяем что все запустились
    print_header "Проверка статуса всех процессов"
    ps aux | grep -E "(teteguard_bot|first_agent|second_agent|third_agent|fourth_agent|fifth_agent)" | grep -v grep || print_warning "Некоторые процессы не запустились"
}

stop_all_agents() {
    print_header "Остановка всех агентов и бота"
    
    pkill -f teteguard_bot.py || true
    pkill -f first_agent.py || true
    pkill -f second_agent.py || true
    pkill -f third_agent.py || true
    pkill -f fourth_agent.py || true
    pkill -f fifth_agent.py || true
    
    sleep 1
    print_success "Все процессы остановлены"
}

# === ПРОВЕРКА СТАТУСА ===

check_status() {
    print_header "Статус системы"
    
    echo -e "\n${BLUE}🗄️  PostgreSQL:${NC}"
    if check_postgres; then
        echo "Статус: ✅ Online"
    else
        echo "Статус: ❌ Offline"
    fi
    
    echo -e "\n${BLUE}🔴 Redis:${NC}"
    if check_redis; then
        echo "Статус: ✅ Online"
        REDIS_SIZE=$(redis-cli DBSIZE | grep keys | cut -d' ' -f1)
        echo "Размер БД: $REDIS_SIZE ключей"
    else
        echo "Статус: ❌ Offline"
    fi
    
    echo -e "\n${BLUE}🤖 Процессы:${NC}"
    RUNNING=$(ps aux | grep -E "(teteguard_bot|first_agent|second_agent|third_agent|fourth_agent|fifth_agent)" | grep -v grep | wc -l)
    echo "Запущено процессов: $RUNNING"
    
    if [ $RUNNING -gt 0 ]; then
        echo -e "\n${BLUE}Список процессов:${NC}"
        ps aux | grep -E "(teteguard_bot|first_agent|second_agent|third_agent|fourth_agent|fifth_agent)" | grep -v grep
    fi
    
    echo -e "\n${BLUE}🌐 Проверка API Агента №2:${NC}"
    if curl -s http://localhost:8002/health &> /dev/null; then
        print_success "API Агента №2 доступен"
        curl -s http://localhost:8002/health | python3 -m json.tool 2>/dev/null || echo "API доступен"
    else
        print_warning "API Агента №2 не доступен"
    fi
}

# === ЛОГИ ===

show_logs() {
    print_header "Логи системы"
    
    echo -e "\n${BLUE}📋 Последние 20 строк bot.log:${NC}"
    if [ -f "$PROJECT_DIR/bot.log" ]; then
        tail -20 "$PROJECT_DIR/bot.log"
    else
        print_warning "bot.log не найден"
    fi
    
    echo -e "\n${BLUE}📋 Последние 20 строк agent2.log:${NC}"
    if [ -f "$PROJECT_DIR/agent2.log" ]; then
        tail -20 "$PROJECT_DIR/agent2.log"
    else
        print_warning "agent2.log не найден"
    fi
}

# === ОЧИСТКА ===

clean_database() {
    print_header "Очистка базы данных"
    
    if ! check_postgres; then
        print_error "PostgreSQL недоступен"
        return 1
    fi
    
    sudo -u postgres psql -d $POSTGRES_DB << EOF
DELETE FROM messages;
DELETE FROM negative_messages;
DELETE FROM moderators;
DELETE FROM chats;
EOF
    
    print_success "БД очищена"
}

clean_redis() {
    print_header "Очистка Redis"
    
    if ! check_redis; then
        print_error "Redis недоступен"
        return 1
    fi
    
    redis-cli FLUSHDB
    print_success "Redis очищен"
}

# === УДАЛЕНИЕ ПАПКИ ===

delete_project() {
    print_header "Удаление проекта"
    
    if [ -d "$PROJECT_DIR" ]; then
        print_warning "Вы уверены что хотите удалить $PROJECT_DIR? (yes/no)"
        read -r response
        
        if [ "$response" = "yes" ]; then
            rm -rf "$PROJECT_DIR"
            print_success "Проект удален"
        else
            print_info "Удаление отменено"
        fi
    else
        print_warning "Папка $PROJECT_DIR не существует"
    fi
}

# === КЛОНИРОВАНИЕ РЕПО ===

clone_repo() {
    print_header "Клонирование репозитория"
    
    if [ -d "$PROJECT_DIR" ]; then
        print_warning "Папка $PROJECT_DIR уже существует. Удалить? (yes/no)"
        read -r response
        
        if [ "$response" = "yes" ]; then
            rm -rf "$PROJECT_DIR"
        else
            print_info "Клонирование отменено"
            return 1
        fi
    fi
    
    print_info "Клонирование из $REPO_URL..."
    git clone "$REPO_URL" "$PROJECT_DIR"
    
    cd "$PROJECT_DIR"
    print_success "Репо клонировано"
}

# === ПОЛНАЯ УСТАНОВКА ===

full_setup() {
    print_header "🚀 Полная установка системы с нуля"
    
    check_dependencies
    
    # Удаляем старый проект если существует
    if [ -d "$PROJECT_DIR" ]; then
        print_warning "Удаляю старый проект..."
        rm -rf "$PROJECT_DIR"
    fi
    
    # Клонируем новый
    clone_repo
    
    # Запускаем зависимости
    start_postgres
    start_redis
    
    # Подготавливаем БД
    if check_postgres; then
        prepare_database
    fi
    
    # Устанавливаем зависимости Python
    install_dependencies
    
    # Запускаем систему
    start_all_agents
    
    # Показываем статус
    check_status
    
    print_header "✅ Система готова к работе!"
}

# === ГЛАВНАЯ ФУНКЦИЯ ===

main() {
    case "${1:-help}" in
        start)
            print_header "Запуск системы"
            start_postgres
            start_redis
            sleep 1
            start_all_agents
            check_status
            ;;
        stop)
            print_header "Остановка системы"
            stop_all_agents
            ;;
        restart)
            print_header "Перезагрузка системы"
            stop_all_agents
            sleep 2
            start_postgres
            start_redis
            sleep 1
            start_all_agents
            check_status
            ;;
        status)
            check_status
            ;;
        logs)
            show_logs
            ;;
        clean)
            print_header "Очистка"
            clean_database
            clean_redis
            ;;
        delete)
            delete_project
            ;;
        clone)
            clone_repo
            ;;
        full-setup)
            full_setup
            ;;
        check-deps)
            check_dependencies
            ;;
        *)
            print_header "🤖 TeleGuard - Система управления"
            echo ""
            echo -e "${BLUE}Доступные команды:${NC}"
            echo ""
            echo -e "  ${GREEN}bash teleguard.sh start${NC}        - Запустить всю систему"
            echo -e "  ${GREEN}bash teleguard.sh stop${NC}         - Остановить всю систему"
            echo -e "  ${GREEN}bash teleguard.sh restart${NC}      - Перезагрузить систему"
            echo -e "  ${GREEN}bash teleguard.sh status${NC}       - Проверить статус"
            echo -e "  ${GREEN}bash teleguard.sh logs${NC}         - Показать логи"
            echo -e "  ${GREEN}bash teleguard.sh clean${NC}        - Очистить БД и Redis"
            echo -e "  ${GREEN}bash teleguard.sh delete${NC}       - Удалить папку проекта"
            echo -e "  ${GREEN}bash teleguard.sh clone${NC}        - Клонировать репо"
            echo -e "  ${GREEN}bash teleguard.sh full-setup${NC}   - Полная установка с нуля"
            echo -e "  ${GREEN}bash teleguard.sh check-deps${NC}   - Проверить зависимости"
            echo ""
            echo -e "${YELLOW}Примеры:${NC}"
            echo -e "  bash teleguard.sh start"
            echo -e "  bash teleguard.sh status"
            echo -e "  bash teleguard.sh logs | tail -50"
            echo ""
            ;;
    esac
}

# Запуск
main "$@"
