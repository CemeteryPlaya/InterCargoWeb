document.addEventListener('DOMContentLoaded', function() {
    var fileInput = document.getElementById('xlsx_file');
    var fileName = document.getElementById('file_name');
    var dropZone = document.getElementById('drop_zone');

    fileInput.addEventListener('change', function() {
        if (this.files.length > 0) {
            fileName.textContent = this.files[0].name;
            fileName.classList.remove('hidden');
        }
    });

    dropZone.addEventListener('dragover', function(e) {
        e.preventDefault();
        this.classList.add('border-primary', 'bg-red-50');
    });
    dropZone.addEventListener('dragleave', function(e) {
        e.preventDefault();
        this.classList.remove('border-primary', 'bg-red-50');
    });
    dropZone.addEventListener('drop', function(e) {
        e.preventDefault();
        this.classList.remove('border-primary', 'bg-red-50');
        if (e.dataTransfer.files.length > 0) {
            fileInput.files = e.dataTransfer.files;
            fileName.textContent = e.dataTransfer.files[0].name;
            fileName.classList.remove('hidden');
        }
    });
});
