(function () {
  var list = document.getElementById('item-list');
  var addBtn = document.getElementById('add-item-btn');
  var counter = document.getElementById('item-counter');
  if (!list || !addBtn) return;

  function rowTemplate(index) {
    return '' +
      '<div class="item-row">' +
        '<div class="item-head"><span class="n">' + index + '</span>' +
          '<button type="button" class="link-btn js-remove">удалить</button></div>' +
        '<input class="fld js-url" type="url" name="item_url" placeholder="Ссылка на товар (бренд-сайт)">' +
        '<div class="row2">' +
          '<input class="fld js-comment" type="text" name="item_comment" placeholder="Размер, цвет, детали">' +
          '<input class="fld qty" type="number" name="item_quantity" min="1" value="1">' +
        '</div>' +
      '</div>';
  }

  function renumber() {
    var rows = list.querySelectorAll('.item-row');
    rows.forEach(function (row, i) {
      var n = row.querySelector('.n');
      if (n) n.textContent = i + 1;
    });
    if (counter) counter.textContent = rows.length + ' товар(ов)';
  }

  addBtn.addEventListener('click', function () {
    var count = list.querySelectorAll('.item-row').length;
    list.insertAdjacentHTML('beforeend', rowTemplate(count + 1));
    renumber();
  });

  list.addEventListener('click', function (e) {
    if (!e.target.classList.contains('js-remove')) return;
    var rows = list.querySelectorAll('.item-row');
    if (rows.length <= 1) return; // keep at least one row
    e.target.closest('.item-row').remove();
    renumber();
  });

  renumber();
})();
