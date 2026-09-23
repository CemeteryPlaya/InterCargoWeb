#!/bin/bash
# Health check script for InterCargoWeb
# Checks if https://cargointer.kz is alive.
# If site is DOWN, outputs alert message (which gets delivered via cronjob to Telegram).
# If site is UP, outputs nothing (watchdog pattern — no spam to user).

SITE_URL="https://cargointer.kz/"
TIMEOUT=15
USER_AGENT="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"

# Check site health
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  --max-time "$TIMEOUT" \
  -A "$USER_AGENT" \
  "$SITE_URL" 2>/dev/null)

if [ -z "$HTTP_STATUS" ] || [ "$HTTP_STATUS" = "000" ]; then
  # Site is unreachable — connection failed
  echo "🚨 Сайт InterCargoWeb ❌ НЕДОСТУПЕН"
  echo ""
  echo "URL: $SITE_URL"
  echo "Ошибка: Не удалось установить соединение (connection refused/timeout)"
  echo "Время: $(date +'%Y-%m-%d %H:%M:%S')"
  echo ""
  echo "Действия:"
  echo "  1. Проверьте, запущен ли gunicorn/uwsgi"
  echo "  2. Проверьте, доступен ли сервер по SSH"
  echo "  3. Проверьте логи: journalctl -u cargointer -f"
  echo "  4. Проверьте nginx: sudo systemctl status nginx"
elif [ "$HTTP_STATUS" -ge 500 ]; then
  # Server error
  echo "🚨 Сайт InterCargoWeb ❌ ОШИБКА СЕРВЕРА"
  echo ""
  echo "URL: $SITE_URL"
  echo "Статус: HTTP $HTTP_STATUS"
  echo "Время: $(date +'%Y-%m-%d %H:%M:%S')"
  echo ""
  echo "Действия:"
  echo "  1. Проверьте логи приложения: tail -f /var/log/cargointer/error.log"
  echo "  2. Проверьте миграции: python manage.py showmigrations"
  echo "  3. Проверьте БД: python manage.py check"
else
  # Site is alive — output nothing (watchdog pattern)
  # Only output minimal status if verbose is needed
  :
fi
