from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
import uuid
from io import BytesIO
import base64
from barcode import Code128
from barcode.writer import ImageWriter
import inspect
from django.utils import timezone


class SortingLocation(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="Название")
    is_active = models.BooleanField(default=True, verbose_name="Активен")

    class Meta:
        verbose_name = "Место сортировки"
        verbose_name_plural = "Места сортировки"

    def __str__(self):
        return self.name


class TrackCode(models.Model):
    STATUS_CHOICES = [
        ('no_owner', 'Нет владельца товара'),
        ('user_added', 'Добавлен пользователем'),
        ('warehouse_cn', 'Прибыло на склад (Китай)'),
        ('shipped_cn', 'Отправлено со склада (Китай)'),
        ('delivered', 'Доставлен на сортировочный склад'),
        ('shipping_pp', 'В доставке'),
        ('ready', 'Доставлен на ПВЗ'),
        ('claimed', 'Выдано клиенту'),
    ]

    # Порядок статусов для проверки отката
    STATUS_ORDER = {
        'no_owner': -1,
        'user_added': 0,
        'warehouse_cn': 1,
        'shipped_cn': 2,
        'delivered': 3,
        'shipping_pp': 4,
        'ready': 5,
        'claimed': 6,
    }

    id = models.AutoField(primary_key=True, verbose_name="№ трек кода")
    track_code = models.CharField(max_length=100, unique=True, verbose_name="Трек код")
    update_date = models.DateField(default=timezone.now, verbose_name="Дата обновления")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, verbose_name="Статус трек-кода")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        verbose_name="Имя владельца",
        null=True,
        blank=True
    )
    description = models.CharField(max_length=255, blank=True, verbose_name="О посылке")
    weight = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True, verbose_name="Вес посылки (кг)")
    delivery_pickup = models.ForeignKey(
        'register.PickupPoint', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='delivery_tracks',
        verbose_name="Переопределённый ПВЗ доставки"
    )
    temp_owner = models.ForeignKey(
        'register.TempUser', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='track_codes',
        verbose_name="Временный владелец"
    )
    sorting_location = models.ForeignKey(
        SortingLocation, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='track_codes',
        verbose_name="Где отсортирован"
    )
    delivered_date = models.DateField(
        null=True, blank=True,
        verbose_name="Дата прихода на сорт. склад"
    )

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

    class Meta:
        verbose_name = "Трек-код"
        verbose_name_plural = "Трек-коды"

    def __str__(self):
        return f"{self.track_code} - {self.get_status_display()}"



class ArchivedTrackCode(models.Model):
    track_code = models.CharField(max_length=100, verbose_name="Трек код")
    update_date = models.DateField(verbose_name="Дата обновления")
    status = models.CharField(max_length=20, choices=TrackCode.STATUS_CHOICES, verbose_name="Статус")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        verbose_name="Владелец", null=True, blank=True
    )
    description = models.CharField(max_length=255, blank=True, verbose_name="О посылке")
    weight = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True, verbose_name="Вес (кг)")
    archived_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата архивации")

    class Meta:
        verbose_name = "Архивный трек-код"
        verbose_name_plural = "Архивные трек-коды"

    @classmethod
    def from_track(cls, track):
        """Создаёт архивный трек-код из активного TrackCode."""
        return cls.objects.create(
            track_code=track.track_code,
            update_date=track.update_date,
            status=track.status,
            owner=track.owner,
            description=track.description,
            weight=track.weight,
        )

    def __str__(self):
        return f"{self.track_code} (архив)"


