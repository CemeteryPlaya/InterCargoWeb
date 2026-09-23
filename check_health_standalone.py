#!/usr/bin/env python3
"""
Standalone Site Health Monitor — не зависит от Hermes / Django.
Работает прямо на продакшн-сервере через системный cron.

Проверяет https://cargointer.kz/ каждые 5 минут.
Если сайт мёртв → отправляет alert в Telegram на ваш чат.

Установка:
  1. Создайте бота через @BotFather и получите токен
  2. Добавьте в .env:  TELEGRAM_BOT_TOKEN=ваш_токен_бота
  3. Добавьте в crontab:
     */5 * * * * /usr/bin/python3 /path/to/cargo/check_health_standalone.py

Или используйте уже созданный скрипт:
     */5 * * * * /bin/bash /path/to/cargo/check_health.sh
"""
import os
import sys
import json
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime


# --- Configuration (читается из .env или переменных окружения) ---
def load_env_file(path=".env"):
    """Load environment variables from .env file."""
    env_vars = {}
    if not os.path.exists(path):
        # Try parent directories
        for parent in range(1, 4):
            alt_path = os.path.join(*(['..'] * parent), path)
            if os.path.exists(alt_path):
                path = alt_path
                break
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip()
    return env_vars


# --- Settings ---
ENV = load_env_file()
SITE_URL = os.environ.get('SITE_URL', ENV.get('SITE_URL', 'https://cargointer.kz/'))
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', ENV.get('TELEGRAM_BOT_TOKEN', ''))
CHAT_ID = os.environ.get('TELEGRAM_ALERT_CHAT_ID', ENV.get('TELEGRAM_ALERT_CHAT_ID', '733256345'))
TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def send_telegram_message(token, chat_id, text):
    """Send message via Telegram Bot API."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': 'true',
    }).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST')
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode('utf-8'))


def check_site(url, timeout=15):
    """
    Check if the site is alive.
    Returns (is_alive, status_code, error_message).
    """
    try:
        req = urllib.request.Request(
            url,
            headers={'User-Agent': USER_AGENT, 'Accept': 'text/html,*/*'}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.getcode()
            if 200 <= status < 500:
                return True, status, None
            return False, status, f"Server returned HTTP {status}"
    except urllib.error.HTTPError as e:
        if e.code < 500:
            return True, e.code, None
        return False, e.code, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return False, 0, f"Connection error: {e.reason}"
    except Exception as e:
        return False, 0, f"Unexpected error: {e}"


def main():
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    is_alive, status, error = check_site(SITE_URL, TIMEOUT)

    if is_alive:
        # Site is alive — output nothing (silent on success = watchdog pattern)
        sys.exit(0)

    # Site is DOWN — send Telegram alert
    if not BOT_TOKEN:
        # No bot token configured — write to stderr/log instead
        print(f"[{timestamp}] ❌ Site {SITE_URL} is DOWN — {error}", file=sys.stderr)
        print(f"  TELEGRAM_BOT_TOKEN not set — alert not sent", file=sys.stderr)
        sys.exit(1)

    alert_text = (
        f"🚨 <b>ИнтерКарго сайт упал (резервный мониторинг)</b>\n\n"
        f"<b>URL:</b> {SITE_URL}\n"
        f"<b>Статус:</b> {status or 'no response'}\n"
        f"<b>Ошибка:</b> {error}\n"
        f"<b>Время:</b> {timestamp}\n\n"
        f"<b>Действия:</b>\n"
        f"1. Проверить gunicorn: <code>systemctl status gunicorn</code>\n"
        f"2. Проверить nginx: <code>systemctl status nginx</code>\n"
        f"3. Проверить SSH доступность сервера\n"
        f"4. Проверить логи: <code>journalctl -u gunicorn -n 50</code>"
    )

    try:
        result = send_telegram_message(BOT_TOKEN, CHAT_ID, alert_text)
        if result.get('ok'):
            print(f"[{timestamp}] ✅ Alert sent to Telegram (chat {CHAT_ID})", file=sys.stderr)
            sys.exit(0)
        else:
            print(f"[{timestamp}] ❌ Failed to send Telegram alert: {result.get('description')}", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f"[{timestamp}] ❌ Telegram API error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
