from django.shortcuts import render
from register.models import PickupPoint

# Create your views here.
def index(request):
    pickup_points = PickupPoint.objects.filter(is_active=True, show_in_registration=True)
    return render(request, "index.html", {'pickup_points': pickup_points})

def education(request):
    return render(request, "education.html")

def about(request):
    return render(request, "about.html")