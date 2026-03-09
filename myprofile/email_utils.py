import logging
import time
from django.core.mail import get_connection, EmailMessage
from django.conf import settings as django_settings

logger = logging.getLogger(__name__)


def send_mail_logged(subject, body, recipient_list, from_email=None, fail_silently=False):
    """Отправка одного письма с логированием."""
    from myprofile.models import EmailLog

    if from_email is None:
        from_email = django_settings.DEFAULT_FROM_EMAIL

    for recipient in recipient_list:
        try:
            msg = EmailMessage(subject, body, from_email, [recipient])
            msg.send(fail_silently=False)
            EmailLog.objects.create(
                recipient=recipient,
                subject=subject,
                body=body,
                status='sent',
            )
        except Exception as e:
            error_str = str(e)
            logger.error(f"Ошибка отправки email на {recipient}: {error_str}")
            EmailLog.objects.create(
                recipient=recipient,
                subject=subject,
                body=body,
                status='failed',
                error_message=error_str,
            )
            if not fail_silently:
                raise


def send_mail_batch(messages_data, from_email=None):
    """
    Пакетная отправка email через одно SMTP-соединение.
    messages_data: список dict с ключами subject, body, recipient
    Возвращает (sent_count, failed_list) — failed_list содержит dict с recipient и error.
    """
    from myprofile.models import EmailLog

    if from_email is None:
        from_email = django_settings.DEFAULT_FROM_EMAIL

    if not messages_data:
        return 0, []

    sent_count = 0
    failed_list = []

    try:
        connection = get_connection(fail_silently=False)
        connection.open()
    except Exception as e:
        error_str = f"Не удалось открыть SMTP-соединение: {e}"
        logger.error(error_str)
        # Логируем все как failed
        for msg_data in messages_data:
            EmailLog.objects.create(
                recipient=msg_data['recipient'],
                subject=msg_data['subject'],
                body=msg_data['body'],
                status='failed',
                error_message=error_str,
            )
            failed_list.append({'recipient': msg_data['recipient'], 'error': error_str})
        return 0, failed_list

    try:
        for i, msg_data in enumerate(messages_data):
            recipient = msg_data['recipient']
            subject = msg_data['subject']
            body = msg_data['body']

            try:
                email = EmailMessage(subject, body, from_email, [recipient], connection=connection)
                email.send(fail_silently=False)
                EmailLog.objects.create(
                    recipient=recipient,
                    subject=subject,
                    body=body,
                    status='sent',
                )
                sent_count += 1
            except Exception as e:
                error_str = str(e)
                logger.error(f"Ошибка отправки email на {recipient}: {error_str}")
                EmailLog.objects.create(
                    recipient=recipient,
                    subject=subject,
                    body=body,
                    status='failed',
                    error_message=error_str,
                )
                failed_list.append({'recipient': recipient, 'error': error_str})

                # Переоткрываем соединение после ошибки
                try:
                    connection.close()
                    connection.open()
                except Exception:
                    pass

            # Небольшая пауза каждые 10 писем для обхода rate-limit
            if (i + 1) % 10 == 0:
                time.sleep(1)
    finally:
        try:
            connection.close()
        except Exception:
            pass

    return sent_count, failed_list
