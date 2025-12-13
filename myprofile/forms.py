from django import forms
from .models import TrackCode

class MassUpdateTrackForm(forms.Form):
    status = forms.ChoiceField(
        choices=TrackCode.STATUS_CHOICES,
        label="Новый статус",
        required=True
    )
    
    PAYMENT_STATUS_CHOICES = [
        ('no_change', 'Не менять'),
        ('paid', 'Отметить как ОПЛАЧЕНО'),
        ('not_paid', 'Отметить как НЕ ОПЛАЧЕНО'),
    ]
    
    payment_status = forms.ChoiceField(
        choices=PAYMENT_STATUS_CHOICES,
        label="Статус оплаты (для связанных чеков)",
        required=True,
        initial='no_change'
    )
