from django.db import models
from django.contrib.auth.models import User


class PickupPoint(models.Model):
    address = models.CharField(max_length=255, verbose_name="Адрес")
    premise_name = models.CharField(max_length=100, verbose_name="Название помещения")
    payment_link = models.URLField(blank=True, null=True, verbose_name="Ссылка на оплату")
    is_active = models.BooleanField(default=True, verbose_name="Активен")
    show_in_registration = models.BooleanField(default=True, verbose_name="Показывать в регистрации/футере")

    class Meta:
        verbose_name = "Пункт выдачи"
        verbose_name_plural = "Пункты выдачи"

    def __str__(self):
        return f"{self.address} ({self.premise_name})"


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, verbose_name="Имя пользователя")
    phone = models.CharField(max_length=20, verbose_name="Телефон")
    pickup = models.ForeignKey(
        PickupPoint, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="ПВЗ"
    )
    is_staff = models.BooleanField(default=False)
    is_hr = models.BooleanField(default=False)
    is_driver = models.BooleanField(default=False, verbose_name="Водитель")
    is_pp_worker = models.BooleanField(default=False, verbose_name="Работник ПВЗ")

    def __str__(self):
        return f"{self.user.username} — {self.phone}"


class PendingRegistration(models.Model):
    login = models.CharField(max_length=150)
    phone = models.CharField(max_length=20)
    pickup = models.ForeignKey(
        PickupPoint, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="ПВЗ"
    )
    password = models.CharField(max_length=255)
    first_name = models.CharField(max_length=150, blank=True, default='', verbose_name="Имя")
    last_name = models.CharField(max_length=150, blank=True, default='', verbose_name="Фамилия")
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def pickup_name(self):
        return str(self.pickup) if self.pickup else ''

    def __str__(self):
        return f"{self.login} ({self.phone})"