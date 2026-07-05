from decimal import Decimal

from django.contrib.auth.models import User
from django.db import models
from django.db.models import F
from django.utils import timezone
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


class Brand(models.Model):
    """Бренд для витрины Di.Buyer. Управляется из админки: название, ссылка,
    логотип (картинка) и счётчик кликов для статистики популярности."""
    name = models.CharField(max_length=100, verbose_name=_("Название"))
    url = models.URLField(max_length=500, verbose_name=_("Ссылка на сайт бренда"))
    logo = models.ImageField(
        upload_to='dibuyer/brands/', blank=True, null=True,
        verbose_name=_("Логотип"),
        help_text=_("Если пусто — на кнопке показывается монограмма."),
    )
    monogram = models.CharField(
        max_length=4, blank=True, default='',
        verbose_name=_("Монограмма"),
        help_text=_("1–4 буквы для кнопки без логотипа. Пусто — берутся инициалы названия."),
    )
    click_count = models.PositiveIntegerField(default=0, editable=False, verbose_name=_("Кликов"))
    is_active = models.BooleanField(default=True, verbose_name=_("Показывать на витрине"))
    sort_order = models.IntegerField(default=0, verbose_name=_("Порядок"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Добавлен"))

    class Meta:
        ordering = ['sort_order', 'name']
        verbose_name = _("Бренд Di.Buyer")
        verbose_name_plural = _("Бренды Di.Buyer")

    @property
    def display_monogram(self):
        if self.monogram:
            return self.monogram
        parts = self.name.split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[1][0]).upper()
        return self.name[:2].upper()

    def __str__(self):
        return self.name


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


class DibuyerChat(models.Model):
    """Чат клиента с администраторами Di.Buyer (аналог SupportChat).

    Два вида чатов:
    - общий чат с клиентом (``order`` IS NULL, один на клиента);
    - ветка по конкретной заявке (``order`` задан, один чат на заявку).

    Очереди/назначения операторов нет: все сотрудники Di.Buyer видят все чаты.
    """
    client = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='dibuyer_chats',
        verbose_name=_("Клиент"))
    order = models.OneToOneField(
        BuyerOrder, null=True, blank=True, on_delete=models.CASCADE,
        related_name='chat', verbose_name=_("Заявка"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Создан"))
    last_message_at = models.DateTimeField(
        null=True, blank=True, db_index=True, verbose_name=_("Последнее сообщение"))
    client_unread = models.PositiveIntegerField(
        default=0, verbose_name=_("Непрочитано клиентом"))
    staff_unread = models.PositiveIntegerField(
        default=0, verbose_name=_("Непрочитано Di.Buyer"))

    class Meta:
        verbose_name = _("Чат Di.Buyer")
        verbose_name_plural = _("Чаты Di.Buyer")
        ordering = ['-last_message_at']
        constraints = [
            models.UniqueConstraint(
                fields=['client'], condition=models.Q(order__isnull=True),
                name='dibuyer_unique_general_chat_per_client'),
        ]

    @property
    def client_name(self):
        full = self.client.get_full_name()
        return f"{full} ({self.client.username})" if full else self.client.username

    @property
    def title_for_staff(self):
        """Имя чата на стороне Di.Buyer: клиент (+ № заявки для веток)."""
        if self.order_id:
            return f"№{self.order_id} — {self.client_name}"
        return self.client_name

    def post_message(self, sender, author_role, text):
        """Единая точка добавления сообщения: создаёт DibuyerMessage и
        атомарно (F-выражения) обновляет счётчики и last_message_at."""
        msg = DibuyerMessage.objects.create(
            chat=self, sender=sender, author_role=author_role, text=text,
            is_read_by_client=(author_role != DibuyerMessage.ROLE_STAFF),
            is_read_by_staff=(author_role != DibuyerMessage.ROLE_CLIENT),
        )
        updates = {'last_message_at': timezone.now()}
        if author_role == DibuyerMessage.ROLE_CLIENT:
            updates['staff_unread'] = F('staff_unread') + 1
        elif author_role == DibuyerMessage.ROLE_STAFF:
            updates['client_unread'] = F('client_unread') + 1
        DibuyerChat.objects.filter(pk=self.pk).update(**updates)
        self.refresh_from_db()
        return msg

    def mark_read_by_client(self):
        self.messages.filter(is_read_by_client=False).update(is_read_by_client=True)
        DibuyerChat.objects.filter(pk=self.pk).update(client_unread=0)
        self.client_unread = 0

    def mark_read_by_staff(self):
        self.messages.filter(is_read_by_staff=False).update(is_read_by_staff=True)
        DibuyerChat.objects.filter(pk=self.pk).update(staff_unread=0)
        self.staff_unread = 0

    def __str__(self):
        return f"Чат Di.Buyer: {self.title_for_staff}"


class DibuyerMessage(models.Model):
    ROLE_CLIENT = 'client'
    ROLE_STAFF = 'staff'
    ROLE_CHOICES = [
        (ROLE_CLIENT, _("Клиент")),
        (ROLE_STAFF, _("Di.Buyer")),
    ]

    chat = models.ForeignKey(
        DibuyerChat, on_delete=models.CASCADE, related_name='messages',
        verbose_name=_("Чат"))
    sender = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='dibuyer_messages', verbose_name=_("Отправитель"))
    author_role = models.CharField(
        max_length=10, choices=ROLE_CHOICES, verbose_name=_("Роль автора"))
    text = models.TextField(verbose_name=_("Текст"))
    created_at = models.DateTimeField(
        auto_now_add=True, db_index=True, verbose_name=_("Отправлено"))
    is_read_by_client = models.BooleanField(
        default=False, verbose_name=_("Прочитано клиентом"))
    is_read_by_staff = models.BooleanField(
        default=False, verbose_name=_("Прочитано Di.Buyer"))

    class Meta:
        verbose_name = _("Сообщение Di.Buyer")
        verbose_name_plural = _("Сообщения Di.Buyer")
        ordering = ['id']

    def __str__(self):
        return f"[{self.get_author_role_display()}] {self.text[:40]}"


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
