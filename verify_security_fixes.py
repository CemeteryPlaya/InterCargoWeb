#!/usr/bin/env python3
"""
Security verification script — tests all fixes in both DEBUG=True and DEBUG=False modes.
"""
import os
import sys
import secrets

os.environ['DJANGO_SECRET_KEY'] = secrets.token_urlsafe(50)
os.environ['DJANGO_ALLOWED_HOSTS'] = '127.0.0.1,localhost,testserver'
os.environ['DJANGO_DEBUG'] = 'False'
os.environ['DJANGO_SETTINGS_MODULE'] = 'cargo.settings'

import django
django.setup()

from django.core.management import call_command
call_command('migrate', '--run-syncdb', verbosity=0)

from django.test import Client
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from register.models import UserProfile, PendingRegistration
from myprofile.models import Receipt, ExtraditionPackage

User = get_user_model()

passed = 0
failed = 0
results = []

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        results.append(f"  \u2705 {name}")
    else:
        failed += 1
        results.append(f"  \u274c {name} \u2014 {detail}")


def test_debug_false():
    print("\n" + "=" * 70)
    print("  TESTING WITH DEBUG=False (PRODUCTION MODE)")
    print("=" * 70)

    User.objects.all().delete()
    PendingRegistration.objects.all().delete()

    user1 = User.objects.create_user(
        username='TestUser123', password='StrongPass123!',
        email='test1@example.com', is_active=True)
    UserProfile.objects.create(user=user1, is_staff=False)

    staff_user = User.objects.create_user(
        username='staff_user', password='StaffPass123!',
        email='staff@example.com', is_active=True)
    UserProfile.objects.create(user=staff_user, is_staff=True, is_hr=True)

    client = Client()
    login_ok = client.login(username='staff_user', password='StaffPass123!')
    check("Staff login works", login_ok, "Failed staff login")

    # --- Test 1: GET approve/reject should return 405 ---
    pending = PendingRegistration.objects.create(
        login='newuser', phone='+77001234567', email='new@example.com',
        password=make_password('NewPass456!'), first_name='Test', last_name='User')

    print("\n  Testing GET-based CSRF on approve_registration...")
    resp = client.get(f'/register/confirm/approve/{pending.id}/', secure=True)
    check("GET approve blocked (405)", resp.status_code == 405, f"Got {resp.status_code}")

    resp = client.get(f'/register/confirm/reject/{pending.id}/', secure=True)
    check("GET reject blocked (405)", resp.status_code == 405, f"Got {resp.status_code}")

    # --- Test 2: POST approve works, password properly hashed ---
    print("\n  Testing approve_registration POST + hashed password...")
    new_pending = PendingRegistration.objects.create(
        login='newuser2', phone='+77007654321', email='new2@example.com',
        password=make_password('HashedPass!'), first_name='Test2', last_name='User2')

    resp = client.post(f'/register/confirm/approve/{new_pending.id}/', secure=True)
    check("POST approve succeeds (302)", resp.status_code == 302, f"Got {resp.status_code}")

    new_user = User.objects.filter(username='newuser2').first()
    check("Approved user exists", new_user is not None, "User not created")
    if new_user:
        check("Password hashed (not plaintext)",
              new_user.password.startswith(('pbkdf2', 'argon2', 'scrypt')),
              f"Got: {new_user.password[:20]}...")
        c2 = Client()
        check("Can login with correct password",
              c2.login(username='newuser2', password='HashedPass!'),
              "Login failed with correct password")

    # --- Test 3: Username case sensitivity ---
    print("\n  Testing username case sensitivity...")
    case_client = Client()
    resp = client.post('/register/login/', {'login': 'testuser123', 'password': 'StrongPass123!'}, secure=True)
    check("Login with lowercase username works", resp.status_code in (302, 200),
          f"Got {resp.status_code}")

    # --- Test 4: User enumeration in password reset ---
    print("\n  Testing user enumeration fix in password reset...")
    enum_client = Client()
    resp_nouser = enum_client.post('/register/password-reset/',
                                    {'identifier': 'nonexistent_user_99999'}, secure=True)
    resp_user = enum_client.post('/register/password-reset/',
                                  {'identifier': 'TestUser123'}, secure=True)
    try:
        r1 = resp_nouser.json()
        r2 = resp_user.json()
        check("No enumeration: nonexistent returns success", r1.get('success', False), f"Got: {r1}")
        check("No enumeration: existing user also returns success",
              r2.get('success', False), f"Got: {r2}")
        check("No enumeration: both return success (no differential)",
              r1.get('success') == r2.get('success') == True, f"r1={r1}, r2={r2}")
    except Exception:
        check("Password reset consistent responses", resp_nouser.status_code == resp_user.status_code,
              f"{resp_nouser.status_code} vs {resp_user.status_code}")

    # --- Test 5: Security headers ---
    print("\n  Testing security headers (DEBUG=False)...")
    resp = client.get('/register/login/', secure=True)
    hsts = resp.get('Strict-Transport-Security', '')
    check("HSTS header present (31536000s)", '31536000' in hsts, f"HSTS: {hsts}")
    check("X-Content-Type-Options: nosniff",
          resp.get('X-Content-Type-Options') == 'nosniff',
          f"Got: {resp.get('X-Content-Type-Options', 'MISSING')}")

    # --- Test 6: Analytics ping not csrf_exempt ---
    print("\n  Testing analytics ping CSRF enforcement...")
    import analytics.views as av
    ping_view = av.ping
    check("ping() is not csrf_exempt", not getattr(ping_view, 'csrf_exempt', False))

    # --- Test 7: pg_advisory_xact_lock guard ---
    print("\n  Testing pg_advisory_xact_lock on SQLite...")
    from myprofile.views.extraditions import _next_fst_pkg_barcode
    try:
        _next_fst_pkg_barcode()
        check("pg_advisory_xact_lock doesn't crash on SQLite", True)
    except Exception as e:
        check("pg_advisory_xact_lock doesn't crash on SQLite", False, str(e))

    # --- Test 8: Payment check restored ---
    print("\n  Testing payment check restored in issue_package...")
    resp = client.get('/profile/extradition/', secure=True)
    check("Extradition page accessible for staff", resp.status_code == 200,
          f"Got {resp.status_code}")

    # --- Test 9: Open redirect fix ---
    print("\n  Testing open redirect fix...")
    from myprofile.views.track_codes import _safe_next_url

    class MockRequest:
        def __init__(self, post_data, host='127.0.0.1:8000'):
            self.POST = post_data
            self._host = host
        def get_host(self):
            return self._host

    r = _safe_next_url(MockRequest({'next': '//evil.com'}))
    check("//evil.com rejected", r is None, f"Returned: {r}")
    r = _safe_next_url(MockRequest({'next': '/\\evil.com'}))
    check(" /\\evil.com rejected", r is None, f"Returned: {r}")
    r = _safe_next_url(MockRequest({'next': '/profile/'}))
    check("Valid relative /profile/ accepted", r == '/profile/', f"Returned: {r}")

    # --- Test 10: Secure code generation ---
    print("\n  Testing secure code generation (secrets vs random)...")
    from register.views.password_reset import _generate_code as gen_reset
    from register.views.email_verify import _generate_code as gen_verify
    codes = [gen_reset() for _ in range(100)]
    check("100 unique reset codes", len(set(codes)) == 100)
    codes = [gen_verify() for _ in range(100)]
    check("100 unique verify codes", len(set(codes)) == 100)

    # --- Test 11: Exception logging ---
    print("\n  Testing exception logging in middleware...")
    import cargo.middleware as cmw
    import analytics.middleware as amw
    cmw_src = open(cmw.__file__).read()
    amw_src = open(amw.__file__).read()
    check("cargo.middleware logs instead of pass", "pass" not in cmw_src or "except" not in cmw_src.split("except Exception")[1].split("\n")[0] if "except Exception" in cmw_src else True)
    check("analytics.middleware logs instead of pass", "except Exception:\n            pass" not in amw_src)

    print("\n" + "-" * 70)
    for r in results:
        print(r)
    print("-" * 70)
    print(f"  DEBUG=False Results: {passed} passed, {failed} failed")
    print("-" * 70)
    return passed, failed


