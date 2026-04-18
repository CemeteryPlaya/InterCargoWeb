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
            name: 'How to add track codes',
            steps: [
                {
                    page: '/profile/track-codes/',
                    mobile: true,
                    selector: '#mobile-menu-toggle',
                    text: 'Tap the menu icon to open the side navigation panel.',
                    position: 'bottom',
                },
                {
                    page: '/profile/track-codes/',
                    selector: 'a[href*="track-codes"]',
                    selectorScope: 'sidebar',
                    text: 'Go to the "Track codes" section in the side menu to manage your track codes.',
                    position: 'right',
                    mobilePosition: 'bottom',
                    navigateTo: '/profile/track-codes/',
                    beforeShow: function () { openMobileSidebar(); },
                },
                {
                    page: '/profile/track-codes/',
                    selector: 'button.bg-green-500',
                    text: 'Click the "Add" button to open the form for adding a new track code.',
                    position: 'bottom',
                    beforeShow: function () { closeMobileSidebar(); },
                },
                {
                    page: '/profile/track-codes/',
                    selector: '#track-code-input',
                    text: 'Enter your track code in this field. You get the track code from the seller after paying for the goods.',
                    position: 'bottom',
                    beforeShow: function () {
                        openAlpineModal('addModal');
                    },
                },
                {
                    page: '/profile/track-codes/',
                    selector: 'input[name="description"]',
                    text: 'Add a parcel description (optional). For example: "Winter jacket" — this will help you not to confuse parcels.',
                    position: 'bottom',
                },
                {
                    page: '/profile/track-codes/',
                    selector: 'button[type="submit"].bg-green-500',
                    selectorScope: 'modal',
                    text: 'Click "Save" to add the track code. After that you will be able to track the status of your parcel.',
                    position: 'top',
                },
            ],
            mobileSteps: [
                {
                    page: '/profile/mobile-parcels/',
                    selector: '[data-nav="parcels"]',
                    text: 'Tap the "Parcels" tab in the bottom navigation panel.',
                    position: 'top',
                    navigateTo: '/profile/mobile-parcels/',
                },
                {
                    page: '/profile/mobile-parcels/',
                    selector: '#add-track-btn',
                    text: 'Tap the "Add track code" button to open the add form.',
                    position: 'top',
                },
                {
                    page: '/profile/mobile-parcels/',
                    selector: 'input[name="track_code"]',
                    text: 'Enter your track code in this field. You get the track code from the seller after paying for the goods.',
                    position: 'top',
                    beforeShow: function () { openMobileAddModal(); },
                },
                {
                    page: '/profile/mobile-parcels/',
                    selector: 'textarea[name="description"]',
                    text: 'Add a parcel description (optional). For example: "Winter jacket" — this will help you not to confuse parcels.',
                    position: 'top',
                },
                {
                    page: '/profile/mobile-parcels/',
                    selector: '#add-track-modal button[type="submit"]',
                    text: 'Click "Save" to add the track code. After that you will be able to track the status of your parcel.',
                    position: 'top',
                },
            ],
        },

        view_receipts: {
            name: 'How to view receipts',
            steps: [
                {
                    page: '/profile/delivered-posts/',
                    mobile: true,
                    selector: '#mobile-menu-toggle',
                    text: 'Tap the menu icon to open the side navigation panel.',
                    position: 'bottom',
                },
                {
                    page: '/profile/delivered-posts/',
                    selector: 'a[href*="delivered-posts"]',
                    selectorScope: 'sidebar',
                    text: 'Go to the "Receipts" section in the side menu to view your receipts.',
                    position: 'right',
                    mobilePosition: 'bottom',
                    navigateTo: '/profile/delivered-posts/',
                    beforeShow: function () { openMobileSidebar(); },
                },
                {
                    page: '/profile/delivered-posts/',
                    selector: '.bg-white.border-2.border-gray-300',
                    fallbackSelector: 'h1',
                    text: 'Your receipts are displayed here. Each receipt contains information about the date, weight and cost of parcels.',
                    position: 'bottom',
                    beforeShow: function () { closeMobileSidebar(); },
                },
                {
                    page: '/profile/delivered-posts/',
                    selector: '.cursor-pointer.bg-gray-100',
                    fallbackSelector: '.bg-white.border-2.border-gray-300',
                    text: 'Click on the receipt header to expand details — list of track codes, weight and cost of each parcel.',
                    position: 'bottom',
                },
                {
                    page: '/profile/delivered-posts/',
                    selector: null,
                    text: 'In the expanded receipt you will see a table with track codes, weight and price of each parcel, as well as the total amount and pickup point.',
                    position: 'center',
                },
            ],
            mobileSteps: [
                {
                    page: null,
                    selector: '[data-nav="menu"]',
                    text: 'To view receipts, go to the "Menu" section in the bottom navigation.',
                    position: 'top',
                    navigateTo: '/profile/mobile-menu/',
                },
                {
                    page: '/profile/mobile-menu/',
                    selector: 'a[href*="delivered-posts"]',
                    text: 'Tap the "Receipts" icon to go to your receipts.',
                    position: 'top',
                    navigateTo: '/profile/delivered-posts/',
                },
                {
                    page: '/profile/delivered-posts/',
                    selector: '.bg-white.border-2.border-gray-300',
                    fallbackSelector: 'h1',
                    text: 'Your receipts are displayed here. Each receipt contains information about the date, weight and cost of parcels.',
                    position: 'top',
                },
                {
                    page: '/profile/delivered-posts/',
                    selector: '.cursor-pointer.bg-gray-100',
                    fallbackSelector: '.bg-white.border-2.border-gray-300',
                    text: 'Click on the receipt header to expand details — list of track codes, weight and cost of each parcel.',
                    position: 'top',
                },
                {
                    page: '/profile/delivered-posts/',
                    selector: null,
                    text: 'In the expanded receipt you will see a table with track codes, weight and price of each parcel, as well as the total amount and pickup point.',
                    position: 'center',
                },
            ],
        },

        receive_parcels: {
            name: 'How to receive and pay for parcels',
            steps: [
                {
                    page: '/profile/',
                    mobile: true,
                    selector: '#mobile-menu-toggle',
                    text: 'Tap the menu icon to open the side navigation panel.',
                    position: 'bottom',
                },
                {
                    page: '/profile/',
                    selector: '#user-info',
                    selectorScope: 'sidebar',
                    selectorOverride: 'a[href*="/profile/"]',
                    text: 'Go to the main profile page to receive parcels.',
                    position: 'right',
                    mobilePosition: 'bottom',
                    navigateTo: '/profile/',
                    beforeShow: function () { openMobileSidebar(); },
                },
                {
                    page: '/profile/',
                    selector: '#trackcodes',
                    text: 'This displays statistics of your track codes by status. When parcels arrive at the pickup point, the status will change to "Arrived (PP)".',
                    position: 'bottom',
                    beforeShow: function () { closeMobileSidebar(); },
                },
                {
                    page: '/profile/',
                    selector: '.quickIssueBtn',
                    fallbackSelector: '#trackcodes',
                    text: 'When parcels are delivered to the pickup point, a green "Receive parcels" button will appear. Click it to start the receiving process.',
                    position: 'bottom',
                },
                {
                    page: '/profile/',
                    selector: null,
                    text: 'After clicking, the number of parcels will be shown for confirmation. Check and click "OK".',
                    position: 'center',
                    icon: 'ri-checkbox-circle-line',
                },
                {
                    page: '/profile/',
                    selector: null,
                    text: 'Then a QR code will appear on the screen. Show it to the pickup point employee — they will scan the code and issue your parcels.',
                    position: 'center',
                    icon: 'ri-qr-code-line',
                },
                {
                    page: '/profile/',
                    selector: null,
                    text: 'You can make the payment on-site at the pickup point. Done — your parcels have been received!',
                    position: 'center',
                    icon: 'ri-bank-card-line',
                },
            ],
            mobileSteps: [
                {
                    page: '/profile/mobile-qr/',
                    selector: '.mobile-nav-qr',
                    fallbackSelector: '[data-nav="qr"]',
                    text: 'Tap the "QR" button in the bottom navigation panel.',
                    position: 'top',
                    navigateTo: '/profile/mobile-qr/',
                },
                {
                    page: '/profile/mobile-qr/',
                    selector: '.quickIssueBtn',
                    fallbackSelector: 'h1',
                    text: 'When parcels are delivered to the pickup point, a green "Receive parcels" button will appear. Click it to start the receiving process.',
                    position: 'top',
                },
                {
                    page: '/profile/mobile-qr/',
                    selector: null,
                    text: 'After clicking, the number of parcels will be shown for confirmation. Check and click "OK".',
                    position: 'center',
                    icon: 'ri-checkbox-circle-line',
                },
                {
                    page: '/profile/mobile-qr/',
                    selector: null,
                    text: 'Then a QR code will appear on the screen. Show it to the pickup point employee — they will scan the code and issue your parcels.',
                    position: 'center',
                    icon: 'ri-qr-code-line',
                },
                {
                    page: '/profile/mobile-qr/',
                    selector: null,
                    text: 'You can make the payment on-site at the pickup point. Done — your parcels have been received!',
                    position: 'center',
                    icon: 'ri-bank-card-line',
                },
            ],
        },

        /* ─── Tutorials for unauthenticated users ────────────────────────── */

        guest_register: {
            name: 'How to register',
            guest: true,
            steps: [
                {
                    page: '/register/registration',
                    selector: null,
                    text: 'Welcome! Now we will show you how to register on the Inter Cargo website. Click "Next" to begin.',
                    position: 'center',
                    icon: 'ri-user-add-line',
                    navigateTo: '/register/registration',
                },
                {
                    page: '/register/registration',
                    selector: 'input[name="login"]',
                    text: 'Enter your login in Latin letters. This login will be used to log in to the site and to identify your parcels.',
                    position: 'bottom',
                },
                {
                    page: '/register/registration',
                    selector: 'input[name="phone"]',
                    text: 'Enter your phone number. You can also use it to log in to the site.',
                    position: 'bottom',
                },
                {
                    page: '/register/registration',
                    selector: 'input[name="email"]',
                    text: 'Enter your email. Notifications about parcel status will be sent to it.',
                    position: 'bottom',
                },
                {
                    page: '/register/registration',
                    selector: 'select[name="pickup"]',
                    text: 'Choose a convenient pickup point (PP) where you will receive your parcels.',
                    position: 'bottom',
                },
                {
                    page: '/register/registration',
                    selector: '#password',
                    text: 'Create a strong password. Minimum 8 characters, use letters and digits.',
                    position: 'bottom',
                },
                {
                    page: '/register/registration',
                    selector: '#registerBtn',
                    text: 'After filling in all fields, click the "Register" button. Done!',
                    position: 'top',
                },
            ],
        },

        guest_login: {
            name: 'How to log in',
            guest: true,
            steps: [
                {
                    page: '/register/login/',
                    selector: null,
                    text: 'Now we will show you how to log in to your account. You can log in using login, phone or email.',
                    position: 'center',
                    icon: 'ri-login-box-line',
                    navigateTo: '/register/login/',
                },
                {
                    page: '/register/login/',
                    selector: '.flex.bg-gray-100.rounded-lg',
                    fallbackSelector: 'h2',
                    text: 'Choose the login method: by login, phone number or email. Click the desired tab.',
                    position: 'bottom',
                },
                {
                    page: '/register/login/',
                    selector: '#password-login',
                    text: 'Enter the password you specified during registration and click "Log in".',
                    position: 'bottom',
                },
            ],
        },

        guest_how_to_order: {
            name: 'How to start ordering',
            guest: true,
            steps: [
                {
                    page: null,
                    selector: null,
                    text: 'Want to start ordering goods from China? Here is the procedure. Click "Next".',
                    position: 'center',
                    icon: 'ri-shopping-bag-line',
                },
                {
                    page: null,
                    selector: null,
                    text: '1. Write to the Inter Cargo manager on WhatsApp. They will tell you about tariffs, delivery conditions and answer your questions.',
                    position: 'center',
                    icon: 'ri-whatsapp-line',
                },
                {
                    page: null,
                    selector: null,
                    text: '2. Get instructions from the manager: the warehouse address in China and the order placement rules.',
                    position: 'center',
                    icon: 'ri-file-text-line',
                },
                {
                    page: null,
                    selector: null,
                    text: '3. Register on our site — this is required to track parcels and receive receipts.',
                    position: 'center',
                    icon: 'ri-user-add-line',
                },
                {
                    page: null,
                    selector: null,
                    text: '4. Place an order on a Chinese marketplace (Taobao, Pinduoduo, 1688, etc.).',
                    position: 'center',
                    icon: 'ri-global-line',
                },
                {
                    page: null,
                    selector: null,
                    text: '5. When placing the order, specify our warehouse address in China and your login from the site — this way we will identify whose parcel it is.',
                    position: 'center',
                    icon: 'ri-map-pin-line',
                },
                {
                    page: null,
                    selector: null,
                    text: '6. Add the parcel track code in your personal account. Track the delivery status — from China to your pickup point.',
                    position: 'center',
                    icon: 'ri-barcode-line',
                },
                {
                    page: null,
                    selector: null,
                    text: 'Done! When the parcel arrives at the pickup point, you will receive a notification. Come, pay and pick it up.',
                    position: 'center',
                    icon: 'ri-checkbox-circle-line',
                },
            ],
        },

        /* ─── Tutorials for ПВЗ employees ────────────────────────────────── */

        pp_acceptance_tutorial: {
            name: 'Goods acceptance',
            ppWorker: true,
            steps: [
                {
                    page: '/profile/pp-acceptance/',
                    mobile: true,
                    selector: '#mobile-menu-toggle',
                    text: 'Tap the menu icon to open the side panel.',
                    position: 'bottom',
                },
                {
                    page: '/profile/pp-acceptance/',
                    selector: 'a[href*="pp-acceptance"]',
                    selectorScope: 'sidebar',
                    text: 'Go to the "Goods acceptance" section in the side menu.',
                    position: 'right',
                    mobilePosition: 'bottom',
                    navigateTo: '/profile/pp-acceptance/',
                    beforeShow: function () { openMobileSidebar(); },
                },
                {
                    page: '/profile/pp-acceptance/',
                    selector: '.border-yellow-400',
                    fallbackSelector: 'h2',
                    text: 'Here deliveries awaiting acceptance are displayed. Each card is one delivery from a driver with a number of receipts.',
                    position: 'bottom',
                    beforeShow: function () { closeMobileSidebar(); },
                },
                {
                    page: '/profile/pp-acceptance/',
                    selector: null,
                    text: 'When the driver clicks "Start delivery" — the "Acceptance" button appears on the card. Click it to start accepting parcels.',
                    position: 'center',
                    icon: 'ri-inbox-archive-line',
                },
                {
                    page: '/profile/pp-acceptance/',
                    selector: null,
                    text: 'Scan the QR code of each receipt with a scanner or camera. The system will automatically check the receipt and mark it as accepted.',
                    position: 'center',
                    icon: 'ri-qr-code-line',
                },
                {
                    page: '/profile/pp-acceptance/',
                    selector: null,
                    text: 'After accepting all receipts, click "Finish session". The parcels will be moved to your pickup point warehouse.',
                    position: 'center',
                    icon: 'ri-checkbox-circle-line',
                },
            ],
            mobileSteps: [
                {
                    page: null,
                    selector: '[data-nav="menu"]',
                    text: 'Go to the "Menu" section in the bottom navigation.',
                    position: 'top',
                    navigateTo: '/profile/mobile-menu/',
                },
                {
                    page: '/profile/mobile-menu/',
                    selector: 'a[href*="pp-acceptance"]',
                    text: 'Tap the "Acceptance" icon in the pickup point employees section.',
                    position: 'top',
                    navigateTo: '/profile/pp-acceptance/',
                },
                {
                    page: '/profile/pp-acceptance/',
                    selector: '.border-yellow-400',
                    fallbackSelector: 'h2',
                    text: 'Here deliveries awaiting acceptance are displayed. Each card is one delivery from a driver with a number of receipts.',
                    position: 'top',
                },
                {
                    page: '/profile/pp-acceptance/',
                    selector: null,
                    text: 'When the driver clicks "Start delivery" — the "Acceptance" button appears on the card. Click it to start accepting parcels.',
                    position: 'center',
                    icon: 'ri-inbox-archive-line',
                },
                {
                    page: '/profile/pp-acceptance/',
                    selector: null,
                    text: 'Scan the QR code of each receipt with a scanner or camera. The system will automatically check the receipt and mark it as accepted.',
                    position: 'center',
                    icon: 'ri-qr-code-line',
                },
                {
                    page: '/profile/pp-acceptance/',
                    selector: null,
                    text: 'After accepting all receipts, click "Finish session". The parcels will be moved to your pickup point warehouse.',
                    position: 'center',
                    icon: 'ri-checkbox-circle-line',
                },
            ],
        },

        pp_extradition_tutorial: {
            name: 'Parcel extradition',
            ppWorker: true,
            steps: [
                {
                    page: '/profile/extradition/',
                    mobile: true,
                    selector: '#mobile-menu-toggle',
                    text: 'Tap the menu icon for navigation.',
                    position: 'bottom',
                },
                {
                    page: '/profile/extradition/',
                    selector: 'a[href*="extradition"]',
                    selectorScope: 'sidebar',
                    text: 'Go to the "Parcel extradition" section — here the issuance of parcels to clients is processed.',
                    position: 'right',
                    mobilePosition: 'bottom',
                    navigateTo: '/profile/extradition/',
                    beforeShow: function () { openMobileSidebar(); },
                },
                {
                    page: '/profile/extradition/',
                    selector: '#barcode',
                    fallbackSelector: 'h1',
                    text: 'When a client comes for parcels, scan their extradition QR code into this field. You can also enter the code manually.',
                    position: 'bottom',
                    beforeShow: function () { closeMobileSidebar(); },
                },
                {
                    page: '/profile/extradition/',
                    selector: '#scanBarcodeBtn',
                    fallbackSelector: '#searchBtn',
                    text: 'Or click this button to open the camera and scan the client's QR code.',
                    position: 'bottom',
                },
                {
                    page: '/profile/extradition/',
                    selector: null,
                    text: 'After scanning the client's QR code, the system will find their package and display information: client name, pickup point, storage cell and list of receipts with parcels.',
                    position: 'center',
                    icon: 'ri-search-line',
                },
                {
                    page: '/profile/extradition/',
                    selector: null,
                    text: 'For quick issuance, click "Issue". For verification — click "Verify and issue" to scan QR codes on each receipt.',
                    position: 'center',
                    icon: 'ri-qr-scan-2-line',
                },
                {
                    page: '/profile/extradition/',
                    selector: null,
                    text: 'In verification mode, scan the QR code of each receipt. The progress bar will show how many receipts have been checked. After checking all receipts, click "Confirm issuance".',
                    position: 'center',
                    icon: 'ri-checkbox-circle-line',
                },
                {
                    page: '/profile/extradition/',
                    selector: null,
                    text: 'After processing issuance: parcels will be marked as issued, the storage cell will become free, and the client will receive a notification.',
                    position: 'center',
                    icon: 'ri-hand-coin-line',
                },
            ],
            mobileSteps: [
                {
                    page: null,
                    selector: '[data-nav="menu"]',
                    text: 'Go to the "Menu" section in the bottom navigation.',
                    position: 'top',
                    navigateTo: '/profile/mobile-menu/',
                },
                {
                    page: '/profile/mobile-menu/',
                    selector: 'a[href*="extradition"]',
                    text: 'Tap the "Extradition" icon in the pickup point employees section.',
                    position: 'top',
                    navigateTo: '/profile/extradition/',
                },
                {
                    page: '/profile/extradition/',
                    selector: '#barcode',
                    fallbackSelector: 'h1',
                    text: 'When a client comes for parcels, scan their extradition QR code into this field. You can also enter the code manually.',
                    position: 'top',
                },
                {
                    page: '/profile/extradition/',
                    selector: '#scanBarcodeBtn',
                    fallbackSelector: '#searchBtn',
                    text: 'Or click this button to open the camera and scan the client's QR code.',
                    position: 'top',
                },
                {
                    page: '/profile/extradition/',
                    selector: null,
                    text: 'After scanning, the system will display client information: name, pickup point, storage cell and list of receipts with parcels.',
                    position: 'center',
                    icon: 'ri-search-line',
                },
                {
                    page: '/profile/extradition/',
                    selector: null,
                    text: 'For quick issuance, click "Issue". For verification — "Verify and issue" to scan QR codes on each receipt.',
                    position: 'center',
                    icon: 'ri-qr-scan-2-line',
                },
                {
                    page: '/profile/extradition/',
                    selector: null,
                    text: 'After processing: parcels are marked as issued, the cell will become free, the client will receive a notification.',
                    position: 'center',
                    icon: 'ri-hand-coin-line',
                },
            ],
        },

        pp_warehouse_tutorial: {
            name: 'Pickup point warehouse',
            ppWorker: true,
            steps: [
                {
                    page: '/profile/warehouse/',
                    selector: 'h1',
                    text: 'This is the "Pickup point warehouse" page. All cells with parcels awaiting issuance to clients are displayed here.',
                    position: 'bottom',
                    navigateTo: '/profile/warehouse/',
                },
                {
                    page: '/profile/warehouse/',
                    selector: '.w-14.h-14',
                    fallbackSelector: 'h1',
                    text: 'The cell number is displayed in a square. Click on it to change the cell number. "Floor" means cell 0.',
                    position: 'bottom',
                },
                {
                    page: '/profile/warehouse/',
                    selector: null,
                    text: 'Each cell is divided into sub-cells by receipts. This allows you to easily find specific client parcels.',
                    position: 'center',
                    icon: 'ri-layout-grid-line',
                },
                {
                    page: '/profile/warehouse/',
                    selector: 'a[href*="inventory"]',
                    fallbackSelector: 'h1',
                    text: 'The "Inventory" button creates a printable document with a list of all clients, cells and parcels in the warehouse.',
                    position: 'bottom',
                },
                {
                    page: '/profile/warehouse/',
                    selector: null,
                    text: 'Use the inventory to reconcile the actual warehouse contents with the data in the system.',
                    position: 'center',
                    icon: 'ri-file-list-3-line',
                },
            ],
            mobileSteps: [
                {
                    page: null,
                    selector: '[data-nav="menu"]',
                    text: 'Go to the "Menu" section in the bottom navigation.',
                    position: 'top',
                    navigateTo: '/profile/mobile-menu/',
                },
                {
                    page: '/profile/mobile-menu/',
                    selector: 'a[href*="warehouse"]',
                    text: 'Tap the "Pickup point warehouse" icon in the employees section.',
                    position: 'top',
                    navigateTo: '/profile/warehouse/',
                },
                {
                    page: '/profile/warehouse/',
                    selector: '.w-14.h-14',
                    fallbackSelector: 'h1',
                    text: 'All cells with parcels are displayed here. The cell number is in a square. Click to change the number. "Floor" means cell 0.',
                    position: 'top',
                },
                {
                    page: '/profile/warehouse/',
                    selector: null,
                    text: 'Each cell is divided into sub-cells by receipts. This allows you to easily find specific client parcels.',
                    position: 'center',
                    icon: 'ri-layout-grid-line',
                },
                {
                    page: '/profile/warehouse/',
                    selector: 'a[href*="inventory"]',
                    fallbackSelector: 'h1',
                    text: 'The "Inventory" button creates a printable document with a list of all clients, cells and parcels in the warehouse.',
                    position: 'top',
                },
            ],
        },

        pp_restructure_tutorial: {
            name: 'Warehouse restructuring',
            ppWorker: true,
            steps: [
                {
                    page: '/profile/warehouse/',
                    selector: 'h1',
                    text: 'Restructuring allows you to reassign all cells in the warehouse. Use it when you need to reorganize the warehouse.',
                    position: 'bottom',
                    navigateTo: '/profile/warehouse/',
                },
                {
                    page: '/profile/warehouse/',
                    selector: 'button[type="submit"]',
                    fallbackSelector: '.animate-pulse',
                    text: 'Click "Warehouse restructuring". All cell numbers will be deleted, but the parcels will remain in the system.',
                    position: 'bottom',
                },
                {
                    page: '/profile/warehouse/',
                    selector: null,
                    text: 'After clicking, the cell assignment page will open. There are 3 ways to assign cells here: manually, with a scanner or with a camera.',
                    position: 'center',
                    icon: 'ri-refresh-line',
                },
                {
                    page: '/profile/warehouse/',
                    selector: null,
                    text: 'Scanner: scan the receipt QR code — the system will find the client and assign the cell automatically.',
                    position: 'center',
                    icon: 'ri-barcode-line',
                },
                {
                    page: '/profile/warehouse/',
                    selector: null,
                    text: 'Camera: if there is no hardware scanner, open the phone camera and point it at the receipt QR code.',
                    position: 'center',
                    icon: 'ri-camera-line',
                },
                {
                    page: '/profile/warehouse/',
                    selector: null,
                    text: 'Manually: select a client from the list and specify the cell number (or leave empty for auto-assignment).',
                    position: 'center',
                    icon: 'ri-edit-line',
                },
                {
                    page: '/profile/warehouse/',
                    selector: null,
                    text: 'When all cells are assigned, click "Finish restructuring". Until completion, a blinking "Continue restructuring" button will be shown in the warehouse.',
                    position: 'center',
                    icon: 'ri-checkbox-circle-line',
                },
            ],
            mobileSteps: [
                {
                    page: null,
                    selector: '[data-nav="menu"]',
                    text: 'Go to the "Menu" section in the bottom navigation.',
                    position: 'top',
                    navigateTo: '/profile/mobile-menu/',
                },
                {
                    page: '/profile/mobile-menu/',
                    selector: 'a[href*="warehouse"]',
                    text: 'Tap the "Pickup point warehouse" icon in the employees section.',
                    position: 'top',
                    navigateTo: '/profile/warehouse/',
                },
                {
                    page: '/profile/warehouse/',
                    selector: 'button[type="submit"]',
                    fallbackSelector: '.animate-pulse',
                    text: 'Click "Warehouse restructuring". All cell numbers will be deleted, but the parcels will remain in the system.',
                    position: 'top',
                },
                {
                    page: '/profile/warehouse/',
                    selector: null,
                    text: 'The cell assignment page will open. 3 ways: manually, with a scanner or with a camera.',
                    position: 'center',
                    icon: 'ri-refresh-line',
                },
                {
                    page: '/profile/warehouse/',
                    selector: null,
                    text: 'Scanner: scan the receipt QR code — the system will find the client and assign the cell automatically.',
                    position: 'center',
                    icon: 'ri-barcode-line',
                },
                {
                    page: '/profile/warehouse/',
                    selector: null,
                    text: 'Camera: if there is no hardware scanner, open the camera and point it at the receipt QR code.',
                    position: 'center',
                    icon: 'ri-camera-line',
                },
                {
                    page: '/profile/warehouse/',
                    selector: null,
                    text: 'When all cells are assigned, click "Finish restructuring".',
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
                'cursor:pointer;font-weight:500;white-space:nowrap;">Back</button>';
        }

        if (stepIndex < totalSteps - 1) {
            var nextLabel = step.navigateTo ? 'Go' : 'Next';
            html += '<button id="tutorial-next" style="padding:' + btnPad + ';border-radius:' + btnRadius + ';' +
                'border:none;background:#ef4444;color:white;font-size:' + btnFont + ';' +
                'cursor:pointer;font-weight:500;white-space:nowrap;">' + nextLabel + '</button>';
        } else {
            html += '<button id="tutorial-finish" style="padding:' + btnPad + ';border-radius:' + btnRadius + ';' +
                'border:none;background:#16a34a;color:white;font-size:' + btnFont + ';' +
                'cursor:pointer;font-weight:500;white-space:nowrap;">Done</button>';
        }

        html += '</div></div></div></div>';
        html += '<button id="tutorial-close" style="position:absolute;top:' + closeTop + ';right:' + closeRight + ';' +
            'background:none;border:none;font-size:' + closeSize + ';color:#9ca3af;cursor:pointer;' +
            'line-height:1;" title="Close">&times;</button>';

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
            'Site tutorials</h3>' +
            '<button id="tutorial-menu-close" style="background:none;border:none;font-size:22px;' +
            'color:#9ca3af;cursor:pointer;line-height:1;">&times;</button></div>' +
            '<p style="color:#6b7280;font-size:' + descSize + ';margin-bottom:16px;">' +
            'Select a topic for interactive tutorial:</p>' +
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
                    '<span style="font-size:11px;color:#9ca3af;white-space:nowrap;">For pickup point employees</span>' +
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
        if (!tutorial) return 'Tutorial not found.';
        var mobile = isMobile();
        var steps = getEffectiveSteps(tutorial);
        if (!steps || steps.length === 0) return 'No available steps for this tutorial.';

        // On mobile, check that bottom navigation exists (for authenticated tutorials)
        if (mobile && !tutorial.guest) {
            var bottomNav = document.getElementById('mobile-bottom-nav');
            if (!bottomNav) return 'Mobile navigation not found. Please refresh the page.';
        }

        // Check that the first step's page is valid
        var firstStep = steps[0];
        if (firstStep.selector && !firstStep.page) {
            var el = document.querySelector(firstStep.selector);
            if (!el && !firstStep.fallbackSelector) {
                return 'The interface element for the first step was not found. Try refreshing the page.';
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
