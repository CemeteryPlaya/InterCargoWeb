/**
 * Чат техподдержки на мобильной странице «Сообщения».
 *
 * Один и тот же полноэкранный панель-чат работает в двух режимах:
 * - клиент: свой чат с поддержкой (API /support/api/my/...);
 * - оператор: чат выбранного клиента из очереди/своих (API /support/api/chat/<id>/...).
 *
 * Реалтайм — webpush через воркер; страница опрашивает сервер редко
 * (раз в 3 минуты, только при открытой панели) + при возврате на вкладку.
 */
document.addEventListener('DOMContentLoaded', function () {
    var config = document.getElementById('support-mobile-config');
    if (!config) return;

    var POLL_INTERVAL_MS = 180000;

    var isOperator = config.dataset.isOperator === 'true';
    var myMessagesUrl = config.dataset.myMessagesUrl;
    var mySendUrl = config.dataset.mySendUrl;
    var myReadUrl = config.dataset.myReadUrl;
    var chatBaseUrl = config.dataset.chatBaseUrl;
    var labels = {
        support: config.dataset.labelSupport || 'Техподдержка',
        system: config.dataset.labelSystem || 'Системное сообщение',
        taken: config.dataset.labelTaken || 'Чат взят в работу',
        conflict: config.dataset.labelConflict || 'Чат уже взят другим оператором',
        closeConfirm: config.dataset.labelCloseConfirm || 'Закрыть чат?',
        error: config.dataset.labelError || 'Ошибка. Попробуйте ещё раз.',
    };
    var csrfInput = document.getElementById('csrf-token');
    var csrf = csrfInput ? csrfInput.value : '';

    var panel = document.getElementById('support-panel');
    var panelTitle = document.getElementById('support-panel-title');
    var scrollEl = document.getElementById('support-panel-scroll');
    var emptyEl = document.getElementById('support-panel-empty');
    var form = document.getElementById('support-panel-form');
    var input = document.getElementById('support-panel-input');
    var sendBtn = document.getElementById('support-panel-send');
    var backBtn = document.getElementById('support-back-btn');
    var claimBar = document.getElementById('support-claim-bar');
    var claimBtn = document.getElementById('support-claim-btn');
    var closeChatBtn = document.getElementById('support-close-chat-btn');
    var escalateBtn = document.getElementById('support-escalate-btn');
    var returnBtn = document.getElementById('support-return-btn');
    var escalateOverlay = document.getElementById('support-escalate-overlay');
    var escalateListEl = document.getElementById('support-escalate-list');
    var escalateCancel = document.getElementById('support-escalate-cancel');
    var escalateBackdrop = document.getElementById('support-escalate-backdrop');
    var directorsUrl = config.dataset.directorsUrl;
    var bottomNav = document.getElementById('mobile-bottom-nav');

    var openChatId = null;   // null = клиентский режим
    var assignedToMe = false;
    var lastId = 0;
    var lastDate = '';
    var pollTimer = null;

    function apiUrl(chatId, action) {
        return chatBaseUrl + chatId + '/' + action + '/';
    }

    function scrollBottom() {
        scrollEl.scrollTop = scrollEl.scrollHeight;
    }

    function clearMessages() {
        scrollEl.querySelectorAll('.support-msg-node').forEach(function (n) { n.remove(); });
        lastId = 0;
        lastDate = '';
    }

    function showEmpty(show) {
        if (emptyEl) emptyEl.style.display = show ? '' : 'none';
    }

    function appendDateSeparator(date) {
        var wrap = document.createElement('div');
        wrap.className = 'support-msg-node flex items-center justify-center my-3';
        wrap.innerHTML = '<span class="px-3 py-1 bg-gray-200 text-gray-500 text-[11px] font-medium rounded-full"></span>';
        wrap.querySelector('span').textContent = date;
        scrollEl.appendChild(wrap);
    }

    function appendMessage(msg) {
        showEmpty(false);
        if (msg.date !== lastDate) {
            appendDateSeparator(msg.date);
            lastDate = msg.date;
        }

        if (msg.author_role === 'system') {
            var sys = document.createElement('div');
            sys.className = 'support-msg-node flex justify-center mb-2';
            sys.innerHTML = '<span class="px-3 py-1 bg-gray-100 text-gray-400 text-[11px] rounded-full text-center"></span>';
            sys.querySelector('span').textContent = msg.text;
            scrollEl.appendChild(sys);
            if (msg.id > lastId) lastId = msg.id;
            return;
        }

        // «Мои» сообщения: у клиента — свои, у оператора — сообщения поддержки
        var mine = isOperator ? msg.author_role === 'staff' : msg.author_role === 'client';
        var row = document.createElement('div');
        row.className = 'support-msg-node flex mb-2 ' + (mine ? 'justify-end' : 'justify-start');

        var bubble = document.createElement('div');
        bubble.className = 'max-w-[85%] rounded-2xl px-3.5 py-2.5 shadow-sm ' +
            (mine ? 'bg-primary text-white rounded-tr-sm'
                  : 'bg-white border border-gray-200 rounded-tl-sm');

        if (!mine && msg.sender_name) {
            var name = document.createElement('p');
            name.className = 'text-[11px] font-semibold text-primary mb-0.5';
            name.textContent = msg.sender_name;
            bubble.appendChild(name);
        }

        var text = document.createElement('p');
        text.className = 'text-[13px] leading-relaxed whitespace-pre-wrap break-words' + (mine ? '' : ' text-gray-800');
        text.textContent = msg.text;
        bubble.appendChild(text);

        var time = document.createElement('p');
        time.className = 'text-[10px] mt-1 text-right ' + (mine ? 'text-white/70' : 'text-gray-400');
        time.textContent = msg.time;
        bubble.appendChild(time);

        row.appendChild(bubble);
        scrollEl.appendChild(row);
        if (msg.id > lastId) lastId = msg.id;
    }

    function postForm(url, body) {
        return fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-CSRFToken': csrf,
            },
            body: body || '',
        });
    }

    function markRead() {
        if (openChatId === null) {
            postForm(myReadUrl).catch(function () {});
        } else if (assignedToMe) {
            postForm(apiUrl(openChatId, 'read')).catch(function () {});
        }
    }

    function updateClaimBar(chat) {
        if (!claimBar) return;
        assignedToMe = !!(chat && chat.assigned_to_me);
        var closed = chat && chat.status === 'closed';
        var inQueue = chat && !chat.assigned_to_name && chat.status === 'open';
        claimBar.classList.toggle('hidden', !inQueue);
        if (closeChatBtn) {
            closeChatBtn.classList.toggle('hidden', !assignedToMe || closed);
        }
        if (escalateBtn) {
            escalateBtn.classList.toggle('hidden', !assignedToMe || closed);
        }
        if (returnBtn) {
            returnBtn.classList.toggle('hidden', !(chat && chat.can_return) || closed);
        }
    }

    function loadMessages(initial) {
        var url;
        if (openChatId === null) {
            url = myMessagesUrl + '?after_id=' + lastId;
        } else {
            url = apiUrl(openChatId, 'messages') + '?after_id=' + lastId;
        }
        fetch(url, { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.chat) updateClaimBar(data.chat);
                var msgs = data.messages || [];
                if (msgs.length) {
                    msgs.forEach(appendMessage);
                    scrollBottom();
                }
                if (initial || (data.unread && data.unread > 0) ||
                        (data.chat && data.chat.unread > 0)) {
                    markRead();
                }
            })
            .catch(function () { /* повторим по таймеру */ });
    }

    function openPanel(chatId, title) {
        openChatId = chatId;
        assignedToMe = false;
        clearMessages();
        showEmpty(true);
        panelTitle.textContent = title || labels.support;
        if (claimBar) claimBar.classList.add('hidden');
        if (closeChatBtn) closeChatBtn.classList.add('hidden');
        if (escalateBtn) escalateBtn.classList.add('hidden');
        if (returnBtn) returnBtn.classList.add('hidden');
        panel.classList.remove('hidden');
        if (bottomNav) bottomNav.style.display = 'none';
        loadMessages(true);
        clearInterval(pollTimer);
        pollTimer = setInterval(loadMessages, POLL_INTERVAL_MS);
        setTimeout(function () { input.focus(); }, 250);
    }

    function closePanel() {
        panel.classList.add('hidden');
        if (bottomNav) bottomNav.style.display = '';
        clearInterval(pollTimer);
        pollTimer = null;
        openChatId = null;
        // Обновляем бейджи списка простым способом — перезагрузкой страницы
        // не пользуемся; бейджи актуализируются при следующем заходе.
    }

    // Клиентская запись
    var clientBtn = document.getElementById('support-open-btn');
    if (clientBtn) {
        clientBtn.addEventListener('click', function () {
            openPanel(null, labels.support);
            var badge = document.getElementById('support-entry-badge');
            if (badge) badge.remove();
        });
    }

    // Операторские записи
    document.querySelectorAll('.support-chat-open').forEach(function (btn) {
        btn.addEventListener('click', function () {
            openPanel(parseInt(btn.dataset.chatId, 10), btn.dataset.chatTitle);
            var badge = btn.querySelector('.rounded-full.text-white');
            if (badge) badge.remove();
        });
    });

    if (backBtn) backBtn.addEventListener('click', closePanel);

    // Взять в работу
    if (claimBtn) {
        claimBtn.addEventListener('click', function () {
            if (openChatId === null) return;
            postForm(apiUrl(openChatId, 'claim'))
                .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
                .then(function (res) {
                    if (res.ok) {
                        claimBar.classList.add('hidden');
                        assignedToMe = true;
                        if (closeChatBtn) closeChatBtn.classList.remove('hidden');
                        loadMessages();
                        markRead();
                    } else {
                        alert(res.data.error || labels.conflict);
                        closePanel();
                    }
                })
                .catch(function () { alert(labels.error); });
        });
    }

    // Эскалация директору (оператор)
    if (escalateBtn) {
        escalateBtn.addEventListener('click', function () {
            if (openChatId === null) return;
            escalateListEl.innerHTML = '';
            fetch(directorsUrl, { credentials: 'same-origin' })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    (data.directors || []).forEach(function (d) {
                        var btn = document.createElement('button');
                        btn.type = 'button';
                        btn.className = 'w-full flex items-center gap-3 px-3 py-3 border border-gray-200 rounded-xl hover:bg-violet-50 transition text-left';
                        btn.innerHTML = '<div class="w-9 h-9 rounded-full bg-violet-100 text-violet-600 flex items-center justify-center flex-shrink-0"><i class="ri-user-star-line"></i></div>';
                        var name = document.createElement('span');
                        name.className = 'text-sm font-medium';
                        name.textContent = d.name;
                        btn.appendChild(name);
                        btn.addEventListener('click', function () {
                            escalateOverlay.classList.add('hidden');
                            postForm(apiUrl(openChatId, 'escalate'),
                                'director_id=' + encodeURIComponent(d.id))
                                .then(function (r) { return r.json().then(function (dd) { return { ok: r.ok, data: dd }; }); })
                                .then(function (res) {
                                    if (!res.ok) {
                                        alert(res.data.error || labels.error);
                                        return;
                                    }
                                    // Чат передан — оператор теряет доступ
                                    closePanel();
                                })
                                .catch(function () { alert(labels.error); });
                        });
                        escalateListEl.appendChild(btn);
                    });
                    escalateOverlay.classList.remove('hidden');
                })
                .catch(function () { alert(labels.error); });
        });
    }
    if (escalateCancel) {
        escalateCancel.addEventListener('click', function () {
            escalateOverlay.classList.add('hidden');
        });
    }
    if (escalateBackdrop) {
        escalateBackdrop.addEventListener('click', function () {
            escalateOverlay.classList.add('hidden');
        });
    }

    // Вернуть чат оператору (директор)
    if (returnBtn) {
        returnBtn.addEventListener('click', function () {
            if (openChatId === null) return;
            postForm(apiUrl(openChatId, 'return'))
                .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
                .then(function (res) {
                    if (!res.ok) {
                        alert(res.data.error || labels.error);
                        return;
                    }
                    loadMessages();
                })
                .catch(function () { alert(labels.error); });
        });
    }

    // Закрыть чат (оператор)
    if (closeChatBtn) {
        closeChatBtn.addEventListener('click', function () {
            if (openChatId === null) return;
            if (!confirm(labels.closeConfirm)) return;
            postForm(apiUrl(openChatId, 'close'))
                .then(function () { closePanel(); })
                .catch(function () { alert(labels.error); });
        });
    }

    // Отправка
    form.addEventListener('submit', function (e) {
        e.preventDefault();
        var text = input.value.trim();
        if (!text) return;
        sendBtn.disabled = true;
        var url = openChatId === null ? mySendUrl : apiUrl(openChatId, 'reply');
        postForm(url, 'text=' + encodeURIComponent(text))
            .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
            .then(function (res) {
                if (!res.ok) {
                    alert(res.data.error || labels.error);
                    return;
                }
                input.value = '';
                input.style.height = 'auto';
                appendMessage(res.data.message);
                scrollBottom();
                if (isOperator && claimBar) {
                    // Ответ из очереди автоматически берёт чат в работу
                    claimBar.classList.add('hidden');
                    assignedToMe = true;
                    if (closeChatBtn) closeChatBtn.classList.remove('hidden');
                }
            })
            .catch(function () { alert(labels.error); })
            .finally(function () { sendBtn.disabled = false; input.focus(); });
    });

    input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            form.dispatchEvent(new Event('submit'));
        }
    });
    input.addEventListener('input', function () {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 120) + 'px';
    });

    document.addEventListener('visibilitychange', function () {
        if (!document.hidden && !panel.classList.contains('hidden')) loadMessages();
    });
});
