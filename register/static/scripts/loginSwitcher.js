function switchLoginMethod(method) {
    var forms = {
        login: document.getElementById('login-by-login'),
        phone: document.getElementById('login-by-phone'),
        email: document.getElementById('login-by-email')
    };
    var tabs = {
        login: document.getElementById('tab-login-method'),
        phone: document.getElementById('tab-phone-method'),
        email: document.getElementById('tab-email-method')
    };

    Object.keys(forms).forEach(function(key) {
        forms[key].classList.add('hidden');
        forms[key].querySelectorAll('[required]').forEach(function(el) { el.removeAttribute('required'); });
        tabs[key].classList.remove('bg-white', 'shadow-sm', 'text-gray-900');
        tabs[key].classList.add('text-gray-500');
    });

    forms[method].classList.remove('hidden');
    tabs[method].classList.add('bg-white', 'shadow-sm', 'text-gray-900');
    tabs[method].classList.remove('text-gray-500');

    if (method === 'login') {
        forms.login.querySelector('[name="login"]').setAttribute('required', '');
        forms.login.querySelector('[name="password"]').setAttribute('required', '');
    } else if (method === 'phone') {
        forms.phone.querySelector('[name="phone"]').setAttribute('required', '');
        forms.phone.querySelector('[name="password"]').setAttribute('required', '');
    } else if (method === 'email') {
        forms.email.querySelector('[name="email"]').setAttribute('required', '');
        forms.email.querySelector('[name="password"]').setAttribute('required', '');
    }
}

document.addEventListener('DOMContentLoaded', function() {
    var body = document.body;
    var method = body.dataset.loginMethod || 'login';
    switchLoginMethod(method);
});
