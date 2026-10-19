import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from contextlib import closing

from sqlalchemy import create_engine, inspect
from test_pedidos import app, socketio, db
from models import Users, Category, Product, Pedidos, Auditoria, MovimientosCaja
from schema_updates import actualizar_esquema


class IntegridadTests(unittest.TestCase):
    def setUp(self):
        self.carpeta = tempfile.TemporaryDirectory()
        self.contexto = app.app_context()
        self.contexto.push()
        db.session.remove()
        self.motor_anterior = db.engines[None]
        ruta = Path(self.carpeta.name) / 'concurrencia.db'
        self.motor = create_engine('sqlite:///' + ruta.as_posix(), connect_args={'timeout': 10})
        db.engines[None] = self.motor
        db.create_all()
        db.session.add_all([Users(username='mesero', password='prueba', rol='user'),
                            Users(username='cajero', password='prueba', rol='cajero')])
        producto = Product(name='Agua', price=20, stock=1, category=Category(name='Bebidas'))
        db.session.add(producto)
        db.session.flush()
        self.producto_id = producto.id
        db.session.add(MovimientosCaja(tipo_movimiento='APERTURA', usuario_id='cajero', monto_inicial=100))
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.engines[None] = self.motor_anterior
        self.motor.dispose()
        self.contexto.pop()
        self.carpeta.cleanup()

    def cliente(self, usuario, rol):
        cliente = app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['username'], sesion['tipo_usuario'] = usuario, rol
        return cliente

    def cuenta(self):
        pedido = Pedidos(estado='ENVIADA_A_CAJA', total=20, usuario_id='mesero',
                         products=[{'id': str(self.producto_id), 'nombre': 'Agua', 'precio': 20, 'cantidad': 1}])
        db.session.add(pedido)
        db.session.commit()
        identificador = pedido.id
        db.session.remove()
        return identificador

    def simultaneos(self, rutas, pedido_id):
        barrera = threading.Barrier(2)
        def ejecutar(ruta):
            cliente = self.cliente('cajero', 'cajero')
            barrera.wait(timeout=5)
            return cliente.post(ruta, json={'pedido_id': pedido_id}).status_code
        with ThreadPoolExecutor(max_workers=2) as ejecutor:
            return list(ejecutor.map(ejecutar, rutas))

    def test_dos_cobros_simultaneos_generan_una_sola_venta(self):
        pedido_id = self.cuenta()
        self.assertEqual(sorted(self.simultaneos(['/guardar_historico'] * 2, pedido_id)), [200, 400])
        self.assertEqual(MovimientosCaja.query.filter_by(tipo_movimiento='VENTA').count(), 1)
        self.assertEqual(Auditoria.query.filter_by(accion='COBRAR_PEDIDO').count(), 1)

    def test_cobrar_y_cancelar_simultaneos_no_se_mezclan(self):
        pedido_id = self.cuenta()
        self.assertEqual(sorted(self.simultaneos(['/guardar_historico', f'/delete_pedido/{pedido_id}'], pedido_id)), [200, 400])
        pedido = db.session.get(Pedidos, pedido_id)
        ventas = MovimientosCaja.query.filter_by(tipo_movimiento='VENTA').count()
        self.assertIn(pedido.estado, ('COBRADA', 'CANCELADA'))
        self.assertEqual(ventas, 1 if pedido.estado == 'COBRADA' else 0)

    def test_creaciones_simultaneas_no_se_bloquean_por_stock(self):
        eventos = self.crear_simultaneamente()
        self.assertEqual(sum('pedido_creado' in lista for lista in eventos), 2)
        self.assertEqual(sum('pedido_error' in lista for lista in eventos), 0)
        self.assertEqual(Pedidos.query.count(), 2)
        self.assertEqual(db.session.get(Product, self.producto_id).stock, 1)

    def test_creaciones_simultaneas_generan_folios_distintos(self):
        db.session.get(Product, self.producto_id).stock = 2
        db.session.commit()
        eventos = self.crear_simultaneamente()
        self.assertEqual(sum('pedido_creado' in lista for lista in eventos), 2)
        self.assertEqual({p.folio for p in Pedidos.query.all()}, {'T-000001', 'T-000002'})
        self.assertEqual(db.session.get(Product, self.producto_id).stock, 2)

    def test_cierre_y_cobro_simultaneos_cuadran_el_dinero(self):
        pedido_id = self.cuenta()
        estados = self.simultaneos(['/cerrar_caja', '/guardar_historico'], pedido_id)
        self.assertEqual(estados[0], 302)
        ventas = MovimientosCaja.query.filter_by(tipo_movimiento='VENTA').all()
        cierre = MovimientosCaja.query.filter_by(tipo_movimiento='CIERRE').one()
        self.assertEqual(cierre.monto, 100 + sum(v.monto for v in ventas))
        self.assertEqual(estados[1], 200 if ventas else 400)

    def crear_simultaneamente(self):
        db.session.remove()
        barrera = threading.Barrier(2)
        def crear(_):
            cliente = self.cliente('mesero', 'user')
            conexion = socketio.test_client(app, flask_test_client=cliente)
            try:
                barrera.wait(timeout=5)
                conexion.emit('nuevo_pedido', {'productos': [{'id': str(self.producto_id), 'cantidad': 1}]})
                return [evento['name'] for evento in conexion.get_received()]
            finally:
                conexion.disconnect()
        with ThreadPoolExecutor(max_workers=2) as ejecutor:
            eventos = list(ejecutor.map(crear, range(2)))
        return eventos

    def test_migracion_aditiva_repetible_conserva_datos(self):
        ruta = Path(self.carpeta.name) / 'antigua.db'
        with closing(sqlite3.connect(ruta)) as conexion:
            conexion.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)')
            conexion.execute('INSERT INTO users (username) VALUES (?)', ('existente',))
            conexion.execute('CREATE TABLE auditoria (id INTEGER PRIMARY KEY, accion TEXT)')
            conexion.execute('INSERT INTO auditoria (accion) VALUES (?)', ('CREAR_PEDIDO',))
            conexion.commit()
        motor = create_engine('sqlite:///' + ruta.as_posix())
        try:
            actualizar_esquema(motor)
            actualizar_esquema(motor)
            self.assertEqual(len(list(Path(self.carpeta.name).glob('antigua-integrity-backup-*.db'))), 1)
            columnas = {columna['name'] for columna in inspect(motor).get_columns('users')}
            self.assertTrue({'activo', 'version_sesion'} <= columnas)
            with motor.connect() as conexion:
                self.assertEqual(conexion.exec_driver_sql('SELECT username, activo, version_sesion FROM users').one(), ('existente', 1, 0))
                self.assertEqual(conexion.exec_driver_sql('SELECT accion, ticket_snapshot FROM auditoria').one(), ('CREAR_PEDIDO', None))
        finally:
            motor.dispose()


if __name__ == '__main__':
    unittest.main()
