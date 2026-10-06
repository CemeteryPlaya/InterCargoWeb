document.addEventListener('DOMContentLoaded', function () {
    var config = SESSION_CONFIG;

    // Метод F: регистрируем service worker (офлайн-кэш страницы + Background Sync).
    // Делаем безусловно — скрипты push-уведомлений сюда не подключены.
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/sw.js').catch(function () {});
    }

    var tableBody = document.getElementById('tracks_table_body');
    var addRowBtn = document.getElementById('add_row_btn');
    var toggleBtn = document.getElementById('form_toggle_btn');
    var tableView = document.getElementById('table_view');
    var textView = document.getElementById('text_view');
    var rowCounter = document.getElementById('row_counter');
    var saveStatus = document.getElementById('save-status');
    var emptyCellsWarning = document.getElementById('empty_cells_warning');
    var emptyCellsCount = document.getElementById('empty_cells_count');
    var suspiciousWarning = document.getElementById('suspicious_cells_warning');
    var suspiciousCount = document.getElementById('suspicious_cells_count');
    var suspiciousPrevBtn = document.getElementById('suspicious_prev_btn');
    var suspiciousNextBtn = document.getElementById('suspicious_next_btn');
    var suspiciousInputs = [];
    var suspiciousCursor = -1;

    var textTracks = document.getElementById('text_tracks');
    var textOwners = document.getElementById('text_owners');
    var textWeights = document.getElementById('text_weights');
    var textCountTracks = document.getElementById('text_count_tracks');
    var textCountOwners = document.getElementById('text_count_owners');
    var textCountWeights = document.getElementById('text_count_weights');

    var isTableView = true;
    var saveTimer = null;
    var isSaving = false;
    var rowNum = 0;

    // ==================== Резервное сохранение (методы A/B/E/F) ====================
    // Изменения считаем счётчиком: сохранение подтверждает «до какого изменения»
    // дошло, поэтому правки, сделанные пока запрос в пути, не теряются из виду.
    var changeSeq = 0;
    var ackedSeq = 0;
    var firstUnsavedAt = null;          // когда появились несохранённые на сервере изменения
    var lastServerSyncAt = Date.now();  // при загрузке форма = данные сервера
    var serverCount = (config.initialItems || []).length;
    var revision = config.revision || 0;  // версия строк на сервере, на которой основана форма
    var hardReason = null;              // почему сохранение сейчас невозможно (см. SAVE_REASONS)
    var readOnly = false;               // сессию редактирует другое устройство/вкладка
    var decisionPending = false;        // открыто окно выбора — ввод заблокирован
    var saveQueued = false;
    var lastConflict = null;
    var allowUnload = false;            // намеренный уход (submit формы) — не предупреждать
    var DRAFT_KEY = 'arrival_session_draft_' + config.sessionId;
    var DRAFT_TTL = 48 * 3600 * 1000;   // localStorage-черновик живёт 48 ч (как ACTIVE_HOURS_LIMIT)

    function isDirty() { return changeSeq > ackedSeq; }

    function genId() {
        if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
        return 'id-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
    }

    // Id вкладки: переживает перезагрузку страницы (sessionStorage), у каждой вкладки свой.
    // Сервер по нему отличает «мой более поздний снимок» от «чужого со старой версией».
    var TAB_ID = (function () {
        try {
            var id = sessionStorage.getItem('arrival_tab_id');
            if (!id) { id = genId(); sessionStorage.setItem('arrival_tab_id', id); }
            return id;
        } catch (e) { return genId(); }
    })();

    // Порядковый номер снимка этой вкладки: монотонно растёт и после перезагрузки
    var lastSeqSent = 0;
    function nextSeq() {
        lastSeqSent = Math.max(Date.now(), lastSeqSent + 1);
        return lastSeqSent;
    }

    // Свежий CSRF-токен из cookie: после повторного входа токен в странице устаревает,
    // и без этого все сохранения получали бы 403 до перезагрузки
    function csrfToken() {
        var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return m ? decodeURIComponent(m[1]) : config.csrfToken;
    }

    // ==================== Состояние соединения ====================
    var connectionState = {
        failCount: 0,
        isLost: false,
        retryTimer: null,
        retryInterval: 5000,  // начальный интервал повтора (мс)
        maxRetryInterval: 60000,
        countdownTimer: null
    };

    var lostBanner = document.getElementById('connection-lost-banner');
    var restoredBanner = document.getElementById('connection-restored-banner');
    var reconnectBtn = document.getElementById('reconnect-btn');
    var reconnectCountdown = document.getElementById('reconnect-countdown');

    function showConnectionLost() {
        if (connectionState.isLost) return;
        connectionState.isLost = true;
        lostBanner.classList.remove('hidden');
        restoredBanner.classList.add('hidden');
        scheduleAutoRetry();
    }

    function showConnectionRestored() {
        if (!connectionState.isLost) return;
        connectionState.isLost = false;
        connectionState.failCount = 0;
        connectionState.retryInterval = 5000;
        clearAutoRetry();
        lostBanner.classList.add('hidden');
        restoredBanner.classList.remove('hidden');
        setTimeout(function () {
            restoredBanner.classList.add('hidden');
        }, 5000);
    }

    function scheduleAutoRetry() {
        clearAutoRetry();
        var seconds = Math.round(connectionState.retryInterval / 1000);
        var remaining = seconds;
        reconnectCountdown.classList.remove('hidden');
        reconnectCountdown.textContent = 'Повтор через ' + remaining + ' сек.';

        connectionState.countdownTimer = setInterval(function () {
            remaining--;
            if (remaining > 0) {
                reconnectCountdown.textContent = 'Повтор через ' + remaining + ' сек.';
            } else {
                reconnectCountdown.textContent = '';
            }
        }, 1000);

        connectionState.retryTimer = setTimeout(function () {
            reconnectCountdown.classList.add('hidden');
            clearInterval(connectionState.countdownTimer);
            doSave();
        }, connectionState.retryInterval);

        // Экспоненциальный backoff
        connectionState.retryInterval = Math.min(
            connectionState.retryInterval * 2,
            connectionState.maxRetryInterval
        );
    }

    function clearAutoRetry() {
        if (connectionState.retryTimer) {
            clearTimeout(connectionState.retryTimer);
            connectionState.retryTimer = null;
        }
        if (connectionState.countdownTimer) {
            clearInterval(connectionState.countdownTimer);
            connectionState.countdownTimer = null;
        }
        reconnectCountdown.classList.add('hidden');
    }

    // Глобальная функция для кнопки «Переподключиться»
    window.manualReconnect = function () {
        clearAutoRetry();
        reconnectBtn.disabled = true;
        reconnectBtn.innerHTML = '<i class="ri-loader-4-line mr-1 animate-spin"></i> Подключение...';
        doSave(function () {
            reconnectBtn.disabled = false;
            reconnectBtn.innerHTML = '<i class="ri-refresh-line mr-1"></i> Переподключиться';
        });
    };

    // ==================== Метод A: черновик в localStorage ====================
    function writeDraft() {
        try {
            localStorage.setItem(DRAFT_KEY, JSON.stringify({
                sessionId: config.sessionId,
                savedAt: Date.now(),
                serverSyncedAt: lastServerSyncAt,
                revision: revision,      // на какой версии сервера основана копия
                dirty: isDirty(),        // false — копия уже целиком лежит на сервере
                view: isTableView ? 'table' : 'text',
                items: collectItems()
            }));
        } catch (e) { /* localStorage недоступен/переполнен — не критично */ }
    }

    function readDraft() {
        try {
            var raw = localStorage.getItem(DRAFT_KEY);
            return raw ? JSON.parse(raw) : null;
        } catch (e) { return null; }
    }

    function deleteDraft() {
        try { localStorage.removeItem(DRAFT_KEY); } catch (e) { /* ignore */ }
    }

    // Нормализуем вес численно: "1.500" и "1,5" → "1.5" (иначе ложные срабатывания)
    function normWeight(w) {
        var s = String(w == null ? '' : w).trim().replace(',', '.');
        if (s === '') return '';
        var n = parseFloat(s);
        return isNaN(n) ? s : String(n);
    }

    // Сигнатура строк — для сравнения двух наборов данных без учёта пустых строк
    function itemsSignature(items) {
        if (!items || !items.length) return '';
        return items.map(function (i) {
            return (i.track_code || '').trim() + '|' +
                   (i.owner_name || '').trim() + '|' +
                   normWeight(i.weight);
        }).filter(function (s) { return s !== '||'; }).join('\n');
    }

    function itemsDiffer(a, b) {
        return itemsSignature(a) !== itemsSignature(b);
    }

    // Лучший из доступных черновиков: localStorage и серверный (config.draft)
    function getBestDraft() {
        var candidates = [];
        var local = readDraft();
        // Копия, целиком сохранённая на сервере, — не «несохранённая»: она уже есть в журнале
        // сессии (например, состояние до восстановления из истории)
        var alreadySynced = local && local.dirty === false;
        if (local && local.items && local.items.length && !alreadySynced) {
            candidates.push({ savedAt: local.savedAt || 0, items: local.items, source: 'local' });
        }
        var server = config.draft;
        if (server && server.items && server.items.length && server.savedAt) {
            candidates.push({ savedAt: server.savedAt, items: server.items, source: 'server' });
        }
        if (!candidates.length) return null;
        candidates.sort(function (a, b) { return b.savedAt - a.savedAt; });
        return candidates[0];
    }

    // Загрузить набор строк в форму (восстановление / импорт)
    function restoreItemsIntoForm(items) {
        if (isTableView) {
            tableBody.innerHTML = '';
            rowNum = 0;
            if (items.length) {
                items.forEach(function (item) { addRow(item); });
                validateAllRows();
            } else {
                addRow();
            }
        } else {
            textTracks.value = items.map(function (i) { return i.track_code || ''; }).join('\n');
            textOwners.value = items.map(function (i) { return i.owner_name || ''; }).join('\n');
            textWeights.value = items.map(function (i) { return String(i.weight == null ? '' : i.weight); }).join('\n');
            updateTextCounters();
        }
        scheduleSave();
    }

    function countRows(items) {
        return (items || []).filter(function (i) {
            return (i.track_code || i.owner_name || i.weight);
        }).length;
    }

    function fmtTime(ts) {
        return ts ? new Date(ts).toLocaleString('ru-RU') : '—';
    }

    // Объединение двух наборов строк по трек-коду: порядок и строки первого набора,
    // недостающие строки второго — в конец; у совпавших непустые значения второго.
    // dropTrackless — не дописывать строки второго набора без трек-кода (остатки
    // очищенной колонки при возврате удалённых строк)
    function mergeItems(base, extra, dropTrackless) {
        var out = [], byCode = {};
        function norm(it) {
            return {
                track_code: String(it.track_code || '').trim(),
                owner_name: String(it.owner_name || '').trim(),
                weight: it.weight == null ? '' : String(it.weight).trim()
            };
        }
        (base || []).forEach(function (it) {
            var row = norm(it);
            out.push(row);
            if (row.track_code) byCode[row.track_code] = row;
        });
        (extra || []).forEach(function (it) {
            var row = norm(it);
            var existing = row.track_code && byCode[row.track_code];
            if (existing) {
                if (row.owner_name) existing.owner_name = row.owner_name;
                if (row.weight) existing.weight = row.weight;
            } else if (row.track_code || (!dropTrackless && (row.owner_name || row.weight))) {
                out.push(row);
                if (row.track_code) byCode[row.track_code] = row;
            }
        });
        return out;
    }

    // ==================== Окно выбора (блокирует ввод до решения) ====================
    var decisionModal = document.getElementById('decision-modal');
    var decisionTitle = document.getElementById('decision-title');
    var decisionBody = document.getElementById('decision-body');
    var decisionButtons = document.getElementById('decision-buttons');

    function setFormLocked(locked) {
        var root = document.getElementById('session-editor');
        if (!root) return;
        root.querySelectorAll('input, textarea, button').forEach(function (el) {
            if (el.closest('#complete_form') || el.dataset.keepEnabled) return;
            el.disabled = locked;
        });
        if (locked && document.activeElement && document.activeElement.blur) {
            document.activeElement.blur();
        }
    }

    function para(text, cls) {
        var p = document.createElement('p');
        p.textContent = text;
        if (cls) p.className = cls;
        return p;
    }

    // buttons: [{label, primary, onClick}] — onClick вызывается после закрытия окна
    function openDecision(title, nodes, buttons) {
        decisionPending = true;
        setFormLocked(true);
        decisionTitle.textContent = title;
        decisionBody.innerHTML = '';
        nodes.forEach(function (n) { if (n) decisionBody.appendChild(n); });
        decisionButtons.innerHTML = '';
        buttons.forEach(function (b) {
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = b.primary
                ? 'bg-primary text-white px-4 py-2 rounded-lg hover:bg-red-600 transition text-sm font-medium'
                : 'border border-gray-300 text-gray-700 px-4 py-2 rounded-lg hover:bg-gray-50 transition text-sm font-medium';
            btn.textContent = b.label;
            btn.addEventListener('click', function () {
                closeDecision();
                b.onClick();
            });
            decisionButtons.appendChild(btn);
        });
        decisionModal.classList.remove('hidden');
    }

    function closeDecision() {
        decisionModal.classList.add('hidden');
        decisionPending = false;
        setFormLocked(readOnly);
    }

    // Загрузить в форму строки и сразу сохранить их как новую версию
    function replaceFormWith(items, reason) {
        ringPush(collectItems(), reason || 'before-replace');
        hardReason = null;
        restoreItemsIntoForm(items);
        updateSaveAlert();
    }

    // После сбоя: копия в браузере/на сервере отличается от строк сессии.
    // Ввод заблокирован, пока оператор не выберет — иначе первое же нажатие
    // перезаписало бы копию устаревшими данными (так терялся день работы).
    function offerRestore(draft) {
        var srv = config.initialItems || [];
        var src = draft.source === 'server' ? 'на сервере (черновик)' : 'в этом браузере';
        var nodes = [
            para('Копия от ' + fmtTime(draft.savedAt) + ' — ' + countRows(draft.items) + ' строк, сохранена ' + src +
                 '. В сессии на сервере сейчас ' + countRows(srv) + ' строк.', 'font-medium'),
            para('Так бывает после отключения света или интернета. Выберите, с чем продолжить — ' +
                 'до выбора ввод заблокирован, чтобы копия не затёрлась.'),
            ringListNode()
        ];
        openDecision('Найдена несохранённая копия данных', nodes, [
            { label: 'Восстановить копию', primary: true, onClick: function () {
                replaceFormWith(draft.items || [], 'before-restore');
            } },
            { label: 'Объединить с сервером', onClick: function () {
                replaceFormWith(mergeItems(srv, draft.items || []), 'before-merge');
            } },
            { label: 'Оставить данные сервера', onClick: function () {
                ringPush(draft.items || [], 'dismissed');   // копия остаётся в журнале устройства
                writeDraft();   // черновик = данные сервера, иначе окно вернётся при каждом открытии
            } },
            { label: 'История сохранений', onClick: function () {
                window.open(config.historyUrl, '_blank');
                offerRestore(draft);
            } }
        ]);
    }

    function openConflictDialog(serverItemsList, serverRevision) {
        lastConflict = { items: serverItemsList || [], revision: serverRevision };
        var local = collectItems();
        openDecision('Строки сессии изменены в другом месте', [
            para('Пока вы работали, сессию сохранили с другого устройства, из другой вкладки или ' +
                 'восстановили из истории. На сервере ' + countRows(lastConflict.items) +
                 ' строк, у вас — ' + countRows(local) + '.', 'font-medium'),
            para('«Объединить» сохранит строки и оттуда, и отсюда. Ваша текущая версия в любом случае ' +
                 'остаётся в журнале этого устройства.')
        ], [
            { label: 'Объединить (рекомендуется)', primary: true, onClick: function () {
                revision = lastConflict.revision;
                replaceFormWith(mergeItems(lastConflict.items, local), 'conflict-local');
            } },
            { label: 'Взять версию сервера', onClick: function () {
                revision = lastConflict.revision;
                replaceFormWith(lastConflict.items, 'conflict-local');
            } },
            { label: 'Оставить мою', onClick: function () {
                revision = lastConflict.revision;
                hardReason = null;
                doSave();
            } }
        ]);
    }

    function openShrinkDialog(d) {
        lastConflict = { items: d.server_items || [], revision: d.server_revision, shrink: d };
        var removed = d.server_count - d.new_count;
        openDecision('Сохранение удалит ' + removed + ' строк', [
            para('На сервере ' + d.server_count + ' строк, после сохранения останется ' + d.new_count + '.', 'font-medium'),
            para('Если вы удаляли строки сами — подтвердите. Если нет (например, после сбоя страница ' +
                 'открылась со старыми данными) — верните их.')
        ], [
            { label: 'Вернуть удалённые строки', primary: true, onClick: function () {
                revision = lastConflict.revision;
                replaceFormWith(mergeItems(lastConflict.items, collectItems(), true), 'shrink-local');
            } },
            { label: 'Да, удалить', onClick: function () {
                hardReason = null;
                doSave(null, { confirmShrink: true });
            } }
        ]);
    }

    // ==================== Метод G: журнал копий на устройстве (IndexedDB) ====================
    // Последние 20 копий сессии; пишутся раз в 30 с и перед любой заменой данных формы.
    var RING_SIZE = 20;
    var RING_INTERVAL = 30000;
    var RING_MAX_AGE = 7 * 24 * 3600 * 1000;
    var lastRingAt = 0;
    var lastRingSig = '';

    function backupDb() {
        return new Promise(function (resolve, reject) {
            var req = indexedDB.open('arrival-backup', 1);
            req.onupgradeneeded = function () {
                var store = req.result.createObjectStore('snaps', { keyPath: 'id', autoIncrement: true });
                store.createIndex('session', 'sessionId');
            };
            req.onsuccess = function () { resolve(req.result); };
            req.onerror = function () { reject(req.error); };
        });
    }

    function ringPush(items, reason) {
        if (!('indexedDB' in window) || !items || !countRows(items)) return;
        var sig = itemsSignature(items);
        if (sig === lastRingSig) return;
        lastRingSig = sig;
        lastRingAt = Date.now();
        backupDb().then(function (db) {
            var tx = db.transaction('snaps', 'readwrite');
            var store = tx.objectStore('snaps');
            store.add({ sessionId: config.sessionId, savedAt: Date.now(), reason: reason, items: items });
            var keysReq = store.index('session').getAllKeys(IDBKeyRange.only(config.sessionId));
            keysReq.onsuccess = function () {
                var keys = keysReq.result || [];
                keys.slice(0, Math.max(0, keys.length - RING_SIZE)).forEach(function (k) { store.delete(k); });
            };
            tx.oncomplete = function () { db.close(); };
        }).catch(function () { /* IndexedDB недоступен — остаются localStorage и сервер */ });
    }

    function ringMaybePush() {
        if (Date.now() - lastRingAt >= RING_INTERVAL) ringPush(collectItems(), 'auto');
    }

    function ringList() {
        if (!('indexedDB' in window)) return Promise.resolve([]);
        return backupDb().then(function (db) {
            return new Promise(function (resolve) {
                var req = db.transaction('snaps', 'readonly').objectStore('snaps')
                    .index('session').getAll(IDBKeyRange.only(config.sessionId));
                req.onsuccess = function () {
                    db.close();
                    resolve((req.result || []).sort(function (a, b) { return b.savedAt - a.savedAt; }));
                };
                req.onerror = function () { db.close(); resolve([]); };
            });
        }).catch(function () { return []; });
    }

    function ringCleanup() {
        if (!('indexedDB' in window)) return;
        backupDb().then(function (db) {
            var tx = db.transaction('snaps', 'readwrite');
            var req = tx.objectStore('snaps').openCursor();
            req.onsuccess = function () {
                var cur = req.result;
                if (!cur) return;
                if (Date.now() - (cur.value.savedAt || 0) > RING_MAX_AGE) cur.delete();
                cur.continue();
            };
            tx.oncomplete = function () { db.close(); };
        }).catch(function () {});
    }

    // Список копий устройства для окна восстановления (подгружается асинхронно)
    function ringListNode() {
        var wrap = document.createElement('div');
        wrap.className = 'mt-3';
        ringList().then(function (entries) {
            if (!entries.length) return;
            var details = document.createElement('details');
            details.className = 'border border-gray-200 rounded-lg p-3';
            var summary = document.createElement('summary');
            summary.className = 'cursor-pointer text-sm font-medium text-gray-700';
            summary.textContent = 'Другие копии на этом устройстве (' + entries.length + ')';
            details.appendChild(summary);
            entries.forEach(function (e) {
                var row = document.createElement('div');
                row.className = 'flex items-center justify-between gap-3 py-1 border-t border-gray-100 mt-1';
                row.appendChild(para(fmtTime(e.savedAt) + ' — ' + countRows(e.items) + ' строк', 'text-sm'));
                var btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'text-sm text-blue-600 hover:underline';
                btn.textContent = 'Восстановить эту';
                btn.addEventListener('click', function () {
                    closeDecision();
                    replaceFormWith(e.items, 'before-ring-restore');
                });
                row.appendChild(btn);
                details.appendChild(row);
            });
            wrap.appendChild(details);
        });
        return wrap;
    }

    // ==================== Метод B: финальная досылка через sendBeacon ====================
    function beaconSave() {
        if (!isDirty() || !config.canEdit || readOnly || decisionPending || !navigator.sendBeacon) return;
        try {
            // form-encoded: sendBeacon не умеет ставить заголовки, CSRF идёт полем
            var fd = new FormData();
            fd.append('csrfmiddlewaretoken', csrfToken());
            fd.append('items', JSON.stringify(collectItems()));
            fd.append('base_revision', revision);
            fd.append('client_id', TAB_ID);
            fd.append('seq', nextSeq());
            fd.append('source', 'beacon');
            navigator.sendBeacon(config.saveUrl, fd);
        } catch (e) { /* ignore */ }
    }

    // Освободить редактирование при уходе со страницы — другое устройство не ждёт 60 с
    function beaconRelease() {
        if (!config.canEdit || readOnly || !navigator.sendBeacon) return;
        try {
            var fd = new FormData();
            fd.append('csrfmiddlewaretoken', csrfToken());
            fd.append('client_id', TAB_ID);
            fd.append('release', '1');
            navigator.sendBeacon(config.heartbeatUrl, fd);
        } catch (e) { /* ignore */ }
    }

    // ==================== Метод E: экспорт / импорт резервной копии ====================
    function csvCell(v) {
        v = (v == null ? '' : String(v));
        if (/[",\r\n]/.test(v)) return '"' + v.replace(/"/g, '""') + '"';
        return v;
    }

    function exportBackup() {
        var items = collectItems();
        var lines = ['track_code,owner_name,weight'];
        items.forEach(function (it) {
            lines.push(csvCell(it.track_code) + ',' + csvCell(it.owner_name) + ',' + csvCell(it.weight));
        });
        var stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
        var blob = new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'session_' + config.sessionId + '_backup_' + stamp + '.csv';
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
    }

    function parseCsvLine(line) {
        var out = [], cur = '', inQ = false;
        for (var i = 0; i < line.length; i++) {
            var ch = line[i];
            if (inQ) {
                if (ch === '"') {
                    if (line[i + 1] === '"') { cur += '"'; i++; }
                    else inQ = false;
                } else { cur += ch; }
            } else {
                if (ch === '"') inQ = true;
                else if (ch === ',') { out.push(cur); cur = ''; }
                else cur += ch;
            }
        }
        out.push(cur);
        return out;
    }

    function parseBackupText(text) {
        text = String(text || '').replace(/^﻿/, '').trim();
        if (!text) return [];
        // JSON-формат
        if (text.charAt(0) === '[' || text.charAt(0) === '{') {
            try {
                var j = JSON.parse(text);
                var arr = Array.isArray(j) ? j : (j.items || []);
                return arr.map(function (i) {
                    return {
                        track_code: i.track_code || '',
                        owner_name: i.owner_name || '',
                        weight: i.weight == null ? '' : i.weight
                    };
                });
            } catch (e) { return []; }
        }
        // CSV-формат
        var lines = text.split(/\r?\n/);
        var start = (lines[0] && /track/i.test(lines[0])) ? 1 : 0;  // пропускаем заголовок
        var items = [];
        for (var k = start; k < lines.length; k++) {
            if (!lines[k].trim()) continue;
            var c = parseCsvLine(lines[k]);
            items.push({
                track_code: (c[0] || '').trim(),
                owner_name: (c[1] || '').trim(),
                weight: (c[2] || '').trim()
            });
        }
        return items;
    }

    function importBackup(file) {
        var reader = new FileReader();
        reader.onload = function () {
            var items = parseBackupText(reader.result);
            if (!items.length) {
                alert('Не удалось прочитать файл или он пуст.');
                return;
            }
            if (!confirm('Загрузить ' + items.length + ' строк из файла? Текущие данные таблицы будут заменены.')) return;
            replaceFormWith(items, 'before-import');
        };
        reader.onerror = function () { alert('Ошибка чтения файла.'); };
        reader.readAsText(file);
    }

    // ==================== Метод F: очередь Background Sync (IndexedDB) ====================
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

    // Неудавшееся сохранение — в очередь: service worker дошлёт его сам, даже если
    // вкладку закроют. Снимок несёт id вкладки и порядковый номер — сервер отбросит
    // его, если к тому времени уже сохранено что-то новее.
    function queueForBackgroundSync(items, body) {
        if (!('indexedDB' in window) || !items) return;
        idbOpen().then(function (db) {
            var tx = db.transaction('queue', 'readwrite');
            tx.objectStore('queue').add({
                url: config.saveUrl,
                csrf: csrfToken(),
                items: items,
                base_revision: body.base_revision,
                client_id: body.client_id,
                seq: body.seq,
                createdAt: Date.now()
            });
            tx.oncomplete = function () {
                db.close();
                if ('serviceWorker' in navigator && 'SyncManager' in window) {
                    navigator.serviceWorker.ready.then(function (reg) {
                        return reg.sync.register('arrival-session-sync');
                    }).catch(function () { /* Background Sync недоступен — fallback на метод C */ });
                }
            };
        }).catch(function () { /* ignore */ });
    }

    // Успешное сохранение делает очередь этой сессии ненужной — чистим, чтобы
    // старый снимок не досылался поверх свежих данных
    function clearQueuedSaves() {
        if (!('indexedDB' in window)) return;
        idbOpen().then(function (db) {
            var tx = db.transaction('queue', 'readwrite');
            var req = tx.objectStore('queue').openCursor();
            req.onsuccess = function () {
                var cur = req.result;
                if (!cur) return;
                if (cur.value.url === config.saveUrl) cur.delete();
                cur.continue();
            };
            tx.oncomplete = function () { db.close(); };
        }).catch(function () { /* ignore */ });
    }

    // ==================== Автосохранение ====================
    function scheduleSave() {
        if (readOnly || decisionPending) return;
        if (!isDirty()) firstUnsavedAt = Date.now();
        changeSeq++;
        writeDraft();      // метод A: синхронная локальная копия при каждом изменении
        ringMaybePush();   // метод G: журнал копий устройства раз в 30 с
        if (saveTimer) clearTimeout(saveTimer);
        saveTimer = setTimeout(doSave, 2000);
    }

    function setStatus(text, cls) {
        if (!saveStatus) return;
        saveStatus.textContent = text;
        saveStatus.className = 'text-sm ' + cls;
    }

    // Ответ сервера → {status, data, kind}: kind = json | auth (страница входа) | server
    function readResponse(r) {
        var ct = r.headers.get('Content-Type') || '';
        if (ct.indexOf('application/json') === -1) {
            var kind = (r.redirected || r.status === 403) ? 'auth' : 'server';
            return { status: r.status, data: null, kind: kind };
        }
        return r.json().then(
            function (data) { return { status: r.status, data: data, kind: 'json' }; },
            function () { return { status: r.status, data: null, kind: 'server' }; }
        );
    }

    function saveBody(items, extra) {
        var body = { items: items, base_revision: revision, client_id: TAB_ID, seq: nextSeq(), source: 'fetch' };
        for (var k in (extra || {})) body[k] = extra[k];
        return body;
    }

    function doSave(callback, opts) {
        opts = opts || {};
        if (readOnly || decisionPending) {
            if (callback) callback();
            return;
        }
        if (isSaving) {
            saveQueued = true;
            if (callback) callback();
            return;
        }
        isSaving = true;
        if (!opts.periodic) setStatus('Сохранение...', 'text-yellow-600');

        var seqAtSend = changeSeq;
        var items = collectItems();
        var extra = {};
        if (opts.confirmShrink) extra.confirm_shrink = true;
        if (opts.periodic) extra.periodic = true;
        var body = saveBody(items, extra);

        fetch(config.saveUrl, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken()
            },
            body: JSON.stringify(body)
        })
        .then(readResponse)
        .then(function (res) { handleSaveResult(res, items, body, seqAtSend); })
        .catch(function () { onSaveFailed('offline', items, body); })
        .finally(function () {
            isSaving = false;
            updateSaveAlert();
            if (callback) callback();
            if (saveQueued) {
                saveQueued = false;
                if (isDirty()) doSave();
            }
        });
    }

    function markSaved(seqAtSend) {
        ackedSeq = Math.max(ackedSeq, seqAtSend);
        firstUnsavedAt = isDirty() ? Date.now() : null;
        lastServerSyncAt = Date.now();
        hardReason = null;
        connectionState.failCount = 0;
        writeDraft();          // обновляем serverSyncedAt в локальной копии
        clearQueuedSaves();
        if (connectionState.isLost) showConnectionRestored();
    }

    function handleSaveResult(res, items, body, seqAtSend) {
        var d = res.data || {};
        if (res.kind === 'json' && res.status === 200 && d.success) {
            revision = d.revision;
            serverCount = d.count;
            markSaved(seqAtSend);
            setStatus('Сохранено (' + d.count + ' строк)' +
                      (body.periodic ? ' · сверено ' + new Date().toLocaleTimeString('ru-RU') : ''),
                      'text-green-600');
            if (!d.unchanged) {
                if (d.occupied && d.occupied.length > 0) showOccupiedWarning(d.occupied);
                else hideOccupiedWarning();
                if (d.invalid_chars && d.invalid_chars.length > 0) showInvalidCharsWarning(d.invalid_chars);
                else hideInvalidCharsWarning();
            }
            return;
        }
        if (res.kind === 'json' && res.status === 409) {
            if (d.stale) {
                // Уже применён более поздний снимок этой же вкладки (sendBeacon обогнал запрос)
                revision = Math.max(revision, d.revision);
                markSaved(seqAtSend);
                setStatus('Сохранено', 'text-green-600');
            } else if (d.conflict) {
                hardReason = 'conflict';
                setStatus('Конфликт версий', 'text-red-600');
                openConflictDialog(d.server_items, d.server_revision);
            } else if (d.shrink) {
                hardReason = 'shrink';
                setStatus('Нужно подтверждение', 'text-red-600');
                openShrinkDialog(d);
            } else if (d.locked) {
                enterReadOnly(d.editor_name, false);
            } else if (d.session_status) {
                hardReason = 'inactive';
                setStatus('Сессия не активна', 'text-red-600');
            } else {
                setStatus('Повтор сохранения...', 'text-yellow-600');
                setTimeout(function () { doSave(); }, 3000);
            }
            return;
        }
        if (res.kind === 'auth') {
            hardReason = 'auth';
            setStatus('Вход истёк / нет доступа', 'text-red-600');
            return;
        }
        onSaveFailed('server', items, body);
    }

    function onSaveFailed(reason, items, body) {
        hardReason = reason;
        connectionState.failCount++;
        setStatus(reason === 'offline' ? 'Ошибка связи' : 'Ошибка сервера', 'text-red-600');
        // Метод F: ставим неудавшееся сохранение в очередь Background Sync
        // (повторное сохранение без изменений в очередь не ставим — нечего досылать)
        if (!body.periodic) queueForBackgroundSync(items, body);
        if (connectionState.failCount >= 2) {
            showConnectionLost();
        }
    }

    // ==================== Плашка «данные не сохраняются» ====================
    var saveAlert = document.getElementById('save-alert');
    var saveAlertTitle = document.getElementById('save-alert-title');
    var saveAlertDetail = document.getElementById('save-alert-detail');
    var saveAlertAction = document.getElementById('save-alert-action');

    var SAVE_REASONS = {
        offline: { title: 'Нет связи с сервером',
                   text: 'Данные сохраняются только в этом браузере и уйдут на сервер, когда связь вернётся.',
                   action: 'Повторить сейчас' },
        server: { title: 'Сервер не принимает сохранение',
                  text: 'Данные сохраняются в этом браузере. Если ошибка не проходит — сообщите администратору.',
                  action: 'Повторить сейчас' },
        pending: { title: 'Изменения ещё не сохранены на сервере',
                   text: 'Сохранение задерживается.',
                   action: 'Сохранить сейчас' },
        inactive: { title: 'Сессия не активна — строки не попадают в сессию',
                    text: 'Сессия на паузе или истёк срок. Присланные данные сохранены в истории. Возобновите сессию.',
                    action: 'Возобновить сессию' },
        conflict: { title: 'Строки сессии изменены в другом месте',
                    text: 'Выберите, как объединить данные.',
                    action: 'Выбрать' },
        shrink: { title: 'Сохранение удалит много строк',
                  text: 'Подтвердите удаление или верните строки.',
                  action: 'Выбрать' },
        auth: { title: 'Вход истёк или нет доступа',
                text: 'Войдите заново в соседней вкладке (эту не закрывайте), затем нажмите «Повторить».',
                action: 'Повторить' }
    };

    function fmtDuration(ms) {
        var min = Math.floor(ms / 60000);
        return min < 1 ? 'меньше минуты' : (min + ' мин');
    }

    function updateSaveAlert() {
        if (!saveAlert || !config.canEdit || readOnly) {
            if (saveAlert) saveAlert.classList.add('hidden');
            return;
        }
        var unsavedMs = (isDirty() && firstUnsavedAt) ? Date.now() - firstUnsavedAt : 0;
        var hard = hardReason && hardReason !== 'offline' && hardReason !== 'server';
        if (!hard && unsavedMs <= 60000) {
            saveAlert.classList.add('hidden');
            return;
        }
        var key = hardReason || 'pending';
        var r = SAVE_REASONS[key] || SAVE_REASONS.pending;
        saveAlertTitle.textContent = r.title;
        saveAlertDetail.textContent =
            (unsavedMs ? 'Не сохраняется уже ' + fmtDuration(unsavedMs) + '. ' : '') + r.text +
            ' Последнее сохранение на сервере: ' + fmtTime(lastServerSyncAt) + ' (' + serverCount + ' строк).';
        saveAlertAction.textContent = r.action;
        saveAlertAction.onclick = function () { saveAlertActionFor(key); };
        saveAlert.classList.remove('hidden');
    }

    function saveAlertActionFor(key) {
        if (key === 'inactive') {
            resumeSession();
        } else if (key === 'conflict' && lastConflict) {
            openConflictDialog(lastConflict.items, lastConflict.revision);
        } else if (key === 'shrink' && lastConflict && lastConflict.shrink) {
            openShrinkDialog(lastConflict.shrink);
        } else {
            clearAutoRetry();
            doSave();
        }
    }

    function resumeSession() {
        writeDraft();
        ringPush(collectItems(), 'before-resume');
        var form = document.createElement('form');
        form.method = 'post';
        form.action = config.resumeUrl;
        var token = document.createElement('input');
        token.type = 'hidden';
        token.name = 'csrfmiddlewaretoken';
        token.value = csrfToken();
        form.appendChild(token);
        document.body.appendChild(form);
        allowUnload = true;
        form.submit();
    }

    // ==================== Метод I: повторное сохранение ====================
    // Раз в минуту, пока оператор ничего не меняет, вкладка заново присылает то, что
    // видит на экране. Совпало с сервером — ничего не пишется; если строки на сервере
    // пропали (сбой БД, чужое вмешательство) — сервер запишет их снова.
    var RESAVE_MS = 60000;

    function periodicResave(now) {
        if (!config.canEdit || readOnly || decisionPending || isSaving || isDirty()) return;
        // Ждём решения оператора (конфликт, удаление, сессия на паузе, вход истёк)
        if (hardReason && hardReason !== 'offline' && hardReason !== 'server') return;
        if (!now && Date.now() - lastServerSyncAt < RESAVE_MS) return;
        doSave(null, { periodic: true });
    }

    // ==================== Метод H: одно устройство редактирует сессию ====================
    var HEARTBEAT_MS = 20000;
    var lockBanner = document.getElementById('editor-lock-banner');
    var lockText = document.getElementById('editor-lock-text');
    var lockTakeOverBtn = document.getElementById('editor-lock-takeover');

    function enterReadOnly(name, sameUser) {
        hardReason = 'locked';
        var who = name || 'другой сотрудник';
        lockText.textContent = 'Сессию сейчас редактирует ' + who +
            (sameUser ? ' (это вы — в другой вкладке или на другом устройстве)' : '') +
            '. Здесь только просмотр, чтобы не затереть данные друг друга.';
        lockBanner.classList.remove('hidden');
        if (readOnly) return;
        readOnly = true;
        // Выбор в окне (восстановление/конфликт) в режиме просмотра ничего не сохранит —
        // закрываем; локальная копия не тронута и будет предложена снова после перехвата
        if (decisionPending) closeDecision();
        if (saveTimer) clearTimeout(saveTimer);
        setFormLocked(true);
        setStatus('Только просмотр', 'text-purple-600');
        updateSaveAlert();
    }

    function reloadFresh() {
        allowUnload = true;
        window.location.reload();
    }

    function heartbeat(takeOver) {
        if (!config.canEdit || !config.heartbeatUrl) return Promise.resolve(null);
        var fd = new FormData();
        fd.append('client_id', TAB_ID);
        if (takeOver) fd.append('take_over', '1');
        if (isDirty() && firstUnsavedAt) {
            fd.append('unsaved_seconds', Math.round((Date.now() - firstUnsavedAt) / 1000));
            fd.append('unsaved_reason', hardReason || 'offline');
        }
        return fetch(config.heartbeatUrl, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'X-CSRFToken': csrfToken() },
            body: fd
        })
        .then(readResponse)
        .then(function (res) {
            var d = res.data;
            if (!d) return null;
            if (d.editor) {
                // Редактирование освободилось/перехвачено нами — берём свежие данные с сервера
                if (readOnly) reloadFresh();
            } else if (d.editor_name !== undefined) {
                enterReadOnly(d.editor_name, d.same_user);
            }
            if (d.status && d.status !== 'active' && !readOnly) {
                hardReason = 'inactive';
                updateSaveAlert();
            }
            return d;
        })
        .catch(function () { return null; });   // офлайн — работаем дальше, копии локальные
    }

    if (lockTakeOverBtn) {
        lockTakeOverBtn.addEventListener('click', function () {
            if (!confirm('Забрать редактирование? Другое устройство перейдёт в режим просмотра.')) return;
            heartbeat(true).then(function (d) {
                if (d && d.editor) reloadFresh();
            });
        });
    }

    function collectItems() {
        if (isTableView) {
            return collectFromTable();
        } else {
            return collectFromText();
        }
    }

    function isRowEmpty(row) {
        var inputs = row.querySelectorAll('input');
        if (inputs.length < 3) return true;
        return !inputs[0].value.trim() && !inputs[1].value.trim() && !inputs[2].value.trim();
    }

    function collectFromTable() {
        var rows = tableBody.querySelectorAll('tr');
        var items = [];
        rows.forEach(function (row) {
            var inputs = row.querySelectorAll('input');
            if (inputs.length >= 3) {
                var tc = inputs[0].value.trim();
                var owner = inputs[1].value.trim();
                var weight = inputs[2].value.trim();
                if (tc || owner || weight) {
                    items.push({ track_code: tc, owner_name: owner, weight: weight });
                }
            }
        });
        return items;
    }

    function collectFromText() {
        var tracks = textTracks.value.split('\n');
        var owners = textOwners.value.split('\n');
        var weights = textWeights.value.split('\n');
        var maxLen = Math.max(tracks.length, owners.length, weights.length);
        var items = [];
        for (var i = 0; i < maxLen; i++) {
            var tc = (tracks[i] || '').trim();
            var owner = (owners[i] || '').trim();
            var weight = (weights[i] || '').trim();
            if (tc || owner || weight) {
                items.push({ track_code: tc, owner_name: owner, weight: weight });
            }
        }
        return items;
    }

    // ==================== Навигация стрелками ====================
    function getInputCell(input) {
        var tr = input.closest('tr');
        if (!tr) return null;
        var rows = Array.prototype.slice.call(tableBody.querySelectorAll('tr'));
        var rowIndex = rows.indexOf(tr);
        var inputs = Array.prototype.slice.call(tr.querySelectorAll('input'));
        var colIndex = inputs.indexOf(input);
        return { rowIndex: rowIndex, colIndex: colIndex };
    }

    function getInputAt(rowIndex, colIndex) {
        var rows = tableBody.querySelectorAll('tr');
        if (rowIndex < 0 || rowIndex >= rows.length) return null;
        var inputs = rows[rowIndex].querySelectorAll('input');
        if (colIndex < 0 || colIndex >= inputs.length) return null;
        return inputs[colIndex];
    }

    function handleArrowNav(e, input) {
        var cell = getInputCell(input);
        if (!cell) return;
        var target = null;

        if (e.key === 'ArrowUp') {
            target = getInputAt(cell.rowIndex - 1, cell.colIndex);
        } else if (e.key === 'ArrowDown') {
            target = getInputAt(cell.rowIndex + 1, cell.colIndex);
        } else if (e.key === 'ArrowLeft' && input.selectionStart === 0) {
            target = getInputAt(cell.rowIndex, cell.colIndex - 1);
        } else if (e.key === 'ArrowRight' && input.selectionStart === input.value.length) {
            target = getInputAt(cell.rowIndex, cell.colIndex + 1);
        }

        if (target) {
            e.preventDefault();
            target.focus();
            target.select();
        }
    }

    // ==================== Метка "трек уже был" ====================
    var STATUS_COLORS = {
        'no_owner':     { border: '#94a3b8', bg: '#f8fafc' },  // серый
        'user_added':   { border: '#60a5fa', bg: '#eff6ff' },  // голубой
        'warehouse_cn': { border: '#34d399', bg: '#f0fdf4' },  // зелёный
        'shipped_cn':   { border: '#34d399', bg: '#f0fdf4' },
        'unidentified': { border: '#f87171', bg: '#fef2f2' },  // красный (неопозка)
        'delivered':    { border: '#a78bfa', bg: '#f5f3ff' },  // фиолетовый
        'shipping_pp':  { border: '#f97316', bg: '#fff7ed' },  // оранжевый
        'ready':        { border: '#22c55e', bg: '#f0fdf4' },  // зелёный
        'claimed':      { border: '#6b7280', bg: '#f9fafb' },  // тёмно-серый
    };

    function markTrackExists(trackInput, statusKey, statusLabel) {
        trackInput.dataset.trackExists = '1';
        trackInput.dataset.trackStatusKey = statusKey || '';
        trackInput.dataset.trackStatusLabel = statusLabel || '';
        // Не перезаписываем жёлтую метку «подозрительная ячейка»
        if (trackInput.style.outline && trackInput.style.outline.indexOf('f59e0b') !== -1) return;
        var colors = STATUS_COLORS[statusKey] || { border: '#60a5fa', bg: '#eff6ff' };
        trackInput.style.outline = '2px solid ' + colors.border;
        trackInput.style.backgroundColor = colors.bg;
        trackInput.title = 'Трек уже в базе: ' + statusLabel;
    }

    function clearTrackExistsMark(trackInput) {
        if (trackInput.dataset.trackExists) {
            trackInput.style.outline = '';
            trackInput.style.backgroundColor = '';
            trackInput.title = '';
            delete trackInput.dataset.trackExists;
        }
    }

    // ==================== Подтягивание владельца по трек-коду ====================
    function fetchTrackOwner(trackInput, ownerInput, weightInput) {
        var code = trackInput.value.trim();
        if (!code || !config.getOwnerUrl) return;

        // Сначала проверяем кеш начальных данных
        if (config.knownTracks && config.knownTracks[code]) {
            var kt = config.knownTracks[code];
            markTrackExists(trackInput, kt.status, kt.status_label);
        }

        if (ownerInput.value.trim()) return;

        fetch(config.getOwnerUrl + '?track_code=' + encodeURIComponent(code))
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.exists) {
                    markTrackExists(trackInput, data.status, data.status_label);
                } else {
                    clearTrackExistsMark(trackInput);
                }
                if (data.owner && !ownerInput.value.trim()) {
                    ownerInput.value = data.owner;
                    scheduleSave();
                    if (weightInput) weightInput.focus();
                }
            })
            .catch(function () {});
    }

    // ==================== Автоподсказки владельцев (inline selection) ====================
    function debounce(func, wait) {
        var timeout;
        return function () {
            var ctx = this, args = arguments;
            clearTimeout(timeout);
            timeout = setTimeout(function () { func.apply(ctx, args); }, wait);
        };
    }

    // Глобальное состояние inline-автоподсказки (одна подсказка в один момент)
    var inlineAc = {
        active: false,
        input: null,
        typedLen: 0,
        suggestion: ''
    };

    function inlineClear() {
        inlineAc.active = false;
        inlineAc.input = null;
        inlineAc.typedLen = 0;
        inlineAc.suggestion = '';
    }

    function inlineApply(input, results, typedQuery) {
        if (!results.length || !typedQuery) {
            inlineClear();
            return;
        }
        if (!inlineAc.active || inlineAc.input !== input) {
            if (input.value.trim().toLowerCase() !== typedQuery.toLowerCase()) {
                inlineClear();
                return;
            }
        }
        var login = results[0].login;
        if (login.toLowerCase().indexOf(typedQuery.toLowerCase()) !== 0) {
            inlineClear();
            return;
        }

        inlineAc.active = true;
        inlineAc.input = input;
        inlineAc.typedLen = typedQuery.length;
        inlineAc.suggestion = login;

        input.value = typedQuery + login.substring(typedQuery.length);
        input.setSelectionRange(typedQuery.length, login.length);
    }

    function inlineAccept(input, weightInput) {
        if (!inlineAc.active || inlineAc.input !== input) return false;
        input.value = inlineAc.suggestion;
        input.setSelectionRange(input.value.length, input.value.length);
        inlineClear();
        scheduleSave();
        if (weightInput) weightInput.focus();
        return true;
    }

    function inlineReject(input) {
        if (!inlineAc.active || inlineAc.input !== input) return;
        var typed = input.value.substring(0, inlineAc.typedLen);
        input.value = typed;
        input.setSelectionRange(typed.length, typed.length);
        inlineClear();
    }

    function setupOwnerAutocomplete(input, weightInput) {
        var fetchDebounced = debounce(function () {
            var query;
            if (inlineAc.active && inlineAc.input === input) {
                query = input.value.substring(0, inlineAc.typedLen).trim();
            } else {
                query = input.value.trim();
            }
            if (query.length < 1) {
                inlineClear();
                return;
            }

            fetch(config.searchUsersUrl + '?q=' + encodeURIComponent(query))
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (data.results && data.results.length && document.activeElement === input) {
                        inlineApply(input, data.results, query);
                    } else {
                        inlineClear();
                    }
                })
                .catch(function () { inlineClear(); });
        }, 150);

        input.addEventListener('input', function () {
            if (inlineAc.active && inlineAc.input === input) {
                inlineAc.active = false;
            }
            fetchDebounced();
        });

        input.addEventListener('keydown', function (e) {
            // Inline-подсказка: Enter/Tab принимает
            if (inlineAc.active && inlineAc.input === input) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    inlineAccept(input, weightInput);
                    return;
                } else if (e.key === 'Escape') {
                    e.preventDefault();
                    inlineReject(input);
                    return;
                } else if (e.key === 'Tab') {
                    inlineAccept(input, weightInput);
                    e.preventDefault();
                    return;
                }
            }

            // Enter / Tab без подсказки — переход к весу
            if (e.key === 'Enter' || (e.key === 'Tab' && !e.shiftKey)) {
                e.preventDefault();
                if (weightInput) weightInput.focus();
                return;
            }

            handleArrowNav(e, input);
        });

        input.addEventListener('blur', function () {
            if (inlineAc.active && inlineAc.input === input) {
                inlineReject(input);
            }
        });
    }

    // ==================== Таблица ====================
    function addRow(data, noFocus) {
        rowNum++;
        var tr = document.createElement('tr');
        tr.className = 'border-b border-gray-100 hover:bg-gray-50';

        var numTd = document.createElement('td');
        numTd.className = 'px-2 py-1 text-center text-sm text-gray-500';
        numTd.textContent = rowNum;

        var trackTd = document.createElement('td');
        trackTd.className = 'px-2 py-1';
        var trackInput = document.createElement('input');
        trackInput.type = 'text';
        trackInput.className = 'w-full border border-gray-200 rounded px-2 py-1 text-sm focus:ring-1 focus:ring-red-400';
        trackInput.value = data ? data.track_code : '';
        trackInput.placeholder = 'Трек-код';

        // Сразу метим если трек уже известен из начальных данных
        if (data && data.track_code && config.knownTracks && config.knownTracks[data.track_code]) {
            var kt = config.knownTracks[data.track_code];
            markTrackExists(trackInput, kt.status, kt.status_label);
        }

        trackInput.addEventListener('input', function () {
            clearTrackExistsMark(trackInput);
            scheduleSave();
            validateCell(trackInput, 0);
            var allRows = tableBody.querySelectorAll('tr');
            var lastRow = allRows[allRows.length - 1];
            if (tr === lastRow && trackInput.value.trim() !== '') {
                addRow(null, true);
            }
        });
        trackTd.appendChild(trackInput);

        var ownerTd = document.createElement('td');
        ownerTd.className = 'px-2 py-1';
        var ownerInput = document.createElement('input');
        ownerInput.type = 'text';
        ownerInput.className = 'w-full border border-gray-200 rounded px-2 py-1 text-sm focus:ring-1 focus:ring-red-400';
        ownerInput.value = data ? data.owner_name : '';
        ownerInput.placeholder = 'Логин владельца';
        ownerInput.setAttribute('autocomplete', 'off');
        ownerInput.addEventListener('input', function () {
            scheduleSave();
            validateCell(ownerInput, 1);
        });
        ownerTd.appendChild(ownerInput);

        var weightTd = document.createElement('td');
        weightTd.className = 'px-2 py-1';
        var weightInput = document.createElement('input');
        weightInput.type = 'text';
        weightInput.className = 'w-full border border-gray-200 rounded px-2 py-1 text-sm focus:ring-1 focus:ring-red-400';
        weightInput.value = data ? data.weight || '' : '';
        weightInput.placeholder = '0.000';
        weightInput.addEventListener('keydown', function (e) {
            // Разрешаем: цифры, точку, запятую, Backspace, Delete, стрелки, Tab, Enter, Home, End
            var allowed = [
                'Backspace', 'Delete', 'Tab', 'Enter', 'ArrowLeft', 'ArrowRight',
                'ArrowUp', 'ArrowDown', 'Home', 'End', '.', ','
            ];
            var isDigit = (e.key >= '0' && e.key <= '9');
            var isAllowed = allowed.indexOf(e.key) !== -1;
            var isCtrl = e.ctrlKey || e.metaKey; // Ctrl+A, Ctrl+C, Ctrl+V и т.д.
            if (!isDigit && !isAllowed && !isCtrl) {
                e.preventDefault();
            }
        });
        weightInput.addEventListener('input', function () {
            scheduleSave();
            validateCell(weightInput, 2);
        });
        weightTd.appendChild(weightInput);

        var actionTd = document.createElement('td');
        actionTd.className = 'px-2 py-1 text-center';
        var delBtn = document.createElement('button');
        delBtn.type = 'button';
        delBtn.className = 'text-red-400 hover:text-red-600';
        delBtn.innerHTML = '<i class="ri-delete-bin-line"></i>';
        delBtn.tabIndex = -1;
        delBtn.addEventListener('click', function () {
            tr.remove();
            updateRowNumbers();
            scheduleSave();
        });
        actionTd.appendChild(delBtn);

        tr.appendChild(numTd);
        tr.appendChild(trackTd);
        tr.appendChild(ownerTd);
        tr.appendChild(weightTd);
        tr.appendChild(actionTd);

        tableBody.appendChild(tr);
        updateRowNumbers();

        // Inline ghost text автозаполнение для поля владельца
        setupOwnerAutocomplete(ownerInput, weightInput);

        // Фокус на последний трек-код (только если не авто-создание)
        if (!data && !noFocus) trackInput.focus();

        // Подтягиваем владельца при вводе трек-кода (с debounce)
        trackInput.addEventListener('input', debounce(function () {
            fetchTrackOwner(trackInput, ownerInput, weightInput);
        }, 400));
        trackInput.addEventListener('blur', function () {
            fetchTrackOwner(trackInput, ownerInput, weightInput);
        });

        // Enter + Tab навигация
        trackInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' || e.key === 'Tab') {
                e.preventDefault();
                ownerInput.focus();
                fetchTrackOwner(trackInput, ownerInput, weightInput);
            }
            handleArrowNav(e, trackInput);
        });
        // ownerInput keydown обрабатывается в setupOwnerAutocomplete
        weightInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' || (e.key === 'Tab' && !e.shiftKey)) {
                e.preventDefault();
                var cell = getInputCell(weightInput);
                var nextTrack = cell ? getInputAt(cell.rowIndex + 1, 0) : null;
                if (nextTrack) {
                    nextTrack.focus();
                    nextTrack.select();
                } else {
                    addRow();
                }
                return;
            }
            if (e.key === 'ArrowRight' && weightInput.selectionStart === weightInput.value.length) {
                e.preventDefault();
                var cell = getInputCell(weightInput);
                var nextTrack = cell ? getInputAt(cell.rowIndex + 1, 0) : null;
                if (nextTrack) {
                    nextTrack.focus();
                    nextTrack.select();
                } else {
                    addRow();
                }
                return;
            }
            handleArrowNav(e, weightInput);
        });
    }

    function updateRowNumbers() {
        var rows = tableBody.querySelectorAll('tr');
        rowNum = 0;
        rows.forEach(function (row) {
            rowNum++;
            row.querySelector('td').textContent = rowNum;
        });
        rowCounter.textContent = rowNum + ' строк';
        updateEmptyCells();
    }

    function updateEmptyCells() {
        var empty = 0;
        var rows = tableBody.querySelectorAll('tr');
        rows.forEach(function (row, idx) {
            if (idx === rows.length - 1 && isRowEmpty(row)) return;
            var inputs = row.querySelectorAll('input');
            var hasAny = false;
            inputs.forEach(function (input) { if (input.value.trim()) hasAny = true; });
            if (hasAny) {
                inputs.forEach(function (input) {
                    if (!input.value.trim()) empty++;
                });
            }
        });
        if (empty > 0) {
            emptyCellsWarning.classList.remove('hidden');
            emptyCellsCount.textContent = empty;
        } else {
            emptyCellsWarning.classList.add('hidden');
        }
    }

    addRowBtn.addEventListener('click', function () { addRow(); });

    // ==================== Валидация ячеек ====================
    // Клиент: буквы верхнего регистра + 4 цифры на конце
    var RE_OWNER   = /^[A-ZА-ЯЁ]{2,16}\d{4}$/;
    // Вес: число до 3 знаков после точки/запятой, < 1000
    var RE_WEIGHT  = /^\d{1,3}([.,]\d{1,3})?$/;
    // Трек-код: только цифры (8+), или буквы+цифры
    var RE_TRACK   = /^([A-Z]{2}\d{6,}|[A-Z]{1,5}\d{4,}[\w-]*|\d{8,})$/i;

    function looksLikeOwner(v) { return RE_OWNER.test(v); }
    function looksLikeWeight(v) { return RE_WEIGHT.test(v) && parseFloat(v.replace(',', '.')) < 1000; }
    function looksLikeTrack(v)  { return RE_TRACK.test(v) && !looksLikeOwner(v) && !looksLikeWeight(v); }

    function validateCell(input, col) {
        var v = input.value.trim();
        if (!v) {
            clearCellWarning(input);
            return;
        }
        var suspicious = false;
        if (col === 0) {
            if (looksLikeOwner(v) || looksLikeWeight(v)) suspicious = true;
        } else if (col === 1) {
            if (looksLikeTrack(v) || looksLikeWeight(v)) suspicious = true;
        } else if (col === 2) {
            if (!looksLikeWeight(v) || looksLikeOwner(v) || looksLikeTrack(v)) suspicious = true;
        }
        if (suspicious) {
            input.dataset.suspicious = '1';
            input.style.outline = '2px solid #f59e0b';
            input.style.backgroundColor = '#fefce8';
            input.title = 'Возможно данные введены не в ту колонку';
        } else {
            delete input.dataset.suspicious;
            clearCellWarning(input);
        }
        updateSuspiciousCounter();
    }

    function clearCellWarning(input) {
        delete input.dataset.suspicious;
        // Если трек помечен как существующий — восстанавливаем его стиль, а не просто чистим
        if (input.dataset.trackExists) {
            input.title = 'Трек уже в базе: ' + (input.dataset.trackStatusLabel || '');
            // Перерисуем цвет по сохранённому статусу
            var col = input.dataset.trackStatusKey;
            var colors = (col && STATUS_COLORS[col]) ? STATUS_COLORS[col] : { border: '#60a5fa', bg: '#eff6ff' };
            input.style.outline = '2px solid ' + colors.border;
            input.style.backgroundColor = colors.bg;
        } else {
            input.style.outline = '';
            input.style.backgroundColor = '';
            input.title = '';
        }
    }

    function updateSuspiciousCounter() {
        suspiciousInputs = Array.prototype.slice.call(
            tableBody.querySelectorAll('input[data-suspicious="1"]')
        );
        var cnt = suspiciousInputs.length;
        if (cnt > 0) {
            suspiciousWarning.classList.remove('hidden');
            suspiciousCount.textContent = cnt;
            // Обновляем курсор если вышел за пределы
            if (suspiciousCursor >= cnt) suspiciousCursor = cnt - 1;
        } else {
            suspiciousWarning.classList.add('hidden');
            suspiciousCursor = -1;
        }
    }

    function navigateSuspicious(dir) {
        if (!suspiciousInputs.length) return;
        suspiciousCursor += dir;
        if (suspiciousCursor < 0) suspiciousCursor = suspiciousInputs.length - 1;
        if (suspiciousCursor >= suspiciousInputs.length) suspiciousCursor = 0;
        var inp = suspiciousInputs[suspiciousCursor];
        inp.scrollIntoView({ behavior: 'smooth', block: 'center' });
        inp.focus();
        inp.select();
    }

    suspiciousNextBtn.addEventListener('click', function () { navigateSuspicious(1); });
    suspiciousPrevBtn.addEventListener('click', function () { navigateSuspicious(-1); });

    // ==================== Занятые треки (уже в другой сессии) ====================
    var occupiedWarning = (function () {
        var el = document.createElement('div');
        el.className = 'hidden mt-2 p-3 bg-orange-50 border border-orange-300 rounded-lg text-sm text-orange-800';
        el.innerHTML = '<i class="ri-error-warning-line mr-1"></i> <span id="occupied_text"></span>';
        suspiciousWarning.parentNode.insertBefore(el, suspiciousWarning.nextSibling);
        return el;
    }());
    var occupiedText = document.getElementById('occupied_text');

    function showOccupiedWarning(codes) {
        occupiedText.textContent = 'Треки уже в другой сессии (пропущены): ' + codes.join(', ');
        occupiedWarning.classList.remove('hidden');
    }
    function hideOccupiedWarning() {
        occupiedWarning.classList.add('hidden');
    }

    // ==================== Запрещённые символы в трек-кодах ====================
    var invalidCharsWarning = (function () {
        var el = document.createElement('div');
        el.className = 'hidden mt-2 p-3 bg-red-50 border border-red-300 rounded-lg text-sm text-red-800';
        el.innerHTML = '<i class="ri-forbid-line mr-1"></i> <span id="invalid_chars_text"></span>';
        occupiedWarning.parentNode.insertBefore(el, occupiedWarning.nextSibling);
        return el;
    }());
    var invalidCharsText = document.getElementById('invalid_chars_text');

    function showInvalidCharsWarning(codes) {
        invalidCharsText.textContent = 'Трек-коды с запрещёнными символами (пропущены): ' + codes.join(', ');
        invalidCharsWarning.classList.remove('hidden');
    }
    function hideInvalidCharsWarning() {
        invalidCharsWarning.classList.add('hidden');
    }

    function validateRow(tr) {
        var inputs = tr.querySelectorAll('input');
        inputs.forEach(function (inp, idx) {
            validateCell(inp, idx);
        });
    }

    function validateAllRows() {
        tableBody.querySelectorAll('tr').forEach(function (tr) {
            validateRow(tr);
        });
        updateSuspiciousCounter();
    }

    // ==================== Переключение вида ====================
    toggleBtn.addEventListener('click', function () {
        if (isTableView) {
            var items = collectFromTable();
            textTracks.value = items.map(function (i) { return i.track_code; }).join('\n');
            textOwners.value = items.map(function (i) { return i.owner_name; }).join('\n');
            textWeights.value = items.map(function (i) { return i.weight; }).join('\n');
            tableView.classList.add('hidden');
            textView.classList.remove('hidden');
            toggleBtn.innerHTML = '<i class="ri-table-line"></i> Переключить на табличный вид';
            isTableView = false;
            updateTextCounters();
        } else {
            var items = collectFromText();
            tableBody.innerHTML = '';
            rowNum = 0;
            items.forEach(function (item) { addRow(item); });
            if (items.length === 0) addRow();
            textView.classList.add('hidden');
            tableView.classList.remove('hidden');
            toggleBtn.innerHTML = '<i class="ri-file-text-line"></i> Переключить на текстовый вид';
            isTableView = true;
        }
        scheduleSave();
    });

    function updateTextCounters() {
        var countLines = function (textarea) {
            return textarea.value.split('\n').filter(function (l) { return l.trim(); }).length;
        };
        textCountTracks.textContent = '(' + countLines(textTracks) + ')';
        textCountOwners.textContent = '(' + countLines(textOwners) + ')';
        textCountWeights.textContent = '(' + countLines(textWeights) + ')';
    }

    [textTracks, textOwners, textWeights].forEach(function (ta) {
        ta.addEventListener('input', function () {
            updateTextCounters();
            scheduleSave();
        });
    });

    // ==================== Сохранение перед завершением ====================
    // Завершаем только если последние изменения точно легли на сервер: иначе сессия
    // закрылась бы со старыми строками, и введённое после сбоя пропало бы.
    var completeForm = document.getElementById('complete_form');
    var completeRevision = document.getElementById('complete_revision');
    if (completeForm) {
        completeForm.addEventListener('submit', function (e) {
            if (readOnly || decisionPending) {
                e.preventDefault();
                alert('Сейчас завершить нельзя: сессию редактирует другое устройство или ждёт ваш выбор.');
                return;
            }
            if (saveTimer) clearTimeout(saveTimer);

            var items = collectItems();
            var body = saveBody(items, { source: 'complete' });
            var status = 0, data = null;
            try {
                var xhr = new XMLHttpRequest();
                xhr.open('POST', config.saveUrl, false);
                xhr.setRequestHeader('Content-Type', 'application/json');
                xhr.setRequestHeader('X-CSRFToken', csrfToken());
                xhr.send(JSON.stringify(body));
                status = xhr.status;
                try { data = JSON.parse(xhr.responseText); } catch (err) { data = null; }
            } catch (err) {
                status = 0;   // сеть недоступна
            }

            if (status === 200 && data && data.success) {
                revision = data.revision;
                ackedSeq = changeSeq;
                if (completeRevision) completeRevision.value = revision;
                deleteDraft();
                return;   // форма уходит — сессия завершается
            }

            e.preventDefault();
            if (status === 409 && data) {
                handleSaveResult({ status: 409, data: data, kind: 'json' }, items, body, changeSeq);
                if (data.stale && completeRevision) {
                    // Сохранено более поздним снимком — можно завершать повторно
                    completeRevision.value = revision;
                }
            } else {
                onSaveFailed(status === 0 ? 'offline' : 'server', items, body);
                alert('Не удалось сохранить последние изменения — завершение отменено. ' +
                      'Данные не потеряны: проверьте связь и нажмите «Завершить» ещё раз.');
            }
            updateSaveAlert();
        });
    }

    // ==================== Инициализация ====================
    if (config.initialItems && config.initialItems.length > 0) {
        config.initialItems.forEach(function (item) {
            addRow(item);
        });
        validateAllRows();
    } else {
        addRow();
    }

    // --- Метод H: сессию прямо сейчас ведёт другая вкладка/устройство — только просмотр ---
    if (config.canEdit && config.lock && config.lock.clientId && config.lock.clientId !== TAB_ID) {
        enterReadOnly(config.lock.name, false);
    }

    // --- Метод A: предложить восстановление резервной копии ---
    (function () {
        ringCleanup();
        var local = readDraft();
        // Чистим устаревший localStorage-черновик
        if (local && local.savedAt && (Date.now() - local.savedAt) > DRAFT_TTL) {
            deleteDraft();
        }
        if (!config.canEdit || readOnly) return;   // сессия на паузе/неактивна или только просмотр
        var draft = getBestDraft();
        if (!draft || !draft.items || !draft.items.length) return;
        if (draft.savedAt && (Date.now() - draft.savedAt) > DRAFT_TTL) return;
        // Окно — только если копия реально отличается от загруженных данных. Сравниваем
        // с сырым вводом применённой версии (если есть): строки сессии нормализованы
        // (вес округлён, дубли отброшены) и иначе всегда «отличались» бы от копии.
        var baseline = config.serverRaw || config.initialItems || [];
        if (itemsDiffer(draft.items, baseline) && itemsDiffer(draft.items, config.initialItems || [])) {
            offerRestore(draft);
        }
    })();

    // --- Метод E: кнопки экспорта / импорта ---
    var exportBtn = document.getElementById('export_backup_btn');
    var importBtn = document.getElementById('import_backup_btn');
    var importInput = document.getElementById('import_backup_input');
    if (exportBtn) exportBtn.addEventListener('click', exportBackup);
    if (importBtn && importInput) {
        importBtn.addEventListener('click', function () { importInput.click(); });
        importInput.addEventListener('change', function () {
            if (importInput.files && importInput.files[0]) {
                importBackup(importInput.files[0]);
                importInput.value = '';
            }
        });
    }

    // --- Метод C: реакция на события online / offline ---
    window.addEventListener('online', function () {
        if (isDirty() || connectionState.isLost) {
            clearAutoRetry();
            doSave();
        }
    });
    window.addEventListener('offline', function () {
        if (config.canEdit) showConnectionLost();
    });
    if (config.canEdit && !navigator.onLine) {
        showConnectionLost();
    }

    // --- Метод H/F: heartbeat редактора и плашка несохранённых данных ---
    heartbeat();
    setInterval(heartbeat, HEARTBEAT_MS);
    setInterval(updateSaveAlert, 5000);
    setInterval(periodicResave, 15000);

    // --- Метод B: защита от потери данных при закрытии вкладки ---
    window.addEventListener('beforeunload', function (e) {
        if (isDirty() && config.canEdit && !allowUnload) {
            e.preventDefault();
            e.returnValue = '';
        }
    });
    window.addEventListener('pagehide', function () {
        beaconSave();
        beaconRelease();
    });
    document.addEventListener('visibilitychange', function () {
        if (document.visibilityState === 'hidden') beaconSave();
        else periodicResave(true);   // вернулись на вкладку (после сна/переключения) — сверяемся сразу
    });
    // Намеренный уход (Завершить / Пауза / Возобновить) — дослать данные, не предупреждать
    document.addEventListener('submit', function (e) {
        if (e.defaultPrevented) return;   // завершение отменено — остаёмся на странице
        allowUnload = true;
        beaconSave();
    });
});
