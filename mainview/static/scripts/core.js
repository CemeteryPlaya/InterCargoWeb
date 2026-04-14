// Синхронная инициализация темы ДО рендера body — предотвращает "мигание" светлой темой.
// Выполняется в <head> до парсинга body, что гарантирует отсутствие вспышки белого фона
// на первом кадре новой страницы (особенно при переходах между вкладками).
(function () {
  try {
    var saved = localStorage.getItem('theme');
    var isDark = saved === 'dark';
    var html = document.documentElement;
    if (isDark) {
      html.classList.add('theme-dark');
      // Inline-стили применяются мгновенно, не дожидаясь загрузки styles.css.
      html.style.backgroundColor = '#020617';
      html.style.colorScheme = 'dark';
      // Inject inline <style>, чтобы перекрыть tailwind-утилиты (bg-gray-50, bg-white)
      // на body ещё до первой отрисовки — иначе tailwind CDN успевает применить белый фон.
      var s = document.createElement('style');
      s.id = 'ic-theme-preload';
      s.textContent =
        'html.theme-dark,html.theme-dark body{background-color:#020617 !important;color:#e5e7eb;}' +
        'html.theme-dark body.bg-gray-50,html.theme-dark .bg-gray-50,' +
        'html.theme-dark .bg-white,html.theme-dark .bg-gray-100{background-color:#020617 !important;}';
      // document.head доступен сразу, т.к. скрипт исполняется внутри <head>.
      (document.head || document.documentElement).appendChild(s);
    } else {
      html.classList.remove('theme-dark');
    }
  } catch (e) { /* localStorage недоступен — игнорируем */ }
})();

