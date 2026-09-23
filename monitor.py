#!/usr/bin/env python3
"""
Production Site Health Monitor for InterCargoWeb.

Standalone script that runs on the production server via system crontab.
Checks two things every 5 minutes:
  1. Server uptime — pings https://cargointer.kz/
  2. Data integrity — scans for NEW ContractViolation records

If either check fails, sends a Telegram alert to your chat.

Installation (on production server):
  1. Place this script at: /opt/cargo/monitor.py
  2. Ensure .env with TELEGRAM_BOT_TOKEN is at /opt/cargo/.env
  3. Add to crontab (crontab -e):
     */5 * * * * /usr/bin/python3 /opt/cargo/monitor.py >> /var/log/cargo_health.log 2>&1

NO dependency on Hermes — works purely from the production server with Django ORM.
"""
import os
import sys
import json
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta


# ─── Configuration ───────────────────────────────────────────────────────────
LOGIN_USERNAME = "SANZHAR0802"               # Your login on the site
SITE_URL = "https://cargointer.kz/"
CHECK_INTERVAL_MINUTES = 5                   # How often this script runs via cron
CHECK_TIMEOUT = 15                           # Seconds to wait for site response
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitor_state.json")  # Tracks last-seen violation IDs
FALLBACK_CHAT_ID = 733256345                 # Your known Telegram chat ID

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


# ─── Env & DB helpers ────────────────────────────────────────────────────────

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


def setup_django():
    """Set up Django environment for ORM access."""
    env = load_env()
    if not env:
        env = load_env("../../.env")
    settings_module = env.get('DJANGO_SETTINGS_MODULE', 'cargo.settings')
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', settings_module)
    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())
    import django
    django.setup()
    return env


# ─── Telegram ────────────────────────────────────────────────────────────────

def get_telegram_config():
    """
    Look up Telegram bot token and chat ID.
    Tries DB lookup by username (SANZHAR0802), falls back to env + hardcoded.
    Returns (bot_token, chat_id, lookup_info) or (None, None, error_msg).
    """
    env = load_env()
    token = env.get('TELEGRAM_BOT_TOKEN', '')

    if not token:
        return None, None, "TELEGRAM_BOT_TOKEN not found in .env"

    # Try DB lookup for user SANZHAR0802
    chat_id = None
    try:
        setup_django()
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.get(username=LOGIN_USERNAME)
        profile = user.telegram_profile
        chat_id = profile.telegram_chat_id
        return token, chat_id, f"DB lookup: @{profile.telegram_username} (user={LOGIN_USERNAME})"
    except Exception as e:
        return token, FALLBACK_CHAT_ID, f"DB lookup failed ({e}); using fallback chat_id={FALLBACK_CHAT_ID}"


def send_telegram_message(bot_token, chat_id, text):
    """Send a message via Telegram Bot API."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
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


# ─── Health check ────────────────────────────────────────────────────────────

def check_site(url, timeout=15):
    """Check if site is alive. Returns (is_alive, status_code, error_message)."""
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': USER_AGENT,
            'Accept': 'text/html,*/*'
        })
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


# ─── Contract violation check ────────────────────────────────────────────────

def load_state():
    """Load the state file (tracks which violation IDs have been reported)."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_notified_violation_id": 0, "last_check": None}


