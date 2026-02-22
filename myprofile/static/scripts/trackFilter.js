function toggleFilter(status) {
    var url = new URL(window.location.href);
    var current = url.searchParams.get('status') || '';

    // Clear all status params
    url.searchParams.delete('status');

    // If clicking a new filter (not the same one, not "Все"), set it
    if (status && status !== current) {
        url.searchParams.set('status', status);
    }

    window.location.href = url.toString();
}