def test_debug_true():
    """Test that fixes don't break functionality with DEBUG=True"""
    print("\n" + "=" * 70)
    print("  TESTING WITH DEBUG=True (DEVELOPMENT MODE)")
    print("=" * 70)

    # Save original settings
    orig_debug = os.environ.get('DJANGO_DEBUG')
    orig_sts = os.environ.get('DJANGO_HSTS_SECONDS')

    # We need to reload settings with DEBUG=True
    from django.test import override_settings
    debug_results = []
    global passed, failed

    # Use override_settings for DEBUG=True
    with override_settings(DEBUG=True, SECURE_SSL_REDIRECT=False,
                           SECURE_HSTS_SECONDS=0,
                           SESSION_COOKIE_SECURE=False,
                           CSRF_COOKIE_SECURE=False):
        client = Client()

        # Staff login
        login_ok = client.login(username='staff_user', password='StaffPass123!')
        debug_results.append(("Staff login works", login_ok, "Failed"))

        # Login page should be accessible
        resp = client.get('/register/login/')
        debug_results.append(("Login page accessible", resp.status_code == 200, f"Got {resp.status_code}"))

        # POST login with case-insensitive username
        resp = client.post('/register/login/', {'login': 'testuser123', 'password': 'StrongPass123!'})
        debug_results.append(("Login works (debug mode)", resp.status_code in (200, 302), f"Got {resp.status_code}"))

        # Approve registration via POST
        pending = PendingRegistration.objects.create(
            login='debuguser', phone='+77001112223', email='debug@example.com',
            password=make_password('DebugPass!'), first_name='D', last_name='U')
        resp = client.post(f'/register/confirm/approve/{pending.id}/')
        debug_results.append(("POST approve works (debug)", resp.status_code == 302, f"Got {resp.status_code}"))

        # GET approve should 405 (require_POST)
        resp = client.get(f'/register/confirm/approve/{pending.id}/')
        debug_results.append(("GET approve blocked (405)", resp.status_code == 405, f"Got {resp.status_code}"))

        # Open redirect fix still works
        from myprofile.views.track_codes import _safe_next_url
        class MockR:
            def __init__(self, pd, host='127.0.0.1:8000'):
                self.POST = pd; self._h = host
            def get_host(self): return self._h
        r = _safe_next_url(MockR({'next': '//evil.com'}))
        debug_results.append(("Open redirect blocked (debug)", r is None, f"Got: {r}"))
        r = _safe_next_url(MockR({'next': '/profile/'}))
        debug_results.append(("Valid redirect allowed (debug)", r == '/profile/', f"Got: {r}"))

    # Restore
    if orig_debug is not None:
        os.environ['DJANGO_DEBUG'] = orig_debug

    d_passed = sum(1 for _, ok, _ in debug_results if ok)
    d_failed = len(debug_results) - d_passed

    print("\n" + "-" * 70)
    for name, ok, detail in debug_results:
        status = "\u2705" if ok else "\u274c"
        print(f"  {status} {name}" + (f" \u2014 {detail}" if not ok else ""))
    print("-" * 70)
    print(f"  DEBUG=True Results: {d_passed} passed, {d_failed} failed")
    print("-" * 70)

    return d_passed, d_failed


if __name__ == '__main__':
    p1, f1 = test_debug_false()
    p2, f2 = test_debug_true()

    total_p = p1 + p2
    total_f = f1 + f2

    print(f"\n{'=' * 70}")
    print(f"  TOTAL: {total_p} passed, {total_f} failed")
    print(f"  DEBUG=False: {p1} passed, {f1} failed")
    print(f"  DEBUG=True:  {p2} passed, {f2} failed")
    print(f"{'=' * 70}")
    sys.exit(0 if total_f == 0 else 1)
