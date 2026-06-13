"""Тесты панели управления ролями (role_management, super-admin)."""
import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from register.models import RolePermission, UserProfile

User = get_user_model()


class RoleManagementBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.boss = User.objects.create_superuser(username='boss', password='p', email='b@e.com')
        cls.staff = User.objects.create_user(username='stf', password='p')
        UserProfile.objects.create(user=cls.staff, phone='1', is_staff=True)
        cls.plain = User.objects.create_user(username='plain', password='p')
        UserProfile.objects.create(user=cls.plain, phone='2')


class AccessTests(RoleManagementBase):
    def test_superuser_ok(self):
        c = Client()
        c.login(username='boss', password='p')
        self.assertEqual(c.get(reverse('role_management')).status_code, 200)

    def test_plain_forbidden(self):
        c = Client()
        c.login(username='plain', password='p')
        self.assertEqual(c.get(reverse('role_management')).status_code, 403)

    def test_user_with_users_edit_permission_ok(self):
        RolePermission.objects.create(user=self.plain, aspect='users', can_edit=True)
        c = Client()
        c.login(username='plain', password='p')
        self.assertEqual(c.get(reverse('role_management')).status_code, 200)


class RoleListTests(RoleManagementBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='boss', password='p')

    def test_lists_users_with_roles(self):
        resp = self.client.get(reverse('role_management'))
        usernames = [i['username'] for i in resp.context['items']]
        self.assertIn('stf', usernames)  # имеет is_staff
        self.assertNotIn('plain', usernames)  # без ролей/прав

    def test_search(self):
        resp = self.client.get(reverse('role_management'), {'q': 'stf'})
        self.assertEqual(resp.status_code, 200)


class RoleEditSaveTests(RoleManagementBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='boss', password='p')

    def test_edit_page(self):
        resp = self.client.get(reverse('role_edit', args=[self.plain.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['target'], self.plain)

    def test_save_flags_and_matrix(self):
        payload = {
            'flags': {'is_driver': True},
            'matrix': {'warehouse': {'view': True, 'edit': True}},
        }
        resp = self.client.post(
            reverse('role_save', args=[self.plain.id]),
            data=json.dumps(payload), content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.plain.userprofile.refresh_from_db()
        self.assertTrue(self.plain.userprofile.is_driver)
        rp = RolePermission.objects.get(user=self.plain, aspect='warehouse')
        self.assertTrue(rp.can_view)
        self.assertTrue(rp.can_edit)

    def test_save_empty_matrix_row_skipped(self):
        payload = {'flags': {}, 'matrix': {'finance': {'view': False, 'edit': False}}}
        resp = self.client.post(
            reverse('role_save', args=[self.plain.id]),
            data=json.dumps(payload), content_type='application/json',
        )
        self.assertEqual(resp.json()['explicit_rows'], 0)

    def test_save_invalid_json(self):
        resp = self.client.post(
            reverse('role_save', args=[self.plain.id]),
            data='not json', content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_save_forbidden_for_plain(self):
        c = Client()
        c.login(username='plain', password='p')
        resp = c.post(reverse('role_save', args=[self.staff.id]),
                      data='{}', content_type='application/json')
        self.assertEqual(resp.status_code, 403)


class RoleSearchUsersTests(RoleManagementBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='boss', password='p')

    def test_search_finds_user(self):
        resp = self.client.get(reverse('role_search_users'), {'q': 'plain'})
        usernames = {u['username'] for u in resp.json()['users']}
        self.assertIn('plain', usernames)

    def test_short_query(self):
        resp = self.client.get(reverse('role_search_users'), {'q': 'p'})
        self.assertEqual(resp.json()['users'], [])
