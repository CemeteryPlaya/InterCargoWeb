import logging
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponseForbidden
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.db.models import Q
from myprofile.models import EmailLog
from myprofile.email_utils import send_mail_logged
from register.models import UserProfile

logger = logging.getLogger(__name__)


def _is_staff(user):
    try:
        return user.userprofile.is_staff
    except UserProfile.DoesNotExist:
        return False


@login_required
def email_logs_view(request):
    """Страница логов email-рассылок для операторов."""
    if not _is_staff(request.user):
        return HttpResponseForbidden("У вас нет доступа к этой странице.")

    status_filter = request.GET.get('status', '')
    search = request.GET.get('q', '').strip()

    qs = EmailLog.objects.all()

    if status_filter in ('sent', 'failed'):
        qs = qs.filter(status=status_filter)

    if search:
        qs = qs.filter(
            Q(recipient__icontains=search) | Q(subject__icontains=search)
        )

    logs = qs[:200]

    # Статистика
    total = EmailLog.objects.count()
    sent = EmailLog.objects.filter(status='sent').count()
    failed = EmailLog.objects.filter(status='failed').count()

    return render(request, 'email_logs.html', {
        'logs': logs,
        'status_filter': status_filter,
        'search': search,
        'total': total,
        'sent': sent,
        'failed': failed,
    })


@login_required
@require_POST
def resend_email(request, log_id):
    """Переотправка неудачного email."""
    if not _is_staff(request.user):
        return HttpResponseForbidden("У вас нет доступа.")

    log_entry = get_object_or_404(EmailLog, id=log_id, status='failed')

    try:
        send_mail_logged(
            log_entry.subject,
            log_entry.body,
            [log_entry.recipient],
            fail_silently=False,
        )
        messages.success(request, f"Письмо переотправлено на {log_entry.recipient}")
    except Exception as e:
        messages.error(request, f"Ошибка переотправки: {e}")

    return redirect('email_logs')
