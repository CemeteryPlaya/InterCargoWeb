document.addEventListener('DOMContentLoaded', function () {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
        return;
    }

    var vapidMeta = document.querySelector('meta[name="vapid-key"]');
    if (!vapidMeta || !vapidMeta.content) {
        return;
    }
    var vapidPublicKey = vapidMeta.content;

    navigator.serviceWorker.register('/sw.js').then(function (registration) {
        return registration.pushManager.getSubscription().then(function (subscription) {
            if (subscription) {
                return subscription;
            }
            return Notification.requestPermission().then(function (permission) {
                if (permission !== 'granted') {
                    return null;
                }
                return registration.pushManager.subscribe({
                    userVisibleOnly: true,
                    applicationServerKey: urlBase64ToUint8Array(vapidPublicKey)
                });
            });
        });
    }).then(function (subscription) {
        if (!subscription) return;
        return fetch('/profile/save-subscription/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify(subscription)
        });
    }).catch(function (err) {
        console.warn('Push subscription error:', err);
    });

    function urlBase64ToUint8Array(base64String) {
        var padding = '='.repeat((4 - base64String.length % 4) % 4);
        var base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
        var rawData = atob(base64);
        var outputArray = new Uint8Array(rawData.length);
        for (var i = 0; i < rawData.length; i++) {
            outputArray[i] = rawData.charCodeAt(i);
        }
        return outputArray;
    }

    function getCookie(name) {
        var cookies = document.cookie.split('; ');
        for (var i = 0; i < cookies.length; i++) {
            if (cookies[i].startsWith(name + '=')) {
                return cookies[i].substring(name.length + 1);
            }
        }
        return '';
    }
});
