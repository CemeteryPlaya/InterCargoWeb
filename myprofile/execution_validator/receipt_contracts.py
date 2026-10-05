"""Контракты домена чеков и печати.

Базовое понятие — resolved_pickup(track): ПВЗ, в который реально едет позиция.
    = track.delivery_pickup (если задан override), иначе ПВЗ из профиля владельца.

Единый ПВЗ чека (authoritative) вычисляется детерминированно:
    - если все позиции резолвятся в один ПВЗ → он;
    - если расходятся (аномалия) → ПВЗ из профиля владельца чека.
Эту же функцию использует и фикс create_receipts_for_user, и контракт проверки
метки — чтобы правило было единым источником истины.

Это правило действует для pending-чека (он следует за ПВЗ). После pending чек
заморожен: его факт — только закреплённые delivery_pickup треков; трек без
закрепления не говорит о ПВЗ ничего (unknown), текущий профиль не учитывается.
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


def _pinned_pickup_labels(receipt):
    """Метки закреплённых ПВЗ (track.delivery_pickup) позиций чека."""
    return {
        str(item.track_code.delivery_pickup)
        for item in receipt.items.select_related("track_code__delivery_pickup")
        if item.track_code_id and item.track_code.delivery_pickup_id
    }


def _fact_pickup_labels(receipt):
    """Фактические ПВЗ позиций: pending — resolved (override → профиль),
    после pending — только закреплённые (замороженный чек не следует за профилем)."""
    if receipt.status == "pending":
        return _item_pickup_labels(receipt)
    return _pinned_pickup_labels(receipt)


# ─────────────────────────────────────────────────────
# Контракты уровня чека
# ─────────────────────────────────────────────────────

@contract(severity=Severity.CRITICAL)
def one_pending_receipt_per_client_date_pickup(ctx):
    """На (клиент, дата, ПВЗ) не больше одного pending-чека с позициями-треками.

    Чеки после pending заморожены и ключ не занимают: у клиента может быть
    уехавший чек и новый pending-чек на ту же дату и ПВЗ (решение D4).
    """
    from myprofile.models import Receipt

    r = ctx.result
    if r is None or r.owner_id is None or r.status != "pending":
        return
    if not r.items.filter(track_code__isnull=False).exists():
        return
    dupes = list(
        Receipt.objects
        .filter(owner_id=r.owner_id, created_at=r.created_at, status="pending",
                pickup_point=r.pickup_point or "", items__track_code__isnull=False)
        .exclude(pk=r.pk)
        .distinct()
        .values_list("pk", flat=True)
    )
    require(
        not dupes,
        f"У клиента #{r.owner_id} уже есть pending-чек на {r.created_at} "
        f"для ПВЗ '{r.pickup_point or ''}': {dupes}",
        receipt_id=r.pk, owner_id=r.owner_id, date=str(r.created_at),
        pickup=r.pickup_point or "", duplicates=dupes,
    )


@contract(severity=Severity.CRITICAL)
def receipt_pickup_label_matches_authoritative(ctx):
    """Метка Receipt.pickup_point совпадает с фактическим ПВЗ чека.

    pending — с вычисленным единым ПВЗ (override → профиль), чек перевешивается;
    после pending — только с закреплённым delivery_pickup треков. Нет закрепления
    (или закрепления расходятся — это ловит receipt_tracks_pickup_homogeneous) —
    ПВЗ неизвестен, метку не с чем сверять.
    """
    r = ctx.result
    if r is None:
        return
    if r.status == "pending":
        expected = authoritative_pickup_label(r)
    else:
        pinned = _pinned_pickup_labels(r)
        if len(pinned) != 1:
            return
        expected = next(iter(pinned))
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
    """Все позиции чека ведут в один ПВЗ (иначе аномалия — берём профиль).
    Для замороженного чека учитываются только закреплённые ПВЗ треков."""
    r = ctx.result
    if r is None:
        return
    labels = _fact_pickup_labels(r)
    require(
        len(labels) <= 1,
        f"Чек #{r.pk}: позиции ведут на разные ПВЗ: {sorted(labels)}",
        receipt_id=r.pk, pickups=sorted(labels),
    )


# ─────────────────────────────────────────────────────
# Контракт уровня клиента (sync_pending_receipts_for_user)
# ─────────────────────────────────────────────────────

@contract(severity=Severity.CRITICAL)
def owner_pending_receipts_follow_pickup_rule(ctx):
    """Pending-чеки клиента (первый аргумент — user) однородны по ПВЗ, их метка
    совпадает с authoritative, и на (дата, ПВЗ) не больше одного pending-чека
    с позициями-треками (чек только с архивными позициями ключ не занимает).
    Чеки в других статусах заморожены и здесь не проверяются."""
    from myprofile.models import Receipt

    user = ctx.args[0] if ctx.args else ctx.kwargs.get("user")
    if user is None:
        return
    problems = []
    seen_keys = {}
    for r in Receipt.objects.filter(owner=user, status="pending").order_by("id"):
        labels = sorted(_item_pickup_labels(r))
        if len(labels) > 1:
            problems.append({"receipt_id": r.pk, "problem": "mixed", "pickups": labels})
        expected = authoritative_pickup_label(r)
        if (r.pickup_point or "") != expected:
            problems.append({"receipt_id": r.pk, "problem": "label",
                             "label": r.pickup_point or "", "expected": expected})
        if not labels:
            continue
        key = (r.created_at, r.pickup_point or "")
        if key in seen_keys:
            problems.append({"receipt_id": r.pk, "problem": "duplicate", "same_as": seen_keys[key]})
        seen_keys.setdefault(key, r.pk)
    require(
        not problems,
        f"Клиент #{user.pk}: pending-чеки нарушают правило ПВЗ: {problems}",
        owner_id=user.pk, problems=problems,
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

def split_foreign_print_checks(selected_pickup_names, checks, function_name="print_documents_view.print_checks"):
    """Проверяет печать на чужие ПВЗ: возвращает (к печати, исключённые).

    Нарушение журналируется. Чек чужого ПВЗ не печатается для выбранного ПВЗ,
    но и не теряется молча — вызывающая вьюха показывает его оператору.
    Не бросает исключений (печать read-only).
    """
    from . import runtime

    selected = set(selected_pickup_names)
    printed = [{"username": c.get("username"), "pickup": c.get("address")} for c in checks]
    ctx = ExecutionContext(extra={"selected_pickup_names": list(selected), "printed": printed})
    violations = run_contracts([print_run_has_no_foreign_items], ctx)
    for v in violations:
        v.function = function_name
        runtime.record_violation(v)
    if not violations:
        return checks, []
    return ([c for c in checks if c.get("address") in selected],
            [c for c in checks if c.get("address") not in selected])


def filter_foreign_print_checks(selected_pickup_names, checks, function_name="print_documents_view.print_checks"):
    """Как split_foreign_print_checks, но возвращает только чеки к печати."""
    return split_foreign_print_checks(selected_pickup_names, checks, function_name)[0]


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
