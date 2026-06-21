"""Безопасный перевод существующих пользователей на основные роли (RBAC).

Маппинг по приоритету (ставится только если роль ещё пустая):
  1. is_superuser            -> main_admin
  2. UserProfile.is_staff    -> ПРОПУСК (роль не ставим; печатаем в сводке) —
                                сохраняют текущий доступ, пока Гл.админ не назначит
                                точную роль вручную.
  3. is_pp_worker            -> pvz
  4. is_driver               -> driver

Доп-флаги (is_hr/is_accountant/is_pp_owner/is_tg_admin/is_dibuyer_staff) не трогаются.
Квоты при миграции НЕ проверяются (фиксируем фактическое состояние).

Запуск:
    python manage.py backfill_roles [--dry-run]
"""
from django.core.management.base import BaseCommand

from register.models import UserProfile
from myprofile.permissions import apply_role, ensure_admin_groups


class Command(BaseCommand):
    help = "Назначает основные роли существующим пользователям по старым флагам (безопасно)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help="Показать, что будет сделано, ничего не меняя.",
        )

    def handle(self, *args, **options):
        dry = options['dry_run']
        if not dry:
            ensure_admin_groups()

        mapped = {
            UserProfile.ROLE_MAIN_ADMIN: 0,
            UserProfile.ROLE_PVZ: 0,
            UserProfile.ROLE_DRIVER: 0,
        }
        skipped_staff = []

        for profile in UserProfile.objects.select_related('user'):
            user = profile.user
            if profile.role:
                continue  # роль уже назначена

            if user.is_superuser:
                role = UserProfile.ROLE_MAIN_ADMIN
            elif profile.is_staff:
                skipped_staff.append(user.username)
                continue
            elif profile.is_pp_worker:
                role = UserProfile.ROLE_PVZ
            elif profile.is_driver:
                role = UserProfile.ROLE_DRIVER
            else:
                continue  # клиент / только доп-флаги — без роли

            if not dry:
                apply_role(user, role, enforce_quota=False)
            mapped[role] += 1

        prefix = "[dry-run] " if dry else ""
        self.stdout.write(prefix + "Назначено ролей:")
        self.stdout.write(f"  Главный администратор: {mapped[UserProfile.ROLE_MAIN_ADMIN]}")
        self.stdout.write(f"  Сотрудник ПВЗ:         {mapped[UserProfile.ROLE_PVZ]}")
        self.stdout.write(f"  Доставщик:             {mapped[UserProfile.ROLE_DRIVER]}")
        self.stdout.write(
            f"\nОставлено без роли (is_staff, требуют ручной донастройки): {len(skipped_staff)}"
        )
        for username in skipped_staff:
            self.stdout.write(f"  - {username}")
