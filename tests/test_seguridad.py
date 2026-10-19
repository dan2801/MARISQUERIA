from unittest.mock import patch

import test_pedidos as fixtures
from models import db, Users, Product, Category


# Reusar el fixture sin volver a heredar todos sus tests.
import unittest

app, socketio = fixtures.app, fixtures.socketio


class SeguridadTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PedidosTests()
        self.fixture.setUp()
        self.configuracion = patch.dict(app.config, CSRF_ENABLED=True)
        self.configuracion.start()
        self.cliente = self.fixture.cliente

    def tearDown(self):
        self.configuracion.stop()
        self.fixture.tearDown()

    def token(self):
        self.cliente.get('/login')
        with self.cliente.session_transaction() as sesion:
            return sesion['_csrf_token']

    def test_login_requiere_token_y_no_acepta_el_de_otro_navegador(self):
        usuario = Users.query.filter_by(username='mesero').one()
        usuario.set_password('clave')
        db.session.commit()
        datos = {'username': 'mesero', 'password': 'clave'}
        self.assertEqual(self.cliente.post('/login', data=datos).status_code, 400)
        token = self.token()
        otro = app.test_client()
        otro.get('/login')
        self.assertEqual(otro.post('/login', data={**datos, 'csrf_token': token}).status_code, 400)
        self.assertEqual(self.cliente.post('/login', data={**datos, 'csrf_token': token}).status_code, 302)
        self.assertEqual(self.cliente.get('/').status_code, 200)

    def test_rutas_directas_admin_no_disponibles_a_meseros_o_cajeros(self):
        rutas = ('/admin', '/reportes', '/tickets', '/inventario', '/auditoria', '/auditoria/ticket/1')
        for usuario, rol in (('mesero', 'user'), ('cajero', 'cajero')):
            self.fixture.sesion(usuario, rol)
            for ruta in rutas:
                self.assertEqual(self.cliente.get(ruta).status_code, 403)
        with self.cliente.session_transaction() as sesion:
            sesion.clear()
        for ruta in rutas:
            self.assertEqual(self.cliente.get(ruta).status_code, 302)

    def test_post_sin_token_no_crea_categoria_y_con_token_si(self):
        self.fixture.sesion('admin', 'admin')
        self.assertEqual(self.cliente.post('/create_category', data={'name': 'Nueva'}).status_code, 400)
        self.assertIsNone(Category.query.filter_by(name='Nueva').first())
        token = self.token()
        respuesta = self.cliente.post('/create_category', data={'name': 'Nueva'}, headers={'X-CSRF-Token': token})
        self.assertEqual(respuesta.status_code, 302)
        self.assertIsNotNone(Category.query.filter_by(name='Nueva').first())

    def test_socket_requiere_sesion_y_token_correctos(self):
        self.fixture.sesion()
        token = self.token()
        for auth in (None, {'csrf_token': 'incorrecto'}):
            conexion = socketio.test_client(app, flask_test_client=self.cliente, auth=auth)
            self.assertFalse(conexion.is_connected())
        conexion = socketio.test_client(app, flask_test_client=self.cliente, auth={'csrf_token': token})
        self.fixture.sockets.append(conexion)
        self.assertTrue(conexion.is_connected())

    def test_inyeccion_sql_en_login_no_autentica(self):
        token = self.token()
        for texto in ("admin' OR '1'='1", "' OR 1=1 --", "'; DROP TABLE users; --"):
            respuesta = self.cliente.post('/login', data={'username': texto, 'password': 'x', 'csrf_token': token})
            self.assertEqual(respuesta.status_code, 200)
            with self.cliente.session_transaction() as sesion:
                self.assertNotIn('username', sesion)
        self.assertEqual(Users.query.count(), 4)

    def test_inyeccion_sql_en_busqueda_y_nombre_se_trata_como_texto(self):
        self.fixture.sesion('admin', 'admin')
        token = self.token()
        texto = "O'Brien; DROP TABLE product; --"
        respuesta = self.cliente.post('/create_category', data={'name': texto, 'csrf_token': token})
        self.assertEqual(respuesta.status_code, 302)
        self.assertIsNotNone(Category.query.filter_by(name=texto).first())
        self.assertEqual(self.cliente.get('/tickets', query_string={'folio': "' OR 1=1 --"}).status_code, 200)
        self.assertEqual(Product.query.count(), 1)

    def test_formularios_tienen_token_y_respuestas_no_se_cachean(self):
        self.fixture.sesion('admin', 'admin')
        for ruta in ('/', '/admin', '/auditoria', '/reportes'):
            respuesta = self.cliente.get(ruta)
            self.assertEqual(respuesta.status_code, 200)
            self.assertEqual(respuesta.headers['Cache-Control'], 'no-store')
            self.assertEqual(respuesta.headers['X-Frame-Options'], 'DENY')
        html = self.cliente.get('/admin').get_data(as_text=True)
        self.assertIn('name="csrf_token"', html)

    def test_rol_falso_en_cookie_no_da_acceso_admin(self):
        self.fixture.sesion('mesero', 'admin')
        self.assertEqual(self.cliente.get('/admin').status_code, 403)

    def test_vista_sin_roles_declarados_se_deniega_por_defecto(self):
        self.fixture.sesion('admin', 'admin')
        with patch.dict(app.view_functions, reportes=lambda: 'contenido privado'):
            respuesta = self.cliente.get('/reportes')
        self.assertEqual(respuesta.status_code, 403)
        self.assertNotIn('contenido privado', respuesta.get_data(as_text=True))

    def test_flujo_pedido_y_cobro_funciona_con_csrf_activado(self):
        self.fixture.sesion()
        token = self.token()
        conexion = socketio.test_client(app, flask_test_client=self.cliente, auth={'csrf_token': token})
        self.fixture.sockets.append(conexion)
        conexion.emit('nuevo_pedido', {'productos': [self.fixture.item()]})
        from models import Pedidos
        pedido = Pedidos.query.one()
        respuesta = self.cliente.post(f'/enviar_caja/{pedido.id}', headers={'Accept': 'application/json', 'X-CSRF-Token': token})
        self.assertEqual(respuesta.status_code, 200)
        self.fixture.sesion('cajero', 'cajero')
        token = self.token()
        self.cliente.post('/abrir_caja', data={'monto_inicial': '0', 'csrf_token': token})
        respuesta = self.cliente.post('/guardar_historico', json={'pedido_id': pedido.id}, headers={'X-CSRF-Token': token})
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(pedido.estado, 'COBRADA')


if __name__ == '__main__':
    unittest.main()
