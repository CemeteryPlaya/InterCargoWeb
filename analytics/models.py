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

    class Meta:
        verbose_name = _("Просмотр страницы")
        verbose_name_plural = _("Просмотры страниц")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['path', 'created_at']),
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
