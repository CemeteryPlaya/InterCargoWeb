self.addEventListener('push', function (event) {
    var data = {};
    if (event.data) {
        data = event.data.json();
    }
    var title = data.title || 'InterCargo';
    var options = {
        body: data.body || '',
        icon: '/static/images/favicon.ico',
        data: { url: data.url || '/' }
    };
    event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', function (event) {
    event.notification.close();
    var url = event.notification.data.url || '/';
    event.waitUntil(clients.openWindow(url));
});
