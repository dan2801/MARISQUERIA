const socket = io({auth: {csrf_token: document.querySelector('meta[name="csrf-token"]').content}});
let audioCaja = null;
let ocultarAvisoCaja;
let versionPedidosCaja = 0;
const notasCaja = new Set();
const ticketsNotificadosCaja = new Set();
const claveVistosCaja = 'marisqueria:tickets-vistos:' + document.querySelector('meta[name="usuario-activo"]').content;
let avisoSinSonidoCaja = null;
try {
    avisoSinSonidoCaja = JSON.parse(sessionStorage.getItem(claveVistosCaja + ':pendiente') || 'null');
    const anteriores = JSON.parse(sessionStorage.getItem(claveVistosCaja) || 'null');
    const ids = anteriores || Array.from(document.querySelectorAll('[data-aviso-id]'), nodo => Number(nodo.dataset.avisoId));
    ids.forEach(id => ticketsNotificadosCaja.add(id));
} catch (error) { /* Las notificaciones siguen funcionando sin almacenamiento. */ }
function guardarVistosCaja() {
    try {sessionStorage.setItem(claveVistosCaja, JSON.stringify([...ticketsNotificadosCaja]));} catch (error) {}
}
guardarVistosCaja();
const estadoSonidoCaja = document.getElementById('estadoSonidoCaja');
socket.on('sesion_finalizada', () => {
    detenerSonidoCaja();
    window.location.href = '/login?sesion=finalizada';
});

async function activarAudioCaja() {
    try {
        const ContextoAudio = window.AudioContext || window.webkitAudioContext;
        if (!ContextoAudio) {
            estadoSonidoCaja.textContent = 'Este navegador no admite la alerta sonora.';
            return;
        }
        if (!audioCaja || audioCaja.state === 'closed') audioCaja = new ContextoAudio();
        if (audioCaja.state === 'running') return;
        await audioCaja.resume();
        if (audioCaja.state !== 'running') throw new Error('Audio bloqueado');
        estadoSonidoCaja.textContent = 'Alerta sonora activa: cada nuevo ticket sonará durante 5 segundos.';
        if (avisoSinSonidoCaja) {
            const pendiente = avisoSinSonidoCaja;
            avisoSinSonidoCaja = null;
            try {sessionStorage.removeItem(claveVistosCaja + ':pendiente');} catch (error) {}
            mostrarNuevoTicketCaja(pendiente);
        }
    } catch (error) {
        estadoSonidoCaja.textContent = 'Toca cualquier parte de la página para habilitar el audio del navegador.';
    }
}

// No hay interruptor de silencio; las interacciones permiten desbloquear el audio.
document.addEventListener('pointerdown', activarAudioCaja, { capture: true });
document.addEventListener('keydown', activarAudioCaja, { capture: true });
document.addEventListener('visibilitychange', () => {
    if (!document.hidden) void activarAudioCaja();
});
void activarAudioCaja();

function detenerSonidoCaja() {
    for (const nota of notasCaja) {
        try { nota.stop(); } catch (error) { /* La nota ya terminó. */ }
    }
    notasCaja.clear();
}

async function sonarNuevoTicketCaja() {
    await activarAudioCaja();
    if (!audioCaja) return;
    try {
        if (audioCaja.state === 'suspended') await audioCaja.resume();
        if (audioCaja.state !== 'running') return;
        detenerSonidoCaja();
        const inicio = audioCaja.currentTime + 0.02;
        // Siete pares de notas suaves, contenidos en una alerta de cinco segundos.
        for (let repeticion = 0; repeticion < 7; repeticion++) {
            [783.99, 1046.5].forEach((frecuencia, indice) => {
                const nota = audioCaja.createOscillator();
                const volumen = audioCaja.createGain();
                const tiempo = inicio + repeticion * 0.7 + indice * 0.18;
                nota.type = 'sine';
                nota.frequency.value = frecuencia;
                volumen.gain.setValueAtTime(0, tiempo);
                volumen.gain.linearRampToValueAtTime(0.16, tiempo + 0.015);
                volumen.gain.exponentialRampToValueAtTime(0.001, tiempo + 0.55);
                nota.connect(volumen);
                volumen.connect(audioCaja.destination);
                notasCaja.add(nota);
                nota.onended = () => {
                    notasCaja.delete(nota);
                    nota.disconnect();
                    volumen.disconnect();
                };
                nota.start(tiempo);
                nota.stop(tiempo + 0.6);
            });
        }
    } catch (error) {
        estadoSonidoCaja.textContent = 'Toca la página para reactivar el audio del navegador.';
    }
}

