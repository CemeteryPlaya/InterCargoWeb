/**
 * settings.html — notification level selector.
 * Toggles visibility of "Выборочно" options and highlights the active radio.
 */
function toggleSelective(radio) {
    const opts = document.getElementById('selective-options');
    if (opts) {
        opts.classList.toggle('hidden', radio.value !== 'selective');
    }
    document.querySelectorAll('input[name="notif_level"]').forEach(r => {
        const label = r.closest('label');
        if (!label) return;
        if (r.checked) {
            label.classList.add('border-red-400', 'bg-red-50');
            label.classList.remove('border-gray-200');
        } else {
            label.classList.remove('border-red-400', 'bg-red-50');
            label.classList.add('border-gray-200');
        }
    });
}
