"""Контракты домена чеков и печати.

Базовое понятие — resolved_pickup(track): ПВЗ, в который реально едет позиция.
    = track.delivery_pickup (если задан override), иначе ПВЗ из профиля владельца.

Единый ПВЗ чека (authoritative) вычисляется детерминированно:
    - если все позиции резолвятся в один ПВЗ → он;
    - если расходятся (аномалия) → ПВЗ из профиля владельца чека.
Эту же функцию использует и фикс create_receipts_for_user, и контракт проверки
метки — чтобы правило было единым источником истины.
"""
from .contracts import ExecutionContext, Severity, contract, require, run_contracts


# ─────────────────────────────────────────────────────
# Хелперы резолвинга ПВЗ
# ─────────────────────────────────────────────────────

def _profile_pickup_obj(user):
    if user is None:
        return None
    profile = getattr(user, "userprofile", None)
    if profile and profile.pickup_id:
        return profile.pickup
    return None


def resolved_pickup_obj(track):
    """PickupPoint, в который реально едет трек (override → иначе профиль)."""
    if track is None:
        return None
    if track.delivery_pickup_id and track.delivery_pickup:
        return track.delivery_pickup
    return _profile_pickup_obj(track.owner)


def resolved_pickup_label(track):
    """Строковая метка resolved-ПВЗ трека ('' если не определён)."""
    obj = resolved_pickup_obj(track)
    return str(obj) if obj else ""


def _item_pickup_objs(receipt):
    """{pickup_id: PickupPoint} по позициям чека (только с трек-кодом)."""
    objs = {}
    for item in receipt.items.select_related("track_code", "track_code__owner").all():
        if item.track_code_id and item.track_code:
            obj = resolved_pickup_obj(item.track_code)
            if obj:
                objs[obj.id] = obj
    return objs


def _item_pickup_labels(receipt):
    """Множество непустых resolved-меток ПВЗ по позициям чека."""
    return {str(o) for o in _item_pickup_objs(receipt).values()}


def authoritative_pickup_obj(receipt):
    """Единый PickupPoint чека по детерминированному правилу (см. docstring)."""
    objs = _item_pickup_objs(receipt)
    if len(objs) == 1:
        return next(iter(objs.values()))
    # 0 или >1 (аномалия/нет данных) → ПВЗ из профиля владельца
    return _profile_pickup_obj(receipt.owner)


def authoritative_pickup_label(receipt):
    """Метка единого ПВЗ чека ('' → текущая метка как запасной вариант)."""
    obj = authoritative_pickup_obj(receipt)
    if obj:
        return str(obj)
    return receipt.pickup_point or ""


# ─────────────────────────────────────────────────────
# Контракты уровня чека
# ─────────────────────────────────────────────────────

@contract(severity=Severity.CRITICAL)
def one_receipt_per_client_date(ctx):
    """У клиента не может быть второго чека на ту же дату (created_at)."""
    from myprofile.models import Receipt

    r = ctx.result
    if r is None or r.owner_id is None:
        return
    dupes = (
        Receipt.objects
        .filter(owner_id=r.owner_id, created_at=r.created_at)
        .exclude(pk=r.pk)
        .count()
    )
    require(
        dupes == 0,
        f"У клиента #{r.owner_id} уже есть чек на дату {r.created_at} "
        f"(всего лишних: {dupes})",
        receipt_id=r.pk, owner_id=r.owner_id, date=str(r.created_at), duplicates=dupes,
    )


@contract(severity=Severity.CRITICAL)
def receipt_pickup_label_matches_authoritative(ctx):
    """Метка Receipt.pickup_point совпадает с вычисленным единым ПВЗ чека."""
    r = ctx.result
    if r is None:
        return
    expected = authoritative_pickup_label(r)
    actual = r.pickup_point or ""
    require(
        actual == expected,
        f"Чек #{r.pk}: метка ПВЗ '{actual}' ≠ фактическому '{expected}'",
        receipt_id=r.pk, label=actual, expected=expected,
    )


@contract(severity=Severity.CRITICAL)
def all_items_belong_to_receipt_owner(ctx):
    """Все позиции чека принадлежат владельцу чека."""
    r = ctx.result
    if r is None or r.owner_id is None:
        return
    foreign = []
    for item in r.items.select_related("track_code").all():
        if item.track_code_id and item.track_code and item.track_code.owner_id != r.owner_id:
            foreign.append(item.track_code.track_code)
    require(
        not foreign,
        f"Чек #{r.pk}: позиции чужого владельца: {foreign}",
        receipt_id=r.pk, owner_id=r.owner_id, foreign=foreign,
    )


@contract(severity=Severity.WARNING)
def receipt_tracks_pickup_homogeneous(ctx):
    """Все позиции чека резолвятся в один ПВЗ (иначе аномалия — берём профиль)."""
    r = ctx.result
    if r is None:
        return
    labels = _item_pickup_labels(r)
    require(
        len(labels) <= 1,
        f"Чек #{r.pk}: позиции ведут на разные ПВЗ: {sorted(labels)}",
        receipt_id=r.pk, pickups=sorted(labels),
    )


# ─────────────────────────────────────────────────────
# Контракт печати
# ─────────────────────────────────────────────────────

@contract(severity=Severity.CRITICAL)
def print_run_has_no_foreign_items(ctx):
    """В печать выбранных ПВЗ не должно попасть ни одной позиции другого ПВЗ.

    Ожидает в ctx.extra:
        selected_pickup_names: список/множество строк-меток выбранных ПВЗ;
        printed: список dict с ключом 'pickup' (метка ПВЗ позиции/чека).
    """
    selected = set(ctx.extra.get("selected_pickup_names", []))
    printed = ctx.extra.get("printed", [])
    foreign = [e for e in printed if e.get("pickup") not in selected]
    require(
        not foreign,
        f"В печать ПВЗ {sorted(selected)} попали чужие позиции: {foreign}",
        selected=sorted(selected), foreign=foreign,
    )


# ─────────────────────────────────────────────────────
# Хелперы интеграции во вьюхи печати (read-only, не блокируют)
# ─────────────────────────────────────────────────────

def filter_foreign_print_checks(selected_pickup_names, checks, function_name="print_documents_view.print_checks"):
    """Проверяет печать на чужие ПВЗ; журналит нарушение и убирает чужие чеки.

    Возвращает очищенный список чеков (без чужих ПВЗ). Не бросает исключений —
    печать read-only, поэтому вместо блокировки исключаем некорректный чек и
    фиксируем нарушение в журнал.
    """
    from . import runtime

    selected = set(selected_pickup_names)
    printed = [{"username": c.get("username"), "pickup": c.get("address")} for c in checks]
    ctx = ExecutionContext(extra={"selected_pickup_names": list(selected), "printed": printed})
    violations = run_contracts([print_run_has_no_foreign_items], ctx)
    for v in violations:
        v.function = function_name
        runtime.record_violation(v)
    if violations:
        return [c for c in checks if c.get("address") in selected]
    return checks


def validate_receipt_readonly(receipt, function_name, contracts=None):
    """Гоняет read-only контракты по одному чеку и журналит нарушения.

    Не блокирует (вьюхи печати ничего не меняют). Возвращает список нарушений.
    """
    from . import runtime

    if contracts is None:
        contracts = [
            all_items_belong_to_receipt_owner,
            receipt_pickup_label_matches_authoritative,
            receipt_tracks_pickup_homogeneous,
        ]
    ctx = ExecutionContext(result=receipt)
    violations = run_contracts(contracts, ctx)
    for v in violations:
        v.function = function_name
        runtime.record_violation(v)
    return violations
