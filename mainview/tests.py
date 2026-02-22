from django.test import TestCase, Client
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

    def test_about_page(self):
        response = self.client.get(reverse('about'))
        self.assertEqual(response.status_code, 200)

    def test_index_contains_form(self):
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'login')
