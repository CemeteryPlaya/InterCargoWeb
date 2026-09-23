#!/usr/bin/env python3
"""
Django management command: check_site_health

Periodically checks if the production site (https://cargointer.kz) is alive.
If the site is down or returns a 5xx error, sends a Telegram alert message
to the user's chat ID.

Usage:
  python manage.py check_site_health [--url=https://cargointer.kz/] [--chat-id=733256345]
"""
import os
import json
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError


def send_telegram_message(bot_token, chat_id, text):
    """Send a message via Telegram Bot API."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = urllib.parse.urlencode({
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'HTML',
    }).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST')
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def check_site(url, timeout=15):
    """
    Check if the site is responding.
    Returns (is_alive, status_code, error_message).
    """
    try:
        # Use a request with browser-like headers to avoid being blocked
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            }
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.getcode()
            if 200 <= status < 500:
                return True, status, None
            else:
                return False, status, f"Server returned status {status}"
    except urllib.error.HTTPError as e:
        # 4xx is fine (site is alive), 5xx is a problem
        if e.code < 500:
            return True, e.code, None
        return False, e.code, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return False, 0, f"Connection error: {str(e.reason)}"
    except Exception as e:
        return False, 0, f"Unexpected error: {str(e)}"


class Command(BaseCommand):
    help = 'Check if production site is alive; send Telegram alert if down'

    def add_arguments(self, parser):
        parser.add_argument(
            '--url',
            default=os.environ.get('SITE_URL', 'https://cargointer.kz/'),
            help='Site URL to check (default: SITE_URL from env or https://cargointer.kz/)',
        )
        parser.add_argument(
            '--chat-id',
            default='733256345',
            help='Telegram chat ID to receive alerts (default: user chat)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print the check result without sending a message',
        )

    def handle(self, *args, **options):
        url = options['url'].rstrip('/')
        chat_id = options['chat_id']
        bot_token = os.environ.get('TELEGRAM_BOT_TOKEN', '')

        if not bot_token:
            # Try reading from .env
            env_path = os.path.join(os.getcwd(), '.env')
            if os.path.exists(env_path):
                with open(env_path) as f:
                    for line in f:
                        if line.startswith('TELEGRAM_BOT_TOKEN='):
                            bot_token = line.split('=', 1)[1].strip()
                            break

        is_alive, status, error = check_site(url)
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if is_alive:
            self.stdout.write(self.style.SUCCESS(
                f"[{timestamp}] ✅ Site {url} is alive (HTTP {status})"
            ))
        else:
            self.stdout.write(self.style.ERROR(
                f"[{timestamp}] ❌ Site {url} is DOWN — {error}"
            ))

            if not options['dry_run']:
                if bot_token:
                    alert_text = (
                        f"🚨 <b>Сайт упал!</b>\n\n"
                        f"URL: {url}\n"
                        f"Статус: {status or 'no response'}\n"
                        f"Ошибка: {error}\n"
                        f"Время: {timestamp}\n"
                        f"Проверьте сервер и логи приложения."
                    )
                    try:
                        result = send_telegram_message(bot_token, chat_id, alert_text)
                        if result.get('ok'):
                            self.stdout.write(self.style.WARNING(
                                f"  → Telegram alert sent to chat {chat_id}"
                            ))
                        else:
                            self.stdout.write(self.style.ERROR(
                                f"  → Failed to send Telegram alert: {result.get('error')}"
                            ))
                            self.stdout.write(self.style.WARNING(
                                f"  → NOTE: TELEGRAM_BOT_TOKEN in .env may be invalid. "
                                f"Create a new bot via @BotFather and update .env."
                            ))
                    except Exception as e:
                        self.stdout.write(self.style.ERROR(
                            f"  → Telegram API error: {e}"
                        ))
                else:
                    self.stdout.write(self.style.WARNING(
                        f"  → Bot token not found — alert not sent"
                    ))
            else:
                self.stdout.write(self.style.WARNING(
                    f"  → Dry run — no alert sent"
                ))

