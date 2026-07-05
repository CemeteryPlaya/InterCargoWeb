from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _


def _localized(obj, base):
    """Значение поля ``<base>_<lang>`` для текущего языка с фолбэком на ru."""
    lang = (get_language() or 'ru')[:2]
    if lang != 'ru':
        value = getattr(obj, f'{base}_{lang}', '')
        if value:
            return value
    return getattr(obj, f'{base}_ru')


class NewsCategory(models.Model):
    """Категория новостей (подгруппа на странице «все новости»).

    Управляется из админки. Категорию с постами удалить нельзя (PROTECT) —
    скрывайте через ``is_active`` (влияет только на чипы-фильтры)."""
    name_ru = models.CharField(max_length=100, verbose_name=_("Название (рус)"))
    name_kk = models.CharField(max_length=100, blank=True, default='', verbose_name=_("Название (каз)"))
    name_en = models.CharField(max_length=100, blank=True, default='', verbose_name=_("Название (англ)"))
    slug = models.SlugField(max_length=50, unique=True, verbose_name=_("Слаг"))
    color = models.CharField(
        max_length=7, default='#3b82f6', verbose_name=_("Цвет"),
        help_text=_("HEX-цвет бейджа и обложки-заглушки, например #3b82f6."),
    )
    icon = models.CharField(
        max_length=50, blank=True, default='', verbose_name=_("Иконка"),
        help_text=_("Класс Remix Icon, например ri-megaphone-line."),
    )
    sort_order = models.PositiveIntegerField(default=0, verbose_name=_("Порядок"))
    is_active = models.BooleanField(default=True, verbose_name=_("Активна"))

    class Meta:
        ordering = ('sort_order', 'id')
        verbose_name = _("Категория новостей")
        verbose_name_plural = _("Категории новостей")

    @property
    def name(self):
        return _localized(self, 'name')

    def __str__(self):
        return self.name_ru


class PublishedManager(models.Manager):
    def get_queryset(self):
        return (
            super().get_queryset()
            .filter(is_published=True, published_at__lte=timezone.now())
        )


class NewsPost(models.Model):
    """Новостной пост. Контент трёхъязычный: kk/en опциональны, фолбэк на ru
    (перевод автор готовит внешним сервисом до публикации)."""
    category = models.ForeignKey(
        NewsCategory, on_delete=models.PROTECT, related_name='posts',
        verbose_name=_("Категория"),
    )
    title_ru = models.CharField(max_length=200, verbose_name=_("Заголовок (рус)"))
    title_kk = models.CharField(max_length=200, blank=True, default='', verbose_name=_("Заголовок (каз)"))
    title_en = models.CharField(max_length=200, blank=True, default='', verbose_name=_("Заголовок (англ)"))
    summary_ru = models.CharField(
        max_length=300, verbose_name=_("Короткое описание (рус)"),
        help_text=_("Показывается на карточке."),
    )
    summary_kk = models.CharField(max_length=300, blank=True, default='', verbose_name=_("Короткое описание (каз)"))
    summary_en = models.CharField(max_length=300, blank=True, default='', verbose_name=_("Короткое описание (англ)"))
    body_ru = models.TextField(
        verbose_name=_("Полный текст (рус)"),
        help_text=_("HTML: абзацы, списки, ссылки."),
    )
    body_kk = models.TextField(blank=True, default='', verbose_name=_("Полный текст (каз)"))
    body_en = models.TextField(blank=True, default='', verbose_name=_("Полный текст (англ)"))
    cover = models.ImageField(
        upload_to='news/covers/', blank=True, null=True, verbose_name=_("Обложка"),
        help_text=_("Если пусто — карточка заливается цветом категории."),
    )
    is_published = models.BooleanField(default=False, verbose_name=_("Опубликован"))
    published_at = models.DateTimeField(default=timezone.now, verbose_name=_("Дата публикации"))
    auth_only = models.BooleanField(
        default=False, verbose_name=_("Только авторизованным"),
        help_text=_("Гости этот пост не видят."),
    )
    author = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='news_posts', verbose_name=_("Автор"),
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Создан"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Обновлён"))

    objects = models.Manager()
    published = PublishedManager()

    class Meta:
        ordering = ('-published_at',)
        verbose_name = _("Новость")
        verbose_name_plural = _("Новости")

    @property
    def title(self):
        return _localized(self, 'title')

    @property
    def summary(self):
        return _localized(self, 'summary')

    @property
    def body(self):
        return _localized(self, 'body')

    def __str__(self):
        return self.title_ru


class NewsSettings(models.Model):
    """Singleton: настройки секции новостей на главной."""
    LAYOUT_STRIP = 'strip'
    LAYOUT_FEATURED = 'featured'
    LAYOUT_CHOICES = [
        (LAYOUT_STRIP, _("Горизонтальная лента")),
        (LAYOUT_FEATURED, _("1 крупная + лента")),
    ]

    section_enabled = models.BooleanField(default=True, verbose_name=_("Секция на главной включена"))
    desktop_layout = models.CharField(
        max_length=10, choices=LAYOUT_CHOICES, default=LAYOUT_STRIP,
        verbose_name=_("Режим секции на десктопе"),
    )

    class Meta:
        verbose_name = _("Настройки новостей")
        verbose_name_plural = _("Настройки новостей")

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Настройки новостей"