function cerrarAvisoTicketCaja() {
    clearTimeout(ocultarAvisoCaja);
    document.getElementById('avisoTicketCaja').hidden = true;
}

document.getElementById('cerrarAvisoCaja').addEventListener('click', cerrarAvisoTicketCaja);

function mostrarNuevoTicketCaja(datos) {
    if (!audioCaja || audioCaja.state !== 'running') {
        avisoSinSonidoCaja = datos;
        try {sessionStorage.setItem(claveVistosCaja + ':pendiente', JSON.stringify(datos));} catch (error) {}
    }
    const aviso = document.getElementById('avisoTicketCaja');
    document.getElementById('avisoTicketCajaDetalle').textContent =
        `${datos.folio || 'Ticket #' + datos.id} · Mesero: ${datos.usuario_id}`;
    clearTimeout(ocultarAvisoCaja);
    aviso.hidden = false;
    // Reiniciar el movimiento cuando llega otro ticket mientras el aviso está visible.
    aviso.getAnimations({ subtree: true }).forEach(animacion => {
        animacion.currentTime = 0;
        animacion.play();
    });
    void sonarNuevoTicketCaja();
    ocultarAvisoCaja = setTimeout(cerrarAvisoTicketCaja, 6000);
}

async function actualizarPedidosCaja() {
    const version = ++versionPedidosCaja;
    try {
        const respuesta = await fetch('/');
        if (!respuesta.ok || respuesta.redirected) throw new Error('Sesión no disponible');
        const pagina = new DOMParser().parseFromString(await respuesta.text(), 'text/html');
        const nuevo = pagina.getElementById('pedidosCaja');
        if (!nuevo || version !== versionPedidosCaja) return;
        const nuevos = [];
        nuevo.querySelectorAll('[data-aviso-id]').forEach(nodo => {
            const id = Number(nodo.dataset.avisoId);
            if (!ticketsNotificadosCaja.has(id)) {
                ticketsNotificadosCaja.add(id);
                nuevos.push({id, folio: nodo.dataset.avisoFolio, usuario_id: nodo.dataset.avisoUsuario});
            }
        });
        guardarVistosCaja();
        if (nuevos.length) mostrarNuevoTicketCaja(nuevos.length === 1 ? nuevos[0] : {
            id: nuevos[nuevos.length-1].id, folio: `${nuevos.length} tickets recibidos`, usuario_id: 'Varios meseros'
        });
        const panel = document.getElementById('pedidosCaja');
        const abiertos = Array.from(panel.querySelectorAll('details[open]')).map(detalle => ({
            grupo: detalle.dataset.grupoCaja, ticket: detalle.dataset.ticketCaja
        }));
        const posicion = window.scrollY;
        panel.innerHTML = nuevo.innerHTML;
        panel.querySelectorAll('details').forEach(detalle => {
            detalle.open = abiertos.some(abierto =>
                (abierto.grupo !== undefined && abierto.grupo === detalle.dataset.grupoCaja) ||
                (abierto.ticket !== undefined && abierto.ticket === detalle.dataset.ticketCaja));
        });
        window.scrollTo(window.scrollX, posicion);
    } catch (error) {
        estadoSonidoCaja.textContent = 'No se pudieron actualizar las cuentas. Revisa la conexión y recarga la página.';
    }
}

socket.on('ticket_enviado_caja', datos => {
    void actualizarPedidosCaja();
    if (ticketsNotificadosCaja.has(datos.id)) return;
    ticketsNotificadosCaja.add(datos.id);
    guardarVistosCaja();
    mostrarNuevoTicketCaja(datos);
});
socket.on('connect', actualizarPedidosCaja);
socket.on('pedido_cobrado', actualizarPedidosCaja);
socket.on('pedido_eliminado', actualizarPedidosCaja);

