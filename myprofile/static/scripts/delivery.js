document.addEventListener('DOMContentLoaded', function () {
    // Tab switching
    var tabButtons = document.querySelectorAll('.tab-delivery-btn');
    var tabPanels = document.querySelectorAll('.tab-delivery-panel');

    tabButtons.forEach(function (btn) {
        btn.addEventListener('click', function () {
            var targetTab = this.dataset.tab;

            // Update button styles
            tabButtons.forEach(function (b) {
                b.classList.remove('border-primary', 'text-primary');
                b.classList.add('border-transparent', 'text-gray-500');
            });
            this.classList.remove('border-transparent', 'text-gray-500');
            this.classList.add('border-primary', 'text-primary');

            // Show/hide panels
            tabPanels.forEach(function (panel) {
                panel.classList.add('hidden');
            });
            document.getElementById('panel-' + targetTab).classList.remove('hidden');
        });
    });

    // Select all buttons
    var selectAllTake = document.getElementById('select-all-take');
    if (selectAllTake) {
        selectAllTake.addEventListener('click', function () {
            var panel = document.getElementById('panel-take');
            var checkboxes = panel.querySelectorAll('input[type="checkbox"]');
            var allChecked = Array.from(checkboxes).every(function (cb) { return cb.checked; });
            checkboxes.forEach(function (cb) { cb.checked = !allChecked; });
            this.textContent = allChecked ? 'Выбрать все' : 'Снять все';
        });
    }

    var selectAllComplete = document.getElementById('select-all-complete');
    if (selectAllComplete) {
        selectAllComplete.addEventListener('click', function () {
            var panel = document.getElementById('panel-complete');
            var checkboxes = panel.querySelectorAll('input[type="checkbox"]');
            var allChecked = Array.from(checkboxes).every(function (cb) { return cb.checked; });
            checkboxes.forEach(function (cb) { cb.checked = !allChecked; });
            this.textContent = allChecked ? 'Выбрать все' : 'Снять все';
        });
    }
});
