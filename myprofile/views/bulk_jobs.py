"""Страница и JSON-статус фоновых массовых операций (BulkJob)."""
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils.translation import gettext as _

from myprofile.models import BulkJob
from myprofile.views.utils import is_staff as _is_staff


@login_required
def bulk_job_page(request, job_id):
    if not _is_staff(request.user):
        return HttpResponseForbidden(_("У вас нет доступа к этой странице."))
    job = get_object_or_404(BulkJob, id=job_id)
    return render(request, 'desktop/bulk_job.html', {'job': job})


@login_required
def bulk_job_status(request, job_id):
    if not _is_staff(request.user):
        return HttpResponseForbidden(_("У вас нет доступа."))
    job = get_object_or_404(BulkJob, id=job_id)
    return JsonResponse({
        'status': job.status,
        'total': job.total,
        'processed': job.processed,
        'result': job.result,
        'error': job.error_text,
    })
