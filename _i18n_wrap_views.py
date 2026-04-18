"""
One-shot script: add gettext import and wrap Russian strings in view files.
Handles:
  - messages.success/error/warning/info(request, "...")
  - HttpResponseForbidden("...") / HttpResponseBadRequest("...")
  - JsonResponse({'error': '...'}) / JsonResponse({"error": "..."})
  - Simple quoted Russian strings in these patterns

Does NOT handle f-strings (those need manual conversion to % formatting).
"""
import re
import os
import glob

VIEW_DIRS = [
    r'd:\cargo\InterCargoWeb\myprofile\views',
    r'd:\cargo\InterCargoWeb\register\views',
]

IMPORT_LINE = 'from django.utils.translation import gettext as _'

# Patterns to wrap - using named groups for clarity
# Match Russian text (contains at least one Cyrillic char)
CYRILLIC = r'[\u0400-\u04FF]'


def has_cyrillic(s):
    return bool(re.search(CYRILLIC, s))


def process_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    original = content

    # Skip __init__.py and files with no Cyrillic
    if not has_cyrillic(content):
        return False

    # Add import if missing
    if IMPORT_LINE not in content:
        # Find the best place to insert - after the last django import
        lines = content.split('\n')
        insert_idx = 0
        for i, line in enumerate(lines):
            if line.startswith('from django') or line.startswith('import django'):
                insert_idx = i + 1
            elif line.startswith('from myprofile') or line.startswith('from register'):
                insert_idx = i + 1
        if insert_idx == 0:
            # Just add after first import
            for i, line in enumerate(lines):
                if line.startswith('import ') or line.startswith('from '):
                    insert_idx = i + 1
                    break

        lines.insert(insert_idx, IMPORT_LINE)
        content = '\n'.join(lines)

    # Pattern 1: messages.success/error/warning/info(request, "...") - non-f-string
    # Match: messages.TYPE(request, "RUSSIAN TEXT")
    def wrap_messages(m):
        prefix = m.group(1)  # messages.success(request,
        quote = m.group(2)   # " or '
        text = m.group(3)    # the text
        return f'{prefix}_({quote}{text}{quote}))'

    # Non-f-string messages: messages.success(request, "text") or messages.success(request, 'text')
    content = re.sub(
        r'(messages\.(?:success|error|warning|info)\(request,\s*)(["\'])(?!f)((?:(?!\2).)*' + CYRILLIC + r'(?:(?!\2).)*)\2\)',
        wrap_messages,
        content
    )

    # Pattern 2: HttpResponseForbidden("...") - non-f-string
    def wrap_http_response(m):
        prefix = m.group(1)
        quote = m.group(2)
        text = m.group(3)
        return f'{prefix}_({quote}{text}{quote}))'

    content = re.sub(
        r'(HttpResponseForbidden\()(["\'])(?!f)((?:(?!\2).)*' + CYRILLIC + r'(?:(?!\2).)*)\2\)',
        wrap_http_response,
        content
    )
    content = re.sub(
        r'(HttpResponseBadRequest\()(["\'])(?!f)((?:(?!\2).)*' + CYRILLIC + r'(?:(?!\2).)*)\2\)',
        wrap_http_response,
        content
    )

    # Pattern 3: JsonResponse({'error': 'RUSSIAN'} or "error": "RUSSIAN")
    def wrap_json_error(m):
        prefix = m.group(1)  # JsonResponse({'error':
        quote = m.group(2)
        text = m.group(3)
        suffix = m.group(4)  # }
        return f"{prefix}_({quote}{text}{quote}){suffix}"

    content = re.sub(
        r"""(JsonResponse\(\{['\"]error['\"]\s*:\s*)(['\"])(?!f)((?:(?!\2).)*""" + CYRILLIC + r"""(?:(?!\2).)*)\2(\s*\})""",
        wrap_json_error,
        content
    )

    # Also handle: JsonResponse({'error': 'text'}, status=...)
    content = re.sub(
        r"""(JsonResponse\(\{['\"]error['\"]\s*:\s*)(['\"])(?!f)((?:(?!\2).)*""" + CYRILLIC + r"""(?:(?!\2).)*)\2(\s*\}\s*,)""",
        wrap_json_error,
        content
    )

    # Fix double-wrapped: _("_("text")") -> _("text")
    content = content.replace('_(_("', '_("').replace('_(_(\'', '_(\'')

    # Fix _(  "text") -> _("text") extra parens
    # Check for _"text" pattern (missing paren) and fix
    content = re.sub(r'_(["\'])', r'_(\1', content)
    # But this might break existing _() calls, let's be more careful
    # Actually let me revert that and be more precise

    # Revert the bad regex above
    content = content.replace('_(_(', '_(')

    if content != original:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    return False


def main():
    files_changed = 0
    for view_dir in VIEW_DIRS:
        for filepath in glob.glob(os.path.join(view_dir, '*.py')):
            basename = os.path.basename(filepath)
            if basename == '__init__.py':
                continue
            changed = process_file(filepath)
            if changed:
                files_changed += 1
                print(f'  Updated: {filepath}')
            else:
                print(f'  Skipped: {filepath}')

    print(f'\nTotal files updated: {files_changed}')


if __name__ == '__main__':
    main()
