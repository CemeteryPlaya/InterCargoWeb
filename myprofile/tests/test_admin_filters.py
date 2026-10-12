"""
Фильтры админки: доставщики только по роли/флагу, диапазоны дат и периоды,
рендер списков всех зарегистрированных моделей с новыми фильтрами.
"""
import datetime
from decimal import Decimal

from django.contrib import admin as django_admin
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from myprofile.models import DeliveryHistory
from register.models import PickupPoint, UserProfile

User = get_user_model()


def _aware(year, month, day, hour=12, minute=0):
    return datetime.datetime(year, month, day, hour, minute, tzinfo=timezone.get_current_timezone())


class AdminFiltersBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create_superuser(username='root', password='password')
        cls.pp = PickupPoint.objects.create(address='Абая 1', premise_name='ПВЗ-1')

        cls.role_driver = User.objects.create_user(username='role_driver', first_name='Ерлан', last_name='Доставщиков')
        UserProfile.objects.create(user=cls.role_driver, role=UserProfile.ROLE_DRIVER, is_driver=True)
        cls.flag_driver = User.objects.create_user(username='flag_driver')
        UserProfile.objects.create(user=cls.flag_driver, is_driver=True)
        cls.client_user = User.objects.create_user(username='just_client')
        UserProfile.objects.create(user=cls.client_user)
        cls.sorter = User.objects.create_user(username='sorter')
        UserProfile.objects.create(user=cls.sorter, role=UserProfile.ROLE_SORTING_PVZ)
        cls.no_profile = User.objects.create_user(username='no_profile')

    def setUp(self):
        self.client.force_login(self.superuser)

    def _history(self, driver, taken_at, delivered_at=None):
        return DeliveryHistory.objects.create(
            driver=driver, pickup_point=self.pp, total_weight=Decimal('1.5'),
            taken_at=taken_at, delivered_at=delivered_at,
        )


class DeliveryHistoryDriverFilterTest(AdminFiltersBase):
    url = reverse('admin:myprofile_deliveryhistory_changelist')

    def _driver_filter_choices(self, response):
        spec = next(s for s in response.context['cl'].filter_specs if s.field_path == 'driver')
        return {pk for pk, _label in spec.lookup_choices}

    def test_sidebar_lists_only_drivers(self):
        # Даже доставка, оформленная не-водителем (Сорт.ПВЗ), не добавляет его в список.
        self._history(self.sorter, timezone.now())
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._driver_filter_choices(response), {self.role_driver.pk, self.flag_driver.pk})

    def test_driver_label_has_full_name(self):
        response = self.client.get(self.url)
        spec = next(s for s in response.context['cl'].filter_specs if s.field_path == 'driver')
        self.assertIn((self.role_driver.pk, 'Ерлан Доставщиков (role_driver)'), list(spec.lookup_choices))

    def test_filter_by_driver(self):
        mine = self._history(self.role_driver, timezone.now())
        self._history(self.flag_driver, timezone.now())
        response = self.client.get(self.url, {'driver__id__exact': self.role_driver.pk})
        self.assertEqual([obj.pk for obj in response.context['cl'].result_list], [mine.pk])

    def test_add_form_offers_only_drivers(self):
        response = self.client.get(reverse('admin:myprofile_deliveryhistory_add'))
        queryset = response.context['adminform'].form.fields['driver'].queryset
        self.assertEqual(set(queryset), {self.role_driver, self.flag_driver})

    def test_change_form_keeps_current_driver_without_role(self):
        history = self._history(self.sorter, timezone.now())
        response = self.client.get(reverse('admin:myprofile_deliveryhistory_change', args=[history.pk]))
        queryset = response.context['adminform'].form.fields['driver'].queryset
        self.assertEqual(set(queryset), {self.role_driver, self.flag_driver, self.sorter})

    def test_track_count_column_is_sortable(self):
        response = self.client.get(self.url, {'o': '5'})
        self.assertEqual(response.status_code, 200)


