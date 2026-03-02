from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from register.models import UserProfile, PendingRegistration, PickupPoint

User = get_user_model()


class PickupPointMixin:
    """Creates a default PickupPoint for tests."""
    def setUp(self):
        super().setUp()
        self.pickup_point = PickupPoint.objects.create(
            address='Акбулак 21', premise_name='Ozon'
        )


class LoginViewTest(PickupPointMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.user = User.objects.create_user(username='LOGINUSER', password='pass123')
        UserProfile.objects.create(user=self.user, phone='7001000001', pickup=self.pickup_point)

    def test_login_page_get(self):
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)

    def test_login_success(self):
        response = self.client.post(reverse('login'), {
            'login': 'loginuser',
            'password': 'pass123',
        })
        self.assertEqual(response.status_code, 302)

    def test_login_uppercase_success(self):
        response = self.client.post(reverse('login'), {
            'login': 'LoginUser',
            'password': 'pass123',
        })
        self.assertEqual(response.status_code, 302)

    def test_login_wrong_password(self):
        response = self.client.post(reverse('login'), {
            'login': 'loginuser',
            'password': 'wrongpass',
        })
        self.assertEqual(response.status_code, 200)

    def test_login_nonexistent_user(self):
        response = self.client.post(reverse('login'), {
            'login': 'nouser',
            'password': 'pass123',
        })
        self.assertEqual(response.status_code, 200)


class LogoutViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='logoutuser', password='pass123')
        self.client.login(username='logoutuser', password='pass123')

    def test_logout_redirects(self):
        response = self.client.get('/register/logout/')
        self.assertEqual(response.status_code, 302)

    def test_logout_clears_session(self):
        self.client.get('/register/logout/')
        response = self.client.get(reverse('track_codes'))
        self.assertEqual(response.status_code, 302)


class RegistrationFlowTest(PickupPointMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()

    def test_pre_register_get(self):
        response = self.client.get(reverse('pre_register'))
        self.assertEqual(response.status_code, 200)

    def test_pre_register_post_success(self):
        response = self.client.post(reverse('pre_register'), {
            'login': 'newuser',
            'phone': '7009999999',
            'pickup': str(self.pickup_point.id),
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('registration_data', self.client.session)

    def test_pre_register_missing_fields(self):
        response = self.client.post(reverse('pre_register'), {
            'login': 'newuser',
            'phone': '',
            'pickup': '',
        })
        self.assertEqual(response.status_code, 200)

    def test_continue_register_with_session(self):
        session = self.client.session
        session['registration_data'] = {
            'login': 'newuser', 'phone': '7009999999', 'pickup': str(self.pickup_point.id)
        }
        session.save()
        response = self.client.get(reverse('continue_register'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'newuser')

    def test_continue_register_without_session(self):
        response = self.client.get(reverse('continue_register'))
        self.assertEqual(response.status_code, 200)

    def test_register_full_flow(self):
        hr_user = User.objects.create_user(username='hr', password='pass123')
        UserProfile.objects.create(user=hr_user, phone='7000000001', pickup=self.pickup_point, is_hr=True)

        response = self.client.post(reverse('register'), {
            'login': 'brandnew',
            'password': 'securepass',
            'phone': '7008888888',
            'email': 'brandnew@test.com',
            'pickup': str(self.pickup_point.id),
            'first_name': 'Иван',
            'last_name': 'Иванов',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(PendingRegistration.objects.filter(login='BRANDNEW').exists())

    def test_register_duplicate_username(self):
        User.objects.create_user(username='EXISTING', password='pass123')
        response = self.client.post(reverse('register'), {
            'login': 'existing',
            'password': 'securepass',
            'phone': '7007777777',
            'pickup': str(self.pickup_point.id),
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(PendingRegistration.objects.filter(login='EXISTING').exists())

    def test_register_duplicate_phone(self):
        user = User.objects.create_user(username='phoneuser', password='pass123')
        UserProfile.objects.create(user=user, phone='7006666666', pickup=self.pickup_point)
        response = self.client.post(reverse('register'), {
            'login': 'anotheruser',
            'password': 'securepass',
            'phone': '7006666666',
            'pickup': str(self.pickup_point.id),
        })
        self.assertEqual(response.status_code, 200)


class ConfirmViewTest(PickupPointMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.hr_user = User.objects.create_user(username='hruser', password='pass123')
        UserProfile.objects.create(
            user=self.hr_user, phone='7000000002', pickup=self.pickup_point, is_hr=True
        )
        self.non_hr = User.objects.create_user(username='normaluser', password='pass123')
        UserProfile.objects.create(
            user=self.non_hr, phone='7000000003', pickup=self.pickup_point, is_hr=False
        )

    def test_confirm_view_hr_access(self):
        self.client.login(username='hruser', password='pass123')
        response = self.client.get(reverse('confirm'))
        self.assertEqual(response.status_code, 200)

    def test_confirm_view_non_hr_redirected(self):
        self.client.login(username='normaluser', password='pass123')
        response = self.client.get(reverse('confirm'))
        self.assertEqual(response.status_code, 302)

    def test_confirm_view_unauthenticated_redirected(self):
        response = self.client.get(reverse('confirm'))
        self.assertEqual(response.status_code, 302)

    def test_approve_registration(self):
        self.client.login(username='hruser', password='pass123')
        pending = PendingRegistration.objects.create(
            login='pendinguser', phone='7005555555',
            pickup=self.pickup_point, password='testpass'
        )
        response = self.client.get(reverse('approve_registration', args=[pending.id]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username='pendinguser').exists())
        self.assertFalse(PendingRegistration.objects.filter(id=pending.id).exists())

    def test_reject_registration(self):
        self.client.login(username='hruser', password='pass123')
        pending = PendingRegistration.objects.create(
            login='rejectuser', phone='7004444444',
            pickup=self.pickup_point, password='testpass'
        )
        response = self.client.post(reverse('reject_registration', args=[pending.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(PendingRegistration.objects.filter(id=pending.id).exists())
        self.assertFalse(User.objects.filter(username='rejectuser').exists())


class SuccessViewTest(TestCase):
    def test_success_page(self):
        response = self.client.get(reverse('success'))
        self.assertEqual(response.status_code, 200)
