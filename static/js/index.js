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

function toggleCategoria(id) {
    const div = document.getElementById(id);
    if (div.style.display === "none") {
        div.style.display = "grid";
    } else {
        div.style.display = "none";
    }
}

function openModal() {
    const modal = document.getElementById('modal');
    modal.classList.add('show');
}

function closeModal() {
    const modal = document.getElementById('modal');
    modal.classList.remove('show');
}

window.onclick = function(event) {
    const modal = document.getElementById('modal');
    if (event.target == modal) {
        closeModal();
    }
}

function openModalCategory() {
    const modal = document.getElementById('modal_category');
    modal.classList.add('show');
}

function closeModalCategory() {
    const modal = document.getElementById('modal_category');
    modal.classList.remove('show');
}

window.onclick = function(event) {
    const modal = document.getElementById('modal_category');
    if (event.target == modal) {
        closeModalCategory();
    }
}

function openModalEdit(productId) {
    const modal = document.getElementById('modal_edit' + productId);
    if (modal) {
        modal.classList.add('show');
    }
}

function closeModalEdit(productId) {
    const modal = document.getElementById('modal_edit' + productId);
    if (modal) {
        modal.classList.remove('show');
    }
}

window.onclick = function(event) {
    document.querySelectorAll('.modal').forEach(modal => {
        if (event.target === modal) {
            modal.classList.remove('show');
        }
    });
}

function logout() {
    fetch('/logout', {
        method: 'POST'
    })
    .then(response => {
        if (response.ok) {
            window.location.href = '/login';
        }
    })
    .catch(error => {
        console.error('Error al cerrar sesión:', error);
    });
}