class Receipt(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name="Владелец")
    created_at = models.DateField(auto_now_add=True, verbose_name="Дата создания")
    is_paid = models.BooleanField(default=False, verbose_name="Статус оплаты")
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name="Дата и время оплаты")
    total_weight = models.DecimalField(max_digits=6, decimal_places=3, default=0, verbose_name="Общий вес (кг)")
    total_price = models.DecimalField(max_digits=10, decimal_places=0, default=0, verbose_name="Сумма чека")
    price_per_kg = models.DecimalField(max_digits=6, decimal_places=2, default=0, verbose_name="Цена за кг (историческая)")
    receipt_number = models.CharField(max_length=20, unique=True, blank=True, verbose_name="Номер чека")

    # Пункт выдачи
    pickup_point = models.CharField(max_length=255, blank=True, null=True, verbose_name="Пункт выдачи")

    # Ссылка на оплату (генерируется в зависимости от пункта)
    payment_link = models.URLField(blank=True, null=True, verbose_name="Ссылка на оплату")

    class Meta:
        verbose_name = "Чек"
        verbose_name_plural = "Чеки"

    def save(self, *args, **kwargs):
        if not self.receipt_number:
            self.receipt_number = f"IC-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)

    def get_qr_base64(self):
        """Генерирует QR-код из номера чека и возвращает base64-строку."""
        import qrcode
        qr = qrcode.make(self.receipt_number, box_size=4, border=1)
        buffer = BytesIO()
        qr.save(buffer, format='PNG')
        encoded = base64.b64encode(buffer.getvalue()).decode()
        return f"data:image/png;base64,{encoded}"

    def __str__(self):
        return f"Чек {self.receipt_number} от {self.created_at} — {'Оплачен' if self.is_paid else 'Не оплачен'}"

class ReceiptItem(models.Model):
    receipt = models.ForeignKey(Receipt, related_name='items', on_delete=models.CASCADE)
    track_code = models.OneToOneField(TrackCode, on_delete=models.CASCADE)

    class Meta:
        verbose_name = "Позиция чека"
        verbose_name_plural = "Позиции чеков"

    def __str__(self):
        return str(self.track_code)

class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    message = models.CharField(max_length=255, verbose_name="Сообщение")
    is_read = models.BooleanField(default=False, verbose_name="Прочитано")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата")

    class Meta:
        verbose_name = "Уведомление"
        verbose_name_plural = "Уведомления"

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

    class Meta:
        verbose_name = "Скидка клиента"
        verbose_name_plural = "Скидки клиентов"

    def __str__(self):
        type_label = "Разовая" if self.is_temporary else "Постоянная"
        return f"{type_label} скидка {self.amount_per_kg} ₸/кг ({self.user.username})"

class UserPushSubscription(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    subscription_data = models.JSONField(default=dict, blank=True, null=True)

    class Meta:
        verbose_name = "Push-подписка"
        verbose_name_plural = "Push-подписки"

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
                except Exception:
                    self.pickup_point = "Не указан"
        super().save(*args, **kwargs)

class ExtraditionPackage(models.Model):
    """
    Пакет выдачи: собирает все трек-коды пользователя,
    у которых статус 'ready' и есть оплаченная квитанция.
    Генерация штрихкода происходит на лету, без сохранения PNG.
    """

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

    receipts = models.ManyToManyField(
        'Receipt',
        related_name="extradition_packages",
        verbose_name="Чеки",
        blank=True
    )

    comment = models.TextField(blank=True, null=True, verbose_name="Комментарий")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлено")
    is_issued = models.BooleanField(default=False, verbose_name="Выдано клиенту")

    class Meta:
        verbose_name = "Пакет выдачи"
        verbose_name_plural = "Пакеты выдачи"

    def save(self, *args, **kwargs):
        """Автоматически генерируем штрихкод, если он пустой."""
        if not self.barcode:
            self.barcode = f"PKG-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)

    @property
    def pickup_point_display(self):
        try:
            pickup = self.user.userprofile.pickup
            return str(pickup) if pickup else "Не указан"
        except Exception:
            return "Не указан"

    def get_barcode_base64(self):
        """
        Генерирует штрихкод на лету и возвращает base64-строку для отображения в шаблоне.
        """
        buffer = BytesIO()
        Code128(self.barcode, writer=ImageWriter()).write(buffer)
        encoded = base64.b64encode(buffer.getvalue()).decode()
        return f"data:image/png;base64,{encoded}"

    def __str__(self):
        return f"{self.barcode} ({self.user.username})"


class GlobalSettings(models.Model):
    price_per_kg = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=1859,
        verbose_name="Цена за кг (₸/кг)"
    )

    class Meta:
        verbose_name = "Глобальные настройки"
        verbose_name_plural = "Глобальные настройки"

    def __str__(self):
        return "Глобальные настройки"






