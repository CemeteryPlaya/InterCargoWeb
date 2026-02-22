document.addEventListener('DOMContentLoaded', function () {
    var formEl = document.getElementById('goods_arrival_form');
    var getOwnerUrl = formEl.dataset.getOwnerUrl;

    var trackCodesArea = document.getElementById('track_codes');
    var ownerUsernamesArea = document.getElementById('owner_usernames');
    var weightsArea = document.getElementById('weights');

    var standardView = document.getElementById('standard_view');
    var tableView = document.getElementById('table_view');
    var tracksTableBody = document.getElementById('tracks_table_body');
    var addRowBtn = document.getElementById('add_row_btn');
    var formToggleBtn = document.getElementById('form_toggle_btn');

    var isTableMode = false;

    function toggleFormView() {
        isTableMode = !isTableMode;

        if (isTableMode) {
            standardView.classList.add('hidden');
            tableView.classList.remove('hidden');
            trackCodesArea.removeAttribute('required');
            syncToTable();
            formToggleBtn.innerHTML = '<i class="ri-file-text-line"></i> Переключить на текстовый вид';
        } else {
            standardView.classList.remove('hidden');
            tableView.classList.add('hidden');
            trackCodesArea.setAttribute('required', '');
            syncFromTable();
            formToggleBtn.innerHTML = '<i class="ri-table-line"></i> Переключить на табличный вид';
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

    function createRow(code, owner, weight) {
        code = code || '';
        owner = owner || '';
        weight = weight || '';

        var tr = document.createElement('tr');
        tr.innerHTML =
            '<td class="border px-4 py-2">' +
            '<input type="text" class="w-full border rounded px-2 py-1 track-code-input" value="' + code + '" placeholder="Трек-код">' +
            '</td>' +
            '<td class="border px-4 py-2">' +
            '<input type="text" class="w-full border rounded px-2 py-1 owner-input" value="' + owner + '" placeholder="Login владельца">' +
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
        });

        var inputs = tr.querySelectorAll('input');
        inputs.forEach(function (input, index) {
            input.addEventListener('keydown', function (e) {
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
                            var rowInputs = tr.querySelectorAll('input');
                            if (rowInputs[2]) {
                                rowInputs[2].focus();
                            }
                        }
                    })
                    .catch(function (err) { console.error('Error fetching owner:', err); });
            }
        }, 500));

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
    });

    formEl.addEventListener('submit', function () {
        if (isTableMode) {
            syncFromTable();
        }
    });
});