class DateRangeFilterTest(AdminFiltersBase):
    url = reverse('admin:myprofile_deliveryhistory_changelist')

    def _result_pks(self, params):
        response = self.client.get(self.url, params)
        self.assertEqual(response.status_code, 200)
        return {obj.pk for obj in response.context['cl'].result_list}

    def test_range_is_inclusive_in_local_time(self):
        before = self._history(self.role_driver, _aware(2026, 9, 30, 23, 59))
        first = self._history(self.role_driver, _aware(2026, 10, 1, 0, 0))
        last = self._history(self.role_driver, _aware(2026, 10, 5, 23, 59))
        after = self._history(self.role_driver, _aware(2026, 10, 6, 0, 0))
        pks = self._result_pks({'taken_at__from': '2026-10-01', 'taken_at__to': '2026-10-05'})
        self.assertEqual(pks, {first.pk, last.pk})
        self.assertNotIn(before.pk, pks)
        self.assertNotIn(after.pk, pks)

    def test_open_ended_and_swapped_bounds(self):
        old = self._history(self.role_driver, _aware(2026, 1, 10))
        new = self._history(self.role_driver, _aware(2026, 10, 10))
        self.assertEqual(self._result_pks({'taken_at__from': '2026-06-01'}), {new.pk})
        self.assertEqual(self._result_pks({'taken_at__to': '2026-06-01'}), {old.pk})
        self.assertEqual(
            self._result_pks({'taken_at__from': '2026-12-31', 'taken_at__to': '2026-01-01'}),
            {old.pk, new.pk},
        )

    def test_invalid_date_is_ignored(self):
        entry = self._history(self.role_driver, _aware(2026, 10, 10))
        self.assertEqual(self._result_pks({'taken_at__from': 'не-дата'}), {entry.pk})

    def test_isnull_for_nullable_field(self):
        in_transit = self._history(self.role_driver, _aware(2026, 10, 10))
        delivered = self._history(self.role_driver, _aware(2026, 10, 10), delivered_at=_aware(2026, 10, 10, 15))
        self.assertEqual(self._result_pks({'delivered_at__isnull': 'True'}), {in_transit.pk})
        self.assertEqual(self._result_pks({'delivered_at__isnull': 'False'}), {delivered.pk})

    def test_today_preset_and_form_keeps_other_params(self):
        today = self._history(self.role_driver, timezone.now())
        self._history(self.role_driver, timezone.now() - datetime.timedelta(days=3))
        iso = timezone.localdate().isoformat()
        response = self.client.get(self.url, {
            'taken_at__from': iso, 'taken_at__to': iso, 'driver__id__exact': self.role_driver.pk,
        })
        self.assertEqual({obj.pk for obj in response.context['cl'].result_list}, {today.pk})
        spec = next(s for s in response.context['cl'].filter_specs if s.field_path == 'taken_at')
        self.assertFalse(spec.is_custom)  # совпало с пресетом «Сегодня»
        self.assertIn(('driver__id__exact', str(self.role_driver.pk)), spec.hidden_params)
        self.assertNotIn('taken_at__from', dict(spec.hidden_params))
        self.assertContains(response, 'name="taken_at__from"')

    def test_date_field_range(self):
        response = self.client.get(
            reverse('admin:myprofile_clientregistry_changelist'),
            {'registry_date__from': '2026-10-01', 'registry_date__to': '2026-10-31'},
        )
        self.assertEqual(response.status_code, 200)

    def test_facet_counts(self):
        self._history(self.role_driver, timezone.now())
        response = self.client.get(self.url, {'_facets': '1'})
        self.assertEqual(response.status_code, 200)


class AdminChangelistsRenderTest(AdminFiltersBase):
    """Каждый список админки открывается — с фильтрами, счётчиками и периодом."""

    def test_all_changelists_render(self):
        for model, model_admin in django_admin.site._registry.items():
            opts = model._meta
            url = reverse(f'admin:{opts.app_label}_{opts.model_name}_changelist')
            date_paths = [
                f[0] for f in model_admin.list_filter
                if isinstance(f, (list, tuple)) and f[1].__name__ == 'DateRangeFilter'
            ]
            variants = [{}, {'_facets': '1'}]
            if date_paths:
                variants.append({f'{date_paths[0]}__from': '2026-01-01', f'{date_paths[0]}__to': '2026-12-31'})
            for params in variants:
                with self.subTest(model=opts.label, params=params):
                    response = self.client.get(url, params)
                    self.assertEqual(response.status_code, 200)
                    self.assertNotIn('e=1', response.get('Location', ''))
