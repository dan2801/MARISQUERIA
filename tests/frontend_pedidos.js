// Ejecutable con un motor JavaScript: probarFrontendPedidos(scriptRenderizado, scriptAvisos).
function probarFrontendPedidos(scriptPedidos, scriptAvisos) {
    let comprobaciones = 0;
    function comprobar(condicion, mensaje) {
        if (!condicion) throw new Error(mensaje);
        comprobaciones++;
    }
    const almacenamiento = new Map();
    let secuencia = 1;
    function entorno() {
        const elementos = new Map(), eventos = {}, enviados = [], temporizadores = new Map();
        function elemento(id) {
            if (!elementos.has(id)) elementos.set(id, {
                id, textContent: '', value: '', disabled: false, dataset: {},
                children: [],
                classList: {add() {}, remove() {}, toggle() {}},
                addEventListener() {}, appendChild(nodo) {this.children.push(nodo);},
                append(...nodos) {this.children.push(...nodos);}, replaceChildren() {this.children = [];},
                setAttribute() {}, matches() {return false;},
                querySelectorAll() {return [];}
            });
            return elementos.get(id);
        }
        const document = {getElementById: elemento, querySelector() {return {content: 'token-prueba'};}, querySelectorAll() {return [];},
            addEventListener() {}, createElement() {return elemento('creado-' + secuencia++);},
            body: {classList: {add() {}, remove() {}}}};
        const socket = {connected: true, on(nombre, callback) {eventos[nombre] = callback;},
            emit(nombre, datos) {enviados.push(JSON.parse(JSON.stringify({nombre, datos})));}};
        const storage = {getItem: clave => almacenamiento.get(clave) || null,
            setItem: (clave, valor) => almacenamiento.set(clave, valor), removeItem: clave => almacenamiento.delete(clave)};
        const window = {crypto: {getRandomValues(bytes) {bytes.fill(secuencia++);}}, addEventListener() {}};
        const timer = callback => {const id = secuencia++; temporizadores.set(id, callback); return id;};
        const codigo = scriptPedidos + '\nreturn {agregarAlPedido, eliminarAlPedido, quitarDelBorrador, enviarPedido, estado: () => ({pedido, solicitudPendiente, enviandoPedido})};';
        const api = new Function('document', 'io', 'sessionStorage', 'window', 'setTimeout', 'clearTimeout',
            'console', 'alert', 'fetch', 'DOMParser', codigo)(document, () => socket, storage, window,
            timer, id => temporizadores.delete(id), {log() {}, error() {}}, () => {},
            async () => ({ok: true, redirected: false, text: async () => ''}),
            class {parseFromString() {return {getElementById() {return null;}};}});
        return {api, socket, eventos, enviados, temporizadores, elemento};
    }
    const producto = {id: '1', nombre: 'Agua', precio: 20, cantidad: 2};
    const uno = entorno();
    uno.api.agregarAlPedido(producto);
    uno.eventos.nuevo_pedido_creado({id: 50, usuario_id: 'mesero'});
    comprobar(uno.api.estado().pedido[0].cantidad === 2, 'Otra pestaña borró la selección');
    comprobar(almacenamiento.size === 1, 'No se guardó el borrador');
    const recarga = entorno();
    comprobar(recarga.api.estado().pedido[0].cantidad === 2, 'La recarga perdió el borrador');
    recarga.socket.connected = false;
    recarga.api.enviarPedido();
    comprobar(recarga.enviados.length === 0, 'Se envió estando desconectado');
    recarga.socket.connected = true;
    recarga.api.enviarPedido();
    const token = recarga.enviados[0].datos.solicitud_id;
    comprobar(!!token, 'El envío no tiene identificador');
    recarga.api.agregarAlPedido(producto);
    comprobar(recarga.api.estado().pedido[0].cantidad === 2, 'Se modificó un envío pendiente');
    recarga.api.quitarDelBorrador('1');
    comprobar(recarga.api.estado().pedido[0].cantidad === 2, 'Se quitó un artículo de un envío pendiente');
    [...recarga.temporizadores.values()][0]();
    comprobar(!recarga.api.estado().enviandoPedido, 'El timeout dejó bloqueado el envío');
    recarga.api.enviarPedido();
    comprobar(recarga.enviados[1].datos.solicitud_id === token, 'El reintento cambió el identificador');
    const reconexion = entorno();
    reconexion.eventos.connect();
    comprobar(reconexion.enviados[0].datos.solicitud_id === token, 'La recarga no verificó el envío pendiente');
    reconexion.eventos.pedido_creado({solicitud_id: 'otro-envio'});
    comprobar(reconexion.api.estado().pedido.length === 1, 'Una respuesta ajena borró el pedido');
    reconexion.eventos.pedido_creado({solicitud_id: token, id: 1});
    comprobar(reconexion.api.estado().pedido.length === 0, 'No se limpió el pedido confirmado');
    comprobar(almacenamiento.size === 0, 'No se retiró el borrador confirmado');
    const error = entorno();
    error.api.agregarAlPedido(producto);
    error.api.enviarPedido();
    error.eventos.pedido_error({solicitud_id: error.api.estado().solicitudPendiente.id, error: 'Producto no disponible'});
    comprobar(error.api.estado().pedido.length === 1 && !error.api.estado().solicitudPendiente,
        'Un rechazo perdió el pedido o dejó bloqueada su edición');

    almacenamiento.clear();
    const edicion = entorno();
    edicion.api.agregarAlPedido({...producto, cantidad: 3});
    edicion.api.eliminarAlPedido({...producto, cantidad: 1});
    comprobar(edicion.api.estado().pedido[0].cantidad === 2, 'No se redujo una unidad desde el resumen');
    comprobar(edicion.elemento('pedidoTotal').textContent === '40.00', 'El total no se actualizó al reducir');
    edicion.api.quitarDelBorrador('1');
    comprobar(edicion.api.estado().pedido.length === 0 && almacenamiento.size === 0, 'Quitar no retiró el artículo y su borrador');
    comprobar(edicion.elemento('pedidoTotal').textContent === '0.00' && edicion.elemento('crearTicketBoton').disabled,
        'Una selección vacía conserva importe o permite crear ticket');

    const mensaje = '<img src=x onerror=alert(1)>';
    let textoCreado = '', contenidoHtml = false;
    const nodo = () => ({textContent: '', append() {}, appendChild() {}, replaceChildren() {},
        classList: {add() {}}, set innerHTML(valor) {contenidoHtml = true;}});
    const docAvisos = {addEventListener(nombre, callback) {callback();},
        querySelectorAll() {return [{dataset: {category: 'success'}, textContent: mensaje}];},
        getElementById() {return nodo();}, createElement: nodo,
        createTextNode(texto) {textoCreado = texto; return nodo();}};
    new Function('document', 'window', scriptAvisos)(docAvisos, {addEventListener() {}});
    comprobar(!contenidoHtml && textoCreado === mensaje, 'El aviso interpretó HTML en lugar de texto');
    return comprobaciones;
}

