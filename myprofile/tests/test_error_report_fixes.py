"""Ошибки из писем [Django] (разбор 2026-10-05): воспроизведение и защита.

Каждый тест — сценарий, который давал 500 и письмо администратору.

Запуск: python manage.py test myprofile.tests.test_error_report_fixes --settings=cargo.settings_test
"""
import json
import logging
import smtplib
import sys
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.db import IntegrityError
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from myprofile.models import (
    ArrivalSession, ArrivalSessionItem, EmailLog, Extradition, ExtraditionPackage,
    Receipt, ReceiptItem, TrackCode,
)
from register.models import PendingRegistration, PickupPoint, UserProfile


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pp = PickupPoint.objects.create(address='A', premise_name='PP')
        cls.staff = User.objects.create_user(username='STAFF', password='p')
        UserProfile.objects.create(user=cls.staff, phone='1', pickup=cls.pp, is_staff=True, is_hr=True)
        cls.cli = User.objects.create_user(username='CLI', password='p')
        UserProfile.objects.create(user=cls.cli, phone='2', pickup=cls.pp)

    def _messages(self, resp):
        return [str(m) for m in get_messages(resp.wsgi_request)]


class RegistrationApprovalTests(Base):
    """DoesNotExist (×2) и дубль username (×4) на /register/confirm/approve/<id>/."""

    def setUp(self):
        self.c = Client(); self.c.login(username='STAFF', password='p')

    def _reg(self, login='NEWCLI'):
        return PendingRegistration.objects.create(login=login, phone='777', password='secret123',
                                                  pickup=self.pp)

    def test_repeated_approve_does_not_500(self):
        reg = self._reg()
        self.c.get(reverse('approve_registration', args=[reg.id]))
        resp = self.c.get(reverse('approve_registration', args=[reg.id]))   # повторный клик
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(any('обработана' in m for m in self._messages(resp)))
        self.assertEqual(User.objects.filter(username='NEWCLI').count(), 1)

    def test_approve_when_active_user_with_same_login_exists(self):
        reg = self._reg(login='CLI')                                      # логин уже занят активным
        resp = self.c.get(reverse('approve_registration', args=[reg.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(PendingRegistration.objects.filter(id=reg.id).exists())   # заявка не потеряна
        self.assertTrue(any('уже существует' in m for m in self._messages(resp)))

    def test_reject_missing_registration_does_not_500(self):
        resp = self.c.post(reverse('reject_registration', args=[999999]))
        self.assertEqual(resp.status_code, 302)


class NotificationsContextTests(TestCase):
    """AttributeError: у 'WSGIRequest' нет атрибута 'user' (×5)."""

    def test_request_without_user_is_safe(self):
        from myprofile.views.notifications import notifications_context
        request = RequestFactory().get('/')      # запрос, оборвавшийся до AuthenticationMiddleware
        context = notifications_context(request)
        self.assertIsInstance(context, dict)


class UnidentifiedValidationTests(Base):
    """ValidationError: кириллица/иероглифы в трек-коде (×3) — сообщение вместо 500."""

    def test_cyrillic_track_code_shows_message(self):
        c = Client(); c.login(username='STAFF', password='p')
        resp = c.post(reverse('unidentified'), {'track_code': 'ТРЕК123'})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(TrackCode.all_objects.filter(track_code='ТРЕК123').exists())
        self.assertTrue(self._messages(resp))


class GoodsArrivalSaveTests(Base):
    """IntegrityError по уникальности трек-кода (×4) и numeric overflow (×3)."""

    def setUp(self):
        self.c = Client(); self.c.login(username='STAFF', password='p')
        self.session = ArrivalSession.objects.create(date=timezone.localdate(), created_by=self.staff)

    def _save(self, items):
        return self.c.post(reverse('goods_arrival_save', args=[self.session.id]),
                           data=json.dumps({'items': items}), content_type='application/json')

    def test_weight_rounding_to_1000_is_rejected_not_overflow(self):
        resp = self._save([{'track_code': 'W1', 'weight': '999.9996'}])
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(ArrivalSessionItem.objects.get(track_code='W1').weight)

    def test_weight_is_rounded_to_grams(self):
        self._save([{'track_code': 'W2', 'weight': '1.23456'}])
        self.assertEqual(ArrivalSessionItem.objects.get(track_code='W2').weight, Decimal('1.235'))

    def test_concurrent_save_conflict_returns_409(self):
        with mock.patch.object(ArrivalSessionItem.objects, 'bulk_create',
                               side_effect=IntegrityError('duplicate key')):
            resp = self._save([{'track_code': 'R1'}])
        self.assertEqual(resp.status_code, 409)
        self.assertTrue(resp.json().get('retry'))


class TrackCodeDoubleSubmitTests(Base):
    """IntegrityError myprofile_trackcode_track_code_key (×3) — двойная отправка формы."""

    def test_race_on_create_shows_already_added(self):
        from myprofile.views.track_codes import TrackCodeForm
        TrackCode.objects.create(track_code='RACE1', status='user_added', owner=self.cli)
        c = Client(); c.login(username='CLI', password='p')
        # Имитируем гонку: проверка «есть ли трек» и валидация формы прошли до вставки соседа
        with mock.patch.object(TrackCode.all_objects, "get", side_effect=TrackCode.DoesNotExist), \
                mock.patch.object(TrackCodeForm, 'validate_unique', lambda self: None):
            resp = c.post(reverse('track_codes'), {'track_code': 'RACE1'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(TrackCode.all_objects.filter(track_code='RACE1').count(), 1)
        self.assertTrue(any('уже' in m for m in self._messages(resp)))

    def test_race_between_full_clean_and_insert(self):
        from myprofile.views.track_codes import TrackCodeForm
        TrackCode.objects.create(track_code='RACE2', status='user_added', owner=self.cli)
        c = Client(); c.login(username='CLI', password='p')
        # Сосед вставил трек уже после full_clean() — до БД доходит IntegrityError
        with mock.patch.object(TrackCode.all_objects, "get", side_effect=TrackCode.DoesNotExist), \
                mock.patch.object(TrackCodeForm, 'validate_unique', lambda self: None), \
                mock.patch.object(TrackCode, 'validate_unique', lambda self, exclude=None: None):
            resp = c.post(reverse('track_codes'), {'track_code': 'RACE2'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(TrackCode.all_objects.filter(track_code='RACE2').count(), 1)
        self.assertTrue(any('уже' in m for m in self._messages(resp)))


class ExtraditionDuplicateTests(Base):
    """IntegrityError myprofile_extradition_package_id_key (×2)."""

    def test_package_with_existing_extradition_is_not_issued_twice(self):
        pkg = ExtraditionPackage.objects.create(user=self.cli)
        receipt = Receipt.objects.create(owner=self.cli, status='accepted_pvz',
                                         total_weight=Decimal('1'), total_price=Decimal('100'))
        track = TrackCode.objects.create(track_code='EXD1', status='ready', owner=self.cli, weight=Decimal('1'))
        ReceiptItem.objects.create(receipt=receipt, track_code=track, weight=Decimal('1'))
        pkg.receipts.add(receipt)
        Extradition.objects.create(package=pkg, user=self.cli, issued_by=self.staff, pickup_point='PP')
        c = Client(); c.login(username='STAFF', password='p')
        resp = c.post(reverse('extradition'), {'barcode': pkg.barcode})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Extradition.objects.filter(package=pkg).count(), 1)
        self.assertTrue(any('уже' in m for m in self._messages(resp)))


class ResendEmailRedirectTests(Base):
    """NoReverseMatch 'email_logs' (×1) после переотправки письма."""

    def test_resend_redirects_to_notification_logs(self):
        log = EmailLog.objects.create(recipient='a@b.c', subject='S', body='B', status='failed')
        c = Client(); c.login(username='STAFF', password='p')
        with mock.patch('myprofile.views.email_logs.send_mail_logged'):
            resp = c.post(reverse('resend_email', args=[log.id]))
        self.assertRedirects(resp, reverse('notification_logs'), fetch_redirect_response=False)


class SendEmailCodeTests(TestCase):
    """«Traceback None» ×65: send_email_code сам отдавал 500 при сбое SMTP."""

    def _post(self, exc):
        with mock.patch('register.views.email_verify.send_mail_logged', side_effect=exc):
            return Client().post(reverse('email_verify_send'), {'email': 'user@example.com'})

    def test_rejected_recipient_is_user_error_400(self):
        resp = self._post(smtplib.SMTPRecipientsRefused({'user@example.com': (550, b'no such user')}))
        self.assertEqual(resp.status_code, 400)
        self.assertIn('email', resp.json()['error'].lower())

    def test_smtp_outage_is_503(self):
        resp = self._post(smtplib.SMTPServerDisconnected('down'))
        self.assertEqual(resp.status_code, 503)


class SendMailLoggedTests(TestCase):
    def test_refused_recipient_not_retried_and_keeps_type(self):
        from myprofile.email_utils import send_mail_logged
        refused = smtplib.SMTPRecipientsRefused({'x@y.z': (550, b'no')})
        with mock.patch('myprofile.email_utils.EmailMessage.send', side_effect=refused) as send, \
                mock.patch('myprofile.email_utils.time.sleep'):
            with self.assertRaises(smtplib.SMTPRecipientsRefused):
                send_mail_logged('S', 'B', ['x@y.z'])
        self.assertEqual(send.call_count, 1)
        self.assertTrue(EmailLog.objects.filter(recipient='x@y.z', status='failed').exists())


class ErrorEmailFilterTests(TestCase):
    """Письма администратору — только по необработанным исключениям на проде."""

    def _record(self, name, msg='x', exc=False, status=None):
        exc_info = None
        if exc:
            try:
                raise ValueError('boom')
            except ValueError:
                exc_info = sys.exc_info()
        record = logging.LogRecord(name, logging.ERROR, __file__, 1, msg, (), exc_info)
        if status is not None:
            record.status_code = status
        return record

    def test_unhandled_exception_is_emailed(self):
        from cargo.logging_filters import EmailWorthy
        self.assertTrue(EmailWorthy().filter(self._record('django.request', exc=True, status=500)))

    def test_deliberate_5xx_without_traceback_is_not_emailed(self):
        from cargo.logging_filters import EmailWorthy
        self.assertFalse(EmailWorthy().filter(self._record('django.request', status=503)))

    def test_security_and_dev_server_noise_is_not_emailed(self):
        from cargo.logging_filters import EmailWorthy
        for name in ('django.security.DisallowedHost', 'django.security.SuspiciousFileOperation',
                     'django.server'):
            self.assertFalse(EmailWorthy().filter(self._record(name, exc=True)), name)

    def test_logging_config_writes_to_file_and_filters_mail(self):
        from django.conf import settings
        handlers = settings.LOGGING['handlers']
        self.assertEqual(handlers['file']['class'], 'logging.handlers.RotatingFileHandler')
        self.assertIn('email_worthy', handlers['mail_admins']['filters'])
        self.assertIn('require_debug_false', handlers['mail_admins']['filters'])
        self.assertIn('file', settings.LOGGING['loggers']['django.request']['handlers'])
        self.assertIn('file', settings.LOGGING['root']['handlers'])
