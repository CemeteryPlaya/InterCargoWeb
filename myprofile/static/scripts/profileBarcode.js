(function() {
    var modal = document.getElementById('barcode-modal');
    var backdrop = document.getElementById('barcode-backdrop');
    var img = document.getElementById('barcode-modal-img');
    var title = document.getElementById('barcode-modal-title');
    var codeEl = document.getElementById('barcode-modal-code');
    var closeBtn = document.getElementById('barcode-modal-close');
    var copyBtn = document.getElementById('barcode-copy-btn');
    var downloadLink = document.getElementById('barcode-download-link');
    /* PAYMENT COMMENTED OUT */
    // var paymentLinkEl = document.getElementById('barcode-payment-link');

    function openModal(barcodeText, imgData, paymentUrl) {
        title.textContent = 'QR-код ' + barcodeText;
        codeEl.textContent = barcodeText;
        img.src = imgData;
        downloadLink.href = imgData;
        downloadLink.setAttribute('download', barcodeText + '.png');
        /* PAYMENT COMMENTED OUT
        if (paymentLinkEl) {
            if (paymentUrl) {
                paymentLinkEl.href = paymentUrl;
                paymentLinkEl.classList.remove('hidden');
            } else {
                paymentLinkEl.classList.add('hidden');
            }
        }
        */
        modal.classList.remove('hidden');
        modal.classList.add('flex');
    }

    function closeModal() {
        modal.classList.remove('flex');
        modal.classList.add('hidden');
        img.src = '';
        /* PAYMENT COMMENTED OUT: if (paymentLinkEl) paymentLinkEl.classList.add('hidden'); */
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

    var btn = document.getElementById('quickIssueBtn');
    if (btn) {
        var btnLabel = btn.dataset.label || 'Выдать';
        var readyCount = btn.dataset.readyCount || '0';

        var confirmModal = document.getElementById('issue-confirm-modal');
        var confirmBackdrop = document.getElementById('issue-confirm-backdrop');
        var confirmText = document.getElementById('issue-confirm-text');
        var confirmOk = document.getElementById('issue-confirm-ok');

        function doIssue() {
            confirmModal.classList.remove('flex');
            confirmModal.classList.add('hidden');

            btn.disabled = true;
            btn.textContent = 'Создание...';

            fetch(btn.dataset.url, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': btn.dataset.csrf,
                    'Content-Type': 'application/x-www-form-urlencoded'
                }
            })
            .then(function(resp) { return resp.json(); })
            .then(function(data) {
                if (data.success) {
                    openModal(data.barcode, data.qr_base64, data.payment_link);
                } else {
                    alert(data.error || 'Ошибка');
                }
            })
            .catch(function() {
                alert('Ошибка связи с сервером');
            })
            .finally(function() {
                btn.disabled = false;
                btn.innerHTML = '<i class="ri-hand-coin-line"></i> ' + btnLabel;
            });
        }

        btn.addEventListener('click', function() {
            confirmText.textContent = 'Проверяйте количество ваших товаров на пункте выдачи, у вас их ' + readyCount;
            confirmModal.classList.remove('hidden');
            confirmModal.classList.add('flex');
        });

        confirmOk.addEventListener('click', doIssue);
        confirmBackdrop.addEventListener('click', function() {
            confirmModal.classList.remove('flex');
            confirmModal.classList.add('hidden');
        });
    }
})();
