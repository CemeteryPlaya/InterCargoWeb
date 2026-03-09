(function () {
    const POLL_INTERVAL = 30000; // 30 секунд
    const POLL_URL = '/profile/notifications/poll/';

    // Цвета статусов трек-кодов (соответствуют CSS-классам в track_codes.html)
    const STATUS_COLORS = {
        ready: { bg: 'bg-green-100', border: 'border-green-300' },
        user_added: { bg: 'bg-red-100', border: 'border-red-300' },
        warehouse_cn: { bg: 'bg-orange-100', border: 'border-orange-300' },
        shipped_cn: { bg: 'bg-yellow-100', border: 'border-yellow-300' },
        delivered: { bg: 'bg-purple-100', border: 'border-purple-300' },
        shipping_pp: { bg: 'bg-gray-200', border: 'border-gray-400' },
        claimed: { bg: 'bg-blue-100', border: 'border-blue-300' },
    };

    let lastUnreadCount = null;

    function updateNotificationBadge(count) {
        const badge = document.getElementById('notification-count');
        if (count > 0) {
            if (badge) {
                badge.textContent = count;
            } else {
                // Создаём badge если его нет
                const btn = document.getElementById('notification-button');
                if (btn) {
                    const span = document.createElement('span');
                    span.id = 'notification-count';
                    span.className = 'absolute top-0 right-0 inline-flex items-center justify-center px-1 text-xs font-bold leading-none text-white bg-red-600 rounded-full';
                    span.textContent = count;
                    btn.appendChild(span);
                }
            }
        } else if (badge) {
            badge.remove();
        }
    }

    function updateNotificationDropdown(notifications) {
        const list = document.querySelector('#notification-dropdown ul');
        if (!list) return;

        if (notifications.length === 0) {
            list.innerHTML = '<li class="px-4 py-2 text-sm text-gray-500">Нет уведомлений</li>';
            return;
        }

        list.innerHTML = notifications.map(function (n) {
            return '<li class="px-4 py-2 text-sm bg-gray-100">' +
                n.message +
                '<div class="text-xs text-gray-500">' + n.created_at + '</div>' +
                '</li>';
        }).join('');
    }

    function updateTrackStatuses(trackStatuses) {
        // Обновляем карточки трек-кодов на странице track_codes
        const cards = document.querySelectorAll('[data-track-id]');
        cards.forEach(function (card) {
            const trackId = card.dataset.trackId;
            const data = trackStatuses[trackId];
            if (!data) return;

            // Обновляем текст статуса
            const statusEl = card.querySelector('[data-track-status]');
            if (statusEl && statusEl.textContent !== data.status_display) {
                statusEl.textContent = data.status_display;
            }

            // Обновляем дату
            const dateEl = card.querySelector('[data-track-date]');
            if (dateEl && dateEl.textContent !== data.update_date) {
                dateEl.textContent = data.update_date;
            }

            // Обновляем цвет карточки
            const currentStatus = card.dataset.trackStatus;
            if (currentStatus !== data.status) {
                // Убираем старые цветовые классы
                const oldColors = STATUS_COLORS[currentStatus];
                if (oldColors) {
                    card.classList.remove(oldColors.bg, oldColors.border);
                }
                // Добавляем новые
                const newColors = STATUS_COLORS[data.status];
                if (newColors) {
                    card.classList.add(newColors.bg, newColors.border);
                }
                card.dataset.trackStatus = data.status;
            }
        });
    }

    function poll() {
        fetch(POLL_URL)
            .then(function (r) {
                if (!r.ok) return null;
                return r.json();
            })
            .then(function (data) {
                if (!data) return;

                // Обновляем badge и dropdown уведомлений
                updateNotificationBadge(data.unread_count);
                updateNotificationDropdown(data.notifications);

                // Обновляем статусы трек-кодов (если на странице есть карточки)
                if (data.track_statuses) {
                    updateTrackStatuses(data.track_statuses);
                }

                // Уведомление о новых уведомлениях (звуковой/визуальный сигнал)
                if (lastUnreadCount !== null && data.unread_count > lastUnreadCount) {
                    // Мигание заголовка
                    const originalTitle = document.title;
                    let blink = true;
                    const blinkInterval = setInterval(function () {
                        document.title = blink ? 'Новое уведомление!' : originalTitle;
                        blink = !blink;
                    }, 1000);
                    setTimeout(function () {
                        clearInterval(blinkInterval);
                        document.title = originalTitle;
                    }, 5000);
                }
                lastUnreadCount = data.unread_count;
            })
            .catch(function () {
                // Тихо игнорируем ошибки сети
            });
    }

    // Запускаем polling только для авторизованных пользователей
    document.addEventListener('DOMContentLoaded', function () {
        const notifBtn = document.getElementById('notification-button');
        if (!notifBtn) return; // Не авторизован

        // Первый poll через 5 секунд после загрузки
        setTimeout(poll, 5000);
        setInterval(poll, POLL_INTERVAL);
    });
})();
