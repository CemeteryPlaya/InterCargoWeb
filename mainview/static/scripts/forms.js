document.addEventListener('DOMContentLoaded', () => {
  var _i18n = document.getElementById('js-i18n')?.dataset || {};
  // Auto-uppercase + Latin-only + no spaces for all login fields
  document.querySelectorAll('input[name="login"]').forEach(function (input) {
    // Блокируем пробел на уровне клавиши
    input.addEventListener('keydown', function (e) {
      if (e.key === ' ' || e.code === 'Space') {
        e.preventDefault();
      }
    });
    input.addEventListener('input', function () {
      var oldLen = this.value.length;
      var start = this.selectionStart;
      var end = this.selectionEnd;
      // Убираем кириллицу и пробелы, оставляем только латиницу, цифры и допустимые символы
      var clean = this.value.replace(/[а-яА-ЯёЁ\s]/g, '').toUpperCase();
      this.value = clean;
      // Корректируем позицию курсора если символы были удалены
      var removed = oldLen - clean.length;
      this.setSelectionRange(Math.max(0, start - removed), Math.max(0, end - removed));
    });
  });

  // Password visibility toggle
  document.querySelectorAll('.password-toggle').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var input = this.parentElement.querySelector('input');
      var icon = this.querySelector('i');
      if (input.type === 'password') {
        input.type = 'text';
        icon.classList.remove('ri-eye-off-line');
        icon.classList.add('ri-eye-line');
      } else {
        input.type = 'password';
        icon.classList.remove('ri-eye-line');
        icon.classList.add('ri-eye-off-line');
      }
    });
  });

  const registrationForm = document.getElementById('registration-form');
  const loginForm = document.getElementById('login-form');

  // === Регистрация ===
  if (registrationForm) {
    const password = document.getElementById('password');
    const confirm = document.getElementById('confirm-password');
    const login = document.getElementById('login');
    const pickup = document.getElementById('pickup');
    const phone = document.getElementById('phone');
    const firstName = document.getElementById('first_name');
    const lastName = document.getElementById('last_name');

    confirm?.addEventListener('input', () => {
      confirm.classList.toggle('border-red-500', confirm.value !== password.value);
    });

    registrationForm.addEventListener('submit', e => {
      const raw = phone?.value.replace(/\D/g, '') || '';
      let msg = '';
      if (!lastName || !lastName.value.trim()) msg += (_i18n.enterLastname || 'Введите фамилию.') + '\n';
      if (!firstName || !firstName.value.trim()) msg += (_i18n.enterFirstname || 'Введите имя.') + '\n';
      if (raw.length !== 11 || !raw.startsWith('7')) msg += (_i18n.invalidPhone || 'Неверный телефон.') + '\n';
      if (!login.value.trim()) msg += (_i18n.enterLogin || 'Введите логин.') + '\n';
      if (!pickup.value) msg += (_i18n.selectPickup || 'Выберите пункт выдачи.') + '\n';
      if (!password.value || password.value.length < 6) msg += (_i18n.passwordShort || 'Пароль слишком короткий.') + '\n';
      if (password.value !== confirm.value) msg += (_i18n.passwordsMismatch || 'Пароли не совпадают.') + '\n';
      if (msg) { e.preventDefault(); alert(msg); }
    });
  }

  // === Логин ===
  if (loginForm) {
    const login = document.getElementById('login');
    const pass = document.getElementById('password');
    loginForm.addEventListener('submit', e => {
      let msg = '';
      if (!login.value.trim()) msg += (_i18n.enterLogin || 'Введите логин.') + '\n';
      if (!pass.value) msg += (_i18n.enterPassword || 'Введите пароль.') + '\n';
      if (msg) { e.preventDefault(); alert(msg); }
    });
  }
});