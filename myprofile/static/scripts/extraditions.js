document.addEventListener('DOMContentLoaded', function () {
    var _i18n = document.getElementById('js-i18n')?.dataset || {};
    var _ei18n = document.getElementById('js-i18n-extraditions')?.dataset || {};
    var config = document.getElementById('extradition-config');
    var searchUrl = config.dataset.searchUrl;
    var sessionsUrl = config.dataset.sessionsUrl;
    var closeSessionUrl = config.dataset.closeSessionUrl;
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
            showMessage(_ei18n.cameraFailed || 'Не удалось запустить камеру. Проверьте разрешения.');
        });
    }

    function closeBarcodeScanner() {
        barcodeScanModal.classList.add('hidden');
        if (barcodeScanner) {
            var scanner = barcodeScanner;
            barcodeScanner = null;
            try {
                scanner.stop().then(function () {
                    try { scanner.clear(); } catch (e) { /* ignore */ }
                }).catch(function () { /* ignore */ });
            } catch (e) {
                console.error('closeBarcodeScanner error:', e);
            }
        }
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

        // Фокус на поле сканера для аппаратного сканера
        if (qrScannerInput) {
            qrScannerInput.value = '';
            qrScannerInput.focus();
        }

        // Запускаем QR-сканер (камера)
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
            showQrFeedback(_ei18n.cameraUnavail || 'Камера не доступна — используйте сканер или ввод вручную', 'warning');
        });
    }

    function closeQrVerifyModal() {
        // ВСЕГДА скрываем модалку первым делом, независимо от ошибок сканера
        qrVerifyModal.classList.add('hidden');
        try {
            stopQrScanner();
        } catch (e) {
            console.error('Ошибка при остановке сканера:', e);
            qrScanner = null;
        }
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
                    showQrFeedback((_ei18n.receiptAlready || 'Чек {code} уже отсканирован').replace('{code}', code), 'warning');
                } else {
                    scannedReceipts[code] = true;
                    showQrFeedback((_ei18n.receiptConfirmed || 'Чек {code} подтверждён').replace('{code}', code), 'success');
                    renderQrReceiptsList();
                    updateQrProgress();
                    updateQrSubmitButton();

                    // Останавливаем сканер когда все чеки отсканированы
                    var scannedCount = Object.keys(scannedReceipts).length;
                    if (scannedCount >= currentReceipts.length) {
                        try { stopQrScanner(); } catch (e) { /* ignore */ }
                    }
                }
                break;
            }
        }
        if (!found) {
            showQrFeedback((_ei18n.receiptWrongPkg || 'Чек {code} не относится к этому пакету').replace('{code}', code), 'error');
        }
    }

    function stopQrScanner() {
        if (qrScanner) {
            var scanner = qrScanner;
            qrScanner = null;
            try {
                scanner.stop().then(function () {
                    try { scanner.clear(); } catch (e) { /* ignore */ }
                }).catch(function () { /* ignore */ });
            } catch (e) {
                console.error('stopQrScanner error:', e);
            }
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

            /* PAYMENT COMMENTED OUT: payment badge in QR verify list removed */

            // Кнопка ручной отметки (если не отсканирован)
            if (!isScanned) {
                var manualBtn = document.createElement('button');
                manualBtn.type = 'button';
                manualBtn.className = 'text-xs text-blue-500 hover:text-blue-700 underline';
                manualBtn.textContent = _ei18n.manually || 'Вручную';
                manualBtn.title = _ei18n.markWithoutScan || 'Отметить без сканирования';
                (function (rn) {
                    manualBtn.addEventListener('click', function () {
                        scannedReceipts[rn] = true;
                        showQrFeedback((_ei18n.receiptManual || 'Чек {code} отмечен вручную').replace('{code}', rn), 'success');
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
                        mainBadge.textContent = _ei18n.paid || 'Оплачено';
                        mainBadge.style.cursor = '';
                        mainBadge.title = data.paid_at || '';
                    }
                    updateGlobalPaymentStatus();
                    updateSubmitButton();
                    renderQrReceiptsList();
                    updateQrSubmitButton();
                    showQrFeedback((_ei18n.paymentConfirmed || 'Оплата чека {num} подтверждена').replace('{num}', receipt.receipt_number), 'success');
                } else {
                    showQrFeedback(_ei18n.paymentError || 'Ошибка обновления оплаты', 'error');
                }
            })
            .catch(function () {
                showQrFeedback(_ei18n.commError || 'Ошибка связи с сервером', 'error');
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
        /* PAYMENT COMMENTED OUT: allPaid check removed */
        var allScanned = scanned >= total && total > 0;

        var statusEl = document.getElementById('qr-verify-block-reason');
        if (!statusEl) {
            statusEl = document.createElement('p');
            statusEl.id = 'qr-verify-block-reason';
            statusEl.className = 'text-xs text-center mt-1';
            qrVerifySubmit.parentNode.appendChild(statusEl);
        }

        if (allScanned) {
            qrVerifySubmit.disabled = false;
            qrVerifySubmit.classList.remove('opacity-50', 'cursor-not-allowed');
            statusEl.textContent = '';
            statusEl.classList.add('hidden');
        } else {
            qrVerifySubmit.disabled = true;
            qrVerifySubmit.classList.add('opacity-50', 'cursor-not-allowed');
            statusEl.textContent = 'Отсканировано ' + scanned + ' из ' + total + ' чеков';
            statusEl.className = 'text-xs text-center mt-1 text-red-500';
            statusEl.classList.remove('hidden');
        }
    }

    qrVerifyClose.onclick = closeQrVerifyModal;
    qrVerifyCancel.onclick = closeQrVerifyModal;

    qrVerifySubmit.addEventListener('click', function () {
        if (qrVerifySubmit.disabled) return;
        closeQrVerifyModal();
        // Сабмитим основную форму
        var form = document.getElementById('extraditionForm');
        var barcodeVal = document.getElementById('barcode').value.trim();
        if (!barcodeVal) {
            showMessage(_ei18n.qrNoCode || 'Ошибка: QR-код пакета не указан');
            return;
        }
        form.submit();
    });

    verifyBtn.onclick = openQrVerifyModal;

    // Кнопка "Выбрать все" — отмечает все чеки как отсканированные
    var selectAllBtn = document.getElementById('qr-select-all-btn');
    if (selectAllBtn) {
        selectAllBtn.addEventListener('click', function () {
            currentReceipts.forEach(function (receipt) {
                scannedReceipts[receipt.receipt_number] = true;
            });
            showQrFeedback(_ei18n.allChecked || 'Все чеки отмечены', 'success');
            renderQrReceiptsList();
            updateQrProgress();
            updateQrSubmitButton();
            stopQrScanner();
        });
    }

    // === Поддержка аппаратного сканера в модалке QR-верификации ===
    var qrScannerInput = document.getElementById('qr-verify-scanner-input');

    // Обработка ввода через поле (аппаратный сканер или ручной ввод)
    if (qrScannerInput) {
        qrScannerInput.addEventListener('keypress', function (e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                var code = qrScannerInput.value.trim();
                qrScannerInput.value = '';
                if (code) {
                    onQrScanned(code);
                }
                qrScannerInput.focus();
            }
        });
    }

    // Буфер для сканера когда фокус не на поле ввода
    var hwScanBuffer = '';
    var hwScanTimer = null;

    document.addEventListener('keydown', function (e) {
        // Работаем только когда модалка QR-верификации открыта
        if (qrVerifyModal.classList.contains('hidden')) return;

        // Если фокус на поле сканера — оно само обрабатывает ввод
        if (document.activeElement === qrScannerInput) return;

        // Игнорируем если фокус на других input/textarea
        var tag = document.activeElement ? document.activeElement.tagName : '';
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

        if (e.key === 'Enter') {
            e.preventDefault();
            e.stopPropagation();
            if (hwScanBuffer.length > 0) {
                onQrScanned(hwScanBuffer.trim());
                hwScanBuffer = '';
            }
            return;
        }

        // Только печатные символы
        if (e.key.length === 1 && !e.ctrlKey && !e.altKey && !e.metaKey) {
            e.preventDefault();
            hwScanBuffer += e.key;
            clearTimeout(hwScanTimer);
            hwScanTimer = setTimeout(function () { hwScanBuffer = ''; }, 500);
        }
    });

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
        /* PAYMENT COMMENTED OUT: submit no longer depends on payment status */
        var hasReceipts = receiptsContainer.querySelectorAll('.receipt-block').length > 0;

        if (hasReceipts) {
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

    /* PAYMENT COMMENTED OUT */
    function updateGlobalPaymentStatus() { /* no-op */ }

    clearBtn.onclick = clearForm;
    searchBtn.onclick = performSearch;

    barcodeInput.addEventListener('keypress', function (e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            // Не запускаем поиск если открыта модалка
            if (!qrVerifyModal.classList.contains('hidden')) return;
            if (!barcodeScanModal.classList.contains('hidden')) return;
            performSearch();
        }
    });

    function performSearch() {
        var barcode = barcodeInput.value.trim();
        if (!barcode) {
            showMessage(_ei18n.enterQr || 'Введите QR-код');
            return;
        }

        fetch(searchUrl + '?barcode=' + encodeURIComponent(barcode))
            .then(function (response) {
                if (!response.ok) {
                    if (response.status === 404) throw new Error(_ei18n.packageNotFound || 'Пакет не найден');
                    throw new Error(_ei18n.serverError || 'Ошибка сервера');
                }
                return response.json();
            })
            .then(function (data) {
                messagesContainer.innerHTML = '';
                currentBarcode = data.barcode;
                currentReceipts = data.receipts || [];
                infoOwner.textContent = data.owner_full_name
                    ? data.owner_full_name + ' (' + data.owner + ')'
                    : data.owner;
                infoPickup.textContent = data.pickup_point;
                // Refresh sessions list since a new session was just created server-side
                setTimeout(loadSessions, 500);

                // Ячейка хранения
                var cellBlock = document.getElementById('cellNumberBlock');
                var cellEl = document.getElementById('infoCellNumber');
                if (data.cell_number && cellBlock && cellEl) {
                    cellEl.textContent = data.cell_number;
                    cellBlock.classList.remove('hidden');
                } else if (cellBlock) {
                    cellBlock.classList.add('hidden');
                }

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

            /* PAYMENT COMMENTED OUT: payment badge removed from receipt header */
            header.appendChild(headerLeft);

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

    // ==================== Sessions ====================

    var sessionsList = document.getElementById('sessions-list');
    var sessionsEmpty = document.getElementById('sessions-empty');
    var sessionsCountBadge = document.getElementById('sessions-count-badge');
    var refreshSessionsBtn = document.getElementById('refreshSessionsBtn');

    function loadSessions() {
        if (!sessionsUrl) return;
        fetch(sessionsUrl)
            .then(function (r) { return r.json(); })
            .then(function (data) { renderSessions(data.sessions || []); })
            .catch(function () { /* silently ignore */ });
    }

    function renderSessions(sessions) {
        // Remove existing session cards (keep the empty placeholder)
        var cards = sessionsList.querySelectorAll('.session-card');
        cards.forEach(function (c) { c.remove(); });

        if (sessions.length === 0) {
            sessionsEmpty.classList.remove('hidden');
            sessionsCountBadge.classList.add('hidden');
            return;
        }

        sessionsEmpty.classList.add('hidden');
        sessionsCountBadge.textContent = sessions.length;
        sessionsCountBadge.classList.remove('hidden');

        sessions.forEach(function (s) {
            var card = document.createElement('div');
            card.className = 'session-card bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden';
            card.dataset.sessionId = s.session_id;
            card.dataset.barcode = s.barcode;

            var clientName = s.owner_full_name
                ? s.owner_full_name + ' (' + s.owner + ')'
                : s.owner;

            card.innerHTML =
                '<div class="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-gray-50 transition session-card-header">' +
                    '<div class="flex items-center gap-3">' +
                        '<div class="w-9 h-9 rounded-full bg-primary bg-opacity-10 flex items-center justify-center flex-shrink-0">' +
                            '<i class="ri-user-line text-primary"></i>' +
                        '</div>' +
                        '<div>' +
                            '<p class="font-semibold text-sm text-gray-900">' + clientName + '</p>' +
                            '<p class="text-xs text-gray-500 font-mono">' + s.barcode +
                                ' &bull; ' + s.receipt_count + ' чек.' +
                                ' &bull; открыта в ' + s.opened_at +
                                (s.opened_by ? ' (' + s.opened_by + ')' : '') +
                            '</p>' +
                        '</div>' +
                    '</div>' +
                    '<div class="flex items-center gap-2">' +
                        '<button type="button" class="session-load-btn bg-primary text-white text-xs px-3 py-1.5 rounded-lg hover:bg-red-600 transition flex items-center gap-1">' +
                            '<i class="ri-arrow-up-line"></i> Открыть' +
                        '</button>' +
                        '<button type="button" class="session-close-btn text-gray-400 hover:text-red-500 transition p-1" title="Закрыть сессию">' +
                            '<i class="ri-close-line text-lg"></i>' +
                        '</button>' +
                    '</div>' +
                '</div>';

            // Load barcode into main form
            card.querySelector('.session-load-btn').addEventListener('click', function (e) {
                e.stopPropagation();
                barcodeInput.value = s.barcode;
                window.scrollTo({ top: 0, behavior: 'smooth' });
                performSearch();
            });

            // Also click on card header loads barcode
            card.querySelector('.session-card-header').addEventListener('click', function (e) {
                if (e.target.closest('.session-close-btn') || e.target.closest('.session-load-btn')) return;
                barcodeInput.value = s.barcode;
                window.scrollTo({ top: 0, behavior: 'smooth' });
                performSearch();
            });

            // Close session
            card.querySelector('.session-close-btn').addEventListener('click', function (e) {
                e.stopPropagation();
                var csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;
                fetch(closeSessionUrl, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded',
                        'X-CSRFToken': csrfToken,
                    },
                    body: 'session_id=' + encodeURIComponent(s.session_id),
                })
                .then(function () { loadSessions(); })
                .catch(function () { loadSessions(); });
            });

            sessionsList.appendChild(card);
        });
    }

    if (refreshSessionsBtn) {
        refreshSessionsBtn.addEventListener('click', loadSessions);
    }

    // Initial load + auto-refresh every 30s
    loadSessions();
    setInterval(loadSessions, 30000);

    // ==================== END Sessions ====================

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
                        badgeEl.textContent = _ei18n.paid || 'Оплачено';
                        badgeEl.style.cursor = '';
                        badgeEl.title = data.paid_at || '';
                    } else {
                        badgeEl.className = 'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800 cursor-pointer hover:bg-red-200';
                        badgeEl.textContent = _ei18n.notPaid || 'Не оплачено';
                        badgeEl.title = _ei18n.clickToPay || 'Нажмите, чтобы отметить как оплачено';
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
                    showMessage(_ei18n.statusUpdated || 'Статус оплаты обновлен', 'success');
                } else {
                    showMessage((_ei18n.statusError || 'Ошибка: {msg}').replace('{msg}', data.error || ''));
                }
            })
            .catch(function () {
                showMessage(_ei18n.commError || 'Ошибка связи с сервером');
            });
    }
});
