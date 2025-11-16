document.addEventListener('DOMContentLoaded', () => {
  const faqToggles = document.querySelectorAll('.faq-toggle');

  faqToggles.forEach(toggle => {
    toggle.addEventListener('click', function () {
      const targetId = this.getAttribute('data-target');
      const content = document.getElementById(targetId);
      const icon = this.querySelector('i');

      // 🧠 Защита от ошибок:
      if (!targetId) {
        console.warn(`[faq.js] Кнопка без data-target:`, this);
        return;
      }
      if (!content) {
        console.warn(`[faq.js] Не найден элемент с id="${targetId}"`);
        return;
      }

      // ✅ Если всё в порядке — выполняем
      content.classList.toggle('hidden');
      if (icon) {
        icon.classList.toggle('ri-arrow-down-s-line');
        icon.classList.toggle('ri-arrow-up-s-line');
      }
    });
  });
});
