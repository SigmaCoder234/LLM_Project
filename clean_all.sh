#!/bin/bash

# 🧹 ОЧИСТКА БД И REDIS

echo "🧹 ОЧИСТКА TELEGUARD..."

# Подключаемся к PostgreSQL и удаляем всё
psql -U tg_user -d teleguard -c "DELETE FROM negative_messages;"
psql -U tg_user -d teleguard -c "DELETE FROM media_files;"
psql -U tg_user -d teleguard -c "DELETE FROM messages;"
psql -U tg_user -d teleguard -c "DELETE FROM moderators;"
psql -U tg_user -d teleguard -c "DELETE FROM chats;"

echo "✅ БД очищена"

# Очищаем Redis
redis-cli FLUSHDB

echo "✅ Redis очищена"
echo "🎯 Система готова к новому тестированию!"
