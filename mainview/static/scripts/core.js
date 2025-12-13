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
});