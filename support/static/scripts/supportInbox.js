/**
 * Операторский inbox чатов поддержки (десктоп /support/inbox/).
 *
 * Вкладки: Очередь (не назначены) / Мои / Все (только привилегированные).
 * Ответ на чат из очереди автоматически берёт его в работу.
 * Поллинг редкий (3 мин) — мгновенность обеспечивают push-уведомления.
 */
document.addEventListener('DOMContentLoaded', function () {
    var config = document.getElementById('inbox-config');
    if (!config) return;

    var POLL_INTERVAL_MS = 180000;

    var inboxUrl = config.dataset.inboxUrl;
    var chatBaseUrl = config.dataset.chatBaseUrl;
    var directorsUrl = config.dataset.directorsUrl;
    var csrf = config.dataset.csrf;
    var labels = {
        queue: config.dataset.labelQueue,
        assigned: config.dataset.labelAssigned,
        closed: config.dataset.labelClosed,
        conflict: config.dataset.labelConflict,
        closeConfirm: config.dataset.labelCloseConfirm,
        error: config.dataset.labelError,
    };

    var listEl = document.getElementById('inbox-list');
    var emptyEl = document.getElementById('inbox-empty');
    var tabs = document.querySelectorAll('.inbox-tab');
    var placeholder = document.getElementById('chat-placeholder');
    var chatArea = document.getElementById('chat-area');
    var chatTitle = document.getElementById('chat-title');
    var chatSubtitle = document.getElementById('chat-subtitle');
    var claimBtn = document.getElementById('chat-claim-btn');
    var closeBtn = document.getElementById('chat-close-btn');
    var escalateBtn = document.getElementById('chat-escalate-btn');
    var returnBtn = document.getElementById('chat-return-btn');
    var escalateModal = document.getElementById('escalate-modal');
    var escalateList = document.getElementById('escalate-list');
    var escalateCancel = document.getElementById('escalate-cancel');
    var escalateBackdrop = document.getElementById('escalate-backdrop');
    var messagesEl = document.getElementById('chat-messages');
    var replyForm = document.getElementById('chat-reply-form');
    var replyInput = document.getElementById('chat-reply-input');
    var replySend = document.getElementById('chat-reply-send');
    var chatError = document.getElementById('chat-error');

    var inboxData = { queue: [], mine: [], all: [] };
    var activeTab = 'queue';
    var activeChatId = null;
    var activeChat = null;
    var lastId = 0;
    var lastDate = '';

    function apiUrl(chatId, action) {
        return chatBaseUrl + chatId + '/' + action + '/';
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

    // ==================== Список чатов ====================

    function loadInbox() {
        fetch(inboxUrl, { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                inboxData = data;
                renderTabs();
                renderList();
            })
            .catch(function () { /* повторим по таймеру */ });
    }

    function renderTabs() {
        var qBadge = document.getElementById('tab-badge-queue');
        var mBadge = document.getElementById('tab-badge-mine');
        var qCount = (inboxData.queue || []).length;
        var mUnread = (inboxData.mine || []).reduce(function (s, c) { return s + (c.unread || 0); }, 0);
        if (qBadge) {
            qBadge.textContent = qCount;
            qBadge.classList.toggle('hidden', qCount === 0);
        }
        if (mBadge) {
            mBadge.textContent = mUnread;
            mBadge.classList.toggle('hidden', mUnread === 0);
        }
    }

    function renderList() {
        var chats = inboxData[activeTab] || [];
        listEl.innerHTML = '';
        emptyEl.classList.toggle('hidden', chats.length > 0);
        listEl.classList.toggle('hidden', chats.length === 0);

        chats.forEach(function (chat) {
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'w-full text-left px-4 py-3 hover:bg-gray-50 transition flex items-start gap-3' +
                (chat.id === activeChatId ? ' bg-red-50' : '');

            var icon = document.createElement('div');
            icon.className = 'w-9 h-9 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5 ' +
                (chat.assigned_to_name ? 'bg-primary bg-opacity-10 text-primary' : 'bg-orange-100 text-orange-600');
            icon.innerHTML = '<i class="ri-user-line"></i>';

            var body = document.createElement('div');
            body.className = 'flex-1 min-w-0';

            var top = document.createElement('div');
            top.className = 'flex items-center justify-between gap-2';
            var name = document.createElement('p');
            name.className = 'font-semibold text-sm truncate';
            name.textContent = chat.title + (chat.status === 'closed' ? ' ✓' : '');
            var time = document.createElement('span');
            time.className = 'text-[10px] text-gray-400 flex-shrink-0';
            time.textContent = chat.last_time;
            top.appendChild(name);
            top.appendChild(time);

            var bottom = document.createElement('div');
            bottom.className = 'flex items-center justify-between gap-2 mt-0.5';
            var preview = document.createElement('p');
            preview.className = 'text-xs text-gray-400 truncate';
            preview.textContent = chat.last_message;
            bottom.appendChild(preview);
            if (chat.unread > 0) {
                var badge = document.createElement('span');
                badge.className = 'inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 text-[10px] font-bold rounded-full text-white bg-primary flex-shrink-0';
                badge.textContent = chat.unread;
                bottom.appendChild(badge);
            }

            body.appendChild(top);
            body.appendChild(bottom);
            if (activeTab === 'all' && chat.assigned_to_name) {
                var owner = document.createElement('p');
                owner.className = 'text-[10px] text-gray-400 mt-0.5';
                owner.textContent = labels.assigned + ' ' + chat.assigned_to_name;
                body.appendChild(owner);
            }

            btn.appendChild(icon);
            btn.appendChild(body);
            btn.addEventListener('click', function () { openChat(chat.id); });
            listEl.appendChild(btn);
        });
    }

    tabs.forEach(function (tab) {
        tab.addEventListener('click', function () {
            activeTab = tab.dataset.tab;
            tabs.forEach(function (t) {
                var active = t === tab;
                t.classList.toggle('border-primary', active);
                t.classList.toggle('text-primary', active);
                t.classList.toggle('border-transparent', !active);
                t.classList.toggle('text-gray-500', !active);
            });
            renderList();
        });
    });

    // ==================== Чат ====================

    function appendDateSeparator(date) {
        var wrap = document.createElement('div');
        wrap.className = 'flex items-center justify-center my-3';
        wrap.innerHTML = '<span class="px-3 py-1 bg-gray-200 text-gray-500 text-[11px] font-medium rounded-full"></span>';
        wrap.querySelector('span').textContent = date;
        messagesEl.appendChild(wrap);
    }

    function appendMessage(msg) {
        if (msg.date !== lastDate) {
            appendDateSeparator(msg.date);
            lastDate = msg.date;
        }

        if (msg.author_role === 'system') {
            var sys = document.createElement('div');
            sys.className = 'flex justify-center mb-2';
            sys.innerHTML = '<span class="px-3 py-1 bg-gray-100 text-gray-400 text-[11px] rounded-full text-center"></span>';
            sys.querySelector('span').textContent = msg.text;
            messagesEl.appendChild(sys);
            if (msg.id > lastId) lastId = msg.id;
            return;
        }

        var mine = msg.author_role === 'staff';
        var row = document.createElement('div');
        row.className = 'flex mb-2 ' + (mine ? 'justify-end' : 'justify-start');

        var bubble = document.createElement('div');
        bubble.className = 'max-w-[75%] rounded-2xl px-3.5 py-2.5 shadow-sm ' +
            (mine ? 'bg-primary text-white rounded-tr-sm'
                  : 'bg-gray-100 border border-gray-200 rounded-tl-sm');

        if (msg.sender_name) {
            var name = document.createElement('p');
            name.className = 'text-[11px] font-semibold mb-0.5 ' + (mine ? 'text-white/80' : 'text-primary');
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
        messagesEl.appendChild(row);
        if (msg.id > lastId) lastId = msg.id;
    }

    function updateChatHeader(chat) {
        activeChat = chat;
        chatTitle.textContent = chat.title;
        if (chat.status === 'closed') {
            chatSubtitle.textContent = labels.closed;
        } else if (chat.assigned_to_name) {
            chatSubtitle.textContent = labels.assigned + ' ' + chat.assigned_to_name;
        } else {
            chatSubtitle.textContent = labels.queue;
        }
        claimBtn.classList.toggle('hidden', !!chat.assigned_to_name || chat.status === 'closed');
        closeBtn.classList.toggle('hidden', !chat.assigned_to_me || chat.status === 'closed');
        escalateBtn.classList.toggle('hidden', !chat.assigned_to_me || chat.status === 'closed');
        returnBtn.classList.toggle('hidden', !chat.can_return || chat.status === 'closed');
    }

    function openChat(chatId) {
        activeChatId = chatId;
        lastId = 0;
        lastDate = '';
        messagesEl.innerHTML = '';
        placeholder.classList.add('hidden');
        chatArea.classList.remove('hidden');
        renderList();
        loadChatMessages(true);
        replyInput.focus();
    }

    function loadChatMessages(markAsRead) {
        if (activeChatId === null) return;
        var chatId = activeChatId;
        fetch(apiUrl(chatId, 'messages') + '?after_id=' + lastId, { credentials: 'same-origin' })
            .then(function (r) {
                if (r.status === 403) {
                    // Доступ потерян (чат передан) — закрываем окно чата
                    if (chatId === activeChatId) {
                        activeChatId = null;
                        chatArea.classList.add('hidden');
                        placeholder.classList.remove('hidden');
                        loadInbox();
                    }
                    return null;
                }
                return r.json();
            })
            .then(function (data) {
                if (!data) return;
                if (chatId !== activeChatId) return; // пользователь переключил чат
                if (data.chat) updateChatHeader(data.chat);
                (data.messages || []).forEach(appendMessage);
                if ((data.messages || []).length) {
                    messagesEl.scrollTop = messagesEl.scrollHeight;
                }
                if (markAsRead && data.chat &&
                        (data.chat.assigned_to_me || data.chat.unread > 0)) {
                    postForm(apiUrl(chatId, 'read')).then(loadInbox).catch(function () {});
                }
            })
            .catch(function () { /* повторим по таймеру */ });
    }

    function showChatError(text) {
        chatError.textContent = text;
        chatError.classList.remove('hidden');
        setTimeout(function () { chatError.classList.add('hidden'); }, 4000);
    }

    claimBtn.addEventListener('click', function () {
        if (activeChatId === null) return;
        postForm(apiUrl(activeChatId, 'claim'))
            .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
            .then(function (res) {
                if (res.ok) {
                    loadChatMessages(true);
                    loadInbox();
                } else {
                    showChatError(res.data.error || labels.conflict);
                    loadInbox();
                }
            })
            .catch(function () { showChatError(labels.error); });
    });

    closeBtn.addEventListener('click', function () {
        if (activeChatId === null) return;
        if (!confirm(labels.closeConfirm)) return;
        postForm(apiUrl(activeChatId, 'close'))
            .then(function () {
                loadChatMessages(false);
                loadInbox();
            })
            .catch(function () { showChatError(labels.error); });
    });

    // ==================== Эскалация директору ====================

    function closeEscalateModal() {
        escalateModal.classList.add('hidden');
    }

    escalateBtn.addEventListener('click', function () {
        if (activeChatId === null) return;
        escalateList.innerHTML = '';
        fetch(directorsUrl, { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                (data.directors || []).forEach(function (d) {
                    var btn = document.createElement('button');
                    btn.type = 'button';
                    btn.className = 'w-full flex items-center gap-3 px-3 py-2.5 border border-gray-200 rounded-lg hover:bg-violet-50 hover:border-violet-300 transition text-left';
                    btn.innerHTML = '<div class="w-8 h-8 rounded-full bg-violet-100 text-violet-600 flex items-center justify-center flex-shrink-0"><i class="ri-user-star-line"></i></div>';
                    var name = document.createElement('span');
                    name.className = 'text-sm font-medium';
                    name.textContent = d.name;
                    btn.appendChild(name);
                    btn.addEventListener('click', function () { escalateTo(d.id); });
                    escalateList.appendChild(btn);
                });
                if (!(data.directors || []).length) {
                    escalateList.innerHTML = '<p class="text-sm text-gray-400 text-center py-3">—</p>';
                }
                escalateModal.classList.remove('hidden');
            })
            .catch(function () { showChatError(labels.error); });
    });

    function escalateTo(directorId) {
        var chatId = activeChatId;
        closeEscalateModal();
        if (chatId === null) return;
        postForm(apiUrl(chatId, 'escalate'), 'director_id=' + encodeURIComponent(directorId))
            .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
            .then(function (res) {
                if (!res.ok) {
                    showChatError(res.data.error || labels.error);
                    return;
                }
                // Чат передан — обновляем шапку/списки (не-привилегированный
                // оператор потеряет к нему доступ при следующем действии)
                loadChatMessages(false);
                loadInbox();
            })
            .catch(function () { showChatError(labels.error); });
    }

    escalateCancel.addEventListener('click', closeEscalateModal);
    escalateBackdrop.addEventListener('click', closeEscalateModal);

    returnBtn.addEventListener('click', function () {
        if (activeChatId === null) return;
        postForm(apiUrl(activeChatId, 'return'))
            .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
            .then(function (res) {
                if (!res.ok) {
                    showChatError(res.data.error || labels.error);
                    return;
                }
                loadChatMessages(false);
                loadInbox();
            })
            .catch(function () { showChatError(labels.error); });
    });

    replyForm.addEventListener('submit', function (e) {
        e.preventDefault();
        if (activeChatId === null) return;
        var text = replyInput.value.trim();
        if (!text) return;
        replySend.disabled = true;
        postForm(apiUrl(activeChatId, 'reply'), 'text=' + encodeURIComponent(text))
            .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
            .then(function (res) {
                if (!res.ok) {
                    showChatError(res.data.error || labels.error);
                    return;
                }
                replyInput.value = '';
                replyInput.style.height = 'auto';
                appendMessage(res.data.message);
                messagesEl.scrollTop = messagesEl.scrollHeight;
                loadChatMessages(false); // системное «взял в работу» и статусы
                loadInbox();
            })
            .catch(function () { showChatError(labels.error); })
            .finally(function () { replySend.disabled = false; replyInput.focus(); });
    });

    replyInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            replyForm.dispatchEvent(new Event('submit'));
        }
    });
    replyInput.addEventListener('input', function () {
        replyInput.style.height = 'auto';
        replyInput.style.height = Math.min(replyInput.scrollHeight, 120) + 'px';
    });

    document.addEventListener('visibilitychange', function () {
        if (!document.hidden) {
            loadInbox();
            loadChatMessages(false);
        }
    });

    loadInbox();
    setInterval(function () {
        loadInbox();
        loadChatMessages(false);
    }, POLL_INTERVAL_MS);
});
