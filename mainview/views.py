from django.shortcuts import render
from register.models import PickupPoint
from news.services import home_news
from tgbot.services import is_telegram_linked, get_or_create_link_url


def index(request):
    pickup_points = PickupPoint.objects.filter(is_active=True, show_in_registration=True)
    context = {'pickup_points': pickup_points, 'home_news': home_news(request.user)}

    if request.user.is_authenticated:
        from myprofile.models import TrackCode
        from django.db.models import Count

        user = request.user
        tracks = TrackCode.objects.filter(owner=user)
        status_counts = dict(tracks.values_list('status').annotate(c=Count('id')))
        context['mobile_stats'] = {
            'user_added': status_counts.get('user_added', 0),
            'in_transit': status_counts.get('warehouse_cn', 0) + status_counts.get('shipped_cn', 0),
            'sorting': status_counts.get('unidentified', 0) + status_counts.get('delivered', 0) + status_counts.get('shipping_pp', 0),
            'ready': status_counts.get('ready', 0),
        }

        # Telegram: показываем ссылку только если не привязан (на главной)
        linked = is_telegram_linked(user)
        context['telegram_linked'] = linked
        context['telegram_link_url'] = None if linked else get_or_create_link_url(user)

    return render(request, "desktop/index.html", context)


def education(request):
    return render(request, "desktop/education.html")


def about(request):
    # «О компании» переехала в раздел «Инфо» (стиль страниц для банка-эквайера).
    from django.shortcuts import redirect
    return redirect('info_page', slug='about', permanent=True)


def info_page(request, slug):
    """Страницы «Покупателям»: реквизиты, услуги, оплата, доставка, возврат,
    оферта, политика конфиденциальности, согласие на обработку ПД.

    Требование банка-эквайера (Приложение 1 к Договору интернет-эквайринга).
    Длинные юридические тексты лежат отдельным шаблоном на язык:
    info/<slug>.<lang>.html (ru — запасной).
    """
    from django.http import Http404
    from django.utils.translation import get_language
    from mainview.context_processors import INFO_PAGES
    from myprofile.views.utils import get_global_price_per_kg

    titles = dict(INFO_PAGES)
    if slug not in titles:
        raise Http404
    lang = (get_language() or 'ru')[:2]
    if lang not in ('ru', 'kk', 'en'):
        lang = 'ru'

    from django.template import TemplateDoesNotExist
    from django.template.loader import get_template
    content_template = f'info/{slug}.{lang}.html'
    try:
        get_template(content_template)
    except TemplateDoesNotExist:
        content_template = f'info/{slug}.ru.html'

    points = PickupPoint.objects.filter(is_active=True)
    context = {
        'slug': slug,
        'page_title': titles[slug],
        'content_template': content_template,
        'price_per_kg': get_global_price_per_kg(),
        'office_points': points.filter(is_home_delivery=False).order_by('address'),
        'has_home_delivery': points.filter(is_home_delivery=True).exists(),
    }
    return render(request, 'desktop/info_page.html', context)
