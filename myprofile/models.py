from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
import uuid
import re
from io import BytesIO
import base64
import qrcode
import inspect
from django.utils import timezone

# Запрещённые символы в трек-кодах: китайские (CJK) и кириллица
_INVALID_TRACK_CODE_RE = re.compile(
    r'['
    r'\u4E00-\u9FFF'   # CJK Unified Ideographs (включая 订单编号)
    r'\u3400-\u4DBF'   # CJK Extension A
    r'\uF900-\uFAFF'   # CJK Compatibility Ideographs
    r'\u3000-\u303F'   # CJK Symbols and Punctuation
    r'\u0400-\u04FF'   # Кириллица
    r']'
)


class SortingLocation(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="Название")
    is_active = models.BooleanField(default=True, verbose_name="Активен")

    class Meta:
        verbose_name = "Место сортировки"
        verbose_name_plural = "Места сортировки"

    def __str__(self):
        return self.name


class ActiveTrackCodeManager(models.Manager):
    """Менеджер, исключающий архивные трек-коды из запросов."""
    def get_queryset(self):
        return super().get_queryset().filter(is_archived=False)


class TrackCode(models.Model):
    STATUS_CHOICES = [
        ('no_owner', 'Нет владельца товара'),
        ('user_added', 'Добавлен пользователем'),
        ('warehouse_cn', 'Прибыло на склад (Китай)'),
        ('shipped_cn', 'Отправлено со склада (Китай)'),
        ('unidentified', 'Неопознанка (сортировочный склад)'),
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
        'unidentified': 3,
        'delivered': 4,
        'shipping_pp': 5,
        'ready': 6,
        'claimed': 7,
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
    sorting_location = models.ForeignKey(
        SortingLocation, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='track_codes',
        verbose_name="Где отсортирован"
    )
    # Даты по этапам жизненного цикла
    date_user_added = models.DateField(null=True, blank=True, verbose_name="Дата добавления пользователем")
    date_shipped_cn = models.DateField(null=True, blank=True, verbose_name="Дата отправки со склада (Китай)")
    delivered_date = models.DateField(null=True, blank=True, verbose_name="Дата прихода на сорт. склад")
    date_shipping_pp = models.DateField(null=True, blank=True, verbose_name="Дата принятия в доставку")
    date_ready = models.DateField(null=True, blank=True, verbose_name="Дата прибытия на ПВЗ")
    date_claimed = models.DateField(null=True, blank=True, verbose_name="Дата выдачи клиенту")

    # Историческая стоимость и история статусов
    historical_price_per_kg = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        verbose_name="Тариф на момент доставки (₸/кг)"
    )
    status_history = models.JSONField(default=list, blank=True, verbose_name="История статусов")

    # Принятие на ПВЗ / складе
    is_accepted_pp = models.BooleanField(default=False, verbose_name="Принят на ПВЗ")
    accepted_pp_at = models.DateTimeField(null=True, blank=True, verbose_name="Дата принятия на ПВЗ")
    accepted_pp_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='accepted_tracks',
        verbose_name="Кто принял на ПВЗ"
    )

    # Требует переноса: прибыл без ПВЗ у клиента
    needs_pickup_reschedule = models.BooleanField(
        default=False,
        verbose_name="Требует переноса (прибыл без ПВЗ)"
    )

    # Архивация
    is_archived = models.BooleanField(default=False, verbose_name="Архивирован")
    archived_at = models.DateTimeField(null=True, blank=True, verbose_name="Дата архивации")

    # Менеджеры: objects — только активные, all_objects — все (включая архивные)
    objects = ActiveTrackCodeManager()
    all_objects = models.Manager()

    def clean(self):
        """
        Запрещаем регресс статуса: нельзя менять на статус с меньшим порядком.
        Но пропускаем проверку, если изменение делается администратором через админ-панель.
        """
        # Проверяем трек-код на наличие запрещённых символов (китайские, кириллица)
        if self.track_code and _INVALID_TRACK_CODE_RE.search(self.track_code):
            raise ValidationError({
                'track_code': 'Трек-код не может содержать китайские символы или кириллицу.'
            })

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
                old = TrackCode.all_objects.get(pk=self.pk)
            except TrackCode.DoesNotExist:
                old = None

            if old:
                old_order = self.STATUS_ORDER.get(old.status, 0)
                new_order = self.STATUS_ORDER.get(self.status, 0)
                if new_order < old_order:
                    raise ValidationError({
                        'status': f"Нельзя откатить статус с '{old.get_status_display()}' на '{dict(self.STATUS_CHOICES).get(self.status)}'."
                    })

    # Маппинг статуса → поле даты
    STATUS_DATE_FIELD = {
        'user_added': 'date_user_added',
        'shipped_cn': 'date_shipped_cn',
        'unidentified': 'delivered_date',
        'delivered': 'delivered_date',
        'shipping_pp': 'date_shipping_pp',
        'ready': 'date_ready',
        'claimed': 'date_claimed',
    }

    def log_status_change(self, changed_by=None):
        """Записывает текущий статус в историю."""
        entry = {
            'status': self.status,
            'date': timezone.localdate().isoformat(),
        }
        if changed_by:
            entry['changed_by'] = changed_by if isinstance(changed_by, str) else changed_by.username
        if not isinstance(self.status_history, list):
            self.status_history = []
        self.status_history.append(entry)

    def set_status_date(self):
        """Устанавливает дату для текущего статуса, если ещё не заполнена."""
        field = self.STATUS_DATE_FIELD.get(self.status)
        if field and not getattr(self, field, None):
            setattr(self, field, timezone.localdate())

    def save(self, *args, **kwargs):
        # Если установлен флаг пропуска валидации (для админ-панели), пропускаем full_clean
        skip_full_clean = kwargs.pop('skip_full_clean', False) or (hasattr(self, '_skip_status_validation') and self._skip_status_validation)
        if not skip_full_clean:
            self.full_clean()
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Трек-код"
        verbose_name_plural = "Трек-коды"
        default_manager_name = 'all_objects'

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
    from myprofile.receipt_lifecycle import STATUS_CHOICES as _LIFECYCLE_STATUSES

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Владелец")
    created_at = models.DateField(default=timezone.now, verbose_name="Дата создания")

    # Статус жизненного цикла чека (валидируется receipt_lifecycle.py)
    status = models.CharField(
        max_length=20, choices=_LIFECYCLE_STATUSES, default='pending',
        verbose_name="Статус чека", db_index=True,
    )
    # Привязка к доставке: 1 чек → максимум 1 доставка
    delivery = models.ForeignKey(
        'DeliveryHistory', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='receipts',
        verbose_name="Доставка",
    )

    is_paid = models.BooleanField(default=False, verbose_name="Статус оплаты")
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name="Дата и время оплаты")
    is_claimed = models.BooleanField(default=False, verbose_name="Выдано клиенту")
    claimed_at = models.DateTimeField(null=True, blank=True, verbose_name="Дата и время выдачи")
    needs_attention = models.BooleanField(default=False, verbose_name="Требует внимания")
    attention_reason = models.CharField(max_length=100, blank=True, default='', verbose_name="Причина внимания")
    attention_added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='attention_added_receipts',
        verbose_name="Кто добавил в внимание"
    )
    attention_pickup = models.CharField(max_length=255, blank=True, default='', verbose_name="ПВЗ внимания")
    attention_at = models.DateTimeField(null=True, blank=True, verbose_name="Дата установки «Требует внимания»")

    # Принятие на ПВЗ / складе
    is_accepted_pp = models.BooleanField(default=False, verbose_name="Принят на ПВЗ")
    accepted_pp_at = models.DateTimeField(null=True, blank=True, verbose_name="Дата принятия на ПВЗ")
    accepted_pp_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='accepted_receipts',
        verbose_name="Кто принял на ПВЗ"
    )

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

    # Поля, которые разрешено менять после финализации чека (операционные флаги).
    _MUTABLE_FIELDS = frozenset({
        'status', 'delivery', 'delivery_id',
        'is_paid', 'paid_at', 'is_claimed', 'claimed_at',
        'needs_attention', 'attention_reason',
        'attention_added_by', 'attention_added_by_id', 'attention_pickup', 'attention_at',
        'is_accepted_pp', 'accepted_pp_at', 'accepted_pp_by', 'accepted_pp_by_id',
    })

    @property
    def is_finalized(self):
        """Чек финализирован, если у него есть номер и уже посчитан вес."""
        return bool(self.receipt_number and self.total_weight > 0)

    def save(self, *args, **kwargs):
        is_new = not self.pk

        if is_new and not self.receipt_number:
            # Первое сохранение: получим pk, затем сгенерируем номер
            self.receipt_number = f"IC-TEMP-{uuid.uuid4().hex[:8].upper()}"
            super().save(*args, **kwargs)
            self.receipt_number = f"IC-{self.pk:06d}"
            super().save(update_fields=['receipt_number'])
            return

        # Защита от изменения содержимого финализированного чека
        if self.pk and not getattr(self, '_allow_content_update', False):
            update_fields = kwargs.get('update_fields')
            if update_fields:
                # Если указаны конкретные поля — проверяем, что все в списке разрешённых
                forbidden = set(update_fields) - self._MUTABLE_FIELDS - {'receipt_number'}
                if forbidden and self.is_finalized:
                    raise ValueError(
                        f"Чек {self.receipt_number} финализирован. "
                        f"Изменение полей {forbidden} запрещено."
                    )
            elif self.is_finalized:
                # Полный save() — проверяем, не менялись ли контентные поля
                try:
                    old = Receipt.objects.get(pk=self.pk)
                    content_fields = [
                        'total_weight', 'total_price', 'price_per_kg',
                        'owner_id', 'pickup_point',
                        'payment_link', 'created_at',
                    ]
                    changed = [
                        f for f in content_fields
                        if getattr(self, f) != getattr(old, f)
                    ]
                    if changed:
                        raise ValueError(
                            f"Чек {self.receipt_number} финализирован. "
                            f"Изменение полей {changed} запрещено."
                        )
                except Receipt.DoesNotExist:
                    pass

        super().save(*args, **kwargs)

    @property
    def client_display_name(self):
        """Отображаемое имя клиента чека."""
        if self.owner:
            full = self.owner.get_full_name()
            return f"{self.owner.username} ({full})" if full else self.owner.username
        return '—'

    def get_qr_base64(self):
        """Генерирует QR-код из номера чека и возвращает base64-строку."""
        qr = qrcode.make(self.receipt_number, box_size=4, border=1)
        buffer = BytesIO()
        qr.save(buffer, format='PNG')
        encoded = base64.b64encode(buffer.getvalue()).decode()
        return f"data:image/png;base64,{encoded}"

    def __str__(self):
        return f"Чек {self.receipt_number} от {self.created_at} — {'Оплачен' if self.is_paid else 'Не оплачен'}"

