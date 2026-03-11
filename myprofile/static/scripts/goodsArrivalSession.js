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

    // ==================== Подтягивание владельца по трек-коду ====================
    function fetchTrackOwner(trackInput, ownerInput) {
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
                }
            })
            .catch(function () {});
    }

    // ==================== Таблица ====================
    function addRow(data) {
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
        trackInput.addEventListener('input', scheduleSave);
        trackTd.appendChild(trackInput);

        var ownerTd = document.createElement('td');
        ownerTd.className = 'px-2 py-1 relative';
        var ownerInput = document.createElement('input');
        ownerInput.type = 'text';
        ownerInput.className = 'w-full border border-gray-200 rounded px-2 py-1 text-sm focus:ring-1 focus:ring-red-400';
        ownerInput.value = data ? data.owner_name : '';
        ownerInput.placeholder = 'Логин владельца';
        ownerInput.addEventListener('input', scheduleSave);
        setupOwnerAutocomplete(ownerInput);
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

        // Фокус на последний трек-код
        if (!data) trackInput.focus();

        // При потере фокуса трек-кодом — подтягиваем владельца
        trackInput.addEventListener('blur', function () {
            fetchTrackOwner(trackInput, ownerInput);
        });

        // Enter + Tab навигация
        trackInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' || e.key === 'Tab') {
                e.preventDefault();
                ownerInput.focus();
                // Подтягиваем владельца при переходе
                fetchTrackOwner(trackInput, ownerInput);
            }
            handleArrowNav(e, trackInput);
        });
        ownerInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' || (e.key === 'Tab' && !e.shiftKey)) {
                e.preventDefault();
                weightInput.focus();
            }
            if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
                handleArrowNav(e, ownerInput);
            }
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
        tableBody.querySelectorAll('tr').forEach(function (row) {
            row.querySelectorAll('input').forEach(function (input) {
                if (!input.value.trim()) empty++;
            });
        });
        if (empty > 0) {
            emptyCellsWarning.classList.remove('hidden');
            emptyCellsCount.textContent = empty;
        } else {
            emptyCellsWarning.classList.add('hidden');
        }
    }

    addRowBtn.addEventListener('click', function () { addRow(); });

    // ==================== Автоподсказки владельцев ====================
    function setupOwnerAutocomplete(input) {
        var dropdown = null;
        var debounceTimer = null;
        var selectedIndex = -1;

        input.addEventListener('input', function () {
            var query = input.value.trim();
            if (query.length < 2) {
                removeDropdown();
                return;
            }
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(function () {
                fetch(config.searchUsersUrl + '?q=' + encodeURIComponent(query))
                    .then(function (r) { return r.json(); })
                    .then(function (data) {
                        removeDropdown();
                        if (!data.results || !data.results.length) return;
                        selectedIndex = -1;
                        dropdown = document.createElement('div');
                        dropdown.className = 'absolute z-50 bg-white border border-gray-200 rounded shadow-lg max-h-40 overflow-y-auto text-sm left-0 right-0 top-full';
                        data.results.forEach(function (r, idx) {
                            var item = document.createElement('div');
                            item.className = 'px-3 py-1.5 cursor-pointer hover:bg-gray-100';
                            item.textContent = r.username;
                            item.dataset.index = idx;
                            item.addEventListener('mousedown', function (e) {
                                e.preventDefault();
                                input.value = r.username;
                                removeDropdown();
                                scheduleSave();
                            });
                            dropdown.appendChild(item);
                        });
                        // Вставляем в ownerTd (relative) для корректного позиционирования
                        input.parentNode.appendChild(dropdown);
                    })
                    .catch(function () {});
            }, 300);
        });

        // Навигация по dropdown стрелками
        input.addEventListener('keydown', function (e) {
            if (!dropdown) return;
            var items = dropdown.querySelectorAll('div[data-index]');
            if (!items.length) return;

            if (e.key === 'ArrowDown') {
                e.preventDefault();
                selectedIndex = Math.min(selectedIndex + 1, items.length - 1);
                highlightItem(items);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                selectedIndex = Math.max(selectedIndex - 1, 0);
                highlightItem(items);
            } else if (e.key === 'Enter' && selectedIndex >= 0) {
                e.preventDefault();
                e.stopPropagation();
                input.value = items[selectedIndex].textContent;
                removeDropdown();
                scheduleSave();
            } else if (e.key === 'Escape') {
                removeDropdown();
            }
        });

        function highlightItem(items) {
            items.forEach(function (el, i) {
                el.classList.toggle('bg-blue-100', i === selectedIndex);
                el.classList.toggle('hover:bg-gray-100', i !== selectedIndex);
            });
            if (selectedIndex >= 0 && items[selectedIndex]) {
                items[selectedIndex].scrollIntoView({ block: 'nearest' });
            }
        }

        input.addEventListener('blur', function () {
            setTimeout(removeDropdown, 200);
        });

        function removeDropdown() {
            if (dropdown) {
                dropdown.remove();
                dropdown = null;
                selectedIndex = -1;
            }
        }
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
