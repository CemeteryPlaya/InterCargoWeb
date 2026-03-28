import logging
import time
from django.core.mail import get_connection, EmailMessage
from django.conf import settings as django_settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAYS = [2, 5, 10]  # секунды между повторами


def send_mail_logged(subject, body, recipient_list, from_email=None, fail_silently=False):
    """Отправка одного письма с логированием и повторными попытками."""
    from myprofile.models import EmailLog

    if from_email is None:
        from_email = django_settings.DEFAULT_FROM_EMAIL

    for recipient in recipient_list:
        last_error = None
        sent = False

        for attempt in range(MAX_RETRIES):
            try:
                connection = get_connection(fail_silently=False)
                msg = EmailMessage(subject, body, from_email, [recipient], connection=connection)
                msg.send(fail_silently=False)
                sent = True
                break
            except Exception as e:
                last_error = str(e)
                logger.warning(
                    "Попытка %d/%d отправки email на %s: %s",
                    attempt + 1, MAX_RETRIES, recipient, last_error,
                )
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAYS[attempt])
            finally:
                try:
                    connection.close()
                except Exception:
                    pass

        if sent:
            EmailLog.objects.create(
                recipient=recipient,
                subject=subject,
                body=body,
                status='sent',
            )
        else:
            logger.error("Не удалось отправить email на %s после %d попыток: %s",
                         recipient, MAX_RETRIES, last_error)
            EmailLog.objects.create(
                recipient=recipient,
                subject=subject,
                body=body,
                status='failed',
                error_message=last_error,
            )
            if not fail_silently:
                raise Exception(last_error)


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

    connection = _open_smtp_connection()
    if connection is None:
        error_str = "Не удалось открыть SMTP-соединение после нескольких попыток"
        logger.error(error_str)
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

            send_ok = False
            last_error = ''

            for attempt in range(MAX_RETRIES):
                try:
                    email = EmailMessage(subject, body, from_email, [recipient], connection=connection)
                    email.send(fail_silently=False)
                    send_ok = True
                    break
                except Exception as e:
                    last_error = str(e)
                    logger.warning(
                        "Попытка %d/%d отправки batch email на %s: %s",
                        attempt + 1, MAX_RETRIES, recipient, last_error,
                    )
                    # Переоткрываем соединение
                    try:
                        connection.close()
                    except Exception:
                        pass
                    connection = _open_smtp_connection()
                    if connection is None:
                        last_error = "Не удалось переоткрыть SMTP-соединение"
                        break
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(RETRY_DELAYS[attempt])

            if send_ok:
                EmailLog.objects.create(
                    recipient=recipient,
                    subject=subject,
                    body=body,
                    status='sent',
                )
                sent_count += 1
            else:
                logger.error("Не удалось отправить email на %s: %s", recipient, last_error)
                EmailLog.objects.create(
                    recipient=recipient,
                    subject=subject,
                    body=body,
                    status='failed',
                    error_message=last_error,
                )
                failed_list.append({'recipient': recipient, 'error': last_error})

            # Пауза каждые 10 писем для обхода rate-limit Gmail
            if (i + 1) % 10 == 0:
                time.sleep(1)
    finally:
        try:
            connection.close()
        except Exception:
            pass

    return sent_count, failed_list


def _open_smtp_connection():
    """Открывает SMTP-соединение с повторными попытками."""
    for attempt in range(MAX_RETRIES):
        try:
            connection = get_connection(fail_silently=False)
            connection.open()
            return connection
        except Exception as e:
            logger.warning(
                "Попытка %d/%d открытия SMTP-соединения: %s",
                attempt + 1, MAX_RETRIES, e,
            )
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAYS[attempt])
    return None
