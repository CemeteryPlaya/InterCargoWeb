"""Тесты сброса пароля и подтверждения email (register.views).

AJAX-флоу с кодами: отправка, rate-limit, проверка, попытки, срок действия.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from register.models import EmailVerificationCode, PasswordResetCode

User = get_user_model()


class PasswordResetRequestTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username='RESETME', password='old', email='r@example.com',
        )
        cls.no_email = User.objects.create_user(username='NOEMAIL', password='old')

    def setUp(self):
        self.client = Client()

    def test_get_page(self):
        resp = self.client.get(reverse('password_reset'))
        self.assertEqual(resp.status_code, 200)

    def test_missing_identifier(self):
        resp = self.client.post(reverse('password_reset'), {'identifier': ''})
        self.assertEqual(resp.status_code, 400)

    def test_unknown_user(self):
        resp = self.client.post(reverse('password_reset'), {'identifier': 'GHOST'})
        self.assertEqual(resp.status_code, 404)

    def test_user_without_email(self):
        resp = self.client.post(reverse('password_reset'), {'identifier': 'NOEMAIL'})
        self.assertEqual(resp.status_code, 400)

    def test_success_creates_code_and_session(self):
        resp = self.client.post(reverse('password_reset'), {'identifier': 'RESETME'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])
        self.assertTrue(PasswordResetCode.objects.filter(user=self.user).exists())
        self.assertEqual(self.client.session['reset_user_id'], self.user.id)

    def test_rate_limited(self):
        PasswordResetCode.objects.create(user=self.user, code='111-111')
        resp = self.client.post(reverse('password_reset'), {'identifier': 'RESETME'})
        self.assertEqual(resp.status_code, 429)

    def test_case_insensitive_lookup(self):
        resp = self.client.post(reverse('password_reset'), {'identifier': 'resetme'})
        self.assertEqual(resp.status_code, 200)


class PasswordResetVerifyTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='V', password='old', email='v@e.com')
        self.code = PasswordResetCode.objects.create(user=self.user, code='123-456')
        s = self.client.session
        s['reset_user_id'] = self.user.id
        s.save()

    def test_no_session_rejected(self):
        c = Client()
        resp = c.post(reverse('password_reset_verify'), {'code': '123-456'})
        self.assertEqual(resp.status_code, 400)

    def test_wrong_code_increments_attempts(self):
        resp = self.client.post(reverse('password_reset_verify'), {'code': '000-000'})
        self.assertEqual(resp.status_code, 400)
        self.code.refresh_from_db()
        self.assertEqual(self.code.attempts, 1)

    def test_correct_code_marks_used(self):
        resp = self.client.post(reverse('password_reset_verify'), {'code': '123-456'})
        self.assertEqual(resp.status_code, 200)
        self.code.refresh_from_db()
        self.assertTrue(self.code.is_used)
        self.assertTrue(self.client.session['reset_verified'])

    def test_expired_code(self):
        PasswordResetCode.objects.filter(pk=self.code.pk).update(
            created_at=timezone.now() - timedelta(minutes=11),
        )
        resp = self.client.post(reverse('password_reset_verify'), {'code': '123-456'})
        self.assertEqual(resp.status_code, 400)

    def test_too_many_attempts(self):
        PasswordResetCode.objects.filter(pk=self.code.pk).update(attempts=5)
        resp = self.client.post(reverse('password_reset_verify'), {'code': '123-456'})
        self.assertEqual(resp.status_code, 429)


class PasswordResetSetPasswordTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='SP', password='old', email='s@e.com')
        s = self.client.session
        s['reset_user_id'] = self.user.id
        s['reset_verified'] = True
        s.save()

    def test_not_verified_rejected(self):
        c = Client()
        resp = c.post(reverse('password_reset_set_password'),
                      {'password': 'newpass', 'password_confirm': 'newpass'})
        self.assertEqual(resp.status_code, 400)

    def test_short_password(self):
        resp = self.client.post(reverse('password_reset_set_password'),
                                {'password': '123', 'password_confirm': '123'})
        self.assertEqual(resp.status_code, 400)

    def test_mismatch(self):
        resp = self.client.post(reverse('password_reset_set_password'),
                                {'password': 'newpass', 'password_confirm': 'other1'})
        self.assertEqual(resp.status_code, 400)

    def test_success_changes_password(self):
        resp = self.client.post(reverse('password_reset_set_password'),
                                {'password': 'brandnew', 'password_confirm': 'brandnew'})
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('brandnew'))
        self.assertNotIn('reset_user_id', self.client.session)


class EmailVerifyTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_send_missing_email(self):
        resp = self.client.post(reverse('email_verify_send'), {'email': ''})
        self.assertEqual(resp.status_code, 400)

    def test_send_success(self):
        resp = self.client.post(reverse('email_verify_send'), {'email': 'New@Mail.com'})
        self.assertEqual(resp.status_code, 200)
        # email нормализуется в нижний регистр
        self.assertTrue(EmailVerificationCode.objects.filter(email='new@mail.com').exists())
        self.assertEqual(self.client.session['verification_email'], 'new@mail.com')

    def test_send_rate_limited(self):
        EmailVerificationCode.objects.create(email='x@mail.com', code='111-111')
        resp = self.client.post(reverse('email_verify_send'), {'email': 'x@mail.com'})
        self.assertEqual(resp.status_code, 429)

    def test_verify_missing_fields(self):
        resp = self.client.post(reverse('email_verify_check'), {'email': 'a@b.com'})
        self.assertEqual(resp.status_code, 400)

    def test_verify_wrong_code(self):
        EmailVerificationCode.objects.create(email='w@mail.com', code='123-456')
        resp = self.client.post(reverse('email_verify_check'),
                                {'email': 'w@mail.com', 'code': '000-000'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            EmailVerificationCode.objects.get(email='w@mail.com').attempts, 1,
        )

    def test_verify_success(self):
        EmailVerificationCode.objects.create(email='ok@mail.com', code='123-456')
        resp = self.client.post(reverse('email_verify_check'),
                                {'email': 'ok@mail.com', 'code': '123-456'})
        self.assertEqual(resp.status_code, 200)
        v = EmailVerificationCode.objects.get(email='ok@mail.com')
        self.assertTrue(v.is_verified)
        self.assertEqual(self.client.session['email_verified'], 'ok@mail.com')

    def test_verify_expired(self):
        v = EmailVerificationCode.objects.create(email='exp@mail.com', code='123-456')
        EmailVerificationCode.objects.filter(pk=v.pk).update(
            created_at=timezone.now() - timedelta(minutes=11),
        )
        resp = self.client.post(reverse('email_verify_check'),
                                {'email': 'exp@mail.com', 'code': '123-456'})
        self.assertEqual(resp.status_code, 400)
