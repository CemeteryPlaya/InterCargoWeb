from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class PageView(models.Model):
    """Один просмотр страницы. Длительность (`duration_ms`) дозаписывается
    клиентским beacon'ом при уходе со страницы."""
    path = models.CharField(max_length=255, db_index=True, verbose_name=_("Путь"))
    view_name = models.CharField(max_length=120, blank=True, default='', verbose_name=_("Имя маршрута"))
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='page_views', verbose_name=_("Пользователь"),
    )
    session_key = models.CharField(max_length=40, blank=True, default='', db_index=True, verbose_name=_("Сессия"))
    is_authenticated = models.BooleanField(default=False, verbose_name=_("Авторизован"))
    duration_ms = models.PositiveIntegerField(null=True, blank=True, verbose_name=_("Время на странице (мс)"))
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name=_("Время"))

    # Аудитория для рекламодателей (analytics/tracking.py). У записей до
    # 2026-10 поля пустые — посетитель для них считается по сессии.
    visitor_id = models.CharField(max_length=32, blank=True, default='', db_index=True,
                                  verbose_name=_("Посетитель (cookie)"))
    visit_id = models.CharField(max_length=32, blank=True, default='', db_index=True,
                                verbose_name=_("Визит"))
    is_entry = models.BooleanField(default=False, verbose_name=_("Первый просмотр визита"))
    is_new_visitor = models.BooleanField(default=False, verbose_name=_("Новый посетитель"))
    is_staff_view = models.BooleanField(default=False, verbose_name=_("Сотрудник"))
    section = models.CharField(max_length=10, blank=True, default='', db_index=True,
                               verbose_name=_("Раздел"))   # cargo / dibuyer
    source = models.CharField(max_length=12, blank=True, default='', verbose_name=_("Источник"))
    referrer_host = models.CharField(max_length=120, blank=True, default='', verbose_name=_("Сайт-источник"))
    utm_source = models.CharField(max_length=60, blank=True, default='', verbose_name="utm_source")
    utm_medium = models.CharField(max_length=60, blank=True, default='', verbose_name="utm_medium")
    utm_campaign = models.CharField(max_length=100, blank=True, default='', verbose_name="utm_campaign")
    device = models.CharField(max_length=10, blank=True, default='', verbose_name=_("Устройство"))
    os = models.CharField(max_length=20, blank=True, default='', verbose_name=_("ОС"))
    browser = models.CharField(max_length=20, blank=True, default='', verbose_name=_("Браузер"))
    language = models.CharField(max_length=8, blank=True, default='', verbose_name=_("Язык сайта"))
    city = models.CharField(max_length=60, blank=True, default='', verbose_name=_("Город"))

    class Meta:
        verbose_name = _("Просмотр страницы")
        verbose_name_plural = _("Просмотры страниц")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['path', 'created_at']),
            models.Index(fields=['section', 'created_at']),
        ]

    @property
    def duration_seconds(self):
        return round(self.duration_ms / 1000, 1) if self.duration_ms else None

    def __str__(self):
        who = self.user.username if self.user else 'anon'
        return f"{self.path} — {who}"


class PageViewDaily(models.Model):
    """Дневная сводка по (дата, путь) — архив. Сырые `PageView` сворачиваются
    сюда и затем удаляются, чтобы основная таблица не разрасталась."""
    date = models.DateField(db_index=True, verbose_name=_("Дата"))
    path = models.CharField(max_length=255, verbose_name=_("Путь"))
    views = models.PositiveIntegerField(default=0, verbose_name=_("Просмотры"))
    unique_users = models.PositiveIntegerField(default=0, verbose_name=_("Уник. пользователи"))
    unique_sessions = models.PositiveIntegerField(default=0, verbose_name=_("Уник. сессии"))
    auth_views = models.PositiveIntegerField(default=0, verbose_name=_("Просмотры авторизованных"))
    total_duration_ms = models.BigIntegerField(default=0, verbose_name=_("Суммарное время (мс)"))
    duration_samples = models.PositiveIntegerField(default=0, verbose_name=_("Замеров времени"))
    unique_visitors = models.PositiveIntegerField(default=0, verbose_name=_("Уник. посетители"))
    visits = models.PositiveIntegerField(default=0, verbose_name=_("Визиты"))

    class Meta:
        verbose_name = _("Дневная сводка просмотров")
        verbose_name_plural = _("Дневные сводки просмотров")
        ordering = ['-date', '-views']
        constraints = [
            models.UniqueConstraint(fields=['date', 'path'], name='uniq_pageviewdaily_date_path'),
        ]
        indexes = [models.Index(fields=['date', 'path'])]

    @property
    def avg_duration_ms(self):
        return self.total_duration_ms / self.duration_samples if self.duration_samples else None

    def __str__(self):
        return f"{self.date} {self.path} — {self.views}"


