document.addEventListener('DOMContentLoaded', () => {
  const faqToggles = document.querySelectorAll('.faq-toggle');

  faqToggles.forEach(toggle => {
    toggle.addEventListener('click', function () {
      const targetId = this.getAttribute('data-target');
      const content = document.getElementById(targetId);
      const icon = this.querySelector('i');

      if (!targetId) {
        console.warn('[faq.js] Кнопка без data-target:', this);
        return;
      }
      if (!content) {
        console.warn(`[faq.js] Не найден элемент с id="${targetId}"`);
        return;
      }

      const isOpen = content.classList.contains('open');

      if (isOpen) {
        // Закрываем: сначала фиксируем текущую высоту, затем 0
        content.style.maxHeight = content.scrollHeight + 'px';
        // форсируем reflow, чтобы анимация сработала
        content.offsetHeight;
        content.style.maxHeight = '0px';
        content.classList.remove('open');
        if (icon) icon.classList.remove('rotate');
      } else {
        // Открываем: max-height до scrollHeight, потом auto после анимации
        content.classList.add('open');
        content.style.maxHeight = content.scrollHeight + 'px';
        if (icon) icon.classList.add('rotate');

        // После анимации убираем фиксированный max-height,
        // чтобы контент мог расти (например, при ресайзе)
        const onEnd = function (e) {
          if (e.propertyName !== 'max-height') return;
          if (content.classList.contains('open')) {
            content.style.maxHeight = 'none';
          }
          content.removeEventListener('transitionend', onEnd);
        };
        content.addEventListener('transitionend', onEnd);
      }
    });
  });
});
