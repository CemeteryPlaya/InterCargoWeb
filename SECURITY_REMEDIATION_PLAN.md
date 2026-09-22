# Security Remediation Plan — InterCargoWeb

**Branch:** `upgrade-protection` (local only)
**Base:** `main` @ commit `281732e 1.5.5`
**Goal:** Fix all 15 identified vulnerabilities without breaking existing site functionality.
**Constraint:** No remote push; all commits are local only.

---

## Phase 0: Environment Baseline (done)

- **Already applied:** Switched `cargo/settings.py` from PostgreSQL to SQLite3 for local testing (commented PostgreSQL, uncommented SQLite). This change is committed in this branch as "test: use SQLite3 for local security testing".
- The local `db.sqlite3` database (created during security audit) is **gitignored** and will NOT be committed.

---

## Phase 1: Secrets & Debug (CRITICAL — deploy-blocker)

### 1.1 Set `DEBUG=False` in production
**File:** `cargo/settings.py`

**Changes:**
- Split settings into `settings_dev.py` (DEBUG=True) and `settings_prod.py` (DEBUG=False) — OR
- Use environment variable: `DEBUG = os.environ.get('DJANGO_DEBUG', 'False') == 'True'`
- Add `ALLOWED_HOSTS` validation — read from env var, fail closed if not set in production

**Non-breaking:** Dev workflow continues using `settings_dev.py` or `DJANGO_DEBUG=True` env var.

### 1.2 Generate strong SECRET_KEY, move to env
**File:** `cargo/settings.py`, `.env.example`

**Changes:**
- Replace the hardcoded `django-insecure-...` key with `SECRET_KEY = os.environ.get('SECRET_KEY')`
- Add `.env` to `.gitignore` (ensure not already committed)
- Create `.env.example` with: `SECRET_KEY=GENERATE_WITH_python_secrets_token_urlsafe50`
- In `settings.py`: `if not SECRET_KEY: raise RuntimeError('SECRET_KEY env var not set')`

**Non-breaking:** Developers copy `.env.example` to `.env` and set their own key.

### 1.3 Remove secrets from git history
**Action:** Use `git filter-repo` or `BFG Repo-Cleaner` to scrub the old SECRET_KEY from history.
**Rationale:** The secret was committed in plaintext — old commits must be cleaned.

---

## Phase 2: Authentication & Session Security (CRITICAL)

### 2.1 Fix login username uppercasing bug
**File:** `register/views/enter.py`

**Current (vulnerable):**
```python
username = request.POST.get('username', '').upper()
user = authenticate(request, username=username, password=password)
```

**Fix:** Remove `.upper()` — Django's `authenticate()` is case-sensitive by default:
```python
username = request.POST.get('username', '').strip()
user = authenticate(request, username=username, password=password)
```

**Non-breaking:** Users who registered with mixed-case usernames can now log in. All-uppercase username users are unaffected.

### 2.2 Replace `random.randint()` with `secrets`
**Files:** `register/views/regConfirm.py`, `register/views/email_verify.py` (password reset & email verification code generation)

**Changes:**
- Replace `import random` with `from secrets import token_urlsafe, token_hex`
- Replace `random.randint(100000, 999999)` with `secrets.token_urlsafe(32)` (32-byte URL-safe token)
- Store the full token in the DB (token field width already 128 chars — sufficient)
- Return the token to the user (not a 6-digit code) — adjust templates/flows accordingly

**Non-breaking:** Token-based flows are actually more user-friendly (click link vs. type code).

### 2.3 Hash plaintext passwords in PendingRegistration
**File:** `register/models.py`, `register/views/regConfirm.py`

**Changes:**
- Change `PendingRegistration.password` from `CharField` to a field that stores a hash (or add `password_hash` field)
- In `regConfirm.py` finalize logic: hash the password BEFORE storing it in `PendingRegistration`
- Use `django.contrib.auth.hashers.make_password(password)` and verify with `check_password()`
- Add migration to migrate existing plaintext passwords to hashed (data migration script)

**Non-breaking:** Existing pending registrations must be migrated via a one-time migration script.

### 2.4 Session security settings
**File:** `cargo/settings.py`

