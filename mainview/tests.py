from django.test import TestCase, Client, override_settings
from django.urls import reverse


class MainViewTest(TestCase):
    def setUp(self):
        self.client = Client()

    def test_index_page(self):
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)

    def test_education_page(self):
        response = self.client.get(reverse('education'))
        self.assertEqual(response.status_code, 200)

    def test_about_page_moved_to_info(self):
        response = self.client.get(reverse('about'))
        self.assertRedirects(response, reverse('info_page', args=['about']), status_code=301)
        page = self.client.get(reverse('info_page', args=['about']))
        self.assertContains(page, 'Inter Cargo')
        self.assertContains(page, 'faq-list')

    def test_header_has_info_instead_of_about(self):
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'href="%s"' % reverse('info_page', args=['about']))
        self.assertNotContains(response, 'href="%s"' % reverse('about'))

    def test_index_contains_form(self):
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'login')


class AcquiringRequirementsTest(TestCase):
    """Требования Halyk Bank к оформлению сайта (Приложение 1 к Договору эквайринга)."""

    def setUp(self):
        from register.models import PickupPoint
        PickupPoint.objects.create(address='г. Тараз, ул. Толе би, 1', premise_name='ТЦ Тест',
                                   working_hours='Пн–Сб 10:00–19:00')

    def test_all_info_pages_render_in_all_languages(self):
        from mainview.context_processors import INFO_PAGES
        from django.utils import translation
        for lang in ('ru', 'kk', 'en'):
            with translation.override(lang):
                for slug, _title in INFO_PAGES:
                    resp = self.client.get(reverse('info_page', args=[slug]), HTTP_ACCEPT_LANGUAGE=lang)
                    self.assertEqual(resp.status_code, 200, f'{lang}/{slug}')

    def test_unknown_info_page_404(self):
        self.assertEqual(self.client.get('/info/unknown/').status_code, 404)

    def test_info_page_uses_language_template(self):
        from mainview.context_processors import INFO_PAGES
        for slug, _title in INFO_PAGES:
            if slug == 'about':  # один шаблон на все языки — тексты через {% trans %}
                continue
            for lang in ('kk', 'en'):
                self.client.cookies['django_language'] = lang
                resp = self.client.get(reverse('info_page', args=[slug]))
                self.assertEqual(resp.context['content_template'], f'info/{slug}.{lang}.html')
        self.client.cookies.pop('django_language')

    @override_settings(COMPANY_INFO={
        'brand': 'Inter Cargo', 'legal_name': 'ИП Тестов Т.Т.', 'iin': '900101300123',
        'country': 'Республика Казахстан', 'city': 'Тараз', 'legal_address': 'Юр. адрес 1',
        'actual_address': 'Факт. адрес 2', 'schedule': 'Пн–Пт 9:00–18:00',
        'phone_director': '+7 (777) 000-00-00', 'phone_support': '+7 (700) 111-11-11',
        'email': 'test@example.com', 'bank_name': 'Halyk', 'iban': '', 'bik': 'HSBKKZKX',
        'vat_payer': False})
    def test_contacts_show_requisites_and_pickup_points(self):
        resp = self.client.get(reverse('info_page', args=['contacts']))
        for text in ('ИП Тестов Т.Т.', '900101300123', 'Юр. адрес 1', 'Факт. адрес 2',
                     'Пн–Пт 9:00–18:00', '+7 (700) 111-11-11', 'г. Тараз, ул. Толе би, 1',
                     'Пн–Сб 10:00–19:00', 'makemap.2gis.ru'):
            self.assertContains(resp, text)

    def test_services_show_price_in_tenge(self):
        from myprofile.models import GlobalSettings
        GlobalSettings.objects.create(price_per_kg=1859)
        resp = self.client.get(reverse('info_page', args=['services']))
        self.assertContains(resp, '1859 ₸')

    def test_footer_has_payment_logos_epay_link_and_legal_links(self):
        resp = self.client.get(reverse('home'))
        self.assertContains(resp, 'images/payments/visa.svg')
        self.assertContains(resp, 'images/payments/mastercard.svg')
        self.assertContains(resp, 'href="https://epayment.kz"')
        for slug in ('offer', 'privacy', 'returns', 'payment', 'delivery', 'contacts'):
            self.assertContains(resp, reverse('info_page', args=[slug]))

    def test_no_placeholder_links_on_public_pages(self):
        for url in (reverse('home'), reverse('education'), reverse('info_page', args=['about']),
                    reverse('info_page', args=['payment'])):
            resp = self.client.get(url)
            self.assertNotContains(resp, 'href="#"', msg_prefix=url)

    @override_settings(EDUCATION_VIDEOS={'registration': 'https://t.me/c/1/3', 'order': '',
                                         'tracking': 'https://youtu.be/public'})
    def test_private_videos_hidden_from_guests(self):
        """Закрытый канал — только для вошедших; публичные ссылки видны всем."""
        from django.contrib.auth.models import User
        resp = self.client.get(reverse('education'))
        self.assertNotContains(resp, 't.me/c/')
        self.assertContains(resp, 'https://youtu.be/public')
        User.objects.create_user('VIDEO0001', password='pw')
        self.client.login(username='VIDEO0001', password='pw')
        resp = self.client.get(reverse('education'))
        self.assertContains(resp, 'https://t.me/c/1/3')

    def test_check_warns_about_missing_requisites(self):
        from mainview.checks import company_info_check
        with self.settings(COMPANY_INFO={'legal_name': '', 'iin': ''}):
            ids = [w.id for w in company_info_check(None)]
        self.assertEqual(ids, ['mainview.W001'])
        self.assertEqual(company_info_check(None), [])  # реквизиты ИП заданы по умолчанию


