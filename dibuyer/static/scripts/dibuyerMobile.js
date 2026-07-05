/**
 * Чат Di.Buyer на мобильной странице «Сообщения».
 *
 * Одна полноэкранная панель работает в двух режимах:
 * - клиент: общий чат / ветка своей заявки (API /dibuyer/api/my/... с order_id);
 * - сотрудник Di.Buyer: любой чат по id (API /dibuyer/api/chat/<id>/...);
 *   для заявки без чата сотрудник сначала открывает ветку
 *   (POST /dibuyer/api/order/<id>/chat/).
 *
 * Реалтайм — webpush через воркер; страница опрашивает сервер редко
 * (раз в 3 минуты, только при открытой панели) + при возврате на вкладку.
 */
document.addEventListener('DOMContentLoaded', function () {
    var config = document.getElementById('dibuyer-mobile-config');
    if (!config) return;

    var POLL_INTERVAL_MS = 180000;

    var isStaff = config.dataset.isStaff === 'true';
    var myMessagesUrl = config.dataset.myMessagesUrl;
    var mySendUrl = config.dataset.mySendUrl;
    var myReadUrl = config.dataset.myReadUrl;
    var chatBaseUrl = config.dataset.chatBaseUrl;
    var orderChatBaseUrl = config.dataset.orderChatBaseUrl;
    var errorLabel = config.dataset.labelError || 'Ошибка. Попробуйте ещё раз.';
    var csrfInput = document.getElementById('csrf-token');
    var csrf = csrfInput ? csrfInput.value : '';

    var panel = document.getElementById('dibuyer-panel');
    var panelTitle = document.getElementById('dibuyer-panel-title');
    var scrollEl = document.getElementById('dibuyer-panel-scroll');
    var emptyEl = document.getElementById('dibuyer-panel-empty');
    var form = document.getElementById('dibuyer-panel-form');
    var input = document.getElementById('dibuyer-panel-input');
    var sendBtn = document.getElementById('dibuyer-panel-send');
    var backBtn = document.getElementById('dibuyer-back-btn');
    var bottomNav = document.getElementById('mobile-bottom-nav');

    var openChatId = null;   // сотрудник: id чата
    var openOrderId = null;  // клиент: ветка заявки (null = общий чат)
    var lastId = 0;
    var lastDate = '';
    var pollTimer = null;

    function chatUrl(action) {
        return chatBaseUrl + openChatId + '/' + action + '/';
    }

    function withOrderId(url) {
        return openOrderId ? url + (url.indexOf('?') === -1 ? '?' : '&') + 'order_id=' + openOrderId : url;
    }

    function scrollBottom() {
        scrollEl.scrollTop = scrollEl.scrollHeight;
    }

    function clearMessages() {
        scrollEl.querySelectorAll('.dibuyer-msg-node').forEach(function (n) { n.remove(); });
        lastId = 0;
        lastDate = '';
    }

    function showEmpty(show) {
        if (emptyEl) emptyEl.style.display = show ? '' : 'none';
    }

    function appendDateSeparator(date) {
        var wrap = document.createElement('div');
        wrap.className = 'dibuyer-msg-node flex items-center justify-center my-3';
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

        // «Мои» сообщения: у клиента — свои, у сотрудника — сообщения Di.Buyer
        var mine = isStaff ? msg.author_role === 'staff' : msg.author_role === 'client';
        var row = document.createElement('div');
        row.className = 'dibuyer-msg-node flex mb-2 ' + (mine ? 'justify-end' : 'justify-start');

        var bubble = document.createElement('div');
        bubble.className = 'max-w-[85%] rounded-2xl px-3.5 py-2.5 shadow-sm ' +
            (mine ? 'text-white rounded-tr-sm'
                  : 'bg-white border border-gray-200 rounded-tl-sm');
        if (mine) bubble.style.background = '#7c3aed';

        if (!mine && msg.sender_name) {
            var name = document.createElement('p');
            name.className = 'text-[11px] font-semibold mb-0.5';
            name.style.color = '#7c3aed';
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
        if (isStaff) {
            if (openChatId !== null) postForm(chatUrl('read')).catch(function () {});
        } else {
            postForm(myReadUrl, openOrderId ? 'order_id=' + openOrderId : '').catch(function () {});
        }
    }

    function loadMessages(initial) {
        var url;
        if (isStaff) {
            if (openChatId === null) return;
            url = chatUrl('messages') + '?after_id=' + lastId;
        } else {
            url = withOrderId(myMessagesUrl + '?after_id=' + lastId);
        }
        fetch(url, { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (data) {
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

    function openPanel(title) {
        clearMessages();
        showEmpty(true);
        panelTitle.textContent = title || 'Di.Buyer';
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
        openOrderId = null;
    }

    document.querySelectorAll('.dibuyer-chat-open').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var chatId = btn.dataset.chatId ? parseInt(btn.dataset.chatId, 10) : null;
            var orderId = btn.dataset.orderId ? parseInt(btn.dataset.orderId, 10) : null;
            var title = btn.dataset.chatTitle;
            var badge = btn.querySelector('.rounded-full.text-white');
            if (badge) badge.remove();

            if (isStaff && chatId === null && orderId !== null) {
                // Заявка без чата: сначала открываем ветку
                postForm(orderChatBaseUrl + orderId + '/chat/')
                    .then(function (r) { return r.json(); })
                    .then(function (data) {
                        if (!data.chat_id) {
                            alert(data.error || errorLabel);
                            return;
                        }
                        btn.dataset.chatId = data.chat_id;
                        openChatId = data.chat_id;
                        openOrderId = null;
                        openPanel(title);
                    })
                    .catch(function () { alert(errorLabel); });
                return;
            }
            openChatId = chatId;
            openOrderId = isStaff ? null : orderId;
            openPanel(title);
        });
    });

    if (backBtn) backBtn.addEventListener('click', closePanel);

    form.addEventListener('submit', function (e) {
        e.preventDefault();
        var text = input.value.trim();
        if (!text) return;
        sendBtn.disabled = true;
        var url, body = 'text=' + encodeURIComponent(text);
        if (isStaff) {
            if (openChatId === null) { sendBtn.disabled = false; return; }
            url = chatUrl('reply');
        } else {
            url = mySendUrl;
            if (openOrderId) body += '&order_id=' + openOrderId;
        }
        postForm(url, body)
            .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
            .then(function (res) {
                if (!res.ok) {
                    alert(res.data.error || errorLabel);
                    return;
                }
                input.value = '';
                input.style.height = 'auto';
                appendMessage(res.data.message);
                scrollBottom();
            })
            .catch(function () { alert(errorLabel); })
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
