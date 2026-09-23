#!/bin/bash
# check_health.sh — Standalone Site Health Monitor for InterCargoWeb
#
# Проверяет https://cargointer.kz/ и если сайт упал — присылает alert в Telegram.
# Работает на продакшн-сервере через системный cron (без зависимости от Hermes/Django).
#
# Установка на продакшн-сервер:
#   1. Скопируйте этот скрипт на сервер:  scp check_health.sh user@server:/opt/cargo/
#   2. Создайте бота через @BotFather, получите токен
#   3. Добавьте в crontab (crontab -e):
#      */5 * * * * BOT_TOKEN="ваш_токен" CHAT_ID="733256345" /bin/bash /opt/cargo/check_health.sh
#
# Либо добавьте переменные в ~/.bashrc или /etc/environment:
#   TELEGRAM_BOT_TOKEN=ваш_токен_бота
#   TELEGRAM_ALERT_CHAT_ID=733256345

set -euo pipefail

SITE_URL="${SITE_URL:-https://cargointer.kz/}"
BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-${BOT_TOKEN:-}}"
CHAT_ID="${TELEGRAM_ALERT_CHAT_ID:-${CHAT_ID:-733256345}}"
TIMEOUT="${TIMEOUT:-15}"
USER_AGENT="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Function to send Telegram message
send_telegram() {
    local text="$1"
    if [ -z "$BOT_TOKEN" ]; then
        echo "ERROR: TELEGRAM_BOT_TOKEN not set — cannot send alert" >&2
        return 1
    fi
    curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
        -d chat_id="${CHAT_ID}" \
        --data-urlencode "text=${text}" \
        --data-urlencode "parse_mode=HTML" \
        --max-time 10 \
        >/dev/null 2>&1 || true
}

# Check site health
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    --max-time "$TIMEOUT" \
    -A "$USER_AGENT" \
    "$SITE_URL" 2>/dev/null || echo "000")

TIMESTAMP=$(date +'%Y-%m-%d %H:%M:%S')

if [ -z "$HTTP_STATUS" ] || [ "$HTTP_STATUS" = "000" ]; then
    # Site is unreachable — connection failed
    echo "Site $SITE_URL is DOWN — connection refused/timeout" >&2
    if [ -n "$BOT_TOKEN" ]; then
        send_telegram "🚨 <b>ИнтерКарго сайт упал!</b>

<b>URL:</b> ${SITE_URL}
<b>Ошибка:</b> Не удалось установить соединение
<b>Время:</b> ${TIMESTAMP}

<b>Действия:</b>
1. systemctl status gunicorn
2. systemctl status nginx
3. journalctl -u gunicorn -n 50 --no-pager
4. Проверить SSH доступность сервера"
        echo "Telegram alert sent to chat ${CHAT_ID}" >&2
    else
        echo "TELEGRAM_BOT_TOKEN not set — alert not sent" >&2
    fi
    exit 1
elif [ "$HTTP_STATUS" -ge 500 ]; then
    # Server error
    echo "Site $SITE_URL returned HTTP $HTTP_STATUS" >&2
    if [ -n "$BOT_TOKEN" ]; then
        send_telegram "🚨 <b>Сайт InterCargoWeb ❌ ОШИБКА СЕРВЕРА</b>

<b>URL:</b> ${SITE_URL}
<b>Статус:</b> HTTP ${HTTP_STATUS}
<b>Время:</b> ${TIMESTAMP}

<b>Действия:</b>
1. journalctl -u gunicorn -n 50 --no-pager
2. tail -f /var/log/cargointer/error.log
3. python manage.py check --deploy"
        echo "Telegram alert sent to chat ${CHAT_ID}" >&2
    else
        echo "TELEGRAM_BOT_TOKEN not set — alert not sent" >&2
    fi
    exit 1
else
    # Site is alive — output nothing (watchdog pattern: silent on success)
    exit 0
fi
