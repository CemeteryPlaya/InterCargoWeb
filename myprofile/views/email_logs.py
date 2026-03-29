import logging
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, get_object_or_404
from django.http import HttpResponseForbidden
from django.views.decorators.http import require_POST
from django.contrib import messages
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
