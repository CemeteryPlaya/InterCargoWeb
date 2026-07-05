"""Формы staff-UI новостей. Тело поста всегда проходит clean_html (nh3)."""
from django import forms
from django.utils.translation import gettext_lazy as _

from .models import NewsCategory, NewsPost, NewsSettings
from .sanitize import clean_html

_INPUT = ('w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm '
          'focus:ring-2 focus:ring-primary focus:border-primary transition')


class NewsPostForm(forms.ModelForm):
    class Meta:
        model = NewsPost
        fields = [
            'category', 'cover',
            'title_ru', 'title_kk', 'title_en',
            'summary_ru', 'summary_kk', 'summary_en',
            'body_ru', 'body_kk', 'body_en',
            'is_published', 'published_at', 'auth_only',
        ]
        widgets = {
            'category': forms.Select(attrs={'class': _INPUT}),
            'cover': forms.ClearableFileInput(attrs={'class': 'text-sm'}),
            'title_ru': forms.TextInput(attrs={'class': _INPUT}),
            'title_kk': forms.TextInput(attrs={'class': _INPUT}),
            'title_en': forms.TextInput(attrs={'class': _INPUT}),
            'summary_ru': forms.Textarea(attrs={'class': _INPUT, 'rows': 2}),
            'summary_kk': forms.Textarea(attrs={'class': _INPUT, 'rows': 2}),
            'summary_en': forms.Textarea(attrs={'class': _INPUT, 'rows': 2}),
            # Заполняются Quill'ом при submit (news/static/news/manageForm.js)
            'body_ru': forms.HiddenInput(),
            'body_kk': forms.HiddenInput(),
            'body_en': forms.HiddenInput(),
            'published_at': forms.DateTimeInput(
                attrs={'type': 'datetime-local', 'class': _INPUT},
                format='%Y-%m-%dT%H:%M'),
        }

    def _clean_body(self, field):
        return clean_html(self.cleaned_data.get(field, ''))

    def clean_body_ru(self):
        cleaned = self._clean_body('body_ru')
        if not cleaned.strip():
            raise forms.ValidationError(
                _("Текст новости пуст (или полностью удалён при очистке HTML)."))
        return cleaned

    def clean_body_kk(self):
        return self._clean_body('body_kk')

    def clean_body_en(self):
        return self._clean_body('body_en')


class NewsCategoryForm(forms.ModelForm):
    class Meta:
        model = NewsCategory
        fields = ['name_ru', 'name_kk', 'name_en', 'slug', 'color', 'icon',
                  'sort_order', 'is_active']


class NewsSettingsForm(forms.ModelForm):
    class Meta:
        model = NewsSettings
        fields = ['section_enabled', 'desktop_layout']
