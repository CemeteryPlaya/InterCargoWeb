document.addEventListener('DOMContentLoaded', function () {
    const markAllReadBtn = document.getElementById('mark-all-read');
    if (markAllReadBtn) {
        markAllReadBtn.addEventListener('click', function () {
            fetch(markAllReadBtn.dataset.url, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': markAllReadBtn.dataset.csrf,
                    'Content-Type': 'application/json'
                },
            })
                .then(response => {
                    if (response.ok) {
                        window.location.reload();
                    } else {
                        console.error('Ошибка при пометке уведомлений как прочитанных');
                    }
                })
                .catch(error => {
                    console.error('Ошибка сети:', error);
                });
        });
    }
});
