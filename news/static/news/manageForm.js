// Quill-редакторы формы новости (ru/kk/en) + синхронизация в hidden-поля.
(function () {
    'use strict';

    var TOOLBAR = [
        [{ header: [2, 3, false] }],
        ['bold', 'italic', 'underline', 'strike'],
        [{ list: 'ordered' }, { list: 'bullet' }],
        [{ align: [] }],
        ['link', 'blockquote', 'clean'],
    ];

    function initEditor(lang) {
        var container = document.getElementById('editor-' + lang);
        var input = document.getElementById('id_body_' + lang);
        if (!container || !input) return null;
        var quill = new Quill(container, {
            theme: 'snow',
            modules: { toolbar: TOOLBAR },
        });
        if (input.value) {
            quill.clipboard.dangerouslyPasteHTML(input.value);
        }
        return { quill: quill, input: input };
    }

    document.addEventListener('DOMContentLoaded', function () {
        var editors = ['ru', 'kk', 'en'].map(initEditor).filter(Boolean);
        var form = document.getElementById('news-post-form');
        if (!form) return;
        form.addEventListener('submit', function () {
            editors.forEach(function (e) {
                // Пустой Quill отдаёт '<p></p>' — считаем это пустым полем
                e.input.value = e.quill.getText().trim() === ''
                    ? ''
                    : e.quill.getSemanticHTML();
            });
        });
    });
})();
