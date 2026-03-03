document.addEventListener('DOMContentLoaded', () => {
  const weightInput = document.getElementById('weight');
  const inc = document.getElementById('increment');
  const dec = document.getElementById('decrement');
  const totalWeight = document.getElementById('total-weight');
  const totalPrice = document.getElementById('total-price');
  const discountEl = document.getElementById('discount');
  const RATE = parseInt(weightInput.dataset.rate) || 1859;

  if (!weightInput) return;

  weightInput.addEventListener('input', () => {
    // Заменяем запятую на точку
    var val = weightInput.value.replace(',', '.');
    // Убираем всё кроме цифр и первой точки
    var parts = val.split('.');
    var integer = parts[0].replace(/[^0-9]/g, '');
    if (integer.length > 3) integer = integer.slice(0, 3);
    if (parts.length > 1) {
      var decimal = parts.slice(1).join('').replace(/[^0-9]/g, '');
      if (decimal.length > 3) decimal = decimal.slice(0, 3);
      val = integer + '.' + decimal;
    } else {
      val = integer;
    }
    weightInput.value = val;
    update();
  });

  weightInput.addEventListener('keydown', (e) => {
    var allowedKeys = ['Backspace', 'Delete', 'ArrowLeft', 'ArrowRight', 'Tab', 'Home', 'End'];
    if (allowedKeys.indexOf(e.key) !== -1) return;
    // Разрешаем точку и запятую (один раз)
    if (e.key === '.' || e.key === ',') {
      if (weightInput.value.indexOf('.') !== -1) {
        e.preventDefault();
      }
      return;
    }
    // Блокируем нецифровые символы
    if (!/^\d$/.test(e.key)) {
      e.preventDefault();
      return;
    }
    // Проверяем лимит цифр после точки (3) и до точки (3)
    var val = weightInput.value;
    var dotIdx = val.indexOf('.');
    var selStart = weightInput.selectionStart;
    if (dotIdx !== -1) {
      if (selStart > dotIdx) {
        var decPart = val.slice(dotIdx + 1);
        if (decPart.length >= 3) e.preventDefault();
      } else {
        var intPart = val.slice(0, dotIdx);
        if (intPart.length >= 3) e.preventDefault();
      }
    } else {
      if (val.replace(/[^0-9]/g, '').length >= 3) e.preventDefault();
    }
  });

  const update = () => {
    const w = parseFloat(weightInput.value) || 0;
    const price = w * RATE;

    totalWeight.textContent = `${w.toLocaleString('ru-RU', {maximumFractionDigits: 3})} кг`;
    totalPrice.textContent = `${Math.round(price).toLocaleString()} ₸`;

    if (w >= 30) {
      const discountAmount = price - (w * 10);
      document.getElementById('discount-amount').textContent = `${Math.round(discountAmount).toLocaleString()} ₸`;
      discountEl.style.visibility = 'visible';
    } else {
      discountEl.style.visibility = 'hidden';
    }
  };

  inc?.addEventListener('click', () => {
    let w = parseFloat(weightInput.value) || 0;
    if (w < 100) weightInput.value = Math.min(100, w + 1);
    update();
  });
  dec?.addEventListener('click', () => {
    let w = parseFloat(weightInput.value) || 0;
    if (w > 0) weightInput.value = Math.max(0, w - 1);
    update();
  });
});
