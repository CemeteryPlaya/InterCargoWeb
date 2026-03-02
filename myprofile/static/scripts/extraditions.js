document.addEventListener('DOMContentLoaded', function () {
    var config = document.getElementById('extradition-config');
    var searchUrl = config.dataset.searchUrl;
    var toggleUrl = config.dataset.toggleUrl;

    var barcodeInput = document.getElementById('barcode');
    var searchBtn = document.getElementById('searchBtn');
    var packageInfo = document.getElementById('packageInfo');
    var infoOwner = document.getElementById('infoOwner');
    var infoPickup = document.getElementById('infoPickup');
    var infoPaymentStatus = document.getElementById('infoPaymentStatus');
    var submitBtn = document.getElementById('submitBtn');
    var clearBtn = document.getElementById('clearBtn');
    var messagesContainer = document.getElementById('ajax-messages');
    var receiptsContainer = document.getElementById('receiptsContainer');
    var packageTotalBlock = document.getElementById('packageTotalBlock');
    var packageTotalEl = document.getElementById('packageTotal');

    var currentBarcode = '';

    function showMessage(text, type) {
        type = type || 'error';
        var msgDiv = document.createElement('div');
        msgDiv.className = 'p-4 mb-3 rounded-lg text-sm font-medium ' + (type === 'error' ? 'bg-red-100 text-red-800' : 'bg-green-100 text-green-800');
        msgDiv.textContent = text;
        messagesContainer.innerHTML = '';
        messagesContainer.appendChild(msgDiv);
        setTimeout(function () { msgDiv.remove(); }, 5000);
    }

    function clearForm() {
        barcodeInput.value = '';
        packageInfo.classList.add('hidden');
        receiptsContainer.innerHTML = '';
        packageTotalBlock.classList.add('hidden');
        currentBarcode = '';
        updateSubmitButton();
        messagesContainer.innerHTML = '';
    }

    function updateSubmitButton() {
        var unpaidBadges = receiptsContainer.querySelectorAll('[data-paid="false"]');
        var hasReceipts = receiptsContainer.querySelectorAll('.receipt-block').length > 0;

        if (hasReceipts && unpaidBadges.length === 0) {
            submitBtn.disabled = false;
            submitBtn.classList.remove('bg-gray-400', 'cursor-not-allowed');
            submitBtn.classList.add('bg-primary', 'hover:bg-red-600');
        } else {
            submitBtn.disabled = true;
            submitBtn.classList.add('bg-gray-400', 'cursor-not-allowed');
            submitBtn.classList.remove('bg-primary', 'hover:bg-red-600');
        }
    }

    function updateGlobalPaymentStatus() {
        var unpaidBadges = receiptsContainer.querySelectorAll('[data-paid="false"]');
        if (unpaidBadges.length === 0) {
            infoPaymentStatus.textContent = 'Оплачено';
            infoPaymentStatus.className = 'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800';
        } else {
            infoPaymentStatus.textContent = 'Не оплачено';
            infoPaymentStatus.className = 'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800';
        }
    }

    clearBtn.onclick = clearForm;
    searchBtn.onclick = performSearch;

    barcodeInput.addEventListener('keypress', function (e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            performSearch();
        }
    });

    function performSearch() {
        var barcode = barcodeInput.value.trim();
        if (!barcode) {
            showMessage('Введите штрихкод');
            return;
        }

        fetch(searchUrl + '?barcode=' + encodeURIComponent(barcode))
            .then(function (response) {
                if (!response.ok) {
                    if (response.status === 404) throw new Error('Пакет не найден');
                    throw new Error('Ошибка сервера');
                }
                return response.json();
            })
            .then(function (data) {
                messagesContainer.innerHTML = '';
                currentBarcode = data.barcode;
                infoOwner.textContent = data.owner;
                infoPickup.textContent = data.pickup_point;
                renderReceipts(data.receipts || []);
                updateGlobalPaymentStatus();
                updateSubmitButton();
                // Показываем общую сумму пакета
                if (data.package_total !== undefined) {
                    packageTotalEl.textContent = data.package_total;
                    packageTotalBlock.classList.remove('hidden');
                }
                packageInfo.classList.remove('hidden');
            })
            .catch(function (err) {
                console.error(err);
                packageInfo.classList.add('hidden');
                receiptsContainer.innerHTML = '';
                updateSubmitButton();
                showMessage(err.message);
            });
    }

    function renderReceipts(receipts) {
        receiptsContainer.innerHTML = '';

        if (!receipts.length) return;

        receipts.forEach(function (receipt) {
            var block = document.createElement('div');
            block.className = 'receipt-block border border-gray-200 rounded-lg mb-3 overflow-hidden';

            // Заголовок чека
            var header = document.createElement('div');
            header.className = 'flex items-center justify-between px-4 py-3 bg-gray-100 cursor-pointer hover:bg-gray-200 transition';

            var headerLeft = document.createElement('div');
            headerLeft.className = 'flex items-center gap-3';

            var chevron = document.createElement('i');
            chevron.className = 'ri-arrow-down-s-line text-gray-500 transition-transform';

            var title = document.createElement('span');
            title.className = 'font-medium text-sm';
            title.textContent = 'Чек #' + receipt.receipt_id + ' от ' + receipt.created_at;

            var weightInfo = document.createElement('span');
            weightInfo.className = 'text-xs text-gray-500';
            weightInfo.textContent = receipt.total_weight.toFixed(3) + ' кг — ' + receipt.total_price + ' тг';

            headerLeft.appendChild(chevron);
            headerLeft.appendChild(title);
            headerLeft.appendChild(weightInfo);

            // Бейдж оплаты
            var payBadge = document.createElement('span');
            payBadge.setAttribute('data-receipt-id', receipt.receipt_id);
            payBadge.setAttribute('data-paid', receipt.is_paid ? 'true' : 'false');

            if (receipt.is_paid) {
                payBadge.className = 'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800';
                payBadge.textContent = 'Оплачено';
                if (receipt.paid_at) {
                    payBadge.title = receipt.paid_at;
                }
            } else {
                payBadge.className = 'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800 cursor-pointer hover:bg-red-200';
                payBadge.textContent = 'Не оплачено';
                payBadge.title = 'Нажмите, чтобы отметить как оплачено';

                payBadge.addEventListener('click', function (e) {
                    e.stopPropagation();
                    showPaymentModal(receipt.receipt_id, payBadge);
                });
            }

            header.appendChild(headerLeft);
            header.appendChild(payBadge);

            // Тело — таблица трек-кодов (по умолчанию скрыта)
            var body = document.createElement('div');
            body.className = 'hidden px-4 py-3';

            header.addEventListener('click', function () {
                body.classList.toggle('hidden');
                chevron.style.transform = body.classList.contains('hidden') ? '' : 'rotate(180deg)';
            });

            if (receipt.tracks && receipt.tracks.length) {
                var table = document.createElement('table');
                table.className = 'w-full text-sm border-collapse';

                var thead = document.createElement('thead');
                var headRow = document.createElement('tr');
                headRow.className = 'bg-gray-200 text-gray-700';

                ['#', 'Трек-код', 'Вес (кг)', 'Стоимость (тг)'].forEach(function (text, i) {
                    var th = document.createElement('th');
                    th.className = 'border border-gray-300 px-3 py-2 ' + (i >= 2 ? 'text-right' : 'text-left');
                    th.textContent = text;
                    headRow.appendChild(th);
                });

                thead.appendChild(headRow);
                table.appendChild(thead);

                var tbody = document.createElement('tbody');
                receipt.tracks.forEach(function (t, i) {
                    var tr = document.createElement('tr');
                    tr.className = i % 2 === 0 ? 'bg-white' : 'bg-gray-50';
                    var cellClass = 'border border-gray-300 px-3 py-1.5';

                    var td1 = document.createElement('td');
                    td1.className = cellClass;
                    td1.textContent = i + 1;

                    var td2 = document.createElement('td');
                    td2.className = cellClass + ' font-mono text-xs';
                    td2.textContent = t.track_code;

                    var td3 = document.createElement('td');
                    td3.className = cellClass + ' text-right';
                    td3.textContent = t.weight.toFixed(3);

                    var td4 = document.createElement('td');
                    td4.className = cellClass + ' text-right';
                    td4.textContent = t.price;

                    tr.appendChild(td1);
                    tr.appendChild(td2);
                    tr.appendChild(td3);
                    tr.appendChild(td4);
                    tbody.appendChild(tr);
                });

                table.appendChild(tbody);

                var tfoot = document.createElement('tfoot');
                var footRow = document.createElement('tr');
                footRow.className = 'bg-gray-100 font-semibold';

                var fc1 = document.createElement('td');
                fc1.className = 'border border-gray-300 px-3 py-2';

                var fc2 = document.createElement('td');
                fc2.className = 'border border-gray-300 px-3 py-2';
                fc2.textContent = 'Итого: ' + receipt.tracks.length + ' шт.';

                var fc3 = document.createElement('td');
                fc3.className = 'border border-gray-300 px-3 py-2 text-right';
                fc3.textContent = receipt.total_weight.toFixed(3);

                var fc4 = document.createElement('td');
                fc4.className = 'border border-gray-300 px-3 py-2 text-right';
                fc4.textContent = receipt.total_price;

                footRow.appendChild(fc1);
                footRow.appendChild(fc2);
                footRow.appendChild(fc3);
                footRow.appendChild(fc4);
                tfoot.appendChild(footRow);
                table.appendChild(tfoot);

                body.appendChild(table);
            }

            block.appendChild(header);
            block.appendChild(body);
            receiptsContainer.appendChild(block);
        });
    }

    function showPaymentModal(receiptId, badgeEl) {
        // Создаём модальное окно с выбором даты/времени оплаты
        var overlay = document.createElement('div');
        overlay.className = 'fixed inset-0 z-50 flex items-center justify-center';
        overlay.innerHTML =
            '<div class="absolute inset-0 bg-black/50" id="pay-modal-backdrop"></div>' +
            '<div class="relative bg-white rounded-lg shadow-xl p-6 max-w-sm w-full mx-4 z-10">' +
                '<h3 class="text-lg font-semibold mb-4">Отметить оплату чека #' + receiptId + '</h3>' +
                '<label class="block text-sm font-medium text-gray-700 mb-1">Дата и время оплаты</label>' +
                '<input type="datetime-local" id="pay-modal-datetime" class="w-full border border-gray-300 rounded px-3 py-2 mb-4">' +
                '<div class="flex gap-2 justify-end">' +
                    '<button type="button" id="pay-modal-cancel" class="px-4 py-2 border border-gray-200 rounded hover:bg-gray-50 text-sm">Отмена</button>' +
                    '<button type="button" id="pay-modal-confirm" class="px-4 py-2 bg-green-500 text-white rounded hover:bg-green-600 text-sm">Подтвердить</button>' +
                '</div>' +
            '</div>';

        document.body.appendChild(overlay);

        // Устанавливаем текущую дату/время
        var now = new Date();
        var pad = function (n) { return n < 10 ? '0' + n : n; };
        var dtInput = overlay.querySelector('#pay-modal-datetime');
        dtInput.value = now.getFullYear() + '-' + pad(now.getMonth() + 1) + '-' + pad(now.getDate()) +
            'T' + pad(now.getHours()) + ':' + pad(now.getMinutes());

        overlay.querySelector('#pay-modal-backdrop').onclick = function () { overlay.remove(); };
        overlay.querySelector('#pay-modal-cancel').onclick = function () { overlay.remove(); };
        overlay.querySelector('#pay-modal-confirm').onclick = function () {
            var paidAt = dtInput.value;
            overlay.remove();
            togglePayment(receiptId, badgeEl, paidAt);
        };
    }

    function togglePayment(receiptId, badgeEl, paidAt) {
        var csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;
        var body = 'receipt_id=' + encodeURIComponent(receiptId);
        if (paidAt) {
            body += '&paid_at=' + encodeURIComponent(paidAt);
        }

        fetch(toggleUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-CSRFToken': csrfToken
            },
            body: body
        })
            .then(function (response) { return response.json(); })
            .then(function (data) {
                if (data.success) {
                    badgeEl.setAttribute('data-paid', data.is_paid ? 'true' : 'false');
                    if (data.is_paid) {
                        badgeEl.className = 'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800';
                        badgeEl.textContent = 'Оплачено';
                        badgeEl.style.cursor = '';
                        badgeEl.title = data.paid_at || '';
                    } else {
                        badgeEl.className = 'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800 cursor-pointer hover:bg-red-200';
                        badgeEl.textContent = 'Не оплачено';
                        badgeEl.title = 'Нажмите, чтобы отметить как оплачено';
                    }
                    updateGlobalPaymentStatus();
                    updateSubmitButton();
                    showMessage('Статус оплаты обновлен', 'success');
                } else {
                    showMessage('Ошибка: ' + (data.error || 'Не удалось обновить статус'));
                }
            })
            .catch(function () {
                showMessage('Ошибка связи с сервером');
            });
    }
});
