from django.urls import path
from . import views

urlpatterns = [
    path('link/', views.generate_link, name='telegram_link'),
    path('unlink/', views.unlink_telegram, name='telegram_unlink'),
    path('relink/', views.relink_telegram, name='telegram_relink'),
]
