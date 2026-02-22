document.addEventListener('DOMContentLoaded', function () {
  var phoneInputs = document.querySelectorAll('input[name="phone"], input[type="tel"]');

  phoneInputs.forEach(function (phoneInput) {
    // Инициализация: если пустое — вставляем +7
    if (!phoneInput.value || phoneInput.value.trim() === '') {
      phoneInput.value = '+7';
    }

    function formatPhone(value) {
      // Извлекаем только цифры
      var digits = value.replace(/\D/g, '');
      // Всегда начинаем с 7
      if (!digits || digits.charAt(0) !== '7') {
        digits = '7' + digits.replace(/^[78]/, '');
      }
      digits = digits.slice(0, 11);

      var result = '+7';
      if (digits.length > 1) result += ' (' + digits.substring(1, Math.min(4, digits.length));
      if (digits.length >= 4) result += ') ' + digits.substring(4, Math.min(7, digits.length));
      if (digits.length >= 7) result += '-' + digits.substring(7, Math.min(9, digits.length));
      if (digits.length >= 9) result += '-' + digits.substring(9, 11);
      return result;
    }

    function getDigitCount(value) {
      return value.replace(/\D/g, '').length;
    }

    phoneInput.addEventListener('input', function () {
      var pos = this.selectionStart;
      var oldLen = this.value.length;
      this.value = formatPhone(this.value);
      var newLen = this.value.length;
      // Корректируем позицию курсора
      var newPos = pos + (newLen - oldLen);
      if (newPos < 2) newPos = 2;
      this.setSelectionRange(newPos, newPos);
    });

    phoneInput.addEventListener('keydown', function (e) {
      // Не даём удалить +7
      if (e.key === 'Backspace') {
        var pos = this.selectionStart;
        var selEnd = this.selectionEnd;

        // Если курсор в начале или выделение включает +7 — блокируем
        if (pos <= 2 && selEnd <= 2) {
          e.preventDefault();
          return;
        }

        // Если выделен весь текст — оставляем только +7
        if (pos === 0 && selEnd === this.value.length) {
          e.preventDefault();
          this.value = '+7';
          this.setSelectionRange(2, 2);
          return;
        }

        // Если символ перед курсором — форматирующий (скобка, пробел, дефис)
        if (pos > 2 && selEnd === pos) {
          var charBefore = this.value.charAt(pos - 1);
          if (' ()-'.indexOf(charBefore) !== -1) {
            // Пропускаем форматирующие символы — удаляем до предыдущей цифры
            e.preventDefault();
            var digits = this.value.replace(/\D/g, '');
            // Находим какую цифру удаляем: считаем цифры до позиции pos
            var digitsBefore = this.value.substring(0, pos).replace(/\D/g, '').length;
            // Удаляем последнюю цифру перед позицией
            if (digitsBefore > 1) { // не удаляем 7
              var newDigits = digits.substring(0, digitsBefore - 1) + digits.substring(digitsBefore);
              this.value = formatPhone(newDigits);
              // Ставим курсор
              var newPos = 0;
              var count = 0;
              for (var i = 0; i < this.value.length; i++) {
                if (/\d/.test(this.value.charAt(i))) count++;
                if (count === digitsBefore - 1) { newPos = i + 1; break; }
              }
              this.setSelectionRange(newPos, newPos);
            }
            return;
          }
        }
      }

      // Не даём стрелку влево уйти до +7
      if (e.key === 'ArrowLeft' && this.selectionStart <= 2) {
        e.preventDefault();
      }

      // Home — ставим на позицию 2, не 0
      if (e.key === 'Home') {
        e.preventDefault();
        this.setSelectionRange(2, 2);
      }
    });

    // Клик — не даём поставить курсор до +7
    phoneInput.addEventListener('click', function () {
      if (this.selectionStart < 2) {
        this.setSelectionRange(2, 2);
      }
    });

    phoneInput.addEventListener('focus', function () {
      if (!this.value || this.value.length < 2) {
        this.value = '+7';
      }
      var self = this;
      setTimeout(function () {
        if (self.selectionStart < 2) {
          self.setSelectionRange(2, 2);
        }
      }, 0);
    });

    phoneInput.addEventListener('paste', function (e) {
      e.preventDefault();
      var pasted = (e.clipboardData || window.clipboardData).getData('text');
      this.value = formatPhone(pasted);
    });

    // Валидация при отправке формы
    var form = phoneInput.closest('form');
    if (form) {
      form.addEventListener('submit', function (e) {
        var digits = phoneInput.value.replace(/\D/g, '');
        if (digits.length < 11) {
          e.preventDefault();
          phoneInput.classList.add('border-red-500');
          // Ищем или создаём сообщение об ошибке
          var errorMsg = phoneInput.parentElement.querySelector('.phone-error');
          if (!errorMsg) {
            errorMsg = document.createElement('div');
            errorMsg.className = 'phone-error text-xs text-red-600 mt-1';
            phoneInput.parentElement.appendChild(errorMsg);
          }
          errorMsg.textContent = 'Введите номер полностью: +7 (XXX) XXX-XX-XX';
          phoneInput.focus();
        } else {
          phoneInput.classList.remove('border-red-500');
          var errorMsg = phoneInput.parentElement.querySelector('.phone-error');
          if (errorMsg) errorMsg.remove();
        }
      });
    }
  });
});
