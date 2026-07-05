from django.urls import path

from news.views import manage, public

urlpatterns = [
    # Staff-UI (доступ: аспект 'news', page_key 'news_management')
    path('manage/', manage.news_manage, name='news_manage'),
    path('manage/settings/', manage.news_settings_save, name='news_settings_save'),
    path('manage/category/save/', manage.news_category_save, name='news_category_save'),
    path('manage/category/<int:pk>/delete/', manage.news_category_delete, name='news_category_delete'),
    path('manage/post/new/', manage.news_post_create, name='news_post_create'),
    path('manage/post/<int:pk>/', manage.news_post_edit, name='news_post_edit'),
    path('manage/post/<int:pk>/toggle/', manage.news_post_toggle, name='news_post_toggle'),
    path('manage/post/<int:pk>/delete/', manage.news_post_delete, name='news_post_delete'),
    # Публичные страницы
    path('', public.news_list, name='news_list'),
    path('<int:pk>/', public.news_detail, name='news_detail'),
]
