from django.urls import path

from . import views

urlpatterns = [
    path('', views.dashboard, name='analytics_dashboard'),
    path('ping/', views.ping, name='analytics_ping'),
    path('ad/', views.ad_event, name='analytics_ad_event'),
    path('mediakit/', views.mediakit, name='analytics_mediakit'),
]