class ReceiptItem(models.Model):
    receipt = models.ForeignKey(Receipt, related_name='items', on_delete=models.CASCADE)
    track_code = models.OneToOneField(TrackCode, on_delete=models.SET_NULL, null=True, blank=True)
    # Сохранённые данные — остаются после архивации трек-кода
    track_code_str = models.CharField(max_length=100, blank=True, verbose_name="Трек-код (текст)")
    weight = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True, verbose_name="Вес (кг)")
    item_price = models.DecimalField(max_digits=10, decimal_places=0, default=0, verbose_name="Стоимость позиции (₸)")
    item_rate = models.DecimalField(max_digits=6, decimal_places=2, default=0, verbose_name="Тариф за кг (₸/кг)")

    class Meta:
        verbose_name = "Позиция чека"
        verbose_name_plural = "Позиции чеков"

    def save(self, *args, **kwargs):
        # При первом сохранении копируем данные из track_code
        if self.track_code:
            if not self.track_code_str:
                self.track_code_str = self.track_code.track_code
            if self.weight is None:
                self.weight = self.track_code.weight
        super().save(*args, **kwargs)

    @property
    def display_track_code(self):
        """Возвращает текст трек-кода (из связи или сохранённый)."""
        if self.track_code:
            return self.track_code.track_code
        return self.track_code_str

    @property
    def display_weight(self):
        """Возвращает зафиксированный вес позиции (не из живого трек-кода)."""
        return self.weight

    def __str__(self):
        return self.display_track_code or str(self.id)

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
        verbose_name="Пользователь",
        null=True,
        blank=True,
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
        owner_name = self.user.username if self.user else "—"
        return f"{type_label} скидка {self.amount_per_kg} ₸/кг ({owner_name})"

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

    def get_qr_base64(self):
        """Генерирует QR-код на лету и возвращает base64-строку для отображения в шаблоне."""
        qr = qrcode.make(self.barcode, box_size=6, border=2)
        buffer = BytesIO()
        qr.save(buffer, format='PNG')
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
    discount_weight_threshold = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=30,
        verbose_name="Порог веса для скидки (кг)"
    )

    class Meta:
        verbose_name = "Глобальные настройки"
        verbose_name_plural = "Глобальные настройки"

    def __str__(self):
        return "Глобальные настройки"






