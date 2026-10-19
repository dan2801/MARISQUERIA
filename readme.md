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

Pruebas en Windows:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```
