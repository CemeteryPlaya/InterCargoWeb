document.addEventListener('DOMContentLoaded', function () {
    document.getElementById('select_all_pickups').addEventListener('change', function () {
        const checkboxes = document.querySelectorAll('.pickup-checkbox');
        checkboxes.forEach(cb => cb.checked = this.checked);
    });

    document.getElementById('select_all_pickups_checks').addEventListener('change', function () {
        const checkboxes = document.querySelectorAll('.pickup-check-checkbox');
        checkboxes.forEach(cb => cb.checked = this.checked);
    });
});
