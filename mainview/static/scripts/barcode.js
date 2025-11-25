document.addEventListener('DOMContentLoaded', function () {
    const modal = document.getElementById('barcode-modal');
    const backdrop = document.getElementById('barcode-backdrop');
    const img = document.getElementById('barcode-modal-img');
    const title = document.getElementById('barcode-modal-title');
    const codeEl = document.getElementById('barcode-modal-code');
    const closeBtn = document.getElementById('barcode-modal-close');
    const copyBtn = document.getElementById('barcode-copy-btn');
    const downloadLink = document.getElementById('barcode-download-link');

    function openModal(barcodeText, imgData) {
        title.textContent = `Штрихкод ${barcodeText}`;
        codeEl.textContent = barcodeText;
        img.src = imgData;
        downloadLink.href = imgData;
        downloadLink.setAttribute('download', `${barcodeText}.png`);
        modal.classList.remove('hidden');
        modal.classList.add('flex');
    }

    function closeModal() {
        modal.classList.remove('flex');
        modal.classList.add('hidden');
        img.src = '';
    }

    document.querySelectorAll('.show-barcode-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const barcode = btn.dataset.barcode || '';
            const imgData = btn.dataset.img || '';
            openModal(barcode, imgData);
        });
    });

    closeBtn.addEventListener('click', closeModal);
    backdrop.addEventListener('click', closeModal);
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeModal();
    });

    copyBtn.addEventListener('click', async () => {
        const text = codeEl.textContent || '';
        if (!text) return;
        try {
            await navigator.clipboard.writeText(text);
            copyBtn.textContent = 'Скопировано!';
            setTimeout(() => copyBtn.textContent = 'Копировать код', 1200);
        } catch (err) {
            copyBtn.textContent = 'Ошибка';
            setTimeout(() => copyBtn.textContent = 'Копировать код', 1200);
        }
    });
});
