import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.db.models import Q

from myprofile.models import Notification, EmailLog
from register.models import UserProfile

logger = logging.getLogger(__name__)


def _is_staff(user):
    try:
        return user.userprofile.is_staff
    except UserProfile.DoesNotExist:
        return False


@login_required
def notification_logs_view(request):
    """Сводная страница логов уведомлений: сайт, Telegram, Email."""
    if not _is_staff(request.user):
        return HttpResponseForbidden("У вас нет доступа к этой странице.")

    tab = request.GET.get('tab', 'site')  # site | telegram | email
    search = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '')

    # ── Сайтовые уведомления ──────────────────────────────────────────────
    site_qs = Notification.objects.select_related('user').order_by('-created_at')
    if search:
        site_qs = site_qs.filter(
            Q(user__username__icontains=search) | Q(message__icontains=search)
        )
    if status_filter == 'read':
        site_qs = site_qs.filter(is_read=True)
    elif status_filter == 'unread':
        site_qs = site_qs.filter(is_read=False)

    site_logs = site_qs[:200]
    site_total = Notification.objects.count()
    site_read = Notification.objects.filter(is_read=True).count()
    site_unread = Notification.objects.filter(is_read=False).count()

    # ── Telegram-уведомления ──────────────────────────────────────────────
    tg_logs = []
    tg_total = tg_sent = tg_pending = tg_failed = 0
    try:
        from tgbot.models import TelegramNotification
        tg_qs = TelegramNotification.objects.select_related('user').order_by('-created_at')
        if search:
            tg_qs = tg_qs.filter(
                Q(user__username__icontains=search)
                | Q(title__icontains=search)
                | Q(message__icontains=search)
            )
        if status_filter == 'sent':
            tg_qs = tg_qs.filter(is_sent=True, last_error='')
        elif status_filter == 'failed':
            tg_qs = tg_qs.filter(is_sent=True).exclude(last_error='')
        elif status_filter == 'pending':
            tg_qs = tg_qs.filter(is_sent=False)

        tg_logs = list(tg_qs[:200])
        # добавляем вычисляемое поле tg_status для удобства в шаблоне
        for n in tg_logs:
            if not n.is_sent:
                n.tg_status = 'pending'
            elif n.last_error:
                n.tg_status = 'failed'
            else:
                n.tg_status = 'sent'

        tg_total = TelegramNotification.objects.count()
        tg_sent = TelegramNotification.objects.filter(is_sent=True, last_error='').count()
        tg_failed = TelegramNotification.objects.filter(is_sent=True).exclude(last_error='').count()
        tg_pending = TelegramNotification.objects.filter(is_sent=False).count()
    except Exception as e:
        logger.warning("Could not load TelegramNotification: %s", e)

    # ── Email-логи ────────────────────────────────────────────────────────
    email_qs = EmailLog.objects.order_by('-created_at')
    if search:
        email_qs = email_qs.filter(
            Q(recipient__icontains=search) | Q(subject__icontains=search)
        )
    if status_filter == 'sent':
        email_qs = email_qs.filter(status='sent')
    elif status_filter == 'failed':
        email_qs = email_qs.filter(status='failed')

    email_logs = email_qs[:200]
    email_total = EmailLog.objects.count()
    email_sent = EmailLog.objects.filter(status='sent').count()
    email_failed = EmailLog.objects.filter(status='failed').count()

    return render(request, 'notification_logs.html', {
        'tab': tab,
        'search': search,
        'status_filter': status_filter,
        # site
        'site_logs': site_logs,
        'site_total': site_total,
        'site_read': site_read,
        'site_unread': site_unread,
        # telegram
        'tg_logs': tg_logs,
        'tg_total': tg_total,
        'tg_sent': tg_sent,
        'tg_pending': tg_pending,
        'tg_failed': tg_failed,
        # email
        'email_logs': email_logs,
        'email_total': email_total,
        'email_sent': email_sent,
        'email_failed': email_failed,
    })
