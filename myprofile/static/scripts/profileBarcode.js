(function() {
    var modal = document.getElementById('barcode-modal');
    var backdrop = document.getElementById('barcode-backdrop');
    var img = document.getElementById('barcode-modal-img');
    var title = document.getElementById('barcode-modal-title');
    var codeEl = document.getElementById('barcode-modal-code');
    var closeBtn = document.getElementById('barcode-modal-close');
    var copyBtn = document.getElementById('barcode-copy-btn');
    var downloadLink = document.getElementById('barcode-download-link');

    function openModal(barcodeText, imgData) {
        title.textContent = 'QR-код ' + barcodeText;
        codeEl.textContent = barcodeText;
        downloadLink.href = imgData;
        downloadLink.setAttribute('download', barcodeText + '.png');

        // Проверяем загрузку QR-кода изображения
        img.onload = function() {
            // QR-код успешно загрузился
            modal.classList.remove('hidden');
            modal.classList.add('flex');
        };
        img.onerror = function() {
            // QR-код не загрузился — сообщаем и позволяем повторить
            alert('QR-код не удалось отобразить. Попробуйте нажать "Выдать" ещё раз.');
            modal.classList.remove('flex');
            modal.classList.add('hidden');
        };
        img.src = imgData;

        // Если изображение уже закешировано (complete), проверяем вручную
        if (img.complete && img.naturalWidth > 0) {
            modal.classList.remove('hidden');
            modal.classList.add('flex');
        }
    }

    function closeModal() {
        modal.classList.remove('flex');
        modal.classList.add('hidden');
        img.src = '';
    }

    closeBtn.addEventListener('click', closeModal);
    backdrop.addEventListener('click', closeModal);
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') closeModal();
    });

    copyBtn.addEventListener('click', function() {
        var text = codeEl.textContent || '';
        if (!text) return;
        navigator.clipboard.writeText(text).then(function() {
            copyBtn.textContent = 'Скопировано!';
            setTimeout(function() { copyBtn.textContent = 'Копировать код'; }, 1200);
        }).catch(function() {
            copyBtn.textContent = 'Ошибка';
            setTimeout(function() { copyBtn.textContent = 'Копировать код'; }, 1200);
        });
    });

    var buttons = document.querySelectorAll('.quickIssueBtn');
    if (buttons.length > 0) {
        var MAX_RETRIES = 3;
        var confirmModal = document.getElementById('issue-confirm-modal');
        var confirmBackdrop = document.getElementById('issue-confirm-backdrop');
        var confirmText = document.getElementById('issue-confirm-text');
        var confirmOk = document.getElementById('issue-confirm-ok');
        var activeBtn = null;

        function doIssue(btn, attempt) {
            if (typeof attempt === 'undefined') attempt = 1;
            var btnLabel = btn.dataset.label || 'Выдать';
            var pickupPoint = btn.dataset.pickupPoint;

            confirmModal.classList.remove('flex');
            confirmModal.classList.add('hidden');

            btn.disabled = true;
            btn.textContent = attempt > 1 ? 'Повторная попытка (' + attempt + ')...' : 'Создание...';

            var body = '';
            if (pickupPoint !== undefined && pickupPoint !== '') {
                body = 'pickup_point=' + encodeURIComponent(pickupPoint);
            }

            fetch(btn.dataset.url, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': btn.dataset.csrf,
                    'Content-Type': 'application/x-www-form-urlencoded'
                },
                body: body
            })
            .then(function(resp) { return resp.json(); })
            .then(function(data) {
                if (data.success && data.qr_base64) {
                    var testImg = new Image();
                    testImg.onload = function() {
                        btn.disabled = false;
                        btn.innerHTML = '<i class="ri-hand-coin-line"></i> ' + btnLabel;
                        openModal(data.barcode, data.qr_base64);
                    };
                    testImg.onerror = function() {
                        if (attempt < MAX_RETRIES) {
                            setTimeout(function() { doIssue(btn, attempt + 1); }, 500);
                        } else {
                            btn.disabled = false;
                            btn.innerHTML = '<i class="ri-hand-coin-line"></i> ' + btnLabel;
                            alert('Не удалось сгенерировать QR-код после ' + MAX_RETRIES + ' попыток. Попробуйте ещё раз.');
                        }
                    };
                    testImg.src = data.qr_base64;
                } else if (data.success && !data.qr_base64) {
                    if (attempt < MAX_RETRIES) {
                        setTimeout(function() { doIssue(btn, attempt + 1); }, 500);
                    } else {
                        btn.disabled = false;
                        btn.innerHTML = '<i class="ri-hand-coin-line"></i> ' + btnLabel;
                        alert('QR-код не был сгенерирован. Попробуйте ещё раз.');
                    }
                } else {
                    btn.disabled = false;
                    btn.innerHTML = '<i class="ri-hand-coin-line"></i> ' + btnLabel;
                    alert(data.error || 'Ошибка');
                }
            })
            .catch(function() {
                if (attempt < MAX_RETRIES) {
                    setTimeout(function() { doIssue(btn, attempt + 1); }, 1000);
                } else {
                    btn.disabled = false;
                    btn.innerHTML = '<i class="ri-hand-coin-line"></i> ' + btnLabel;
                    alert('Ошибка связи с сервером. Попробуйте ещё раз.');
                }
            });
        }

        buttons.forEach(function(btn) {
            btn.addEventListener('click', function() {
                activeBtn = btn;
                var readyCount = btn.dataset.readyCount || '0';
                confirmText.textContent = 'Проверяйте количество ваших товаров на пункте выдачи, у вас их ' + readyCount;
                confirmModal.classList.remove('hidden');
                confirmModal.classList.add('flex');
            });
        });

        confirmOk.addEventListener('click', function() {
            if (activeBtn) doIssue(activeBtn, 1);
        });
        confirmBackdrop.addEventListener('click', function() {
            confirmModal.classList.remove('flex');
            confirmModal.classList.add('hidden');
        });
    }
})();
