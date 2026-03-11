document.addEventListener('DOMContentLoaded', function () {
    // ============================================
    // Tab switching
    // ============================================
    var tabButtons = document.querySelectorAll('.tab-delivery-btn');
    var tabPanels = document.querySelectorAll('.tab-delivery-panel');

    tabButtons.forEach(function (btn) {
        btn.addEventListener('click', function () {
            var targetTab = this.dataset.tab;

            tabButtons.forEach(function (b) {
                b.classList.remove('border-primary', 'text-primary');
                b.classList.add('border-transparent', 'text-gray-500');
            });
            this.classList.remove('border-transparent', 'text-gray-500');
            this.classList.add('border-primary', 'text-primary');

            tabPanels.forEach(function (panel) {
                panel.classList.add('hidden');
            });
            document.getElementById('panel-' + targetTab).classList.remove('hidden');
        });
    });

    // ============================================
    // Select all (for home delivery checkboxes)
    // ============================================
    var selectAllTake = document.getElementById('select-all-take');
    if (selectAllTake) {
        selectAllTake.addEventListener('click', function () {
            var form = document.getElementById('home-delivery-form');
            if (!form) return;
            var checkboxes = form.querySelectorAll('input[type="checkbox"]');
            var allChecked = Array.from(checkboxes).every(function (cb) { return cb.checked; });
            checkboxes.forEach(function (cb) { cb.checked = !allChecked; });
            this.textContent = allChecked ? 'Выбрать все' : 'Снять все';
        });
    }

    var selectAllComplete = document.getElementById('select-all-complete');
    if (selectAllComplete) {
        selectAllComplete.addEventListener('click', function () {
            var panel = document.getElementById('panel-complete');
            var checkboxes = panel.querySelectorAll('input[type="checkbox"]');
            var allChecked = Array.from(checkboxes).every(function (cb) { return cb.checked; });
            checkboxes.forEach(function (cb) { cb.checked = !allChecked; });
            this.textContent = allChecked ? 'Выбрать все' : 'Снять все';
        });
    }

    // ============================================
    // History expand/collapse
    // ============================================
    var historyPanel = document.getElementById('panel-history');
    if (historyPanel) {
        historyPanel.addEventListener('click', function (e) {
            var toggle = e.target.closest('.history-toggle');
            if (!toggle) return;

            var targetId = toggle.dataset.target;
            var content = document.getElementById(targetId);
            var arrow = toggle.querySelector('.history-arrow');

            if (content) content.classList.toggle('hidden');
            if (arrow) arrow.classList.toggle('rotate-180');
        });
    }

    // ============================================
    // QR Scanner for per-pickup-point scanning
    // ============================================
    var takePanel = document.getElementById('panel-take');
    if (!takePanel) return;

    var receiptsUrl = takePanel.dataset.receiptsUrl;
    var takeUrl = takePanel.dataset.takeUrl;
    var csrfToken = takePanel.dataset.csrf;

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

    // Scanner state
    var currentPickupId = null;
    var clientsData = [];            // from server: [{username, full_name, receipts: [{receipt_number, track_count, total_weight}]}]
    var allExpectedReceipts = [];    // flat list of receipt_numbers
    var scannedReceipts = [];        // already scanned receipt_numbers
    var receiptToClient = {};        // receipt_number → username (for quick lookup)
    var html5QrCode = null;
    var scannerActive = false;
    var scanProcessing = false;

    // Prevent page reload while scanning
    var scanningInProgress = false;
    window.addEventListener('beforeunload', function (e) {
        if (scanningInProgress) {
            e.preventDefault();
            e.returnValue = 'Сканирование не завершено. Вы уверены, что хотите покинуть страницу?';
            return e.returnValue;
        }
    });

    // Keep-alive: ping server every 10 minutes
    setInterval(function () {
        fetch(window.location.href, { method: 'HEAD', credentials: 'same-origin' }).catch(function () {});
    }, 600000);

    // ============================================
    // Per-pickup scan buttons
    // ============================================
    var currentDeliveredDate = '';

    var scanButtons = document.querySelectorAll('.scan-pickup-btn');
    scanButtons.forEach(function (btn) {
        btn.addEventListener('click', function () {
            var pickupId = this.dataset.pickupId;
            var pickupName = this.dataset.pickupName;
            var deliveredDate = this.dataset.deliveredDate || '';
            startScanForPickup(pickupId, pickupName, deliveredDate);
        });
    });

    function startScanForPickup(pickupId, pickupName, deliveredDate) {
        currentDeliveredDate = deliveredDate;
        // Fetch receipt data for this pickup (with date filter)
        var url = receiptsUrl + '?pickup_id=' + encodeURIComponent(pickupId);
        if (deliveredDate) url += '&delivered_date=' + encodeURIComponent(deliveredDate);

        fetch(url, { credentials: 'same-origin' })
            .then(function (res) { return res.json(); })
            .then(function (data) {
                if (!data.clients || data.clients.length === 0) {
                    submitDirectly(pickupId, [], deliveredDate);
                    return;
                }

                openScanner(pickupId, pickupName, data.clients);
            })
            .catch(function (err) {
                console.error('Error fetching receipts:', err);
                alert('Ошибка загрузки данных. Попробуйте снова.');
            });
    }

    function submitDirectly(pickupId, scannedList, deliveredDate) {
        var form = document.createElement('form');
        form.method = 'POST';
        form.action = takeUrl;
        form.innerHTML =
            '<input type="hidden" name="csrfmiddlewaretoken" value="' + csrfToken + '">' +
            '<input type="hidden" name="pickup_id" value="' + pickupId + '">' +
            '<input type="hidden" name="delivered_date" value="' + (deliveredDate || '') + '">' +
            '<input type="hidden" name="scanned_receipts" value=\'' + JSON.stringify(scannedList) + '\'>';
        document.body.appendChild(form);
        form.submit();
    }

    // ============================================
    // Scanner Modal
    // ============================================
    function openScanner(pickupId, pickupName, clients) {
        currentPickupId = pickupId;
        clientsData = clients;
        scannedReceipts = [];
        scanningInProgress = true;

        // Build flat list and lookup
        allExpectedReceipts = [];
        receiptToClient = {};
        clients.forEach(function (client) {
            client.receipts.forEach(function (r) {
                allExpectedReceipts.push(r.receipt_number);
                receiptToClient[r.receipt_number] = client.username;
            });
        });

        // Set title
        modalTitle.textContent = pickupName;

        // Reset UI
        updateProgress();
        errorEl.classList.add('hidden');
        lastScanEl.classList.add('hidden');
        submitBtn.disabled = true;

        // Build clients list
        renderClientsList();

        modal.classList.remove('hidden');

        if (allExpectedReceipts.length > 0) {
            startCamera();
        } else {
            // No receipts to scan (e.g. only TempUser tracks) — allow submit immediately
            submitBtn.disabled = false;
            qrReaderDiv.innerHTML =
                '<div class="flex flex-col items-center justify-center py-6 text-yellow-600">' +
                '<i class="ri-information-line text-5xl mb-2"></i>' +
                '<p class="font-semibold text-lg">Нет QR-кодов для сканирования</p>' +
                '<p class="text-sm text-gray-500 mt-1">У клиентов нет чеков — можно сразу взять в доставку</p>' +
                '</div>';
        }
    }

    function closeScanner() {
        scanningInProgress = false;
        modal.classList.add('hidden');
        stopCamera();
        qrReaderDiv.innerHTML = '';
    }

    function renderClientsList() {
        clientsListEl.innerHTML = '';

        clientsData.forEach(function (client) {
            var hasReceipts = client.receipts.length > 0;
            var hasNoReceiptTracks = client.no_receipt_tracks > 0;

            if (!hasReceipts && !hasNoReceiptTracks) return;

            var clientDiv = document.createElement('div');
            clientDiv.className = 'border border-gray-200 rounded-lg overflow-hidden';

            // Client header
            var header = document.createElement('div');
            header.className = 'px-3 py-2 bg-gray-50 font-medium text-sm text-gray-800 flex items-center gap-2';
            header.innerHTML = '<i class="ri-user-line text-gray-400"></i> ' +
                client.full_name + ' <span class="text-xs text-gray-400">(' + client.username + ')</span>';
            clientDiv.appendChild(header);

            // Receipts
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
                manualBtn.className = 'manual-check-btn px-2 py-1 text-xs rounded bg-gray-100 text-gray-600 hover:bg-blue-100 hover:text-blue-700 transition';
                manualBtn.innerHTML = '<i class="ri-check-line"></i>';
                manualBtn.title = 'Отметить вручную';
                manualBtn.dataset.receipt = r.receipt_number;
                row.appendChild(manualBtn);

                clientDiv.appendChild(row);
            });

            // Tracks without receipts (e.g. TempUser clients)
            if (hasNoReceiptTracks) {
                var noReceiptRow = document.createElement('div');
                noReceiptRow.className = 'flex items-center gap-2 px-3 py-2 border-t border-gray-100 text-sm bg-yellow-50';
                var noReceiptWeight = client.no_receipt_weight || 0;
                noReceiptRow.innerHTML =
                    '<i class="ri-information-line text-yellow-500 text-base"></i>' +
                    '<div class="flex-1">' +
                    '<span class="text-yellow-700 text-xs">Без чека: ' + client.no_receipt_tracks + ' шт. / ' +
                    noReceiptWeight.toFixed(3) + ' кг</span>' +
                    '</div>';
                clientDiv.appendChild(noReceiptRow);
            }

            clientsListEl.appendChild(clientDiv);
        });
    }

    // Manual check button handler (delegated)
    clientsListEl.addEventListener('click', function (e) {
        var btn = e.target.closest('.manual-check-btn');
        if (!btn) return;
        var code = btn.dataset.receipt;
        if (!code || scannedReceipts.indexOf(code) !== -1) return;

        scannedReceipts.push(code);
        markReceiptScanned(code);
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

    // ============================================
    // Camera
    // ============================================
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

        // Already scanned?
        if (scannedReceipts.indexOf(code) !== -1) {
            showError('Этот QR-код уже отсканирован: ' + code);
            return;
        }

        // Is it expected?
        if (allExpectedReceipts.indexOf(code) === -1) {
            showError('Неизвестный QR-код: ' + code);
            return;
        }

        // Prevent rapid duplicates
        scanProcessing = true;
        setTimeout(function () { scanProcessing = false; }, 1500);

        // Accept
        scannedReceipts.push(code);
        errorEl.classList.add('hidden');

        // Show success flash
        var clientName = receiptToClient[code] || '';
        lastScanText.textContent = code + (clientName ? ' — ' + clientName : '');
        lastScanEl.classList.remove('hidden');
        setTimeout(function () { lastScanEl.classList.add('hidden'); }, 2500);

        // Mark in client list
        markReceiptScanned(code);

        updateProgress();

        // All scanned?
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

        // Enable submit when at least 1 receipt scanned (partial delivery allowed)
        if (scanned > 0) {
            submitBtn.disabled = false;
        }
    }

    function showError(msg) {
        errorEl.textContent = msg;
        errorEl.classList.remove('hidden');
        setTimeout(function () { errorEl.classList.add('hidden'); }, 3000);
    }

    // ============================================
    // Modal actions
    // ============================================
    modalClose.addEventListener('click', function () {
        if (scannedReceipts.length > 0 && scannedReceipts.length < allExpectedReceipts.length) {
            if (!confirm('Сканирование не завершено. Вы уверены, что хотите отменить?')) return;
        }
        closeScanner();
    });

    cancelBtn.addEventListener('click', function () {
        if (scannedReceipts.length > 0 && scannedReceipts.length < allExpectedReceipts.length) {
            if (!confirm('Сканирование не завершено. Вы уверены, что хотите отменить?')) return;
        }
        closeScanner();
    });

    submitBtn.addEventListener('click', function () {
        if (scannedReceipts.length === 0) return;

        // If not all scanned, confirm
        if (scannedReceipts.length < allExpectedReceipts.length) {
            var remaining = allExpectedReceipts.length - scannedReceipts.length;
            if (!confirm('Не все чеки отсканированы (' + remaining + ' осталось). Не отсканированные чеки НЕ будут взяты в доставку. Продолжить?')) {
                return;
            }
        }

        scanningInProgress = false;
        submitDirectly(currentPickupId, scannedReceipts, currentDeliveredDate);
    });

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && !modal.classList.contains('hidden')) {
            modalClose.click();
        }
    });
});
