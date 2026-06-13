from decimal import Decimal

from django.contrib.auth.models import User
from django.db import models
from django.utils.translation import gettext_lazy as _


class DibuyerSettings(models.Model):
    """Singleton: один глобальный рубильник + тариф доставки Di.Buyer."""
    is_enabled = models.BooleanField(default=True, verbose_name=_("Сервис включён"))
    delivery_rate_usd = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal('11.30'),
        verbose_name=_("Тариф доставки ($/кг)"),
    )

    class Meta:
        verbose_name = _("Настройки Di.Buyer")
        verbose_name_plural = _("Настройки Di.Buyer")

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Настройки Di.Buyer"


class BuyerOrder(models.Model):
    STATUS_NEW = 'new'
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_PURCHASED = 'purchased'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_NEW, _("Новая")),
        (STATUS_IN_PROGRESS, _("В работе")),
        (STATUS_PURCHASED, _("Выкуплено")),
        (STATUS_REJECTED, _("Отклонена")),
    ]

    client = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='buyer_orders',
        verbose_name=_("Клиент"),
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_NEW,
        verbose_name=_("Статус"),
    )
    comment = models.TextField(blank=True, default='', verbose_name=_("Комментарий клиента"))
    staff_response = models.TextField(blank=True, default='', verbose_name=_("Ответ сотрудника"))
    handled_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
        verbose_name=_("Обработал"),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tracking_exported = models.BooleanField(default=False, verbose_name=_("Посылки созданы"))

    class Meta:
        ordering = ['-created_at']
        verbose_name = _("Заявка Di.Buyer")
        verbose_name_plural = _("Заявки Di.Buyer")

    @property
    def items_count(self):
        return self.items.count()

    def __str__(self):
        return f"Заявка №{self.pk} ({self.client})"


class BuyerOrderItem(models.Model):
    order = models.ForeignKey(
        BuyerOrder, on_delete=models.CASCADE, related_name='items',
        verbose_name=_("Заявка"),
    )
    url = models.URLField(max_length=1000, verbose_name=_("Ссылка на товар"))
    comment = models.CharField(
        max_length=500, blank=True, default='',
        verbose_name=_("Комментарий (размер/цвет/кол-во)"),
    )
    quantity = models.PositiveIntegerField(default=1, verbose_name=_("Количество"))
    weight = models.DecimalField(
        max_digits=6, decimal_places=3, null=True, blank=True, verbose_name=_("Вес (кг)"),
    )
    delivery_cost_kzt = models.DecimalField(
        max_digits=10, decimal_places=0, null=True, blank=True, verbose_name=_("Стоимость доставки (₸)"),
    )
    exchange_rate = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True, verbose_name=_("Курс ₸/$"),
    )
    track_code = models.ForeignKey(
        'myprofile.TrackCode', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name=_("Трек-код посылки"),
    )

    def __str__(self):
        return self.url
