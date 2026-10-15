from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
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
    name = models.CharField(max_length=100, unique=True, verbose_name=_("Название"))
    is_active = models.BooleanField(default=True, verbose_name=_("Активен"))

    class Meta:
        verbose_name = _("Место сортировки")
        verbose_name_plural = _("Места сортировки")

    def __str__(self):
        return self.name


class ActiveTrackCodeManager(models.Manager):
    """Менеджер, исключающий архивные трек-коды из запросов."""
    def get_queryset(self):
        return super().get_queryset().filter(is_archived=False)


class TrackCode(models.Model):
    STATUS_CHOICES = [
        ('no_owner', _('Нет владельца товара')),
        ('user_added', _('Добавлен пользователем')),
        ('warehouse_cn', _('Прибыло на склад (Китай)')),
        ('shipped_cn', _('Отправлено со склада (Китай)')),
        ('at_customs', _('Прибыло на таможню (Китай-Казахстан)')),
        ('left_almaty', _('Прибыло в Алматы')),
        ('unidentified', _('Неопозка (сортировочный склад)')),
        ('delivered', _('Доставлен на сортировочный склад')),
        ('shipping_pp', _('В доставке')),
        ('ready', _('Доставлен на ПВЗ')),
        ('claimed', _('Выдано клиенту')),
    ]

    # Порядок статусов для проверки отката
    STATUS_ORDER = {
        'no_owner': -1,
        'user_added': 0,
        'warehouse_cn': 1,
        'shipped_cn': 2,
        'at_customs': 3,
        'left_almaty': 4,
        'unidentified': 5,
        'delivered': 6,
        'shipping_pp': 7,
        'ready': 8,
        'claimed': 9,
    }

    id = models.AutoField(primary_key=True, verbose_name=_("№ трек кода"))
    track_code = models.CharField(max_length=100, unique=True, verbose_name=_("Трек код"))
    update_date = models.DateField(default=timezone.now, verbose_name=_("Дата обновления"))
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, verbose_name=_("Статус трек-кода"))
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        verbose_name=_("Имя владельца"),
        null=True,
        blank=True
    )
    description = models.CharField(max_length=255, blank=True, verbose_name=_("О посылке"))
    weight = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True, verbose_name=_("Вес посылки (кг)"))
    delivery_pickup = models.ForeignKey(
        'register.PickupPoint', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='delivery_tracks',
        verbose_name=_("Переопределённый ПВЗ доставки")
    )
    sorting_location = models.ForeignKey(
        SortingLocation, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='track_codes',
        verbose_name=_("Где отсортирован")
    )
    # Даты по этапам жизненного цикла
    date_user_added = models.DateField(null=True, blank=True, verbose_name=_("Дата добавления пользователем"))
    date_shipped_cn = models.DateField(null=True, blank=True, verbose_name=_("Дата отправки со склада (Китай)"))
    date_at_customs = models.DateField(null=True, blank=True, verbose_name=_("Дата прибытия на таможню (Китай-Казахстан)"))
    date_left_almaty = models.DateField(null=True, blank=True, verbose_name=_("Дата прибытия в Алматы"))
    delivered_date = models.DateField(null=True, blank=True, verbose_name=_("Дата прихода на сорт. склад"))
    date_shipping_pp = models.DateField(null=True, blank=True, verbose_name=_("Дата принятия в доставку"))
    date_ready = models.DateField(null=True, blank=True, verbose_name=_("Дата прибытия на ПВЗ"))
    date_claimed = models.DateField(null=True, blank=True, verbose_name=_("Дата выдачи клиенту"))

    # Историческая стоимость и история статусов
    historical_price_per_kg = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        verbose_name=_("Тариф на момент доставки (₸/кг)")
    )
    rate_override = models.DecimalField(
        max_digits=7, decimal_places=2, null=True, blank=True,
        verbose_name=_("Фиксированный тариф позиции в чеке (₸/кг)")
    )
    status_history = models.JSONField(default=list, blank=True, verbose_name=_("История статусов"))

    # Принятие на ПВЗ / складе
    is_accepted_pp = models.BooleanField(default=False, verbose_name=_("Принят на ПВЗ"))
    accepted_pp_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Дата принятия на ПВЗ"))
    accepted_pp_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='accepted_tracks',
        verbose_name=_("Кто принял на ПВЗ")
    )

    # Требует переноса: прибыл без ПВЗ у клиента
    needs_pickup_reschedule = models.BooleanField(
        default=False,
        verbose_name=_("Требует переноса (прибыл без ПВЗ)")
    )

    # Подтверждённая неопознанная посылка, ожидающая добавления в сессию прихода.
    # Пока флаг установлен — посылка остаётся в статусе 'unidentified' и будет
    # автоматически добавлена в конец активной/новой "Сессии прихода".
    awaiting_arrival = models.BooleanField(
        default=False,
        verbose_name=_("Ожидает добавления в приход")
    )

    # Архивация
    is_archived = models.BooleanField(default=False, verbose_name=_("Архивирован"))
    archived_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Дата архивации"))

    # Менеджеры: objects — только активные, all_objects — все (включая архивные)
    objects = ActiveTrackCodeManager()
    all_objects = models.Manager()

    def clean(self):
        if self.track_code and _INVALID_TRACK_CODE_RE.search(self.track_code):
            raise ValidationError({
                'track_code': _('Трек-код не может содержать китайские символы или кириллицу.')
            })

        if hasattr(self, '_skip_status_validation') and self._skip_status_validation:
            return

        frame = inspect.currentframe()
        try:
            for _i in range(10):
                frame = frame.f_back
                if frame is None:
                    break
                filename = frame.f_code.co_filename
                if 'django/contrib/admin' in filename or 'django\\contrib\\admin' in filename:
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
        'at_customs': 'date_at_customs',
        'left_almaty': 'date_left_almaty',
        'unidentified': 'delivered_date',
        'delivered': 'delivered_date',
        'shipping_pp': 'date_shipping_pp',
        'ready': 'date_ready',
        'claimed': 'date_claimed',
    }

    def log_status_change(self, changed_by=None):
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
        field = self.STATUS_DATE_FIELD.get(self.status)
        if field and not getattr(self, field, None):
            setattr(self, field, timezone.localdate())

    def save(self, *args, **kwargs):
        skip_full_clean = kwargs.pop('skip_full_clean', False) or (hasattr(self, '_skip_status_validation') and self._skip_status_validation)
        if not skip_full_clean:
            self.full_clean()
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = _("Трек-код")
        verbose_name_plural = _("Трек-коды")
        default_manager_name = 'all_objects'

    def __str__(self):
        return f"{self.track_code} - {self.get_status_display()}"



