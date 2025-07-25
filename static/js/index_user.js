function openModalProduct(id) {
    const modal = document.getElementById('modal_product' + id);
    if (modal) {
        console.log("Antes: ", modal.className);
        modal.classList.add('show');
        console.log("Después: ", modal.className);
    }
}

function closeModalProduct(id) {
    const modal = document.getElementById('modal_product' + id);
    if (modal) {
        console.log("Antes: ", modal.className);
        modal.classList.remove('show');
        console.log("Después: ", modal.className);
    }
}