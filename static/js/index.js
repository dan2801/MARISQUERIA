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

function openModalCategory() {
    const modal = document.getElementById('modal_category');
    modal.classList.add('show');
}

function closeModalCategory() {
    const modal = document.getElementById('modal_category');
    modal.classList.remove('show');
}

function openModalDeleteCategory() {
    const modal = document.getElementById('modal_delete_category');
    modal.classList.add('show');
}

function closeModalDeleteCategory() {
    const modal = document.getElementById('modal_delete_category');
    modal.classList.remove('show');
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

window.addEventListener("click", function(event) {
    document.querySelectorAll('.modal').forEach(modal => {
        if (event.target === modal) {
            modal.classList.remove('show');
        }
    });
});


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
