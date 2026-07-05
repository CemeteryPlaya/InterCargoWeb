/**
 * Нормализация кодов со сканеров штрих/QR-кодов (общая для всех страниц).
 *
 * Аппаратный сканер работает как клавиатура: при включённой русской раскладке
 * латинский код «PKG-…» превращается в «ЗЛП-…», при Caps Lock — в нижний
 * регистр, часть сканеров добавляет AIM-префикс вида «]Q1». Все коды системы
 * (штрихкоды пакетов, номера чеков) — верхний регистр латиницы + цифры + дефис.
 *
 * Зеркало серверной логики в myprofile/scan_utils.py — правки синхронизировать.
 */
(function () {
    'use strict';

    // Русская раскладка ЙЦУКЕН → латинская QWERTY (та же физическая клавиша)
    var RU_LAYOUT_TO_LAT = {
        'Й': 'Q', 'Ц': 'W', 'У': 'E', 'К': 'R', 'Е': 'T', 'Н': 'Y', 'Г': 'U',
        'Ш': 'I', 'Щ': 'O', 'З': 'P', 'Ф': 'A', 'Ы': 'S', 'В': 'D', 'А': 'F',
        'П': 'G', 'Р': 'H', 'О': 'J', 'Л': 'K', 'Д': 'L', 'Я': 'Z', 'Ч': 'X',
        'С': 'C', 'М': 'V', 'И': 'B', 'Т': 'N', 'Ь': 'M',
        'Х': '[', 'Ъ': ']', 'Ж': ';', 'Э': "'", 'Б': ',', 'Ю': '.'
    };

    // Визуальные двойники (кириллица, похожая на латиницу)
    var HOMOGLYPH_TO_LAT = {
        'А': 'A', 'В': 'B', 'С': 'C', 'Е': 'E', 'Н': 'H', 'К': 'K', 'М': 'M',
        'О': 'O', 'Р': 'P', 'Т': 'T', 'Х': 'X', 'У': 'Y'
    };

    var AIM_PREFIX_RE = /^\][A-Za-z][0-9A-Za-z]/;

    function mapChars(str, table) {
        var out = '';
        for (var i = 0; i < str.length; i++) {
            out += table[str[i]] || str[i];
        }
        return out;
    }

    /** Базовая нормализация: обрезка, AIM-префикс, верхний регистр. */
    function normalize(raw) {
        if (!raw) return '';
        var code = String(raw).trim();
        if (AIM_PREFIX_RE.test(code)) {
            code = code.slice(3);
        }
        return code.trim().toUpperCase();
    }

    /** Варианты кода по убыванию приоритета (без дубликатов). */
    function candidates(raw) {
        var base = normalize(raw);
        if (!base) return [];
        var list = [base];
        var layout = mapChars(base, RU_LAYOUT_TO_LAT);
        if (list.indexOf(layout) === -1) list.push(layout);
        var homoglyph = mapChars(base, HOMOGLYPH_TO_LAT);
        if (list.indexOf(homoglyph) === -1) list.push(homoglyph);
        return list;
    }

    /** Первый вариант кода, который есть в списке list; иначе null. */
    function matchIn(list, raw) {
        var cands = candidates(raw);
        for (var i = 0; i < cands.length; i++) {
            if (list.indexOf(cands[i]) !== -1) return cands[i];
        }
        return null;
    }

    window.ScanNormalize = {
        normalize: normalize,
        candidates: candidates,
        matchIn: matchIn
    };
})();