class StorageCell(models.Model):
    pickup_point = models.ForeignKey(
        'register.PickupPoint',
        on_delete=models.PROTECT,
        related_name='storage_cells',
        verbose_name="Пункт выдачи"
    )
    cell_number = models.CharField(max_length=10, verbose_name="Номер ячейки")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='storage_cells',
        verbose_name="Клиент"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('pickup_point', 'cell_number')]
        verbose_name = "Ячейка хранения"
        verbose_name_plural = "Ячейки хранения"

    @property
    def display_number(self):
        """Возвращает отображаемый номер ячейки ('0' → 'Пол', '0.1' → 'Пол 1')."""
        if self.cell_number == '0':
            return 'Пол'
        if self.cell_number.startswith('0.'):
            suffix = self.cell_number[2:]
            return 'Пол ' + suffix
        return self.cell_number

    @property
    def client_name(self):
        """Возвращает отображаемое имя клиента."""
        if self.user:
            return self.user.username
        return '—'

    @property
    def client_full_name(self):
        """Возвращает полное имя клиента (если есть)."""
        if self.user:
            return self.user.get_full_name() or ''
        return ''

    def __str__(self):
        return f"Ячейка #{self.display_number} — {self.client_name} ({self.pickup_point})"


class DeliveryHistory(models.Model):
    """Запись истории доставки: какой водитель доставил какой пункт выдачи."""
    driver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="delivery_history",
        verbose_name="Доставщик"
    )
    pickup_point = models.ForeignKey(
        'register.PickupPoint',
        on_delete=models.PROTECT,
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


class Arrival(models.Model):
    """Запись о приходе товаров за определённый день."""
    date = models.DateField(verbose_name="Дата прихода")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name="Создал"
    )
    sorting_location = models.ForeignKey(
        SortingLocation, on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name="Место сортировки"
    )
    track_codes = models.ManyToManyField(
        TrackCode, related_name='arrivals', blank=True,
        verbose_name="Трек-коды"
    )
    raw_data = models.JSONField(
        default=dict, blank=True,
        verbose_name="Исходные данные (трек-коды, владельцы, веса)"
    )
    total_tracks = models.PositiveIntegerField(default=0, verbose_name="Всего трек-кодов")
    updated_count = models.PositiveIntegerField(default=0, verbose_name="Обновлено")
    created_count = models.PositiveIntegerField(default=0, verbose_name="Создано")

    class Meta:
        verbose_name = "Приход"
        verbose_name_plural = "Приходы"
        ordering = ['-date', '-created_at']

    def __str__(self):
        loc = f" ({self.sorting_location})" if self.sorting_location else ""
        return f"Приход {self.date.strftime('%d.%m.%Y')}{loc} — {self.total_tracks} треков"


