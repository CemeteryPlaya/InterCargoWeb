document.addEventListener('DOMContentLoaded', () => {
  const weightInput = document.getElementById('weight');
  const inc = document.getElementById('increment');
  const dec = document.getElementById('decrement');
  const totalWeight = document.getElementById('total-weight');
  const totalPrice = document.getElementById('total-price');
  const RATE = 1859;

  if (!weightInput) return;

  const update = () => {
    const w = parseFloat(weightInput.value) || 0;
    const p = w * RATE;
    totalWeight.textContent = `${w} кг`;
    totalPrice.textContent = `${p.toLocaleString()} ₸`;
  };

  weightInput.addEventListener('input', update);
  inc?.addEventListener('click', () => {
    let w = parseFloat(weightInput.value) || 0;
    if (w < 100) weightInput.value = w + 1;
    update();
  });
  dec?.addEventListener('click', () => {
    let w = parseFloat(weightInput.value) || 0;
    if (w > 0) weightInput.value = w - 1;
    update();
  });
});