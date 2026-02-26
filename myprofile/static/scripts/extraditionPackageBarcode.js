document.addEventListener('DOMContentLoaded', function() {
    var params = new URLSearchParams(window.location.search);
    var showBarcode = params.get('show_barcode');
    if (showBarcode) {
        var btns = document.querySelectorAll('.show-barcode-btn');
        for (var i = 0; i < btns.length; i++) {
            if (btns[i].dataset.barcode === showBarcode) {
                btns[i].click();
                break;
            }
        }
    }
});