class ArchivedTrackCode(models.Model):
    track_code = models.CharField(max_length=100, verbose_name=_("Трек код"))
    update_date = models.DateField(verbose_name=_("Дата обновления"))
    status = models.CharField(max_length=20, choices=TrackCode.STATUS_CHOICES, verbose_name=_("Статус"))
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        verbose_name=_("Владелец"), null=True, blank=True
    )
    description = models.CharField(max_length=255, blank=True, verbose_name=_("О посылке"))
    weight = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True, verbose_name=_("Вес (кг)"))
    archived_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Дата архивации"))

    class Meta:
        verbose_name = _("Архивный трек-код")
        verbose_name_plural = _("Архивные трек-коды")

    @classmethod
    def from_track(cls, track):
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

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, verbose_name=_("Владелец"))
    created_at = models.DateField(default=timezone.now, verbose_name=_("Дата создания"))

    status = models.CharField(
        max_length=20, choices=_LIFECYCLE_STATUSES, default='pending',
        verbose_name=_("Статус чека"), db_index=True,
    )
    delivery = models.ForeignKey(
        'DeliveryHistory', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='receipts',
        verbose_name=_("Доставка"),
    )

    is_paid = models.BooleanField(default=False, verbose_name=_("Статус оплаты"))
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Дата и время оплаты"))
    is_claimed = models.BooleanField(default=False, verbose_name=_("Выдано клиенту"))
    claimed_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Дата и время выдачи"))
    needs_attention = models.BooleanField(default=False, verbose_name=_("Требует внимания"))
    attention_reason = models.CharField(max_length=100, blank=True, default='', verbose_name=_("Причина внимания"))
    attention_added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='attention_added_receipts',
        verbose_name=_("Кто добавил в внимание")
    )
    attention_pickup = models.CharField(max_length=255, blank=True, default='', verbose_name=_("ПВЗ внимания"))
    attention_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Дата установки «Требует внимания»"))

    # Принятие на ПВЗ / складе
    is_accepted_pp = models.BooleanField(default=False, verbose_name=_("Принят на ПВЗ"))
    accepted_pp_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Дата принятия на ПВЗ"))
    accepted_pp_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='accepted_receipts',
        verbose_name=_("Кто принял на ПВЗ")
    )

    total_weight = models.DecimalField(max_digits=6, decimal_places=3, default=0, verbose_name=_("Общий вес (кг)"))
    total_price = models.DecimalField(max_digits=10, decimal_places=0, default=0, verbose_name=_("Сумма чека"))
    price_per_kg = models.DecimalField(max_digits=6, decimal_places=2, default=0, verbose_name=_("Цена за кг (историческая)"))
    receipt_number = models.CharField(max_length=20, unique=True, blank=True, verbose_name=_("Номер чека"))

    pickup_point = models.CharField(max_length=255, blank=True, null=True, verbose_name=_("Пункт выдачи"))
    # Ссылка на ПВЗ: сверки и фильтры идут по ней (переименование ПВЗ их не ломает);
    # pickup_point остаётся снимком названия для отображения.
    pickup = models.ForeignKey(
        'register.PickupPoint', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='receipts', verbose_name=_("Пункт выдачи (ссылка)"),
    )
    payment_link = models.URLField(blank=True, null=True, verbose_name=_("Ссылка на оплату"))

    # Чек Di.Buyer — посылки партнёрского сервиса: Inter Cargo их выдаёт, но денег
    # не берёт (оплату партнёр принимает на свои счета), поэтому сумма чека 0 и
    # выдача разрешена только после отметки партнёра об оплате
    # (myprofile/partner_receipts.py). Ключ pending-чека: клиент + дата + ПВЗ + источник.
    SOURCE_CARGO = 'cargo'
    SOURCE_DIBUYER = 'dibuyer'
    SOURCE_CHOICES = [
        (SOURCE_CARGO, 'Inter Cargo'),
        (SOURCE_DIBUYER, _('Di.Buyer (партнёр)')),
    ]
    source = models.CharField(
        max_length=10, choices=SOURCE_CHOICES, default=SOURCE_CARGO, db_index=True,
        verbose_name=_("Источник"),
    )

    class Meta:
        verbose_name = _("Чек")
        verbose_name_plural = _("Чеки")

    _MUTABLE_FIELDS = frozenset({
        'status', 'delivery', 'delivery_id',
        'is_paid', 'paid_at', 'is_claimed', 'claimed_at',
        'needs_attention', 'attention_reason',
        'attention_added_by', 'attention_added_by_id', 'attention_pickup', 'attention_at',
        'is_accepted_pp', 'accepted_pp_at', 'accepted_pp_by', 'accepted_pp_by_id',
    })

    @property
    def is_finalized(self):
        return bool(self.receipt_number and self.total_weight > 0)

    def save(self, *args, **kwargs):
        is_new = not self.pk

        if is_new and not self.receipt_number:
            self.receipt_number = f"IC-TEMP-{uuid.uuid4().hex[:8].upper()}"
            super().save(*args, **kwargs)
            self.receipt_number = f"IC-{self.pk:06d}"
            super().save(update_fields=['receipt_number'])
            ReceiptQrCode.register(self)
            return

        if self.pk and not getattr(self, '_allow_content_update', False):
            update_fields = kwargs.get('update_fields')
            if update_fields:
                forbidden = set(update_fields) - self._MUTABLE_FIELDS - {'receipt_number'}
                if forbidden and self.is_finalized:
                    raise ValueError(
                        f"Чек {self.receipt_number} финализирован. "
                        f"Изменение полей {forbidden} запрещено."
                    )
            elif self.is_finalized:
                try:
                    old = Receipt.objects.get(pk=self.pk)
                    content_fields = [
                        'total_weight', 'total_price', 'price_per_kg',
                        'owner_id', 'pickup_point', 'pickup_id',
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
        if is_new:
            ReceiptQrCode.register(self)

    @property
    def client_display_name(self):
        if self.owner:
            full = self.owner.get_full_name()
            return f"{self.owner.username} ({full})" if full else self.owner.username
        return '—'

    @property
    def client_status(self):
        """Клиентский статус чека: 'sorting'/'in_delivery'/'not_issued'/'issued'/None.

        Выводится из статусов привязанных трек-кодов
        (см. ``receipt_lifecycle.derive_client_status_from_tracks``).
        """
        from myprofile.receipt_lifecycle import derive_client_status_from_tracks
        return derive_client_status_from_tracks(self)

    @property
    def client_status_display(self):
        """Человекочитаемое название клиентского статуса
        ("На сортировочном пункте" / "В доставке" / "Не выдано" / "Выдано")."""
        from myprofile.receipt_lifecycle import CLIENT_STATUS_DISPLAY
        return CLIENT_STATUS_DISPLAY.get(self.client_status, '—')

    def get_qr_base64(self):
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
    track_code_str = models.CharField(max_length=100, blank=True, verbose_name=_("Трек-код (текст)"))
    weight = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True, verbose_name=_("Вес (кг)"))
    item_price = models.DecimalField(max_digits=10, decimal_places=0, default=0, verbose_name=_("Стоимость позиции (₸)"))
    item_rate = models.DecimalField(max_digits=7, decimal_places=2, default=0, verbose_name=_("Тариф за кг (₸/кг)"))

    class Meta:
        verbose_name = _("Позиция чека")
        verbose_name_plural = _("Позиции чеков")

    def save(self, *args, **kwargs):
        if self.track_code:
            if not self.track_code_str:
                self.track_code_str = self.track_code.track_code
            if self.weight is None:
                self.weight = self.track_code.weight
        super().save(*args, **kwargs)

    @property
    def display_track_code(self):
        if self.track_code:
            return self.track_code.track_code
        return self.track_code_str

    @property
    def display_weight(self):
        return self.weight

    def __str__(self):
        return self.display_track_code or str(self.id)


