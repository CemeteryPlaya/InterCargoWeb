// Стрелки десктопной ленты новостей на главной: прокрутка + гашение на краях.
(function () {
    'use strict';

    function init() {
        var strip = document.querySelector('[data-news-strip]');
        if (!strip) return;
        var prev = document.querySelector('[data-news-prev]');
        var next = document.querySelector('[data-news-next]');
        if (!prev || !next) return;

        function step() {
            var card = strip.querySelector('a');
            var gap = 16; // gap-4
            return card ? (card.offsetWidth + gap) * 2 : strip.clientWidth;
        }

        function update() {
            var maxScroll = strip.scrollWidth - strip.clientWidth;
            prev.disabled = strip.scrollLeft <= 1;
            next.disabled = strip.scrollLeft >= maxScroll - 1;
            // Лента не переполнена — стрелки не нужны вовсе
            var hidden = maxScroll <= 1;
            prev.style.visibility = hidden ? 'hidden' : '';
            next.style.visibility = hidden ? 'hidden' : '';
        }

        prev.addEventListener('click', function () {
            strip.scrollBy({ left: -step(), behavior: 'smooth' });
        });
        next.addEventListener('click', function () {
            strip.scrollBy({ left: step(), behavior: 'smooth' });
        });
        strip.addEventListener('scroll', update, { passive: true });
        window.addEventListener('resize', update);
        update();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
