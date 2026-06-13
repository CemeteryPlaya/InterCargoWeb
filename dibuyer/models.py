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