class ReceiptQrCode(models.Model):
    """Реестр и архив QR-кодов чеков — единое место хранения каждого
    когда-либо выданного receipt_number.

    Записи не удаляются: при удалении чека остаётся архивная строка
    (receipt=NULL, archived_at установлен), при объединении чеков ставится
    ссылка superseded_by на актуальный чек. Это позволяет при сканировании
    напечатанного ранее QR-кода объяснить, что с ним произошло, вместо
    ошибки «код не найден в системе».
    """
    code = models.CharField(max_length=32, unique=True, verbose_name=_("Код (содержимое QR)"))
    receipt = models.ForeignKey(
        Receipt, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='qr_codes', verbose_name=_("Чек"))
    superseded_by = models.ForeignKey(
        Receipt, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='superseded_qr_codes', verbose_name=_("Заменён чеком"))
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='receipt_qr_codes', verbose_name=_("Клиент"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Создано"))
    archived_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Архивировано"))
    note = models.CharField(max_length=255, blank=True, default='', verbose_name=_("Примечание"))

    class Meta:
        verbose_name = _("QR-код чека")
        verbose_name_plural = _("QR-коды чеков (реестр)")

    @property
    def is_active(self):
        return self.receipt_id is not None and self.archived_at is None

    def get_qr_base64(self):
        qr = qrcode.make(self.code, box_size=4, border=1)
        buffer = BytesIO()
        qr.save(buffer, format='PNG')
        encoded = base64.b64encode(buffer.getvalue()).decode()
        return f"data:image/png;base64,{encoded}"

    @classmethod
    def register(cls, receipt):
        """Регистрирует (или актуализирует) запись реестра для номера чека.

        Временные номера IC-TEMP-* не регистрируются — они живут только
        между двумя save() при создании чека и никогда не печатаются.
        """
        number = receipt.receipt_number
        if not number or number.startswith('IC-TEMP-'):
            return None
        obj, _created = cls.objects.update_or_create(
            code=number,
            defaults={'receipt': receipt, 'owner': receipt.owner, 'archived_at': None},
        )
        return obj

    def __str__(self):
        state = "актуален" if self.is_active else "архив"
        return f"{self.code} ({state})"


def _archive_receipt_qr_on_delete(sender, instance, **kwargs):
    """При удалении чека помечаем его записи реестра как архивные
    (FK receipt обнулится сам через SET_NULL)."""
    ReceiptQrCode.objects.filter(receipt=instance, archived_at__isnull=True).update(
        archived_at=timezone.now(),
        note="Чек удалён",
    )


models.signals.pre_delete.connect(
    _archive_receipt_qr_on_delete, sender=Receipt,
    dispatch_uid='receipt_qr_archive_on_delete',
)


class Notification(models.Model):
    PUSH_PENDING = 'pending'
    PUSH_SENT = 'sent'
    PUSH_FAILED = 'failed'
    PUSH_SKIPPED = 'skipped'
    PUSH_STATUS_CHOICES = [
        (PUSH_PENDING, _("Ожидает отправки")),
        (PUSH_SENT, _("Отправлено")),
        (PUSH_FAILED, _("Ошибка")),
        (PUSH_SKIPPED, _("Пропущено")),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    message = models.CharField(max_length=255, verbose_name=_("Сообщение"))
    is_read = models.BooleanField(default=False, verbose_name=_("Прочитано"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Дата"))
    # Outbox для browser push: 'pending' ставится явно (notify_in_user_language),
    # отправляет фоновый воркер бота (tgbot/bot/workers/push.py), а не HTTP-запрос.
    # default='sent', чтобы старые строки не попали в очередь без data-миграции.
    push_status = models.CharField(
        max_length=10, choices=PUSH_STATUS_CHOICES, default=PUSH_SENT,
        db_index=True, verbose_name=_("Push-статус"),
    )
    push_attempts = models.PositiveSmallIntegerField(default=0, verbose_name=_("Попыток push"))

    class Meta:
        verbose_name = _("Уведомление")
        verbose_name_plural = _("Уведомления")

    def __str__(self):
        return f"Уведомление для {self.user.username}: {self.message}"

class CustomerDiscount(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="discounts",
        verbose_name=_("Пользователь"),
        null=True,
        blank=True,
    )
    amount_per_kg = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        verbose_name=_("Скидка (₸/кг)")
    )
    is_temporary = models.BooleanField(default=False, verbose_name=_("Разовая скидка"))
    active = models.BooleanField(default=True, verbose_name=_("Активная скидка"))
    comment = models.CharField(max_length=255, blank=True, verbose_name=_("Комментарий"))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Скидка клиента")
        verbose_name_plural = _("Скидки клиентов")

    def __str__(self):
        type_label = "Разовая" if self.is_temporary else "Постоянная"
        owner_name = self.user.username if self.user else "—"
        return f"{type_label} скидка {self.amount_per_kg} ₸/кг ({owner_name})"

class UserPushSubscription(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    subscription_data = models.JSONField(default=dict, blank=True, null=True)

    class Meta:
        verbose_name = _("Push-подписка")
        verbose_name_plural = _("Push-подписки")

class Extradition(models.Model):
    package = models.OneToOneField(
        'ExtraditionPackage',
        on_delete=models.CASCADE,
        related_name='extradition',
        verbose_name=_("Пакет выдачи")
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="extraditions",
        verbose_name=_("Получатель")
    )
    pickup_point = models.CharField(max_length=255, verbose_name=_("Пункт выдачи"))
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="issued_extraditions",
        verbose_name=_("Сотрудник, выдавший посылку")
    )
    confirmed = models.BooleanField(default=False, verbose_name=_("Подтверждено получателем"))
    comment = models.TextField(blank=True, verbose_name=_("Комментарий"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Создано"))

    class Meta:
        verbose_name = _("Выдача посылки")
        verbose_name_plural = _("Выдачи посылок")

    def __str__(self):
        return f"Выдача #{self.id} — {self.user.username}"

    def save(self, *args, **kwargs):
        if self.package and not self.pk:
            self.user = self.package.user
            if not self.pickup_point:
                try:
                    self.pickup_point = self.package.pickup_point_display
                except Exception:
                    self.pickup_point = "Не указан"
        super().save(*args, **kwargs)

class ExtraditionPackage(models.Model):
    barcode = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
        verbose_name=_("Штрихкод выдачи")
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="extradition_packages",
        verbose_name=_("Получатель")
    )

    receipts = models.ManyToManyField(
        'Receipt',
        related_name="extradition_packages",
        verbose_name=_("Чеки"),
        blank=True
    )

    comment = models.TextField(blank=True, null=True, verbose_name=_("Комментарий"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Создано"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Обновлено"))
    is_issued = models.BooleanField(default=False, verbose_name=_("Выдано клиенту"))

    class Meta:
        verbose_name = _("Пакет выдачи")
        verbose_name_plural = _("Пакеты выдачи")

    def save(self, *args, **kwargs):
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
        verbose_name=_("Цена за кг (₸/кг)")
    )
    discount_weight_threshold = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=30,
        verbose_name=_("Порог веса для скидки (кг)")
    )
    # Квоты ролей (редактируемые Главным администратором). 0 = без лимита.
    quota_main_admin = models.PositiveIntegerField(
        default=5, verbose_name=_("Лимит: Главный администратор"))
    quota_director = models.PositiveIntegerField(
        default=3, verbose_name=_("Лимит: Директор"))
    quota_support = models.PositiveIntegerField(
        default=3, verbose_name=_("Лимит: Менеджер тех.поддержки"))

    class Meta:
        verbose_name = _("Глобальные настройки")
        verbose_name_plural = _("Глобальные настройки")

    def __str__(self):
        return "Глобальные настройки"


class StorageCell(models.Model):
    pickup_point = models.ForeignKey(
        'register.PickupPoint',
        on_delete=models.PROTECT,
        related_name='storage_cells',
        verbose_name=_("Пункт выдачи")
    )
    cell_number = models.CharField(max_length=10, verbose_name=_("Номер ячейки"))
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='storage_cells',
        verbose_name=_("Клиент")
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('pickup_point', 'cell_number')]
        verbose_name = _("Ячейка хранения")
        verbose_name_plural = _("Ячейки хранения")

    @property
    def display_number(self):
        if self.cell_number == '0':
            return 'Пол'
        if self.cell_number.startswith('0.'):
            suffix = self.cell_number[2:]
            return 'Пол ' + suffix
        return self.cell_number

    @property
    def client_name(self):
        if self.user:
            return self.user.username
        return '—'

    @property
    def client_full_name(self):
        if self.user:
            return self.user.get_full_name() or ''
        return ''

    def __str__(self):
        return f"Ячейка #{self.display_number} — {self.client_name} ({self.pickup_point})"


class DeliveryHistory(models.Model):
    driver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="delivery_history",
        verbose_name=_("Доставщик")
    )
    pickup_point = models.ForeignKey(
        'register.PickupPoint',
        on_delete=models.PROTECT,
        related_name="delivery_history",
        verbose_name=_("Пункт выдачи")
    )
    track_codes = models.ManyToManyField(
        'TrackCode',
        related_name="delivery_history",
        blank=True,
        verbose_name=_("Трек-коды в доставке")
    )
    total_weight = models.DecimalField(
        max_digits=10, decimal_places=3, default=0,
        verbose_name=_("Общий вес (кг)")
    )
    taken_at = models.DateTimeField(verbose_name=_("Время принятия в доставку"))
    delivered_at = models.DateTimeField(
        null=True, blank=True,
        verbose_name=_("Время доставки до пункта")
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Создано"))

    class Meta:
        verbose_name = _("История доставки")
        verbose_name_plural = _("История доставок")
        ordering = ['-taken_at']

    def __str__(self):
        return f"{self.driver.get_full_name() or self.driver.username} → {self.pickup_point} ({self.taken_at.strftime('%d.%m.%Y')})"


class PickupChangeRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', _('На рассмотрении')),
        ('approved', _('Одобрена')),
        ('rejected', _('Отклонена')),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='pickup_change_requests', verbose_name=_("Пользователь"))
    current_pickup = models.ForeignKey('register.PickupPoint', on_delete=models.SET_NULL, null=True, blank=True, related_name='+', verbose_name=_("Текущий ПВЗ"))
    requested_pickup = models.ForeignKey('register.PickupPoint', on_delete=models.CASCADE, related_name='+', verbose_name=_("Запрашиваемый ПВЗ"))
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name=_("Статус"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Дата заявки"))
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Дата рассмотрения"))
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+', verbose_name=_("Рассмотрел"))

    class Meta:
        verbose_name = _("Заявка на смену ПВЗ")
        verbose_name_plural = _("Заявки на смену ПВЗ")
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username}: {self.current_pickup} → {self.requested_pickup} ({self.get_status_display()})"