class AllTemplatesCompileTest(TestCase):
    """Каждый шаблон проекта компилируется (ловит битые {% if %} и т.п. после
    массовых правок вёрстки — страница иначе падает только при открытии)."""

    def test_every_template_compiles(self):
        from pathlib import Path
        from django.conf import settings
        from django.template import TemplateSyntaxError
        from django.template.loader import get_template
        broken = []
        for templates_dir in Path(settings.BASE_DIR).glob('*/templates'):
            if '.venv' in templates_dir.parts:
                continue
            for path in templates_dir.rglob('*.html'):
                name = path.relative_to(templates_dir).as_posix()
                try:
                    get_template(name)
                except TemplateSyntaxError as exc:
                    broken.append(f'{name}: {exc}')
        self.assertEqual(broken, [])


class NavGroupsTest(TestCase):
    """Служебное меню (сайдбар, мобильное «Меню», выдвижное меню) — группы по
    назначению из NAV_GROUPS, только доступные роли пункты, пустые группы скрыты."""

    def _titles(self, user):
        from mainview.context_processors import build_nav_groups
        from myprofile.permissions import allowed_pages
        return [str(g['title']) for g in build_nav_groups(user, allowed_pages(user))]

    def test_client_has_no_service_groups(self):
        from django.contrib.auth.models import User
        from register.models import UserProfile
        client = User.objects.create_user('CLIENT0100', password='pw')
        UserProfile.objects.create(user=client)
        self.assertEqual(self._titles(client), [])

    def test_pp_worker_sees_only_pickup_point_group(self):
        from django.contrib.auth.models import User
        from register.models import UserProfile
        worker = User.objects.create_user('PVZ0100', password='pw')
        UserProfile.objects.create(user=worker, is_pp_worker=True)
        self.assertEqual(self._titles(worker), ['Пункт выдачи'])

    def test_superuser_sees_all_groups_in_workflow_order(self):
        from django.contrib.auth.models import User
        admin = User.objects.create_superuser('ROOT0100', 'r@example.com', 'pw')
        self.assertEqual(self._titles(admin), [
            'Приход и сортировка', 'Доставка', 'Пункт выдачи', 'Клиенты',
            'Отчёты и рассылки', 'Администрирование'])

    def test_menus_render_groups(self):
        from django.contrib.auth.models import User
        User.objects.create_superuser('ROOT0101', 'r2@example.com', 'pw')
        self.client.login(username='ROOT0101', password='pw')
        desktop = self.client.get(reverse('track_codes'))
        self.assertContains(desktop, 'Приход и сортировка')
        self.assertContains(desktop, reverse('role_management'))
        mobile = self.client.get(reverse('mobile_menu'))
        self.assertContains(mobile, 'Отчёты и рассылки')
        self.assertContains(mobile, reverse('support_inbox'))
