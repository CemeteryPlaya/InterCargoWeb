function toggleCell(cellId) {
    var content = document.getElementById('cell-' + cellId);
    var arrow = document.getElementById('arrow-' + cellId);
    if (content.classList.contains('hidden')) {
        content.classList.remove('hidden');
        arrow.style.transform = 'rotate(180deg)';
    } else {
        content.classList.add('hidden');
        arrow.style.transform = 'rotate(0deg)';
    }
}

function cellDisplayNumber(num) {
    return num === '0' ? 'Пол' : num;
}

function editCellNumber(cellId, currentNumber, el) {
    var newNumber = prompt('Введите новый номер ячейки (например: 1, 2.1, 0 для «Пол»):', currentNumber);
    if (newNumber === null) return;

    newNumber = newNumber.trim();
    if (!/^\d+(\.\d+)?$/.test(newNumber)) {
        alert('Номер ячейки должен быть числом (например: 1, 2.1, 0).');
        return;
    }
    if (newNumber === currentNumber) return;

    var csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;

    fetch('/profile/warehouse/update-cell/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken,
        },
        body: JSON.stringify({ cell_id: cellId, cell_number: newNumber }),
    })
    .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
    .then(function (result) {
        if (!result.ok) {
            alert(result.data.error || 'Ошибка при обновлении.');
            return;
        }
        var numSpan = document.getElementById('cell-num-' + cellId);
        if (numSpan) numSpan.textContent = cellDisplayNumber(result.data.cell_number);

        el.setAttribute('onclick',
            "event.stopPropagation(); editCellNumber(" + cellId + ", '" + result.data.cell_number + "', this)");
    })
    .catch(function () {
        alert('Ошибка сети. Попробуйте ещё раз.');
    });
}