class Arrival(models.Model):
    date = models.DateField(verbose_name=_("Дата прихода"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Дата создания"))
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name=_("Создал")
    )
    sorting_location = models.ForeignKey(
        SortingLocation, on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name=_("Место сортировки")
    )
    track_codes = models.ManyToManyField(
        TrackCode, related_name='arrivals', blank=True,
        verbose_name=_("Трек-коды")
    )
    raw_data = models.JSONField(
        default=dict, blank=True,
        verbose_name=_("Исходные данные (трек-коды, владельцы, веса)")
    )
    total_tracks = models.PositiveIntegerField(default=0, verbose_name=_("Всего трек-кодов"))
    updated_count = models.PositiveIntegerField(default=0, verbose_name=_("Обновлено"))
    created_count = models.PositiveIntegerField(default=0, verbose_name=_("Создано"))

    class Meta:
        verbose_name = _("Приход")
        verbose_name_plural = _("Приходы")
        ordering = ['-date', '-created_at']

    def __str__(self):
        loc = f" ({self.sorting_location})" if self.sorting_location else ""
        return f"Приход {self.date.strftime('%d.%m.%Y')}{loc} — {self.total_tracks} треков"


class ArrivalSession(models.Model):
    STATUS_CHOICES = [
        ('active', _('Активная')),
        ('paused', _('На паузе')),
        ('inactive', _('Неактивная')),
        ('completed', _('Завершена')),
    ]
    ACTIVE_HOURS_LIMIT = 48

    date = models.DateField(verbose_name=_("Дата прихода"))
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active', verbose_name=_("Статус"))
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name=_("Создал")
    )
    sorting_location = models.ForeignKey(
        SortingLocation, on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name=_("Место сортировки")
    )
    arrival = models.OneToOneField(
        Arrival, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='session',
        verbose_name=_("Приход (после завершения)")
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Создано"))
    paused_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Поставлена на паузу"))
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Завершено"))
    # Резервный сырой снимок последнего автосохранения (на случай потери связи).
    # Хранит входящий список строк как есть — восстановимая копия, доступная с любого устройства.
    draft_data = models.JSONField(default=dict, blank=True, verbose_name=_("Черновик (резерв)"))
    draft_saved_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Черновик сохранён"))
    # Защита от затирания (myprofile/arrival_autosave.py): номер версии строк сессии,
    # хеш текущего содержимого и последний применённый (клиент, порядковый номер).
    revision = models.PositiveIntegerField(default=0, verbose_name=_("Версия строк"))
    content_hash = models.CharField(max_length=64, blank=True, default='', verbose_name=_("Хеш содержимого"))
    # Сколько строк записано последним сохранением — сверка для повторного сохранения:
    # совпал хеш, но строк в БД меньше → строки пропали, записываем заново
    applied_rows = models.PositiveIntegerField(default=0, verbose_name=_("Записано строк"))
    last_client_id = models.CharField(max_length=64, blank=True, default='', verbose_name=_("Последний клиент"))
    last_client_seq = models.BigIntegerField(default=0, verbose_name=_("Порядковый номер клиента"))
    # 48-часовой лимит считается от последнего сохранения, а не от создания
    last_activity_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Последняя активность"))
    # Кто сейчас редактирует (одно устройство/вкладка за раз)
    editor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+', verbose_name=_("Редактирует")
    )
    editor_client_id = models.CharField(max_length=64, blank=True, default='', verbose_name=_("Устройство редактора"))
    editor_seen_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Редактор был в сети"))

    class Meta:
        verbose_name = _("Сессия прихода")
        verbose_name_plural = _("Сессии прихода")
        ordering = ['-created_at']

    def __str__(self):
        loc = f" ({self.sorting_location})" if self.sorting_location else ""
        return f"Сессия #{self.id} {self.date.strftime('%d.%m.%Y')}{loc} — {self.get_status_display()}"


