function switchIndexLoginMethod(method) {
    var loginForm = document.getElementById('idx-login-by-login');
    var phoneForm = document.getElementById('idx-login-by-phone');
    var tabLogin = document.getElementById('idx-tab-login');
    var tabPhone = document.getElementById('idx-tab-phone');

    if (method === 'phone') {
        loginForm.classList.add('hidden');
        phoneForm.classList.remove('hidden');
        tabPhone.classList.add('bg-white', 'shadow-sm', 'text-gray-900');
        tabPhone.classList.remove('text-gray-500');
        tabLogin.classList.remove('bg-white', 'shadow-sm', 'text-gray-900');
        tabLogin.classList.add('text-gray-500');
        loginForm.querySelectorAll('[required]').forEach(function(el) { el.removeAttribute('required'); });
        phoneForm.querySelector('[name="phone"]').setAttribute('required', '');
        phoneForm.querySelector('[name="password"]').setAttribute('required', '');
    } else {
        phoneForm.classList.add('hidden');
        loginForm.classList.remove('hidden');
        tabLogin.classList.add('bg-white', 'shadow-sm', 'text-gray-900');
        tabLogin.classList.remove('text-gray-500');
        tabPhone.classList.remove('bg-white', 'shadow-sm', 'text-gray-900');
        tabPhone.classList.add('text-gray-500');
        phoneForm.querySelectorAll('[required]').forEach(function(el) { el.removeAttribute('required'); });
        loginForm.querySelector('[name="login"]').setAttribute('required', '');
        loginForm.querySelector('[name="password"]').setAttribute('required', '');
    }
}

document.addEventListener('DOMContentLoaded', function() {
    switchIndexLoginMethod('login');
});
