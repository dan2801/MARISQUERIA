# Para crear el entorno virtual, debes colocar lo siguiente:

 python3 -m venv .venv

 . .venv/bin/activate

 pip install -r requirements.txt

# El archivo requirements.txt debes descargarlo desde este repositorio

## Sesiones y actualizaciones

La clave de sesión se obtiene de `APP_SECRET_KEY`. Si no se define, se genera
una clave local persistente en `instance/session.key`, excluida de Git y Docker.
En un despliegue con varias instancias, configura la misma `APP_SECRET_KEY` en todas.
El modo debug está desactivado por defecto; para desarrollo se habilita con `FLASK_DEBUG=1`.

Al iniciar se agregan las columnas nuevas sin borrar registros y se crea una copia
SQLite `instance/products-integrity-backup-*.db` antes de actualizar una base existente.
La primera actualización de la clave requiere volver a iniciar sesión.

Para cobrar, el cajero debe tener una apertura activa. Los tickets cobrados permanecen
en `Pedidos`; el archivo histórico anterior se conserva sin recibir duplicados nuevos.
Las copias de auditoría se guardan para acciones nuevas. En registros anteriores se
identifica expresamente que se está mostrando el contenido actual del ticket.

Las bajas de usuarios son lógicas: conservan nombres y referencias históricas,
revocan el acceso y no permiten reutilizar el mismo nombre.

El control de existencias está deshabilitado. Las ventas no validan ni modifican
stock; el catálogo se administra por productos, categorías, precios y variantes.

El borrador de una cuenta se conserva en `sessionStorage`, separado por usuario
y pestaña, y sobrevive a una recarga. Al cerrar la pestaña, el navegador puede
eliminarlo. Los envíos usan un identificador persistido antes de enviarse: una
reconexión o reintento confirma la cuenta existente sin crear otra. Hasta recibir
confirmación, la selección queda protegida para no cambiar el contenido del envío.

Cada inicio de sesión correcto invalida la sesión anterior del mismo usuario,
incluidas sus conexiones Socket.IO. Las pestañas que comparten la misma cookie
pertenecen a una sola sesión. Cerrar sesión revoca esa cookie en el servidor.

Todas las rutas privadas declaran roles y se deniegan por defecto si no tienen
permisos explícitos. Los formularios y peticiones que modifican datos usan CSRF;
Socket.IO verifica el token al conectar. `static/js/seguridad.js` adjunta el token
solo a peticiones del mismo origen. `CSRF_ENABLED=False` se usa exclusivamente en
fixtures de pruebas generales; las pruebas de seguridad lo habilitan.
Los datos enviados por el usuario se consultan mediante parámetros de SQLAlchemy;
no se deben interpolar en SQL. Las migraciones solo interpolan nombres constantes.

Los cambios sobre cuentas (agregar/quitar, envío a caja, cobro y cancelación)
guardan una clave de operación y su respuesta en la misma transacción. Reintentar
la misma clave recupera el resultado, sin repetir el cambio. El navegador conserva
la operación pendiente en `localStorage` por usuario, incluso si se cierra, y
ofrece verificarla antes de permitir otra. No contiene contraseñas ni tokens CSRF.
Los renglones activos tienen identificadores permanentes; no se eliminan por posición.
Si cambió un precio desde la selección, se exige revisar y confirmar el nuevo importe.

Pruebas en Windows:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```