class ArrivalSessionItem(models.Model):
    session = models.ForeignKey(
        ArrivalSession, on_delete=models.CASCADE,
        related_name='items', verbose_name=_("Сессия")
    )
    track_code = models.CharField(max_length=100, unique=True, verbose_name=_("Трек-код"))
    track_obj = models.ForeignKey(
        'TrackCode', on_delete=models.CASCADE,
        null=True, blank=True, related_name='session_items',
        verbose_name=_("Трек (объект)")
    )
    owner_name = models.CharField(max_length=150, blank=True, default='', verbose_name=_("Владелец (логин)"))
    weight = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True, verbose_name=_("Вес (кг)"))
    row_number = models.PositiveIntegerField(default=0, verbose_name=_("Номер строки"))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Строка сессии прихода")
        verbose_name_plural = _("Строки сессии прихода")
        ordering = ['row_number']

    def __str__(self):
        return f"{self.track_code} — {self.owner_name} ({self.weight} кг)"


class ArrivalSessionSnapshot(models.Model):
    """Журнал сохранений сессии прихода: каждый присланный набор строк хранится
    отдельной записью (в т.ч. отклонённые), чтобы любую точку можно было восстановить."""
    SOURCE_CHOICES = [
        ('fetch', _('Автосохранение')),
        ('beacon', _('Уход со страницы')),
        ('sw', _('Досылка из фона')),
        ('complete', _('Перед завершением')),
        ('restore', _('Восстановление')),
        ('legacy', _('Старая версия страницы')),
    ]
    OUTCOME_CHOICES = [
        ('received', _('Получен')),
        ('applied', _('Применён')),
        ('stale', _('Устаревший (есть новее)')),
        ('conflict', _('Конфликт версий')),
        ('shrink', _('Резкое сокращение строк')),
        ('locked', _('Редактирует другое устройство')),
        ('inactive', _('Сессия не активна')),
        ('error', _('Ошибка')),
    ]

    session = models.ForeignKey(
        ArrivalSession, on_delete=models.CASCADE,
        related_name='snapshots', verbose_name=_("Сессия")
    )
    items = models.JSONField(default=list, verbose_name=_("Строки"))
    row_count = models.PositiveIntegerField(default=0, verbose_name=_("Строк"))
    items_hash = models.CharField(max_length=64, blank=True, default='')
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default='fetch', verbose_name=_("Источник"))
    outcome = models.CharField(max_length=10, choices=OUTCOME_CHOICES, default='received', verbose_name=_("Результат"))
    base_revision = models.IntegerField(null=True, blank=True, verbose_name=_("Базовая версия"))
    revision = models.PositiveIntegerField(default=0, verbose_name=_("Версия после сохранения"))
    client_id = models.CharField(max_length=64, blank=True, default='', verbose_name=_("Устройство"))
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+', verbose_name=_("Пользователь")
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Время"))

    class Meta:
        verbose_name = _("Снимок сессии прихода")
        verbose_name_plural = _("Снимки сессий прихода")
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['session', 'created_at'])]

    def __str__(self):
        return f"#{self.session_id} {self.created_at:%d.%m %H:%M:%S} — {self.row_count} ({self.outcome})"