class StorageCell(models.Model):
    pickup_point = models.ForeignKey(
        'register.PickupPoint',
        on_delete=models.CASCADE,
        related_name='storage_cells',
        verbose_name="Пункт выдачи"
    )
    cell_number = models.PositiveIntegerField(verbose_name="Номер ячейки")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='storage_cells',
        verbose_name="Клиент"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('pickup_point', 'cell_number'), ('pickup_point', 'user')]
        verbose_name = "Ячейка хранения"
        verbose_name_plural = "Ячейки хранения"

    def __str__(self):
        return f"Ячейка #{self.cell_number} — {self.user.username} ({self.pickup_point})"


class DeliveryHistory(models.Model):
    """Запись истории доставки: какой водитель доставил какой пункт выдачи."""
    driver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="delivery_history",
        verbose_name="Доставщик"
    )
    pickup_point = models.ForeignKey(
        'register.PickupPoint',
        on_delete=models.CASCADE,
        related_name="delivery_history",
        verbose_name="Пункт выдачи"
    )
    track_codes = models.ManyToManyField(
        'TrackCode',
        related_name="delivery_history",
        blank=True,
        verbose_name="Трек-коды в доставке"
    )
    total_weight = models.DecimalField(
        max_digits=10, decimal_places=3, default=0,
        verbose_name="Общий вес (кг)"
    )
    taken_at = models.DateTimeField(verbose_name="Время принятия в доставку")
    delivered_at = models.DateTimeField(
        null=True, blank=True,
        verbose_name="Время доставки до пункта"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")

    class Meta:
        verbose_name = "История доставки"
        verbose_name_plural = "История доставок"
        ordering = ['-taken_at']

    def __str__(self):
        return f"{self.driver.get_full_name() or self.driver.username} → {self.pickup_point} ({self.taken_at.strftime('%d.%m.%Y')})"


class PickupChangeRequest(models.Model):
    """Заявка на смену пункта выдачи."""
    STATUS_CHOICES = [
        ('pending', 'На рассмотрении'),
        ('approved', 'Одобрена'),
        ('rejected', 'Отклонена'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='pickup_change_requests', verbose_name="Пользователь")
    current_pickup = models.ForeignKey('register.PickupPoint', on_delete=models.SET_NULL, null=True, blank=True, related_name='+', verbose_name="Текущий ПВЗ")
    requested_pickup = models.ForeignKey('register.PickupPoint', on_delete=models.CASCADE, related_name='+', verbose_name="Запрашиваемый ПВЗ")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="Статус")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата заявки")
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name="Дата рассмотрения")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+', verbose_name="Рассмотрел")

    class Meta:
        verbose_name = "Заявка на смену ПВЗ"
        verbose_name_plural = "Заявки на смену ПВЗ"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username}: {self.current_pickup} → {self.requested_pickup} ({self.get_status_display()})"


class ClientRegistry(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    registry_date = models.DateField(verbose_name="Дата реестра")
    pickup_points = models.JSONField(verbose_name="Пункты выдачи")
    track_codes = models.ManyToManyField(TrackCode, related_name='registries', verbose_name="Трек-коды")

    class Meta:
        verbose_name = "Реестр клиентов"
        verbose_name_plural = "Реестры клиентов"

    def __str__(self):
        return f"Реестр от {self.created_at.strftime('%d.%m.%Y %H:%M')} ({self.registry_date})"
