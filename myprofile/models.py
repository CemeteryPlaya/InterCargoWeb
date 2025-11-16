from django.db import models
from django.conf import settings


# Create your models here.
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
import inspect

class TrackCode(models.Model):
    STATUS_CHOICES = [
        ('user_added', 'Добавлено пользователем'),
        ('warehouse_cn', 'Принято на склад (Китай)'),
        ('shipped_cn', 'Отправлено со склада (Китай)'),
        ('delivered', 'Принято сортировочным центром'),
        ('ready', 'Доставлено на ПВЗ'),
        ('claimed', 'Выдано получателю'),
    ]

    # Порядок статусов для проверки отката
    STATUS_ORDER = {
        'user_added': 0,
        'warehouse_cn': 1,
        'shipped_cn': 2,
        'delivered': 3,
        'ready': 4,
        'claimed': 5,
    }

    id = models.AutoField(primary_key=True, verbose_name="№ трек кода")
    track_code = models.CharField(max_length=100, unique=True, verbose_name="Трек код")
    update_date = models.DateField(auto_now=True, verbose_name="Дата обновления")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, verbose_name="Статус трек-кода")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        verbose_name="Имя владельца"
    )
    description = models.CharField(max_length=255, blank=True, verbose_name="О посылке")
    weight = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True, verbose_name="Вес посылки (кг)")

    def clean(self):
        """
        Запрещаем регресс статуса: нельзя менять на статус с меньшим порядком.
        Но пропускаем проверку, если изменение делается администратором через админ-панель.
        """
        # Проверяем, установлен ли флаг для обхода валидации (для админ-панели)
        if hasattr(self, '_skip_status_validation') and self._skip_status_validation:
            return
        
        # Дополнительная проверка: если вызывается из админ-панели Django
        # Проверяем стек вызовов на наличие django.contrib.admin
        frame = inspect.currentframe()
        try:
            # Проверяем несколько уровней стека вызовов
            for _ in range(10):
                frame = frame.f_back
                if frame is None:
                    break
                filename = frame.f_code.co_filename
                if 'django/contrib/admin' in filename or 'django\\contrib\\admin' in filename:
                    # Вызывается из админ-панели - пропускаем валидацию
                    return
        finally:
            del frame
            
        if self.pk:
            try:
                old = TrackCode.objects.get(pk=self.pk)
            except TrackCode.DoesNotExist:
                old = None

            if old:
                old_order = self.STATUS_ORDER.get(old.status, 0)
                new_order = self.STATUS_ORDER.get(self.status, 0)
                if new_order < old_order:
                    raise ValidationError({
                        'status': f"Нельзя откатить статус с '{old.get_status_display()}' на '{dict(self.STATUS_CHOICES).get(self.status)}'."
                    })

    def save(self, *args, **kwargs):
        # Если установлен флаг пропуска валидации (для админ-панели), пропускаем full_clean
        skip_full_clean = kwargs.pop('skip_full_clean', False) or (hasattr(self, '_skip_status_validation') and self._skip_status_validation)
        if not skip_full_clean:
            self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.track_code} - {self.get_status_display()}"

    
class Receipt(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name="Владелец")
    created_at = models.DateField(auto_now_add=True, verbose_name="Дата создания")
    is_paid = models.BooleanField(default=False, verbose_name="Статус оплаты")
    total_weight = models.DecimalField(max_digits=6, decimal_places=3, default=0, verbose_name="Общий вес (кг)")
    total_price = models.DecimalField(max_digits=10, decimal_places=0, default=0, verbose_name="Сумма чека")
    
    # 🏬 Пункт выдачи
    pickup_point = models.CharField(max_length=255, blank=True, null=True, verbose_name="Пункт выдачи")
    
    # 💳 Ссылка на оплату (генерируется в зависимости от пункта)
    payment_link = models.URLField(blank=True, null=True, verbose_name="Ссылка на оплату")

    def __str__(self):
        return f"Чек #{self.id} от {self.created_at} — {'Оплачен' if self.is_paid else 'Не оплачен'}"

class ReceiptItem(models.Model):
    receipt = models.ForeignKey(Receipt, related_name='items', on_delete=models.CASCADE)
    track_code = models.OneToOneField(TrackCode, on_delete=models.CASCADE)

    def __str__(self):
        return str(self.track_code)

class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    message = models.CharField(max_length=255, verbose_name="Сообщение")
    is_read = models.BooleanField(default=False, verbose_name="Прочитано")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата")

    def __str__(self):
        return f"Уведомление для {self.user.username}: {self.message}"
    
