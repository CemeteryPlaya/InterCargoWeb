document.addEventListener('DOMContentLoaded', function () {
    var panel = document.getElementById('acceptance-panel');
    if (!panel) return;

    var receiptsUrl = panel.dataset.receiptsUrl;
    var acceptUrl = panel.dataset.acceptUrl;
    var csrfToken = panel.dataset.csrf;

    // Modal elements
    var modal = document.getElementById('qr-modal');
    var modalTitle = document.getElementById('qr-modal-title');
    var modalClose = document.getElementById('qr-modal-close');
    var cancelBtn = document.getElementById('qr-cancel-btn');
    var submitBtn = document.getElementById('qr-submit-btn');
    var qrReaderDiv = document.getElementById('qr-reader');
    var scannedCountEl = document.getElementById('qr-scanned-count');
    var totalCountEl = document.getElementById('qr-total-count');
    var progressPercent = document.getElementById('qr-progress-percent');
    var progressBar = document.getElementById('qr-progress-bar');
    var clientsListEl = document.getElementById('qr-clients-list');
    var lastScanEl = document.getElementById('qr-last-scan');
    var lastScanText = document.getElementById('qr-last-scan-text');
    var errorEl = document.getElementById('qr-error');

    var scannerInput = document.getElementById('qr-scanner-input');

    // State
    var currentPickupId = null;
    var clientsData = [];
    var allExpectedReceipts = [];
    var scannedReceipts = [];
    var receiptToClient = {};
    var receiptToCell = {};
    var html5QrCode = null;
    var scannerActive = false;
    var scanProcessing = false;
    var scanningInProgress = false;

    // Prevent page reload while scanning
    window.addEventListener('beforeunload', function (e) {
        if (scanningInProgress) {
            e.preventDefault();
            e.returnValue = 'Сортировка не завершена. Вы уверены, что хотите покинуть страницу?';
            return e.returnValue;
        }
    });

    // Keep-alive
    setInterval(function () {
        fetch(window.location.href, { method: 'HEAD', credentials: 'same-origin' }).catch(function () {});
    }, 600000);

    // Scan buttons
    var scanButtons = document.querySelectorAll('.scan-accept-btn');
    scanButtons.forEach(function (btn) {
        btn.addEventListener('click', function () {
            startScan(this.dataset.pickupId, this.dataset.pickupName);
        });
    });

    function startScan(pickupId, pickupName) {
        fetch(receiptsUrl + '?pickup_id=' + encodeURIComponent(pickupId), { credentials: 'same-origin' })
            .then(function (res) { return res.json(); })
            .then(function (data) {
                if (!data.clients || data.clients.length === 0) {
                    submitDirectly(pickupId, []);
                    return;
                }
                var hasReceipts = data.clients.some(function (c) { return c.receipts.length > 0; });
                if (!hasReceipts) {
                    submitDirectly(pickupId, []);
                    return;
                }
                openScanner(pickupId, pickupName, data.clients);
            })
            .catch(function (err) {
                console.error('Error fetching receipts:', err);
                alert('Ошибка загрузки данных. Попробуйте снова.');
            });
    }

    function submitDirectly(pickupId, scannedList) {
        var form = document.createElement('form');
        form.method = 'POST';
        form.action = acceptUrl;
        form.innerHTML =
            '<input type="hidden" name="csrfmiddlewaretoken" value="' + csrfToken + '">' +
            '<input type="hidden" name="pickup_id" value="' + pickupId + '">' +
            '<input type="hidden" name="scanned_receipts" value=\'' + JSON.stringify(scannedList) + '\'>';
        document.body.appendChild(form);
        form.submit();
    }

    function openScanner(pickupId, pickupName, clients) {
        currentPickupId = pickupId;
        clientsData = clients;
        scannedReceipts = [];
        scanningInProgress = true;

        allExpectedReceipts = [];
        receiptToClient = {};
        receiptToCell = {};
        clients.forEach(function (client) {
            client.receipts.forEach(function (r) {
                allExpectedReceipts.push(r.receipt_number);
                receiptToClient[r.receipt_number] = client.full_name;
                receiptToCell[r.receipt_number] = client.cell_number;
            });
        });

        modalTitle.textContent = pickupName;
        updateProgress();
        errorEl.classList.add('hidden');
        lastScanEl.classList.add('hidden');
        submitBtn.disabled = true;

        renderClientsList();
        modal.classList.remove('hidden');
        startCamera();

        // Фокус на поле ввода для сканера
        setTimeout(function () { scannerInput.focus(); }, 300);
    }

    function closeScanner() {
        scanningInProgress = false;
        modal.classList.add('hidden');
        stopCamera();
        qrReaderDiv.innerHTML = '';
        scannerInput.value = '';
    }

    // Обработка ввода от физического сканера (вводит текст + Enter)
    scannerInput.addEventListener('keypress', function (e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            var code = scannerInput.value.trim();
            scannerInput.value = '';
            if (code) {
                onScanSuccess(code);
            }
            // Сохраняем фокус на поле для следующего сканирования
            scannerInput.focus();
        }
    });

    function renderClientsList() {
        clientsListEl.innerHTML = '';

        clientsData.forEach(function (client) {
            if (client.receipts.length === 0) return;

            var clientDiv = document.createElement('div');
            clientDiv.className = 'border border-gray-200 rounded-lg overflow-hidden';

            var header = document.createElement('div');
            header.className = 'px-3 py-2 bg-gray-50 font-medium text-sm text-gray-800 flex items-center justify-between';

            var headerLeft = document.createElement('div');
            headerLeft.className = 'flex items-center gap-2';
            headerLeft.innerHTML = '<i class="ri-user-line text-gray-400"></i> ' +
                client.full_name + ' <span class="text-xs text-gray-400">(' + client.username + ')</span>';
            header.appendChild(headerLeft);

            // Ячейка хранения
            if (client.cell_number) {
                var cellBadge = document.createElement('span');
                cellBadge.className = 'inline-flex items-center px-2 py-0.5 rounded-full text-xs font-bold bg-blue-100 text-blue-800';
                cellBadge.innerHTML = '<i class="ri-inbox-archive-line mr-1"></i>Ячейка ' + client.cell_number;
                header.appendChild(cellBadge);
            }

            clientDiv.appendChild(header);

            client.receipts.forEach(function (r) {
                var row = document.createElement('div');
                row.className = 'receipt-row flex items-center gap-2 px-3 py-2 border-t border-gray-100 text-sm';
                row.dataset.receipt = r.receipt_number;

                var icon = document.createElement('i');
                icon.className = 'ri-checkbox-blank-circle-line text-gray-300 receipt-icon text-base';
                row.appendChild(icon);

                var info = document.createElement('div');
                info.className = 'flex-1';
                info.innerHTML = '<span class="font-mono text-xs">' + r.receipt_number + '</span>' +
                    '<span class="text-gray-400 ml-2 text-xs">' + r.track_count + ' шт. / ' +
                    r.total_weight.toFixed(3) + ' кг</span>';
                row.appendChild(info);

                var manualBtn = document.createElement('button');
                manualBtn.type = 'button';
                manualBtn.className = 'manual-check-btn px-2 py-1 text-xs rounded bg-gray-100 text-gray-600 hover:bg-green-100 hover:text-green-700 transition';
                manualBtn.innerHTML = '<i class="ri-check-line"></i>';
                manualBtn.title = 'Отметить вручную';
                manualBtn.dataset.receipt = r.receipt_number;
                row.appendChild(manualBtn);

                clientDiv.appendChild(row);
            });

            clientsListEl.appendChild(clientDiv);
        });
    }

    // Manual check handler
    clientsListEl.addEventListener('click', function (e) {
        var btn = e.target.closest('.manual-check-btn');
        if (!btn) return;
        var code = btn.dataset.receipt;
        if (!code || scannedReceipts.indexOf(code) !== -1) return;

        scannedReceipts.push(code);
        markReceiptScanned(code);
        showCellInfo(code);
        updateProgress();

        if (scannedReceipts.length >= allExpectedReceipts.length) {
            onAllScanned();
        }
    });

    function markReceiptScanned(receiptNumber) {
        var rows = clientsListEl.querySelectorAll('.receipt-row');
        rows.forEach(function (row) {
            if (row.dataset.receipt === receiptNumber) {
                row.classList.add('bg-green-50');
                var icon = row.querySelector('.receipt-icon');
                if (icon) {
                    icon.className = 'ri-checkbox-circle-fill text-green-500 receipt-icon text-base';
                }
                var btn = row.querySelector('.manual-check-btn');
                if (btn) {
                    btn.classList.add('hidden');
                }
            }
        });
    }

    function showCellInfo(receiptNumber) {
        var clientName = receiptToClient[receiptNumber] || '';
        var cellNumber = receiptToCell[receiptNumber];
        var text = receiptNumber;
        if (clientName) text += ' — ' + clientName;
        if (cellNumber) text += ' → Ячейка ' + cellNumber;
        lastScanText.textContent = text;
        lastScanEl.classList.remove('hidden');
        setTimeout(function () { lastScanEl.classList.add('hidden'); }, 4000);
    }

    // Camera
    function startCamera() {
        if (scannerActive) return;
        html5QrCode = new Html5Qrcode('qr-reader');
        html5QrCode.start(
            { facingMode: 'environment' },
            { fps: 10, qrbox: { width: 250, height: 250 }, aspectRatio: 1.0 },
            onScanSuccess,
            function () {}
        ).then(function () {
            scannerActive = true;
        }).catch(function (err) {
            console.error('Camera error:', err);
            showError('Не удалось получить доступ к камере. Разрешите доступ в настройках браузера.');
        });
    }

    function stopCamera() {
        if (html5QrCode && scannerActive) {
            html5QrCode.stop().then(function () {
                html5QrCode.clear();
                scannerActive = false;
            }).catch(function () {
                scannerActive = false;
            });
        }
    }

    function onScanSuccess(decodedText) {
        if (scanProcessing) return;
        var code = decodedText.trim();

        if (scannedReceipts.indexOf(code) !== -1) {
            showError('Этот QR-код уже отсканирован: ' + code);
            return;
        }
        if (allExpectedReceipts.indexOf(code) === -1) {
            showError('Неизвестный QR-код: ' + code);
            return;
        }

        scanProcessing = true;
        setTimeout(function () { scanProcessing = false; }, 1500);

        scannedReceipts.push(code);
        errorEl.classList.add('hidden');

        markReceiptScanned(code);
        showCellInfo(code);
        updateProgress();

        if (scannedReceipts.length >= allExpectedReceipts.length) {
            onAllScanned();
        }
    }

    function onAllScanned() {
        submitBtn.disabled = false;
        stopCamera();
        qrReaderDiv.innerHTML =
            '<div class="flex flex-col items-center justify-center py-6 text-green-600">' +
            '<i class="ri-checkbox-circle-fill text-5xl mb-2"></i>' +
            '<p class="font-semibold text-lg">Все QR-коды отсканированы!</p>' +
            '</div>';
    }

    function updateProgress() {
        var total = allExpectedReceipts.length;
        var scanned = scannedReceipts.length;
        var pct = total > 0 ? Math.round((scanned / total) * 100) : 0;

        scannedCountEl.textContent = scanned;
        totalCountEl.textContent = total;
        progressPercent.textContent = pct + '%';
        progressBar.style.width = pct + '%';

        if (scanned > 0) {
            submitBtn.disabled = false;
        }
    }

    function showError(msg) {
        errorEl.textContent = msg;
        errorEl.classList.remove('hidden');
        setTimeout(function () { errorEl.classList.add('hidden'); }, 3000);
    }

    // Modal actions
    modalClose.addEventListener('click', function () {
        if (scannedReceipts.length > 0 && scannedReceipts.length < allExpectedReceipts.length) {
            if (!confirm('Сортировка не завершена. Вы уверены, что хотите отменить?')) return;
        }
        closeScanner();
    });

    cancelBtn.addEventListener('click', function () {
        if (scannedReceipts.length > 0 && scannedReceipts.length < allExpectedReceipts.length) {
            if (!confirm('Сортировка не завершена. Вы уверены, что хотите отменить?')) return;
        }
        closeScanner();
    });

    submitBtn.addEventListener('click', function () {
        if (scannedReceipts.length === 0) return;

        if (scannedReceipts.length < allExpectedReceipts.length) {
            var remaining = allExpectedReceipts.length - scannedReceipts.length;
            if (!confirm('Не все чеки отсканированы (' + remaining + ' осталось). Не отсканированные чеки НЕ будут отсортированы. Продолжить?')) {
                return;
            }
        }

        scanningInProgress = false;
        submitDirectly(currentPickupId, scannedReceipts);
    });

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && !modal.classList.contains('hidden')) {
            modalClose.click();
        }
    });
});
