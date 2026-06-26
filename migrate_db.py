import sqlite3

def migrate_database():
    db_path = 'instance/products.db'
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Verificar si las columnas ya existen
        cursor.execute("PRAGMA table_info(pedidos)")
        columns = [column[1] for column in cursor.fetchall()]
        
        # Agregar columnas faltantes si no existen
        if 'folio' not in columns:
            cursor.execute("ALTER TABLE pedidos ADD COLUMN folio VARCHAR(20)")
            print("Columna 'folio' agregada")
        
        if 'estado' not in columns:
            cursor.execute("ALTER TABLE pedidos ADD COLUMN estado VARCHAR(20) DEFAULT 'ABIERTA'")
            print("Columna 'estado' agregada")
        
        if 'fecha_cobro' not in columns:
            cursor.execute("ALTER TABLE pedidos ADD COLUMN fecha_cobro DATETIME")
            print("Columna 'fecha_cobro' agregada")
        
        if 'cajero_id' not in columns:
            cursor.execute("ALTER TABLE pedidos ADD COLUMN cajero_id VARCHAR(80)")
            print("Columna 'cajero_id' agregada")
        
        # Verificar si las tablas nuevas existen
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='auditoria'")
        if not cursor.fetchone():
            cursor.execute("""
                CREATE TABLE auditoria (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario_id VARCHAR(80) NOT NULL,
                    usuario_nombre VARCHAR(80) NOT NULL,
                    rol VARCHAR(80) NOT NULL,
                    accion VARCHAR(100) NOT NULL,
                    descripcion TEXT,
                    fecha_hora DATETIME DEFAULT CURRENT_TIMESTAMP,
                    pedido_id INTEGER
                )
            """)
            print("Tabla 'auditoria' creada")
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='movimientos_caja'")
        if not cursor.fetchone():
            cursor.execute("""
                CREATE TABLE movimientos_caja (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tipo_movimiento VARCHAR(50) NOT NULL,
                    monto FLOAT,
                    usuario_id VARCHAR(80) NOT NULL,
                    fecha_hora DATETIME DEFAULT CURRENT_TIMESTAMP,
                    pedido_id INTEGER
                )
            """)
            print("Tabla 'movimientos_caja' creada")
        
        conn.commit()
        conn.close()
        print("Migración completada exitosamente")
        
    except Exception as e:
        print(f"Error durante la migración: {e}")
        if conn:
            conn.rollback()
            conn.close()

if __name__ == '__main__':
    migrate_database()
