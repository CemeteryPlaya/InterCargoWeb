(function() {
    var container = document.getElementById('password-reset-container');
    if (!container) return;

    var csrf = container.dataset.csrf;
    var urlReset = container.dataset.urlReset;
    var urlVerify = container.dataset.urlVerify;
    var urlSetPassword = container.dataset.urlSetPassword;
    var resendInterval = null;

    var codeInput = document.getElementById('reset-code');
    codeInput.addEventListener('input', function(e) {
        var val = this.value.replace(/[^0-9]/g, '');
        if (val.length > 6) val = val.substring(0, 6);
        if (val.length > 3) {
            this.value = val.substring(0, 3) + '-' + val.substring(3);
        } else {
            this.value = val;
        }
    });

    function showError(stepId, msg) {
        var el = document.getElementById(stepId);
        el.textContent = msg;
        el.classList.remove('hidden');
    }
    function hideError(stepId) {
        document.getElementById(stepId).classList.add('hidden');
    }
    function showStep(n) {
        for (var i = 1; i <= 4; i++) {
            document.getElementById('step-' + i).classList.toggle('hidden', i !== n);
        }
    }

    function startResendTimer() {
        var btn = document.getElementById('btn-resend');
        var timerSpan = document.getElementById('resend-timer');
        var seconds = 60;
        btn.disabled = true;
        btn.classList.remove('text-primary');
        btn.classList.add('text-gray-400');
        timerSpan.textContent = seconds;

        if (resendInterval) clearInterval(resendInterval);
        resendInterval = setInterval(function() {
            seconds--;
            timerSpan.textContent = seconds;
            if (seconds <= 0) {
                clearInterval(resendInterval);
                btn.disabled = false;
                btn.classList.add('text-primary');
                btn.classList.remove('text-gray-400');
                btn.innerHTML = 'Отправить повторно';
            }
        }, 1000);
    }

    document.getElementById('btn-send-code').addEventListener('click', function() {
        var identifier = document.getElementById('identifier').value.trim();
        if (!identifier) return;

        hideError('step1-error');
        this.disabled = true;
        this.textContent = 'Отправка...';

        var self = this;
        fetch(urlReset, {
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': csrf},
            body: 'identifier=' + encodeURIComponent(identifier)
        })
        .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, data: d}; }); })
        .then(function(res) {
            self.disabled = false;
            self.textContent = 'Отправить код';
            if (res.data.success) {
                document.getElementById('masked-email').textContent = res.data.masked_email;
                document.getElementById('masked-login').textContent = res.data.masked_login;
                showStep(2);
                startResendTimer();
            } else {
                showError('step1-error', res.data.error || 'Произошла ошибка.');
            }
        })
        .catch(function() {
            self.disabled = false;
            self.textContent = 'Отправить код';
            showError('step1-error', 'Ошибка сети. Попробуйте позже.');
        });
    });

    document.getElementById('btn-resend').addEventListener('click', function() {
        var identifier = document.getElementById('identifier').value.trim();
        if (!identifier) return;

        hideError('step2-error');
        this.disabled = true;

        var self = this;
        fetch(urlReset, {
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': csrf},
            body: 'identifier=' + encodeURIComponent(identifier)
        })
        .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, data: d}; }); })
        .then(function(res) {
            if (res.data.success) {
                startResendTimer();
            } else {
                showError('step2-error', res.data.error || 'Произошла ошибка.');
                self.disabled = false;
            }
        })
        .catch(function() {
            showError('step2-error', 'Ошибка сети.');
            self.disabled = false;
        });
    });

    document.getElementById('btn-verify-code').addEventListener('click', function() {
        var code = document.getElementById('reset-code').value.trim();
        if (!code) return;

        hideError('step2-error');
        this.disabled = true;
        this.textContent = 'Проверка...';

        var self = this;
        fetch(urlVerify, {
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': csrf},
            body: 'code=' + encodeURIComponent(code)
        })
        .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, data: d}; }); })
        .then(function(res) {
            self.disabled = false;
            self.textContent = 'Подтвердить код';
            if (res.data.success) {
                showStep(3);
            } else {
                showError('step2-error', res.data.error || 'Неверный код.');
            }
        })
        .catch(function() {
            self.disabled = false;
            self.textContent = 'Подтвердить код';
            showError('step2-error', 'Ошибка сети.');
        });
    });

    document.getElementById('btn-set-password').addEventListener('click', function() {
        var pw = document.getElementById('new-password').value;
        var pw2 = document.getElementById('confirm-password').value;

        hideError('step3-error');

        if (pw.length < 6) {
            showError('step3-error', 'Пароль должен быть не менее 6 символов.');
            return;
        }
        if (pw !== pw2) {
            showError('step3-error', 'Пароли не совпадают.');
            return;
        }

        this.disabled = true;
        this.textContent = 'Сохранение...';

        var self = this;
        fetch(urlSetPassword, {
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': csrf},
            body: 'password=' + encodeURIComponent(pw) + '&password_confirm=' + encodeURIComponent(pw2)
        })
        .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, data: d}; }); })
        .then(function(res) {
            self.disabled = false;
            self.textContent = 'Установить пароль';
            if (res.data.success) {
                showStep(4);
            } else {
                showError('step3-error', res.data.error || 'Произошла ошибка.');
            }
        })
        .catch(function() {
            self.disabled = false;
            self.textContent = 'Установить пароль';
            showError('step3-error', 'Ошибка сети.');
        });
    });

    document.getElementById('identifier').addEventListener('keydown', function(e) {
        if (e.key === 'Enter') document.getElementById('btn-send-code').click();
    });
    codeInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') document.getElementById('btn-verify-code').click();
    });
    document.getElementById('confirm-password').addEventListener('keydown', function(e) {
        if (e.key === 'Enter') document.getElementById('btn-set-password').click();
    });
})();
