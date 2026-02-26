document.addEventListener('DOMContentLoaded', function() {
    var trackInput = document.getElementById('track-code-input');
    var trackError = document.getElementById('track-code-error');
    if (!trackInput) return;

    trackInput.addEventListener('input', function() {
        var clean = this.value.replace(/[а-яА-ЯёЁ]/g, '');
        if (clean !== this.value) {
            this.value = clean;
            trackError.textContent = 'Трек-код должен содержать только латинские буквы и цифры';
        } else {
            trackError.textContent = '';
        }
    });

    var form = trackInput.closest('form');
    if (form) {
        form.addEventListener('submit', function(e) {
            var val = trackInput.value.trim();
            if (/^2\d{5}-\d/.test(val)) {
                e.preventDefault();
                trackError.textContent = 'Неверный формат трек-кода. Код не должен начинаться с "2XXXXX-X"';
                trackInput.focus();
                return;
            }
            if (val.indexOf('№') !== -1) {
                e.preventDefault();
                trackError.textContent = 'Трек-код не должен содержать символ "№"';
                trackInput.focus();
                return;
            }
            if (/[а-яА-ЯёЁ]/.test(val)) {
                e.preventDefault();
                trackError.textContent = 'Трек-код должен содержать только латинские буквы и цифры';
                trackInput.focus();
                return;
            }
            trackError.textContent = '';
        });
    }
});
