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
            'position:fixed;z-index:10001;max-width:380px;width:calc(100vw - 32px);' +
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

        // Position the tooltip relative to element
        if (!el || pos === 'center') {
            tooltip.style.top = '50%';
            tooltip.style.left = '50%';
            tooltip.style.transform = 'translate(-50%, -50%)';
            tooltip.style.right = '';
            tooltip.style.bottom = '';
            return;
        }

        tooltip.style.transform = '';
        var rect = el.getBoundingClientRect();
        var pad = 16;

        // Reset
        tooltip.style.top = '';
        tooltip.style.left = '';
        tooltip.style.right = '';
        tooltip.style.bottom = '';

        if (pos === 'bottom') {
            tooltip.style.top = (rect.bottom + pad) + 'px';
            tooltip.style.left = Math.max(16, Math.min(rect.left, window.innerWidth - 396)) + 'px';
        } else if (pos === 'top') {
            tooltip.style.bottom = (window.innerHeight - rect.top + pad) + 'px';
            tooltip.style.left = Math.max(16, Math.min(rect.left, window.innerWidth - 396)) + 'px';
        } else if (pos === 'right') {
            tooltip.style.top = Math.max(16, rect.top) + 'px';
            tooltip.style.left = (rect.right + pad) + 'px';
            // If goes off-screen, fallback to bottom
            if (rect.right + pad + 380 > window.innerWidth) {
                tooltip.style.top = (rect.bottom + pad) + 'px';
                tooltip.style.left = Math.max(16, Math.min(rect.left, window.innerWidth - 396)) + 'px';
            }
        } else if (pos === 'left') {
            tooltip.style.top = Math.max(16, rect.top) + 'px';
            tooltip.style.right = (window.innerWidth - rect.left + pad) + 'px';
            tooltip.style.left = '';
            if (rect.left - pad - 380 < 0) {
                tooltip.style.right = '';
                tooltip.style.top = (rect.bottom + pad) + 'px';
                tooltip.style.left = '16px';
            }
        }

        // After render, check if tooltip is off-screen and adjust
        requestAnimationFrame(function () {
            if (!tooltip) return;
            var tr = tooltip.getBoundingClientRect();
            // If tooltip goes below viewport, try placing above
            if (tr.bottom > window.innerHeight - 10 && pos !== 'top') {
                tooltip.style.top = '';
                tooltip.style.bottom = (window.innerHeight - rect.top + pad) + 'px';
            }
            // If goes above, place below
            if (tr.top < 10 && pos !== 'bottom') {
                tooltip.style.bottom = '';
                tooltip.style.top = (rect.bottom + pad) + 'px';
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

        var tutorials = [
            { id: 'add_track', icon: 'ri-add-circle-line', color: '#16a34a' },
            { id: 'view_receipts', icon: 'ri-bill-line', color: '#2563eb' },
            { id: 'receive_parcels', icon: 'ri-hand-coin-line', color: '#ea580c' },
        ];

        tutorials.forEach(function (t) {
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
