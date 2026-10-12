"""
Общие фильтры для Django-админки всех приложений.

- ``DateRangeFilter`` — фильтр по дате: быстрые периоды (сегодня, вчера,
  7/30 дней, месяц, прошлый месяц, год) + произвольный отрезок «с … по …».
  Подключение: ``list_filter = (('created_at', DateRangeFilter), ...)``.
  Параметры URL: ``<поле>__from`` / ``<поле>__to`` (YYYY-MM-DD, обе границы
  включительно) и ``<поле>__isnull`` для полей с null=True.
- ``DriverListFilter`` — фильтр по FK на пользователя, в котором выводятся
  только доставщики (роль «Доставщик» или флаг ``is_driver``).
- ``StaffUserListFilter`` — то же для персонала (без клиентов).

Списки пользователей фильтруются по роли, а не «все User»: стандартный
RelatedFieldListFilter вывел бы в сайдбар каждого клиента.
"""
import calendar
import datetime

from django.contrib import admin
from django.contrib.admin.views.main import ERROR_FLAG, PAGE_VAR
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from register.models import UserProfile


def driver_users_q(prefix=''):
    """Q-условие «пользователь — доставщик» (роль или legacy-флаг)."""
    return (
        Q(**{f'{prefix}userprofile__role': UserProfile.ROLE_DRIVER})
        | Q(**{f'{prefix}userprofile__is_driver': True})
    )


def staff_users_q(prefix=''):
    """Q-условие «пользователь — персонал»: любая роль, служебный флаг или доступ в админку."""
    profile = f'{prefix}userprofile__'
    q = Q(**{f'{prefix}is_staff': True}) | Q(**{f'{prefix}is_superuser': True})
    q |= ~Q(**{f'{profile}role': ''}) & Q(**{f'{profile}role__isnull': False})
    for flag in ('is_staff', 'is_hr', 'is_driver', 'is_pp_worker', 'is_pp_owner',
                 'is_accountant', 'is_tg_admin', 'is_dibuyer_staff'):
        q |= Q(**{f'{profile}{flag}': True})
    return q


def user_label(user):
    full_name = user.get_full_name()
    return f'{full_name} ({user.username})' if full_name else user.username


class RoleUserListFilter(admin.RelatedFieldListFilter):
    """Фильтр по FK на User, ограниченный условием ``users_q()``.

    Подключение: ``list_filter = (('driver', DriverListFilter), ...)``.
    """

    def users_q(self):
        raise NotImplementedError

    def field_choices(self, field, request, model_admin):
        users = (
            field.related_model._default_manager
            .filter(self.users_q())
            .distinct()
            .order_by('first_name', 'last_name', 'username')
        )
        return [(user.pk, user_label(user)) for user in users]


class DriverListFilter(RoleUserListFilter):
    def users_q(self):
        return driver_users_q()


class StaffUserListFilter(RoleUserListFilter):
    def users_q(self):
        return staff_users_q()


def _month_bounds(day):
    first = day.replace(day=1)
    last = day.replace(day=calendar.monthrange(day.year, day.month)[1])
    return first, last


