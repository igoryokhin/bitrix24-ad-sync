#!/bin/sh
set -e

# Первый запуск: если база ещё не инициализирована — делаем full_sync
if [ ! -f /app/logs/.initialized ]; then
    echo "[INIT] $(date) Первый запуск — выполняю full_sync..."
    if python /app/full_sync.py; then
        touch /app/logs/.initialized
        echo "[INIT] full_sync завершён успешно"
    else
        echo "[INIT] full_sync завершился с ошибкой — повторю при следующем старте"
    fi
fi

# Запуск планировщика
echo "[INIT] Запуск supercronic..."
exec supercronic -passthrough-logs -no-overlap /app/crontab