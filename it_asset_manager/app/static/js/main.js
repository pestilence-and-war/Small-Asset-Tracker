// Modal handling
document.addEventListener('click', function(event) {
    const modal = document.getElementById('qr-modal');
    const qrContent = document.getElementById('qr-content');
    if (modal && !qrContent.contains(event.target) && !event.target.closest('button[hx-get*="/assets/qr/"]')) {
        modal.classList.add('hidden');
    }
});

// Keyboard handler for ESC key
document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') {
        const modal = document.getElementById('qr-modal');
        if (modal) {
            modal.classList.add('hidden');
        }
    }
});