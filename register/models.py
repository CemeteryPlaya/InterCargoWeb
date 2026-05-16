from django.db import models
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _


class PickupPoint(models.Model):
    address = models.CharField(max_length=255, verbose_name=_("Адрес"))
    premise_name = models.CharField(max_length=100, verbose_name=_("Название помещения"))
    payment_link = models.URLField(blank=True, null=True, verbose_name=_("Ссылка на оплату"))
    working_hours = models.CharField(max_length=100, blank=True, default='', verbose_name=_("Время работы"))
    is_active = models.BooleanField(default=True, verbose_name=_("Активен"))
    show_in_registration = models.BooleanField(default=True, verbose_name=_("Показывать в регистрации"))
    show_in_footer = models.BooleanField(default=True, verbose_name=_("Показывать в футере"))
    show_in_pickup_transfer = models.BooleanField(
        default=True, verbose_name=_("Показывать в заявках для перевода в другой ПВЗ")
    )
    is_home_delivery = models.BooleanField(default=False, verbose_name=_("Доставка на дом"))
    short_info = models.TextField(blank=True, default='', verbose_name=_("Краткая информация"))
    map_widget_code = models.TextField(blank=True, default='', verbose_name=_("2GIS виджет-код"))
    reminder_enabled = models.BooleanField(default=False, verbose_name=_("Напоминания включены"))
    reminder_intervals = models.CharField(
        max_length=100, blank=True, default='',
        verbose_name=_("Интервалы напоминаний (дни)"),
        help_text=_("Через запятую, например: 3,5,7. Если пусто — используются глобальные настройки.")
    )

    class Meta:
        verbose_name = _("Пункт выдачи")
        verbose_name_plural = _("Пункты выдачи")

    def __str__(self):
        return f"{self.address} ({self.premise_name})"


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, verbose_name=_("Имя пользователя"))
    phone = models.CharField(max_length=20, blank=True, default='', verbose_name=_("Телефон"))
    pickup = models.ForeignKey(
        PickupPoint, on_delete=models.SET_NULL, null=True, blank=True, verbose_name=_("ПВЗ")
    )
    is_staff = models.BooleanField(default=False, verbose_name=_("Персонал"))
    is_hr = models.BooleanField(default=False, verbose_name=_("HR"))
    is_driver = models.BooleanField(default=False, verbose_name=_("Водитель"))
    is_pp_worker = models.BooleanField(default=False, verbose_name=_("Работник ПВЗ"))
    is_pp_owner = models.BooleanField(default=False, verbose_name=_("Владелец ПВЗ"))
    is_accountant = models.BooleanField(default=False, verbose_name=_("Бухгалтер"))
    is_tg_admin = models.BooleanField(default=False, verbose_name=_("Администратор Telegram-бота"))
    is_registered = models.BooleanField(default=True, verbose_name=_("Регистрация подтверждена"))
    delivery_rate = models.DecimalField(
        max_digits=8, decimal_places=2, default=0,
        verbose_name=_("Цена за 1 кг доставки (₸)")
    )
    profile_updated_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Дата последнего изменения профиля"))
    pickup_changed_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Дата последней смены ПВЗ"))
    language = models.CharField(
        max_length=5,
        choices=[('ru', 'Русский'), ('kk', 'Қазақша'), ('en', 'English')],
        default='ru',
        verbose_name=_("Язык интерфейса"),
    )

    class Meta:
        verbose_name = _("Профиль пользователя")
        verbose_name_plural = _("Профили пользователей")

    def __str__(self):
        return f"{self.user.username} — {self.phone}"


class PendingRegistration(models.Model):
    login = models.CharField(max_length=150)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True, default='', verbose_name=_("Email"))
    pickup = models.ForeignKey(
        PickupPoint, on_delete=models.SET_NULL, null=True, blank=True, verbose_name=_("ПВЗ")
    )
    password = models.CharField(max_length=255)
    first_name = models.CharField(max_length=150, blank=True, default='', verbose_name=_("Имя"))
    last_name = models.CharField(max_length=150, blank=True, default='', verbose_name=_("Фамилия"))
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def pickup_name(self):
        return str(self.pickup) if self.pickup else ''

    class Meta:
        verbose_name = _("Заявка на регистрацию")
        verbose_name_plural = _("Заявки на регистрацию")

    def __str__(self):
        return f"{self.login} ({self.phone})"


class PasswordResetCode(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reset_codes')
    code = models.CharField(max_length=7, verbose_name=_("Код сброса"))
    created_at = models.DateTimeField(auto_now_add=True)
    attempts = models.IntegerField(default=0, verbose_name=_("Попытки ввода"))
    is_used = models.BooleanField(default=False, verbose_name=_("Использован"))

    class Meta:
        verbose_name = _("Код сброса пароля")
        verbose_name_plural = _("Коды сброса пароля")

    def __str__(self):
        return f"{self.user.username} — {self.code}"


class EmailVerificationCode(models.Model):
    email = models.EmailField(verbose_name=_("Email"))
    code = models.CharField(max_length=7, verbose_name=_("Код подтверждения"))
    created_at = models.DateTimeField(auto_now_add=True)
    attempts = models.IntegerField(default=0, verbose_name=_("Попытки ввода"))
    is_verified = models.BooleanField(default=False, verbose_name=_("Подтверждён"))

    class Meta:
        verbose_name = _("Код подтверждения email")
        verbose_name_plural = _("Коды подтверждения email")

    def __str__(self):
        return f"{self.email} — {self.code}"



class LoginAttempt(models.Model):
    identifier = models.CharField(max_length=255, unique=True, verbose_name=_("Идентификатор"))
    attempts = models.IntegerField(default=0, verbose_name=_("Попытки"))
    locked_until = models.DateTimeField(null=True, blank=True, verbose_name=_("Заблокирован до"))
    last_attempt = models.DateTimeField(auto_now=True, verbose_name=_("Последняя попытка"))

    class Meta:
        verbose_name = _("Попытка входа")
        verbose_name_plural = _("Попытки входа")

    def __str__(self):
        return f"{self.identifier} — {self.attempts} попыток"


class RolePermission(models.Model):
    """Точечное право пользователя на (аспект, действие).

    Работает поверх булевых флагов в UserProfile: если запись существует,
    её значения переопределяют дефолты, выведенные из флагов.
    Список аспектов и действий задаётся в myprofile.permissions.
    """
    user = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='role_permissions',
        verbose_name=_("Пользователь"),
    )
    aspect = models.CharField(max_length=50, verbose_name=_("Аспект"))
    can_view = models.BooleanField(default=False, verbose_name=_("Чтение"))
    can_create = models.BooleanField(default=False, verbose_name=_("Создание"))
    can_edit = models.BooleanField(default=False, verbose_name=_("Редактирование"))
    can_delete = models.BooleanField(default=False, verbose_name=_("Удаление"))
    can_approve = models.BooleanField(default=False, verbose_name=_("Одобрение"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Обновлено"))
    updated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='+',
        verbose_name=_("Кем обновлено"),
    )

    class Meta:
        unique_together = ('user', 'aspect')
        indexes = [models.Index(fields=['user', 'aspect'])]
        verbose_name = _("Право доступа")
        verbose_name_plural = _("Права доступа")

    def __str__(self):
        return f"{self.user.username} — {self.aspect}"
