"""Мессенджер техподдержки: чат клиента с операторами.

Схема: один вечный чат на клиента (SupportChat) + сообщения (SupportMessage).
Закрытый чат переоткрывается новым сообщением клиента — история не теряется.

Задел под тикеты: если понадобится работа по тикетам, добавляется модель
SupportTicket и nullable FK ``SupportMessage.ticket`` отдельной миграцией —
текущая схема (чат как контейнер всей истории) при этом не меняется.
"""
from django.conf import settings
from django.db import models
from django.db.models import F
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class SupportChat(models.Model):
    STATUS_OPEN = 'open'
    STATUS_CLOSED = 'closed'
    STATUS_CHOICES = [
        (STATUS_OPEN, _("Открыт")),
        (STATUS_CLOSED, _("Закрыт")),
    ]

    client = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='support_chat', verbose_name=_("Клиент"))
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='support_chats_assigned', verbose_name=_("Назначен оператору"))
    escalated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='support_chats_escalated',
        verbose_name=_("Передал директору"))
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default=STATUS_OPEN,
        verbose_name=_("Статус"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Создан"))
    last_message_at = models.DateTimeField(
        null=True, blank=True, db_index=True, verbose_name=_("Последнее сообщение"))
    client_unread = models.PositiveIntegerField(
        default=0, verbose_name=_("Непрочитано клиентом"))
    staff_unread = models.PositiveIntegerField(
        default=0, verbose_name=_("Непрочитано поддержкой"))

    class Meta:
        verbose_name = _("Чат поддержки")
        verbose_name_plural = _("Чаты поддержки")
        ordering = ['-last_message_at']

    @property
    def title_for_staff(self):
        """Имя чата на стороне поддержки = имя клиента."""
        full = self.client.get_full_name()
        return f"{full} ({self.client.username})" if full else self.client.username

    def post_message(self, sender, author_role, text):
        """Единая точка добавления сообщения.

        Создаёт SupportMessage, атомарно (через F-выражения) обновляет счётчики
        непрочитанного и last_message_at, переоткрывает закрытый чат при любом
        несистемном сообщении.
        """
        msg = SupportMessage.objects.create(
            chat=self, sender=sender, author_role=author_role, text=text,
            is_read_by_client=(author_role != SupportMessage.ROLE_STAFF),
            is_read_by_staff=(author_role != SupportMessage.ROLE_CLIENT),
        )
        updates = {'last_message_at': timezone.now()}
        if author_role == SupportMessage.ROLE_CLIENT:
            updates['staff_unread'] = F('staff_unread') + 1
        elif author_role == SupportMessage.ROLE_STAFF:
            updates['client_unread'] = F('client_unread') + 1
        if author_role != SupportMessage.ROLE_SYSTEM and self.status == self.STATUS_CLOSED:
            updates['status'] = self.STATUS_OPEN
        SupportChat.objects.filter(pk=self.pk).update(**updates)
        self.refresh_from_db()
        return msg

    def post_system_message(self, text):
        """Служебное сообщение в ленту (видно только персоналу)."""
        return self.post_message(None, SupportMessage.ROLE_SYSTEM, text)

    def mark_read_by_client(self):
        self.messages.filter(is_read_by_client=False).update(is_read_by_client=True)
        SupportChat.objects.filter(pk=self.pk).update(client_unread=0)
        self.client_unread = 0

    def mark_read_by_staff(self):
        self.messages.filter(is_read_by_staff=False).update(is_read_by_staff=True)
        SupportChat.objects.filter(pk=self.pk).update(staff_unread=0)
        self.staff_unread = 0

    def __str__(self):
        return f"Чат поддержки: {self.title_for_staff}"


class SupportMessage(models.Model):
    ROLE_CLIENT = 'client'
    ROLE_STAFF = 'staff'
    ROLE_SYSTEM = 'system'
    ROLE_CHOICES = [
        (ROLE_CLIENT, _("Клиент")),
        (ROLE_STAFF, _("Поддержка")),
        (ROLE_SYSTEM, _("Система")),
    ]

    chat = models.ForeignKey(
        SupportChat, on_delete=models.CASCADE, related_name='messages',
        verbose_name=_("Чат"))
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='support_messages', verbose_name=_("Отправитель"))
    author_role = models.CharField(
        max_length=10, choices=ROLE_CHOICES, verbose_name=_("Роль автора"))
    text = models.TextField(verbose_name=_("Текст"))
    created_at = models.DateTimeField(
        auto_now_add=True, db_index=True, verbose_name=_("Отправлено"))
    is_read_by_client = models.BooleanField(
        default=False, verbose_name=_("Прочитано клиентом"))
    is_read_by_staff = models.BooleanField(
        default=False, verbose_name=_("Прочитано поддержкой"))
    # Вложения (фото/файлы) — фаза 2: поле attachment добавится отдельной миграцией.

    class Meta:
        verbose_name = _("Сообщение поддержки")
        verbose_name_plural = _("Сообщения поддержки")
        ordering = ['id']

    def __str__(self):
        return f"[{self.get_author_role_display()}] {self.text[:40]}"
