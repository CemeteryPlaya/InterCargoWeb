/**
 * Клиентский чат с техподдержкой (десктоп-страница /support/).
 *
 * Реалтайм: webpush-уведомления приходят через существующий воркер очереди,
 * страница сама опрашивает сервер редко (раз в 3 минуты) + обновляется при
 * возврате на вкладку и сразу после отправки.
 */
document.addEventListener('DOMContentLoaded', function () {
    var config = document.getElementById('support-config');
    if (!config) return;

    var POLL_INTERVAL_MS = 180000; // 3 минуты (webpush закрывает мгновенность)

    var messagesUrl = config.dataset.messagesUrl;
    var sendUrl = config.dataset.sendUrl;
    var readUrl = config.dataset.readUrl;
    var csrf = config.dataset.csrf;
    var labelSupport = config.dataset.labelSupport || 'Техподдержка';
    var labelError = config.dataset.labelError || 'Не удалось отправить сообщение.';

    var listEl = document.getElementById('support-messages');
    var emptyEl = document.getElementById('support-empty');
    var form = document.getElementById('support-send-form');
    var input = document.getElementById('support-input');
    var sendBtn = document.getElementById('support-send-btn');
    var errorEl = document.getElementById('support-error');

    var lastId = 0;
    var lastDate = '';

    function scrollBottom() {
        listEl.scrollTop = listEl.scrollHeight;
    }

    function appendDateSeparator(date) {
        var wrap = document.createElement('div');
        wrap.className = 'flex items-center justify-center my-3';
        var pill = document.createElement('span');
        pill.className = 'px-3 py-1 bg-gray-200 text-gray-500 text-[11px] font-medium rounded-full';
        pill.textContent = date;
        wrap.appendChild(pill);
        listEl.appendChild(wrap);
    }

    function appendMessage(msg) {
        if (emptyEl) { emptyEl.remove(); emptyEl = null; }
        if (msg.date !== lastDate) {
            appendDateSeparator(msg.date);
            lastDate = msg.date;
        }
        var mine = msg.author_role === 'client';
        var row = document.createElement('div');
        row.className = 'flex mb-2 ' + (mine ? 'justify-end' : 'justify-start');

        var bubble = document.createElement('div');
        bubble.className = 'max-w-[85%] rounded-2xl px-3.5 py-2.5 shadow-sm ' +
            (mine ? 'bg-primary text-white rounded-tr-sm'
                  : 'bg-white border border-gray-200 rounded-tl-sm');

        if (!mine) {
            var name = document.createElement('p');
            name.className = 'text-[11px] font-semibold text-primary mb-0.5';
            name.textContent = msg.sender_name || labelSupport;
            bubble.appendChild(name);
        }

        var text = document.createElement('p');
        text.className = 'text-[13px] leading-relaxed whitespace-pre-wrap break-words' +
            (mine ? '' : ' text-gray-800');
        text.textContent = msg.text;
        bubble.appendChild(text);

        var time = document.createElement('p');
        time.className = 'text-[10px] mt-1 text-right ' + (mine ? 'text-white/70' : 'text-gray-400');
        time.textContent = msg.time;
        bubble.appendChild(time);

        row.appendChild(bubble);
        listEl.appendChild(row);
        if (msg.id > lastId) lastId = msg.id;
    }

    function markRead() {
        fetch(readUrl, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrf },
        }).catch(function () { /* ignore */ });
    }

    function loadMessages() {
        fetch(messagesUrl + '?after_id=' + lastId, { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var msgs = data.messages || [];
                if (!msgs.length) return;
                msgs.forEach(appendMessage);
                scrollBottom();
                if (data.unread > 0) markRead();
            })
            .catch(function () { /* ignore, повторим по таймеру */ });
    }

    function showError(text) {
        errorEl.textContent = text;
        errorEl.classList.remove('hidden');
        setTimeout(function () { errorEl.classList.add('hidden'); }, 4000);
    }

    form.addEventListener('submit', function (e) {
        e.preventDefault();
        var text = input.value.trim();
        if (!text) return;
        sendBtn.disabled = true;
        fetch(sendUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-CSRFToken': csrf,
            },
            body: 'text=' + encodeURIComponent(text),
        })
            .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
            .then(function (res) {
                if (!res.ok) {
                    showError(res.data.error || labelError);
                    return;
                }
                input.value = '';
                input.style.height = 'auto';
                appendMessage(res.data.message);
                scrollBottom();
                loadMessages(); // подтягиваем возможные параллельные ответы
            })
            .catch(function () { showError(labelError); })
            .finally(function () { sendBtn.disabled = false; input.focus(); });
    });

    // Enter — отправить, Shift+Enter — новая строка
    input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            form.dispatchEvent(new Event('submit'));
        }
    });

    // Автовысота textarea
    input.addEventListener('input', function () {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 120) + 'px';
    });

    document.addEventListener('visibilitychange', function () {
        if (!document.hidden) loadMessages();
    });

    loadMessages();
    setInterval(loadMessages, POLL_INTERVAL_MS);
});
