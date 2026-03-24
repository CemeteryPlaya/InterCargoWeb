document.addEventListener('DOMContentLoaded', () => {
  console.log('[core.js] DOM fully loaded.');

  const root = document.body;
  const THEME_KEY = 'theme';

  function applyTheme(theme) {
    if (theme === 'dark') {
      root.classList.add('theme-dark');
    } else {
      root.classList.remove('theme-dark');
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
    if (!icon || !button) return;

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

  // Инициализация темы при загрузке
  const initialTheme = getPreferredTheme();
  applyTheme(initialTheme);

  // Обработчик кнопки переключения темы
  const toggleBtn = document.getElementById('theme-toggle');
  if (toggleBtn) {
    toggleBtn.addEventListener('click', () => {
      const current = root.classList.contains('theme-dark') ? 'dark' : 'light';
      const next = current === 'dark' ? 'light' : 'dark';
      localStorage.setItem(THEME_KEY, next);
      applyTheme(next);
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

    // Перехват отправки форм
    document.addEventListener('submit', function () {
      showLoader();
    });

    // Скрываем при загрузке страницы (если вернулись по back/forward)
    window.addEventListener('pageshow', hideLoader);
  })();
});