class ArrivalSession(models.Model):
    """Сессия прихода товаров — данные записываются в реальном времени на сервер."""
    STATUS_CHOICES = [
        ('active', 'Активная'),
        ('paused', 'На паузе'),
        ('inactive', 'Неактивная'),
        ('completed', 'Завершена'),
    ]
    ACTIVE_HOURS_LIMIT = 48  # сессия старше этого числа часов автоматически становится неактивной

    date = models.DateField(verbose_name="Дата прихода")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active', verbose_name="Статус")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name="Создал"
    )
    sorting_location = models.ForeignKey(
        SortingLocation, on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name="Место сортировки"
    )
    arrival = models.OneToOneField(
        Arrival, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='session',
        verbose_name="Приход (после завершения)"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")
    paused_at = models.DateTimeField(null=True, blank=True, verbose_name="Поставлена на паузу")
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name="Завершено")

    class Meta:
        verbose_name = "Сессия прихода"
        verbose_name_plural = "Сессии прихода"
        ordering = ['-created_at']

    def __str__(self):
        loc = f" ({self.sorting_location})" if self.sorting_location else ""
        return f"Сессия #{self.id} {self.date.strftime('%d.%m.%Y')}{loc} — {self.get_status_display()}"


class ArrivalSessionItem(models.Model):
    """Строка в сессии прихода — трек-код, владелец, вес."""
    session = models.ForeignKey(
        ArrivalSession, on_delete=models.CASCADE,
        related_name='items', verbose_name="Сессия"
    )
    track_code = models.CharField(max_length=100, unique=True, verbose_name="Трек-код")
    track_obj = models.ForeignKey(
        'TrackCode', on_delete=models.CASCADE,
        null=True, blank=True, related_name='session_items',
        verbose_name="Трек (объект)"
    )
    owner_name = models.CharField(max_length=150, blank=True, default='', verbose_name="Владелец (логин)")
    weight = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True, verbose_name="Вес (кг)")
    row_number = models.PositiveIntegerField(default=0, verbose_name="Номер строки")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Строка сессии прихода"
        verbose_name_plural = "Строки сессии прихода"
        ordering = ['row_number']

    def __str__(self):
        return f"{self.track_code} — {self.owner_name} ({self.weight} кг)"


