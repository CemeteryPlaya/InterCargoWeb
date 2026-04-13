/**
 * mobile_qr.html — tabs, quick-issue POST button, barcode modal.
 * All URLs and CSRF tokens are provided via data-attributes on the triggering
 * elements, so this script does not need any server-rendered values.
 */
(function() {
    // === Табы ===
    var tabReady = document.getElementById('tab-ready');
    var tabHistory = document.getElementById('tab-history');
    var panelReady = document.getElementById('panel-ready');
    var panelHistory = document.getElementById('panel-history');

    function switchTab(active, inactive, showPanel, hidePanel) {
        active.classList.add('border-primary', 'text-primary');
        active.classList.remove('border-transparent', 'text-gray-500');
        inactive.classList.remove('border-primary', 'text-primary');
        inactive.classList.add('border-transparent', 'text-gray-500');
        showPanel.classList.remove('hidden');
        hidePanel.classList.add('hidden');
    }

    if (tabReady && tabHistory) {
        tabReady.addEventListener('click', function() {
            switchTab(tabReady, tabHistory, panelReady, panelHistory);
        });
        tabHistory.addEventListener('click', function() {
            switchTab(tabHistory, tabReady, panelHistory, panelReady);
        });
        // Авто-переключение по ?tab=history
        if (new URLSearchParams(window.location.search).get('tab') === 'history') {
            switchTab(tabHistory, tabReady, panelHistory, panelReady);
        }
    }

    // === Quick Issue ===
    document.querySelectorAll('.quickIssueBtn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var url = btn.dataset.url;
            var csrf = btn.dataset.csrf;
            var pickupPoint = btn.dataset.pickupPoint;

            btn.disabled = true;
            btn.innerHTML = '<i class="ri-loader-4-line animate-spin mr-1"></i> Формирование...';

            var body = new URLSearchParams();
            if (pickupPoint !== undefined) {
                body.append('pickup_point', pickupPoint);
            }

            fetch(url, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrf,
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: body.toString()
            })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.success) {
                    window.location.reload();
                } else {
                    alert(data.error || 'Ошибка');
                    btn.disabled = false;
                    btn.innerHTML = '<i class="ri-hand-coin-line mr-1"></i> ' + btn.dataset.label;
                }
            })
            .catch(function() {
                alert('Ошибка сети');
                btn.disabled = false;
                btn.innerHTML = '<i class="ri-hand-coin-line mr-1"></i> ' + btn.dataset.label;
            });
        });
    });

    // === Barcode Modal ===
    var modal = document.getElementById('barcode-modal');
    var backdrop = document.getElementById('barcode-backdrop');
    var closeBtn = document.getElementById('barcode-modal-close');
    var modalImg = document.getElementById('barcode-modal-img');
    var modalCode = document.getElementById('barcode-modal-code');
    var copyBtn = document.getElementById('barcode-copy-btn');
    var downloadLink = document.getElementById('barcode-download-link');

    function openModal(img, code) {
        modalImg.src = img;
        modalCode.textContent = code;
        if (downloadLink) {
            downloadLink.href = img;
            downloadLink.download = code + '.png';
        }
        modal.classList.remove('hidden');
        modal.classList.add('flex');
    }

    function closeModal() {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }

    if (closeBtn) closeBtn.addEventListener('click', closeModal);
    if (backdrop) backdrop.addEventListener('click', closeModal);

    if (copyBtn) {
        copyBtn.addEventListener('click', function() {
            var code = modalCode.textContent;
            navigator.clipboard.writeText(code).then(function() {
                copyBtn.textContent = 'Скопировано!';
                setTimeout(function() { copyBtn.textContent = 'Копировать код'; }, 1500);
            });
        });
    }

})();
