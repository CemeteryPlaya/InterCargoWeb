"""Посылки партнёрского сервиса Di.Buyer в чеках Inter Cargo.

Решение владельца (2026-10-10): Di.Buyer — партнёрский сервис, оплату принимает
партнёр на свои счета. Inter Cargo его посылки только доставляет и выдаёт:
- такие посылки идут в отдельный чек (Receipt.source = 'dibuyer') — ключ
  pending-чека: клиент + дата + ПВЗ + источник (receipt_pickup.receipt_key);
- сумма чека Di.Buyer для Inter Cargo — 0 ₸ (ни картой, ни на ПВЗ);
- ПВЗ выдаёт чек Di.Buyer только после отметки партнёра «оплата получена»
  (BuyerOrder.partner_paid_at) — unpaid_partner_receipts / partner_issue_error.

Посылка Di.Buyer = трек, привязанный к позиции заявки (BuyerOrderItem.track_code).
"""
from django.utils.translation import gettext as _

SOURCE_CARGO = 'cargo'
SOURCE_DIBUYER = 'dibuyer'


def partner_track_ids(track_ids):
    """Из переданных id треков — те, что принадлежат заявкам Di.Buyer (один запрос)."""
    ids = [i for i in track_ids if i]
    if not ids:
        return set()
    try:
        from dibuyer.models import BuyerOrderItem
    except ImportError:  # модуль партнёра отключён
        return set()
    return set(BuyerOrderItem.objects.filter(track_code_id__in=ids)
               .values_list('track_code_id', flat=True))


def track_source(track, partner_ids=None):
    """Источник чека для трека. partner_ids — заранее посчитанный набор
    (partner_track_ids), чтобы не делать запрос на каждый трек."""
    if partner_ids is None:
        partner_ids = partner_track_ids([track.id])
    return SOURCE_DIBUYER if track.id in partner_ids else SOURCE_CARGO


def unpaid_partner_receipts(receipts):
    """Чеки Di.Buyer, оплату которых партнёр ещё не подтвердил.

    Чек считается оплаченным, когда у всех его посылок заявка отмечена
    партнёром (partner_paid_at). Чеки Inter Cargo не проверяются.
    """
    from myprofile.models import ReceiptItem

    partner = [r for r in receipts if r.source == SOURCE_DIBUYER]
    if not partner:
        return []
    pairs = list(ReceiptItem.objects.filter(receipt__in=partner, track_code__isnull=False)
                 .values_list('receipt_id', 'track_code_id'))
    try:
        from dibuyer.models import BuyerOrderItem
        paid_tracks = set(BuyerOrderItem.objects.filter(
            track_code_id__in=[t for _r, t in pairs], order__partner_paid_at__isnull=False,
        ).values_list('track_code_id', flat=True))
    except ImportError:
        paid_tracks = set()
    unpaid_ids = {r for r, t in pairs if t not in paid_tracks}
    return [r for r in partner if r.id in unpaid_ids]


def partner_issue_error(receipts):
    """Текст ошибки для оператора, если среди выдаваемых чеков есть Di.Buyer без
    подтверждённой оплаты; None — выдавать можно."""
    unpaid = unpaid_partner_receipts(receipts)
    if not unpaid:
        return None
    return _(
        "Выдача остановлена: чек(и) Di.Buyer %(numbers)s — партнёр ещё не подтвердил оплату. "
        "Свяжитесь с Di.Buyer; посылки Inter Cargo этого клиента можно выдать отдельно."
    ) % {'numbers': ', '.join(r.receipt_number for r in unpaid)}
