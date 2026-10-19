document.addEventListener("DOMContentLoaded", () => {
    const flashMessages = document.querySelectorAll(".flash-message");
    if (flashMessages.length > 0) {
        const modal = document.getElementById("modal-flash");
        const messageText = document.getElementById("flash-message-text");
    
        messageText.replaceChildren();
        flashMessages.forEach(msg => {
            const linea = document.createElement('div');
            const categoria = document.createElement('strong');
            categoria.textContent = `[${(msg.dataset.category || '').toUpperCase()}] `;
            linea.append(categoria, document.createTextNode(msg.textContent));
            messageText.appendChild(linea);
        });
    
        modal.classList.add("show");
    }
    });
    
function closeFlashModal() {
    document.getElementById("modal-flash").classList.remove("show");
}
