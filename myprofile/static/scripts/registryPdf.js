function removeClient(element) {
    if (!confirm('Удалить клиента из этого списка?')) return;

    var row = element.closest('tr');
    var tbody = row.parentElement;

    row.remove();
    recalculateTableTotals(tbody);
    recalculateGrandTotals();
}

function recalculateTableTotals(tbody) {
    var totalCount = 0;
    var totalWeight = 0;
    var totalSum = 0;

    var rows = tbody.querySelectorAll('.client-row');
    rows.forEach(function (row) {
        var count = parseFloat(row.getAttribute('data-count')) || 0;
        var weight = parseFloat(row.getAttribute('data-weight').replace(',', '.')) || 0;
        var sum = parseFloat(row.getAttribute('data-sum').replace(',', '.')) || 0;

        totalCount += count;
        totalWeight += weight;
        totalSum += sum;
    });

    var totalsRow = tbody.querySelector('.totals-row');
    if (totalsRow) {
        totalsRow.cells[1].textContent = totalCount;
        totalsRow.cells[2].textContent = totalWeight.toFixed(3).replace('.', ',');
        totalsRow.cells[3].textContent = totalSum.toFixed(0);
    }
}

function recalculateGrandTotals() {
    var grandCount = 0;
    var grandWeight = 0;
    var grandSum = 0;

    var allRows = document.querySelectorAll('.client-row');
    allRows.forEach(function (row) {
        var count = parseFloat(row.getAttribute('data-count')) || 0;
        var weight = parseFloat(row.getAttribute('data-weight').replace(',', '.')) || 0;
        var sum = parseFloat(row.getAttribute('data-sum').replace(',', '.')) || 0;

        grandCount += count;
        grandWeight += weight;
        grandSum += sum;
    });

    var grandCountEl = document.getElementById('grand-total-clients');
    var grandWeightEl = document.getElementById('grand-total-weight');
    var grandSumEl = document.getElementById('grand-total-sum');

    if (grandCountEl) grandCountEl.textContent = grandCount;
    if (grandWeightEl) grandWeightEl.textContent = grandWeight.toFixed(3).replace('.', ',');
    if (grandSumEl) grandSumEl.textContent = grandSum.toFixed(0);
}
