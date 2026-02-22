from django.test import TestCase, RequestFactory
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from myprofile.models import TrackCode, Receipt, ReceiptItem
from myprofile.admin import TrackCodeAdmin
from myprofile.forms import MassUpdateTrackForm

User = get_user_model()

class MockSuperUser:
    def has_perm(self, perm):
        return True

class TrackCodeAdminTest(TestCase):
    def setUp(self):
        self.site = AdminSite()
        self.admin = TrackCodeAdmin(TrackCode, self.site)
        self.factory = RequestFactory()
        self.user = User.objects.create_superuser(username='admin', password='password')

        # Create test data
        self.track1 = TrackCode.objects.create(track_code='TRACK1', status='user_added', owner=self.user)
        self.track2 = TrackCode.objects.create(track_code='TRACK2', status='user_added', owner=self.user)
        
        # Create receipt for track1
        self.receipt = Receipt.objects.create(owner=self.user, is_paid=False)
        ReceiptItem.objects.create(receipt=self.receipt, track_code=self.track1)

    def _mock_messages(self, request):
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, 'session', 'session')
        messages = FallbackStorage(request)
        setattr(request, '_messages', messages)

    def test_mass_update_status_only(self):
        # Prepare POST data simulating the intermediate form submission
        data = {
            'post': 'yes',
            'status': 'warehouse_cn',
            'payment_status': 'no_change',
            '_selected_action': [self.track1.pk, self.track2.pk]
        }
        request = self.factory.post('/admin/myprofile/trackcode/actions/', data)
        request.user = self.user
        self._mock_messages(request)

        # Execute action
        queryset = TrackCode.objects.filter(pk__in=[self.track1.pk, self.track2.pk])
        self.admin.update_status_action(request, queryset)

        # Verify status update
        self.track1.refresh_from_db()
        self.track2.refresh_from_db()
        self.assertEqual(self.track1.status, 'warehouse_cn')
        self.assertEqual(self.track2.status, 'warehouse_cn')
        
        # Verify payment status unchanged
        self.receipt.refresh_from_db()
        self.assertFalse(self.receipt.is_paid)

    def test_mass_update_status_and_payment(self):
        # Prepare POST data simulating the intermediate form submission
        data = {
            'post': 'yes',
            'status': 'delivered',
            'payment_status': 'paid',
            '_selected_action': [self.track1.pk]
        }
        request = self.factory.post('/admin/myprofile/trackcode/actions/', data)
        request.user = self.user
        self._mock_messages(request)

        # Execute action
        queryset = TrackCode.objects.filter(pk__in=[self.track1.pk])
        self.admin.update_status_action(request, queryset)

        # Verify status update
        self.track1.refresh_from_db()
        self.assertEqual(self.track1.status, 'delivered')
        
        # Verify payment status updated
        self.receipt.refresh_from_db()
        self.assertTrue(self.receipt.is_paid)

    def test_mass_update_payment_unpaid(self):
        # Set receipt to paid initially
        self.receipt.is_paid = True
        self.receipt.save()

        data = {
            'post': 'yes',
            'status': 'ready',
            'payment_status': 'not_paid',
            '_selected_action': [self.track1.pk]
        }
        request = self.factory.post('/admin/myprofile/trackcode/actions/', data)
        request.user = self.user
        self._mock_messages(request)

        # Execute action
        queryset = TrackCode.objects.filter(pk__in=[self.track1.pk])
        self.admin.update_status_action(request, queryset)

        # Verify payment status updated
        self.receipt.refresh_from_db()
        self.assertFalse(self.receipt.is_paid)
