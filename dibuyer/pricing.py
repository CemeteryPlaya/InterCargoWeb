from decimal import Decimal, ROUND_HALF_UP


def compute_line_pricing(total_kzt, weight, usd_rate_per_kg):
    """Из итоговой стоимости доставки (₸) и веса (кг) считает ставку ₸/кг и курс ₸/$.

    Возвращает (rate_per_kg, exchange_rate), оба Decimal с 2 знаками.
    rate_per_kg   = total_kzt / weight                       — «коэффициент» позиции чека.
    exchange_rate = total_kzt / (weight * usd_rate_per_kg)   — подразумеваемый курс ₸/$.
    Бросает ValueError при weight <= 0.
    """
    total_kzt = Decimal(total_kzt)
    weight = Decimal(weight)
    usd_rate_per_kg = Decimal(usd_rate_per_kg)
    if weight <= 0:
        raise ValueError("weight must be > 0")

    q = Decimal("0.01")
    rate_per_kg = (total_kzt / weight).quantize(q, rounding=ROUND_HALF_UP)
    if usd_rate_per_kg > 0:
        exchange_rate = (total_kzt / (weight * usd_rate_per_kg)).quantize(q, rounding=ROUND_HALF_UP)
    else:
        exchange_rate = Decimal("0.00")
    return rate_per_kg, exchange_rate