class RestructureSession(models.Model):
    STATUS_CHOICES = [
        ('active', _('Активная')),
        ('completed', _('Завершена')),
    ]
    pickup_point = models.ForeignKey(
        'register.PickupPoint', on_delete=models.PROTECT,
        verbose_name=_("Пункт выдачи")
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active', verbose_name=_("Статус"))
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name=_("Создал")
    )
    cells_backup = models.JSONField(default=list, blank=True, verbose_name=_("Бэкап ячеек"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Начало"))
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Завершено"))

    class Meta:
        verbose_name = _("Сессия реструктуризации")
        verbose_name_plural = _("Сессии реструктуризации")
        ordering = ['-created_at']

    def __str__(self):
        return f"Реструктуризация {self.pickup_point} — {self.get_status_display()}"


class InventorySession(models.Model):
    """Сессия инвентаризации склада ПВЗ: сканирование QR чеков, сверка,
    авто-приёмка и тихая выдача ненайденного при завершении."""
    STATUS_CHOICES = [
        ('active', _('Активная')),
        ('completed', _('Завершена')),
        ('cancelled', _('Отменена')),
    ]
    pickup_point = models.ForeignKey(
        'register.PickupPoint', on_delete=models.PROTECT,
        related_name='inventory_sessions', verbose_name=_("Пункт выдачи"))
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active', verbose_name=_("Статус"))
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name=_("Создал"))
    started_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Начало"))
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Завершено"))
    report = models.JSONField(default=dict, blank=True, verbose_name=_("Отчёт"))
    # Аккаунты, созданные в сессии (для отката при отмене)
    created_user_ids = models.JSONField(default=list, blank=True, verbose_name=_("Созданные аккаунты"))
    auto_accepted_count = models.PositiveIntegerField(default=0, verbose_name=_("Авто-принято чеков"))
    auto_issued_count = models.PositiveIntegerField(default=0, verbose_name=_("Тихо выдано чеков"))
    auto_issued_amount = models.DecimalField(
        max_digits=12, decimal_places=0, default=0, verbose_name=_("Сумма тихо выданного (₸)"))

    class Meta:
        verbose_name = _("Сессия инвентаризации")
        verbose_name_plural = _("Сессии инвентаризации")
        ordering = ['-started_at']
        constraints = [
            models.UniqueConstraint(
                fields=['pickup_point'], condition=models.Q(status='active'),
                name='uniq_active_inventory_per_pickup'),
        ]

    def __str__(self):
        return f"Инвентаризация {self.pickup_point} — {self.get_status_display()}"


class InventoryScan(models.Model):
    """Строка сессии инвентаризации: отсканированный (или введённый вручную) чек."""
    FLAG_CHOICES = [
        ('', _('ОК')),
        ('foreign_pickup', _('Чек другого ПВЗ')),
    ]
    session = models.ForeignKey(
        InventorySession, on_delete=models.CASCADE,
        related_name='scans', verbose_name=_("Сессия"))
    receipt = models.ForeignKey(
        Receipt, on_delete=models.CASCADE,
        related_name='inventory_scans', verbose_name=_("Чек"))
    cell_number = models.CharField(max_length=10, verbose_name=_("Номер ячейки"))
    is_legacy = models.BooleanField(default=False, verbose_name=_("Введён вручную (legacy)"))
    flag = models.CharField(max_length=20, blank=True, default='', choices=FLAG_CHOICES, verbose_name=_("Отметка"))
    scanned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name=_("Кто сканировал"))
    scanned_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Когда"))

    class Meta:
        verbose_name = _("Скан инвентаризации")
        verbose_name_plural = _("Сканы инвентаризации")
        ordering = ['scanned_at']
        unique_together = [('session', 'receipt')]

    def __str__(self):
        return f"{self.receipt.receipt_number} → ячейка {self.cell_number}"


