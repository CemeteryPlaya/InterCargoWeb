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

    function getMobileNavHeight() {
        var nav = document.getElementById('mobile-bottom-nav');
        if (nav) return nav.offsetHeight || 64;
        return 64;
    }

    /**
     * Calculate the bottom offset for the tutorial tooltip on mobile.
     * Takes into account the bottom nav bar AND any visible bottom-sheet modals.
     */
    function getMobileBottomOffset() {
        var navH = getMobileNavHeight();

        // Check for open bottom-sheet modals that sit above the nav
        var sheets = document.querySelectorAll(
            '#add-track-sheet, .mobile-bottom-sheet'
        );
        var maxSheetH = 0;
        for (var i = 0; i < sheets.length; i++) {
            var sheet = sheets[i];
            // Sheet is visible if it has translate-y-0 (open) and its parent modal is not hidden
            var parent = sheet.closest('.fixed');
            if (!parent || parent.classList.contains('hidden')) continue;
            if (sheet.classList.contains('translate-y-full')) continue;
            var h = sheet.offsetHeight || 0;
            if (h > maxSheetH) maxSheetH = h;
        }

        return maxSheetH > 0 ? maxSheetH : navH;
    }

    /* ─── Tutorial Definitions ──────────────────────────────────────────── */

    var TUTORIALS = {
        add_track: {
            name: 'Трек-кодтарды қалай қосу керек',
            steps: [
                {
                    page: '/profile/track-codes/',
                    mobile: true,
                    selector: '#mobile-menu-toggle',
                    text: 'Бүйірлік навигация тақтасын ашу үшін мәзір белгішесін басыңыз.',
                    position: 'bottom',
                },
                {
                    page: '/profile/track-codes/',
                    selector: 'a[href*="track-codes"]',
                    selectorScope: 'sidebar',
                    text: 'Трек-кодтарыңызды басқару үшін бүйірлік мәзірдегі "Трек-кодтар" бөліміне өтіңіз.',
                    position: 'right',
                    mobilePosition: 'bottom',
                    navigateTo: '/profile/track-codes/',
                    beforeShow: function () { openMobileSidebar(); },
                },
                {
                    page: '/profile/track-codes/',
                    selector: 'button.bg-green-500',
                    text: 'Жаңа трек-код қосу нысанын ашу үшін "Қосу" түймесін басыңыз.',
                    position: 'bottom',
                    beforeShow: function () { closeMobileSidebar(); },
                },
                {
                    page: '/profile/track-codes/',
                    selector: '#track-code-input',
                    text: 'Трек-кодты осы өріске енгізіңіз. Трек-кодты сатушыдан тауарды төлегеннен кейін аласыз.',
                    position: 'bottom',
                    beforeShow: function () {
                        openAlpineModal('addModal');
                    },
                },
                {
                    page: '/profile/track-codes/',
                    selector: 'input[name="description"]',
                    text: 'Посылканың сипаттамасын қосыңыз (міндетті емес). Мысалы: "Қысқы куртка" — бұл посылкаларды шатастырмауға көмектеседі.',
                    position: 'bottom',
                },
                {
                    page: '/profile/track-codes/',
                    selector: 'button[type="submit"].bg-green-500',
                    selectorScope: 'modal',
                    text: 'Трек-кодты қосу үшін "Сақтау" түймесін басыңыз. Одан кейін посылканың күйін бақылай аласыз.',
                    position: 'top',
                },
            ],
            mobileSteps: [
                {
                    page: '/profile/mobile-parcels/',
                    selector: '[data-nav="parcels"]',
                    text: 'Төменгі навигация тақтасындағы "Посылкалар" қойындысын басыңыз.',
                    position: 'top',
                    navigateTo: '/profile/mobile-parcels/',
                },
                {
                    page: '/profile/mobile-parcels/',
                    selector: '#add-track-btn',
                    text: 'Қосу нысанын ашу үшін "Трек-код қосу" түймесін басыңыз.',
                    position: 'top',
                },
                {
                    page: '/profile/mobile-parcels/',
                    selector: 'input[name="track_code"]',
                    text: 'Трек-кодты осы өріске енгізіңіз. Трек-кодты сатушыдан тауарды төлегеннен кейін аласыз.',
                    position: 'top',
                    beforeShow: function () { openMobileAddModal(); },
                },
                {
                    page: '/profile/mobile-parcels/',
                    selector: 'textarea[name="description"]',
                    text: 'Посылканың сипаттамасын қосыңыз (міндетті емес). Мысалы: "Қысқы куртка" — бұл посылкаларды шатастырмауға көмектеседі.',
                    position: 'top',
                },
                {
                    page: '/profile/mobile-parcels/',
                    selector: '#add-track-modal button[type="submit"]',
                    text: 'Трек-кодты қосу үшін "Сақтау" түймесін басыңыз. Одан кейін посылканың күйін бақылай аласыз.',
                    position: 'top',
                },
            ],
        },

        view_receipts: {
            name: 'Чектерді қалай көру керек',
            steps: [
                {
                    page: '/profile/delivered-posts/',
                    mobile: true,
                    selector: '#mobile-menu-toggle',
                    text: 'Бүйірлік навигация тақтасын ашу үшін мәзір белгішесін басыңыз.',
                    position: 'bottom',
                },
                {
                    page: '/profile/delivered-posts/',
                    selector: 'a[href*="delivered-posts"]',
                    selectorScope: 'sidebar',
                    text: 'Чектеріңізді көру үшін бүйірлік мәзірдегі "Чектер" бөліміне өтіңіз.',
                    position: 'right',
                    mobilePosition: 'bottom',
                    navigateTo: '/profile/delivered-posts/',
                    beforeShow: function () { openMobileSidebar(); },
                },
                {
                    page: '/profile/delivered-posts/',
                    selector: '.bg-white.border-2.border-gray-300',
                    fallbackSelector: 'h1',
                    text: 'Мұнда сіздің чектеріңіз көрсетіледі. Әр чекте посылкалардың күні, салмағы және құны туралы ақпарат бар.',
                    position: 'bottom',
                    beforeShow: function () { closeMobileSidebar(); },
                },
                {
                    page: '/profile/delivered-posts/',
                    selector: '.cursor-pointer.bg-gray-100',
                    fallbackSelector: '.bg-white.border-2.border-gray-300',
                    text: 'Әр посылканың трек-кодтарының тізімін, салмағын және құнын көру үшін чек тақырыбын басыңыз.',
                    position: 'bottom',
                },
                {
                    page: '/profile/delivered-posts/',
                    selector: null,
                    text: 'Ашылған чекте трек-кодтардың, әр посылканың салмағы мен бағасының кестесін, сондай-ақ жалпы сомасы мен алу пунктін көресіз.',
                    position: 'center',
                },
            ],
            mobileSteps: [
                {
                    page: null,
                    selector: '[data-nav="menu"]',
                    text: 'Чектерді көру үшін төменгі навигациядағы "Мәзір" бөліміне өтіңіз.',
                    position: 'top',
                    navigateTo: '/profile/mobile-menu/',
                },
                {
                    page: '/profile/mobile-menu/',
                    selector: 'a[href*="delivered-posts"]',
                    text: 'Чектеріңізге өту үшін "Чектер" белгішесін басыңыз.',
                    position: 'top',
                    navigateTo: '/profile/delivered-posts/',
                },
                {
                    page: '/profile/delivered-posts/',
                    selector: '.bg-white.border-2.border-gray-300',
                    fallbackSelector: 'h1',
                    text: 'Мұнда сіздің чектеріңіз көрсетіледі. Әр чекте посылкалардың күні, салмағы және құны туралы ақпарат бар.',
                    position: 'top',
                },
                {
                    page: '/profile/delivered-posts/',
                    selector: '.cursor-pointer.bg-gray-100',
                    fallbackSelector: '.bg-white.border-2.border-gray-300',
                    text: 'Әр посылканың трек-кодтарының тізімін, салмағын және құнын көру үшін чек тақырыбын басыңыз.',
                    position: 'top',
                },
                {
                    page: '/profile/delivered-posts/',
                    selector: null,
                    text: 'Ашылған чекте трек-кодтардың, әр посылканың салмағы мен бағасының кестесін, сондай-ақ жалпы сомасы мен алу пунктін көресіз.',
                    position: 'center',
                },
            ],
        },

        receive_parcels: {
            name: 'Посылкаларды қалай алу және төлеу керек',
            steps: [
                {
                    page: '/profile/',
                    mobile: true,
                    selector: '#mobile-menu-toggle',
                    text: 'Бүйірлік навигация тақтасын ашу үшін мәзір белгішесін басыңыз.',
                    position: 'bottom',
                },
                {
                    page: '/profile/',
                    selector: '#user-info',
                    selectorScope: 'sidebar',
                    selectorOverride: 'a[href*="/profile/"]',
                    text: 'Посылкаларды алу үшін профильдің басты бетіне өтіңіз.',
                    position: 'right',
                    mobilePosition: 'bottom',
                    navigateTo: '/profile/',
                    beforeShow: function () { openMobileSidebar(); },
                },
                {
                    page: '/profile/',
                    selector: '#trackcodes',
                    text: 'Мұнда трек-кодтарыңыздың статустар бойынша статистикасы көрсетіледі. Посылкалар ПВЗ-ға келгенде, статус "Келді (ПВЗ)" болып өзгереді.',
                    position: 'bottom',
                    beforeShow: function () { closeMobileSidebar(); },
                },
                {
                    page: '/profile/',
                    selector: '.quickIssueBtn',
                    fallbackSelector: '#trackcodes',
                    text: 'Посылкалар ПВЗ-ға жеткізілгенде, жасыл "Посылкаларды алу" түймесі пайда болады. Алу процесін бастау үшін оны басыңыз.',
                    position: 'bottom',
                },
                {
                    page: '/profile/',
                    selector: null,
                    text: 'Басқаннан кейін растау үшін посылкалар саны көрсетіледі. Тексеріп, "Жарайды" түймесін басыңыз.',
                    position: 'center',
                    icon: 'ri-checkbox-circle-line',
                },
                {
                    page: '/profile/',
                    selector: null,
                    text: 'Содан кейін экранда QR-код пайда болады. Оны алу пунктінің қызметкеріне көрсетіңіз — ол кодты сканерлеп, посылкаларыңызды береді.',
                    position: 'center',
                    icon: 'ri-qr-code-line',
                },
                {
                    page: '/profile/',
                    selector: null,
                    text: 'Төлемді алу пунктінде орнында жасай аласыз. Дайын — посылкаларыңыз алынды!',
                    position: 'center',
                    icon: 'ri-bank-card-line',
                },
            ],
            mobileSteps: [
                {
                    page: '/profile/mobile-qr/',
                    selector: '.mobile-nav-qr',
                    fallbackSelector: '[data-nav="qr"]',
                    text: 'Төменгі навигация тақтасындағы "QR" түймесін басыңыз.',
                    position: 'top',
                    navigateTo: '/profile/mobile-qr/',
                },
                {
                    page: '/profile/mobile-qr/',
                    selector: '.quickIssueBtn',
                    fallbackSelector: 'h1',
                    text: 'Посылкалар ПВЗ-ға жеткізілгенде, жасыл "Посылкаларды алу" түймесі пайда болады. Алу процесін бастау үшін оны басыңыз.',
                    position: 'top',
                },
                {
                    page: '/profile/mobile-qr/',
                    selector: null,
                    text: 'Басқаннан кейін растау үшін посылкалар саны көрсетіледі. Тексеріп, "Жарайды" түймесін басыңыз.',
                    position: 'center',
                    icon: 'ri-checkbox-circle-line',
                },
                {
                    page: '/profile/mobile-qr/',
                    selector: null,
                    text: 'Содан кейін экранда QR-код пайда болады. Оны алу пунктінің қызметкеріне көрсетіңіз — ол кодты сканерлеп, посылкаларыңызды береді.',
                    position: 'center',
                    icon: 'ri-qr-code-line',
                },
                {
                    page: '/profile/mobile-qr/',
                    selector: null,
                    text: 'Төлемді алу пунктінде орнында жасай аласыз. Дайын — посылкаларыңыз алынды!',
                    position: 'center',
                    icon: 'ri-bank-card-line',
                },
            ],
        },

        /* ─── Tutorials for unauthenticated users ────────────────────────── */

        guest_register: {
            name: 'Қалай тіркелу керек',
            guest: true,
            steps: [
                {
                    page: '/register/registration',
                    selector: null,
                    text: 'Қош келдіңіз! Қазір Inter Cargo сайтында қалай тіркелетінін көрсетеміз. Бастау үшін "Келесі" түймесін басыңыз.',
                    position: 'center',
                    icon: 'ri-user-add-line',
                    navigateTo: '/register/registration',
                },
                {
                    page: '/register/registration',
                    selector: 'input[name="login"]',
                    text: 'Логинді латын әріптерімен енгізіңіз. Бұл логин сайтқа кіру және посылкаларыңызды анықтау үшін қолданылады.',
                    position: 'bottom',
                },
                {
                    page: '/register/registration',
                    selector: 'input[name="phone"]',
                    text: 'Телефон нөміріңізді енгізіңіз. Ол арқылы сайтқа да кіре аласыз.',
                    position: 'bottom',
                },
                {
                    page: '/register/registration',
                    selector: 'input[name="email"]',
                    text: 'Email-іңізді көрсетіңіз. Посылка күйі туралы хабарландырулар оған келеді.',
                    position: 'bottom',
                },
                {
                    page: '/register/registration',
                    selector: 'select[name="pickup"]',
                    text: 'Посылкаларыңызды алатын қолайлы алу пунктін (ПВЗ) таңдаңыз.',
                    position: 'bottom',
                },
                {
                    page: '/register/registration',
                    selector: '#password',
                    text: 'Сенімді құпия сөз ойлап табыңыз. Ең кемі 8 таңба, әріптер мен цифрларды қолданыңыз.',
                    position: 'bottom',
                },
                {
                    page: '/register/registration',
                    selector: '#registerBtn',
                    text: 'Барлық өрістерді толтырғаннан кейін "Тіркелу" түймесін басыңыз. Дайын!',
                    position: 'top',
                },
            ],
        },

        guest_login: {
            name: 'Сайтқа қалай кіру керек',
            guest: true,
            steps: [
                {
                    page: '/register/login/',
                    selector: null,
                    text: 'Қазір аккаунтыңызға қалай кіру керектігін көрсетеміз. Логин, телефон немесе email арқылы кіре аласыз.',
                    position: 'center',
                    icon: 'ri-login-box-line',
                    navigateTo: '/register/login/',
                },
                {
                    page: '/register/login/',
                    selector: '.flex.bg-gray-100.rounded-lg',
                    fallbackSelector: 'h2',
                    text: 'Кіру әдісін таңдаңыз: логин, телефон нөмірі немесе email бойынша. Керекті қойындыны басыңыз.',
                    position: 'bottom',
                },
                {
                    page: '/register/login/',
                    selector: '#password-login',
                    text: 'Тіркелу кезінде көрсеткен құпия сөзіңізді енгізіп, "Кіру" түймесін басыңыз.',
                    position: 'bottom',
                },
            ],
        },

        guest_how_to_order: {
            name: 'Тапсырыс беруді қалай бастау керек',
            guest: true,
            steps: [
                {
                    page: null,
                    selector: null,
                    text: 'Қытайдан тауарларға тапсырыс бергіңіз келе ме? Мынау — тәртіп. "Келесі" түймесін басыңыз.',
                    position: 'center',
                    icon: 'ri-shopping-bag-line',
                },
                {
                    page: null,
                    selector: null,
                    text: '1. Inter Cargo менеджеріне WhatsApp арқылы жазыңыз. Ол тарифтер, жеткізу шарттары туралы айтады және сұрақтарыңызға жауап береді.',
                    position: 'center',
                    icon: 'ri-whatsapp-line',
                },
                {
                    page: null,
                    selector: null,
                    text: '2. Менеджерден нұсқаулық алыңыз: Қытайдағы қойма мекенжайы және тапсырысты ресімдеу ережелері.',
                    position: 'center',
                    icon: 'ri-file-text-line',
                },
                {
                    page: null,
                    selector: null,
                    text: '3. Сайтымызда тіркеліңіз — посылкаларды бақылау және чектерді алу үшін қажет.',
                    position: 'center',
                    icon: 'ri-user-add-line',
                },
                {
                    page: null,
                    selector: null,
                    text: '4. Қытайлық сауда алаңында тапсырыс беріңіз (Taobao, Pinduoduo, 1688 т.б.).',
                    position: 'center',
                    icon: 'ri-global-line',
                },
                {
                    page: null,
                    selector: null,
                    text: '5. Тапсырыс беру кезінде Қытайдағы қоймамыздың мекенжайын және сайттағы логиніңізді көрсетіңіз — осылайша біз посылканың иесін анықтаймыз.',
                    position: 'center',
                    icon: 'ri-map-pin-line',
                },
                {
                    page: null,
                    selector: null,
                    text: '6. Посылканың трек-кодын жеке кабинетке қосыңыз. Жеткізу күйін Қытайдан ПВЗ-ға дейін бақылаңыз.',
                    position: 'center',
                    icon: 'ri-barcode-line',
                },
                {
                    page: null,
                    selector: null,
                    text: 'Дайын! Посылка ПВЗ-ға келгенде, сізге хабарландыру келеді. Келіңіз, төлеңіз және алыңыз.',
                    position: 'center',
                    icon: 'ri-checkbox-circle-line',
                },
            ],
        },

        /* ─── Tutorials for ПВЗ employees ────────────────────────────────── */

        pp_acceptance_tutorial: {
            name: 'Тауар қабылдау',
            ppWorker: true,
            steps: [
                {
                    page: '/profile/pp-acceptance/',
                    mobile: true,
                    selector: '#mobile-menu-toggle',
                    text: 'Бүйірлік тақтаны ашу үшін мәзір белгішесін басыңыз.',
                    position: 'bottom',
                },
                {
                    page: '/profile/pp-acceptance/',
                    selector: 'a[href*="pp-acceptance"]',
                    selectorScope: 'sidebar',
                    text: 'Бүйірлік мәзірдегі "Тауар қабылдау" бөліміне өтіңіз.',
                    position: 'right',
                    mobilePosition: 'bottom',
                    navigateTo: '/profile/pp-acceptance/',
                    beforeShow: function () { openMobileSidebar(); },
                },
                {
                    page: '/profile/pp-acceptance/',
                    selector: '.border-yellow-400',
                    fallbackSelector: 'h2',
                    text: 'Мұнда қабылдауды күтіп тұрған жеткізулер көрсетіледі. Әр карточка — чектер санымен бір жүргізушіден келген жеткізу.',
                    position: 'bottom',
                    beforeShow: function () { closeMobileSidebar(); },
                },
                {
                    page: '/profile/pp-acceptance/',
                    selector: null,
                    text: 'Жүргізуші "Беруді бастау" түймесін басқанда, карточкада "Қабылдау" түймесі пайда болады. Посылкаларды қабылдауды бастау үшін оны басыңыз.',
                    position: 'center',
                    icon: 'ri-inbox-archive-line',
                },
                {
                    page: '/profile/pp-acceptance/',
                    selector: null,
                    text: 'Әр чектің QR-кодын сканермен немесе камерамен сканерлеңіз. Жүйе чекті автоматты түрде тексеріп, оны қабылданды деп белгілейді.',
                    position: 'center',
                    icon: 'ri-qr-code-line',
                },
                {
                    page: '/profile/pp-acceptance/',
                    selector: null,
                    text: 'Барлық чектерді қабылдағаннан кейін "Сессияны аяқтау" түймесін басыңыз. Посылкалар сіздің ПВЗ қоймасына жылжытылады.',
                    position: 'center',
                    icon: 'ri-checkbox-circle-line',
                },
            ],
            mobileSteps: [
                {
                    page: null,
                    selector: '[data-nav="menu"]',
                    text: 'Төменгі навигациядағы "Мәзір" бөліміне өтіңіз.',
                    position: 'top',
                    navigateTo: '/profile/mobile-menu/',
                },
                {
                    page: '/profile/mobile-menu/',
                    selector: 'a[href*="pp-acceptance"]',
                    text: 'ПВЗ қызметкерлеріне арналған бөлімдегі "Қабылдау" белгішесін басыңыз.',
                    position: 'top',
                    navigateTo: '/profile/pp-acceptance/',
                },
                {
                    page: '/profile/pp-acceptance/',
                    selector: '.border-yellow-400',
                    fallbackSelector: 'h2',
                    text: 'Мұнда қабылдауды күтіп тұрған жеткізулер көрсетіледі. Әр карточка — чектер санымен бір жүргізушіден келген жеткізу.',
                    position: 'top',
                },
                {
                    page: '/profile/pp-acceptance/',
                    selector: null,
                    text: 'Жүргізуші "Беруді бастау" түймесін басқанда, карточкада "Қабылдау" түймесі пайда болады. Посылкаларды қабылдауды бастау үшін оны басыңыз.',
                    position: 'center',
                    icon: 'ri-inbox-archive-line',
                },
                {
                    page: '/profile/pp-acceptance/',
                    selector: null,
                    text: 'Әр чектің QR-кодын сканермен немесе камерамен сканерлеңіз. Жүйе чекті автоматты түрде тексеріп, оны қабылданды деп белгілейді.',
                    position: 'center',
                    icon: 'ri-qr-code-line',
                },
                {
                    page: '/profile/pp-acceptance/',
                    selector: null,
                    text: 'Барлық чектерді қабылдағаннан кейін "Сессияны аяқтау" түймесін басыңыз. Посылкалар сіздің ПВЗ қоймасына жылжытылады.',
                    position: 'center',
                    icon: 'ri-checkbox-circle-line',
                },
            ],
        },

        pp_extradition_tutorial: {
            name: 'Посылкаларды беру',
            ppWorker: true,
            steps: [
                {
                    page: '/profile/extradition/',
                    mobile: true,
                    selector: '#mobile-menu-toggle',
                    text: 'Навигация үшін мәзір белгішесін басыңыз.',
                    position: 'bottom',
                },
                {
                    page: '/profile/extradition/',
                    selector: 'a[href*="extradition"]',
                    selectorScope: 'sidebar',
                    text: '"Посылкаларды беру" бөліміне өтіңіз — мұнда клиенттерге посылка беру рәсімделеді.',
                    position: 'right',
                    mobilePosition: 'bottom',
                    navigateTo: '/profile/extradition/',
                    beforeShow: function () { openMobileSidebar(); },
                },
                {
                    page: '/profile/extradition/',
                    selector: '#barcode',
                    fallbackSelector: 'h1',
                    text: 'Клиент посылкаларын алуға келгенде, оның беру QR-кодын осы өріске сканерлеңіз. Сондай-ақ кодты қолмен енгізуге болады.',
                    position: 'bottom',
                    beforeShow: function () { closeMobileSidebar(); },
                },
                {
                    page: '/profile/extradition/',
                    selector: '#scanBarcodeBtn',
                    fallbackSelector: '#searchBtn',
                    text: 'Немесе камераны ашып, клиенттің QR-кодын сканерлеу үшін осы түймені басыңыз.',
                    position: 'bottom',
                },
                {
                    page: '/profile/extradition/',
                    selector: null,
                    text: 'Клиенттің QR-кодын сканерлегеннен кейін жүйе оның пакетін тауып, ақпаратты көрсетеді: клиент аты, ПВЗ, сақтау ұяшығы және посылкалары бар чектер тізімі.',
                    position: 'center',
                    icon: 'ri-search-line',
                },
                {
                    page: '/profile/extradition/',
                    selector: null,
                    text: 'Жылдам беру үшін "Беруді рәсімдеу" түймесін басыңыз. Тексеру үшін әр чектегі QR-кодтарды сканерлеуге "Тексеру және беру" түймесін басыңыз.',
                    position: 'center',
                    icon: 'ri-qr-scan-2-line',
                },
                {
                    page: '/profile/extradition/',
                    selector: null,
                    text: 'Тексеру режимінде әр чектің QR-кодын сканерлеңіз. Прогресс жолағы қанша чек тексерілгенін көрсетеді. Барлық чектерді тексергеннен кейін "Беруді растау" түймесін басыңыз.',
                    position: 'center',
                    icon: 'ri-checkbox-circle-line',
                },
                {
                    page: '/profile/extradition/',
                    selector: null,
                    text: 'Беруді рәсімдегеннен кейін: посылкалар берілген ретінде белгіленеді, сақтау ұяшығы босайды және клиент хабарландыру алады.',
                    position: 'center',
                    icon: 'ri-hand-coin-line',
                },
            ],
            mobileSteps: [
                {
                    page: null,
                    selector: '[data-nav="menu"]',
                    text: 'Төменгі навигациядағы "Мәзір" бөліміне өтіңіз.',
                    position: 'top',
                    navigateTo: '/profile/mobile-menu/',
                },
                {
                    page: '/profile/mobile-menu/',
                    selector: 'a[href*="extradition"]',
                    text: 'ПВЗ қызметкерлеріне арналған бөлімдегі "Беру" белгішесін басыңыз.',
                    position: 'top',
                    navigateTo: '/profile/extradition/',
                },
                {
                    page: '/profile/extradition/',
                    selector: '#barcode',
                    fallbackSelector: 'h1',
                    text: 'Клиент посылкаларын алуға келгенде, оның беру QR-кодын осы өріске сканерлеңіз. Сондай-ақ кодты қолмен енгізуге болады.',
                    position: 'top',
                },
                {
                    page: '/profile/extradition/',
                    selector: '#scanBarcodeBtn',
                    fallbackSelector: '#searchBtn',
                    text: 'Немесе камераны ашып, клиенттің QR-кодын сканерлеу үшін осы түймені басыңыз.',
                    position: 'top',
                },
                {
                    page: '/profile/extradition/',
                    selector: null,
                    text: 'Сканерлегеннен кейін жүйе клиент туралы ақпаратты көрсетеді: аты, ПВЗ, сақтау ұяшығы және посылкалары бар чектер тізімі.',
                    position: 'center',
                    icon: 'ri-search-line',
                },
                {
                    page: '/profile/extradition/',
                    selector: null,
                    text: 'Жылдам беру үшін "Беруді рәсімдеу" түймесін басыңыз. Тексеру үшін әр чектегі QR-кодтарды сканерлеуге "Тексеру және беру" түймесін басыңыз.',
                    position: 'center',
                    icon: 'ri-qr-scan-2-line',
                },
                {
                    page: '/profile/extradition/',
                    selector: null,
                    text: 'Рәсімдегеннен кейін: посылкалар берілген ретінде белгіленеді, ұяшық босайды, клиент хабарландыру алады.',
                    position: 'center',
                    icon: 'ri-hand-coin-line',
                },
            ],
        },

        pp_warehouse_tutorial: {
            name: 'ПВЗ қоймасы',
            ppWorker: true,
            steps: [
                {
                    page: '/profile/warehouse/',
                    selector: 'h1',
                    text: 'Бұл "ПВЗ қоймасы" беті. Мұнда клиенттерге берілуді күтіп тұрған посылкалары бар барлық ұяшықтар көрсетіледі.',
                    position: 'bottom',
                    navigateTo: '/profile/warehouse/',
                },
                {
                    page: '/profile/warehouse/',
                    selector: '.w-14.h-14',
                    fallbackSelector: 'h1',
                    text: 'Ұяшық нөмірі квадратта көрсетіледі. Ұяшық нөмірін өзгерту үшін оны басыңыз. "Еден" — 0 ұяшығын білдіреді.',
                    position: 'bottom',
                },
                {
                    page: '/profile/warehouse/',
                    selector: null,
                    text: 'Әр ұяшық чектер бойынша ішкі ұяшықтарға бөлінген. Бұл клиенттің нақты посылкаларын оңай табуға мүмкіндік береді.',
                    position: 'center',
                    icon: 'ri-layout-grid-line',
                },
                {
                    page: '/profile/warehouse/',
                    selector: 'a[href*="inventory"]',
                    fallbackSelector: 'h1',
                    text: '"Түгендеу" түймесі қоймадағы барлық клиенттер, ұяшықтар мен посылкалар тізімі бар баспа құжатын жасайды.',
                    position: 'bottom',
                },
                {
                    page: '/profile/warehouse/',
                    selector: null,
                    text: 'Қойманың нақты құрамын жүйедегі деректермен салыстыру үшін түгендеуді қолданыңыз.',
                    position: 'center',
                    icon: 'ri-file-list-3-line',
                },
            ],
            mobileSteps: [
                {
                    page: null,
                    selector: '[data-nav="menu"]',
                    text: 'Төменгі навигациядағы "Мәзір" бөліміне өтіңіз.',
                    position: 'top',
                    navigateTo: '/profile/mobile-menu/',
                },
                {
                    page: '/profile/mobile-menu/',
                    selector: 'a[href*="warehouse"]',
                    text: 'Қызметкерлерге арналған бөлімдегі "ПВЗ қоймасы" белгішесін басыңыз.',
                    position: 'top',
                    navigateTo: '/profile/warehouse/',
                },
                {
                    page: '/profile/warehouse/',
                    selector: '.w-14.h-14',
                    fallbackSelector: 'h1',
                    text: 'Мұнда посылкалары бар барлық ұяшықтар көрсетіледі. Ұяшық нөмірі — квадратта. Нөмірді өзгерту үшін басыңыз. "Еден" — 0 ұяшығын білдіреді.',
                    position: 'top',
                },
                {
                    page: '/profile/warehouse/',
                    selector: null,
                    text: 'Әр ұяшық чектер бойынша ішкі ұяшықтарға бөлінген. Бұл клиенттің нақты посылкаларын оңай табуға мүмкіндік береді.',
                    position: 'center',
                    icon: 'ri-layout-grid-line',
                },
                {
                    page: '/profile/warehouse/',
                    selector: 'a[href*="inventory"]',
                    fallbackSelector: 'h1',
                    text: '"Түгендеу" түймесі қоймадағы барлық клиенттер, ұяшықтар мен посылкалар тізімі бар баспа құжатын жасайды.',
                    position: 'top',
                },
            ],
        },

        pp_restructure_tutorial: {
            name: 'Қойманы қайта құрылымдау',
            ppWorker: true,
            steps: [
                {
                    page: '/profile/warehouse/',
                    selector: 'h1',
                    text: 'Қайта құрылымдау қоймадағы барлық ұяшықтарды қайта тағайындауға мүмкіндік береді. Қойманы қайта ұйымдастыру қажет болғанда қолданыңыз.',
                    position: 'bottom',
                    navigateTo: '/profile/warehouse/',
                },
                {
                    page: '/profile/warehouse/',
                    selector: 'button[type="submit"]',
                    fallbackSelector: '.animate-pulse',
                    text: '"Қойманы қайта құрылымдау" түймесін басыңыз. Барлық ұяшық нөмірлері жойылады, ал посылкалар жүйеде қалады.',
                    position: 'bottom',
                },
                {
                    page: '/profile/warehouse/',
                    selector: null,
                    text: 'Басқаннан кейін ұяшықтарды тағайындау беті ашылады. Мұнда ұяшықтарды тағайындаудың 3 тәсілі бар: қолмен, сканермен немесе камерамен.',
                    position: 'center',
                    icon: 'ri-refresh-line',
                },
                {
                    page: '/profile/warehouse/',
                    selector: null,
                    text: 'Сканер: чектің QR-кодын сканерлеңіз — жүйе клиентті тауып, ұяшықты автоматты түрде тағайындайды.',
                    position: 'center',
                    icon: 'ri-barcode-line',
                },
                {
                    page: '/profile/warehouse/',
                    selector: null,
                    text: 'Камера: аппараттық сканер болмаса, телефон камерасын ашып, чектің QR-кодына бағыттаңыз.',
                    position: 'center',
                    icon: 'ri-camera-line',
                },
                {
                    page: '/profile/warehouse/',
                    selector: null,
                    text: 'Қолмен: тізімнен клиентті таңдап, ұяшық нөмірін енгізіңіз (немесе автотағайындау үшін бос қалдырыңыз).',
                    position: 'center',
                    icon: 'ri-edit-line',
                },
                {
                    page: '/profile/warehouse/',
                    selector: null,
                    text: 'Барлық ұяшықтар тағайындалғаннан кейін "Қайта құрылымдауды аяқтау" түймесін басыңыз. Аяқталғанға дейін қоймада "Қайта құрылымдауды жалғастыру" түймесі жыпылықтайды.',
                    position: 'center',
                    icon: 'ri-checkbox-circle-line',
                },
            ],
            mobileSteps: [
                {
                    page: null,
                    selector: '[data-nav="menu"]',
                    text: 'Төменгі навигациядағы "Мәзір" бөліміне өтіңіз.',
                    position: 'top',
                    navigateTo: '/profile/mobile-menu/',
                },
                {
                    page: '/profile/mobile-menu/',
                    selector: 'a[href*="warehouse"]',
                    text: 'Қызметкерлерге арналған бөлімдегі "ПВЗ қоймасы" белгішесін басыңыз.',
                    position: 'top',
                    navigateTo: '/profile/warehouse/',
                },
                {
                    page: '/profile/warehouse/',
                    selector: 'button[type="submit"]',
                    fallbackSelector: '.animate-pulse',
                    text: '"Қойманы қайта құрылымдау" түймесін басыңыз. Барлық ұяшық нөмірлері жойылады, ал посылкалар жүйеде қалады.',
                    position: 'top',
                },
                {
                    page: '/profile/warehouse/',
                    selector: null,
                    text: 'Ұяшықтарды тағайындау беті ашылады. 3 тәсіл: қолмен, сканермен немесе камерамен.',
                    position: 'center',
                    icon: 'ri-refresh-line',
                },
                {
                    page: '/profile/warehouse/',
                    selector: null,
                    text: 'Сканер: чектің QR-кодын сканерлеңіз — жүйе клиентті тауып, ұяшықты автоматты түрде тағайындайды.',
                    position: 'center',
                    icon: 'ri-barcode-line',
                },
                {
                    page: '/profile/warehouse/',
                    selector: null,
                    text: 'Камера: аппараттық сканер болмаса, камераны ашып, чектің QR-кодына бағыттаңыз.',
                    position: 'center',
                    icon: 'ri-camera-line',
                },
                {
                    page: '/profile/warehouse/',
                    selector: null,
                    text: 'Барлық ұяшықтар тағайындалғаннан кейін "Қайта құрылымдауды аяқтау" түймесін басыңыз.',
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

    function openMobileAddModal() {
        var addBtn = document.getElementById('add-track-btn');
        if (addBtn) {
            addBtn.click();
            return;
        }
        // Fallback: open modal directly
        var modal = document.getElementById('add-track-modal');
        var sheet = document.getElementById('add-track-sheet');
        var backdrop = modal ? modal.querySelector('[class*="bg-black"]') : null;
        if (modal) {
            modal.classList.remove('hidden');
            modal.classList.add('flex');
            if (sheet) {
                requestAnimationFrame(function () {
                    requestAnimationFrame(function () {
                        sheet.classList.remove('translate-y-full');
                        sheet.classList.add('translate-y-0');
                        if (backdrop) {
                            backdrop.classList.remove('bg-black/0');
                            backdrop.classList.add('bg-black/50');
                        }
                    });
                });
            }
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

        var mobile = isMobile();

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
            'position:fixed;z-index:10001;box-sizing:border-box;' +
            'background:white;color:#1f2937;' +
            'transition:opacity 0.3s ease;' +
            (mobile
                ? 'left:0;right:0;width:100%;max-width:100%;' +
                  'border-radius:24px 24px 0 0;padding:24px 20px;' +
                  'box-shadow:0 -4px 30px rgba(0,0,0,0.25);' +
                  'font-size:15px;line-height:1.65;'
                : 'max-width:380px;width:calc(100vw - 16px);' +
                  'border-radius:12px;padding:20px;' +
                  'box-shadow:0 10px 40px rgba(0,0,0,0.3);' +
                  'font-size:14px;line-height:1.6;');
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

    var activeNavOrigZIndex = null;
    var activeContainerEl = null;
    var activeContainerOrigZIndex = null;

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

        // If element is inside the bottom nav, raise the nav above the overlay
        var bottomNav = document.getElementById('mobile-bottom-nav');
        if (bottomNav && bottomNav.contains(el)) {
            activeNavOrigZIndex = bottomNav.style.zIndex;
            bottomNav.style.zIndex = '9999';
        }

        // If element is inside a fixed modal/bottom-sheet, raise it above the overlay
        var fixedParent = el.closest('.fixed');
        if (fixedParent && fixedParent !== bottomNav && fixedParent.id !== 'tutorial-overlay') {
            activeContainerEl = fixedParent;
            activeContainerOrigZIndex = fixedParent.style.zIndex;
            fixedParent.style.zIndex = '9999';
        }

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
        // Restore bottom nav z-index
        if (activeNavOrigZIndex !== null) {
            var bottomNav = document.getElementById('mobile-bottom-nav');
            if (bottomNav) bottomNav.style.zIndex = activeNavOrigZIndex;
            activeNavOrigZIndex = null;
        }
        // Restore modal container z-index
        if (activeContainerEl) {
            activeContainerEl.style.zIndex = activeContainerOrigZIndex;
            activeContainerEl = null;
            activeContainerOrigZIndex = null;
        }
        activeEl = null;
        activeElOrigStyles = null;
    }

    /** Viewport dimensions safe for iOS Safari / Telegram WebView */
    function vw() { return document.documentElement.clientWidth  || window.innerWidth; }
    function vh() { return document.documentElement.clientHeight || window.innerHeight; }

    function positionTooltip(el, step, stepIndex, totalSteps) {
        var pos = step.position || 'bottom';
        var mobile = isMobile();
        if (mobile && step.mobilePosition) pos = step.mobilePosition;
        var icon = step.icon || 'ri-lightbulb-line';

        // Adaptive sizes for mobile vs desktop
        var btnPad = mobile ? '10px 20px' : '6px 16px';
        var btnRadius = mobile ? '10px' : '6px';
        var btnFont = mobile ? '14px' : '13px';
        var iconSize = mobile ? '28px' : '24px';
        var counterFont = mobile ? '13px' : '12px';
        var closeSize = mobile ? '24px' : '20px';
        var closeTop = mobile ? '16px' : '8px';
        var closeRight = mobile ? '16px' : '12px';

        // Build tooltip HTML
        var html =
            '<div style="display:flex;align-items:flex-start;gap:12px;">' +
            '<i class="' + icon + '" style="font-size:' + iconSize + ';color:#ef4444;flex-shrink:0;margin-top:2px;"></i>' +
            '<div style="flex:1;min-width:0;">' +
            '<p style="margin:0 0 16px 0;word-wrap:break-word;">' + step.text + '</p>' +
            '<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;">' +
            '<span style="font-size:' + counterFont + ';color:#9ca3af;white-space:nowrap;">' + (stepIndex + 1) + ' / ' + totalSteps + '</span>' +
            '<div style="display:flex;gap:8px;">';

        if (stepIndex > 0) {
            html += '<button id="tutorial-prev" style="padding:' + btnPad + ';border-radius:' + btnRadius + ';' +
                'border:1px solid #d1d5db;background:white;color:#374151;font-size:' + btnFont + ';' +
                'cursor:pointer;font-weight:500;white-space:nowrap;">Артқа</button>';
        }

        if (stepIndex < totalSteps - 1) {
            var nextLabel = step.navigateTo ? 'Өту' : 'Келесі';
            html += '<button id="tutorial-next" style="padding:' + btnPad + ';border-radius:' + btnRadius + ';' +
                'border:none;background:#ef4444;color:white;font-size:' + btnFont + ';' +
                'cursor:pointer;font-weight:500;white-space:nowrap;">' + nextLabel + '</button>';
        } else {
            html += '<button id="tutorial-finish" style="padding:' + btnPad + ';border-radius:' + btnRadius + ';' +
                'border:none;background:#16a34a;color:white;font-size:' + btnFont + ';' +
                'cursor:pointer;font-weight:500;white-space:nowrap;">Дайын</button>';
        }

        html += '</div></div></div></div>';
        html += '<button id="tutorial-close" style="position:absolute;top:' + closeTop + ';right:' + closeRight + ';' +
            'background:none;border:none;font-size:' + closeSize + ';color:#9ca3af;cursor:pointer;' +
            'line-height:1;" title="Жабу">&times;</button>';

        tooltip.innerHTML = html;

        // Reset all positioning before measuring
        tooltip.style.top = '';
        tooltip.style.left = '';
        tooltip.style.right = '';
        tooltip.style.bottom = '';
        tooltip.style.transform = '';

        // Mobile: pin above bottom nav or above an open bottom-sheet modal
        if (mobile) {
            tooltip.style.bottom = getMobileBottomOffset() + 'px';
            tooltip.style.left = '0';
            tooltip.style.right = '0';
            return;
        }

        // Center mode (no target element) — desktop only
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
        var mobile = isMobile();
        // Use dedicated mobileSteps if available on mobile
        if (mobile && tutorial.mobileSteps) {
            return tutorial.mobileSteps;
        }
        // Filter out mobile-only steps when on desktop
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

        var mobile = isMobile();

        var modal = document.createElement('div');
        modal.id = 'tutorial-menu-modal';
        modal.style.cssText =
            'position:fixed;inset:0;z-index:9999;display:flex;' +
            (mobile
                ? 'align-items:flex-end;'
                : 'align-items:center;justify-content:center;padding:16px;');

        var backdrop = document.createElement('div');
        backdrop.style.cssText =
            'position:absolute;inset:0;background:rgba(0,0,0,0.5);' +
            'backdrop-filter:blur(2px);';
        backdrop.addEventListener('click', function () { modal.remove(); });
        modal.appendChild(backdrop);

        var card = document.createElement('div');
        card.className = 'tutorial-menu-card';
        card.style.cssText =
            'position:relative;background:white;z-index:1;' +
            (mobile
                ? 'border-radius:24px 24px 0 0;padding:20px 16px calc(20px + env(safe-area-inset-bottom, 0px));' +
                  'width:100%;max-height:85vh;overflow-y:auto;' +
                  'box-shadow:0 -4px 30px rgba(0,0,0,0.25);'
                : 'border-radius:12px;padding:24px;max-width:420px;width:100%;' +
                  'box-shadow:0 20px 60px rgba(0,0,0,0.3);');

        var headerSize = mobile ? '17px' : '18px';
        var descSize = mobile ? '13px' : '13px';

        card.innerHTML =
            (mobile ? '<div style="width:40px;height:4px;background:#d1d5db;border-radius:2px;margin:0 auto 16px;"></div>' : '') +
            '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">' +
            '<h3 style="font-size:' + headerSize + ';font-weight:700;margin:0;">' +
            '<i class="ri-graduation-cap-line" style="color:#ef4444;margin-right:8px;"></i>' +
            'Сайтты үйрету</h3>' +
            '<button id="tutorial-menu-close" style="background:none;border:none;font-size:22px;' +
            'color:#9ca3af;cursor:pointer;line-height:1;">&times;</button></div>' +
            '<p style="color:#6b7280;font-size:' + descSize + ';margin-bottom:16px;">' +
            'Интерактивті үйрену тақырыбын таңдаңыз:</p>' +
            '<div id="tutorial-menu-items" style="display:flex;flex-direction:column;gap:' + (mobile ? '8px' : '10px') + ';"></div>';

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
                    '<span style="font-size:11px;color:#9ca3af;white-space:nowrap;">ПВЗ қызметкерлеріне</span>' +
                    '<div style="flex:1;height:1px;background:#e5e7eb;"></div>';
                itemsContainer.appendChild(sep);
            }

            var btn = document.createElement('button');
            btn.className = 'tutorial-menu-btn';
            var btnPadding = mobile ? '12px 14px' : '14px 16px';
            var btnFontSize = mobile ? '14px' : '14px';
            var iconFontSize = mobile ? '20px' : '22px';
            btn.style.cssText =
                'display:flex;align-items:center;gap:12px;padding:' + btnPadding + ';' +
                'border:1px solid #e5e7eb;border-radius:' + (mobile ? '16px' : '10px') + ';background:white;' +
                'cursor:pointer;text-align:left;transition:all 0.2s;font-size:' + btnFontSize + ';' +
                'color:#374151;width:100%;';
            btn.innerHTML =
                '<div style="width:' + (mobile ? '40px' : 'auto') + ';height:' + (mobile ? '40px' : 'auto') + ';' +
                (mobile ? 'border-radius:12px;display:flex;align-items:center;justify-content:center;flex-shrink:0;background:' + t.color + '14;' : 'flex-shrink:0;') + '">' +
                '<i class="' + t.icon + '" style="font-size:' + iconFontSize + ';color:' + t.color + ';"></i></div>' +
                '<span style="font-weight:500;flex:1;min-width:0;word-wrap:break-word;">' + TUTORIALS[t.id].name + '</span>' +
                '<i class="ri-arrow-right-s-line" style="flex-shrink:0;color:#9ca3af;"></i>';

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

    function validateEnvironment(tutorialId) {
        var tutorial = TUTORIALS[tutorialId];
        if (!tutorial) return 'Үйрету табылмады.';
        var mobile = isMobile();
        var steps = getEffectiveSteps(tutorial);
        if (!steps || steps.length === 0) return 'Бұл үйрету үшін қолжетімді қадамдар жоқ.';

        // On mobile, check that bottom navigation exists (for authenticated tutorials)
        if (mobile && !tutorial.guest) {
            var bottomNav = document.getElementById('mobile-bottom-nav');
            if (!bottomNav) return 'Мобильді навигация табылмады. Бетті жаңартыңыз.';
        }

        // Check that the first step's page is valid
        var firstStep = steps[0];
        if (firstStep.selector && !firstStep.page) {
            var el = document.querySelector(firstStep.selector);
            if (!el && !firstStep.fallbackSelector) {
                return 'Бірінші қадамға арналған интерфейс элементі табылмады. Бетті жаңартып көріңіз.';
            }
        }

        return null; // validation passed
    }

    function startTutorial(tutorialId) {
        var tutorial = TUTORIALS[tutorialId];
        if (!tutorial) return;

        // Validate environment before starting
        var error = validateEnvironment(tutorialId);
        if (error) {
            alert(error);
            return;
        }

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
