"""Тесты мобильных клиентских страниц: посылки (архив AJAX) и QR-страница."""
import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from myprofile.models import ExtraditionPackage, Receipt, TrackCode
from register.models import PickupPoint, UserProfile

User = get_user_model()


class MobileParcelsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='mp', password='p')
        UserProfile.objects.create(user=cls.user, phone='1')

    def setUp(self):
        self.client = Client()
        self.client.login(username='mp', password='p')

    def test_view_groups_by_status(self):
        TrackCode.objects.create(track_code='A', status='user_added', owner=self.user)
        TrackCode.objects.create(track_code='B', status='ready', owner=self.user)
        resp = self.client.get(reverse('mobile_parcels'))
        self.assertEqual(resp.status_code, 200)
        cats = {c['key']: c['count'] for c in resp.context['categories']}
        self.assertEqual(cats['user_added'], 1)
        self.assertEqual(cats['ready'], 1)

    def test_archive_ajax(self):
        t = TrackCode.objects.create(track_code='AR', status='user_added', owner=self.user)
        resp = self.client.post(reverse('mobile_archive_track'), {'track_id': t.id})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])
        t.refresh_from_db()
        self.assertTrue(t.is_archived)

    def test_archive_already_archived(self):
        from django.utils import timezone
        t = TrackCode.objects.create(track_code='AR2', status='user_added', owner=self.user)
        t.is_archived = True
        t.archived_at = timezone.now()
        t._skip_status_validation = True
        t.save(update_fields=['is_archived', 'archived_at'])
        resp = self.client.post(reverse('mobile_archive_track'), {'track_id': t.id})
        self.assertTrue(resp.json().get('already_archived'))

    def test_unarchive_ajax(self):
        from django.utils import timezone
        t = TrackCode.objects.create(track_code='UN', status='ready', owner=self.user)
        t.is_archived = True
        t.archived_at = timezone.now()
        t._skip_status_validation = True
        t.save(update_fields=['is_archived', 'archived_at'])
        resp = self.client.post(reverse('mobile_unarchive_track'), {'track_id': t.id})
        self.assertTrue(resp.json()['success'])
        t.refresh_from_db()
        self.assertFalse(t.is_archived)

    def test_mass_archive_json(self):
        ids = [
            TrackCode.objects.create(track_code=f'MX{i}', status='user_added', owner=self.user).id
            for i in range(2)
        ]
        resp = self.client.post(
            reverse('mobile_mass_archive'),
            data=json.dumps({'track_ids': ids}),
            content_type='application/json',
        )
        self.assertEqual(resp.json()['count'], 2)

    def test_mass_archive_empty(self):
        resp = self.client.post(
            reverse('mobile_mass_archive'),
            data=json.dumps({'track_ids': []}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_edit_description_ajax(self):
        t = TrackCode.objects.create(
            track_code='ED1', status='user_added', owner=self.user, description='старое',
        )
        resp = self.client.post(reverse('mobile_edit_description'), {
            'track_id': t.id, 'description': 'новое описание',
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['description'], 'новое описание')
        t.refresh_from_db()
        self.assertEqual(t.description, 'новое описание')

    def test_edit_description_can_clear(self):
        t = TrackCode.objects.create(
            track_code='ED2', status='ready', owner=self.user, description='было',
        )
        resp = self.client.post(reverse('mobile_edit_description'), {
            'track_id': t.id, 'description': '',
        })
        self.assertTrue(resp.json()['success'])
        t.refresh_from_db()
        self.assertEqual(t.description, '')

    def test_edit_description_truncates_to_255(self):
        t = TrackCode.objects.create(track_code='ED3', status='user_added', owner=self.user)
        resp = self.client.post(reverse('mobile_edit_description'), {
            'track_id': t.id, 'description': 'x' * 300,
        })
        self.assertTrue(resp.json()['success'])
        t.refresh_from_db()
        self.assertEqual(len(t.description), 255)

    def test_edit_description_other_user_404(self):
        other = User.objects.create_user(username='oth2', password='p')
        t = TrackCode.objects.create(track_code='ED4', status='user_added', owner=other)
        resp = self.client.post(reverse('mobile_edit_description'), {
            'track_id': t.id, 'description': 'чужое',
        })
        self.assertEqual(resp.status_code, 404)

    def test_edit_description_requires_post(self):
        resp = self.client.get(reverse('mobile_edit_description'))
        self.assertEqual(resp.status_code, 405)

    def test_messages_rendered_as_toast(self):
        """Сообщения Django после редиректа добавления попадают на мобильную страницу."""
        other = User.objects.create_user(username='owner-x', password='p')
        TrackCode.objects.create(track_code='TAKEN1', status='user_added', owner=other)
        resp = self.client.post(
            reverse('track_codes'),
            {'track_code': 'TAKEN1', 'description': '', 'next': '/profile/mobile-parcels/'},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn('serverMessages', content)
        self.assertIn('зарегистрирован другим пользователем', content)


class MobileQrTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pp = PickupPoint.objects.create(address='A', premise_name='PP')
        cls.user = User.objects.create_user(username='mq', password='p')
        UserProfile.objects.create(user=cls.user, phone='1', pickup=cls.pp)

    def setUp(self):
        self.client = Client()
        self.client.login(username='mq', password='p')

    def test_view_without_package(self):
        resp = self.client.get(reverse('mobile_qr'))
        self.assertEqual(resp.status_code, 200)

    def test_view_with_active_package(self):
        pkg = ExtraditionPackage.objects.create(user=self.user, is_issued=False)
        receipt = Receipt.objects.create(
            owner=self.user, total_weight=1, total_price=1000, price_per_kg=1000,
        )
        pkg.receipts.add(receipt)
        resp = self.client.get(reverse('mobile_qr'))
        self.assertEqual(resp.status_code, 200)