class DateRangeFilter(admin.FieldListFilter):
    template = 'admin/filters/date_range.html'

    def __init__(self, field, request, params, model, model_admin, field_path):
        self.parameter_from = f'{field_path}__from'
        self.parameter_to = f'{field_path}__to'
        self.parameter_isnull = f'{field_path}__isnull'
        super().__init__(field, request, params, model, model_admin, field_path)
        self.date_from = self._date_param(self.parameter_from)
        self.date_to = self._date_param(self.parameter_to)
        if self.date_from and self.date_to and self.date_from > self.date_to:
            self.date_from, self.date_to = self.date_to, self.date_from
        isnull = self.used_parameters.get(self.parameter_isnull)
        self.isnull = isnull[-1] if isnull else None
        self.hidden_params = []
        self.is_custom = False

    def expected_parameters(self):
        params = [self.parameter_from, self.parameter_to]
        if self.field.null:
            params.append(self.parameter_isnull)
        return params

    def _date_param(self, name):
        values = self.used_parameters.get(name)
        if not values:
            return None
        try:
            return datetime.date.fromisoformat(values[-1])
        except (TypeError, ValueError):
            return None  # битую дату из URL игнорируем, а не роняем список

    @property
    def is_datetime(self):
        return isinstance(self.field, models.DateTimeField)

    def _range_q(self, date_from, date_to):
        """Отрезок [date_from; date_to] включительно, в локальном часовом поясе."""
        lookups = {}
        if self.is_datetime:
            tz = timezone.get_current_timezone()
            if date_from:
                lookups[f'{self.field_path}__gte'] = datetime.datetime.combine(
                    date_from, datetime.time.min, tzinfo=tz)
            if date_to:
                lookups[f'{self.field_path}__lt'] = datetime.datetime.combine(
                    date_to + datetime.timedelta(days=1), datetime.time.min, tzinfo=tz)
        else:
            if date_from:
                lookups[f'{self.field_path}__gte'] = date_from
            if date_to:
                lookups[f'{self.field_path}__lte'] = date_to
        return Q(**lookups)

    def queryset(self, request, queryset):
        if self.isnull is not None:
            queryset = queryset.filter(**{f'{self.field_path}__isnull': self.isnull})
        if self.date_from or self.date_to:
            queryset = queryset.filter(self._range_q(self.date_from, self.date_to))
        return queryset

    def presets(self):
        today = timezone.localdate()
        yesterday = today - datetime.timedelta(days=1)
        month_start, month_end = _month_bounds(today)
        prev_start, prev_end = _month_bounds(month_start - datetime.timedelta(days=1))
        return [
            (_("Сегодня"), today, today),
            (_("Вчера"), yesterday, yesterday),
            (_("Последние 7 дней"), today - datetime.timedelta(days=6), today),
            (_("Последние 30 дней"), today - datetime.timedelta(days=29), today),
            (_("Этот месяц"), month_start, month_end),
            (_("Прошлый месяц"), prev_start, prev_end),
            (_("Этот год"), today.replace(month=1, day=1), today.replace(month=12, day=31)),
        ]

    def _links(self):
        """(подпись, параметры URL, Q для счётчика) для каждой ссылки фильтра."""
        links = [(_("Любая дата"), {}, Q())]
        for title, date_from, date_to in self.presets():
            links.append((
                title,
                {self.parameter_from: date_from.isoformat(), self.parameter_to: date_to.isoformat()},
                self._range_q(date_from, date_to),
            ))
        if self.field.null:
            links.append((_("Без даты"), {self.parameter_isnull: 'True'},
                          Q(**{f'{self.field_path}__isnull': True})))
            links.append((_("С датой"), {self.parameter_isnull: 'False'},
                          Q(**{f'{self.field_path}__isnull': False})))
        return links

    def _current_params(self):
        params = {}
        if self.date_from:
            params[self.parameter_from] = self.date_from.isoformat()
        if self.date_to:
            params[self.parameter_to] = self.date_to.isoformat()
        if self.isnull is not None:
            params[self.parameter_isnull] = str(self.isnull)
        return params

    def get_facet_counts(self, pk_attname, filtered_qs):
        return {
            f'{i}__c': models.Count(pk_attname, filter=q)
            for i, (_title, _params, q) in enumerate(self._links())
        }

    def choices(self, changelist):
        # Скрытые поля формы «с … по …»: остальные фильтры, поиск и сортировка
        # не должны сбрасываться при выборе своего отрезка.
        own = set(self.expected_parameters()) | {PAGE_VAR, ERROR_FLAG}
        self.hidden_params = [
            (name, value)
            for name, values in changelist.filter_params.items() if name not in own
            for value in values
        ]
        add_facets = changelist.add_facets
        facet_counts = self.get_facet_queryset(changelist) if add_facets else None
        current = self._current_params()
        is_custom = bool(current)
        for i, (title, params, _q) in enumerate(self._links()):
            selected = current == params
            is_custom &= not selected
            if add_facets:
                title = f'{title} ({facet_counts[f"{i}__c"]})'
            yield {
                'selected': selected,
                'query_string': changelist.get_query_string(params, self.expected_parameters()),
                'display': title,
            }
        self.is_custom = is_custom
