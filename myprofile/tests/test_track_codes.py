"""Тесты архивации и спец-веток добавления трек-кодов (track_codes view)."""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from myprofile.models import SortingLocation, TrackCode
from register.models import PickupPoint, UserProfile

User = get_user_model()


class TrackCodeArchiveTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pp = PickupPoint.objects.create(address='A', premise_name='PP')
        cls.user = User.objects.create_user(username='arc', password='p')
        UserProfile.objects.create(user=cls.user, phone='1', pickup=cls.pp)

    def setUp(self):
        self.client = Client()
        self.client.login(username='arc', password='p')

    def test_archive(self):
        t = TrackCode.objects.create(track_code='ARC1', status='user_added', owner=self.user)
        resp = self.client.post(reverse('archive_track_code', args=[t.id]))
        self.assertEqual(resp.status_code, 302)
        t.refresh_from_db()
        self.assertTrue(t.is_archived)
        self.assertIsNotNone(t.archived_at)

    def test_archive_requires_post(self):
        t = TrackCode.objects.create(track_code='ARC2', status='user_added', owner=self.user)
        resp = self.client.get(reverse('archive_track_code', args=[t.id]))
        self.assertEqual(resp.status_code, 405)

    def test_archive_other_user_404(self):
        other = User.objects.create_user(username='oth', password='p')
        t = TrackCode.objects.create(track_code='ARC3', status='user_added', owner=other)
        resp = self.client.post(reverse('archive_track_code', args=[t.id]))
        self.assertEqual(resp.status_code, 404)

    def test_unarchive(self):
        from django.utils import timezone
        t = TrackCode.objects.create(track_code='UN1', status='user_added', owner=self.user)
        t.is_archived = True
        t.archived_at = timezone.now()
        t._skip_status_validation = True
        t.save(update_fields=['is_archived', 'archived_at'])

        resp = self.client.post(reverse('unarchive_track_code', args=[t.id]))
        self.assertEqual(resp.status_code, 302)
        t.refresh_from_db()
        self.assertFalse(t.is_archived)

    def test_mass_archive(self):
        ids = []
        for i in range(3):
            t = TrackCode.objects.create(track_code=f'M{i}', status='user_added', owner=self.user)
            ids.append(str(t.id))
        resp = self.client.post(reverse('mass_archive_track_codes'), {'track_ids': ids})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            TrackCode.all_objects.filter(owner=self.user, is_archived=True).count(), 3,
        )

    def test_mass_archive_empty_selection(self):
        resp = self.client.post(reverse('mass_archive_track_codes'), {})
        self.assertEqual(resp.status_code, 302)


class TrackCodeAddSpecialBranchesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pp = PickupPoint.objects.create(address='A', premise_name='PP')
        cls.user = User.objects.create_user(username='addr', password='p')
        UserProfile.objects.create(user=cls.user, phone='1', pickup=cls.pp)

    def setUp(self):
        self.client = Client()
        self.client.login(username='addr', password='p')

    def test_claim_unidentified_orphan_keeps_status(self):
        loc = SortingLocation.objects.create(name='Алматы-1')
        TrackCode.objects.create(
            track_code='UNID1', status='unidentified', owner=None, sorting_location=loc,
        )
        resp = self.client.post(reverse('track_codes'), {
            'track_code': 'UNID1', 'description': 'моя посылка',
        })
        self.assertEqual(resp.status_code, 302)
        t = TrackCode.objects.get(track_code='UNID1')
        self.assertEqual(t.owner, self.user)
        self.assertEqual(t.status, 'unidentified')  # статус не меняется

    def test_add_redirects_to_safe_next(self):
        resp = self.client.post(reverse('track_codes'), {
            'track_code': 'NEXT1', 'description': '', 'next': '/profile/mobile-parcels/',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/profile/mobile-parcels/', resp.url)

    def test_add_rejects_unsafe_next(self):
        resp = self.client.post(reverse('track_codes'), {
            'track_code': 'NEXT2', 'description': '', 'next': 'https://evil.com/x',
        })
        self.assertEqual(resp.status_code, 302)
        # небезопасный next отброшен → редирект на дефолтный track_codes
        self.assertEqual(resp.url, reverse('track_codes'))

    def test_new_track_redirects_to_user_added_cat(self):
        resp = self.client.post(reverse('track_codes'), {
            'track_code': 'CAT1', 'description': '',
            'next': '/profile/mobile-parcels/?cat=user_added',
        })
        self.assertEqual(resp.status_code, 302)
        t = TrackCode.objects.get(track_code='CAT1')
        self.assertIn('cat=user_added', resp.url)
        self.assertIn(f'new={t.id}', resp.url)

    def test_claim_shipped_orphan_redirects_to_its_cat(self):
        TrackCode.objects.create(track_code='CAT2', status='shipped_cn', owner=None)
        resp = self.client.post(reverse('track_codes'), {
            'track_code': 'CAT2', 'description': '',
            'next': '/profile/mobile-parcels/?cat=user_added',
        })
        self.assertEqual(resp.status_code, 302)
        t = TrackCode.objects.get(track_code='CAT2')
        self.assertEqual(t.status, 'shipped_cn')
        self.assertIn('cat=shipped_cn', resp.url)
        self.assertNotIn('cat=user_added', resp.url)
        self.assertIn(f'new={t.id}', resp.url)

    def test_claim_unidentified_orphan_redirects_to_in_sorting(self):
        TrackCode.objects.create(track_code='CAT3', status='unidentified', owner=None)
        resp = self.client.post(reverse('track_codes'), {
            'track_code': 'CAT3', 'description': '',
            'next': '/profile/mobile-parcels/?cat=user_added',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertIn('cat=in_sorting', resp.url)

    def test_already_owned_redirects_to_its_cat(self):
        t = TrackCode.objects.create(track_code='CAT4', status='ready', owner=self.user)
        resp = self.client.post(reverse('track_codes'), {
            'track_code': 'CAT4', 'description': '',
            'next': '/profile/mobile-parcels/?cat=user_added',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertIn('cat=ready', resp.url)
        self.assertIn(f'new={t.id}', resp.url)

    def test_invalid_form_with_next_redirects_back_with_error(self):
        # Китайские символы проходят HTML-форму, но режутся валидацией модели
        resp = self.client.post(reverse('track_codes'), {
            'track_code': 'AB123订单编号', 'description': '',
            'next': '/profile/mobile-parcels/?cat=user_added',
        })
        # Раньше рендерилась десктопная страница — теперь редирект обратно
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/profile/mobile-parcels/', resp.url)
        self.assertFalse(TrackCode.all_objects.filter(track_code__startswith='AB123').exists())
        msgs = [m.message for m in list(resp.wsgi_request._messages)]
        self.assertTrue(any('кита' in m or 'кирил' in m for m in msgs), msgs)

    def test_invalid_form_without_next_renders_page(self):
        # Десктопное поведение не меняется: страница с формой и ошибками
        resp = self.client.post(reverse('track_codes'), {
            'track_code': 'AB456订单', 'description': '',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context['form'].errors)

    def test_next_without_cat_only_gets_new_param(self):
        resp = self.client.post(reverse('track_codes'), {
            'track_code': 'CAT5', 'description': '',
            'next': '/profile/mobile-parcels/',
        })
        self.assertEqual(resp.status_code, 302)
        t = TrackCode.objects.get(track_code='CAT5')
        self.assertNotIn('cat=', resp.url)
        self.assertIn(f'new={t.id}', resp.url)
