"""
URL configuration for cargo project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve as static_serve
from mainview import views as mainview_views

urlpatterns = [
    path('i18n/', include('django.conf.urls.i18n')),
    path('rosetta/', include('rosetta.urls')),
    # Service worker must be served from root scope
    path('sw.js', static_serve, {'document_root': settings.BASE_DIR / 'mainview' / 'static', 'path': 'sw.js'}, name='sw.js'),
    re_path(r"^mainview/", include('mainview.urls')),
    re_path(r"^register/", include('register.urls')),
    re_path(r"^profile/", include('myprofile.urls')),
    path('profile/telegram/', include('tgbot.urls')),
    path('dibuyer/', include('dibuyer.urls')),
    path('analytics/', include('analytics.urls')),
    path('support/', include('support.urls')),
    path('news/', include('news.urls')),
    path('payments/', include('payments.urls')),
    # Покупателям: реквизиты, оферта, оплата, доставка, возврат (требование банка-эквайера)
    path('info/<slug:slug>/', mainview_views.info_page, name='info_page'),
    path('admin/', admin.site.urls),
    # Main application URLs
    path('', mainview_views.index, name='home'),
]
# === DEV: раскомментируй для локальной разработки ===
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
# === PROD: на продакшене DEBUG=False, статику раздаёт Nginx ===