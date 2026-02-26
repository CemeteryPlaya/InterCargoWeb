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
