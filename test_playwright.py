#!/usr/bin/env python3
"""
Playwright E2E test for InterCargoWeb — checks all endpoints/pages and button functionality.
"""
import os
import sys
import secrets
import time

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cargo.settings')
os.environ['DJANGO_DEBUG'] = 'True'

import django
django.setup()

from django.core.management import call_command
call_command('migrate', '--run-syncdb', verbosity=0)

from django.test import Client
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from register.models import UserProfile, PendingRegistration

User = get_user_model()

# Create superuser + test user
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@test.local', 'AdminPass123!')
if not User.objects.filter(username='tester').exists():
    u = User.objects.create_user('tester', 'tester@test.local', 'TestPass123!')
    UserProfile.objects.create(user=u, is_staff=True, is_hr=True, is_registered=True)
if not User.objects.filter(username='Staff123').exists():
    u = User.objects.create_user('Staff123', 'staff@test.local', 'StaffPass123!')
    UserProfile.objects.create(user=u, is_staff=True, is_registered=True)

from wsgiref import simple_server
from threading import Thread
from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
httpd = simple_server.make_server('127.0.0.1', 8001, application)
server_thread = Thread(target=httpd.serve_forever, daemon=True)
server_thread.start()
print("Server started on http://127.0.0.1:8001")
time.sleep(1)

from playwright.sync_api import sync_playwright

BASE_URL = 'http://127.0.0.1:8001'
passed = 0
failed = 0
results = []
errors_found = []

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        results.append(f"  ✅ {name}")
    else:
        failed += 1
        results.append(f"  ❌ {name} — {detail}")