document.addEventListener('DOMContentLoaded', () => {
  console.log('[core.js] DOM fully loaded.');

  const root = document.body;
  const THEME_KEY = 'theme';

  // Синхронизируем класс с <html> на <body> сразу после появления body,
  // чтобы существующие CSS-правила body.theme-dark применились без задержки.
  if (document.documentElement.classList.contains('theme-dark')) {
    root.classList.add('theme-dark');
  }

  function applyTheme(theme) {
    if (theme === 'dark') {
      root.classList.add('theme-dark');
      document.documentElement.classList.add('theme-dark');
    } else {
      root.classList.remove('theme-dark');
      document.documentElement.classList.remove('theme-dark');
    }
    updateToggleIcon(theme);
  }

  function getPreferredTheme() {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === 'light' || saved === 'dark') {
      return saved;
    }
    // По умолчанию светлая тема
    return 'light';
  }

  function updateToggleIcon(theme) {
    const icon = document.getElementById('theme-toggle-icon');
    const button = document.getElementById('theme-toggle');
    if (icon && button) {
      if (theme === 'dark') {
        icon.classList.remove('ri-moon-line');
        icon.classList.add('ri-sun-line');
        button.setAttribute('aria-label', 'Переключить на светлую тему');
      } else {
        icon.classList.remove('ri-sun-line');
        icon.classList.add('ri-moon-line');
        button.setAttribute('aria-label', 'Переключить на тёмную тему');
      }
    }
    // Мобильная кнопка темы
    const mobileIcon = document.getElementById('mobile-theme-icon');
    if (mobileIcon) {
      if (theme === 'dark') {
        mobileIcon.classList.remove('ri-moon-line');
        mobileIcon.classList.add('ri-sun-line');
      } else {
        mobileIcon.classList.remove('ri-sun-line');
        mobileIcon.classList.add('ri-moon-line');
      }
    }
  }

  // Инициализация темы при загрузке
  const initialTheme = getPreferredTheme();
  applyTheme(initialTheme);

  // === Анимация спирали при смене темы ===
  function animateThemeTransition(originEl, nextTheme, callback) {
    // Получаем позицию кнопки-источника
    var rect = originEl.getBoundingClientRect();
    var cx = rect.left + rect.width / 2;
    var cy = rect.top + rect.height / 2;

    // Максимальный радиус — от кнопки до самого дальнего угла
    var maxR = Math.ceil(Math.sqrt(
      Math.max(cx, window.innerWidth - cx) ** 2 +
      Math.max(cy, window.innerHeight - cy) ** 2
    ));

    // Создаём оверлей
    var overlay = document.createElement('div');
    overlay.style.cssText =
      'position:fixed;inset:0;z-index:99998;pointer-events:none;' +
      'background:' + (nextTheme === 'dark' ? '#1a1a2e' : '#ffffff') + ';' +
      'clip-path:circle(0px at ' + cx + 'px ' + cy + 'px);' +
      'transition:clip-path 0.6s cubic-bezier(0.4,0,0.2,1);';
    document.body.appendChild(overlay);

    // Форсируем reflow, затем запускаем анимацию
    overlay.offsetHeight;
    overlay.style.clipPath = 'circle(' + maxR + 'px at ' + cx + 'px ' + cy + 'px)';

    overlay.addEventListener('transitionend', function() {
      callback();
      // Плавно убираем оверлей
      overlay.style.transition = 'opacity 0.2s ease';
      overlay.style.opacity = '0';
      setTimeout(function() { overlay.remove(); }, 200);
    }, { once: true });
  }

  function toggleThemeWithAnimation(originEl) {
    var current = root.classList.contains('theme-dark') ? 'dark' : 'light';
    var next = current === 'dark' ? 'light' : 'dark';

    // Координаты центра кнопки + максимальный радиус до угла экрана
    var rect = originEl.getBoundingClientRect();
    var cx = rect.left + rect.width / 2;
    var cy = rect.top + rect.height / 2;
    var maxR = Math.ceil(Math.sqrt(
      Math.max(cx, window.innerWidth - cx) ** 2 +
      Math.max(cy, window.innerHeight - cy) ** 2
    ));

    // Передаём координаты в CSS — анимация ::view-transition их использует
    document.documentElement.style.setProperty('--theme-anim-x', cx + 'px');
    document.documentElement.style.setProperty('--theme-anim-y', cy + 'px');
    document.documentElement.style.setProperty('--theme-anim-r', maxR + 'px');

    // Современный путь: View Transitions API — снапшотит контент,
    // иконки и фото остаются на местах, тема "наезжает" сверху кругом
    if (typeof document.startViewTransition === 'function') {
      document.startViewTransition(function() {
        localStorage.setItem(THEME_KEY, next);
        applyTheme(next);
      });
      return;
    }

    // Фолбэк для старых браузеров — прежний overlay
    animateThemeTransition(originEl, next, function() {
      localStorage.setItem(THEME_KEY, next);
      applyTheme(next);
    });
  }

  // Обработчик кнопки переключения темы (header)
  const toggleBtn = document.getElementById('theme-toggle');
  if (toggleBtn) {
    toggleBtn.addEventListener('click', function() {
      toggleThemeWithAnimation(toggleBtn);
    });
  }

  // Обработчик мобильной кнопки темы
  const mobileThemeBtn = document.getElementById('mobile-theme-btn');
  if (mobileThemeBtn) {
    mobileThemeBtn.addEventListener('click', function() {
      toggleThemeWithAnimation(mobileThemeBtn);
    });
  }

  // Реакция на системное изменение темы, если пользователь явно не выбирал
  if (!localStorage.getItem(THEME_KEY) && window.matchMedia) {
    window
      .matchMedia('(prefers-color-scheme: dark)')
      .addEventListener('change', (e) => {
        applyTheme(e.matches ? 'dark' : 'light');
      });
  }

  // === Анимация загрузки при переходах между страницами ===
  (function () {
    // Создаём overlay
    var overlay = document.createElement('div');
    overlay.id = 'ic-loading-overlay';
    overlay.innerHTML =
      '<div class="ic-loading-spinner">' +
      '<div class="ic-spinner-ring"></div>' +
      '<span>Загрузка...</span>' +
      '</div>';
    document.body.appendChild(overlay);

    // Добавляем стили
    var style = document.createElement('style');
    style.textContent =
      '#ic-loading-overlay{position:fixed;inset:0;z-index:99999;display:none;align-items:center;justify-content:center;background:rgba(255,255,255,.7);backdrop-filter:blur(2px);transition:opacity .2s}' +
      '#ic-loading-overlay.active{display:flex}' +
      '.ic-loading-spinner{display:flex;flex-direction:column;align-items:center;gap:12px}' +
      '.ic-loading-spinner span{font-size:14px;color:#6b7280;font-family:Arial,sans-serif}' +
      '.ic-spinner-ring{width:40px;height:40px;border:4px solid #e5e7eb;border-top-color:#ef4444;border-radius:50%;animation:ic-spin .8s linear infinite}' +
      '@keyframes ic-spin{to{transform:rotate(360deg)}}';
    document.head.appendChild(style);

    var timer = null;
    var DELAY = 1500; // показываем только если дольше 1.5с

    function showLoader() {
      timer = setTimeout(function () {
        overlay.classList.add('active');
      }, DELAY);
    }

    function hideLoader() {
      if (timer) { clearTimeout(timer); timer = null; }
      overlay.classList.remove('active');
    }

    // Перехват кликов по ссылкам (переходы между страницами)
    document.addEventListener('click', function (e) {
      var link = e.target.closest('a[href]');
      if (!link) return;
      var href = link.getAttribute('href');
      // Пропускаем: якоря, javascript:, внешние ссылки, target=_blank, скачивание
      if (!href || href.startsWith('#') || href.startsWith('javascript:') ||
          link.target === '_blank' || link.hasAttribute('download') ||
          href.startsWith('http') && !href.startsWith(location.origin)) return;
      showLoader();
    });

    // Перехват отправки форм (кроме AJAX-форм с data-ajax)
    document.addEventListener('submit', function (e) {
      if (e.target.dataset.ajax !== undefined) return;
      showLoader();
    });

    // Скрываем при загрузке страницы (если вернулись по back/forward)
    window.addEventListener('pageshow', hideLoader);
  })();
});