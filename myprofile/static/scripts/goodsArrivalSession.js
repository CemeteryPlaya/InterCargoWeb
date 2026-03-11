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

    // ==================== Автосохранение ====================
    function scheduleSave() {
        if (saveTimer) clearTimeout(saveTimer);
        saveTimer = setTimeout(doSave, 2000);
    }

    function doSave() {
        if (isSaving) {
            scheduleSave();
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
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (data.success) {
                saveStatus.textContent = 'Сохранено (' + data.count + ' строк)';
                saveStatus.className = 'text-sm text-green-600';
            } else {
                saveStatus.textContent = 'Ошибка сохранения';
                saveStatus.className = 'text-sm text-red-600';
            }
        })
        .catch(function () {
            saveStatus.textContent = 'Ошибка связи';
            saveStatus.className = 'text-sm text-red-600';
        })
        .finally(function () {
            isSaving = false;
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
        // Возвращает {rowIndex, colIndex} для input внутри таблицы
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

    // ==================== Inline-автозаполнение (ghost text) ====================
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

    // ==================== Подтягивание владельца по трек-коду ====================
    function fetchTrackOwner(trackInput, ownerInput, weightInput) {
        var code = trackInput.value.trim();
        if (!code || !config.getOwnerUrl) return;
        // Не перезаписываем если уже заполнено
        if (ownerInput.value.trim()) return;

        fetch(config.getOwnerUrl + '?track_code=' + encodeURIComponent(code))
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.owner && !ownerInput.value.trim()) {
                    ownerInput.value = data.owner;
                    scheduleSave();
                    // Сразу переносим курсор на поле "Вес"
                    if (weightInput) weightInput.focus();
                }
            })
            .catch(function () {});
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
        trackInput.addEventListener('input', function () {
            scheduleSave();
            // Автоматически добавляем строку, если это последняя и в ней начали вводить
            var allRows = tableBody.querySelectorAll('tr');
            var lastRow = allRows[allRows.length - 1];
            if (tr === lastRow && trackInput.value.trim() !== '') {
                addRow(null, true);
            }
        });
        trackTd.appendChild(trackInput);

        var ownerTd = document.createElement('td');
        ownerTd.className = 'px-2 py-1 relative';
        var ownerInput = document.createElement('input');
        ownerInput.type = 'text';
        ownerInput.className = 'w-full border border-gray-200 rounded px-2 py-1 text-sm focus:ring-1 focus:ring-red-400';
        ownerInput.value = data ? data.owner_name : '';
        ownerInput.placeholder = 'Логин владельца';
        ownerInput.addEventListener('input', scheduleSave);
        ownerTd.appendChild(ownerInput);

        var weightTd = document.createElement('td');
        weightTd.className = 'px-2 py-1';
        var weightInput = document.createElement('input');
        weightInput.type = 'text';
        weightInput.className = 'w-full border border-gray-200 rounded px-2 py-1 text-sm focus:ring-1 focus:ring-red-400';
        weightInput.value = data ? data.weight || '' : '';
        weightInput.placeholder = '0.000';
        weightInput.addEventListener('input', scheduleSave);
        weightTd.appendChild(weightInput);

        var actionTd = document.createElement('td');
        actionTd.className = 'px-2 py-1 text-center';
        var delBtn = document.createElement('button');
        delBtn.type = 'button';
        delBtn.className = 'text-red-400 hover:text-red-600';
        delBtn.innerHTML = '<i class="ri-delete-bin-line"></i>';
        delBtn.tabIndex = -1; // Не фокусируется через Tab/клавиши, только мышью
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

        // Inline-автозаполнение для поля владельца
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
                // Подтягиваем владельца при переходе
                fetchTrackOwner(trackInput, ownerInput, weightInput);
            }
            handleArrowNav(e, trackInput);
        });
        ownerInput.addEventListener('keydown', function (e) {
            // Inline-автозаполнение: Enter/Tab подтверждает подсказку
            if (inlineAc.active && inlineAc.input === ownerInput) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    inlineAccept(ownerInput, weightInput);
                    return;
                } else if (e.key === 'Escape') {
                    e.preventDefault();
                    inlineReject(ownerInput);
                    return;
                } else if (e.key === 'Tab') {
                    inlineAccept(ownerInput, weightInput);
                    return;
                }
            }
            if (e.key === 'Enter' || (e.key === 'Tab' && !e.shiftKey)) {
                e.preventDefault();
                weightInput.focus();
            }
            handleArrowNav(e, ownerInput);
        });
        weightInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' || (e.key === 'Tab' && !e.shiftKey)) {
                e.preventDefault();
                addRow();
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
            // Пропускаем последнюю пустую строку — она автоматическая
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

    // ==================== Автоподсказки владельцев (inline ghost text) ====================
    function debounce(func, wait) {
        var timeout;
        return function () {
            var ctx = this, args = arguments;
            clearTimeout(timeout);
            timeout = setTimeout(function () { func.apply(ctx, args); }, wait);
        };
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

        input.addEventListener('blur', function () {
            if (inlineAc.active && inlineAc.input === input) {
                inlineReject(input);
            }
        });
    }

    // ==================== Переключение вида ====================
    toggleBtn.addEventListener('click', function () {
        if (isTableView) {
            // Таблица → Текст
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
            // Текст → Таблица
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
        // Синхронное сохранение перед сабмитом
        if (saveTimer) clearTimeout(saveTimer);

        var items = collectItems();
        var xhr = new XMLHttpRequest();
        xhr.open('POST', config.saveUrl, false); // синхронный
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.setRequestHeader('X-CSRFToken', config.csrfToken);
        xhr.send(JSON.stringify({ items: items }));
    });

    // ==================== Инициализация ====================
    if (config.initialItems && config.initialItems.length > 0) {
        config.initialItems.forEach(function (item) {
            addRow(item);
        });
    } else {
        addRow();
    }
});