function probarProteccionFetch(scriptSeguridad) {
    const llamadas = [];
    class URLPrueba {
        constructor(valor, base) {
            this.origin = (/^https?:\/\/[^/]+/.exec(valor) || /^https?:\/\/[^/]+/.exec(base))[0];
            this.href = valor;
        }
    }
    class HeadersPrueba {
        constructor(valores = {}) {this.valores = new Map(Object.entries(valores).map(([k,v]) => [k.toLowerCase(), v]));}
        set(nombre, valor) {this.valores.set(nombre.toLowerCase(), valor);}
        get(nombre) {return this.valores.get(nombre.toLowerCase());}
    }
    const window = {location: {href: 'https://marisqueria.test/', origin: 'https://marisqueria.test'},
        fetch(input, opciones) {llamadas.push({input, opciones}); return 'respuesta';}};
    const document = {querySelector() {return {content: 'token-seguro'};}};
    new Function('window', 'document', 'URL', 'Headers', scriptSeguridad)(window, document, URLPrueba, HeadersPrueba);
    const respuesta = window.fetch('/guardar_historico', {method: 'POST', headers: {'Content-Type': 'application/json'}});
    window.fetch('/tickets');
    window.fetch('https://externo.test/api', {method: 'POST'});
    window.fetch({url: '/create', method: 'POST', headers: {'Content-Type': 'application/json'}});
    if (respuesta !== 'respuesta' || llamadas[0].opciones.headers.get('X-CSRF-Token') !== 'token-seguro' ||
        llamadas[0].opciones.headers.get('Content-Type') !== 'application/json' ||
        llamadas[1].opciones.headers || llamadas[2].opciones.headers ||
        llamadas[3].opciones.headers.get('X-CSRF-Token') !== 'token-seguro') {
        throw new Error('La protección de fetch no conserva cabeceras o filtra el token a otro origen');
    }
    return 6;
}