class ClientRegistry(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Дата создания"))
    registry_date = models.DateField(verbose_name=_("Дата реестра"))
    pickup_points = models.JSONField(verbose_name=_("Пункты выдачи"))
    track_codes = models.ManyToManyField(TrackCode, related_name='registries', verbose_name=_("Трек-коды"))

    class Meta:
        verbose_name = _("Реестр клиентов")
        verbose_name_plural = _("Реестры клиентов")

    def __str__(self):
        return f"Реестр от {self.created_at.strftime('%d.%m.%Y %H:%M')} ({self.registry_date})"


class EmailLog(models.Model):
    STATUS_CHOICES = [
        ('sent', _('Отправлено')),
        ('failed', _('Ошибка')),
    ]

    recipient = models.EmailField(verbose_name=_("Получатель"))
    subject = models.CharField(max_length=255, verbose_name=_("Тема"))
    body = models.TextField(verbose_name=_("Текст письма"))
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, verbose_name=_("Статус"))
    error_message = models.TextField(blank=True, default='', verbose_name=_("Ошибка"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Дата отправки"))

    class Meta:
        verbose_name = _("Лог email")
        verbose_name_plural = _("Логи email")
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.get_status_display()}] {self.subject} → {self.recipient}"


class NotificationMute(models.Model):
    CHANNEL_CHOICES = [
        ('telegram', _('Telegram')),
        ('email', _('Email')),
        ('all', _('Все каналы')),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='notification_mutes',
        verbose_name=_('Клиент (пусто = все клиенты)'),
    )
    channel = models.CharField(
        max_length=20, choices=CHANNEL_CHOICES, default='all',
        verbose_name=_('Канал'),
    )
    muted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_notification_mutes',
        verbose_name=_('Кто отключил'),
    )
    muted_at = models.DateTimeField(auto_now_add=True, verbose_name=_('Время отключения'))
    expires_at = models.DateTimeField(
        null=True, blank=True,
        verbose_name=_('Истекает (пусто = только вручную)'),
    )
    is_active = models.BooleanField(default=True, verbose_name=_('Активна'))
    reason = models.CharField(max_length=255, blank=True, verbose_name=_('Причина'))

    class Meta:
        verbose_name = _('Заглушка уведомлений')
        verbose_name_plural = _('Заглушки уведомлений')
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
        return self.is_active and not self.is_expired


