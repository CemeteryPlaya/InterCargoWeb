document.addEventListener('DOMContentLoaded', () => {
  const phoneInput = document.getElementById('phone');
  if (!phoneInput) return;

  const formatPhone = (value) => {
    const digits = value.replace(/\D/g, '');
    let cleaned = digits.startsWith('7') ? digits : '7' + digits;
    cleaned = cleaned.slice(0, 11);

    let result = '+7';
    if (cleaned.length > 1) result += ' (' + cleaned.substring(1, 4);
    if (cleaned.length >= 4) result += ') ' + cleaned.substring(4, 7);
    if (cleaned.length >= 7) result += '-' + cleaned.substring(7, 9);
    if (cleaned.length >= 9) result += '-' + cleaned.substring(9, 11);
    return result;
  };

  phoneInput.addEventListener('input', e => {
    phoneInput.value = formatPhone(e.target.value);
  });

  phoneInput.addEventListener('paste', e => {
    e.preventDefault();
    const pasted = (e.clipboardData || window.clipboardData).getData('text');
    phoneInput.value = formatPhone(pasted);
  });
});