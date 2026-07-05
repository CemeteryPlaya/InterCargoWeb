"""Санитизация HTML тела новости (XSS-защита: посты пишут не-суперадмины).

Белый список подобран под тулбар Quill (см. news/static/news/manageForm.js):
заголовки h2/h3, жирный/курсив/подчёркнутый/зачёркнутый, списки, ссылка,
цитата, выравнивание (класс ql-align-*)."""
import nh3

ALLOWED_TAGS = {
    'p', 'br', 'strong', 'em', 'u', 's', 'a', 'ul', 'ol', 'li',
    'h2', 'h3', 'blockquote', 'span',
}

ALLOWED_ATTRIBUTES = {
    # 'rel' намеренно не в allowlist: nh3 не даёт одновременно 'rel' здесь и
    # link_rel ниже (падает в рантайме) — link_rel='noopener noreferrer' сам
    # проставляет rel на каждую <a>. Не добавляй 'rel' обратно.
    'a': {'href', 'target'},
    'span': {'class'},
    'p': {'class'},
    'li': {'class', 'data-list'},
    'h2': {'class'},
    'h3': {'class'},
    'blockquote': {'class'},
}


def clean_html(html):
    """Очищенный HTML; для пустого/None входа — пустая строка."""
    if not html:
        return ''
    return nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes={'http', 'https', 'mailto', 'tel'},
        link_rel='noopener noreferrer',
    )