class ExtraditionSession(models.Model):
    package = models.OneToOneField(
        'ExtraditionPackage',
        on_delete=models.CASCADE,
        related_name='extradition_session',
        verbose_name=_("Пакет выдачи"),
    )
    pickup_point = models.ForeignKey(
        'register.PickupPoint',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='extradition_sessions',
        verbose_name=_("ПВЗ"),
    )
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='opened_extradition_sessions',
        verbose_name=_("Открыл"),
    )
    opened_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Открыта в"))

    class Meta:
        verbose_name = _("Сессия выдачи")
        verbose_name_plural = _("Сессии выдачи")
        ordering = ['-opened_at']

    def __str__(self):
        return f"Сессия: {self.package.barcode} ({self.package.user.username})"


class ContractViolation(models.Model):
    """Журнал нарушений контрактов фреймворка валидации выполнения функций."""

    SEVERITY_CHOICES = [
        ("critical", _("Критично")),
        ("warning", _("Предупреждение")),
    ]

    function = models.CharField(max_length=200, verbose_name=_("Функция"))
    contract = models.CharField(max_length=200, verbose_name=_("Контракт"))
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, db_index=True, verbose_name=_("Серьёзность"))
    message = models.TextField(verbose_name=_("Сообщение"))
    context = models.JSONField(default=dict, blank=True, verbose_name=_("Контекст"))
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name=_("Время"))
    resolved = models.BooleanField(default=False, db_index=True, verbose_name=_("Разобрано"))

    class Meta:
        verbose_name = _("Нарушение контракта")
        verbose_name_plural = _("Нарушения контрактов")
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.severity}] {self.function} :: {self.contract}"


class BulkJob(models.Model):
    """Фоновая массовая операция (django-q2) со страницей прогресса."""
    KIND_CHOICES = [
        ('shipped_cn_import', _("Импорт «Отправлено из Китая»")),
        ('day_receipts', _("Генерация чеков за день")),
    ]
    STATUS_CHOICES = [
        ('pending', _("В очереди")),
        ('running', _("Выполняется")),
        ('done', _("Завершена")),
        ('failed', _("Ошибка")),
    ]

    kind = models.CharField(max_length=32, choices=KIND_CHOICES, verbose_name=_("Тип"))
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending',
                              db_index=True, verbose_name=_("Статус"))
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name=_("Запустил"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Создана"))
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Завершена в"))
    total = models.PositiveIntegerField(default=0, verbose_name=_("Всего"))
    processed = models.PositiveIntegerField(default=0, verbose_name=_("Обработано"))
    result = models.JSONField(default=dict, blank=True, verbose_name=_("Результат"))
    error_text = models.TextField(blank=True, default='', verbose_name=_("Ошибка"))

    class Meta:
        verbose_name = _("Фоновая операция")
        verbose_name_plural = _("Фоновые операции")
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_kind_display()} #{self.pk} — {self.get_status_display()}"