class AdEvent(models.Model):
    """Показ или клик рекламного места (`data-ad-slot` в шаблоне).

    Показ считается по стандарту видимости IAB/MRC: не меньше 50% площади
    блока в окне браузера не меньше 1 секунды; один раз на просмотр страницы."""
    KIND_VIEW = 'view'
    KIND_CLICK = 'click'
    KIND_CHOICES = [(KIND_VIEW, _("Показ")), (KIND_CLICK, _("Клик"))]

    slot = models.CharField(max_length=40, db_index=True, verbose_name=_("Рекламное место"))
    label = models.CharField(max_length=100, blank=True, default='', verbose_name=_("Объявление"))
    kind = models.CharField(max_length=5, choices=KIND_CHOICES, verbose_name=_("Событие"))
    path = models.CharField(max_length=255, blank=True, default='', verbose_name=_("Страница"))
    section = models.CharField(max_length=10, blank=True, default='', verbose_name=_("Раздел"))
    visitor_id = models.CharField(max_length=32, blank=True, default='', verbose_name=_("Посетитель"))
    is_staff_view = models.BooleanField(default=False, verbose_name=_("Сотрудник"))
    pv_id = models.PositiveIntegerField(null=True, blank=True, verbose_name=_("Просмотр страницы"))
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name=_("Время"))

    class Meta:
        verbose_name = _("Событие рекламного места")
        verbose_name_plural = _("События рекламных мест")
        ordering = ['-created_at']
        indexes = [models.Index(fields=['slot', 'created_at'])]

    def __str__(self):
        return f"{self.slot} {self.kind}"


class AdDaily(models.Model):
    """Дневной архив по рекламным местам (сырые AdEvent чистятся вместе с PageView)."""
    date = models.DateField(db_index=True, verbose_name=_("Дата"))
    slot = models.CharField(max_length=40, verbose_name=_("Рекламное место"))
    label = models.CharField(max_length=100, blank=True, default='', verbose_name=_("Объявление"))
    section = models.CharField(max_length=10, blank=True, default='', verbose_name=_("Раздел"))
    views = models.PositiveIntegerField(default=0, verbose_name=_("Показы"))
    clicks = models.PositiveIntegerField(default=0, verbose_name=_("Клики"))
    unique_visitors = models.PositiveIntegerField(default=0, verbose_name=_("Уник. посетители"))

    class Meta:
        verbose_name = _("Дневная сводка рекламного места")
        verbose_name_plural = _("Дневные сводки рекламных мест")
        ordering = ['-date', 'slot']
        constraints = [
            models.UniqueConstraint(fields=['date', 'slot', 'label'], name='uniq_addaily_date_slot_label'),
        ]


class AudienceMonth(models.Model):
    """Снимок аудитории за календарный месяц — для медиакита. Строится из
    сырых данных, пока они есть (90 дней), и хранится долго."""
    month = models.DateField(verbose_name=_("Месяц"))   # первое число месяца
    section = models.CharField(max_length=10, verbose_name=_("Раздел"))  # all / cargo / dibuyer
    data = models.JSONField(default=dict, verbose_name=_("Показатели"))
    built_at = models.DateTimeField(auto_now=True, verbose_name=_("Посчитано"))

    class Meta:
        verbose_name = _("Аудитория за месяц")
        verbose_name_plural = _("Аудитория по месяцам")
        ordering = ['-month', 'section']
        constraints = [
            models.UniqueConstraint(fields=['month', 'section'], name='uniq_audiencemonth_month_section'),
        ]

    def __str__(self):
        return f"{self.month:%Y-%m} {self.section}"
