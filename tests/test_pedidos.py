import unittest
from flask import template_rendered
from datetime import datetime, timedelta
from unittest.mock import patch

import __init__ as configuracion


# Configurar una base efímera antes de importar app, que crea sus tablas.
inicializar = configuracion.init_app


def inicializar_pruebas():
    app, socketio = inicializar()
    app.config.update(SQLALCHEMY_DATABASE_URI='sqlite://', TESTING=True)
    return app, socketio


with patch.object(configuracion, 'init_app', inicializar_pruebas):
    from app import app, socketio

from models import db, Product, Category, ProductVariant, Users, Pedidos, PedidoHistorico, Auditoria, MovimientosCaja
from sales_reporting import resumir_ventas


class PedidosTests(unittest.TestCase):
    def reporte(self, filtros):
        contextos = []
        def guardar_contexto(sender, template, context, **extra):
            contextos.append(context)
        template_rendered.connect(guardar_contexto, app)
        try:
            respuesta = self.cliente.get('/reportes', query_string=filtros)
            self.assertEqual(respuesta.status_code, 200)
            return respuesta, contextos[-1]
        finally:
            template_rendered.disconnect(guardar_contexto, app)

    def venta(self, fecha, total, estado='COBRADA'):
        pedido = Pedidos(estado=estado, usuario_id='mesero', fecha=datetime(2026, 1, 1),
                         fecha_cobro=fecha, total=total, products=[])
        db.session.add(pedido)
        db.session.commit()
        return pedido

    def test_reportes_suman_solo_cobrados_sin_duplicar_historico(self):
        self.venta(datetime(2026, 10, 12, 12), 200)
        self.venta(datetime(2026, 10, 13, 23, 59, 59), 350)
        self.venta(datetime(2026, 10, 13, 10), 150)
        self.venta(datetime(2026, 10, 13, 10), 900, 'CANCELADA')
        self.venta(datetime(2026, 10, 13, 10), 800, 'ENVIADA_A_CAJA')
        self.venta(datetime(2026, 10, 15), 700)
        db.session.add(PedidoHistorico(total=700, fecha=datetime(2026, 10, 13), productos='[]'))
        db.session.commit()
        self.sesion('admin', 'admin')
        respuesta, contexto = self.reporte({'periodo': 'rango', 'desde': '2026-10-12', 'hasta': '2026-10-14'})
        resumen = contexto['resumen']
        self.assertEqual(resumen['total'], 700)
        self.assertEqual(resumen['cantidad'], 3)
        self.assertEqual([b['actual'] for b in resumen['barras']], [200, 500, 0])
        self.assertEqual(resumen['mejor_dia'], datetime(2026, 10, 13).date())
        self.assertIn('Mar 13/10', respuesta.get_data(as_text=True))
        self.assertNotIn('Ver ticket', respuesta.get_data(as_text=True))

    def test_reportes_comparan_periodos_de_igual_duracion(self):
        self.venta(datetime(2026, 10, 10, 12), 100)
        self.venta(datetime(2026, 10, 12, 12), 300)
        self.sesion('admin', 'admin')
        _, contexto = self.reporte({'periodo': 'rango', 'desde': '2026-10-12', 'hasta': '2026-10-13', 'comparar': '1'})
        resumen = contexto['resumen']
        self.assertEqual(resumen['total'], 300)
        self.assertEqual(resumen['anterior'], 100)
        self.assertEqual(resumen['cambio'], 200)
        self.assertEqual([b['anterior'] for b in resumen['barras']], [100, 0])

    def test_reportes_dia_horas_sin_ventas_y_rangos_invalidos(self):
        self.venta(datetime(2026, 10, 12, 9, 30), 0.1)
        self.venta(datetime(2026, 10, 12, 9, 45), 0.2)
        self.sesion('admin', 'admin')
        _, contexto = self.reporte({'periodo': 'rango', 'desde': '2026-10-12', 'hasta': '2026-10-12', 'comparar': '1'})
        resumen = contexto['resumen']
        self.assertEqual(str(resumen['total']), '0.30')
        self.assertEqual(len(resumen['barras']), 24)
        self.assertEqual(resumen['barras'][9]['tickets'], 2)
        self.assertIsNone(resumen['cambio'])
        for desde, hasta in [('2026-10-13', '2026-10-12'), ('invalida', '2026-10-12'), ('2020-01-01', '2026-10-12')]:
            _, contexto = self.reporte({'periodo': 'rango', 'desde': desde, 'hasta': hasta})
            self.assertIsNotNone(contexto['error'])

    def test_agrupacion_mensual_con_inicio_parcial_y_comparacion(self):
        ventas = [self.venta(datetime(2026, 2, 28), 100), self.venta(datetime(2026, 6, 2), 200)]
        resumen = resumir_ventas(ventas, datetime(2026, 2, 15).date(), datetime(2026, 6, 3).date(), True)
        self.assertEqual(resumen['agrupacion'], 'mes')
        self.assertEqual(len(resumen['barras']), 5)
        self.assertEqual(sum(b['actual'] for b in resumen['barras']), 300)
        self.assertEqual(resumen['barras'][-1]['actual'], 200)

    def test_tickets_filtran_y_archivo_permite_reimpresion(self):
        pedido = self.pedido('COBRADA')
        db.session.add(PedidoHistorico(total=40, fecha=datetime.now(), productos='[{"nombre":"Agua", "precio":20,"cantidad":2}]'))
        db.session.commit()
        self.sesion('admin', 'admin')
        html = self.cliente.get('/tickets', query_string={'estado': 'COBRADA', 'folio': '000001'}).get_data(as_text=True)
        self.assertIn('T-000001', html)
        self.assertIn(f'/auditoria/ticket/{pedido.id}', html)
        html = self.cliente.get('/tickets', query_string={'estado': 'CANCELADA'}).get_data(as_text=True)
        self.assertNotIn('<td>T-000001</td>', html)
        archivo = PedidoHistorico.query.one()
        respuesta = self.cliente.get('/tickets?archivo=1')
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn(f'/tickets/archivo/{archivo.id}', respuesta.get_data(as_text=True))
        respuesta = self.cliente.get(f'/tickets/archivo/{archivo.id}')
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('2 x Agua', respuesta.get_data(as_text=True))
        self.assertIn('Reimprimir ticket', respuesta.get_data(as_text=True))

    def test_reportes_y_tickets_requieren_admin(self):
        self.sesion('mesero', 'user')
        for ruta in ('/reportes', '/tickets', '/tickets/archivo/1'):
            self.assertEqual(self.cliente.get(ruta).status_code, 302)

    def setUp(self):
        self.contexto = app.app_context()
        self.contexto.push()
        db.drop_all()
        db.create_all()
        self.cliente = app.test_client()
        self.sockets = []
        db.session.add_all([
            Users(username='mesero', password='prueba', rol='user'),
            Users(username='otro', password='prueba', rol='user'),
            Users(username='cajero', password='prueba', rol='cajero'),
            Users(username='admin', password='prueba', rol='admin'),
        ])
        categoria = Category(name='Bebidas')
        self.producto = Product(name='Agua', price=20, stock=5, category=categoria)
        db.session.add(self.producto)
        db.session.flush()
        self.variante = ProductVariant(size='Grande', price=30, product_id=self.producto.id)
        db.session.add(self.variante)
        db.session.commit()

    def tearDown(self):
        for cliente in self.sockets:
            if cliente.is_connected():
                cliente.disconnect()
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def sesion(self, usuario='mesero', rol='user'):
        with self.cliente.session_transaction() as sesion:
            sesion['username'] = usuario
            sesion['tipo_usuario'] = rol

    def conectar(self):
        cliente = socketio.test_client(app, flask_test_client=self.cliente)
        self.sockets.append(cliente)
        return cliente

    def item(self, cantidad=1, variante=False):
        identificador = str(self.producto.id)
        if variante:
            identificador += f'_{self.variante.id}'
        return {'id': identificador, 'nombre': 'Nombre manipulado', 'precio': 0.01, 'cantidad': cantidad}

    def crear(self, productos):
        self.sesion()
        cliente = self.conectar()
        cliente.emit('nuevo_pedido', {'productos': productos, 'total': 0.01})
        return cliente.get_received()

    def pedido(self, estado='ENVIADA_A_CAJA'):
        pedido = Pedidos(folio='T-000001', estado=estado, usuario_id='mesero', total=40,
                         products=[{'id': str(self.producto.id), 'nombre': 'Agua', 'precio': 20, 'cantidad': 2}])
        db.session.add(pedido)
        db.session.commit()
        return pedido

    def test_stock_insuficiente_no_deja_pedido_auditoria_ni_descuento(self):
        eventos = self.crear([self.item(2), self.item(4)])
        self.assertIn('pedido_error', [e['name'] for e in eventos])
        self.assertNotIn('nuevo_pedido_creado', [e['name'] for e in eventos])
        self.assertEqual(Pedidos.query.count(), 0)
        self.assertEqual(Auditoria.query.count(), 0)
        self.assertEqual(db.session.get(Product, self.producto.id).stock, 5)

    def test_variante_descuenta_stock_y_usa_precio_del_catalogo(self):
        eventos = self.crear([self.item(2, variante=True)])
        self.assertIn('pedido_creado', [e['name'] for e in eventos])
        pedido = Pedidos.query.one()
        self.assertEqual(pedido.total, 60)
        self.assertEqual(pedido.products[0]['nombre'], 'Agua Grande')
        self.assertEqual(self.producto.stock, 3)
        self.assertEqual(Auditoria.query.one().pedido_id, pedido.id)

    def test_cantidades_invalidas_no_crean_pedidos(self):
        for cantidad in (0, -1, 1.5, '2', True):
            with self.subTest(cantidad=cantidad):
                self.crear([self.item(cantidad)])
                self.assertEqual(Pedidos.query.count(), 0)
                self.assertEqual(self.producto.stock, 5)

    def test_fallo_al_guardar_revierte_pedido_y_stock(self):
        self.sesion()
        cliente = self.conectar()
        with patch.object(db.session, 'commit', side_effect=RuntimeError('Fallo simulado')):
            cliente.emit('nuevo_pedido', {'productos': [self.item(2)]})
        self.assertEqual(Pedidos.query.count(), 0)
        self.assertEqual(Auditoria.query.count(), 0)
        self.assertEqual(self.producto.stock, 5)

    def test_crear_requiere_rol_autorizado(self):
        for usuario, rol in ((None, None), ('cajero', 'cajero')):
            with self.cliente.session_transaction() as sesion:
                sesion.clear()
            if usuario:
                self.sesion(usuario, rol)
            cliente = self.conectar()
            if usuario is None:
                self.assertFalse(cliente.is_connected())
                continue
            cliente.emit('nuevo_pedido', {'productos': [self.item()]})
            self.assertIn('pedido_error', [e['name'] for e in cliente.get_received()])
        self.assertEqual(Pedidos.query.count(), 0)

    def test_producto_o_variante_inexistente_no_crean_pedido(self):
        for identificador in ('99999', f'{self.producto.id}_99999'):
            item = self.item()
            item['id'] = identificador
            eventos = self.crear([item])
            self.assertIn('pedido_error', [e['name'] for e in eventos])
            self.assertEqual(Pedidos.query.count(), 0)
            self.assertEqual(self.producto.stock, 5)

    def test_agregar_rechaza_stock_insuficiente_y_cantidad_negativa(self):
        pedido = self.pedido('ABIERTA')
        self.sesion()
        for cantidad in ('6', '-1', 'abc'):
            respuesta = self.cliente.post(f'/agregar_producto_pedido/{pedido.id}',
                                         data={'producto_id': self.producto.id, 'cantidad': cantidad})
            self.assertEqual(respuesta.status_code, 400)
            db.session.expire_all()
            self.assertEqual(pedido.products[0]['cantidad'], 2)
            self.assertEqual(pedido.total, 40)
            self.assertEqual(self.producto.stock, 5)

    def test_cobro_asocia_venta_y_no_se_duplica(self):
        pedido = self.pedido()
        self.sesion('cajero', 'cajero')
        respuesta = self.cliente.post('/guardar_historico', json={'pedido_id': pedido.id})
        self.assertEqual(respuesta.status_code, 200)
        venta = MovimientosCaja.query.one()
        self.assertEqual(venta.pedido_id, pedido.id)
        self.assertEqual(venta.monto, 40)
        self.assertIsNone(venta.monto_inicial)
        self.assertEqual(pedido.estado, 'COBRADA')
        self.assertEqual(pedido.cajero_id, 'cajero')
        self.assertIsNotNone(pedido.fecha_cobro)
        self.assertEqual(self.cliente.post('/guardar_historico', json={'pedido_id': pedido.id}).status_code, 400)
        self.assertEqual(PedidoHistorico.query.count(), 1)
        self.assertEqual(MovimientosCaja.query.count(), 1)

    def test_cobro_rechaza_estados_incorrectos(self):
        pedido = self.pedido('ABIERTA')
        self.sesion('cajero', 'cajero')
        for estado in ('ABIERTA', 'CANCELADA', 'COBRADA'):
            pedido.estado = estado
            db.session.commit()
            self.assertEqual(self.cliente.post('/guardar_historico', json={'pedido_id': pedido.id}).status_code, 400)
        self.assertEqual(MovimientosCaja.query.count(), 0)

    def test_mesero_no_puede_cobrar_ni_operar_pedido_ajeno(self):
        pedido = self.pedido('ABIERTA')
        self.sesion('otro', 'user')
        self.assertEqual(self.cliente.post('/guardar_historico', json={'pedido_id': pedido.id}).status_code, 302)
        self.assertEqual(self.cliente.post(f'/delete_pedido/{pedido.id}').status_code, 403)
        self.assertEqual(self.cliente.post(f'/enviar_caja/{pedido.id}').status_code, 403)
        self.assertEqual(pedido.estado, 'ABIERTA')

    def test_cancelar_restituye_stock_una_sola_vez(self):
        pedido = self.pedido('ABIERTA')
        self.producto.stock = 3
        db.session.commit()
        self.sesion()
        self.assertEqual(self.cliente.post(f'/delete_pedido/{pedido.id}').status_code, 200)
        self.assertEqual(self.producto.stock, 5)
        self.assertEqual(self.cliente.post(f'/delete_pedido/{pedido.id}').status_code, 400)
        self.assertEqual(self.producto.stock, 5)

    def test_cancelacion_en_caja_no_suma_a_ventas_ni_cierre(self):
        pedido = self.pedido()
        self.sesion('cajero', 'cajero')
        self.cliente.post('/abrir_caja', data={'monto_inicial': '100'})
        respuesta = self.cliente.post(f'/delete_pedido/{pedido.id}')
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(pedido.estado, 'CANCELADA')
        self.assertIsNone(pedido.fecha_cobro)
        self.assertEqual(PedidoHistorico.query.count(), 0)
        self.assertEqual(MovimientosCaja.query.filter_by(tipo_movimiento='VENTA').count(), 0)
        self.assertEqual(Auditoria.query.filter_by(accion='CANCELAR_PEDIDO', pedido_id=pedido.id).count(), 1)
        self.assertEqual(self.cliente.post('/guardar_historico', json={'pedido_id': pedido.id}).status_code, 400)
        self.cliente.post('/cerrar_caja')
        self.assertEqual(MovimientosCaja.query.filter_by(tipo_movimiento='CIERRE').one().monto, 100)
        self.assertEqual(self.cliente.get('/').get_data(as_text=True).count('onclick="cancelarPedidoCaja('), 0)

    def test_no_se_puede_cancelar_una_cuenta_cobrada(self):
        pedido = self.pedido()
        self.sesion('cajero', 'cajero')
        self.assertEqual(self.cliente.post('/guardar_historico', json={'pedido_id': pedido.id}).status_code, 200)
        stock = self.producto.stock
        self.assertEqual(self.cliente.post(f'/delete_pedido/{pedido.id}').status_code, 400)
        self.assertEqual(pedido.estado, 'COBRADA')
        self.assertEqual(self.producto.stock, stock)
        self.assertEqual(PedidoHistorico.query.one().total, 40)
        self.assertEqual(MovimientosCaja.query.filter_by(tipo_movimiento='VENTA').one().monto, 40)

    def test_ticket_muestra_folio_productos_y_total(self):
        pedido = self.pedido()
        self.sesion('cajero', 'cajero')
        respuesta = self.cliente.get(f'/ticket/{pedido.id}')
        self.assertEqual(respuesta.status_code, 200)
        for texto in ('T-000001', '2 x Agua', '$20.00', '$40.00'):
            self.assertIn(texto, respuesta.get_data(as_text=True))
        self.assertEqual(self.cliente.get('/ticket/99999').status_code, 404)

    def test_auditoria_enlaza_ticket_y_solo_permite_reimprimir(self):
        pedido = self.pedido('CANCELADA')
        db.session.add(Auditoria(usuario_id='cajero', usuario_nombre='cajero', rol='cajero',
                                 accion='CANCELAR_PEDIDO', pedido_id=pedido.id))
        db.session.commit()
        self.sesion('admin', 'admin')
        listado = self.cliente.get('/auditoria')
        self.assertEqual(listado.status_code, 200)
        self.assertIn(f'/auditoria/ticket/{pedido.id}', listado.get_data(as_text=True))
        self.assertIn('T-000001', listado.get_data(as_text=True))
        respuesta = self.cliente.get(f'/auditoria/ticket/{pedido.id}')
        self.assertEqual(respuesta.status_code, 200)
        html = respuesta.get_data(as_text=True)
        for texto in ('2 x Agua', '$40.00', 'CANCELADA', 'Reimprimir ticket'):
            self.assertIn(texto, html)
        self.assertEqual(html.count('<button'), 1)
        self.assertNotIn('<script>', html)
        self.assertEqual(pedido.estado, 'CANCELADA')
        self.assertEqual(MovimientosCaja.query.count(), 0)
        self.assertEqual(PedidoHistorico.query.count(), 0)
        self.assertEqual(self.cliente.get('/auditoria/ticket/99999').status_code, 404)

    def test_ticket_auditoria_es_exclusivo_de_admin(self):
        pedido = self.pedido()
        for usuario, rol in (('mesero', 'user'), ('cajero', 'cajero')):
            self.sesion(usuario, rol)
            self.assertEqual(self.cliente.get(f'/auditoria/ticket/{pedido.id}').status_code, 302)

    def test_auditoria_hoy_historial_y_filtros_combinados(self):
        pedido = self.pedido('CANCELADA')
        hoy = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        ayer = hoy - timedelta(days=1)
        db.session.add_all([
            Auditoria(usuario_id='mesero', usuario_nombre='mesero', rol='user', accion='CREAR_PEDIDO',
                      descripcion='registro-hoy', fecha_hora=hoy, pedido_id=pedido.id),
            Auditoria(usuario_id='cajero', usuario_nombre='cajero', rol='cajero', accion='CANCELAR_PEDIDO',
                      descripcion='registro-ayer', fecha_hora=ayer + timedelta(hours=23, minutes=59), pedido_id=pedido.id),
            Auditoria(usuario_id='borrado', usuario_nombre='borrado', rol='cajero', accion='ABRIR_CAJA',
                      descripcion='registro-caja', fecha_hora=hoy),
        ])
        db.session.commit()
        self.sesion('admin', 'admin')
        html = self.cliente.get('/auditoria').get_data(as_text=True)
        self.assertIn('registro-hoy', html)
        self.assertNotIn('registro-ayer', html)
        self.assertIn('borrado', html)
        html = self.cliente.get('/auditoria', query_string={'periodo': 'todo', 'accion': 'pedidos'}).get_data(as_text=True)
        self.assertIn('registro-hoy', html)
        self.assertIn('registro-ayer', html)
        self.assertNotIn('registro-caja', html)
        html = self.cliente.get('/auditoria', query_string={
            'periodo': 'rango', 'desde': ayer.date().isoformat(), 'hasta': ayer.date().isoformat(),
            'accion': 'CANCELAR_PEDIDO', 'usuario': 'cajero', 'folio': '000001'
        }).get_data(as_text=True)
        self.assertIn('registro-ayer', html)
        self.assertNotIn('registro-hoy', html)
        self.assertNotIn('registro-caja', html)

    def test_auditoria_rechaza_rango_invertido_y_folio_literal(self):
        pedido = self.pedido()
        db.session.add(Auditoria(usuario_id='mesero', usuario_nombre='mesero', rol='user',
                                 accion='CREAR_PEDIDO', descripcion='registro-filtrable', pedido_id=pedido.id))
        db.session.commit()
        self.sesion('admin', 'admin')
        respuesta = self.cliente.get('/auditoria', query_string={
            'periodo': 'rango', 'desde': '2026-10-20', 'hasta': '2026-10-01'})
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('La fecha inicial no puede ser posterior', respuesta.get_data(as_text=True))
        self.assertNotIn('registro-filtrable', respuesta.get_data(as_text=True))
        respuesta = self.cliente.get('/auditoria', query_string={'periodo': 'todo', 'folio': '%'})
        self.assertNotIn('registro-filtrable', respuesta.get_data(as_text=True))
        respuesta = self.cliente.get('/auditoria', query_string={'periodo': 'rango', 'desde': 'invalida'})
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('Revisa las fechas', respuesta.get_data(as_text=True))

    def test_creacion_usuario_queda_en_auditoria(self):
        self.sesion('admin', 'admin')
        respuesta = self.cliente.post('/register', data={'username': 'nuevo', 'password': 'clave-prueba', 'rol': 'user'})
        self.assertEqual(respuesta.status_code, 302)
        self.assertIsNotNone(Users.query.filter_by(username='nuevo').first())
        registro = Auditoria.query.filter_by(accion='CREAR_USUARIO').one()
        self.assertEqual(registro.usuario_nombre, 'admin')
        self.assertIn('nuevo', registro.descripcion)
        self.assertNotIn('clave-prueba', registro.descripcion)

    def test_enviar_caja_responde_sin_redireccion_ni_aviso_success(self):
        pedido = self.pedido('ABIERTA')
        self.sesion()
        respuesta = self.cliente.post(f'/enviar_caja/{pedido.id}', headers={'Accept': 'application/json'})
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.get_json()['success'])
        self.assertEqual(pedido.estado, 'ENVIADA_A_CAJA')
        with self.cliente.session_transaction() as sesion:
            self.assertFalse(sesion.get('_flashes'))

    def test_envio_notifica_solo_a_cajeros_y_no_se_repite(self):
        pedido = self.pedido('ABIERTA')
        cliente_caja = app.test_client()
        with cliente_caja.session_transaction() as sesion:
            sesion['username'] = 'cajero'
            sesion['tipo_usuario'] = 'cajero'
        caja = socketio.test_client(app, flask_test_client=cliente_caja)
        self.sockets.append(caja)
        self.sesion()
        mesero = self.conectar()
        respuesta = self.cliente.post(f'/enviar_caja/{pedido.id}', headers={'Accept': 'application/json'})
        self.assertEqual(respuesta.status_code, 200)
        eventos = [evento for evento in caja.get_received() if evento['name'] == 'ticket_enviado_caja']
        self.assertEqual(len(eventos), 1)
        self.assertEqual(eventos[0]['args'][0], {'id': pedido.id, 'folio': pedido.folio, 'usuario_id': 'mesero'})
        self.assertNotIn('ticket_enviado_caja', [evento['name'] for evento in mesero.get_received()])
        self.assertEqual(self.cliente.post(f'/enviar_caja/{pedido.id}',
                                          headers={'Accept': 'application/json'}).status_code, 400)
        self.assertEqual(caja.get_received(), [])

    def test_caja_renderiza_control_sonido_y_cuentas_agrupadas(self):
        self.pedido()
        self.sesion('cajero', 'cajero')
        respuesta = self.cliente.get('/')
        self.assertEqual(respuesta.status_code, 200)
        html = respuesta.get_data(as_text=True)
        self.assertNotIn('id="activarSonidoCaja"', html)
        for texto in ('estadoSonidoCaja', 'avisoTicketCaja', 'pedidosCaja', 'Pedidos de mesero', 'js/caja.js'):
            self.assertIn(texto, html)

    def test_quitar_producto_responde_sin_redireccion_ni_aviso_success(self):
        pedido = self.pedido('ABIERTA')
        self.sesion()
        respuesta = self.cliente.post(f'/eliminar_producto_pedido/{pedido.id}',
                                     data={'producto_id': str(self.producto.id)},
                                     headers={'Accept': 'application/json'})
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.get_json()['success'])
        self.assertEqual(pedido.products, [])
        self.assertEqual(pedido.total, 0)
        with self.cliente.session_transaction() as sesion:
            self.assertFalse(sesion.get('_flashes'))

    def test_operaciones_sin_sesion_no_modifican_pedido(self):
        pedido = self.pedido()
        for ruta in ('/guardar_historico', f'/delete_pedido/{pedido.id}'):
            self.assertEqual(self.cliente.post(ruta, json={'pedido_id': pedido.id}).status_code, 302)
        self.assertEqual(pedido.estado, 'ENVIADA_A_CAJA')

    def test_fechas_se_generan_al_insertar(self):
        # Un límite posterior al import detecta el antiguo default congelado.
        desde = datetime.now()
        pedido = self.pedido()
        historico = PedidoHistorico(total=0)
        auditoria = Auditoria(usuario_id='mesero', usuario_nombre='mesero', rol='user', accion='PRUEBA')
        movimiento = MovimientosCaja(tipo_movimiento='APERTURA', usuario_id='cajero')
        db.session.add_all([historico, auditoria, movimiento])
        db.session.commit()
        for fecha in (pedido.fecha, historico.fecha, auditoria.fecha_hora, movimiento.fecha_hora):
            self.assertGreaterEqual(fecha, desde)
            self.assertLessEqual(fecha, datetime.now() + timedelta(seconds=1))


if __name__ == '__main__':
    unittest.main()
