document.addEventListener('DOMContentLoaded', () => {
  const btn = document.getElementById('notification-button');
  const drop = document.getElementById('notification-dropdown');
  if (!btn || !drop) return;

  btn.addEventListener('click', e => {
    e.stopPropagation();
    drop.classList.toggle('hidden');
  });

  window.addEventListener('click', e => {
    if (!drop.contains(e.target) && !btn.contains(e.target)) {
      drop.classList.add('hidden');
    }
  });

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') drop.classList.add('hidden');
  });
});