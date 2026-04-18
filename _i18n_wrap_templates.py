"""
Wrap Russian strings in Django HTML templates with {% trans %}.
Handles:
  - Text nodes between tags (no template vars inside)
  - HTML attributes: placeholder, title, alt, aria-label, aria-placeholder
  - Adds {% load i18n %} if missing (after {% extends %} if present)

Skips strings that already contain {% trans %}, {% blocktrans %}, or {{ }}.
"""
import re
import os
import glob

TEMPLATE_DIRS = [
    r'd:\cargo\InterCargoWeb\mainview\templates',
    r'd:\cargo\InterCargoWeb\myprofile\templates',
    r'd:\cargo\InterCargoWeb\register\templates',
]

CYRILLIC = r'[\u0400-\u04FF]'
LOAD_I18N = '{% load i18n %}'


def has_cyrillic(s):
    return bool(re.search(CYRILLIC, s))


def process_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    original = content

    if not has_cyrillic(content):
        return False

    # Add {% load i18n %} if missing
    if LOAD_I18N not in content:
        lines = content.split('\n')
        insert_idx = 0
        # Must come after {% extends %} if present
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith('{% extends'):
                insert_idx = i + 1
                break
        lines.insert(insert_idx, LOAD_I18N)
        content = '\n'.join(lines)

    # --- Pattern 1: Text nodes between tags ---
    # Match: >(whitespace)(pure Russian text with no template tags)(whitespace)<
    # Skip if already wrapped with {% trans %} or has {{ }}

    def wrap_text_node(m):
        before = m.group(1)  # leading whitespace
        text = m.group(2).strip()
        after = m.group(3)   # trailing whitespace
        if not has_cyrillic(text):
            return m.group(0)
        # Skip if contains template tags or vars
        if '{%' in text or '{{' in text or '%}' in text or '}}' in text:
            return m.group(0)
        # Skip if already wrapped
        if '{% trans' in text or '{% blocktrans' in text:
            return m.group(0)
        # Escape quotes in text
        if '"' in text:
            return f'>{before}{{% trans \'{text}\' %}}{after}<'
        return f'>{before}{{% trans "{text}" %}}{after}<'

    # Match text content between > and < with at least one Cyrillic char
    # The text must not contain < > { }
    content = re.sub(
        r'>(\s*)([^<>{}\n]+' + CYRILLIC + r'[^<>{}\n]*?)(\s*)<',
        wrap_text_node,
        content
    )

    # --- Pattern 2: HTML attributes with Russian text ---
    ATTRS = ['placeholder', 'title', 'alt', 'aria-label', 'aria-placeholder', 'data-tooltip', 'data-title']

    for attr in ATTRS:
        def make_replacer(a):
            def replace_attr(m):
                text = m.group(1)
                if not has_cyrillic(text):
                    return m.group(0)
                # Skip if already has trans
                if '{% trans' in text or '{% blocktrans' in text or '{{' in text:
                    return m.group(0)
                if '"' in text:
                    return f"{a}='{{% trans \"{text}\" %}}'"
                return f'{a}="{{% trans "{text}" %}}"'
            return replace_attr

        # Double-quoted attribute values
        content = re.sub(
            rf'{attr}="([^"]*{CYRILLIC}[^"]*)"',
            make_replacer(attr),
            content
        )
        # Single-quoted attribute values
        content = re.sub(
            rf"{attr}='([^']*{CYRILLIC}[^']*)'",
            make_replacer(attr),
            content
        )

    if content != original:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    return False


def main():
    files_changed = 0
    for tdir in TEMPLATE_DIRS:
        for filepath in glob.glob(os.path.join(tdir, '**', '*.html'), recursive=True):
            changed = process_file(filepath)
            if changed:
                files_changed += 1
                print(f'  Updated: {filepath}')
            else:
                print(f'  Skipped: {filepath}')
    print(f'\nTotal files updated: {files_changed}')


if __name__ == '__main__':
    main()