def save_state(state):
    """Save state file."""
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def check_contract_violations():
    """
    Scan for NEW ContractViolation records since last check.
    Returns (list_of_violations, timestamp) or (None, error_msg) if DB not accessible.
    """
    try:
        setup_django()
        from myprofile.models import ContractViolation
        from django.utils import timezone

        now = timezone.now()
        since = now - timedelta(minutes=CHECK_INTERVAL_MINUTES + 1)  # +1 for safety

        new_violations = list(ContractViolation.objects.filter(
            created_at__gte=since
        ).order_by('-created_at')[:20])

        result = []
        for v in new_violations:
            result.append({
                'id': v.id,
                'created_at': v.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'severity': v.severity,
                'function': v.function,
                'contract': v.contract,
                'message': v.message,
                'resolved': v.resolved,
            })
        return result, now.strftime('%Y-%m-%d %H:%M:%S')

    except Exception as e:
        return None, str(e)


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    state = load_state()

    # ─── 1. Server health check ───
    is_alive, status, error = check_site(SITE_URL, CHECK_TIMEOUT)

    if not is_alive:
        # Site is DOWN — this is critical
        bot_token, chat_id, lookup_info = get_telegram_config()

        if bot_token:
            alert_text = (
                f"🚨 <b>INTERCARGO САЙТ УПАЛ!</b>\n\n"
                f"<b>URL:</b> {SITE_URL}\n"
                f"<b>Статус:</b> {status or 'no response'}\n"
                f"<b>Ошибка:</b> {error}\n"
                f"<b>Время:</b> {timestamp}\n\n"
                f"<b>Получатель:</b> {lookup_info}\n\n"
                f"<b>Действия:</b>\n"
                f"1. systemctl status gunicorn\n"
                f"2. systemctl status nginx\n"
                f"3. journalctl -u gunicorn -n 50 --no-pager\n"
                f"4. python manage.py check --deploy"
            )
            try:
                result = send_telegram_message(bot_token, chat_id, alert_text)
                if result.get('ok'):
                    print(f"[{timestamp}] ✅ Server-down alert sent to Telegram chat {chat_id}", file=sys.stderr)
                else:
                    print(f"[{timestamp}] ❌ Telegram error: {result.get('description')}", file=sys.stderr)
            except Exception as e:
                print(f"[{timestamp}] ❌ Telegram API error: {e}", file=sys.stderr)
        else:
            print(f"[{timestamp}] ❌ Site DOWN — {error} — bot token not set", file=sys.stderr)

        sys.exit(1)

    # Site is alive — silent (watchdog: no output on success for server check)

    # ─── 2. Contract violation check ───
    violations, check_info = check_contract_violations()

    if violations is None:
        # DB not accessible — skip (could be DB restart during deploy)
        print(f"[{timestamp}] ⚠️ ContractViolation DB check skipped: {check_info}", file=sys.stderr)
        sys.exit(0)

    if not violations:
        # No new violations — silent (watchdog pattern)
        sys.exit(0)

    # Filter out already-notified violations (dedupe using state file)
    last_notified_id = state.get("last_notified_violation_id", 0)
    new_unreported = [v for v in violations if v['id'] > last_notified_id]

    if not new_unreported:
        # All violations were already reported
        sys.exit(0)

    # Update state with the highest ID we've seen
    max_id = max(v['id'] for v in violations)
    state["last_notified_violation_id"] = max_id
    state["last_check"] = check_info
    save_state(state)

    # Send alert
    bot_token, chat_id, lookup_info = get_telegram_config()

    if not bot_token:
        print(f"[{timestamp}] ⚠️ {len(new_unreported)} new ContractViolation(s) — but bot token not set", file=sys.stderr)
        for v in new_unreported:
            print(f"  [{v['severity']}] [{v['created_at']}] {v['function']} :: {v['contract']} — {v['message']}", file=sys.stderr)
        sys.exit(0)

    # Format message for Telegram
    msg_lines = []
    for v in new_unreported[:10]:  # Cap at 10 in message
        emoji = "🔴" if v['severity'] == 'critical' else "🟡"
        msg_lines.append(
            f"{emoji} <b>{v['severity'].upper()}</b>\n"
            f"  Функция: <code>{v['function']}</code>\n"
            f"  Контракт: <code>{v['contract']}</code>\n"
            f"  Сообщение: {v['message']}\n"
            f"  Время: {v['created_at']}"
        )

    if len(new_unreported) > 10:
        msg_lines.append(f"\n... и ещё {len(new_unreported) - 10} нарушений")

    alert_text = (
        f"⚠️ <b>Новые нарушения контракта данных</b>\n"
        f"Количество: {len(new_unreported)}\n"
        f"Сайт: {SITE_URL}\n\n"
        f"{chr(10).join(msg_lines)}\n\n"
        f"<i>Журнал: /admin/myprofile/contractviolation/</i>"
    )

    try:
        result = send_telegram_message(bot_token, chat_id, alert_text)
        if result.get('ok'):
            print(f"[{timestamp}] ✅ ContractViolation alert sent ({len(new_unreported)} new)", file=sys.stderr)
        else:
            print(f"[{timestamp}] ❌ Telegram error: {result.get('description')}", file=sys.stderr)
    except Exception as e:
        print(f"[{timestamp}] ❌ Telegram API error: {e}", file=sys.stderr)

    sys.exit(0)


if __name__ == '__main__':
    main()
