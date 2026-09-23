#!/usr/bin/env python3
"""
Production Site Health Monitor for InterCargoWeb.

Standalone script that runs on the production server via system crontab.
Look up your Telegram chat ID by username (SANZHAR0802) in the Django DB,
check if the site is alive, and send a Telegram alert if it's down.

NO dependency on Hermes — works purely from the production server.

Installation (on production server):
  1. Place this script at: /opt/cargo/monitor.py
  2. Ensure .env with TELEGRAM_BOT_TOKEN is at /opt/cargo/.env
  3. Add to crontab (crontab -e):
     */5 * * * * /usr/bin/python3 /opt/cargo/monitor.py >> /var/log/cargo_health.log 2>&1
"""
import os
import sys
import json
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime


# --- CONFIGURATION ---
LOGIN_USERNAME = "SANZHAR0802"         # User's login on the site
SITE_URL = "https://cargointer.kz/"
CHECK_TIMEOUT = 15                     # seconds to wait for site response
# Fallback chat ID if DB lookup fails (your known chat ID)
FALLBACK_CHAT_ID = 733256345

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def load_env(path=".env"):
    """Load .env file into dict."""
    env = {}
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    env[k.strip()] = v.strip()
    return env


def get_telegram_chat_id():
    """
    Look up Telegram chat ID from the database by username.
    Falls back to FALLBACK_CHAT_ID if DB lookup fails.
    """
    env = load_env()
    token = env.get('TELEGRAM_BOT_TOKEN', '')

    if not token:
        return None, FALLBACK_CHAT_ID, "TELEGRAM_BOT_TOKEN not found in .env"

    # Try to look up via Django ORM
    try:
        # Set Django settings module
        settings_module = env.get('DJANGO_SETTINGS_MODULE', 'cargo.settings')
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', settings_module)

        # Add current directory to Python path
        if os.getcwd() not in sys.path:
            sys.path.insert(0, os.getcwd())

        import django
        django.setup()

        from django.contrib.auth import get_user_model
        User = get_user_model()

        try:
            user = User.objects.get(username=LOGIN_USERNAME)
            profile = user.telegram_profile
            chat_id = profile.telegram_chat_id
            tg_username = profile.telegram_username or "N/A"
            return token, chat_id, f"Found via DB: user={user.username}, tg_user=@{tg_username}"
        except Exception as e:
            return token, FALLBACK_CHAT_ID, f"DB lookup failed ({e}), using fallback chat_id"

    except ImportError:
        return token, FALLBACK_CHAT_ID, "Django not available, using fallback chat_id"
    except Exception as e:
        return token, FALLBACK_CHAT_ID, f"DB error ({e}), using fallback chat_id"


def send_telegram_message(token, chat_id, text):
    """Send a message via Telegram Bot API."""
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
    """Check if site is alive. Returns (is_alive, status_code, error)."""
    try:
        req = urllib.request.Request(
            url,
            headers={'User-Agent': USER_AGENT, 'Accept': 'text/html,*/*'}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.getcode()
            if 200 <= status < 500:
                return True, status, None
            return False, status, f"HTTP {status}"
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
    is_alive, status, error = check_site(SITE_URL, CHECK_TIMEOUT)

    if is_alive:
        # Site is alive — silent (watchdog pattern: no output on success)
        sys.exit(0)

    # Site is DOWN — send Telegram alert
    bot_token, chat_id, lookup_info = get_telegram_chat_id()

    if not bot_token:
        print(f"[{timestamp}] ❌ Site {SITE_URL} is DOWN — {error}", file=sys.stderr)
        print(f"  TELEGRAM_BOT_TOKEN not set — alert NOT sent", file=sys.stderr)
        sys.exit(1)

    alert_text = (
        f"🚨 <b>INTERCARGO САЙТ УПАЛ!</b>\n\n"
        f"<b>URL:</b> {SITE_URL}\n"
        f"<b>Статус:</b> {status or 'no response'}\n"
        f"<b>Ошибка:</b> {error}\n"
        f"<b>Время:</b> {timestamp}\n"
        f"<b>Получатель:</b> {lookup_info}\n\n"
        f"<b>Действия:</b>\n"
        f"1. systemctl status gunicorn\n"
        f"2. systemctl status nginx\n"
        f"3. journalctl -u gunicorn -n 50 --no-pager\n"
        f"4. Проверить SSH доступность сервера\n"
        f"5. python manage.py check --deploy"
    )

    try:
        result = send_telegram_message(bot_token, chat_id, alert_text)
        if result.get('ok'):
            print(f"[{timestamp}] ✅ Alert sent to Telegram chat {chat_id}", file=sys.stderr)
            sys.exit(0)
        else:
            print(f"[{timestamp}] ❌ Telegram error: {result.get('description')}", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f"[{timestamp}] ❌ Telegram API error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
