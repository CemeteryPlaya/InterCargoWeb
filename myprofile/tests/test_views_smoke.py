"""Смоук- и permission-тесты операционных страниц.

Главные view защищены только @login_required, ролевые проверки — внутри.
Здесь мы:
  1. логинимся суперюзером с полным набором ролей и проверяем, что страницы
     отдают 200 (прогоняет крупные view-модули: warehouse/delivery/finance/...);
  2. проверяем, что обычный клиент получает 403/редирект на staff-страницах.
"""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from myprofile.models import GlobalSettings
from register.models import PickupPoint, UserProfile

User = get_user_model()

# Страницы, доступные любому залогиненному клиенту.
CLIENT_PAGES = [
    'profile', 'settings', 'track_codes', 'delivered_posts',
    'notifications', 'mobile_qr', 'mobile_parcels', 'mobile_notifications',
    'mobile_menu',
]

# Staff-страницы (GET без аргументов), которые суперюзер должен открыть.
STAFF_PAGES = [
    'extradition', 'extradition_package', 'print_documents', 'goods_arrival',
    'delivery', 'shipped_cn', 'warehouse', 'warehouse_inventory',
    'arrival_history', 'arrival_summary', 'pp_acceptance', 'attention_required',
    'pp_extradition_history', 'notification_logs', 'notification_mutes',
    'finance_summary', 'reschedule_arrival', 'unidentified', 'service',
    'blocks_management', 'role_management',
]


class SuperuserPageSmokeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pp = PickupPoint.objects.create(address='A', premise_name='PP')
        cls.user = User.objects.create_superuser(
            username='boss', password='p', email='b@e.com',
        )
        UserProfile.objects.create(
            user=cls.user, phone='1', pickup=cls.pp,
            is_staff=True, is_hr=True, is_driver=True, is_pp_worker=True,
            is_pp_owner=True, is_accountant=True, is_tg_admin=True,
        )
        GlobalSettings.objects.create()

    def setUp(self):
        self.client = Client()
        self.client.login(username='boss', password='p')

    def test_client_pages_ok(self):
        for name in CLIENT_PAGES:
            with self.subTest(page=name):
                resp = self.client.get(reverse(name))
                self.assertEqual(resp.status_code, 200, f'{name} → {resp.status_code}')

    def test_staff_pages_ok(self):
        for name in STAFF_PAGES:
            with self.subTest(page=name):
                resp = self.client.get(reverse(name))
                self.assertIn(
                    resp.status_code, (200, 302),
                    f'{name} → {resp.status_code}',
                )


class ClientForbiddenOnStaffPagesTests(TestCase):
    """Обычный клиент не должен иметь доступ к операционным страницам."""

    @classmethod
    def setUpTestData(cls):
        cls.pp = PickupPoint.objects.create(address='A', premise_name='PP')
        cls.user = User.objects.create_user(username='client', password='p')
        UserProfile.objects.create(user=cls.user, phone='1', pickup=cls.pp)

    def setUp(self):
        self.client = Client()
        self.client.login(username='client', password='p')

    def test_staff_pages_blocked_for_client(self):
        # Берём подмножество явно ролевых страниц.
        protected = ['warehouse', 'finance_summary', 'delivery', 'service',
                     'role_management', 'notification_mutes']
        for name in protected:
            with self.subTest(page=name):
                resp = self.client.get(reverse(name))
                self.assertIn(
                    resp.status_code, (403, 302),
                    f'{name} доступна клиенту → {resp.status_code}',
                )

    def test_unauthenticated_redirected(self):
        self.client.logout()
        resp = self.client.get(reverse('warehouse'))
        self.assertEqual(resp.status_code, 302)


class ReceiptListRedirectTests(TestCase):
    """receipt_list ('/profile/receipts/') раньше рендерил несуществующий
    шаблон 'receipts.html' и падал с 500. Теперь редиректит на рабочую
    страницу списка чеков (delivered_posts)."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='rl', password='p')
        UserProfile.objects.create(user=cls.user, phone='1')

    def setUp(self):
        self.client = Client()
        self.client.login(username='rl', password='p')

    def test_receipt_list_redirects_to_delivered_posts(self):
        resp = self.client.get(reverse('receipt_list'))
        self.assertRedirects(resp, reverse('delivered_posts'))

    def test_generate_daily_receipt_no_tracks_redirects(self):
        # Нет доставленных треков → редирект на delivered_posts с info-сообщением
        resp = self.client.get(reverse('generate_receipt'))
        self.assertRedirects(resp, reverse('delivered_posts'))
