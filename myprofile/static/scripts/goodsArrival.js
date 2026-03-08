document.addEventListener('DOMContentLoaded', function () {
    var formEl = document.getElementById('goods_arrival_form');
    var getOwnerUrl = formEl.dataset.getOwnerUrl;
    var searchUsersUrl = formEl.dataset.searchUsersUrl;

    var trackCodesArea = document.getElementById('track_codes');
    var ownerUsernamesArea = document.getElementById('owner_usernames');
    var weightsArea = document.getElementById('weights');

    var standardView = document.getElementById('standard_view');
    var tableView = document.getElementById('table_view');
    var tracksTableBody = document.getElementById('tracks_table_body');
    var addRowBtn = document.getElementById('add_row_btn');
    var formToggleBtn = document.getElementById('form_toggle_btn');

    // Счётчики
    var tableRowCounter = document.getElementById('table_row_counter');
    var textCountTracks = document.getElementById('text_count_tracks');
    var textCountOwners = document.getElementById('text_count_owners');
    var textCountWeights = document.getElementById('text_count_weights');
    var emptyCellsWarning = document.getElementById('empty_cells_warning');
    var emptyCellsCount = document.getElementById('empty_cells_count');

    var isTableMode = false;

    // ============================================
    // Счётчик строк текстового вида
    // ============================================
    function countNonEmptyLines(text) {
        return text.split('\n').filter(function (s) { return s.trim() !== ''; }).length;
    }

    function updateTextCounters() {
        var tc = countNonEmptyLines(trackCodesArea.value);
        var oc = countNonEmptyLines(ownerUsernamesArea.value);
        var wc = countNonEmptyLines(weightsArea.value);
        textCountTracks.textContent = tc > 0 ? '(' + tc + ')' : '';
        textCountOwners.textContent = oc > 0 ? '(' + oc + ')' : '';
        textCountWeights.textContent = wc > 0 ? '(' + wc + ')' : '';
    }

    trackCodesArea.addEventListener('input', updateTextCounters);
    ownerUsernamesArea.addEventListener('input', updateTextCounters);
    weightsArea.addEventListener('input', updateTextCounters);
    updateTextCounters();

    // ============================================
    // Счётчик строк и пустых ячеек табличного вида
    // ============================================
    function updateTableRowCounter() {
        var rows = tracksTableBody.querySelectorAll('tr');
        var filledCount = 0;
        rows.forEach(function (row) {
            var c = row.querySelector('.track-code-input').value.trim();
            var o = row.querySelector('.owner-input').value.trim();
            var w = row.querySelector('.weight-input').value.trim();
            if (c || o || w) filledCount++;
        });
        tableRowCounter.textContent = 'Строк: ' + filledCount;
    }

    function getEmptyCells() {
        // Возвращает массив input-элементов, которые пусты в строках с хотя бы одним заполненным полем
        var rows = tracksTableBody.querySelectorAll('tr');
        var emptyCells = [];
        rows.forEach(function (row) {
            var inputs = [
                row.querySelector('.track-code-input'),
                row.querySelector('.owner-input'),
                row.querySelector('.weight-input')
            ];
            var values = inputs.map(function (inp) { return inp.value.trim(); });
            var hasAny = values.some(function (v) { return v !== ''; });
            if (hasAny) {
                inputs.forEach(function (inp, i) {
                    if (values[i] === '') emptyCells.push(inp);
                });
            }
        });
        return emptyCells;
    }

    function updateEmptyCellsCounter() {
        if (!isTableMode) {
            emptyCellsWarning.classList.add('hidden');
            return;
        }
        var empty = getEmptyCells();
        if (empty.length > 0) {
            emptyCellsWarning.classList.remove('hidden');
            emptyCellsCount.textContent = empty.length;
        } else {
            emptyCellsWarning.classList.add('hidden');
        }
    }

    function clearAllRedBorders() {
        tracksTableBody.querySelectorAll('.border-red-500').forEach(function (inp) {
            inp.classList.remove('border-red-500', 'border-2');
            inp.classList.add('border');
        });
    }

    function toggleFormView() {
        isTableMode = !isTableMode;

        if (isTableMode) {
            standardView.classList.add('hidden');
            tableView.classList.remove('hidden');
            trackCodesArea.removeAttribute('required');
            ownerUsernamesArea.removeAttribute('required');
            weightsArea.removeAttribute('required');
            syncToTable();
            formToggleBtn.innerHTML = '<i class="ri-file-text-line"></i> Переключить на текстовый вид';
            updateTableRowCounter();
            updateEmptyCellsCounter();
        } else {
            standardView.classList.remove('hidden');
            tableView.classList.add('hidden');
            trackCodesArea.setAttribute('required', '');
            ownerUsernamesArea.setAttribute('required', '');
            weightsArea.setAttribute('required', '');
            syncFromTable();
            clearAllRedBorders();
            formToggleBtn.innerHTML = '<i class="ri-table-line"></i> Переключить на табличный вид';
            updateTextCounters();
            updateEmptyCellsCounter();
        }
    }

    function debounce(func, wait) {
        var timeout;
        return function () {
            var context = this;
            var args = arguments;
            clearTimeout(timeout);
            timeout = setTimeout(function () { func.apply(context, args); }, wait);
        };
    }

    // ============================================
    // Inline-автозаполнение (ghost text в поле ввода)
    // ============================================
    var inlineAc = {
        active: false,
        input: null,
        typedLen: 0,
        suggestion: '',
        results: []
    };

    function inlineClear() {
        inlineAc.active = false;
        inlineAc.input = null;
        inlineAc.typedLen = 0;
        inlineAc.suggestion = '';
        inlineAc.results = [];
    }

    function inlineApply(input, results, typedQuery) {
        if (!results.length || !typedQuery) {
            inlineClear();
            return;
        }
        // Если пользователь уже ввёл больше символов, чем было в запросе — не подставляем
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

    function inlineAccept(input) {
        if (!inlineAc.active || inlineAc.input !== input) return false;
        input.value = inlineAc.suggestion;
        input.setSelectionRange(input.value.length, input.value.length);
        inlineClear();

        var td = input.closest('td');
        if (td) {
            var nextTd = td.nextElementSibling;
            if (nextTd) {
                var next = nextTd.querySelector('input');
                if (next) next.focus();
            }
        }
        return true;
    }

    function inlineReject(input) {
        if (!inlineAc.active || inlineAc.input !== input) return;
        var typed = input.value.substring(0, inlineAc.typedLen);
        input.value = typed;
        input.setSelectionRange(typed.length, typed.length);
        inlineClear();
    }

    // ============================================
    // Dropdown автозаполнения (для textarea)
    // ============================================
    var acDropdown = null;
    var acSelectedIndex = -1;
    var acActiveInput = null;
    var acResults = [];

    function acRemove() {
        if (acDropdown) {
            acDropdown.remove();
            acDropdown = null;
        }
        acSelectedIndex = -1;
        acResults = [];
        acActiveInput = null;
    }

    // ============================================
    // Нумерация строк
    // ============================================
    function updateRowNumbers() {
        var rows = tracksTableBody.querySelectorAll('tr');
        rows.forEach(function (row, i) {
            var numCell = row.querySelector('.row-number');
            if (numCell) numCell.textContent = i + 1;
        });
    }

    // ============================================
    // Создание строки таблицы
    // ============================================
    function createRow(code, owner, weight) {
        code = code || '';
        owner = owner || '';
        weight = weight || '';

        var tr = document.createElement('tr');
        tr.innerHTML =
            '<td class="border px-2 py-2 text-center text-sm text-gray-400 row-number w-12"></td>' +
            '<td class="border px-4 py-2">' +
            '<input type="text" class="w-full border rounded px-2 py-1 track-code-input" value="' + code + '" placeholder="Трек-код">' +
            '</td>' +
            '<td class="border px-4 py-2 relative">' +
            '<input type="text" class="w-full border rounded px-2 py-1 owner-input" value="' + owner + '" placeholder="Login владельца" autocomplete="off">' +
            '</td>' +
            '<td class="border px-4 py-2">' +
            '<input type="text" inputmode="decimal" class="w-full border rounded px-2 py-1 weight-input" value="' + weight + '" placeholder="Вес (кг)">' +
            '</td>' +
            '<td class="border px-4 py-2 text-center">' +
            '<button type="button" class="text-red-500 hover:text-red-700 delete-row-btn">' +
            '<i class="ri-delete-bin-line"></i>' +
            '</button>' +
            '</td>';

        tr.querySelector('.delete-row-btn').addEventListener('click', function () {
            tr.remove();
            updateRowNumbers();
            updateTableRowCounter();
            updateEmptyCellsCounter();
        });

        var inputs = tr.querySelectorAll('input');
        inputs.forEach(function (input, index) {
            // Снимаем красную рамку при вводе
            input.addEventListener('input', function () {
                if (this.value.trim() !== '') {
                    this.classList.remove('border-red-500', 'border-2');
                    this.classList.add('border');
                }
                updateTableRowCounter();
                updateEmptyCellsCounter();
            });

            input.addEventListener('keydown', function (e) {
                // Inline-автозаполнение: Enter подтверждает подсказку
                if (inlineAc.active && inlineAc.input === this) {
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        inlineAccept(this);
                        return;
                    } else if (e.key === 'Escape') {
                        e.preventDefault();
                        inlineReject(this);
                        return;
                    } else if (e.key === 'Tab') {
                        inlineAccept(this);
                        return;
                    }
                }

                if (e.key === 'Enter') {
                    e.preventDefault();
                    moveFocus(tr, index, 'next', false);
                } else if (e.key === 'ArrowRight') {
                    if (this.selectionStart === this.value.length) {
                        e.preventDefault();
                        moveFocus(tr, index, 'next', true);
                    }
                } else if (e.key === 'ArrowLeft') {
                    if (this.selectionStart === 0) {
                        e.preventDefault();
                        moveFocus(tr, index, 'prev', true);
                    }
                } else if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    moveVerticalFocus(tr, index, 'up');
                } else if (e.key === 'ArrowDown') {
                    e.preventDefault();
                    moveVerticalFocus(tr, index, 'down');
                }
            });
        });

        var trackInput = tr.querySelector('.track-code-input');
        trackInput.addEventListener('input', function () {
            var allRows = tracksTableBody.querySelectorAll('tr');
            var lastRow = allRows[allRows.length - 1];
            if (tr === lastRow && this.value.trim() !== '') {
                tracksTableBody.appendChild(createRow());
                updateRowNumbers();
            }
        });

        trackInput.addEventListener('input', debounce(function () {
            var inputCode = this.value.trim();
            if (inputCode) {
                fetch(getOwnerUrl + '?track_code=' + encodeURIComponent(inputCode))
                    .then(function (response) { return response.json(); })
                    .then(function (data) {
                        if (data.owner) {
                            var ownerInput = tr.querySelector('.owner-input');
                            ownerInput.value = data.owner;
                            ownerInput.classList.remove('border-red-500', 'border-2');
                            ownerInput.classList.add('border');
                            var rowInputs = tr.querySelectorAll('input');
                            if (rowInputs[2]) {
                                rowInputs[2].focus();
                            }
                            updateEmptyCellsCounter();
                        }
                    })
                    .catch(function (err) { console.error('Error fetching owner:', err); });
            }
        }, 500));

        // Автозаполнение для поля владельца
        var ownerInput = tr.querySelector('.owner-input');
        setupOwnerAutocomplete(ownerInput);

        return tr;
    }

    function moveFocus(currentRow, currentIndex, direction, allowWrap) {
        var inputs = currentRow.querySelectorAll('input');
        if (direction === 'next') {
            if (currentIndex < inputs.length - 1) {
                inputs[currentIndex + 1].focus();
            } else if (allowWrap) {
                var nextRow = currentRow.nextElementSibling;
                if (nextRow) {
                    var nextInputs = nextRow.querySelectorAll('input');
                    if (nextInputs.length > 0) nextInputs[0].focus();
                }
            }
        } else if (direction === 'prev') {
            if (currentIndex > 0) {
                inputs[currentIndex - 1].focus();
            } else if (allowWrap) {
                var prevRow = currentRow.previousElementSibling;
                if (prevRow) {
                    var prevInputs = prevRow.querySelectorAll('input');
                    if (prevInputs.length > 0) prevInputs[prevInputs.length - 1].focus();
                }
            }
        }
    }

    function moveVerticalFocus(currentRow, currentIndex, direction) {
        if (direction === 'up') {
            var prevRow = currentRow.previousElementSibling;
            if (prevRow) {
                var prevInputs = prevRow.querySelectorAll('input');
                if (prevInputs[currentIndex]) prevInputs[currentIndex].focus();
            }
        } else if (direction === 'down') {
            var nextRow = currentRow.nextElementSibling;
            if (nextRow) {
                var nextInputs = nextRow.querySelectorAll('input');
                if (nextInputs[currentIndex]) nextInputs[currentIndex].focus();
            }
        }
    }

    // ============================================
    // Автозаполнение для input (табличный вид)
    // ============================================
    function setupOwnerAutocomplete(input) {
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

            fetch(searchUsersUrl + '?q=' + encodeURIComponent(query))
                .then(function (res) { return res.json(); })
                .then(function (data) {
                    if (data.results && data.results.length && document.activeElement === input) {
                        inlineApply(input, data.results, query);
                    } else {
                        inlineClear();
                    }
                })
                .catch(function () { inlineClear(); });
        }, 250);

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

    // ============================================
    // Синхронизация между режимами
    // ============================================
    function syncToTable() {
        var codes = trackCodesArea.value.split('\n').map(function (s) { return s.trim(); }).filter(function (s) { return s; });
        var owners = ownerUsernamesArea.value.split('\n').map(function (s) { return s.trim(); }).filter(function (s) { return s; });
        var ws = weightsArea.value.split('\n').map(function (s) { return s.trim(); }).filter(function (s) { return s; });

        tracksTableBody.innerHTML = '';

        var maxRows = Math.max(codes.length, owners.length, ws.length, 1);

        for (var i = 0; i < maxRows; i++) {
            var c = codes[i] || '';
            var o = owners[i] || '';
            var w = ws[i] || '';
            if (c || o || w || i === 0) {
                tracksTableBody.appendChild(createRow(c, o, w));
            }
        }
        updateRowNumbers();
    }

    function syncFromTable() {
        var rows = tracksTableBody.querySelectorAll('tr');
        var codes = [];
        var owners = [];
        var ws = [];

        rows.forEach(function (row) {
            var c = row.querySelector('.track-code-input').value.trim();
            var o = row.querySelector('.owner-input').value.trim();
            var w = row.querySelector('.weight-input').value.trim();

            if (c || o || w) {
                codes.push(c);
                owners.push(o);
                ws.push(w);
            }
        });

        trackCodesArea.value = codes.join('\n');
        ownerUsernamesArea.value = owners.join('\n');
        weightsArea.value = ws.join('\n');
    }

    formToggleBtn.addEventListener('click', toggleFormView);

    addRowBtn.addEventListener('click', function () {
        tracksTableBody.appendChild(createRow());
        updateRowNumbers();
        updateTableRowCounter();
    });

    formEl.addEventListener('submit', function (e) {
        if (isTableMode) {
            // Валидация пустых ячеек
            clearAllRedBorders();
            var empty = getEmptyCells();
            if (empty.length > 0) {
                e.preventDefault();
                // Помечаем все пустые ячейки красной рамкой
                empty.forEach(function (inp) {
                    inp.classList.remove('border');
                    inp.classList.add('border-red-500', 'border-2');
                });
                // Прокрутка к первой незаполненной ячейке (сверху вниз)
                empty[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
                empty[0].focus();
                updateEmptyCellsCounter();
                return;
            }

            syncFromTable();
            trackCodesArea.setAttribute('required', '');
            ownerUsernamesArea.setAttribute('required', '');
            weightsArea.setAttribute('required', '');
            if (!trackCodesArea.value.trim()) {
                e.preventDefault();
                alert('Заполните хотя бы один трек-код.');
                trackCodesArea.removeAttribute('required');
                ownerUsernamesArea.removeAttribute('required');
                weightsArea.removeAttribute('required');
            }
        }
    });

    // ============================================
    // Автозаполнение для textarea (текстовый вид) — dropdown
    // ============================================
    (function setupTextareaAutocomplete() {
        var currentLineStart = 0;
        var currentLineEnd = 0;

        function getCurrentLine() {
            var val = ownerUsernamesArea.value;
            var pos = ownerUsernamesArea.selectionStart;
            var start = val.lastIndexOf('\n', pos - 1) + 1;
            var end = val.indexOf('\n', pos);
            if (end === -1) end = val.length;
            currentLineStart = start;
            currentLineEnd = end;
            return val.substring(start, end).trim();
        }

        function replaceCurrentLine(login) {
            var val = ownerUsernamesArea.value;
            ownerUsernamesArea.value = val.substring(0, currentLineStart) + login + val.substring(currentLineEnd);
            var newPos = currentLineStart + login.length;
            ownerUsernamesArea.selectionStart = newPos;
            ownerUsernamesArea.selectionEnd = newPos;
        }

        function acShowTextarea(results) {
            acRemove();
            if (!results.length) return;

            acActiveInput = ownerUsernamesArea;
            acResults = results;

            acDropdown = document.createElement('div');
            acDropdown.className = 'fixed z-[9999] bg-white border border-gray-300 rounded-lg shadow-xl max-h-52 overflow-y-auto';

            var rect = ownerUsernamesArea.getBoundingClientRect();
            acDropdown.style.top = (rect.bottom + 2) + 'px';
            acDropdown.style.left = rect.left + 'px';
            acDropdown.style.width = Math.max(rect.width, 250) + 'px';

            results.forEach(function (item, i) {
                var option = document.createElement('div');
                option.className = 'px-3 py-2 text-sm cursor-pointer hover:bg-blue-50 border-b border-gray-100 last:border-b-0';

                var text = document.createElement('span');
                text.textContent = item.label;
                option.appendChild(text);

                if (item.type === 'temp') {
                    var badge = document.createElement('span');
                    badge.className = 'ml-2 text-[10px] bg-orange-100 text-orange-600 px-1.5 py-0.5 rounded';
                    badge.textContent = 'временный';
                    option.appendChild(badge);
                } else if (item.type === 'user') {
                    var badge = document.createElement('span');
                    badge.className = 'ml-2 text-[10px] bg-green-100 text-green-600 px-1.5 py-0.5 rounded';
                    badge.textContent = 'зарег.';
                    option.appendChild(badge);
                }

                option.addEventListener('mousedown', function (e) {
                    e.preventDefault();
                    replaceCurrentLine(item.login);
                    acRemove();
                    ownerUsernamesArea.focus();
                });

                acDropdown.appendChild(option);
            });

            document.body.appendChild(acDropdown);
        }

        function acHighlight(idx) {
            if (!acDropdown) return;
            var options = acDropdown.children;
            for (var i = 0; i < options.length; i++) {
                if (i === idx) {
                    options[i].classList.add('bg-blue-100');
                    options[i].classList.remove('hover:bg-blue-50');
                    options[i].scrollIntoView({ block: 'nearest' });
                } else {
                    options[i].classList.remove('bg-blue-100');
                    options[i].classList.add('hover:bg-blue-50');
                }
            }
        }

        ownerUsernamesArea.addEventListener('input', debounce(function () {
            var query = getCurrentLine();
            if (query.length < 1) {
                acRemove();
                return;
            }

            fetch(searchUsersUrl + '?q=' + encodeURIComponent(query))
                .then(function (res) { return res.json(); })
                .then(function (data) {
                    if (data.results && data.results.length && document.activeElement === ownerUsernamesArea) {
                        acShowTextarea(data.results);
                    } else {
                        acRemove();
                    }
                })
                .catch(function () { acRemove(); });
        }, 250));

        ownerUsernamesArea.addEventListener('keydown', function (e) {
            if (!acDropdown || acActiveInput !== ownerUsernamesArea) return;

            if (e.key === 'ArrowDown') {
                e.preventDefault();
                acSelectedIndex = Math.min(acSelectedIndex + 1, acResults.length - 1);
                acHighlight(acSelectedIndex);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                acSelectedIndex = Math.max(acSelectedIndex - 1, -1);
                acHighlight(acSelectedIndex);
            } else if (e.key === 'Enter' && acSelectedIndex >= 0) {
                e.preventDefault();
                replaceCurrentLine(acResults[acSelectedIndex].login);
                acRemove();
            } else if (e.key === 'Escape') {
                acRemove();
            }
        });

        ownerUsernamesArea.addEventListener('blur', function () {
            setTimeout(acRemove, 150);
        });

        // Закрытие textarea dropdown при клике вне или скролле
        document.addEventListener('click', function (e) {
            if (acDropdown && e.target !== ownerUsernamesArea && !acDropdown.contains(e.target)) {
                acRemove();
            }
        });
        document.addEventListener('scroll', function () { acRemove(); }, true);
    })();

    // ============================================
    // Предупреждение при закрытии/обновлении страницы
    // ============================================
    var formSubmitting = false;
    formEl.addEventListener('submit', function () { formSubmitting = true; });

    function hasFormData() {
        if (isTableMode) {
            return tracksTableBody.querySelectorAll('tr').length > 0;
        }
        return trackCodesArea.value.trim() !== '' ||
               ownerUsernamesArea.value.trim() !== '' ||
               weightsArea.value.trim() !== '';
    }

    window.addEventListener('beforeunload', function (e) {
        if (formSubmitting || !hasFormData()) return;
        e.preventDefault();
        e.returnValue = '';
    });
});