class CustomerDiscount(models.Model):
    """Постоянная или разовая скидка в тенге за 1 кг"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="discounts",
        verbose_name="Пользователь"
    )
    amount_per_kg = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        verbose_name="Скидка (₸/кг)"
    )
    is_temporary = models.BooleanField(default=False, verbose_name="Разовая скидка")
    active = models.BooleanField(default=True, verbose_name="Активная скидка")
    comment = models.CharField(max_length=255, blank=True, verbose_name="Комментарий")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        type_label = "Разовая" if self.is_temporary else "Постоянная"
        return f"{type_label} скидка {self.amount_per_kg} ₸/кг ({self.user.username})"
    
class UserPushSubscription(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    subscription_data = models.JSONField(default=dict, blank=True, null=True)

class Extradition(models.Model):
    package = models.OneToOneField(
        'ExtraditionPackage',  # строка для безопасной ссылки
        on_delete=models.CASCADE,
        related_name='extradition',
        verbose_name="Пакет выдачи"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="extraditions",
        verbose_name="Получатель"
    )
    pickup_point = models.CharField(max_length=255, verbose_name="Пункт выдачи")
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="issued_extraditions",
        verbose_name="Сотрудник, выдавший посылку"
    )
    confirmed = models.BooleanField(default=False, verbose_name="Подтверждено получателем")
    comment = models.TextField(blank=True, verbose_name="Комментарий")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")

    class Meta:
        verbose_name = "Выдача посылки"
        verbose_name_plural = "Выдачи посылок"

    def __str__(self):
        return f"Выдача #{self.id} — {self.user.username}"

    def save(self, *args, **kwargs):
        # Если создаётся новая выдача и пакет задан
        if self.package and not self.pk:
            # подтягиваем пользователя и пункт выдачи из пакета
            self.user = self.package.user
            # Получаем пункт выдачи из профиля пользователя через свойство пакета
            if not self.pickup_point:  # Если пункт выдачи не установлен явно
                try:
                    self.pickup_point = self.package.pickup_point_display
                except:
                    self.pickup_point = "Не указан"
        super().save(*args, **kwargs)




import uuid


class ExtraditionPackage(models.Model):
    """Пакет выдачи: собирает все трек-коды пользователя со статусом 'ready' и из оплаченных чеков."""
    
    barcode = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
        verbose_name="Штрихкод выдачи"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="extradition_packages",
        verbose_name="Получатель"
    )
    track_codes = models.ManyToManyField(
        'TrackCode',
        related_name="extradition_packages",
        verbose_name="Трек-коды"
    )
    comment = models.TextField(blank=True, null=True, verbose_name="Комментарий")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлено")
    is_issued = models.BooleanField(default=False, verbose_name="Выдано клиенту")

    def save(self, *args, **kwargs):
        if not self.barcode:
            self.barcode = f"PKG-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)

    comment = models.TextField(
        blank=True,
        null=True,
        verbose_name="Комментарий"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлено")
    is_issued = models.BooleanField(default=False, verbose_name="Выдано клиенту")

    def save(self, *args, **kwargs):
        """При первом сохранении создаёт уникальный штрихкод."""
        if not self.barcode:
            self.barcode = f"PKG-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.barcode} ({self.user.username})"
    
    @property
    def pickup_point_display(self):
        """
        Возвращает отображаемое название пункта выдачи пользователя.
        """
        try:
            profile = self.user.userprofile
            return profile.get_pickup_display()
        except:
            return "Не указан"
    
    @property
    def pickup_point(self):
        """
        Возвращает значение пункта выдачи пользователя.
        """
        try:
            profile = self.user.userprofile
            return profile.pickup
        except:
            return None

    def auto_fill(self):
        """
        Добавляет все треки пользователя, которые:
        - имеют статус 'ready'
        - принадлежат оплаченной квитанции
        """
        ready_paid_tracks = TrackCode.objects.filter(
            owner=self.user,
            status='ready',
            receiptitem__receipt__is_paid=True
        ).distinct()

        if ready_paid_tracks.exists():
            self.track_codes.add(*ready_paid_tracks)
        
        return ready_paid_tracks.count()

    @classmethod
    def create_for_user(cls, user, extradition=None):
        """
        Создаёт новый пакет выдачи и автоматически добавляет треки.
        Опционально привязывает к конкретной выдаче.
        """
        package = cls.objects.create(user=user, extradition=extradition)
        package.auto_fill()
        return package




