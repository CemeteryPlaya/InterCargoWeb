document.addEventListener('DOMContentLoaded', () => {
  const weightInput = document.getElementById('weight');
  const inc = document.getElementById('increment');
  const dec = document.getElementById('decrement');
  const totalWeight = document.getElementById('total-weight');
  const totalPrice = document.getElementById('total-price');
  const discountEl = document.getElementById('discount');
  const RATE = parseInt(weightInput.dataset.rate) || 1859;

  if (!weightInput) return;

  // Вся очистка ввода идёт через событие input — оно надёжно
  // срабатывает и на десктопе, и на мобильных виртуальных клавиатурах
  // (в отличие от keydown, где e.key === "Unidentified" на Android/GBoard
  // и точку/запятую невозможно отловить).
  weightInput.addEventListener('input', () => {
    // Заменяем запятую на точку и убираем всё, кроме цифр и точек
    var val = weightInput.value.replace(',', '.').replace(/[^0-9.]/g, '');
    // Оставляем только первую точку
    var firstDot = val.indexOf('.');
    if (firstDot !== -1) {
      val = val.slice(0, firstDot + 1) + val.slice(firstDot + 1).replace(/\./g, '');
    }
    var parts = val.split('.');
    var integer = parts[0].slice(0, 3);
    if (parts.length > 1) {
      // Сохраняем «висящую» точку: "0." остаётся "0.",
      // чтобы можно было продолжить ввод дробной части
      var decimal = parts[1].slice(0, 3);
      val = integer + '.' + decimal;
    } else {
      val = integer;
    }
    weightInput.value = val;
    update();
  });

  const update = () => {
    const w = parseFloat(weightInput.value) || 0;
    const price = w * RATE;

    totalWeight.textContent = `${w.toLocaleString('ru-RU', {maximumFractionDigits: 3})} кг`;
    totalPrice.textContent = `${Math.round(price).toLocaleString()} ₸`;

    if (w >= 30) {
      const discountAmount = price - (w * 10);
      document.getElementById('discount-amount').textContent = `${Math.round(discountAmount).toLocaleString()} ₸`;
      discountEl.classList.add('is-visible');
    } else {
      discountEl.classList.remove('is-visible');
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
