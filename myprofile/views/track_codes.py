from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages
from django import forms
from myprofile.models import TrackCode

class TrackCodeForm(forms.ModelForm):
    class Meta:
        model = TrackCode
        fields = ['track_code', 'description']
        widgets = {
            'track_code': forms.TextInput(attrs={
                'class': 'w-full border border-gray-300 rounded px-3 py-2',
                'placeholder': 'Введите трек-код'
            }),
            'description': forms.Textarea(attrs={
                'class': 'w-full border border-gray-300 rounded px-3 py-2',
                'placeholder': 'Описание посылки',
                'rows': 3
            }),
        }

@login_required(login_url='login')
def track_codes_view(request):
    if request.method == 'POST':
        form = TrackCodeForm(request.POST)
        if form.is_valid():
            track_code_str = form.cleaned_data['track_code']
            description = form.cleaned_data['description']
            
            try:
                # Проверяем, существует ли уже такой трек-код
                existing_track = TrackCode.objects.get(track_code=track_code_str)
                
                if existing_track.owner is None:
                    # Если трек-код существует, но без владельца ("сиротский"), присваиваем его текущему пользователю
                    existing_track.owner = request.user
                    existing_track.description = description
                    # Статус НЕ меняем, оставляем тот, который был (например, shipped_cn)
                    existing_track.save()
                    messages.success(request, f"Трек-код успешно добавлен. Текущий статус: {existing_track.get_status_display()}")
                elif existing_track.owner == request.user:
                    messages.warning(request, "Этот трек-код уже добавлен в ваш список.")
                else:
                    messages.error(request, "Этот трек-код уже зарегистрирован другим пользователем.")
                    
            except TrackCode.DoesNotExist:
                # Если трек-кода нет, создаём новый со статусом 'user_added'
                track_code = form.save(commit=False)
                track_code.owner = request.user
                track_code.status = 'user_added'
                track_code.save()
                messages.success(request, "Трек-код успешно добавлен.")
            
            return redirect('track_codes')
    else:
        form = TrackCodeForm()

    track_codes = TrackCode.objects.filter(owner=request.user).order_by('-update_date')
    return render(request, 'track_codes.html', {
        'track_codes': track_codes,
        'form': form
    })

@login_required
def add_track_code_view(request):
    if request.method == 'POST':
        form = TrackCodeForm(request.POST)
        if form.is_valid():
            track_code_str = form.cleaned_data['track_code']
            description = form.cleaned_data['description']
            
            try:
                existing_track = TrackCode.objects.get(track_code=track_code_str)
                
                if existing_track.owner is None:
                    existing_track.owner = request.user
                    existing_track.description = description
                    existing_track.save()
                    messages.success(request, f"Трек-код успешно добавлен. Текущий статус: {existing_track.get_status_display()}")
                elif existing_track.owner == request.user:
                    messages.warning(request, "Этот трек-код уже добавлен в ваш список.")
                else:
                    messages.error(request, "Этот трек-код уже зарегистрирован другим пользователем.")
                    
            except TrackCode.DoesNotExist:
                track_code = form.save(commit=False)
                track_code.owner = request.user
                track_code.status = 'user_added'
                track_code.save()
                messages.success(request, "Трек-код успешно добавлен.")
                
            return redirect('track_codes')
    else:
        form = TrackCodeForm()
    return render(request, 'add_track_code.html', {'form': form})

def tracks(request):
    return render(request, "track_codes.html")