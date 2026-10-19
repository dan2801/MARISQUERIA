(() => {
    const usuario = document.querySelector('meta[name="usuario-activo"]')?.content;
    const almacen = 'marisqueria:operacion:' + usuario;
    let enCurso = null;
    function leer() {return JSON.parse(localStorage.getItem(almacen) || 'null');}
    function aviso(mensaje) {
        let panel = document.getElementById('operacionPendienteAviso');
        if (!panel) {
            panel = document.createElement('aside');
            panel.id = 'operacionPendienteAviso';
            panel.className = 'operacion-pendiente';
            panel.setAttribute('role', 'status');
            const texto = document.createElement('p');
            const boton = document.createElement('button');
            boton.type = 'button';
            boton.textContent = 'Verificar cambio pendiente';
            boton.addEventListener('click', () => recuperar().catch(() => {}));
            panel.append(texto, boton);
            document.body.appendChild(panel);
        }
        panel.querySelector('p').textContent = mensaje;
    }
    async function ejecutar(registro) {
        const controlador = new AbortController();
        const espera = setTimeout(() => controlador.abort(), 15000);
        try {
            const opciones = {method: 'POST', signal: controlador.signal,
                headers: {'Accept': 'application/json', 'Idempotency-Key': registro.clave}};
            if (registro.tipo === 'form') {
                const form = new FormData();
                for (const [k,v] of Object.entries(registro.datos)) form.set(k,v);
                opciones.body = form;
            } else {
                opciones.headers['Content-Type'] = 'application/json';
                opciones.body = JSON.stringify(registro.datos);
            }
            const respuesta = await fetch(registro.url, opciones);
            if (respuesta.redirected) throw new Error('Inicia sesión para verificar el cambio pendiente.');
            const datos = await respuesta.json();
            if (datos.codigo === 'SESION_RECARGAR') throw new Error(datos.message);
            if (respuesta.status >= 500) throw new Error('No se pudo verificar el cambio. Reintenta sin repetir la operación.');
            // Validación rechazada o resultado confirmado: ya conocemos el desenlace.
            if (leer()?.clave === registro.clave) localStorage.removeItem(almacen);
            document.getElementById('operacionPendienteAviso')?.remove();
            if (!respuesta.ok || !datos.success) {
                const error = new Error(datos.message || 'No se pudo realizar el cambio');
                error.datos = datos;
                error.definitivo = true;
                throw error;
            }
            window.dispatchEvent(new CustomEvent('pedido:actualizado'));
            return datos;
        } catch (error) {
            if (!error.definitivo) aviso('Hay un cambio pendiente de verificar. No lo repitas; usa este botón cuando vuelva la conexión.');
            throw error;
        } finally {clearTimeout(espera);}
    }
    function procesar(registro) {
        if (enCurso) return enCurso;
        enCurso = ejecutar(registro).finally(() => enCurso = null);
        return enCurso;
    }
    window.operarPedido = function(url, cuerpo) {
        try {
            const ruta = new URL(url, window.location.href);
            if (ruta.origin !== window.location.origin) throw new Error('Ruta de operación inválida');
            const tipo = cuerpo instanceof FormData ? 'form' : 'json';
            const datos = tipo === 'form' ? Object.fromEntries(cuerpo) : cuerpo;
            delete datos.csrf_token;
            const anterior = leer();
            if (anterior) {
                if (anterior.url !== ruta.pathname || JSON.stringify(anterior.datos) !== JSON.stringify(datos)) {
                    aviso('Primero verifica el cambio pendiente antes de iniciar otro.');
                    throw new Error('Primero verifica el cambio pendiente.');
                }
                return procesar(anterior);
            }
            const bytes = crypto.getRandomValues(new Uint8Array(16));
            const registro = {url: ruta.pathname, tipo, datos, clave: Array.from(bytes, b => b.toString(16).padStart(2,'0')).join('')};
            localStorage.setItem(almacen, JSON.stringify(registro));
            return procesar(registro);
        } catch (error) {return Promise.reject(error);}
    };
    async function recuperar() {
        try {const pendiente = leer(); if (pendiente) return await procesar(pendiente);}
        catch (error) {if (error.definitivo) alert(error.message); throw error;}
    }
    document.addEventListener('DOMContentLoaded', () => recuperar().catch(() => {}));
    window.addEventListener('online', () => recuperar().catch(() => {}));
})();