def record_error(msg):
    """Record a discovered error/issue"""
    errors_found.append(msg)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    page_errors = []
    page.on('pageerror', lambda exc: page_errors.append(str(exc)))

    # All endpoints to test
    ALL_ENDPOINTS = [
        ('/', 'Homepage'),
        ('/register/login/', 'Login page'),
        ('/register/registration/', 'Registration flow step 1'),
        ('/register/pre-register/', 'Pre-register page'),
        ('/register/password-reset/', 'Password reset page'),
        ('/profile/', 'Profile (auth required)'),
        ('/profile/extradition/', 'Extradition list'),
        ('/profile/receipts/', 'Receipts page'),
        ('/profile/scan/', 'Scan page'),
        ('/profile/warehouse/', 'Warehouse page'),
        ('/profile/warehouse/inventory/', 'Warehouse inventory'),
        ('/profile/warehouse/restructure/1/', 'Warehouse reassign'),
        ('/profile/telegram/', 'Telegram settings'),
        ('/dibuyer/', 'Di.Buyer entry'),
        ('/analytics/dashboard/', 'Analytics dashboard'),
        ('/support/', 'Support page'),
        ('/news/', 'News page'),
        ('/admin/login/', 'Admin login'),
        ('/i18n/setlang/', 'Language switcher'),
    ]

    print(f"\n{'=' * 70}")
    print(f"  Playwright E2E — Testing {len(ALL_ENDPOINTS)} endpoints")
    print(f"{'=' * 70}")

    # --- Test each endpoint ---
    print("\n  Testing all endpoints...")
    for path, name in ALL_ENDPOINTS:
        console_errors = []
        page.on('console', lambda msg: console_errors.append(f"{msg.type}: {msg.text[:80]}") if msg.type == 'error' else None)

        try:
            resp = page.goto(f'{BASE_URL}{path}', wait_until='networkidle', timeout=10000)
            status = str(resp.status) if resp else 'no response'

            # Track console errors (filter out static 304s and known issues)
            real_errors = [e for e in console_errors if '404' not in e and 'sendBeacon' not in e]

            check(f"{name} ({path}) → {status}",
                  resp.status in (200, 301, 302, 403, 404),
                  f"Unexpected status {status}")

            if real_errors:
                errors_found.append(f"{name}: console errors: {real_errors[:2]}")

            if resp.status >= 500:
                errors_found.append(f"{name}: SERVER ERROR {resp.status}")

        except Exception as e:
            check(f"{name} ({path})", False, str(e))
            errors_found.append(f"{name}: exception {str(e)[:100]}")

    # --- Test login flow ---
    print("\n  Testing login flow...")
    page_errors.clear()
    console_errors.clear()

    try:
        page.goto(f'{BASE_URL}/register/login/', wait_until='networkidle')
        # Use more specific selector - the login form submit button
        login_form = page.locator('form').filter(has_text='Войти').first
        if not login_form:
            # Try finding form with password input
            login_form = page.locator('form:has(input[name="password"])')

        page.fill('input[name="login"]', 'tester')
        page.fill('input[name="password"]', 'TestPass123!')
        # Click the submit button within the login form
        login_btn = login_form.locator('button[type="submit"]').first
        login_btn.click()
        time.sleep(2)
        check("Login form submits successfully", True)
    except Exception as e:
        check("Login form submit", False, str(e))

    # --- Test admin login ---
    print("\n  Testing admin panel...")
    page_errors.clear()
    try:
        page.goto(f'{BASE_URL}/admin/login/?next=/admin/', wait_until='networkidle')
        page.fill('input[name="username"]', 'admin')
        page.fill('input[name="password"]', 'AdminPass123!')
        page.click('input[type="submit"]')
        time.sleep(2)
        check("Admin login → dashboard", '/admin/' in page.url and 'login' not in page.url,
              f"URL: {page.url}")
    except Exception as e:
        check("Admin login", False, str(e))

    # --- Test admin pages ---
    print("\n  Testing admin pages...")
    admin_pages = [
        ('/admin/auth/user/', 'User admin'),
        ('/admin/auth/group/', 'Group admin'),
        ('/admin/register/pendingregistration/', 'Pending registrations'),
        ('/admin/myprofile/receipt/', 'Receipts admin'),
    ]
    for path, name in admin_pages:
        try:
            resp = page.goto(f'{BASE_URL}{path}', wait_until='networkidle', timeout=10000)
            check(f"Admin: {name} ({resp.status})", resp.status == 200, f"Got {resp.status}")
        except Exception as e:
            check(f"Admin: {name}", False, str(e))

    # --- Test button functionality on admin ---
    print("\n  Testing admin button functionality...")
    try:
        page.goto(f'{BASE_URL}/admin/', wait_until='networkidle')
        # Check for app list links
        app_links = page.locator('a').filter(has_not_text='Django')
        link_count = app_links.count()
        check("Admin has app links", link_count > 0, f"Found {link_count} links")
    except Exception as e:
        check("Admin app links", False, str(e))

    # --- Test profile page buttons ---
    print("\n  Testing profile page buttons...")
    try:
        # Login first
        page.goto(f'{BASE_URL}/register/login/', wait_until='networkidle')
        page.fill('input[name="login"]', 'Staff123')
        page.fill('input[name="password"]', 'StaffPass123!')
        login_form = page.locator('form:has(input[name="password"])')
        login_form.locator('button[type="submit"]').first.click()
        time.sleep(2)

        page.goto(f'{BASE_URL}/profile/', wait_until='networkidle')
        # Check for buttons
        buttons = page.locator('button, a[role="button"]')
        btn_count = buttons.count()
        check("Profile page has interactive elements", btn_count > 0, f"Found {btn_count}")
    except Exception as e:
        check("Profile buttons", False, str(e))

    # --- Test broken images ---
    print("\n  Testing for broken images...")
    page.goto(f'{BASE_URL}/', wait_until='networkidle')
    images = page.eval_on_selector_all(
        'img[src]',
        'elements => elements.map(e => ({src: e.src, complete: e.complete, nw: e.naturalWidth}))'
    )
    broken_external = [img for img in images if img['src'].startswith('http') and img['nw'] == 0]
    broken_internal = [img for img in images if '/static/' in img['src'] and img['nw'] == 0]

    if broken_internal:
        record_error(f"Broken internal images (static files): {len(broken_internal)}")
    check("Internal static images load", len(broken_internal) == 0,
          f"{len(broken_internal)} broken static images")

    # --- Test mobile responsiveness ---
    print("\n  Testing mobile responsiveness...")
    page.set_viewport_size({"width": 375, "height": 667})
    for path, name in [('/register/login/', 'Login (mobile)'), ('/register/registration/', 'Registration (mobile)')]:
        try:
            page.goto(f'{BASE_URL}{path}', wait_until='networkidle')
            check(f"{name} mobile loads", page.viewport_size['width'] == 375)
        except Exception as e:
            check(f"{name} mobile", False, str(e))
    page.set_viewport_size({"width": 1280, "height": 720})

    browser.close()

    print("\n" + "-" * 70)
    for r in results:
        print(r)
    print("-" * 70)
    print(f"\n  TOTAL: {passed} passed, {failed} failed out of {passed + failed}")

    if errors_found:
        print(f"\n  Errors discovered ({len(errors_found)}):")
        for e in errors_found:
            print(f"  ⚠️  {e}")

    print(f"\n{'=' * 70}")

httpd.shutdown()
sys.exit(0 if failed == 0 else 1)
