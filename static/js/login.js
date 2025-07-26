document.addEventListener("DOMContentLoaded", () => {
    const flashMessages = document.querySelectorAll(".flash-message");
    if (flashMessages.length > 0) {
        const modal = document.getElementById("modal-flash");
        const messageText = document.getElementById("flash-message-text");
    
        // Puedes combinar todos los mensajes o mostrar uno a uno
        let content = "";
        flashMessages.forEach(msg => {
            const category = msg.dataset.category;
            content += `<strong>[${category.toUpperCase()}]</strong> ${msg.textContent}<br>`;
        });
    
        messageText.innerHTML = content;
        modal.classList.add("show");
    }
    });
    
function closeFlashModal() {
    document.getElementById("modal-flash").classList.remove("show");
}
