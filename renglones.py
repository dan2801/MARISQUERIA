import json
from uuid import uuid4
from sqlalchemy import text


def actualizar_renglones(engine):
    with engine.begin() as conexion:
        for fila in conexion.execute(text("SELECT id, products FROM pedidos WHERE estado IN ('ABIERTA', 'ENVIADA_A_CAJA')")).mappings().all():
            try:
                productos = json.loads(fila['products']) if isinstance(fila['products'], str) else fila['products']
            except (ValueError, TypeError):
                continue
            if not isinstance(productos, list):
                continue
            cambiado = False
            for producto in productos or []:
                if isinstance(producto, dict) and not producto.get('linea_id'):
                    producto['linea_id'] = uuid4().hex
                    cambiado = True
            if cambiado:
                conexion.execute(text('UPDATE pedidos SET products=:productos WHERE id=:id'),
                                 {'productos': json.dumps(productos), 'id': fila['id']})
