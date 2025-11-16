import json
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.conf import settings
from pywebpush import webpush, WebPushException
from myprofile.models import UserPushSubscription, Notification

@csrf_exempt
def save_push_subscription(request):
    if request.method == 'POST' and request.user.is_authenticated:
        data = json.loads(request.body)

        # сохраняем подписку в базе
        sub, _ = UserPushSubscription.objects.update_or_create(
            user=request.user,
            defaults={'subscription_data': data}
        )
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'status': 'error'}, status=400)


def send_push(user, title, message, url='/'):
    try:
        sub = UserPushSubscription.objects.get(user=user)
        webpush(
            subscription_info=sub.subscription_data,
            data=json.dumps({
                "title": title,
                "body": message,
                "url": url
            }),
            vapid_private_key=settings.WEBPUSH_SETTINGS['VAPID_PRIVATE_KEY'],
            vapid_claims={"sub": f"mailto:{settings.WEBPUSH_SETTINGS['VAPID_ADMIN_EMAIL']}"}
        )
    except UserPushSubscription.DoesNotExist:
        print(f"[!] Нет подписки для пользователя {user.username}")
    except WebPushException as e:
        print(f"[!] Ошибка при отправке push: {e}")


def create_notification(user, message):
    notif = Notification.objects.create(user=user, message=message)
    send_push(user, "Новое уведомление", message, "/profile/notifications/")