class RestructureSession(models.Model):
    """Сессия реструктуризации склада ПВЗ."""
    STATUS_CHOICES = [
        ('active', 'Активная'),
        ('completed', 'Завершена'),
    ]
    pickup_point = models.ForeignKey(
        'register.PickupPoint', on_delete=models.PROTECT,
        verbose_name="Пункт выдачи"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active', verbose_name="Статус")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name="Создал"
    )
    cells_backup = models.JSONField(default=list, blank=True, verbose_name="Бэкап ячеек")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Начало")
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name="Завершено")

    class Meta:
        verbose_name = "Сессия реструктуризации"
        verbose_name_plural = "Сессии реструктуризации"
        ordering = ['-created_at']

    def __str__(self):
        return f"Реструктуризация {self.pickup_point} — {self.get_status_display()}"


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


class EmailLog(models.Model):
    """Лог отправки email-сообщений."""
    STATUS_CHOICES = [
        ('sent', 'Отправлено'),
        ('failed', 'Ошибка'),
    ]

    recipient = models.EmailField(verbose_name="Получатель")
    subject = models.CharField(max_length=255, verbose_name="Тема")
    body = models.TextField(verbose_name="Текст письма")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, verbose_name="Статус")
    error_message = models.TextField(blank=True, default='', verbose_name="Ошибка")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата отправки")

    class Meta:
        verbose_name = "Лог email"
        verbose_name_plural = "Логи email"
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.get_status_display()}] {self.subject} → {self.recipient}"


class NotificationMute(models.Model):
    """
    Заглушка уведомлений: позволяет сотруднику временно или бессрочно
    отключить отправку Telegram- и/или email-уведомлений для конкретного
    клиента или для всех клиентов сразу.
    """
    CHANNEL_CHOICES = [
        ('telegram', 'Telegram'),
        ('email', 'Email'),
        ('all', 'Все каналы'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='notification_mutes',
        verbose_name='Клиент (пусто = все клиенты)',
    )
    channel = models.CharField(
        max_length=20, choices=CHANNEL_CHOICES, default='all',
        verbose_name='Канал',
    )
    muted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_notification_mutes',
        verbose_name='Кто отключил',
    )
    muted_at = models.DateTimeField(auto_now_add=True, verbose_name='Время отключения')
    expires_at = models.DateTimeField(
        null=True, blank=True,
        verbose_name='Истекает (пусто = только вручную)',
    )
    is_active = models.BooleanField(default=True, verbose_name='Активна')
    reason = models.CharField(max_length=255, blank=True, verbose_name='Причина')

    class Meta:
        verbose_name = 'Заглушка уведомлений'
        verbose_name_plural = 'Заглушки уведомлений'
        ordering = ['-muted_at']
        indexes = [
            models.Index(fields=['is_active', 'user']),
        ]

    def __str__(self):
        target = self.user.username if self.user else 'все клиенты'
        ch = self.get_channel_display()
        exp = self.expires_at.strftime('%d.%m %H:%M') if self.expires_at else 'вручную'
        return f"Заглушка [{ch}] для {target} до {exp}"

    @property
    def is_expired(self):
        if self.expires_at:
            from django.utils import timezone as _tz
            return _tz.now() > self.expires_at
        return False

    @property
    def is_effective(self):
        """Заглушка реально действует: активна и не просрочена."""
        return self.is_active and not self.is_expired


class ExtraditionSession(models.Model):
    """
    Сессия выдачи посылки: открывается когда сотрудник ПВЗ сканирует штрихкод пакета,
    закрывается (удаляется) после оформления выдачи.
    Видна всем сотрудникам одного ПВЗ.
    """
    package = models.OneToOneField(
        'ExtraditionPackage',
        on_delete=models.CASCADE,
        related_name='extradition_session',
        verbose_name="Пакет выдачи",
    )
    pickup_point = models.ForeignKey(
        'register.PickupPoint',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='extradition_sessions',
        verbose_name="ПВЗ",
    )
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='opened_extradition_sessions',
        verbose_name="Открыл",
    )
    opened_at = models.DateTimeField(auto_now_add=True, verbose_name="Открыта в")

    class Meta:
        verbose_name = "Сессия выдачи"
        verbose_name_plural = "Сессии выдачи"
        ordering = ['-opened_at']

    def __str__(self):
        return f"Сессия: {self.package.barcode} ({self.package.user.username})"
