document.addEventListener('DOMContentLoaded', () => {
  const registrationForm = document.getElementById('registration-form');
  const loginForm = document.getElementById('login-form');

  // === Регистрация ===
  if (registrationForm) {
    const password = document.getElementById('password');
    const confirm = document.getElementById('confirm-password');
    const login = document.getElementById('login');
    const pickup = document.getElementById('pickup');
    const phone = document.getElementById('phone');

    confirm?.addEventListener('input', () => {
      confirm.classList.toggle('border-red-500', confirm.value !== password.value);
    });

    registrationForm.addEventListener('submit', e => {
      const raw = phone?.value.replace(/\D/g, '') || '';
      let msg = '';
      if (raw.length !== 11 || !raw.startsWith('7')) msg += 'Неверный телефон.\n';
      if (!login.value.trim()) msg += 'Введите логин.\n';
      if (!pickup.value) msg += 'Выберите пункт выдачи.\n';
      if (!password.value || password.value.length < 6) msg += 'Пароль слишком короткий.\n';
      if (password.value !== confirm.value) msg += 'Пароли не совпадают.\n';
      if (msg) { e.preventDefault(); alert(msg); }
    });
  }

  // === Логин ===
  if (loginForm) {
    const login = document.getElementById('login');
    const pass = document.getElementById('password');
    loginForm.addEventListener('submit', e => {
      let msg = '';
      if (!login.value.trim()) msg += 'Введите логин.\n';
      if (!pass.value) msg += 'Введите пароль.\n';
      if (msg) { e.preventDefault(); alert(msg); }
    });
  }
});