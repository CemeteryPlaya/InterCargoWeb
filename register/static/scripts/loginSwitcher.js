(function () {
    var SWITCH_DURATION = 180; // ms — fade-out before swap
    var HEIGHT_DURATION = 300; // ms — wrapper height transition

    function getForms() {
        return {
            login: document.getElementById('login-by-login'),
            phone: document.getElementById('login-by-phone'),
            email: document.getElementById('login-by-email')
        };
    }

    function getTabs() {
        return {
            login: document.getElementById('tab-login-method'),
            phone: document.getElementById('tab-phone-method'),
            email: document.getElementById('tab-email-method')
        };
    }

    function applyRequired(method, forms) {
        Object.keys(forms).forEach(function (key) {
            forms[key].querySelectorAll('[data-required], [required]').forEach(function (el) {
                el.removeAttribute('required');
            });
        });
        var requiredFields = {
            login: ['login', 'password'],
            phone: ['phone', 'password'],
            email: ['email', 'password']
        }[method] || [];
        requiredFields.forEach(function (name) {
            var el = forms[method].querySelector('[name="' + name + '"]');
            if (el) el.setAttribute('required', '');
        });
    }

    function updateTabsStyles(method, tabs) {
        Object.keys(tabs).forEach(function (key) {
            tabs[key].classList.remove('text-gray-900', 'font-semibold');
            tabs[key].classList.add('text-gray-500');
        });
        tabs[method].classList.remove('text-gray-500');
        tabs[method].classList.add('text-gray-900', 'font-semibold');
    }

    function moveIndicator(method, tabs) {
        var indicator = document.getElementById('login-tab-indicator');
        var active = tabs[method];
        if (!indicator || !active) return;
        indicator.style.width = active.offsetWidth + 'px';
        indicator.style.transform = 'translateX(' + active.offsetLeft + 'px)';
    }

    function findCurrentForm(forms) {
        var current = null;
        Object.keys(forms).forEach(function (key) {
            if (!forms[key].classList.contains('hidden')) current = forms[key];
        });
        return current;
    }

    window.switchLoginMethod = function (method) {
        var forms = getForms();
        var tabs = getTabs();
        var wrapper = document.getElementById('login-forms-wrap');
        var newForm = forms[method];
        if (!newForm) return;

        updateTabsStyles(method, tabs);
        moveIndicator(method, tabs);
        applyRequired(method, forms);

        var currentForm = findCurrentForm(forms);

        // Initial call or same form — just show without animation
        if (!currentForm || currentForm === newForm) {
            Object.keys(forms).forEach(function (key) {
                if (forms[key] !== newForm) forms[key].classList.add('hidden');
            });
            newForm.classList.remove('hidden');
            return;
        }

        // Lock wrapper height to current for smooth transition
        var currentHeight = wrapper.offsetHeight;
        wrapper.style.height = currentHeight + 'px';

        // Fade out current form
        currentForm.classList.add('login-form-leaving');

        setTimeout(function () {
            currentForm.classList.add('hidden');
            currentForm.classList.remove('login-form-leaving');

            // Reveal new form with "entering" state (opacity 0, translateY 8px)
            newForm.classList.add('login-form-entering');
            newForm.classList.remove('hidden');

            // Measure target height and animate wrapper to it
            var newHeight = newForm.offsetHeight;
            wrapper.style.height = newHeight + 'px';

            // Trigger transition to normal state on next frame
            requestAnimationFrame(function () {
                requestAnimationFrame(function () {
                    newForm.classList.remove('login-form-entering');
                });
            });

            // Release wrapper height after animation
            setTimeout(function () {
                wrapper.style.height = '';
            }, HEIGHT_DURATION);
        }, SWITCH_DURATION);
    };

    document.addEventListener('DOMContentLoaded', function () {
        var method = document.body.dataset.loginMethod || 'login';
        window.switchLoginMethod(method);
    });

    // Reposition indicator on resize (tab widths may change)
    window.addEventListener('resize', function () {
        var body = document.body;
        var method = body.dataset.currentLoginMethod;
        var tabs = getTabs();
        // Determine active tab from styles
        var active = Object.keys(tabs).find(function (k) {
            return tabs[k].classList.contains('text-gray-900');
        });
        if (active) moveIndicator(active, tabs);
    });
})();
