function switchTab(tab) {
    const registerTab = document.getElementById('tab-register');
    const loginTab = document.getElementById('tab-login');
    const registerForm = document.getElementById('register-form-container');
    const loginForm = document.getElementById('login-form-container');
    const sectionTitle = document.getElementById('section-title');
    const sectionHeading = document.getElementById('section-heading');
    const sectionDescription = document.getElementById('section-description');

    if (tab === 'register') {
        registerTab.classList.add('active', 'bg-primary', 'text-white');
        registerTab.classList.remove('text-gray-700', 'hover:text-primary');
        loginTab.classList.remove('active', 'bg-primary', 'text-white');
        loginTab.classList.add('text-gray-700', 'hover:text-primary');
        registerForm.classList.remove('hidden');
        loginForm.classList.add('hidden');
        sectionTitle.textContent = 'РЕГИСТРАЦИЯ';
        sectionHeading.textContent = 'Регистрация нового клиента';
        sectionDescription.textContent = 'Заполните форму ниже, чтобы зарегистрироваться в нашей системе и начать пользоваться услугами доставки из Китая';
    } else {
        loginTab.classList.add('active', 'bg-primary', 'text-white');
        loginTab.classList.remove('text-gray-700', 'hover:text-primary');
        registerTab.classList.remove('active', 'bg-primary', 'text-white');
        registerTab.classList.add('text-gray-700', 'hover:text-primary');
        loginForm.classList.remove('hidden');
        registerForm.classList.add('hidden');
        sectionTitle.textContent = 'АВТОРИЗАЦИЯ';
        sectionHeading.textContent = 'Вход клиента';
        sectionDescription.textContent = 'Заполните форму ниже, чтобы войти в свой аккаунт в нашей системе и начать пользоваться услугами доставки из Китая';
    }
}