function ticket(pedidoId) {
    window.open(`/ticket/${pedidoId}`, '_blank', 'width=400,height=600');
}

const cierresEnProcesoCaja = new Set();
let totalCobroCaja = 0;

function actualizarPagoMixtoCaja() {
    const mixto = document.querySelector('#metodosPagoCaja input:checked').value === 'MIXTO'
        && !document.getElementById('metodosPagoCaja').hidden;
    const campo = document.getElementById('efectivoMixtoCaja');
    document.getElementById('pagoMixtoCaja').hidden = !mixto;
    campo.disabled = !mixto;
    campo.max = ((totalCobroCaja - 1) / 100).toFixed(2);
    const restante = totalCobroCaja - Math.round(Number(campo.value) * 100);
    document.getElementById('transferenciaMixtaCaja').textContent =
        Number.isFinite(restante) && restante >= 0 ? '$' + (restante / 100).toFixed(2) : 'Revisa el efectivo';
}
document.getElementById('metodosPagoCaja').addEventListener('change', actualizarPagoMixtoCaja);
document.getElementById('efectivoMixtoCaja').addEventListener('input', actualizarPagoMixtoCaja);

function confirmarCierrePedidoCaja(pedidoId, boton, cancelar = false) {
    const dialogo = document.getElementById('confirmarCierreCaja');
    if (dialogo.open) return Promise.resolve(false);
    const folio = boton?.dataset.folio || pedidoId;
    const total = boton?.dataset.total;
    document.getElementById('confirmarCierreCajaTitulo').textContent = cancelar ? 'Cancelar pedido' : 'Cerrar pedido';
    document.getElementById('confirmarAccionPedidoCaja').textContent = cancelar ? 'Sí, cancelar pedido' : 'Sí, cerrar pedido';
    document.getElementById('confirmarCierreCajaMensaje').textContent = cancelar
        ? `¿Seguro que deseas cancelar el pedido ${folio}?`
        : `¿Confirmas cerrar el pedido ${folio}${total ? ' por $' + total + ' MXN' : ''}? Quedará registrado como cobrado.`;
    // Al cancelar una cuenta, el botón secundario deja claro que la conserva.
    dialogo.querySelector('[value="cancelar"]').textContent = cancelar ? 'Volver' : 'Cancelar';
    document.getElementById('metodosPagoCaja').hidden = cancelar;
    dialogo.querySelector('[value="EFECTIVO"]').checked = true;
    totalCobroCaja = Math.round(Number(total || 0) * 100);
    document.getElementById('efectivoMixtoCaja').value = '';
    actualizarPagoMixtoCaja();
    dialogo.returnValue = '';
    return new Promise(resolve => {
        dialogo.addEventListener('close', () => resolve(dialogo.returnValue === 'confirmar'), { once: true });
        dialogo.showModal();
    });
}

async function guardar_historico(pedidoId, boton) {
    return procesarPedidoCaja(pedidoId, boton, false);
}

async function cancelarPedidoCaja(pedidoId, boton) {
    return procesarPedidoCaja(pedidoId, boton, true);
}

async function procesarPedidoCaja(pedidoId, boton, cancelar) {
    if (cierresEnProcesoCaja.has(pedidoId)) return;
    cierresEnProcesoCaja.add(pedidoId);
    try {
        if (!await confirmarCierrePedidoCaja(pedidoId, boton, cancelar)) return;
        if (boton) boton.disabled = true;
        const pago = cancelar ? {} : {metodo_pago: document.querySelector('#metodosPagoCaja input:checked').value};
        if (pago.metodo_pago === 'MIXTO') pago.monto_efectivo = document.getElementById('efectivoMixtoCaja').value;
        await window.operarPedido(cancelar ? `/delete_pedido/${pedidoId}` : '/guardar_historico', {pedido_id: pedidoId, ...pago});
        await actualizarPedidosCaja();
    } catch (error) {
        alert(error.message || 'No se pudo actualizar el pedido');
    } finally {
        cierresEnProcesoCaja.delete(pedidoId);
        if (boton) boton.disabled = false;
    }
}
window.addEventListener('pedido:actualizado', actualizarPedidosCaja);