**Changes (add to production settings):**
```python
SESSION_COOKIE_SECURE = True      # HTTPS only
SESSION_COOKIE_HTTPONLY = True    # No JS access (already True)
SESSION_COOKIE_SAMESITE = 'Lax'   # CSRF mitigation
CSRF_COOKIE_SECURE = True        # HTTPS only
CSRF_COOKIE_SAMESITE = 'Lax'     # CSRF mitigation
SECURE_SSL_REDIRECT = True       # Force HTTPS
SECURE_HSTS_SECONDS = 31536000   # 1 year HSTS
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
```

**Non-breaking:** Only active when DEBUG=False (HTTPS). Dev environment unchanged.

---

## Phase 3: CSRF Protection (CRITICAL → HIGH)

### 3.1 Add `@require_POST` to registration approve/reject
**File:** `register/urls.py`, `register/views/regConfirm.py`

**Changes:**
- Change URL patterns from GET to POST-only:
  ```python
  # Before: path('confirm/approve/<token>/', views.regConfirm.approve, name='approve')
  # After:
  path('confirm/approve/<token>/', views.regConfirm.approve, name='approve')
  ```
- Add `@require_POST` decorator to both `approve()` and `reject()` views
- Update templates/links that use `<a href="...approve/...">` to use `<form method="POST">`

**Non-breaking:** The UI changes from links to POST forms — user flow is identical.

### 3.2 Enable CSRF middleware for all POST endpoints
**File:** `cargo/settings.py`

**Verify:** `django.middleware.csrf.CsrfViewMiddleware` is in `MIDDLEWARE` list.
**Action:** Ensure it's present (it's enabled by default in Django).

### 3.3 Remove `@csrf_exempt` from analytics endpoint
**File:** `analytics/views.py`

**Changes:**
- Remove `@csrf_exempt` from `ping()`
- If the endpoint must accept cross-origin requests, use `@ensure_csrf_cookie` on the parent page and send the CSRF token in the header from the client-side beacon
- Alternatively: move analytics to a dedicated subdomain and use CORS instead of CSRF exemption

**Non-breaking:** The client-side beacon code in templates must be updated to include the CSRF token in the `X-CSRFToken` header.

---

## Phase 4: Authorization & Access Control (HIGH)

### 4.1 Restore payment checks
**Files:**
- `myprofile/views/extraditions.py` (lines 94-98, 122-126)
- `myprofile/views/customer_paycheks.py` (lines 87-92)
- `myprofile/views/extradition_Package.py` (line 49)

**Changes:**
- Uncomment payment verification logic
- Ensure `is_paid` is checked before issuing packages
- Return `402 Payment Required` or redirect to payment page if `receipt.is_paid` is False
- Add a test case that verifies non-paid receipts cannot be issued

**Non-breaking:** Paid receipts continue to work. Unpaid receipts now correctly blocked (this is the intended behavior — the bug was that unpaid receipts were incorrectly allowed).

### 4.2 Fix open redirect in `_safe_next_url`
**File:** `myprofile/views/utils.py`

**Current (vulnerable):**
```python
def _safe_next_url(url):
    if url.startswith('/'):
        return url
    return '/'
```

**Fix:** Use Django's built-in `validate_next_url`:
```python
from django.utils.http import validate_next_url

def _safe_next_url(url):
    if validate_next_url(url):
        return url
    return '/'
```

**Non-breaking:** All relative URLs continue to work. Malicious `//evil.com` and `/\evil.com` URLs are blocked.

### 4.3 Fix user enumeration
**Files:** `register/views/regConfirm.py`, `register/views/reg.py` (registration & password reset)

**Changes:**
- In registration: return the SAME success message regardless of whether the username/email exists. E.g., "If this account is not registered, you will not receive a confirmation email."
- In password reset: always show "If the email is registered, a reset link has been sent." — never reveal whether the email exists
- Audit `search_users()` in utils — restrict to only return users the requesting user is allowed to see (e.g., only users in the same pickup point)

**Non-breaking:** UX messaging changes slightly — users get less information but security is maintained.

---

## Phase 5: Database Compatibility (MEDIUM)

### 5.1 Fix PostgreSQL-specific `pg_advisory_xact_lock` crash
**File:** `myprofile/views/warehouse.py` `inventory_session_end()`

