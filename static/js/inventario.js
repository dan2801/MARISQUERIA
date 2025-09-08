// === Variables globales ===
let secciones = JSON.parse(localStorage.getItem("secciones")) || [];

const contenedor = document.getElementById("contenedor-inventario");
const btnNuevaSeccion = document.getElementById("btn-nueva-seccion");
const modalProducto = document.getElementById("modal-producto");
const formProducto = document.getElementById("form-producto");
const modalSeccion = document.getElementById("modal-seccion");
const formSeccion = document.getElementById("form-seccion");

const cancelarProducto = document.getElementById("cancelar-producto");
const cancelarSeccion = document.getElementById("cancelar-seccion");

let productoSeleccionado = null;
let modoEdicion = false;

// === Guardar en localStorage ===
function guardarSecciones() {
  localStorage.setItem("secciones", JSON.stringify(secciones));
}

// === Crear ID ===
function crearID() {
  return '_' + Math.random().toString(36).substr(2, 9);
}

// === Renderizar ===
function renderizar() {
  contenedor.innerHTML = "";

  secciones.forEach(seccion => {
    const div = document.createElement("div");
    div.className = "seccion";

    const encabezado = document.createElement("div");
    encabezado.className = "seccion-header";

    const titulo = document.createElement("h2");
    titulo.innerHTML = `<span class="flecha">►</span> ${seccion.nombre}`;
    titulo.style.cursor = "pointer";

    const listaProductos = document.createElement("div");
    listaProductos.className = "productos";

    // Mostrar / ocultar productos
    titulo.addEventListener("click", (e) => {
      // Evita que el clic en botones hijos afecte el toggle
      if(e.target.tagName === "BUTTON") return;
      if(e.target.closest("button")) return;

      const flecha = titulo.querySelector(".flecha");
      const mostrar = listaProductos.classList.toggle("mostrar");
      flecha.textContent = mostrar ? "▼" : "►";
    });

    // Botón Agregar Producto
    const btnAgregar = document.createElement("button");
    btnAgregar.textContent = "Agregar";
    btnAgregar.className = "btn-agregar";

    btnAgregar.addEventListener("click", (event) => {
      event.stopPropagation();
      productoSeleccionado = seccion.id;
      modoEdicion = false;
      formProducto.reset();
      document.getElementById("producto-seccion").value = seccion.id;
      modalProducto.style.display = "flex";
    });

    encabezado.appendChild(titulo);
    encabezado.appendChild(btnAgregar);

    // Productos
    seccion.productos.forEach((producto, index) => {
      const prod = document.createElement("div");
      prod.className = "producto";

      const span = document.createElement("span");
      span.innerHTML = `<strong>${producto.nombre}</strong> — ${producto.descripcion} | Cant: ${producto.cantidad} | $${producto.precio}`;

      const acciones = document.createElement("div");
      acciones.className = "acciones-producto";

      const btnEliminar = document.createElement("button");
      btnEliminar.textContent = "🗑";
      btnEliminar.addEventListener("click", (e) => {
        e.stopPropagation();
        eliminarProducto(seccion.id, index);
      });

      const btnEditar = document.createElement("button");
      btnEditar.textContent = "✏️";
      btnEditar.addEventListener("click", (e) => {
        e.stopPropagation();
        productoSeleccionado = { idSeccion: seccion.id, index };
        modoEdicion = true;
        const prodEdit = seccion.productos[index];
        document.getElementById("producto-nombre").value = prodEdit.nombre;
        document.getElementById("producto-descripcion").value = prodEdit.descripcion;
        document.getElementById("producto-cantidad").value = prodEdit.cantidad;
        document.getElementById("producto-precio").value = prodEdit.precio;
        document.getElementById("producto-seccion").value = seccion.id;
        modalProducto.style.display = "flex";
      });

      const btnSumar = document.createElement("button");
      btnSumar.textContent = "➕";
      btnSumar.addEventListener("click", (e) => {
        e.stopPropagation();
        seccion.productos[index].cantidad += 1;
        guardarSecciones();
        renderizar();
      });

      const btnRestar = document.createElement("button");
      btnRestar.textContent = "➖";
      btnRestar.addEventListener("click", (e) => {
        e.stopPropagation();
        if (seccion.productos[index].cantidad > 0) {
          seccion.productos[index].cantidad -= 1;
          guardarSecciones();
          renderizar();
        }
      });

      acciones.appendChild(btnEditar);
      acciones.appendChild(btnSumar);
      acciones.appendChild(btnRestar);
      acciones.appendChild(btnEliminar);

      prod.appendChild(span);
      prod.appendChild(acciones);

      listaProductos.appendChild(prod);
    });

    // Eliminar sección
    const accionesSeccion = document.createElement("div");
    accionesSeccion.className = "acciones-seccion";
    const btnEliminarSeccion = document.createElement("button");
    btnEliminarSeccion.textContent = "Eliminar Sección";
    btnEliminarSeccion.addEventListener("click", () => eliminarSeccion(seccion.id));
    accionesSeccion.appendChild(btnEliminarSeccion);

    div.appendChild(encabezado);
    div.appendChild(listaProductos);
    div.appendChild(accionesSeccion);
    contenedor.appendChild(div);
  });
}

// === Eventos ===
btnNuevaSeccion.addEventListener("click", () => {
  formSeccion.reset();
  modalSeccion.style.display = "flex";
});

formSeccion.addEventListener("submit", e => {
  e.preventDefault();
  const nombre = document.getElementById("nombre-seccion").value.trim();
  if (!nombre) return;
  secciones.push({ id: crearID(), nombre, productos: [] });
  guardarSecciones();
  renderizar();
  modalSeccion.style.display = "none";
});

formProducto.addEventListener("submit", e => {
  e.preventDefault();
  const nombre = document.getElementById("producto-nombre").value.trim();
  const descripcion = document.getElementById("producto-descripcion").value.trim();
  const cantidad = parseInt(document.getElementById("producto-cantidad").value);
  const precio = parseFloat(document.getElementById("producto-precio").value);
  const idSeccion = document.getElementById("producto-seccion").value;

  if (!nombre || isNaN(cantidad) || isNaN(precio)) return;

  const seccion = secciones.find(s => s.id === idSeccion);
  if (!seccion) return;

  if (modoEdicion && productoSeleccionado) {
    const { index } = productoSeleccionado;
    seccion.productos[index] = { nombre, descripcion, cantidad, precio };
  } else {
    seccion.productos.push({ nombre, descripcion, cantidad, precio });
  }

  guardarSecciones();
  renderizar();
  modalProducto.style.display = "none";
  productoSeleccionado = null;
  modoEdicion = false;
});

cancelarProducto.addEventListener("click", () => {
  modalProducto.style.display = "none";
  productoSeleccionado = null;
  modoEdicion = false;
});

cancelarSeccion.addEventListener("click", () => {
  modalSeccion.style.display = "none";
});

// === Acciones ===
function eliminarProducto(idSeccion, indexProducto) {
  const seccion = secciones.find(s => s.id === idSeccion);
  if (!seccion) return;
  seccion.productos.splice(indexProducto, 1);
  guardarSecciones();
  renderizar();
}

function eliminarSeccion(id) {
  secciones = secciones.filter(s => s.id !== id);
  guardarSecciones();
  renderizar();
}

// === Inicializar ===
renderizar();
