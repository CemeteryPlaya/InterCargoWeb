from django.db import models
from django.contrib.auth.models import User


class PickupPoint(models.Model):
    address = models.CharField(max_length=255, verbose_name="Адрес")
    premise_name = models.CharField(max_length=100, verbose_name="Название помещения")
    payment_link = models.URLField(blank=True, null=True, verbose_name="Ссылка на оплату")
    working_hours = models.CharField(max_length=100, blank=True, default='', verbose_name="Время работы")
    is_active = models.BooleanField(default=True, verbose_name="Активен")
    show_in_registration = models.BooleanField(default=True, verbose_name="Показывать в регистрации/футере")
    is_home_delivery = models.BooleanField(default=False, verbose_name="Доставка на дом")

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
    profile_updated_at = models.DateTimeField(null=True, blank=True, verbose_name="Дата последнего изменения профиля")

    class Meta:
        verbose_name = "Профиль пользователя"
        verbose_name_plural = "Профили пользователей"

    def __str__(self):
        return f"{self.user.username} — {self.phone}"


class PendingRegistration(models.Model):
    login = models.CharField(max_length=150)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True, default='', verbose_name="Email")
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

    class Meta:
        verbose_name = "Заявка на регистрацию"
        verbose_name_plural = "Заявки на регистрацию"

    def __str__(self):
        return f"{self.login} ({self.phone})"


class PasswordResetCode(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reset_codes')
    code = models.CharField(max_length=7, verbose_name="Код сброса")
    created_at = models.DateTimeField(auto_now_add=True)
    attempts = models.IntegerField(default=0, verbose_name="Попытки ввода")
    is_used = models.BooleanField(default=False, verbose_name="Использован")

    class Meta:
        verbose_name = "Код сброса пароля"
        verbose_name_plural = "Коды сброса пароля"

    def __str__(self):
        return f"{self.user.username} — {self.code}"


class TempUser(models.Model):
    """Временные пользователи — клиенты, на которых пришли посылки, но которые ещё не зарегистрированы."""
    login = models.CharField(max_length=150, unique=True, verbose_name="Логин")
    phone = models.CharField(max_length=20, blank=True, default='', verbose_name="Телефон")
    pickup = models.ForeignKey(
        PickupPoint, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="ПВЗ"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")

    class Meta:
        verbose_name = "Временный пользователь"
        verbose_name_plural = "Временные пользователи"

    def __str__(self):
        return self.login


class LoginAttempt(models.Model):
    identifier = models.CharField(max_length=255, unique=True, verbose_name="Идентификатор")
    attempts = models.IntegerField(default=0, verbose_name="Попытки")
    locked_until = models.DateTimeField(null=True, blank=True, verbose_name="Заблокирован до")
    last_attempt = models.DateTimeField(auto_now=True, verbose_name="Последняя попытка")

    class Meta:
        verbose_name = "Попытка входа"
        verbose_name_plural = "Попытки входа"

    def __str__(self):
        return f"{self.identifier} — {self.attempts} попыток"