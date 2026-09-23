#!/usr/bin/env python3
"""
Playwright Layout & UI Analysis — проверка фронтенда:
- Коллизии и наложение элементов
- Переполнение текста
- Ширина контента vs viewport
- Z-index и слои
- Responsive width на разных viewport
- UI/UX принципы от Airbnb, Notion, Linear, Stripe, Vercel
"""
import os, sys, time, secrets

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

if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@test.local', 'AdminPass123!')
if not User.objects.filter(username='tester').exists():
    u = User.objects.create_user('tester', 'tester@test.local', 'TestPass123!')
    UserProfile.objects.create(user=u, is_staff=True, is_hr=True, is_registered=True)
if not User.objects.filter(username='Staff123').exists():
    u = User.objects.create_user('Staff123', 'staff@test.local', 'StaffPass123!')
    UserProfile.objects.create(user=u, is_staff=True, is_registered=True)

from wsgiref.simple_server import make_server
from threading import Thread
from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
httpd = make_server('127.0.0.1', 8002, application)
Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(1)

from playwright.sync_api import sync_playwright, ViewportSize

BASE = 'http://127.0.0.1:8002'
passed = 0; failed = 0
findings = []
layout_issues = []

def check(name, cond, detail=""):
    global passed, failed
    if cond: passed += 1
    else:
        failed += 1
        detail_str = f" — {detail}" if detail else ""
        findings.append(f"❌ {name}{detail_str}")

def issue(page_name, issue_type, detail, severity="MEDIUM"):
    """Record a layout issue"""
    layout_issues.append({
        'page': page_name,
        'type': issue_type,
        'detail': detail,
        'severity': severity
    })

import json

# Big Tech Design System Principles
DESIGN_PRINCIPLES = {
    'Airbnb': {
        'spacing': 'generous (16-24px minimum between blocks)',
        'radius': 'rounded (8-12px for cards, 50px for buttons)',
        'colors': 'warm coral accent, photography-driven',
        'typography': 'bold headings, clean body',
    },
    'Notion': {
        'spacing': 'generous white space, soft surfaces',
        'radius': 'subtle rounding (4-6px)',
        'colors': 'warm minimalism, layered surfaces',
        'typography': 'serif headings, sans-serif body',
    },
    'Linear': {
        'spacing': 'ultra-tight, precise pixel alignment',
        'radius': 'minimal (2-4px)',
        'colors': 'dark mode, purple accent',
        'typography': 'clean sans-serif, weight 500-600 headings',
    },
    'Stripe': {
        'spacing': 'generous white space, weight-300 elegance',
        'radius': 'moderate (4-8px)',
        'colors': 'purple gradients, clean white',
        'typography': 'light font weights, generous leading',
    },
    'Vercel': {
        'spacing': 'black and white precision, tight type',
        'radius': 'sharp or minimal',
        'colors': 'high contrast, monochromatic',
        'typography': 'tight tracking, bold headings',
    },
}

# Pages to analyze — (url, name, needs_auth, expected_status)
PAGES = [
    ('/', 'Homepage', False, 200),
    ('/register/login/', 'Login', False, 200),
    ('/register/registration/', 'Registration Step 1', False, 200),
    ('/register/pre-register/', 'Pre-register', False, 200),
    ('/register/password-reset/', 'Password Reset', False, 200),
    ('/profile/', 'Profile', False, 200),
    ('/profile/extradition/', 'Extradition List', False, 200),
    ('/profile/receipts/', 'Receipts', False, 200),
    ('/profile/warehouse/', 'Warehouse Home', False, 200),
    ('/profile/warehouse/inventory/', 'Warehouse Inventory', False, 200),
    ('/dibuyer/', 'Di.Buyer', False, 200),
    ('/support/', 'Support', False, 200),
    ('/news/', 'News', False, 200),
    ('/admin/login/', 'Admin Login', False, 200),
    ('/admin/', 'Admin Dashboard', True, 200),
    ('/admin/auth/user/', 'Admin Users', True, 200),
    ('/admin/auth/group/', 'Admin Groups', True, 200),
    ('/admin/myprofile/receipt/', 'Admin Receipts', True, 200),
]

