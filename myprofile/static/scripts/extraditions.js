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
    var verifyBtn = document.getElementById('verifyBtn');
    var clearBtn = document.getElementById('clearBtn');
    var scanBarcodeBtn = document.getElementById('scanBarcodeBtn');
    var messagesContainer = document.getElementById('ajax-messages');
    var receiptsContainer = document.getElementById('receiptsContainer');
    var packageTotalBlock = document.getElementById('packageTotalBlock');
    var packageTotalEl = document.getElementById('packageTotal');

    var currentBarcode = '';
    var currentReceipts = []; // храним данные чеков для QR-верификации

    // ==================== Barcode Scanner ====================
    var barcodeScanModal = document.getElementById('barcode-scan-modal');
    var barcodeModalClose = document.getElementById('barcode-modal-close');
    var barcodeCancelBtn = document.getElementById('barcode-cancel-btn');
    var barcodeScanner = null;

    function openBarcodeScanner() {
        barcodeScanModal.classList.remove('hidden');
        document.getElementById('barcode-scan-result').classList.add('hidden');

        barcodeScanner = new Html5Qrcode("barcode-reader");
        barcodeScanner.start(
            { facingMode: "environment" },
            { fps: 10, qrbox: { width: 250, height: 250 }, aspectRatio: 1.0 },
            function (decodedText) {
                // Успешное сканирование штрихкода
                document.getElementById('barcode-scan-text').textContent = decodedText;
                document.getElementById('barcode-scan-result').classList.remove('hidden');
                barcodeInput.value = decodedText;
                closeBarcodeScanner();
                performSearch();
            },
            function () { /* игнорируем ошибки сканирования */ }
        ).catch(function (err) {
            console.error('Ошибка камеры:', err);
            closeBarcodeScanner();
            showMessage('Не удалось запустить камеру. Проверьте разрешения.');
        });
    }

    function closeBarcodeScanner() {
        if (barcodeScanner) {
            barcodeScanner.stop().then(function () {
                barcodeScanner.clear();
                barcodeScanner = null;
            }).catch(function () {
                barcodeScanner = null;
            });
        }
        barcodeScanModal.classList.add('hidden');
    }

    scanBarcodeBtn.onclick = openBarcodeScanner;
    barcodeModalClose.onclick = closeBarcodeScanner;
    barcodeCancelBtn.onclick = closeBarcodeScanner;

    // ==================== QR Verification ====================
    var qrVerifyModal = document.getElementById('qr-verify-modal');
    var qrVerifyClose = document.getElementById('qr-verify-close');
    var qrVerifyCancel = document.getElementById('qr-verify-cancel');
    var qrVerifySubmit = document.getElementById('qr-verify-submit');
    var qrVerifyReceiptsList = document.getElementById('qr-verify-receipts-list');
    var qrVerifyScanned = document.getElementById('qr-verify-scanned');
    var qrVerifyTotal = document.getElementById('qr-verify-total');
    var qrVerifyPercent = document.getElementById('qr-verify-percent');
    var qrVerifyBar = document.getElementById('qr-verify-bar');
    var qrVerifyFeedback = document.getElementById('qr-verify-feedback');
    var qrScanner = null;
    var scannedReceipts = {}; // receipt_number → true
    var lastScannedCode = '';
    var lastScannedTime = 0;

    function openQrVerifyModal() {
        if (!currentReceipts.length) return;

        scannedReceipts = {};
        qrVerifyModal.classList.remove('hidden');
        qrVerifyFeedback.classList.add('hidden');

        // Рендерим список чеков
        renderQrReceiptsList();
        updateQrProgress();
        updateQrSubmitButton();

        // Запускаем QR-сканер
        qrScanner = new Html5Qrcode("qr-verify-reader");
        qrScanner.start(
            { facingMode: "environment" },
            { fps: 10, qrbox: { width: 200, height: 200 } },
            function (decodedText) {
                onQrScanned(decodedText);
            },
            function () { /* игнорируем */ }
        ).catch(function (err) {
            console.error('Ошибка камеры QR:', err);
            showQrFeedback('Не удалось запустить камеру', 'error');
        });
    }

    function closeQrVerifyModal() {
        stopQrScanner();
        qrVerifyModal.classList.add('hidden');
    }

    function onQrScanned(code) {
        // Debounce: игнорируем повторные сканы того же кода в течение 2 секунд
        var now = Date.now();
        if (code === lastScannedCode && (now - lastScannedTime) < 2000) {
            return;
        }
        lastScannedCode = code;
        lastScannedTime = now;

        // Ищем чек по receipt_number
        var found = false;
        for (var i = 0; i < currentReceipts.length; i++) {
            if (currentReceipts[i].receipt_number === code) {
                found = true;
                if (scannedReceipts[code]) {
                    showQrFeedback('Чек ' + code + ' уже отсканирован', 'warning');
                } else {
                    scannedReceipts[code] = true;
                    showQrFeedback('Чек ' + code + ' подтверждён', 'success');
                    renderQrReceiptsList();
                    updateQrProgress();
                    updateQrSubmitButton();

                    // Останавливаем сканер когда все чеки отсканированы
                    var scannedCount = Object.keys(scannedReceipts).length;
                    if (scannedCount >= currentReceipts.length) {
                        stopQrScanner();
                    }
                }
                break;
            }
        }
        if (!found) {
            showQrFeedback('Чек ' + code + ' не относится к этому пакету', 'error');
        }
    }

    function stopQrScanner() {
        if (qrScanner) {
            qrScanner.stop().then(function () {
                qrScanner.clear();
                qrScanner = null;
            }).catch(function () {
                qrScanner = null;
            });
        }
    }

    function showQrFeedback(text, type) {
        qrVerifyFeedback.classList.remove('hidden', 'bg-green-50', 'text-green-800', 'border-green-200',
            'bg-red-50', 'text-red-800', 'border-red-200', 'bg-yellow-50', 'text-yellow-800', 'border-yellow-200');
        if (type === 'success') {
            qrVerifyFeedback.className = 'mb-3 p-2 rounded-lg text-sm text-center bg-green-50 text-green-800 border border-green-200';
        } else if (type === 'warning') {
            qrVerifyFeedback.className = 'mb-3 p-2 rounded-lg text-sm text-center bg-yellow-50 text-yellow-800 border border-yellow-200';
        } else {
            qrVerifyFeedback.className = 'mb-3 p-2 rounded-lg text-sm text-center bg-red-50 text-red-800 border border-red-200';
        }
        qrVerifyFeedback.textContent = text;
        setTimeout(function () { qrVerifyFeedback.classList.add('hidden'); }, 3000);
    }

    function renderQrReceiptsList() {
        qrVerifyReceiptsList.innerHTML = '';
        currentReceipts.forEach(function (receipt) {
            var isScanned = !!scannedReceipts[receipt.receipt_number];
            var row = document.createElement('div');
            row.className = 'flex items-center justify-between p-3 rounded-lg border ' +
                (isScanned ? 'border-green-300 bg-green-50' : 'border-gray-200 bg-white');

            var left = document.createElement('div');
            left.className = 'flex items-center gap-3';

            var icon = document.createElement('i');
            icon.className = isScanned
                ? 'ri-checkbox-circle-fill text-green-500 text-xl'
                : 'ri-checkbox-blank-circle-line text-gray-300 text-xl';

            var info = document.createElement('div');
            info.innerHTML = '<p class="font-medium text-sm">' + receipt.receipt_number + '</p>' +
                '<p class="text-xs text-gray-500">' + receipt.total_weight.toFixed(3) + ' кг — ' + receipt.total_price + ' тг</p>';

            left.appendChild(icon);
            left.appendChild(info);

            var right = document.createElement('div');
            right.className = 'flex items-center gap-2';

            // Бейдж оплаты
            var payBadge = document.createElement('span');
            if (receipt.is_paid) {
                payBadge.className = 'inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800';
                payBadge.textContent = 'Оплачено';
            } else {
                payBadge.className = 'inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800 cursor-pointer hover:bg-red-200';
                payBadge.textContent = 'Не оплачено';
                payBadge.title = 'Нажмите для отметки оплаты';
                (function (r) {
                    payBadge.addEventListener('click', function () {
                        showQrPaymentModal(r, payBadge);
                    });
                })(receipt);
            }
            right.appendChild(payBadge);

            // Кнопка ручной отметки (если не отсканирован)
            if (!isScanned) {
                var manualBtn = document.createElement('button');
                manualBtn.type = 'button';
                manualBtn.className = 'text-xs text-blue-500 hover:text-blue-700 underline';
                manualBtn.textContent = 'Вручную';
                manualBtn.title = 'Отметить без сканирования';
                (function (rn) {
                    manualBtn.addEventListener('click', function () {
                        scannedReceipts[rn] = true;
                        showQrFeedback('Чек ' + rn + ' отмечен вручную', 'success');
                        renderQrReceiptsList();
                        updateQrProgress();
                        updateQrSubmitButton();
                    });
                })(receipt.receipt_number);
                right.appendChild(manualBtn);
            }

            row.appendChild(left);
            row.appendChild(right);
            qrVerifyReceiptsList.appendChild(row);
        });
    }

    function showQrPaymentModal(receipt, badgeEl) {
        // Модалка оплаты внутри QR-верификации
        var overlay = document.createElement('div');
        overlay.className = 'fixed inset-0 z-[60] flex items-center justify-center';
        overlay.innerHTML =
            '<div class="absolute inset-0 bg-black/50"></div>' +
            '<div class="relative bg-white rounded-lg shadow-xl p-6 max-w-sm w-full mx-4 z-10">' +
                '<h3 class="text-lg font-semibold mb-4">Отметить оплату чека ' + receipt.receipt_number + '</h3>' +
                '<label class="block text-sm font-medium text-gray-700 mb-1">Дата и время оплаты</label>' +
                '<input type="datetime-local" class="qr-pay-datetime w-full border border-gray-300 rounded px-3 py-2 mb-4">' +
                '<div class="flex gap-2 justify-end">' +
                    '<button type="button" class="qr-pay-cancel px-4 py-2 border border-gray-200 rounded hover:bg-gray-50 text-sm">Отмена</button>' +
                    '<button type="button" class="qr-pay-confirm px-4 py-2 bg-green-500 text-white rounded hover:bg-green-600 text-sm">Подтвердить</button>' +
                '</div>' +
            '</div>';

        document.body.appendChild(overlay);

        var now = new Date();
        var pad = function (n) { return n < 10 ? '0' + n : n; };
        var dtInput = overlay.querySelector('.qr-pay-datetime');
        dtInput.value = now.getFullYear() + '-' + pad(now.getMonth() + 1) + '-' + pad(now.getDate()) +
            'T' + pad(now.getHours()) + ':' + pad(now.getMinutes());

        overlay.querySelector('.absolute').onclick = function () { overlay.remove(); };
        overlay.querySelector('.qr-pay-cancel').onclick = function () { overlay.remove(); };
        overlay.querySelector('.qr-pay-confirm').onclick = function () {
            var paidAt = dtInput.value;
            overlay.remove();
            // Отправляем toggle_payment
            var csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;
            var body = 'receipt_id=' + encodeURIComponent(receipt.receipt_id);
            if (paidAt) {
                body += '&paid_at=' + encodeURIComponent(paidAt);
            }
            fetch(toggleUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': csrfToken },
                body: body
            })
            .then(function (resp) { return resp.json(); })
            .then(function (data) {
                if (data.success && data.is_paid) {
                    receipt.is_paid = true;
                    receipt.paid_at = data.paid_at;
                    // Обновляем также основной список
                    var mainBadge = receiptsContainer.querySelector('[data-receipt-id="' + receipt.receipt_id + '"]');
                    if (mainBadge) {
                        mainBadge.setAttribute('data-paid', 'true');
                        mainBadge.className = 'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800';
                        mainBadge.textContent = 'Оплачено';
                        mainBadge.style.cursor = '';
                        mainBadge.title = data.paid_at || '';
                    }
                    updateGlobalPaymentStatus();
                    updateSubmitButton();
                    renderQrReceiptsList();
                    updateQrSubmitButton();
                    showQrFeedback('Оплата чека ' + receipt.receipt_number + ' подтверждена', 'success');
                } else {
                    showQrFeedback('Ошибка обновления оплаты', 'error');
                }
            })
            .catch(function () {
                showQrFeedback('Ошибка связи с сервером', 'error');
            });
        };
    }

    function updateQrProgress() {
        var total = currentReceipts.length;
        var scanned = Object.keys(scannedReceipts).length;
        qrVerifyScanned.textContent = scanned;
        qrVerifyTotal.textContent = total;
        var pct = total > 0 ? Math.round(scanned / total * 100) : 0;
        qrVerifyPercent.textContent = pct + '%';
        qrVerifyBar.style.width = pct + '%';
    }

    function updateQrSubmitButton() {
        var total = currentReceipts.length;
        var scanned = Object.keys(scannedReceipts).length;
        var allPaid = currentReceipts.every(function (r) { return r.is_paid; });
        var allScanned = scanned >= total && total > 0;

        // Показываем причину блокировки
        var statusEl = document.getElementById('qr-verify-block-reason');
        if (!statusEl) {
            statusEl = document.createElement('p');
            statusEl.id = 'qr-verify-block-reason';
            statusEl.className = 'text-xs text-center mt-1';
            qrVerifySubmit.parentNode.appendChild(statusEl);
        }

        if (allScanned && allPaid) {
            qrVerifySubmit.disabled = false;
            qrVerifySubmit.classList.remove('opacity-50', 'cursor-not-allowed');
            statusEl.textContent = '';
            statusEl.classList.add('hidden');
        } else {
            qrVerifySubmit.disabled = true;
            qrVerifySubmit.classList.add('opacity-50', 'cursor-not-allowed');

            var reasons = [];
            if (!allScanned) {
                reasons.push('Отсканировано ' + scanned + ' из ' + total + ' чеков');
            }
            if (!allPaid) {
                var unpaidCount = currentReceipts.filter(function (r) { return !r.is_paid; }).length;
                reasons.push('Не оплачено: ' + unpaidCount + ' чек(ов)');
            }
            statusEl.textContent = reasons.join(' | ');
            statusEl.className = 'text-xs text-center mt-1 text-red-500';
            statusEl.classList.remove('hidden');
        }
    }

    qrVerifyClose.onclick = closeQrVerifyModal;
    qrVerifyCancel.onclick = closeQrVerifyModal;

    qrVerifySubmit.onclick = function () {
        closeQrVerifyModal();
        // Сабмитим основную форму
        document.getElementById('extraditionForm').submit();
    };

    verifyBtn.onclick = openQrVerifyModal;

    // ==================== Common Functions ====================

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
        currentReceipts = [];
        updateSubmitButton();
        messagesContainer.innerHTML = '';
        // Скрываем кнопки
        submitBtn.classList.add('hidden');
        verifyBtn.classList.add('hidden');
    }

    function updateSubmitButton() {
        var unpaidBadges = receiptsContainer.querySelectorAll('[data-paid="false"]');
        var hasReceipts = receiptsContainer.querySelectorAll('.receipt-block').length > 0;

        if (hasReceipts && unpaidBadges.length === 0) {
            submitBtn.disabled = false;
            submitBtn.classList.remove('hidden', 'bg-gray-400', 'cursor-not-allowed');
            submitBtn.classList.add('bg-primary', 'hover:bg-red-600');
        } else {
            submitBtn.disabled = true;
            submitBtn.classList.add('hidden', 'bg-gray-400', 'cursor-not-allowed');
            submitBtn.classList.remove('bg-primary', 'hover:bg-red-600');
        }

        // Кнопка "Проверить и выдать" видна когда есть пакет
        if (hasReceipts) {
            verifyBtn.classList.remove('hidden');
            verifyBtn.disabled = false;
            verifyBtn.classList.remove('opacity-50', 'cursor-not-allowed');
            verifyBtn.classList.add('hover:bg-green-600');
        } else {
            verifyBtn.classList.add('hidden');
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
            showMessage('Введите QR-код');
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
                currentReceipts = data.receipts || [];
                infoOwner.textContent = data.owner;
                infoPickup.textContent = data.pickup_point;
                renderReceipts(currentReceipts);
                updateGlobalPaymentStatus();
                updateSubmitButton();
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
                currentReceipts = [];
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

            var header = document.createElement('div');
            header.className = 'flex items-center justify-between px-4 py-3 bg-gray-100 cursor-pointer hover:bg-gray-200 transition';

            var headerLeft = document.createElement('div');
            headerLeft.className = 'flex items-center gap-3';

            var chevron = document.createElement('i');
            chevron.className = 'ri-arrow-down-s-line text-gray-500 transition-transform';

            var title = document.createElement('span');
            title.className = 'font-medium text-sm';
            title.textContent = receipt.receipt_number + ' от ' + receipt.created_at;

            var weightInfo = document.createElement('span');
            weightInfo.className = 'text-xs text-gray-500';
            weightInfo.textContent = receipt.total_weight.toFixed(3) + ' кг — ' + receipt.total_price + ' тг';

            headerLeft.appendChild(chevron);
            headerLeft.appendChild(title);
            headerLeft.appendChild(weightInfo);

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
                    // Обновляем currentReceipts
                    for (var i = 0; i < currentReceipts.length; i++) {
                        if (currentReceipts[i].receipt_id == receiptId) {
                            currentReceipts[i].is_paid = data.is_paid;
                            currentReceipts[i].paid_at = data.paid_at;
                            break;
                        }
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
