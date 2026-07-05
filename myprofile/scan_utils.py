"""Нормализация кодов, приходящих со сканеров штрих/QR-кодов.

Аппаратный сканер работает как клавиатура (keyboard wedge): при включённой
русской/казахской раскладке латинский код «PKG-…» превращается в кириллицу
(«ЗЛП-…»), при Caps Lock — в нижний регистр, а часть сканеров добавляет
AIM-префикс вида «]Q1». Все коды в системе (barcode пакета, receipt_number
чека) — верхний регистр латиницы + цифры + дефис, поэтому нормализация
безопасна: легитимной кириллицы в этих полях не бывает.
"""

import re

# Русская раскладка ЙЦУКЕН → латинская QWERTY (та же физическая клавиша).
_RU_LAYOUT_TO_LAT = {
    'Й': 'Q', 'Ц': 'W', 'У': 'E', 'К': 'R', 'Е': 'T', 'Н': 'Y', 'Г': 'U',
    'Ш': 'I', 'Щ': 'O', 'З': 'P', 'Ф': 'A', 'Ы': 'S', 'В': 'D', 'А': 'F',
    'П': 'G', 'Р': 'H', 'О': 'J', 'Л': 'K', 'Д': 'L', 'Я': 'Z', 'Ч': 'X',
    'С': 'C', 'М': 'V', 'И': 'B', 'Т': 'N', 'Ь': 'M',
    'Х': '[', 'Ъ': ']', 'Ж': ';', 'Э': "'", 'Б': ',', 'Ю': '.',
}

# Визуальные двойники: человек набрал кириллицу, похожую на латиницу.
_HOMOGLYPH_TO_LAT = {
    'А': 'A', 'В': 'B', 'С': 'C', 'Е': 'E', 'Н': 'H', 'К': 'K', 'М': 'M',
    'О': 'O', 'Р': 'P', 'Т': 'T', 'Х': 'X', 'У': 'Y',
}

# AIM Symbology Identifier, например «]Q1» перед данными QR-кода.
_AIM_PREFIX_RE = re.compile(r"^\][A-Za-z][0-9A-Za-z]")


def normalize_scan_code(raw):
    """Базовая нормализация: пробелы/CR/LF по краям, AIM-префикс, верхний регистр."""
    if not raw:
        return ''
    code = str(raw).strip()
    if _AIM_PREFIX_RE.match(code):
        code = code[3:]
    return code.strip().upper()


def scan_code_candidates(raw):
    """Варианты кода для поиска в БД, по убыванию приоритета (без дубликатов):

    1) нормализованный как есть;
    2) конверсия русской раскладки (ЗЛП-… → PKG-…);
    3) конверсия визуальных двойников (РКG-… → PKG-…).
    """
    base = normalize_scan_code(raw)
    if not base:
        return []
    candidates = [base]
    layout = ''.join(_RU_LAYOUT_TO_LAT.get(ch, ch) for ch in base)
    if layout not in candidates:
        candidates.append(layout)
    homoglyph = ''.join(_HOMOGLYPH_TO_LAT.get(ch, ch) for ch in base)
    if homoglyph not in candidates:
        candidates.append(homoglyph)
    return candidates


def find_by_scan(queryset, field, raw):
    """Первый объект queryset, у которого `field` совпадает (iexact) с одним из
    вариантов отсканированного кода. None, если ничего не найдено."""
    for cand in scan_code_candidates(raw):
        obj = queryset.filter(**{f"{field}__iexact": cand}).first()
        if obj is not None:
            return obj
    return None