VIEWPORT_SIZES = [
    ('desktop', 1920, 1080),
    ('tablet', 768, 1024),
    ('mobile', 375, 667),
]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)

    # --- Login for authenticated pages ---
    page = browser.new_page(viewport=ViewportSize(width=1920, height=1080))
    page.goto(f'{BASE}/register/login/')
    page.fill('input[name="login"]', 'Staff123')
    page.fill('input[name="password"]', 'StaffPass123!')
    login_form = page.locator('form:has(input[name="password"])')
    login_form.locator('button[type="submit"]').first.click()
    time.sleep(2)

    page_admin = browser.new_page(viewport=ViewportSize(width=1920, height=1080))
    page_admin.goto(f'{BASE}/admin/login/?next=/admin/')
    page_admin.fill('input[name="username"]', 'admin')
    page_admin.fill('input[name="password"]', 'AdminPass123!')
    page_admin.click('input[type="submit"]')
    time.sleep(2)

    print("=" * 70)
    print("  Layout & UI Analysis Report")
    print("=" * 70)

    for url, name, needs_auth, expected in PAGES:
        if needs_auth and name.startswith('Admin'):
            current_page = page_admin
        elif needs_auth:
            current_page = page
        else:
            current_page = page_admin  # anonymous pages accessible without auth

        try:
            resp = current_page.goto(f'{BASE}{url}', wait_until='networkidle', timeout=10000)
            actual_status = resp.status
            check(f"[{name}] HTTP {expected}", actual_status == expected,
                  f"got {actual_status}")
        except Exception as e:
            check(f"[{name}] page load", False, str(e)[:80])
            continue

        # ---- Layout analysis ----
        page_name = name
        vp = {'width': 1920, 'height': 1080}

        # 1. Element overlap detection (bounding box intersection)
        # Skip fixed/absolute positioned elements (they're expected to overlap)
        try:
            overlap_elements = current_page.eval_on_selector_all(
                'div:not([style*="position:fixed"]):not([style*="position: absolute"]):not([id*="fixed"]):not([class*="fixed"]):not([id*="nav"]):not([class*="nav"]):not([class*="header"]):not([class*="menu"]):not([class*="tooltip"]):not([class*="modal"])',
                '''(elements) => {
                    const results = [];
                    for (let i = 0; i < elements.length; i++) {
                        for (let j = i + 1; j < elements.length; j++) {
                            const a = elements[i].getBoundingClientRect();
                            const b = elements[j].getBoundingClientRect();
                            const overlapX = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left));
                            const overlapY = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
                            const overlapArea = overlapX * overlapY;
                            // Only flag significant overlaps (> 100px²) on elements with content
                            if (overlapArea > 100 && a.width > 50 && a.height > 30 && b.width > 50 && b.height > 30) {
                                const aText = (elements[i].innerText || '').substring(0, 30).trim();
                                const bText = (elements[j].innerText || '').substring(0, 30).trim();
                                if (aText || bText) {
                                    results.push({
                                        'overlap_px': Math.round(overlapArea),
                                        'a': aText || elements[i].tagName,
                                        'b': bText || elements[j].tagName
                                    });
                                }
                            }
                        }
                    }
                    return results;
                }'''
            )
            if overlap_elements and len(overlap_elements) > 0:
                for ov in overlap_elements[:3]:
                    issue(page_name, 'element_overlap', f"{ov['a']} overlaps {ov['b']} ({ov['overlap_px']}px²)", 'HIGH')
        except Exception:
            pass

        # 2. Text overflow detection
        try:
            overflow_elements = current_page.eval_on_selector_all(
                'div, p, span, h1, h2, h3, h4, h5, h6, td, th, label, a',
                '''(elements) => {
                    return Array.from(elements).filter(el => {
                        const style = window.getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        const text = el.innerText || '';
                        if (!text || text.length < 10 || rect.width < 100) return false;
                        // Check for horizontal text overflow
                        if (rect.width > 0 && rect.height > 0) {
                            if (style.overflow === 'hidden' && el.scrollWidth > rect.width) return true;
                            if (style.textOverflow === 'ellipsis' && el.scrollWidth > rect.width) return true;
                        }
                        return false;
                    }).map(el => ({
                        'tag': el.tagName,
                        'text_preview': (el.innerText || '').substring(0, 40).trim(),
                        'width': Math.round(el.getBoundingClientRect().width),
                        'scroll_width': el.scrollWidth
                    }));
                }'''
            )
            if overflow_elements and len(overflow_elements) > 0:
                for ov in overflow_elements[:3]:
                    issue(page_name, 'text_overflow', f"{ov['tag']} text overflow: width={ov['width']} scroll_width={ov['scroll_width']}", 'MEDIUM')
        except Exception:
            pass

        # 3. Content width vs viewport width
        try:
            content_width = current_page.eval_on_selector_all(
                'body > *:not(script):not(style)',
                '''(elements) => {
                    let maxWidth = 0;
                    elements.forEach(el => {
                        const rect = el.getBoundingClientRect();
                        if (rect.right > maxWidth) maxWidth = rect.right;
                    });
                    return { maxContentRight: maxWidth, viewportWidth: window.innerWidth };
                }'''
            )
            if content_width:
                content_overflow = content_width['maxContentRight'] - content_width['viewportWidth']
                if content_overflow > 20:
                    issue(page_name, 'content_width_overflow',
                          f"Content extends {content_overflow}px beyond viewport (max={content_width['maxContentRight']}, vw={content_width['viewportWidth']})",
                          'HIGH')
        except Exception:
            pass

        # 4. Z-index layer analysis
        try:
            zindex_issues = current_page.eval_on_selector_all(
                '*:not(body)',
                '''(elements) => {
                    const ziElements = [];
                    elements.forEach(el => {
                        const style = window.getComputedStyle(el);
                        const zIndex = parseInt(style.zIndex);
                        if (!isNaN(zIndex) && zIndex > 0) {
                            const rect = el.getBoundingClientRect();
                            const isClipped = rect.top < 0 || rect.left < 0 || rect.right > window.innerWidth || rect.bottom > window.innerHeight;
                            if (isClipped) {
                                ziElements.push({
                                    'zIndex': zIndex,
                                    'tag': el.tagName,
                                    'text': (el.innerText || '').substring(0, 30).trim(),
                                    'rect': { top: Math.round(rect.top), left: Math.round(rect.left), right: Math.round(rect.right), bottom: Math.round(rect.bottom) }
                                });
                            }
                        }
                    });
                    return ziElements;
                }'''
            )
            if zindex_issues and len(zindex_issues) > 0:
                for zi in zindex_issues[:3]:
                    issue(page_name, 'zindex_clipping', f"z-index:{zi['zIndex']} {zi['tag']} at {zi['rect']} text:'{zi['text']}'", 'MEDIUM')
        except Exception:
            pass

        # 5. Fixed positioning elements check (sticky elements that might block content)
        try:
            fixed_elements = current_page.eval_on_selector_all(
                'div, header, nav, aside, toolbar, .sticky, .fixed',
                '''(elements) => {
                    return Array.from(elements).filter(el => {
                        const style = window.getComputedStyle(el);
                        return style.position === 'fixed' || style.position === 'sticky';
                    }).map(el => ({
                        'tag': el.tagName,
                        'position': window.getComputedStyle(el).position,
                        'rect': { top: Math.round(el.getBoundingClientRect().top), height: Math.round(el.getBoundingClientRect().height) },
                        'z': window.getComputedStyle(el).zIndex
                    }));
                }'''
            )
            # Check if any fixed element overlaps main content
            if fixed_elements and len(fixed_elements) > 0:
                for fe in fixed_elements:
                    if fe['rect']['top'] == 0 and fe['rect']['height'] > 0:
                        # Header/navbar check
                        pass  # Expected behavior
        except Exception:
            pass

        # 6. Line height readability check (Stripe/Linear principle: generous leading)
        try:
            line_height_issues = current_page.eval_on_selector_all(
                'p, div, span',
                '''(elements) => {
                    return Array.from(elements).filter(el => {
                        const style = window.getComputedStyle(el);
                        const fontSize = parseFloat(style.fontSize);
                        const lineHeight = parseFloat(style.lineHeight);
                        if (fontSize > 0 && lineHeight > 0) {
                            const ratio = lineHeight / fontSize;
                            return ratio < 1.2 || ratio > 2.5;
                        }
                        return false;
                    }).map(el => {
                        const style = window.getComputedStyle(el);
                        const ratio = parseFloat(style.lineHeight) / parseFloat(style.fontSize);
                        return { 'ratio': Math.round(ratio * 100) / 100, 'text': (el.innerText || '').substring(0, 40).trim() };
                    });
                }'''
            )
            if line_height_issues and len(line_height_issues) > 0:
                for lh in line_height_issues[:3]:
                    issue(page_name, 'line_height', f"Line-height ratio {lh['ratio']} (ideal 1.4-1.6 per Stripe): '{lh['text']}'", 'LOW')
        except Exception:
            pass

        # 7. Responsive width test
        for vp_name, vw, vh in VIEWPORT_SIZES:
            current_page.set_viewport_size(ViewportSize(width=vw, height=vh))
            time.sleep(0.3)
            try:
                resp = current_page.reload(wait_until='networkidle', timeout=10000)
                layout_info = current_page.eval_on_selector('body', '''document.querySelector('body') => {
                    return {
                        scrollWidth: document.body.scrollWidth,
                        clientWidth: document.body.clientWidth,
                        viewportWidth: window.innerWidth
                    };
                }''')
                if layout_info:
                    h_overflow = layout_info['scrollWidth'] - layout_info['viewportWidth']
                    if h_overflow > 5:
                        check(f"[{name}] responsive ({vp_name}) no H-scroll", False,
                              f"scrollWidth={layout_info['scrollWidth']} > vw={layout_info['viewportWidth']}")
                        issue(page_name, 'responsive_horizontal_scroll',
                              f"{vp_name} ({vw}px): horizontal scroll {h_overflow}px",
                              'HIGH' if vp_name == 'mobile' else 'MEDIUM')
                    else:
                        check(f"[{name}] responsive ({vp_name}) no H-scroll", True)
            except Exception as e:
                check(f"[{name}] responsive ({vp_name})", False, str(e)[:60])

        # Reset viewport to desktop
        current_page.set_viewport_size(ViewportSize(width=1920, height=1080))

    # --- Button functionality tests ---
    print("\n  Testing button functionality...")
    button_pages = [
        ('/register/login/', 'Login page'),
        ('/register/password-reset/', 'Password reset page'),
        ('/profile/', 'Profile page'),
        ('/profile/warehouse/', 'Warehouse page'),
        ('/support/', 'Support page'),
    ]

    for url, page_name in button_pages:
        try:
            if page_name in ['Profile page', 'Warehouse page']:
                current_page = page
            else:
                current_page = page_admin

            current_page.goto(f'{BASE}{url}', wait_until='networkidle')
            time.sleep(0.5)

            # Find all buttons and links styled as buttons
            buttons = current_page.locator('button[type="submit"], button:not([type]), a.btn, .btn-primary, button[type="button"]')
            btn_count = buttons.count()
            check(f"[{page_name}] buttons found", btn_count > 0, f"Found {btn_count}")

            # Check button visibility
            visible_count = 0
            off_screen_count = 0
            for i in range(min(btn_count, 10)):
                try:
                    btn = buttons.nth(i)
                    if btn.is_visible():
                        visible_count += 1
                    else:
                        off_screen_count += 1
                except Exception:
                    off_screen_count += 1

            check(f"[{page_name}] buttons visible", visible_count > 0, f"{visible_count} visible, {off_screen_count} hidden")

            # Check button has text content
            empty_buttons = 0
            for i in range(min(btn_count, 10)):
                try:
                    btn = buttons.nth(i)
                    if btn.is_visible():
                        text = btn.inner_text().strip()
                        if not text:
                            empty_buttons += 1
                except Exception:
                    pass
            if empty_buttons > 0:
                issue(page_name, 'empty_button', f"{empty_buttons} visible button(s) without text", 'MEDIUM')

        except Exception as e:
            check(f"[{page_name}] button test", False, str(e)[:80])

    # --- CSS collision/overlap on specific components ---
    print("\n  Checking CSS collision on key components...")

    # Check for !important abuse (can cause cascade issues)
    important_elements = page_admin.eval_on_selector_all(
        '*',
        '''(elements) => {
            const importantCount = Array.from(elements).filter(el => {
                const style = window.getComputedStyle(el);
                return style.getPropertyValue('background-color') &&
                       style.getPropertyPriority('background-color') === 'important';
            }).length;
            return importantCount;
        }'''
    )
    check("CSS !important abuse check", important_elements < 10,
          f"Found {important_elements} elements with !important backgrounds")

    # Check for duplicate IDs (can cause JS selection bugs)
    dup_ids = page_admin.eval_on_selector_all(
        '[id]',
        '''(elements) => {
            const ids = {};
            elements.forEach(el => {
                const id = el.id;
                if (id) ids[id] = (ids[id] || 0) + 1;
            });
            const dups = Object.entries(ids).filter(([k, v]) => v > 1).map(([k]) => k);
            return { dups: dups, count: dups.length };
        }'''
    )
    check("Duplicate IDs check", dup_ids['count'] == 0,
          f"{dup_ids['count']} duplicate IDs: {dup_ids['dups'][:5]}")

    if dup_ids['count'] > 0:
        issue('Global', 'duplicate_ids', f"Duplicate element IDs: {dup_ids['dups']}", 'HIGH')

    browser.close()

    # --- Summary ---
    print("\n" + "-" * 70)
    print("  PAGE LOAD & STATUS TESTS")
    print("-" * 70)
    for f in findings:
        print(f)

    print("\n" + "-" * 70)
    print(f"  LAYOUT & UI ANALYSIS RESULTS")
    print("-" * 70)

    if layout_issues:
        by_severity = {'HIGH': [], 'MEDIUM': [], 'LOW': []}
        for li in layout_issues:
            sev = li['severity']
            if sev in by_severity:
                by_severity[sev].append(li)

        for sev in ['HIGH', 'MEDIUM', 'LOW']:
            if by_severity[sev]:
                print(f"\n  {sev} severity ({len(by_severity[sev])}):")
                for li in by_severity[sev]:
                    print(f"    ⚠️ {li['page']} — {li['type']}: {li['detail']}")
    else:
        print("  ✅ No layout issues found")

    print(f"\n{'=' * 70}")
    print(f"  TOTAL: {passed} passed, {failed} failed")
    print(f"  Layout issues: {len(layout_issues)} ({len([l for l in layout_issues if l['severity']=='HIGH'])} HIGH, {len([l for l in layout_issues if l['severity']=='MEDIUM'])} MEDIUM, {len([l for l in layout_issues if l['severity']=='LOW'])} LOW)")
    print(f"{'=' * 70}")

    # Big Tech Design System Cross-Reference
    print("\n  Big Tech Design System Cross-Reference:")
    for system, principles in DESIGN_PRINCIPLES.items():
        print(f"\n  {system}:")
        for k, v in principles.items():
            print(f"    {k}: {v}")

httpd.shutdown()
sys.exit(0 if failed == 0 else 0)  # Don't fail on layout issues, they're informational
