# utils.py
from decimal import Decimal
from myprofile.models import CustomerDiscount

def get_user_discount(user):
    """Возвращает активную скидку (₸/кг) для пользователя."""
    discounts = CustomerDiscount.objects.filter(user=user, active=True).order_by('-created_at')

    # приоритет — разовая скидка, потом постоянная
    temp = discounts.filter(is_temporary=True).first()
    if temp:
        return Decimal(temp.amount_per_kg)
    
    const = discounts.filter(is_temporary=False).first()
    return Decimal(const.amount_per_kg) if const else Decimal("0")


def deactivate_temporary_discount(user):
    """Отключает активную разовую скидку у пользователя после её использования."""
    CustomerDiscount.objects.filter(user=user, is_temporary=True, active=True).update(active=False)