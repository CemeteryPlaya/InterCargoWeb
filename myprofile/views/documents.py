from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db.models import Sum, Count, F
from myprofile.models import TrackCode, ClientRegistry, GlobalSettings
from register.models import UserProfile
import json
from datetime import datetime
from myprofile.views.utils import get_global_price_per_kg, get_user_discount

@login_required
def print_documents_view(request):
    """
    Страница выбора параметров для печати реестра и просмотра истории.
    """
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'delete':
            registry_id = request.POST.get('registry_id')
            if registry_id:
                get_object_or_404(ClientRegistry, id=registry_id).delete()
                return redirect('print_documents')

        if action == 'print_checks':
            check_date_str = request.POST.get('check_date')
            pickup_points = request.POST.getlist('pickup_points')
            
            if check_date_str and pickup_points:
                # Получаем треки
                # Фильтруем по дате обновления (update_date) и статусу ready/delivered
                check_date = datetime.strptime(check_date_str, '%Y-%m-%d').date()
                
                tracks = TrackCode.objects.filter(
                    status__in=['ready', 'delivered'],
                    update_date=check_date,
                    owner__userprofile__pickup__in=pickup_points
                ).select_related('owner', 'owner__userprofile')
                
                # Группируем по клиентам
                clients_data = {}
                
                # Настройки цены
                default_price_per_kg = get_global_price_per_kg()
                
                for track in tracks:
                    owner = track.owner
                    if not owner:
                        continue
                        
                    username = owner.username
                    if username not in clients_data:
                        # Получаем адрес (из профиля или ПВЗ)
                        try:
                            profile = owner.userprofile
                            # Можно добавить поле адреса в профиль, пока используем название ПВЗ или пустое
                            # Для примера берем название ПВЗ
                            pickup_name = dict(UserProfile.PICKUP_CHOICES).get(profile.pickup, '')
                            address = pickup_name # Или реальный адрес если есть
                        except:
                            address = ''
                            
                        clients_data[username] = {
                            'username': username,
                            'address': address,
                            'tracks': [],
                            'total_count': 0,
                            'total_weight': 0,
                            'total_sum': 0
                        }
                    
                    # Расчет цены
                    weight = track.weight or 0
                    
                    discount_per_kg = get_user_discount(owner)
                    price_per_kg = default_price_per_kg - discount_per_kg
                        
                    price = weight * price_per_kg
                    
                    clients_data[username]['tracks'].append({
                        'track_code': track.track_code,
                        'weight': weight,
                        'price': price
                    })
                    
                    clients_data[username]['total_count'] += 1
                    clients_data[username]['total_weight'] += float(weight)
                    clients_data[username]['total_sum'] += float(price)
                
                # Сортируем клиентов
                sorted_clients = sorted(clients_data.values(), key=lambda x: x['username'])
                
                return render(request, 'client_check_pdf.html', {
                    'clients': sorted_clients,
                    'date': check_date
                })

        registry_date_str = request.POST.get('registry_date')
        pickup_points = request.POST.getlist('pickup_points')

        if registry_date_str and pickup_points:
            # Сохраняем реестр
            registry = ClientRegistry.objects.create(
                registry_date=registry_date_str,
                pickup_points=pickup_points
            )
            
            # Находим подходящие трек-коды
            # Логика: статус 'ready' или 'delivered', и дата обновления совпадает с выбранной датой
            registry_date = datetime.strptime(registry_date_str, '%Y-%m-%d').date()
            
            tracks = TrackCode.objects.filter(
                status__in=['ready', 'delivered'],
                update_date=registry_date,
                owner__userprofile__pickup__in=pickup_points
            )
            
            registry.track_codes.set(tracks)
            registry.save()

            return redirect('client_registry_pdf', registry_id=registry.id)

    # Получаем список всех ПВЗ для формы
    pickup_choices = UserProfile.PICKUP_CHOICES
    
    # История реестров
    registries = ClientRegistry.objects.all().order_by('-created_at')

    return render(request, 'print_documents.html', {
        'pickup_choices': pickup_choices,
        'registries': registries,
        'today': timezone.now().date()
    })

@login_required
def client_registry_pdf(request, registry_id):
    """
    Отображение реестра для печати.
    """
    registry = get_object_or_404(ClientRegistry, id=registry_id)
    
    # Агрегация данных
    # Группируем по ПВЗ, затем по клиенту
    
    # Получаем все треки реестра
    tracks = registry.track_codes.all().select_related('owner', 'owner__userprofile')
    
    # Глобальная цена за кг для расчета суммы (если нет индивидуальной скидки)
    default_price_per_kg = get_global_price_per_kg()
    
    # Структура данных:
    # {
    #   'pickup_code': {
    #       'name': 'Пункт выдачи ...',
    #       'clients': {
    #           'username': {
    #               'count': 5,
    #               'weight': 2.5,
    #               'sum': 5000,
    #               'tracks': [...]
    #           }
    #       },
    #       'total_count': ...,
    #       'total_weight': ...,
    #       'total_sum': ...
    #   }
    # }
    
    data = {}
    
    # Словарь названий ПВЗ
    pickup_names = dict(UserProfile.PICKUP_CHOICES)
    
    for track in tracks:
        owner = track.owner
        if not owner:
            continue
            
        try:
            profile = owner.userprofile
            pickup_code = profile.pickup
        except:
            pickup_code = 'unknown'
            
        pickup_name = pickup_names.get(pickup_code, pickup_code)
        
        if pickup_code not in data:
            data[pickup_code] = {
                'name': pickup_name,
                'clients': {},
                'total_count': 0,
                'total_weight': 0,
                'total_sum': 0
            }
            
        client_username = owner.username
        
        if client_username not in data[pickup_code]['clients']:
            data[pickup_code]['clients'][client_username] = {
                'count': 0,
                'weight': 0,
                'sum': 0
            }
            
        # Расчет веса и суммы
        weight = track.weight or 0
        
        # Расчет цены
        # Проверяем скидки пользователя
        discount_per_kg = get_user_discount(owner)
        price_per_kg = default_price_per_kg - discount_per_kg
            
        price = weight * price_per_kg
        
        # Обновляем данные клиента
        client_data = data[pickup_code]['clients'][client_username]
        client_data['count'] += 1
        client_data['weight'] += float(weight)
        client_data['sum'] += float(price)
        
        # Обновляем общие данные по ПВЗ
        data[pickup_code]['total_count'] += 1
        data[pickup_code]['total_weight'] += float(weight)
        data[pickup_code]['total_sum'] += float(price)

    # Сортировка клиентов по алфавиту внутри ПВЗ
    for pickup_code in data:
        data[pickup_code]['clients'] = dict(sorted(data[pickup_code]['clients'].items()))

    # Общие итоги по всему реестру
    all_clients_count = sum(item['total_count'] for item in data.values())
    all_weight_total = sum(item['total_weight'] for item in data.values())
    all_sum_total = sum(item['total_sum'] for item in data.values())

    return render(request, 'client_registry_pdf.html', {
        'registry': registry,
        'data': data,
        'today': timezone.now().date(),
        'all_clients_count': all_clients_count,
        'all_weight_total': all_weight_total,
        'all_sum_total': all_sum_total
    })
