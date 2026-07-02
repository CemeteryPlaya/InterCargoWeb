"""
Регрессия прод-инцидента: админка рендерила FK/M2M на крупные таблицы
(TrackCode — 62 795 строк, Receipt, ExtraditionPackage) дефолтным <select>
со всеми записями. Итог: OOM-kill воркера gunicorn (RSS ~490 МБ) и 502 по
upstream timeout. Поля на крупные таблицы обязаны использовать autocomplete
(или raw_id) виджеты.
"""
from django.contrib import admin as django_admin
from django.contrib.admin.widgets import (
    AutocompleteSelect,
    AutocompleteSelectMultiple,
    RelatedFieldWidgetWrapper,
)
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from myprofile.models import (
    Arrival, ClientRegistry, DeliveryHistory,
    Extradition, ExtraditionPackage, ReceiptItem,
)

User = get_user_model()


class AdminAutocompleteWidgetsTest(TestCase):
    """Каждое поле из списка должно рендериться автокомплитом."""

    EXPECTED_AUTOCOMPLETE = [
        (ReceiptItem, 'track_code', AutocompleteSelect),
        (ReceiptItem, 'receipt', AutocompleteSelect),
        (ClientRegistry, 'track_codes', AutocompleteSelectMultiple),
        (Arrival, 'track_codes', AutocompleteSelectMultiple),
        (DeliveryHistory, 'track_codes', AutocompleteSelectMultiple),
        (ExtraditionPackage, 'receipts', AutocompleteSelectMultiple),
        (Extradition, 'package', AutocompleteSelect),
    ]

    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create_superuser(
            username='autocomplete_admin', password='password',
        )

    def test_large_table_fields_use_autocomplete(self):
        request = RequestFactory().get('/admin/')
        request.user = self.superuser
        for model, field_name, widget_cls in self.EXPECTED_AUTOCOMPLETE:
            with self.subTest(model=model.__name__, field=field_name):
                model_admin = django_admin.site._registry[model]
                widget = model_admin.get_form(request).base_fields[field_name].widget
                if isinstance(widget, RelatedFieldWidgetWrapper):
                    widget = widget.widget
                self.assertIsInstance(widget, widget_cls)
