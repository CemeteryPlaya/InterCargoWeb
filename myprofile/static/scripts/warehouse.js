function toggleCell(cellNumber) {
    var content = document.getElementById('cell-' + cellNumber);
    var arrow = document.getElementById('arrow-' + cellNumber);
    if (content.classList.contains('hidden')) {
        content.classList.remove('hidden');
        arrow.style.transform = 'rotate(180deg)';
    } else {
        content.classList.add('hidden');
        arrow.style.transform = 'rotate(0deg)';
    }
}

function editCellNumber(cellId, currentNumber, el) {
    var newNumber = prompt('Введите новый номер ячейки:', currentNumber);
    if (newNumber === null) return;

    newNumber = parseInt(newNumber, 10);
    if (isNaN(newNumber) || newNumber < 1) {
        alert('Номер ячейки должен быть положительным числом.');
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
        // Обновляем номер в UI
        var numSpan = document.getElementById('cell-num-' + cellId);
        if (numSpan) numSpan.textContent = result.data.cell_number;

        // Обновляем onclick с новым номером
        el.setAttribute('onclick',
            'event.stopPropagation(); editCellNumber(' + cellId + ', ' + result.data.cell_number + ', this)');
    })
    .catch(function () {
        alert('Ошибка сети. Попробуйте ещё раз.');
    });
}
