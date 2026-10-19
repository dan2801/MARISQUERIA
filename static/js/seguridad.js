// Solo adjuntar el token a peticiones que modifican datos en nuestro propio origen.
(() => {
    const originalFetch = window.fetch.bind(window);
    window.fetch = function(input, opciones = {}) {
        const url = new URL(typeof input === 'string' || input instanceof URL ? input : input.url, window.location.href);
        const metodo = (opciones.method || input.method || 'GET').toUpperCase();
        if (url.origin === window.location.origin && !['GET', 'HEAD', 'OPTIONS'].includes(metodo)) {
            const cabeceras = new Headers(opciones.headers || input.headers);
            const token = document.querySelector('meta[name="csrf-token"]')?.content;
            if (token) cabeceras.set('X-CSRF-Token', token);
            opciones = {...opciones, headers: cabeceras};
        }
        return originalFetch(input, opciones);
    };
})();
