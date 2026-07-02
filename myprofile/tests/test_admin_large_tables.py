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
    Extradition, ExtraditionPackage, Receipt, ReceiptItem, TrackCode,
)
from tgbot.models import SentReminder

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
        (SentReminder, 'track_code', AutocompleteSelect),
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


# Скан статический: читает объявленные атрибуты классов (fields/fieldsets/
# autocomplete_fields и т.д.). Динамические get_fields()/get_inlines()/exclude
# он не учитывает — при их появлении расширить _form_field_names/_violations.
LARGE_TABLE_MODELS = {TrackCode, Receipt, ExtraditionPackage}


def _form_field_names(model_admin):
    """Имена полей, попадающих в форму, или None если форма строится из всех полей."""
    if getattr(model_admin, 'fields', None):
        names = set()
        for entry in model_admin.fields:
            names.update(entry if isinstance(entry, (list, tuple)) else [entry])
        return names
    if getattr(model_admin, 'fieldsets', None):
        names = set()
        for _, opts in model_admin.fieldsets:
            for entry in opts.get('fields', ()):
                names.update(entry if isinstance(entry, (list, tuple)) else [entry])
        return names
    return None


def _violations(model, model_admin):
    protected = (
        set(model_admin.autocomplete_fields)
        | set(model_admin.raw_id_fields)
        | set(model_admin.readonly_fields)
    )
    explicit = _form_field_names(model_admin)
    for field in model._meta.get_fields():
        if not (field.many_to_many or field.many_to_one or field.one_to_one):
            continue
        if not getattr(field, 'concrete', False):
            continue  # обратные связи формой не рендерятся
        if field.related_model not in LARGE_TABLE_MODELS:
            continue
        if field.name in protected:
            continue
        if explicit is not None and field.name not in explicit:
            continue  # поле исключено из формы
        yield (
            f"{model_admin.__class__.__name__}.{field.name} "
            f"-> {field.related_model.__name__}"
        )


class AdminRegistryLargeTableScanTest(TestCase):
    """Ни один admin-класс/инлайн не рендерит крупную таблицу дефолтным select."""

    def test_no_unbounded_selects_anywhere(self):
        problems = []
        for model, model_admin in django_admin.site._registry.items():
            problems.extend(_violations(model, model_admin))
            for inline_cls in model_admin.inlines:
                inline = inline_cls(model, django_admin.site)
                problems.extend(_violations(inline.model, inline))
        self.assertEqual(
            problems, [],
            "FK/M2M на крупные таблицы без autocomplete/raw_id/readonly:\n"
            + "\n".join(problems),
        )
