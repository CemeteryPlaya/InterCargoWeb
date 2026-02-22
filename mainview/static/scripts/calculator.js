document.addEventListener('DOMContentLoaded', () => {
  const weightInput = document.getElementById('weight');
  const inc = document.getElementById('increment');
  const dec = document.getElementById('decrement');
  const totalWeight = document.getElementById('total-weight');
  const totalPrice = document.getElementById('total-price');
  const discountEl = document.getElementById('discount');
  const RATE = parseInt(weightInput.dataset.rate) || 1859;
  const MAX_DIGITS = 6;

  if (!weightInput) return;

  // Limit input to MAX_DIGITS digits
  weightInput.addEventListener('input', () => {
    var val = weightInput.value.replace(/[^0-9]/g, '');
    if (val.length > MAX_DIGITS) {
      val = val.slice(0, MAX_DIGITS);
    }
    weightInput.value = val;
    update();
  });

  weightInput.addEventListener('keydown', (e) => {
    var val = weightInput.value.replace(/[^0-9]/g, '');
    // Allow control keys (backspace, delete, arrows, tab)
    var allowedKeys = ['Backspace', 'Delete', 'ArrowLeft', 'ArrowRight', 'Tab', 'Home', 'End'];
    if (allowedKeys.indexOf(e.key) !== -1) return;
    // Block non-digit keys
    if (!/^\d$/.test(e.key)) {
      e.preventDefault();
      return;
    }
    // Block if already at max digits
    if (val.length >= MAX_DIGITS) {
      e.preventDefault();
    }
  });

  const update = () => {
    const w = parseFloat(weightInput.value) || 0;
    const price = w * RATE;

    totalWeight.textContent = `${w.toLocaleString()} кг`;
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
    var maxVal = parseInt('9'.repeat(MAX_DIGITS));
    if (w < maxVal) weightInput.value = w + 1;
    update();
  });
  dec?.addEventListener('click', () => {
    let w = parseFloat(weightInput.value) || 0;
    if (w > 0) weightInput.value = w - 1;
    update();
  });
});