**Changes:**
- Add a DB backend check before calling the stored procedure:
  ```python
  from django.db import connection

  if connection.vendor == 'postgresql':
      connection.cursor().callproc('pg_advisory_xact_lock', [session.id])
  else:
      # SQLite/MySQL fallback: use SELECT ... FOR UPDATE equivalent or skip locking
      # Django doesn't support SELECT FOR UPDATE on SQLite, so use a simple row lock:
      from django.db.models import F
      InventorySession.objects.filter(id=session.id).update(locked_by=F('id'))
  ```
- Remove the `except Exception: pass` broad-catch and replace with specific exception handling

**Non-breaking:** PostgreSQL behavior unchanged. SQLite (dev) no longer crashes.

### 5.2 Replace `except Exception: pass` with specific exceptions
**Files:** `myprofile/views/utils.py`, `myprofile/views/warehouse.py`, `myprofile/views/extradition_Package.py`

**Changes:**
- Audit all `except Exception:` blocks
- Log the exception: `logger.exception("...")`
- Catch specific exceptions only (e.g., `except UserProfile.DoesNotExist`, `except json.JSONDecodeError`)

**Non-breaking:** Errors are now visible in logs instead of being silently swallowed.

---

## Phase 6: DDoS & Infrastructure (MEDIUM/HIGH)

### 6.1 Add rate limiting
**Dependencies:** `django-ratelimit` (add to `requirements.txt`)

**Changes:**
- Add `@ratelimit(key='ip', rate='10/m')` to login, password reset, registration endpoints
- Add `@ratelimit(key='ip', rate='60/m')` to all API endpoints
- Return HTTP 429 with retry-after header on rate limit exceeded

**Non-breaking:** Legitimate users are unaffected — rate limits are generous enough for normal usage.

### 6.2 Add HSTS and HTTPS redirect
**File:** `cargo/settings_prod.py` (production-only settings)

**Changes:**
```python
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
```

**Non-breaking:** Dev environment (DEBUG=True, HTTP) is unaffected.

---

## Phase 7: Testing & Deployment

### 7.1 Security tests
**Action:** Add Django test cases that verify:
- [ ] Session forgery with old SECRET_KEY is rejected
- [ ] CSRF tokens are properly validated on POST endpoints
- [ ] Payment-required endpoints reject unpaid receipts
- [ ] Open redirect payloads are blocked
- [ ] Registration/confirm endpoints reject GET requests
- [ ] Password reset codes are cryptographically random

### 7.2 Regression tests
**Action:** Run existing test suite with SQLite to ensure no functionality broke.
```bash
python manage.py test --settings=cargo.settings_test
```

### 7.3 Deploy
**Action:** Deploy to production with:
- `DEBUG=False`
- `SECRET_KEY` from environment variable
- HTTPS (Let's Encrypt)
- `ALLOWED_HOSTS` set to production domain

---

## Commit Plan (local branch `upgrade-protection`)

| Commit | Content |
|--------|---------|
| `test: use SQLite3 for local security testing` | Uncomment SQLite, comment PostgreSQL in settings.py |
| `docs: add security remediation plan` | This file: `SECURITY_REMEDIATION_PLAN.md` |
| `fix: set DEBUG=False default, use SECRET_KEY env var` | Phase 1 fixes |
| `fix: restore payment checks in extradition/customer_paycheks views` | Phase 4.1 + 4.2 |
| `fix: add require_POST to registration approve/reject endpoints` | Phase 3.1 |
| `fix: use secrets module for token generation` | Phase 2.2 |
| `fix: hash passwords in PendingRegistration` | Phase 2.3 |
| `fix: replace broad Exception swallowing with specific handling` | Phase 5.2 |
| `fix: fix pg_advisory_xact_lock crash on SQLite` | Phase 5.1 |
| `fix: fix login username uppercasing bug` | Phase 2.1 |
| `fix: fix open redirect in _safe_next_url` | Phase 4.2 |
| `fix: remove csrf_exempt from analytics ping endpoint` | Phase 3.3 |
| `fix: reduce user enumeration in registration/reset flows` | Phase 4.3 |
| `feat: add rate limiting with django-ratelimit` | Phase 6.1 |
| `feat: add HSTS and HTTPS security headers` | Phase 6.2 |
| `test: add security regression tests` | Phase 7.1 |
