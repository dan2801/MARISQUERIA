function openModalProduct(id) {
    const modal = document.getElementById('modal_product' + id);
    if (modal) {
        modal.classList.add('show');
    }
}



window.onclick = function(event) {
    document.querySelectorAll('.modal').forEach(modal => {
        if (event.target === modal) {
            modal.classList.remove('show');
        }
    });
}