document.addEventListener('DOMContentLoaded', function () {
    const config = document.getElementById('extradition-config');
    const searchUrl = config.dataset.searchUrl;
    const toggleUrl = config.dataset.toggleUrl;

    const barcodeInput = document.getElementById('barcode');
    const searchBtn = document.getElementById('searchBtn');
    const packageInfo = document.getElementById('packageInfo');
    const infoOwner = document.getElementById('infoOwner');
    const infoPickup = document.getElementById('infoPickup');
    const infoPaymentStatus = document.getElementById('infoPaymentStatus');
    const paymentHint = document.getElementById('paymentHint');
    const submitBtn = document.getElementById('submitBtn');
    const clearBtn = document.getElementById('clearBtn');
    const messagesContainer = document.getElementById('ajax-messages');

    function showMessage(text, type) {
        type = type || 'error';
        const msgDiv = document.createElement('div');
        msgDiv.className = 'p-4 mb-3 rounded-lg text-sm font-medium ' + (type === 'error' ? 'bg-red-100 text-red-800' : 'bg-green-100 text-green-800');
        msgDiv.textContent = text;
        messagesContainer.innerHTML = '';
        messagesContainer.appendChild(msgDiv);
        setTimeout(function () { msgDiv.remove(); }, 5000);
    }

    function clearForm() {
        barcodeInput.value = '';
        packageInfo.classList.add('hidden');
        document.getElementById('receiptTable').classList.add('hidden');
        document.getElementById('receiptBody').innerHTML = '';
        submitBtn.disabled = true;
        submitBtn.classList.add('bg-gray-400', 'cursor-not-allowed');
        submitBtn.classList.remove('bg-primary', 'hover:bg-red-600');
        infoPaymentStatus.onclick = null;
        messagesContainer.innerHTML = '';
    }

    clearBtn.onclick = clearForm;
    searchBtn.onclick = performSearch;

    barcodeInput.addEventListener('keypress', function (e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            performSearch();
        }
    });

    function performSearch() {
        var barcode = barcodeInput.value.trim();
        if (!barcode) {
            showMessage('Введите штрихкод');
            return;
        }

        fetch(searchUrl + '?barcode=' + encodeURIComponent(barcode))
            .then(function (response) {
                if (!response.ok) {
                    if (response.status === 404) throw new Error('Пакет не найден');
                    throw new Error('Ошибка сервера');
                }
                return response.json();
            })
            .then(function (data) {
                messagesContainer.innerHTML = '';
                infoOwner.textContent = data.owner;
                infoPickup.textContent = data.pickup_point;
                updatePaymentUI(data.is_paid, data.barcode);
                renderReceipt(data.tracks || []);
                packageInfo.classList.remove('hidden');
            })
            .catch(function (err) {
                console.error(err);
                packageInfo.classList.add('hidden');
                submitBtn.disabled = true;
                submitBtn.classList.add('bg-gray-400', 'cursor-not-allowed');
                submitBtn.classList.remove('bg-primary', 'hover:bg-red-600');
                showMessage(err.message);
            });
    }

    function updatePaymentUI(isPaid, barcode) {
        infoPaymentStatus.textContent = isPaid ? 'Оплачено' : 'Не оплачено';

        if (isPaid) {
            infoPaymentStatus.className = 'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800';
            paymentHint.classList.add('hidden');
            infoPaymentStatus.onclick = null;
            submitBtn.disabled = false;
            submitBtn.classList.remove('bg-gray-400', 'cursor-not-allowed');
            submitBtn.classList.add('bg-primary', 'hover:bg-red-600');
        } else {
            infoPaymentStatus.className = 'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800 cursor-pointer hover:bg-red-200';
            paymentHint.classList.remove('hidden');
            submitBtn.disabled = true;
            submitBtn.classList.add('bg-gray-400', 'cursor-not-allowed');
            submitBtn.classList.remove('bg-primary', 'hover:bg-red-600');

            infoPaymentStatus.onclick = function () {
                if (confirm('Отметить пакет как оплаченный?')) {
                    togglePayment(barcode);
                }
            };
        }
    }

    function renderReceipt(tracks) {
        var receiptTable = document.getElementById('receiptTable');
        var receiptBody = document.getElementById('receiptBody');
        var totalCount = document.getElementById('totalCount');
        var totalWeight = document.getElementById('totalWeight');
        var totalPrice = document.getElementById('totalPrice');

        receiptBody.innerHTML = '';

        if (!tracks.length) {
            receiptTable.classList.add('hidden');
            return;
        }

        var sumWeight = 0;
        var sumPrice = 0;

        tracks.forEach(function (t, i) {
            var tr = document.createElement('tr');
            tr.className = i % 2 === 0 ? 'bg-white' : 'bg-gray-50';
            var cellClass = 'border border-gray-300 px-3 py-1.5';

            var td1 = document.createElement('td');
            td1.className = cellClass;
            td1.textContent = i + 1;

            var td2 = document.createElement('td');
            td2.className = cellClass + ' font-mono text-xs';
            td2.textContent = t.track_code;

            var td3 = document.createElement('td');
            td3.className = cellClass + ' text-right';
            td3.textContent = t.weight.toFixed(3);

            var td4 = document.createElement('td');
            td4.className = cellClass + ' text-right';
            td4.textContent = t.price;

            tr.appendChild(td1);
            tr.appendChild(td2);
            tr.appendChild(td3);
            tr.appendChild(td4);
            receiptBody.appendChild(tr);
            sumWeight += t.weight;
            sumPrice += t.price;
        });

        totalCount.textContent = tracks.length;
        totalWeight.textContent = sumWeight.toFixed(3);
        totalPrice.textContent = sumPrice;
        receiptTable.classList.remove('hidden');
    }

    function togglePayment(barcode) {
        var csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;

        fetch(toggleUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-CSRFToken': csrfToken
            },
            body: 'barcode=' + encodeURIComponent(barcode)
        })
            .then(function (response) { return response.json(); })
            .then(function (data) {
                if (data.success) {
                    updatePaymentUI(true, barcode);
                    showMessage('Статус оплаты обновлен', 'success');
                } else {
                    showMessage('Ошибка: ' + (data.error || 'Не удалось обновить статус'));
                }
            })
            .catch(function () {
                showMessage('Ошибка связи с сервером');
            });
    }
});
