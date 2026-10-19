"""Cambios aditivos para bases SQLite existentes; no reescriben históricos."""
from sqlalchemy import inspect, text
from pathlib import Path
from datetime import datetime
from contextlib import closing
import sqlite3


def actualizar_esquema(engine):
    cambios = {
        'users': {'activo': 'BOOLEAN NOT NULL DEFAULT 1', 'version_sesion': 'INTEGER NOT NULL DEFAULT 0'},
        'auditoria': {'ticket_snapshot': 'JSON'},
        'pedidos': {'solicitud_id': 'VARCHAR(64)', 'metodo_pago': 'VARCHAR(20)', 'monto_efectivo': 'FLOAT', 'monto_transferencia': 'FLOAT'},
        'movimientos_caja': {'metodo_pago': 'VARCHAR(20)', 'monto_efectivo': 'FLOAT', 'monto_transferencia': 'FLOAT', 'efectivo_declarado': 'FLOAT', 'diferencia': 'FLOAT', 'resumen_corte': 'JSON'},
    }
    cambios = {tabla: columnas for tabla, columnas in cambios.items() if inspect(engine).has_table(tabla)}
    with engine.connect() as conexion:
        pendientes = any(set(columnas) - {c['name'] for c in inspect(conexion).get_columns(tabla)}
                         for tabla, columnas in cambios.items())
    if not pendientes:
        return
    # Copia consistente antes de modificar una base existente.
    ruta = engine.url.database
    if ruta and ruta != ':memory:' and engine.dialect.name == 'sqlite':
        original = Path(ruta)
        respaldo = original.with_name(original.stem + '-integrity-backup-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.db')
        with closing(sqlite3.connect(str(original))) as fuente, closing(sqlite3.connect(str(respaldo))) as destino:
            fuente.backup(destino)
    with engine.begin() as conexion:
        for tabla, columnas in cambios.items():
            existentes = {columna['name'] for columna in inspect(conexion).get_columns(tabla)}
            for nombre, tipo in columnas.items():
                if nombre not in existentes:
                    conexion.execute(text(f'ALTER TABLE {tabla} ADD COLUMN {nombre} {tipo}'))
        conexion.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS uq_pedidos_solicitud ON pedidos (solicitud_id)'))
