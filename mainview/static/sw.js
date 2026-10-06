/* InterCargo service worker
 * - push-уведомления
 * - офлайн-резерв для «Сессии прихода»: кэш страницы + Background Sync несохранённых данных
 */

var CACHE_NAME = 'intercargo-v2';   // v2: новый протокол сохранения сессии прихода — сбросить старые скрипты

// ==================== Push-уведомления ====================
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

// ==================== Жизненный цикл ====================
self.addEventListener('install', function () {
    self.skipWaiting();
});

self.addEventListener('activate', function (event) {
    event.waitUntil(
        caches.keys().then(function (keys) {
            return Promise.all(keys.map(function (k) {
                if (k !== CACHE_NAME) return caches.delete(k);
            }));
        }).then(function () {
            return self.clients.claim();
        })
    );
});

// ==================== Кэширование (офлайн-загрузка страницы сессии) ====================
// GET-страница сессии прихода (не save/complete/pause/resume — это POST).
function isSessionPage(url) {
    var p = url.pathname;
    return p.indexOf('/goods-arrival/session/') !== -1 &&
        p.indexOf('/save') === -1 &&
        p.indexOf('/complete') === -1 &&
        p.indexOf('/pause') === -1 &&
        p.indexOf('/resume') === -1;
}

self.addEventListener('fetch', function (event) {
    var req = event.request;
    if (req.method !== 'GET') return;

    var url;
    try {
        url = new URL(req.url);
    } catch (e) {
        return;
    }
    if (url.origin !== self.location.origin) return;

    // Страница сессии прихода — network-first с записью свежей копии в кэш.
    // Повторное открытие офлайн отдаёт последнюю закэшированную версию.
    if (isSessionPage(url)) {
        event.respondWith(
            fetch(req).then(function (resp) {
                var copy = resp.clone();
                caches.open(CACHE_NAME).then(function (c) { c.put(req, copy); });
                return resp;
            }).catch(function () {
                return caches.match(req);
            })
        );
        return;
    }

    // Статика — stale-while-revalidate: отдаём копию из кэша (работает офлайн), а свежую
    // версию тут же докачиваем в кэш к следующему открытию. Чистый cache-first держал
    // старые скрипты навсегда, если при выкате забыли поднять APP_VERSION.
    if (url.pathname.indexOf('/static/') === 0) {
        event.respondWith(
            caches.match(req).then(function (cached) {
                var network = fetch(req).then(function (resp) {
                    if (resp && resp.status === 200) {
                        var copy = resp.clone();
                        caches.open(CACHE_NAME).then(function (c) { c.put(req, copy); });
                    }
                    return resp;
                });
                if (cached) {
                    event.waitUntil(network.catch(function () {}));
                    return cached;
                }
                return network;
            })
        );
    }
});

// ==================== Background Sync: досылка несохранённых данных сессии ====================
self.addEventListener('sync', function (event) {
    if (event.tag === 'arrival-session-sync') {
        event.waitUntil(replayQueue());
    }
});

function idbOpen() {
    return new Promise(function (resolve, reject) {
        var req = indexedDB.open('arrival-sync', 1);
        req.onupgradeneeded = function () {
            req.result.createObjectStore('queue', { keyPath: 'id', autoIncrement: true });
        };
        req.onsuccess = function () { resolve(req.result); };
        req.onerror = function () { reject(req.error); };
    });
}

function idbGetAll(db) {
    return new Promise(function (resolve, reject) {
        var req = db.transaction('queue', 'readonly').objectStore('queue').getAll();
        req.onsuccess = function () { resolve(req.result || []); };
        req.onerror = function () { reject(req.error); };
    });
}

function idbDelete(db, id) {
    return new Promise(function (resolve) {
        var tx = db.transaction('queue', 'readwrite');
        tx.objectStore('queue').delete(id);
        tx.oncomplete = function () { resolve(); };
        tx.onerror = function () { resolve(); };
    });
}

// Сервер ответил окончательно — снимок либо принят, либо отклонён осознанно
// (устарел, конфликт версий, сессия закрыта): повторять бессмысленно. Сам снимок
// в любом случае лёг в журнал сессии на сервере.
var FINAL_STATUSES = [400, 403, 404, 409];

// Отправляем по самому свежему снимку на каждую сессию (каждый снимок — полное состояние).
// Снимок несёт id вкладки и порядковый номер: если вкладка уже сохранила что-то новее,
// сервер отклонит его как устаревший и не затрёт свежие строки.
// При сетевом сбое или 5xx промис отклоняется → браузер повторит sync позже.
function replayQueue() {
    return idbOpen().then(function (db) {
        return idbGetAll(db).then(function (entries) {
            if (!entries.length) return;

            var byUrl = {};
            entries.forEach(function (e) {
                var cur = byUrl[e.url];
                if (!cur || (e.seq || e.createdAt) > (cur.seq || cur.createdAt)) {
                    byUrl[e.url] = e;
                }
            });

            var tasks = Object.keys(byUrl).map(function (url) {
                var latest = byUrl[url];
                var fd = new FormData();
                fd.append('csrfmiddlewaretoken', latest.csrf);
                fd.append('items', JSON.stringify(latest.items));
                fd.append('source', 'sw');
                if (latest.client_id) fd.append('client_id', latest.client_id);
                if (latest.seq) fd.append('seq', latest.seq);
                if (latest.base_revision !== undefined && latest.base_revision !== null) {
                    fd.append('base_revision', latest.base_revision);
                }
                return fetch(url, {
                    method: 'POST',
                    body: fd,
                    credentials: 'include'
                }).then(function (resp) {
                    if (!resp || !(resp.ok || FINAL_STATUSES.indexOf(resp.status) !== -1)) {
                        throw new Error('replay failed');
                    }
                    // Снимки этой сессии отработаны — удаляем только их
                    return Promise.all(entries.filter(function (e) { return e.url === url; })
                        .map(function (e) { return idbDelete(db, e.id); }));
                });
            });

            return Promise.all(tasks);
        });
    });
}
