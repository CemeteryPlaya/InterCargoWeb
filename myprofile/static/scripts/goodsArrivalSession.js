document.addEventListener('DOMContentLoaded', function () {
    var config = SESSION_CONFIG;
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

    // ==================== Автосохранение ====================
    function scheduleSave() {
        if (saveTimer) clearTimeout(saveTimer);
        saveTimer = setTimeout(doSave, 2000);
    }

    function doSave(callback) {
        if (isSaving) {
            scheduleSave();
            if (callback) callback();
            return;
        }
        isSaving = true;
        saveStatus.textContent = 'Сохранение...';
        saveStatus.className = 'text-sm text-yellow-600';

        var items = collectItems();

        fetch(config.saveUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': config.csrfToken
            },
            body: JSON.stringify({ items: items })
        })
        .then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        })
        .then(function (data) {
            if (data.success) {
                saveStatus.textContent = 'Сохранено (' + data.count + ' строк)';
                saveStatus.className = 'text-sm text-green-600';
                connectionState.failCount = 0;
                if (connectionState.isLost) showConnectionRestored();
                if (data.occupied && data.occupied.length > 0) {
                    showOccupiedWarning(data.occupied);
                } else {
                    hideOccupiedWarning();
                }
                if (data.invalid_chars && data.invalid_chars.length > 0) {
                    showInvalidCharsWarning(data.invalid_chars);
                } else {
                    hideInvalidCharsWarning();
                }
            } else {
                throw new Error('save failed');
            }
        })
        .catch(function () {
            connectionState.failCount++;
            saveStatus.textContent = 'Ошибка связи';
            saveStatus.className = 'text-sm text-red-600';
            if (connectionState.failCount >= 2) {
                showConnectionLost();
            }
        })
        .finally(function () {
            isSaving = false;
            if (callback) callback();
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
    document.getElementById('complete_form').addEventListener('submit', function (e) {
        if (saveTimer) clearTimeout(saveTimer);

        var items = collectItems();
        var xhr = new XMLHttpRequest();
        xhr.open('POST', config.saveUrl, false);
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.setRequestHeader('X-CSRFToken', config.csrfToken);
        xhr.send(JSON.stringify({ items: items }));
    });

    // ==================== Инициализация ====================
    if (config.initialItems && config.initialItems.length > 0) {
        config.initialItems.forEach(function (item) {
            addRow(item);
        });
        validateAllRows();
    } else {
        addRow();
    }
});
