/**
 * Interactive Tutorial System
 * Provides step-by-step guided tours with overlay and element highlighting.
 * Tutorials persist across page navigations via localStorage.
 */
(function () {
    'use strict';

    var STORAGE_KEY = 'ic_tutorial';
    var overlay, tooltip, activeEl, activeElOrigStyles;

    /* ─── Helpers ───────────────────────────────────────────────────────── */

    function isMobile() {
        return window.innerWidth < 768;
    }

    /* ─── Tutorial Definitions ──────────────────────────────────────────── */

    var TUTORIALS = {
        add_track: {
            name: 'Как добавить трек-коды',
            steps: [
                {
                    page: '/profile/track-codes/',
                    mobile: true,
                    selector: '#mobile-menu-toggle',
                    text: 'Нажмите на иконку меню, чтобы открыть боковую панель навигации.',
                    position: 'bottom',
                },
                {
                    page: '/profile/track-codes/',
                    selector: 'a[href*="track-codes"]',
                    selectorScope: 'sidebar',
                    text: 'Перейдите в раздел "Трек-коды" в боковом меню для управления вашими трек-кодами.',
                    position: 'right',
                    mobilePosition: 'bottom',
                    navigateTo: '/profile/track-codes/',
                    beforeShow: function () { openMobileSidebar(); },
                },
                {
                    page: '/profile/track-codes/',
                    selector: 'button.bg-green-500',
                    text: 'Нажмите кнопку "Добавить" чтобы открыть форму добавления нового трек-кода.',
                    position: 'bottom',
                    beforeShow: function () { closeMobileSidebar(); },
                },
                {
                    page: '/profile/track-codes/',
                    selector: '#track-code-input',
                    text: 'Введите ваш трек-код в это поле. Трек-код вы получаете от продавца после оплаты товара.',
                    position: 'bottom',
                    beforeShow: function () {
                        openAlpineModal('addModal');
                    },
                },
                {
                    page: '/profile/track-codes/',
                    selector: 'input[name="description"]',
                    text: 'Добавьте описание посылки (необязательно). Например: "Куртка зимняя" — это поможет вам не путать посылки.',
                    position: 'bottom',
                },
                {
                    page: '/profile/track-codes/',
                    selector: 'button[type="submit"].bg-green-500',
                    selectorScope: 'modal',
                    text: 'Нажмите "Сохранить" для добавления трек-кода. После этого вы сможете отслеживать статус вашей посылки.',
                    position: 'top',
                },
            ],
        },

        view_receipts: {
            name: 'Как посмотреть чеки',
            steps: [
                {
                    page: '/profile/delivered-posts/',
                    mobile: true,
                    selector: '#mobile-menu-toggle',
                    text: 'Нажмите на иконку меню, чтобы открыть боковую панель навигации.',
                    position: 'bottom',
                },
                {
                    page: '/profile/delivered-posts/',
                    selector: 'a[href*="delivered-posts"]',
                    selectorScope: 'sidebar',
                    text: 'Перейдите в раздел "Чеки" в боковом меню для просмотра ваших чеков.',
                    position: 'right',
                    mobilePosition: 'bottom',
                    navigateTo: '/profile/delivered-posts/',
                    beforeShow: function () { openMobileSidebar(); },
                },
                {
                    page: '/profile/delivered-posts/',
                    selector: '.bg-white.border-2.border-gray-300',
                    fallbackSelector: 'h1',
                    text: 'Здесь отображаются ваши чеки. Каждый чек содержит информацию о дате, весе и стоимости посылок.',
                    position: 'bottom',
                    beforeShow: function () { closeMobileSidebar(); },
                },
                {
                    page: '/profile/delivered-posts/',
                    selector: '.cursor-pointer.bg-gray-100',
                    fallbackSelector: '.bg-white.border-2.border-gray-300',
                    text: 'Нажмите на заголовок чека, чтобы развернуть подробности — список трек-кодов, вес и стоимость каждой посылки.',
                    position: 'bottom',
                },
                {
                    page: '/profile/delivered-posts/',
                    selector: null,
                    text: 'В развёрнутом чеке вы увидите таблицу с трек-кодами, весом и ценой каждой посылки, а также итоговую сумму и пункт выдачи.',
                    position: 'center',
                },
            ],
        },

        receive_parcels: {
            name: 'Как получить и оплатить посылки',
            steps: [
                {
                    page: '/profile/',
                    mobile: true,
                    selector: '#mobile-menu-toggle',
                    text: 'Нажмите на иконку меню, чтобы открыть боковую панель навигации.',
                    position: 'bottom',
                },
                {
                    page: '/profile/',
                    selector: '#user-info',
                    selectorScope: 'sidebar',
                    selectorOverride: 'a[href*="/profile/"]',
                    text: 'Перейдите на главную страницу профиля для получения посылок.',
                    position: 'right',
                    mobilePosition: 'bottom',
                    navigateTo: '/profile/',
                    beforeShow: function () { openMobileSidebar(); },
                },
                {
                    page: '/profile/',
                    selector: '#trackcodes',
                    text: 'Здесь отображается статистика ваших трек-кодов по статусам. Когда посылки прибудут на ПВЗ, статус изменится на "Прибыло (ПВЗ)".',
                    position: 'bottom',
                    beforeShow: function () { closeMobileSidebar(); },
                },
                {
                    page: '/profile/',
                    selector: '.quickIssueBtn',
                    fallbackSelector: '#trackcodes',
                    text: 'Когда посылки доставлены на ПВЗ, появится зелёная кнопка "Получить посылки". Нажмите её, чтобы начать процесс получения.',
                    position: 'bottom',
                },
                {
                    page: '/profile/',
                    selector: null,
                    text: 'После нажатия вам будет показано количество посылок для подтверждения. Проверьте и нажмите "Окей".',
                    position: 'center',
                    icon: 'ri-checkbox-circle-line',
                },
                {
                    page: '/profile/',
                    selector: null,
                    text: 'Далее на экране появится QR-код. Покажите его сотруднику пункта выдачи — он отсканирует код и выдаст ваши посылки.',
                    position: 'center',
                    icon: 'ri-qr-code-line',
                },
                {
                    page: '/profile/',
                    selector: null,
                    text: 'Оплату вы можете произвести на месте в пункте выдачи. Готово — ваши посылки получены!',
                    position: 'center',
                    icon: 'ri-bank-card-line',
                },
            ],
        },

        /* ─── Tutorials for unauthenticated users ────────────────────────── */

        guest_register: {
            name: 'Как зарегистрироваться',
            guest: true,
            steps: [
                {
                    page: '/register/registration',
                    selector: null,
                    text: 'Добро пожаловать! Сейчас мы покажем, как зарегистрироваться на сайте Inter Cargo. Нажмите "Далее" чтобы начать.',
                    position: 'center',
                    icon: 'ri-user-add-line',
                    navigateTo: '/register/registration',
                },
                {
                    page: '/register/registration',
                    selector: 'input[name="login"]',
                    text: 'Введите логин латинскими буквами. Этот логин будет использоваться для входа на сайт и для идентификации ваших посылок.',
                    position: 'bottom',
                },
                {
                    page: '/register/registration',
                    selector: 'input[name="phone"]',
                    text: 'Укажите ваш номер телефона. По нему вы также сможете входить на сайт.',
                    position: 'bottom',
                },
                {
                    page: '/register/registration',
                    selector: 'input[name="email"]',
                    text: 'Укажите ваш email. На него будут приходить уведомления о статусе посылок.',
                    position: 'bottom',
                },
                {
                    page: '/register/registration',
                    selector: 'select[name="pickup"]',
                    text: 'Выберите удобный для вас пункт выдачи (ПВЗ), где вы будете получать свои посылки.',
                    position: 'bottom',
                },
                {
                    page: '/register/registration',
                    selector: '#password',
                    text: 'Придумайте надёжный пароль. Минимум 8 символов, используйте буквы и цифры.',
                    position: 'bottom',
                },
                {
                    page: '/register/registration',
                    selector: '#registerBtn',
                    text: 'После заполнения всех полей нажмите кнопку "Зарегистрироваться". Готово!',
                    position: 'top',
                },
            ],
        },

        guest_login: {
            name: 'Как войти на сайт',
            guest: true,
            steps: [
                {
                    page: '/register/login/',
                    selector: null,
                    text: 'Сейчас мы покажем, как войти в свой аккаунт. Вы можете войти по логину, телефону или email.',
                    position: 'center',
                    icon: 'ri-login-box-line',
                    navigateTo: '/register/login/',
                },
                {
                    page: '/register/login/',
                    selector: '.flex.bg-gray-100.rounded-lg',
                    fallbackSelector: 'h2',
                    text: 'Выберите способ входа: по логину, по номеру телефона или по email. Нажмите на нужную вкладку.',
                    position: 'bottom',
                },
                {
                    page: '/register/login/',
                    selector: '#password-login',
                    text: 'Введите пароль, который вы указали при регистрации, и нажмите "Войти".',
                    position: 'bottom',
                },
            ],
        },

        guest_how_to_order: {
            name: 'Как начать заказывать',
            guest: true,
            steps: [
                {
                    page: null,
                    selector: null,
                    text: 'Хотите начать заказывать товары из Китая? Вот порядок действий. Нажмите "Далее".',
                    position: 'center',
                    icon: 'ri-shopping-bag-line',
                },
                {
                    page: null,
                    selector: null,
                    text: '1. Напишите менеджеру Inter Cargo в WhatsApp. Он расскажет о тарифах, условиях доставки и ответит на ваши вопросы.',
                    position: 'center',
                    icon: 'ri-whatsapp-line',
                },
                {
                    page: null,
                    selector: null,
                    text: '2. Получите от менеджера инструкции: адрес склада в Китае и правила оформления заказа.',
                    position: 'center',
                    icon: 'ri-file-text-line',
                },
                {
                    page: null,
                    selector: null,
                    text: '3. Зарегистрируйтесь на нашем сайте — это необходимо для отслеживания посылок и получения чеков.',
                    position: 'center',
                    icon: 'ri-user-add-line',
                },
                {
                    page: null,
                    selector: null,
                    text: '4. Оформите заказ на китайской торговой площадке (Taobao, Pinduoduo, 1688 и др.).',
                    position: 'center',
                    icon: 'ri-global-line',
                },
                {
                    page: null,
                    selector: null,
                    text: '5. При оформлении укажите адрес нашего склада в Китае и ваш логин с сайта — так мы определим, чья это посылка.',
                    position: 'center',
                    icon: 'ri-map-pin-line',
                },
                {
                    page: null,
                    selector: null,
                    text: '6. Добавьте трек-код посылки в личном кабинете. Отслеживайте статус доставки — от Китая до вашего ПВЗ.',
                    position: 'center',
                    icon: 'ri-barcode-line',
                },
                {
                    page: null,
                    selector: null,
                    text: 'Готово! Когда посылка прибудет на ПВЗ, вы получите уведомление. Приходите, оплатите и заберите.',
                    position: 'center',
                    icon: 'ri-checkbox-circle-line',
                },
            ],
        },

        /* ─── Tutorials for ПВЗ employees ────────────────────────────────── */

        pp_acceptance_tutorial: {
            name: 'Приёмка товара',
            ppWorker: true,
            steps: [
                {
                    page: '/profile/pp-acceptance/',
                    mobile: true,
                    selector: '#mobile-menu-toggle',
                    text: 'Нажмите на иконку меню, чтобы открыть боковую панель.',
                    position: 'bottom',
                },
                {
                    page: '/profile/pp-acceptance/',
                    selector: 'a[href*="pp-acceptance"]',
                    selectorScope: 'sidebar',
                    text: 'Перейдите в раздел "Приёмка товара" в боковом меню.',
                    position: 'right',
                    mobilePosition: 'bottom',
                    navigateTo: '/profile/pp-acceptance/',
                    beforeShow: function () { openMobileSidebar(); },
                },
                {
                    page: '/profile/pp-acceptance/',
                    selector: '.border-yellow-400',
                    fallbackSelector: 'h2',
                    text: 'Здесь отображаются ожидающие приёмки доставки. Каждая карточка — одна доставка от водителя с количеством чеков.',
                    position: 'bottom',
                    beforeShow: function () { closeMobileSidebar(); },
                },
                {
                    page: '/profile/pp-acceptance/',
                    selector: null,
                    text: 'Когда водитель нажимает "Начать выдачу" — на карточке появляется кнопка "Приёмка". Нажмите её, чтобы начать принимать посылки.',
                    position: 'center',
                    icon: 'ri-inbox-archive-line',
                },
                {
                    page: '/profile/pp-acceptance/',
                    selector: null,
                    text: 'Отсканируйте QR-код каждого чека сканером или камерой. Система автоматически проверит чек и отметит его как принятый.',
                    position: 'center',
                    icon: 'ri-qr-code-line',
                },
                {
                    page: '/profile/pp-acceptance/',
                    selector: null,
                    text: 'После приёмки всех чеков нажмите "Завершить сессию". Посылки переместятся на склад вашего ПВЗ.',
                    position: 'center',
                    icon: 'ri-checkbox-circle-line',
                },
            ],
        },

        pp_extradition_tutorial: {
            name: 'Выдача посылок',
            ppWorker: true,
            steps: [
                {
                    page: '/profile/extradition/',
                    mobile: true,
                    selector: '#mobile-menu-toggle',
                    text: 'Нажмите на иконку меню для навигации.',
                    position: 'bottom',
                },
                {
                    page: '/profile/extradition/',
                    selector: 'a[href*="extradition"]',
                    selectorScope: 'sidebar',
                    text: 'Перейдите в раздел "Выдача посылок" — здесь оформляется выдача посылок клиентам.',
                    position: 'right',
                    mobilePosition: 'bottom',
                    navigateTo: '/profile/extradition/',
                    beforeShow: function () { openMobileSidebar(); },
                },
                {
                    page: '/profile/extradition/',
                    selector: '#barcode',
                    fallbackSelector: 'h1',
                    text: 'Когда клиент приходит за посылками, отсканируйте его QR-код выдачи в это поле. Также можно ввести код вручную.',
                    position: 'bottom',
                    beforeShow: function () { closeMobileSidebar(); },
                },
                {
                    page: '/profile/extradition/',
                    selector: '#scanBarcodeBtn',
                    fallbackSelector: '#searchBtn',
                    text: 'Или нажмите эту кнопку, чтобы открыть камеру и отсканировать QR-код клиента.',
                    position: 'bottom',
                },
                {
                    page: '/profile/extradition/',
                    selector: null,
                    text: 'После сканирования QR-кода клиента система найдёт его пакет и покажет информацию: имя клиента, ПВЗ, ячейку хранения и список чеков с посылками.',
                    position: 'center',
                    icon: 'ri-search-line',
                },
                {
                    page: '/profile/extradition/',
                    selector: null,
                    text: 'Для быстрой выдачи нажмите "Оформить выдачу". Для проверки — нажмите "Проверить и выдать", чтобы отсканировать QR-коды на каждом чеке.',
                    position: 'center',
                    icon: 'ri-qr-scan-2-line',
                },
                {
                    page: '/profile/extradition/',
                    selector: null,
                    text: 'В режиме проверки отсканируйте QR-код каждого чека. Прогресс-бар покажет сколько чеков проверено. После проверки всех чеков нажмите "Подтвердить выдачу".',
                    position: 'center',
                    icon: 'ri-checkbox-circle-line',
                },
                {
                    page: '/profile/extradition/',
                    selector: null,
                    text: 'После оформления выдачи: посылки будут отмечены как выданные, ячейка хранения освободится, а клиент получит уведомление.',
                    position: 'center',
                    icon: 'ri-hand-coin-line',
                },
            ],
        },

        pp_warehouse_tutorial: {
            name: 'Склад ПВЗ',
            ppWorker: true,
            steps: [
                {
                    page: '/profile/warehouse/',
                    selector: 'h1',
                    text: 'Это страница "Склад ПВЗ". Здесь отображаются все ячейки с посылками, ожидающими выдачи клиентам.',
                    position: 'bottom',
                    navigateTo: '/profile/warehouse/',
                },
                {
                    page: '/profile/warehouse/',
                    selector: '.w-14.h-14',
                    fallbackSelector: 'h1',
                    text: 'Номер ячейки отображается в квадрате. Нажмите на него, чтобы изменить номер ячейки. "Пол" означает ячейку 0.',
                    position: 'bottom',
                },
                {
                    page: '/profile/warehouse/',
                    selector: null,
                    text: 'Каждая ячейка разделена на подячейки по чекам. Это позволяет легко найти конкретные посылки клиента.',
                    position: 'center',
                    icon: 'ri-layout-grid-line',
                },
                {
                    page: '/profile/warehouse/',
                    selector: 'a[href*="inventory"]',
                    fallbackSelector: 'h1',
                    text: 'Кнопка "Инвентаризация" создаёт печатный документ со списком всех клиентов, ячеек и посылок на складе.',
                    position: 'bottom',
                },
                {
                    page: '/profile/warehouse/',
                    selector: null,
                    text: 'Используйте инвентаризацию для сверки реального содержимого склада с данными в системе.',
                    position: 'center',
                    icon: 'ri-file-list-3-line',
                },
            ],
        },

        pp_restructure_tutorial: {
            name: 'Реструктуризация склада',
            ppWorker: true,
            steps: [
                {
                    page: '/profile/warehouse/',
                    selector: 'h1',
                    text: 'Реструктуризация позволяет переназначить все ячейки на складе. Используйте её, когда нужно переорганизовать склад.',
                    position: 'bottom',
                    navigateTo: '/profile/warehouse/',
                },
                {
                    page: '/profile/warehouse/',
                    selector: 'button[type="submit"]',
                    fallbackSelector: '.animate-pulse',
                    text: 'Нажмите "Реструктуризация склада". Все номера ячеек будут удалены, а посылки останутся в системе.',
                    position: 'bottom',
                },
                {
                    page: '/profile/warehouse/',
                    selector: null,
                    text: 'После нажатия откроется страница назначения ячеек. Здесь 3 способа назначить ячейки: вручную, сканером или камерой.',
                    position: 'center',
                    icon: 'ri-refresh-line',
                },
                {
                    page: '/profile/warehouse/',
                    selector: null,
                    text: 'Сканер: отсканируйте QR-код чека — система найдёт клиента и назначит ячейку автоматически.',
                    position: 'center',
                    icon: 'ri-barcode-line',
                },
                {
                    page: '/profile/warehouse/',
                    selector: null,
                    text: 'Камера: если нет аппаратного сканера, откройте камеру телефона и наведите на QR-код чека.',
                    position: 'center',
                    icon: 'ri-camera-line',
                },
                {
                    page: '/profile/warehouse/',
                    selector: null,
                    text: 'Вручную: выберите клиента из списка и укажите номер ячейки (или оставьте пустым для автоназначения).',
                    position: 'center',
                    icon: 'ri-edit-line',
                },
                {
                    page: '/profile/warehouse/',
                    selector: null,
                    text: 'Когда все ячейки назначены, нажмите "Завершить реструктуризацию". До завершения на складе будет мигать кнопка "Продолжить реструктуризацию".',
                    position: 'center',
                    icon: 'ri-checkbox-circle-line',
                },
            ],
        },
    };

    /* ─── Mobile sidebar helpers ────────────────────────────────────────── */

    function openMobileSidebar() {
        if (!isMobile()) return;
        var sidebar = document.getElementById('mobile-sidebar');
        var sidebarOverlay = document.getElementById('mobile-sidebar-overlay');
        if (sidebar) {
            sidebar.classList.remove('hidden');
            sidebar.style.zIndex = '9997';
        }
        if (sidebarOverlay) {
            sidebarOverlay.classList.remove('hidden');
            sidebarOverlay.style.zIndex = '9996';
        }
    }

    function closeMobileSidebar() {
        if (!isMobile()) return;
        var sidebar = document.getElementById('mobile-sidebar');
        var sidebarOverlay = document.getElementById('mobile-sidebar-overlay');
        if (sidebar) {
            sidebar.classList.add('hidden');
            sidebar.style.zIndex = '';
        }
        if (sidebarOverlay) {
            sidebarOverlay.classList.add('hidden');
            sidebarOverlay.style.zIndex = '';
        }
    }

    function openAlpineModal(name) {
        var el = document.querySelector('[x-data*="' + name + '"]');
        if (!el) return;
        if (el._x_dataStack) {
            el._x_dataStack[0][name] = true;
        } else if (el.__x) {
            el.__x.$data[name] = true;
        } else if (window.Alpine) {
            try { Alpine.evaluate(el, name + ' = true'); } catch (e) { /* ignore */ }
        }
    }

    /* ─── State Management ──────────────────────────────────────────────── */

    function getState() {
        try {
            return JSON.parse(localStorage.getItem(STORAGE_KEY)) || null;
        } catch (e) {
            return null;
        }
    }

    function setState(tutorialId, stepIndex) {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ id: tutorialId, step: stepIndex }));
    }

    function clearState() {
        localStorage.removeItem(STORAGE_KEY);
    }

    /* ─── DOM Helpers ───────────────────────────────────────────────────── */

    function findElement(step) {
        // Mobile-only steps: skip on desktop
        if (step.mobile && !isMobile()) return null;

        var el = null;
        var sel = step.selector;

        // On mobile sidebar steps, use selectorOverride if available
        if (step.selectorScope === 'sidebar' && step.selectorOverride && isMobile()) {
            sel = step.selectorOverride;
        }

        if (sel) {
            if (step.selectorScope === 'sidebar') {
                var sidebar = isMobile()
                    ? document.getElementById('mobile-sidebar')
                    : document.querySelector('aside.w-64');
                if (sidebar) el = sidebar.querySelector(sel);
            } else if (step.selectorScope === 'modal') {
                var modals = document.querySelectorAll('[x-show]');
                for (var i = 0; i < modals.length; i++) {
                    var found = modals[i].querySelector(sel);
                    if (found) { el = found; break; }
                }
                if (!el) el = document.querySelector(sel);
            } else {
                el = document.querySelector(sel);
            }
        }

        if (!el && step.fallbackSelector) {
            el = document.querySelector(step.fallbackSelector);
        }

        return el;
    }

    /* ─── UI Creation ───────────────────────────────────────────────────── */

    function createOverlay() {
        if (overlay) return;

        overlay = document.createElement('div');
        overlay.id = 'tutorial-overlay';
        overlay.style.cssText =
            'position:fixed;inset:0;z-index:9998;' +
            'background:rgba(0,0,0,0.6);' +
            'transition:opacity 0.3s ease;';
        document.body.appendChild(overlay);

        tooltip = document.createElement('div');
        tooltip.id = 'tutorial-tooltip';
        tooltip.style.cssText =
            'position:fixed;z-index:10001;max-width:380px;width:calc(100vw - 16px);' +
            'box-sizing:border-box;' +
            'background:white;border-radius:12px;padding:20px;' +
            'box-shadow:0 10px 40px rgba(0,0,0,0.3);' +
            'font-size:14px;line-height:1.6;color:#1f2937;' +
            'transition:opacity 0.3s ease;';
        document.body.appendChild(tooltip);

        overlay.addEventListener('click', function (e) {
            if (e.target === overlay) {
                e.stopPropagation();
                e.preventDefault();
            }
        });
    }

    function destroyOverlay() {
        restoreElement();
        if (overlay) { overlay.remove(); overlay = null; }
        if (tooltip) { tooltip.remove(); tooltip = null; }
        closeMobileSidebar();
    }

    function highlightElement(el) {
        restoreElement();
        if (!el) return;

        activeEl = el;
        activeElOrigStyles = {
            position: el.style.position,
            zIndex: el.style.zIndex,
            boxShadow: el.style.boxShadow,
            borderRadius: el.style.borderRadius,
            outline: el.style.outline,
            outlineOffset: el.style.outlineOffset,
        };

        // Raise element above overlay
        var computed = window.getComputedStyle(el);
        if (computed.position === 'static') {
            el.style.position = 'relative';
        }
        el.style.zIndex = '10000';
        el.style.boxShadow = '0 0 0 4px #ef4444, 0 0 0 5000px rgba(0,0,0,0.01)';
        el.style.borderRadius = el.style.borderRadius || '8px';
        el.style.outline = '3px solid rgba(239, 68, 68, 0.5)';
        el.style.outlineOffset = '4px';
    }

    function restoreElement() {
        if (activeEl && activeElOrigStyles) {
            activeEl.style.position = activeElOrigStyles.position;
            activeEl.style.zIndex = activeElOrigStyles.zIndex;
            activeEl.style.boxShadow = activeElOrigStyles.boxShadow;
            activeEl.style.borderRadius = activeElOrigStyles.borderRadius;
            activeEl.style.outline = activeElOrigStyles.outline;
            activeEl.style.outlineOffset = activeElOrigStyles.outlineOffset;
        }
        activeEl = null;
        activeElOrigStyles = null;
    }

    /** Viewport dimensions safe for iOS Safari / Telegram WebView */
    function vw() { return document.documentElement.clientWidth  || window.innerWidth; }
    function vh() { return document.documentElement.clientHeight || window.innerHeight; }

    function positionTooltip(el, step, stepIndex, totalSteps) {
        var pos = step.position || 'bottom';
        if (isMobile() && step.mobilePosition) pos = step.mobilePosition;
        var icon = step.icon || 'ri-lightbulb-line';

        // Build tooltip HTML
        var html =
            '<div style="display:flex;align-items:flex-start;gap:12px;">' +
            '<i class="' + icon + '" style="font-size:24px;color:#ef4444;flex-shrink:0;margin-top:2px;"></i>' +
            '<div style="flex:1;">' +
            '<p style="margin:0 0 16px 0;">' + step.text + '</p>' +
            '<div style="display:flex;align-items:center;justify-content:space-between;">' +
            '<span style="font-size:12px;color:#9ca3af;">' + (stepIndex + 1) + ' / ' + totalSteps + '</span>' +
            '<div style="display:flex;gap:8px;">';

        if (stepIndex > 0) {
            html += '<button id="tutorial-prev" style="padding:6px 16px;border-radius:6px;' +
                'border:1px solid #d1d5db;background:white;color:#374151;font-size:13px;' +
                'cursor:pointer;font-weight:500;">Назад</button>';
        }

        if (stepIndex < totalSteps - 1) {
            var nextLabel = step.navigateTo ? 'Перейти' : 'Далее';
            html += '<button id="tutorial-next" style="padding:6px 16px;border-radius:6px;' +
                'border:none;background:#ef4444;color:white;font-size:13px;' +
                'cursor:pointer;font-weight:500;">' + nextLabel + '</button>';
        } else {
            html += '<button id="tutorial-finish" style="padding:6px 16px;border-radius:6px;' +
                'border:none;background:#16a34a;color:white;font-size:13px;' +
                'cursor:pointer;font-weight:500;">Готово</button>';
        }

        html += '</div></div></div></div>';
        html += '<button id="tutorial-close" style="position:absolute;top:8px;right:12px;' +
            'background:none;border:none;font-size:20px;color:#9ca3af;cursor:pointer;' +
            'line-height:1;" title="Закрыть">&times;</button>';

        tooltip.innerHTML = html;

        // Reset all positioning before measuring
        tooltip.style.top = '';
        tooltip.style.left = '';
        tooltip.style.right = '';
        tooltip.style.bottom = '';
        tooltip.style.transform = '';

        // Center mode (no target element)
        if (!el || pos === 'center') {
            tooltip.style.top = '50%';
            tooltip.style.left = '50%';
            tooltip.style.transform = 'translate(-50%, -50%)';
            clampTooltip();
            return;
        }

        var rect = el.getBoundingClientRect();
        var pad = 12;
        var W = vw();
        var H = vh();
        var margin = 8; // minimum distance from any viewport edge

        // Measure tooltip size (needs to be in DOM first — it already is)
        var tw = tooltip.offsetWidth;
        var th = tooltip.offsetHeight;

        var top, left;

        if (pos === 'bottom') {
            top = rect.bottom + pad;
            left = rect.left;
        } else if (pos === 'top') {
            top = rect.top - pad - th;
            left = rect.left;
        } else if (pos === 'right') {
            top = rect.top;
            left = rect.right + pad;
            // Fallback to bottom if no room on right
            if (left + tw > W - margin) {
                top = rect.bottom + pad;
                left = rect.left;
                pos = 'bottom'; // for overflow checks below
            }
        } else if (pos === 'left') {
            top = rect.top;
            left = rect.left - pad - tw;
            // Fallback to bottom if no room on left
            if (left < margin) {
                top = rect.bottom + pad;
                left = rect.left;
                pos = 'bottom';
            }
        }

        // If goes below viewport, try placing above the element
        if (top + th > H - margin) {
            var aboveTop = rect.top - pad - th;
            if (aboveTop >= margin) {
                top = aboveTop;
            } else {
                // Neither above nor below fits — pin to bottom of viewport
                top = H - th - margin;
            }
        }
        // If goes above viewport
        if (top < margin) {
            top = margin;
        }

        // Clamp horizontal: keep fully within viewport
        if (left + tw > W - margin) {
            left = W - tw - margin;
        }
        if (left < margin) {
            left = margin;
        }

        tooltip.style.top = top + 'px';
        tooltip.style.left = left + 'px';

        // Extra safety: after paint, re-clamp in case fonts/images shifted layout
        clampTooltip();
    }

    /** Final clamp — ensures tooltip never overflows viewport on any browser */
    function clampTooltip() {
        requestAnimationFrame(function () {
            if (!tooltip) return;
            var W = vw();
            var H = vh();
            var margin = 8;
            var tr = tooltip.getBoundingClientRect();
            var needsFix = (tr.left < margin || tr.right > W - margin ||
                            tr.top < margin || tr.bottom > H - margin);

            if (!needsFix) return;

            // Drop any transform (e.g. center mode translate) and switch to pixel coords
            if (tooltip.style.transform) {
                // Compute current visual position before removing transform
                var curLeft = tr.left;
                var curTop = tr.top;
                tooltip.style.transform = 'none';
                tooltip.style.left = curLeft + 'px';
                tooltip.style.top = curTop + 'px';
                tooltip.style.right = '';
                tooltip.style.bottom = '';
                // Re-measure after transform removal
                tr = tooltip.getBoundingClientRect();
            }

            // Clamp horizontal
            if (tr.right > W - margin) {
                tooltip.style.left = Math.max(margin, W - tr.width - margin) + 'px';
            }
            if (tr.left < margin) {
                tooltip.style.left = margin + 'px';
            }

            // Clamp vertical
            tr = tooltip.getBoundingClientRect();
            if (tr.bottom > H - margin) {
                tooltip.style.top = Math.max(margin, H - tr.height - margin) + 'px';
            }
            if (tr.top < margin) {
                tooltip.style.top = margin + 'px';
            }
        });
    }

    /* ─── Tutorial Engine ───────────────────────────────────────────────── */

    function getEffectiveSteps(tutorial) {
        // Filter out mobile-only steps when on desktop
        var mobile = isMobile();
        var effective = [];
        for (var i = 0; i < tutorial.steps.length; i++) {
            var step = tutorial.steps[i];
            if (step.mobile && !mobile) continue;
            effective.push(step);
        }
        return effective;
    }

    function showStep(tutorialId, stepIndex) {
        var tutorial = TUTORIALS[tutorialId];
        if (!tutorial) return;

        var steps = getEffectiveSteps(tutorial);
        if (stepIndex < 0 || stepIndex >= steps.length) {
            endTutorial();
            return;
        }

        var step = steps[stepIndex];
        var currentPath = window.location.pathname;

        // If step requires a different page, navigate there
        if (step.page && !currentPath.startsWith(step.page)) {
            if (step.navigateTo) {
                setState(tutorialId, stepIndex + 1);
                window.location.href = step.navigateTo;
                return;
            }
            // Skip steps not on this page
            for (var i = stepIndex + 1; i < steps.length; i++) {
                if (!steps[i].page || currentPath.startsWith(steps[i].page)) {
                    setState(tutorialId, i);
                    showStep(tutorialId, i);
                    return;
                }
            }
            endTutorial();
            return;
        }

        setState(tutorialId, stepIndex);
        createOverlay();

        if (step.beforeShow) {
            step.beforeShow();
            setTimeout(function () { renderStep(tutorialId, stepIndex, steps); }, 300);
        } else {
            renderStep(tutorialId, stepIndex, steps);
        }
    }

    function renderStep(tutorialId, stepIndex, steps) {
        var step = steps[stepIndex];
        var el = findElement(step);

        // Scroll element into view first
        if (el) {
            var viewRect = el.getBoundingClientRect();
            if (viewRect.top < 80 || viewRect.bottom > window.innerHeight - 80) {
                el.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
            setTimeout(function () {
                highlightElement(el);
                positionTooltip(el, step, stepIndex, steps.length);
                bindTooltipButtons(tutorialId, stepIndex, steps);
            }, 350);
        } else {
            restoreElement();
            positionTooltip(null, step, stepIndex, steps.length);
            bindTooltipButtons(tutorialId, stepIndex, steps);
        }
    }

    function bindTooltipButtons(tutorialId, stepIndex, steps) {
        var prevBtn = document.getElementById('tutorial-prev');
        var nextBtn = document.getElementById('tutorial-next');
        var finishBtn = document.getElementById('tutorial-finish');
        var closeBtn = document.getElementById('tutorial-close');

        if (prevBtn) {
            prevBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                showStep(tutorialId, stepIndex - 1);
            });
        }
        if (nextBtn) {
            nextBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                var step = steps[stepIndex];
                if (step.navigateTo) {
                    setState(tutorialId, stepIndex + 1);
                    window.location.href = step.navigateTo;
                } else {
                    showStep(tutorialId, stepIndex + 1);
                }
            });
        }
        if (finishBtn) {
            finishBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                endTutorial();
            });
        }
        if (closeBtn) {
            closeBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                endTutorial();
            });
        }
    }

    function endTutorial() {
        clearState();
        destroyOverlay();
    }

    /* ─── Tutorial Selection Modal ──────────────────────────────────────── */

    function showTutorialMenu() {
        var existing = document.getElementById('tutorial-menu-modal');
        if (existing) existing.remove();

        var modal = document.createElement('div');
        modal.id = 'tutorial-menu-modal';
        modal.style.cssText =
            'position:fixed;inset:0;z-index:9999;display:flex;align-items:center;' +
            'justify-content:center;padding:16px;';

        var backdrop = document.createElement('div');
        backdrop.style.cssText =
            'position:absolute;inset:0;background:rgba(0,0,0,0.5);' +
            'backdrop-filter:blur(2px);';
        backdrop.addEventListener('click', function () { modal.remove(); });
        modal.appendChild(backdrop);

        var card = document.createElement('div');
        card.className = 'tutorial-menu-card';
        card.style.cssText =
            'position:relative;background:white;border-radius:12px;padding:24px;' +
            'max-width:420px;width:100%;box-shadow:0 20px 60px rgba(0,0,0,0.3);z-index:1;';

        card.innerHTML =
            '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">' +
            '<h3 style="font-size:18px;font-weight:700;margin:0;">' +
            '<i class="ri-graduation-cap-line" style="color:#ef4444;margin-right:8px;"></i>' +
            'Обучение по сайту</h3>' +
            '<button id="tutorial-menu-close" style="background:none;border:none;font-size:22px;' +
            'color:#9ca3af;cursor:pointer;line-height:1;">&times;</button></div>' +
            '<p style="color:#6b7280;font-size:13px;margin-bottom:16px;">' +
            'Выберите тему для интерактивного обучения:</p>' +
            '<div id="tutorial-menu-items" style="display:flex;flex-direction:column;gap:10px;"></div>';

        modal.appendChild(card);
        document.body.appendChild(modal);

        var itemsContainer = card.querySelector('#tutorial-menu-items');

        var user = window.__IC_USER || {};
        var isAuth = user.isAuthenticated;
        var isPpWorker = user.isPpWorker || user.isStaff;

        var tutorials = [];

        if (!isAuth) {
            // Tutorials for guests
            tutorials = [
                { id: 'guest_register', icon: 'ri-user-add-line', color: '#2563eb' },
                { id: 'guest_login', icon: 'ri-login-box-line', color: '#16a34a' },
                { id: 'guest_how_to_order', icon: 'ri-shopping-bag-line', color: '#ea580c' },
            ];
        } else {
            // Common tutorials for all authenticated users
            tutorials = [
                { id: 'add_track', icon: 'ri-add-circle-line', color: '#16a34a' },
                { id: 'view_receipts', icon: 'ri-bill-line', color: '#2563eb' },
                { id: 'receive_parcels', icon: 'ri-hand-coin-line', color: '#ea580c' },
            ];
            // Additional tutorials for ПВЗ workers
            if (isPpWorker) {
                tutorials.push(
                    { id: 'pp_acceptance_tutorial', icon: 'ri-inbox-archive-line', color: '#16a34a', separator: true },
                    { id: 'pp_extradition_tutorial', icon: 'ri-hand-coin-line', color: '#2563eb' },
                    { id: 'pp_warehouse_tutorial', icon: 'ri-building-2-line', color: '#7c3aed' },
                    { id: 'pp_restructure_tutorial', icon: 'ri-refresh-line', color: '#ea580c' }
                );
            }
        }

        tutorials.forEach(function (t) {
            // Add separator before ПВЗ section
            if (t.separator) {
                var sep = document.createElement('div');
                sep.style.cssText = 'display:flex;align-items:center;gap:8px;padding:4px 0;';
                sep.innerHTML = '<div style="flex:1;height:1px;background:#e5e7eb;"></div>' +
                    '<span style="font-size:11px;color:#9ca3af;white-space:nowrap;">Для сотрудников ПВЗ</span>' +
                    '<div style="flex:1;height:1px;background:#e5e7eb;"></div>';
                itemsContainer.appendChild(sep);
            }

            var btn = document.createElement('button');
            btn.className = 'tutorial-menu-btn';
            btn.style.cssText =
                'display:flex;align-items:center;gap:12px;padding:14px 16px;' +
                'border:1px solid #e5e7eb;border-radius:10px;background:white;' +
                'cursor:pointer;text-align:left;transition:all 0.2s;font-size:14px;' +
                'color:#374151;width:100%;';
            btn.innerHTML =
                '<i class="' + t.icon + '" style="font-size:22px;color:' + t.color + ';flex-shrink:0;"></i>' +
                '<span style="font-weight:500;">' + TUTORIALS[t.id].name + '</span>' +
                '<i class="ri-arrow-right-s-line" style="margin-left:auto;color:#9ca3af;"></i>';

            btn.addEventListener('mouseenter', function () {
                btn.style.borderColor = '#ef4444';
                btn.style.background = '#fef2f2';
            });
            btn.addEventListener('mouseleave', function () {
                btn.style.borderColor = '#e5e7eb';
                btn.style.background = 'white';
            });
            btn.addEventListener('click', function () {
                modal.remove();
                startTutorial(t.id);
            });

            itemsContainer.appendChild(btn);
        });

        document.getElementById('tutorial-menu-close').addEventListener('click', function () {
            modal.remove();
        });

        var escHandler = function (e) {
            if (e.key === 'Escape') {
                modal.remove();
                document.removeEventListener('keydown', escHandler);
            }
        };
        document.addEventListener('keydown', escHandler);
    }

    function startTutorial(tutorialId) {
        var tutorial = TUTORIALS[tutorialId];
        if (!tutorial) return;

        var steps = getEffectiveSteps(tutorial);
        var currentPath = window.location.pathname;
        var firstStep = steps[0];

        if (firstStep.page && !currentPath.startsWith(firstStep.page)) {
            setState(tutorialId, 0);
            window.location.href = firstStep.navigateTo || firstStep.page;
            return;
        }

        showStep(tutorialId, 0);
    }

    /* ─── Keyboard handler ──────────────────────────────────────────────── */

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && overlay) {
            endTutorial();
        }
    });

    /* ─── Resize handler ────────────────────────────────────────────────── */

    var resizeTimer;
    window.addEventListener('resize', function () {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(function () {
            var state = getState();
            if (state && overlay) {
                showStep(state.id, state.step);
            }
        }, 200);
    });

    /* ─── Global API ────────────────────────────────────────────────────── */

    window.InterCargoTutorial = {
        showMenu: showTutorialMenu,
        start: startTutorial,
        end: endTutorial,
    };

    /* ─── Auto-resume on page load ──────────────────────────────────────── */

    document.addEventListener('DOMContentLoaded', function () {
        var state = getState();
        if (state && state.id && TUTORIALS[state.id]) {
            setTimeout(function () {
                showStep(state.id, state.step);
            }, 500);
        }
    });
})();
