from flask import jsonify, render_template, request, redirect, url_for, flash, session, abort
from collections import defaultdict
from werkzeug.utils import secure_filename
import os
from models import db, Product, Category, Users, ProductVariant, Pedidos, PedidoHistorico, Auditoria, MovimientosCaja
from flask_socketio import emit, join_room
from datetime import datetime, timedelta
import json
from __init__ import init_app
import jinja2
from sqlalchemy.orm.attributes import flag_modified
from sales_reporting import rango_ventas, resumir_ventas
from functools import wraps
from decimal import Decimal, InvalidOperation
from sqlalchemy import text
from schema_updates import actualizar_esquema
from catalogo import datos_producto, nombre_valido, variantes_validas, guardar_imagen, borrar_imagen
import secrets
import hmac
from uuid import uuid4
from operaciones import operacion_repetible, confirmar_cambio
from renglones import actualizar_renglones

app, socketio = init_app()
app.config.setdefault('CSRF_ENABLED', True)
app.config['MAX_CONTENT_LENGTH'] = 12 * 1024 * 1024


def csrf_token():
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_urlsafe(32)
    return session['_csrf_token']


app.jinja_env.globals['csrf_token'] = csrf_token


def csrf_valido(token):
    esperado = session.get('_csrf_token')
    return isinstance(token, str) and isinstance(esperado, str) and hmac.compare_digest(token, esperado)

# Agregar filtro personalizado para parsear JSON en templates
def from_json(value):
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value

app.jinja_env.filters['from_json'] = from_json


@app.template_filter('ordenar_tamanos')
def ordenar_tamanos(variantes):
    orden = {'chico': 0, 'chica': 0, 'mediano': 1, 'mediana': 1, 'grande': 2}
    return sorted(variantes, key=lambda variante: orden.get(variante.size.strip().casefold(), 3))


def usuario_actual():
    usuario = Users.query.filter_by(username=session.get('username'), activo=True).populate_existing().first()
    if not usuario or session.get('version_sesion', 0) != usuario.version_sesion:
        return None
    return usuario


@app.before_request
def validar_sesion_actual():
    if 'username' in session:
        usuario = usuario_actual()
        if not usuario:
            session.clear()
        else:
            session['tipo_usuario'] = usuario.rol
    if request.endpoint and request.endpoint not in ('login', 'static'):
        if 'username' not in session:
            return redirect(url_for('login'))
        vista = app.view_functions.get(request.endpoint)
        permitidos = getattr(vista, 'allowed_roles', ())
        if session.get('tipo_usuario') not in permitidos:
            abort(403)
    if app.config['CSRF_ENABLED'] and request.method not in ('GET', 'HEAD', 'OPTIONS'):
        token = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token')
        if not csrf_valido(token):
            return jsonify({'success': False, 'codigo': 'SESION_RECARGAR', 'message': 'La página venció. Recárgala e intenta nuevamente.'}), 400


@app.after_request
def cabeceras_seguridad(respuesta):
    respuesta.headers['X-Content-Type-Options'] = 'nosniff'
    respuesta.headers['X-Frame-Options'] = 'DENY'
    respuesta.headers['Referrer-Policy'] = 'same-origin'
    if request.endpoint != 'static':
        respuesta.headers['Cache-Control'] = 'no-store'
    return respuesta


@app.errorhandler(403)
def acceso_denegado(error):
    if request.accept_mimetypes.best == 'application/json' or request.is_json:
        return jsonify({'success': False, 'message': 'No tienes permiso para realizar esta acción'}), 403
    return render_template('acceso_denegado.html'), 403


def escritura_serializada(f):
    """SQLite: reservar la escritura antes de leer estado, folios o existencias."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        try:
            db.session.execute(text('BEGIN IMMEDIATE'))
            if request.endpoint != 'login' and not hasattr(request, 'sid') and 'username' in session:
                if not usuario_actual():
                    session.clear()
                    db.session.rollback()
                    return redirect(url_for('login'))
            resultado = f(*args, **kwargs)
            db.session.rollback()
            return resultado
        except Exception:
            db.session.rollback()
            raise
    return wrapped


def apertura_caja_activa(username):
    ultimo = MovimientosCaja.query.filter(
        MovimientosCaja.usuario_id == username,
        MovimientosCaja.tipo_movimiento.in_(('APERTURA', 'CIERRE'))
    ).order_by(MovimientosCaja.id.desc()).first()
    return ultimo if ultimo and ultimo.tipo_movimiento == 'APERTURA' else None


def desconectar_usuario(usuario_id):
    socketio.emit('sesion_finalizada', {'message': 'Tu sesión ya no está activa. Inicia sesión nuevamente.'},
                  to=f'usuario:{usuario_id}')
    conexiones = list(socketio.server.manager.get_participants('/', f'usuario:{usuario_id}'))
    for sid, _ in conexiones:
        socketio.server.disconnect(sid, namespace='/')

# Decorador para verificar rol
def role_required(*allowed_roles):
    def decorator(f):
        def wrapped(*args, **kwargs):
            if 'username' not in session:
                return redirect(url_for('login'))
            if session.get('tipo_usuario') not in allowed_roles:
                abort(403)
            return f(*args, **kwargs)
        wrapped.__name__ = f.__name__
        wrapped.allowed_roles = allowed_roles
        return wrapped
    return decorator

# Función para generar folio consecutivo
def generar_folio():
    ultimo_pedido = Pedidos.query.filter(Pedidos.folio.isnot(None)).order_by(Pedidos.id.desc()).first()
    if ultimo_pedido and ultimo_pedido.folio:
        # Extraer número del folio (T-000001 -> 1)
        try:
            ultimo_num = int(ultimo_pedido.folio.split('-')[1])
            nuevo_num = ultimo_num + 1
        except (IndexError, ValueError):
            nuevo_num = 1
    else:
        nuevo_num = 1
    return f"T-{nuevo_num:06d}"

# Función para registrar auditoría
def registrar_auditoria(accion, descripcion=None, pedido_id=None, commit=True):
    if 'username' in session:
        usuario = Users.query.filter_by(username=session['username']).first()
        if usuario:
            auditoria = Auditoria(
                usuario_id=usuario.username,
                usuario_nombre=usuario.username,
                rol=usuario.rol,
                accion=accion,
                descripcion=descripcion,
                pedido_id=pedido_id
            )
            if pedido_id:
                pedido = db.session.get(Pedidos, pedido_id)
                if pedido:
                    auditoria.ticket_snapshot = {
                        'id': pedido.id, 'folio': pedido.folio, 'estado': pedido.estado,
                        'fecha': pedido.fecha.isoformat(),
                        'fecha_cobro': pedido.fecha_cobro.isoformat() if pedido.fecha_cobro else None,
                        'products': json.loads(json.dumps(pedido.products or [])),
                        'total': pedido.total, 'usuario_id': pedido.usuario_id, 'cajero_id': pedido.cajero_id,
                    }
            db.session.add(auditoria)
            if commit:
                db.session.commit()

# Función para registrar movimiento de cajaa
def registrar_movimiento_caja(tipo_movimiento, monto=None, monto_inicial=None, pedido_id=None, commit=True, metodo_pago=None, monto_efectivo=None, monto_transferencia=None):
    if 'username' in session:
        movimiento = MovimientosCaja(
            tipo_movimiento=tipo_movimiento,
            monto=monto,
            monto_inicial=monto_inicial,
            usuario_id=session['username'],
            pedido_id=pedido_id, metodo_pago=metodo_pago,
            monto_efectivo=monto_efectivo, monto_transferencia=monto_transferencia
        )
        db.session.add(movimiento)
        if commit:
            db.session.commit()

from models import db

db.init_app(app)

with app.app_context():
    db.create_all()
    actualizar_esquema(db.engine)
    actualizar_renglones(db.engine)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def obtener_base_nombre(nombre):
    partes = nombre.lower().split()
    if partes[-1] in ['chico', 'mediano', 'grande']:
        return ' '.join(partes[:-1])
    return nombre.lower()

@app.route('/')
@role_required('admin', 'user', 'cajero')
def index():
    from datetime import date
    
    rol = session.get('tipo_usuario')

    products = Product.query.all()
    categorias = Category.query.all()

    cat = defaultdict(list)
    for product in products:
        cat[product.category.name].append(product)

    pedidos = Pedidos.query.all()

    # Verificar estado de caja para el cajero
    caja_abierta = False
    monto_inicial = 0
    if rol == 'cajero' or rol == 'admin':
        # Buscar la apertura activa (la que NO tiene cierre posterior)
        # Usar ID en lugar de fecha porque múltiples movimientos pueden tener la misma fecha
        todas_aperturas = MovimientosCaja.query.filter(
            MovimientosCaja.tipo_movimiento == 'APERTURA',
            MovimientosCaja.usuario_id == session.get('username')
        ).order_by(MovimientosCaja.id.desc()).all()
        
        for apertura in todas_aperturas:
            # Verificar si hay un cierre después de esta apertura (por ID)
            cierre_despues = MovimientosCaja.query.filter(
                MovimientosCaja.tipo_movimiento == 'CIERRE',
                MovimientosCaja.usuario_id == session.get('username'),
                MovimientosCaja.id > apertura.id
            ).first()
            
            # Solo está abierta si NO hay cierre después de la apertura
            if not cierre_despues:
                caja_abierta = True
                monto_inicial = apertura.monto_inicial
                break

    if rol == 'admin':
        return render_template('index.html', cat=cat, categoriaslist=categorias, caja_abierta=caja_abierta, monto_inicial=monto_inicial)
    elif rol == 'user':
        # Filtrar solo pedidos ABIERTA para el mesero
        pedidos_mesa = Pedidos.query.filter_by(usuario_id=session['username'], estado='ABIERTA').all()
        return render_template('index_user.html', cat=cat, categoriaslist=categorias, pedidos_mesa=pedidos_mesa)
    elif rol == 'cajero':
        usuarios = Users.query.all()
        # Filtrar solo pedidos ENVIADA_A_CAJA para el cajero (no mostrar COBRADA ni CANCELADA)
        pedidos_caja = Pedidos.query.filter_by(estado='ENVIADA_A_CAJA').all()
        # Agrupar pedidos por usuario
        pedidos_por_usuario = defaultdict(list)
        for pedido in pedidos_caja:
            pedidos_por_usuario[pedido.usuario_id].append(pedido)
        return render_template('index_cajero.html', cat=cat, categoriaslist=categorias, pedidos_por_usuario=pedidos_por_usuario, usuarios=usuarios, caja_abierta=caja_abierta, monto_inicial=monto_inicial, apertura=apertura_caja_activa(session['username']))
    else:
        return redirect(url_for('login'))

@socketio.on('connect')
def conectar_notificaciones(auth=None):
    if app.config['CSRF_ENABLED'] and not csrf_valido((auth or {}).get('csrf_token') if isinstance(auth, dict) else None):
        return False
    usuario = usuario_actual()
    if not usuario:
        return False
    join_room(f'usuario:{usuario.id}')
    if usuario.rol == 'cajero':
        join_room('notificaciones_caja')


@socketio.on('nuevo_pedido')
@escritura_serializada
def pedido_handler(data):
    usuario = usuario_actual()
    if not usuario or usuario.rol not in ('user', 'admin'):
        emit('pedido_error', {'error': 'No tienes permiso para crear pedidos',
                              'solicitud_id': data.get('solicitud_id') if isinstance(data, dict) else None})
        return
    try:
        solicitud_id = data.get('solicitud_id') if isinstance(data, dict) else None
        if solicitud_id is not None:
            if not isinstance(solicitud_id, str) or not 16 <= len(solicitud_id) <= 64 or not all(c.isascii() and (c.isalnum() or c == '-') for c in solicitud_id):
                raise ValueError('Identificador de envío inválido')
            existente = Pedidos.query.filter_by(solicitud_id=solicitud_id).first()
            if existente:
                if existente.usuario_id != usuario.username:
                    raise ValueError('Identificador de envío inválido')
                emit('pedido_creado', {'id': existente.id, 'folio': existente.folio, 'solicitud_id': solicitud_id})
                return
        if not isinstance(data, dict) or not isinstance(data.get('productos'), list) or not data['productos']:
            raise ValueError('El pedido debe contener productos')

        productos = []
        precios_cambiaron = False
        for item in data['productos']:
            if not isinstance(item, dict):
                raise ValueError('Producto inválido')
            cantidad = item.get('cantidad')
            if type(cantidad) is not int or cantidad <= 0:
                raise ValueError('La cantidad debe ser un entero positivo')
            partes = str(item.get('id', '')).split('_')
            if len(partes) not in (1, 2) or not all(p.isdigit() for p in partes):
                raise ValueError('Identificador de producto inválido')
            producto = db.session.get(Product, int(partes[0]))
            if not producto:
                raise ValueError('Producto no encontrado')
            nombre, precio = producto.name, producto.price
            if len(partes) == 2:
                variante = db.session.get(ProductVariant, int(partes[1]))
                if not variante or variante.product_id != producto.id:
                    raise ValueError('Variante de producto inválida')
                nombre, precio = f'{producto.name} {variante.size}', variante.price
            if 'precio' in item and Decimal(str(item['precio'])) != Decimal(str(precio)):
                precios_cambiaron = True
            identificador = '_'.join(partes)
            repetido = next((p for p in productos if p['id'] == identificador), None)
            if repetido:
                repetido['cantidad'] += cantidad
            else:
                productos.append({'id': identificador, 'nombre': nombre, 'precio': precio, 'cantidad': cantidad,
                                  'linea_id': uuid4().hex})
        if precios_cambiaron:
            emit('pedido_error', {'error': 'Los precios cambiaron. Revisa el total actualizado y vuelve a confirmar.',
                                  'codigo': 'PRECIOS_CAMBIARON', 'productos_actualizados': productos,
                                  'solicitud_id': solicitud_id})
            return

        pedido = Pedidos(
            folio=generar_folio(),
            estado='ABIERTA',
            total=float(sum((Decimal(str(p['precio'])) * p['cantidad'] for p in productos), Decimal('0'))),
            state='pendiente',
            fecha=datetime.now(),
            products=productos,
            usuario_id=session['username'],
            solicitud_id=solicitud_id
        )
        db.session.add(pedido)
        db.session.flush()
        
        # Registrar auditoría
        registrar_auditoria('CREAR_PEDIDO', f'Pedido {pedido.folio} creado por {session["username"]}', pedido.id, commit=False)
        db.session.commit()
        
        # Emitir evento para actualizar vista del mesero en tiempo real
        socketio.emit('nuevo_pedido_creado', {'id': pedido.id, 'folio': pedido.folio, 'usuario_id': session['username']})

        emit('pedido_creado', {'id': pedido.id, 'folio': pedido.folio, 'solicitud_id': solicitud_id,
                               'total': pedido.total, 'state': pedido.state, 'fecha': pedido.fecha.strftime('%Y-%m-%d %H:%M:%S')})
    except Exception as e:
        db.session.rollback()
        print('Error al crear el pedido: ' + str(e))
        validacion = isinstance(e, (ValueError, InvalidOperation))
        emit('pedido_error', {'error': str(e) if validacion else 'No se pudo verificar el envío. Reintenta para consultar si se guardó.',
                              'codigo': 'VALIDACION' if validacion else 'ESTADO_DESCONOCIDO',
                              'solicitud_id': data.get('solicitud_id') if isinstance(data, dict) else None})

@app.route('/guardar_historico', methods=['POST'])
@role_required('cajero', 'admin')
@escritura_serializada
@operacion_repetible
def guardar_historico():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or type(data.get('pedido_id')) is not int:
        return jsonify({'success': False, 'message': 'Pedido inválido'}), 400

    metodo_pago = data.get('metodo_pago', 'EFECTIVO')
    if metodo_pago not in ('EFECTIVO', 'TRANSFERENCIA', 'MIXTO'):
        return jsonify({'success': False, 'message': 'Selecciona una forma de pago válida'}), 400

    # Datos del pedido actual
    pedido_id = data.get('pedido_id')

    pedido = Pedidos.query.get(pedido_id)
    if not pedido:
        return jsonify({'success': False, 'message': 'Pedido no encontrado'}), 404
    
    # Verificar que el pedido no esté ya cobrado
    if pedido.estado != 'ENVIADA_A_CAJA':
        return jsonify({'success': False, 'message': 'Solo se pueden cobrar pedidos enviados a caja'}), 400
    if not apertura_caja_activa(session['username']):
        return jsonify({'success': False, 'message': 'Abre la caja antes de cobrar pedidos'}), 400
    if not pedido.products or not pedido.total or pedido.total <= 0:
        return jsonify({'success': False, 'message': 'No puedes cobrar una cuenta vacía'}), 400
    
    total_pago = Decimal(str(pedido.total)).quantize(Decimal('0.01'))
    efectivo_pago = total_pago if metodo_pago == 'EFECTIVO' else Decimal('0')
    if metodo_pago == 'MIXTO':
        try:
            efectivo_pago = Decimal(str(data.get('monto_efectivo', '')))
            if (not efectivo_pago.is_finite() or not 0 < efectivo_pago < total_pago
                    or efectivo_pago != efectivo_pago.quantize(Decimal('0.01'))):
                raise ValueError
        except (ValueError, InvalidOperation):
            return jsonify({'success': False, 'message': 'El efectivo debe ser mayor a cero y menor al total, con máximo dos decimales'}), 400
    transferencia_pago = total_pago - efectivo_pago

    # Guardar el desglose junto al cobro, en una sola transacción.
    pedido.metodo_pago = metodo_pago
    pedido.monto_efectivo = float(efectivo_pago)
    pedido.monto_transferencia = float(transferencia_pago)
    pedido.estado = 'COBRADA'
    pedido.fecha_cobro = datetime.now()
    pedido.cajero_id = session['username']
    
    # Pedidos conserva el ticket cobrado; el archivo antiguo ya no recibe copias.
    
    # Registrar movimiento de caja
    registrar_movimiento_caja('VENTA', monto=pedido.total, pedido_id=pedido.id, commit=False, metodo_pago=metodo_pago,
                             monto_efectivo=float(efectivo_pago), monto_transferencia=float(transferencia_pago))
    
    # Registrar auditoría
    registrar_auditoria('COBRAR_PEDIDO', f'Pedido {pedido.folio} cobrado por {session["username"]}', pedido.id, commit=False)
    
    confirmar_cambio({'success': True, 'message': 'Pedido cobrado y guardado en historial'})
    
    # Emitir evento para que el cajero actualice su vista
    socketio.emit('pedido_cobrado', {'id': pedido.id, 'folio': pedido.folio})
    
    return jsonify({'success': True, 'message': 'Pedido cobrado y guardado en historial'})

@app.route('/ticket/<int:id>')
@role_required('cajero', 'admin')
def ticket(id):
    pedido = Pedidos.query.get_or_404(id)
    return render_template('ticket.html', pedido=pedido)

@app.route('/delete_pedido/<int:pedido_id>', methods=['POST'])
@role_required('user', 'cajero', 'admin')
@escritura_serializada
@operacion_repetible
def delete_pedido(pedido_id):
    pedido = Pedidos.query.get_or_404(pedido_id)

    if session['tipo_usuario'] == 'user' and pedido.usuario_id != session['username']:
        return jsonify({'success': False, 'message': 'No puedes cancelar este pedido'}), 403
    if pedido.estado not in ('ABIERTA', 'ENVIADA_A_CAJA'):
        return jsonify({'success': False, 'message': 'El pedido ya fue cobrado o cancelado'}), 400

    # Cambiar estado a CANCELADA en lugar de eliminar
    pedido.estado = 'CANCELADA'
    
    # Registrar auditoría
    registrar_auditoria('CANCELAR_PEDIDO', f'Pedido {pedido.folio} cancelado por {session["username"]}', pedido.id, commit=False)
    
    confirmar_cambio()

    # Emitir evento para que todos actualicen en tiempo real
    socketio.emit('pedido_eliminado', {'id': pedido_id})

    return {'success': True}

@app.route('/login', methods=['GET', 'POST'])
@escritura_serializada
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = Users.query.filter_by(username=username, activo=True).populate_existing().first()
        if user and user.check_password(password):
            user.version_sesion += 1
            db.session.commit()
            desconectar_usuario(user.id)
            session.clear()
            session['username'] = user.username
            session['tipo_usuario'] = user.rol
            session['version_sesion'] = user.version_sesion
            return redirect(url_for('index'))
        else:
            flash('Usuario o contraseña incorrectos', 'error')
    if request.method == 'GET' and request.args.get('sesion') == 'finalizada':
        flash('Tu sesión se cerró porque se inició en otro dispositivo o fue desactivada.', 'error')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
@role_required('admin')
@escritura_serializada
def register():
    if request.method == 'POST' and session['tipo_usuario'] == 'admin':
        username = request.form['username']
        password = request.form['password']
        rol = request.form['rol']
        if not username.strip() or rol not in ('admin', 'user', 'cajero') or not password:
            flash('Revisa el usuario, la contraseña y el rol', 'error')
            return redirect(url_for('admin'))
        if Users.query.filter_by(username=username).first():
            flash('El nombre de usuario ya está registrado', 'error')
            return redirect(url_for('admin'))
        user = Users(username=username, rol=rol)
        user.set_password(password)
        db.session.add(user)
        registrar_auditoria('CREAR_USUARIO', f'Usuario {username} creado con rol {rol}', commit=False)
        db.session.commit()
        return redirect(request.referrer or url_for('admin'))
    else:
        return redirect(url_for('index'))

@app.route('/reportes', methods=['GET'])
@role_required('admin')
def reportes():
    hoy = datetime.now().date()
    error = None
    try:
        inicio, fin = rango_ventas(request.args, hoy)
    except ValueError as exc:
        error = str(exc)
        inicio, fin = rango_ventas({}, hoy)
    comparar = request.args.get('comparar') == '1'
    limite = inicio - timedelta(days=(fin - inicio).days + 1) if comparar else inicio
    ventas = [] if error else Pedidos.query.filter(
        Pedidos.estado == 'COBRADA', Pedidos.fecha_cobro >= datetime.combine(limite, datetime.min.time()),
        Pedidos.fecha_cobro < datetime.combine(fin + timedelta(days=1), datetime.min.time())
    ).all()
    resumen = resumir_ventas(ventas, inicio, fin, comparar)
    return render_template('reportes.html', resumen=resumen, inicio=inicio, fin=fin, comparar=comparar,
                           periodo=request.args.get('periodo', 'semana'), error=error,
                           sin_fecha=Pedidos.query.filter_by(estado='COBRADA', fecha_cobro=None).count())

@app.route('/tickets')
@role_required('admin')
def tickets():
    archivo = request.args.get('archivo') == '1'
    estado = request.args.get('estado', '')
    folio = request.args.get('folio', '').strip()
    consulta = Pedidos.query
    if estado in ('ABIERTA', 'ENVIADA_A_CAJA', 'COBRADA', 'CANCELADA'):
        consulta = consulta.filter_by(estado=estado)
    if folio:
        consulta = consulta.filter(Pedidos.folio.contains(folio, autoescape=True))
    pagina = max(request.args.get('pagina', 1, type=int) or 1, 1)
    resultados = (PedidoHistorico.query.order_by(PedidoHistorico.fecha.desc(), PedidoHistorico.id.desc())
                  if archivo else consulta.order_by(Pedidos.fecha.desc(), Pedidos.id.desc()))
    paginacion = resultados.paginate(page=pagina, per_page=30, error_out=False)
    return render_template('tickets.html', paginacion=paginacion, archivo=archivo, estado=estado, folio=folio)

@app.route('/tickets/archivo/<int:ticket_id>')
@role_required('admin')
def ticket_archivo(ticket_id):
    historico = PedidoHistorico.query.get_or_404(ticket_id)
    productos = from_json(historico.productos)
    pedido = dict(id=f'Archivo-{historico.id}', folio=None, fecha=historico.fecha,
                  products=productos if isinstance(productos, list) else [], total=historico.total or 0,
                  estado='HISTÓRICO', usuario_id='No registrado')
    return render_template('ticket.html', pedido=pedido, vista_auditoria=True)

@app.route('/logout', methods=['POST'])
@role_required('admin', 'user', 'cajero')
@escritura_serializada
def logout():
    usuario = usuario_actual() if 'username' in session else None
    if usuario:
        registrar_auditoria('CERRAR_SESION', f'Usuario {session["username"]} cerró sesión', commit=False)
        usuario.version_sesion += 1
        db.session.commit()
        desconectar_usuario(usuario.id)
    session.clear()
    return redirect(url_for('login'))

@app.route('/abrir_caja', methods=['POST'])
@role_required('cajero', 'admin')
@escritura_serializada
def abrir_caja():
    # Verificar si ya hay una apertura activa (sin cierre posterior)
    # Usar ID en lugar de fecha porque múltiples movimientos pueden tener la misma fecha
    todas_aperturas = MovimientosCaja.query.filter(
        MovimientosCaja.tipo_movimiento == 'APERTURA',
        MovimientosCaja.usuario_id == session['username']
    ).order_by(MovimientosCaja.id.desc()).all()
    
    for apertura in todas_aperturas:
        # Verificar si hay un cierre después de esta apertura (por ID)
        cierre_despues = MovimientosCaja.query.filter(
            MovimientosCaja.tipo_movimiento == 'CIERRE',
            MovimientosCaja.usuario_id == session['username'],
            MovimientosCaja.id > apertura.id
        ).first()
        
        # Si NO hay cierre después, la caja sigue abierta
        if not cierre_despues:
            flash(f'La caja ya está abierta con monto inicial: ${apertura.monto_inicial}. Debe cerrarla antes de abrirla nuevamente.', 'error')
            return redirect(url_for('index'))
    
    try:
        monto = Decimal(request.form.get('monto_inicial') or '0')
        if not monto.is_finite() or monto < 0 or monto > Decimal('999999999.99'):
            raise ValueError
        monto_inicial = float(monto.quantize(Decimal('0.01')))
    except (ValueError, InvalidOperation):
        flash('El monto inicial debe ser un número válido mayor o igual a cero', 'error')
        return redirect(url_for('index'))
    
    registrar_movimiento_caja('APERTURA', monto_inicial=monto_inicial, commit=False)
    registrar_auditoria('ABRIR_CAJA', f'Caja abierta por {session["username"]} con monto inicial: ${monto_inicial}', commit=False)
    db.session.commit()
    flash(f'Caja abierta correctamente. Monto inicial: ${monto_inicial}', 'success')
    return redirect(url_for('index'))

@app.route('/cerrar_caja', methods=['POST'])
@role_required('cajero', 'admin')
@escritura_serializada
def cerrar_caja():
    # Obtener la última apertura de caja que NO tiene cierre posterior
    # Usar ID en lugar de fecha porque múltiples movimientos pueden tener la misma fecha
    todas_aperturas = MovimientosCaja.query.filter(
        MovimientosCaja.tipo_movimiento == 'APERTURA',
        MovimientosCaja.usuario_id == session['username']
    ).order_by(MovimientosCaja.id.desc()).all()
    
    apertura_activa = None
    for apertura in todas_aperturas:
        # Verificar si hay un cierre después de esta apertura (por ID)
        cierre_despues = MovimientosCaja.query.filter(
            MovimientosCaja.tipo_movimiento == 'CIERRE',
            MovimientosCaja.usuario_id == session['username'],
            MovimientosCaja.id > apertura.id
        ).first()
        
        if not cierre_despues:
            apertura_activa = apertura
            break
    
    if not apertura_activa:
        flash('No hay una apertura de caja activa para cerrar.', 'error')
        return redirect(url_for('index'))
    
    # Filtrar ventas solo entre la apertura activa y ahora (por ID)
    ventas = MovimientosCaja.query.filter(
        MovimientosCaja.tipo_movimiento == 'VENTA',
        MovimientosCaja.usuario_id == session['username'],
        MovimientosCaja.id > apertura_activa.id
    ).all()
    
    try:
        declarado = Decimal(request.form.get('efectivo_declarado', ''))
        if not declarado.is_finite() or declarado < 0 or declarado > Decimal('999999999.99'):
            raise ValueError
        declarado = declarado.quantize(Decimal('0.01'))
    except (ValueError, InvalidOperation):
        flash('Ingresa el efectivo contado para registrar el corte.', 'error')
        return redirect(url_for('index'))

    efectivo = sum((Decimal(str(v.monto_efectivo if v.monto_efectivo is not None else
                     (v.monto or 0) if v.metodo_pago in (None, 'EFECTIVO') else 0)) for v in ventas), Decimal('0'))
    transferencias = sum((Decimal(str(v.monto_transferencia if v.monto_transferencia is not None else
                          (v.monto or 0) if v.metodo_pago == 'TRANSFERENCIA' else 0)) for v in ventas), Decimal('0'))
    fondo = Decimal(str(apertura_activa.monto_inicial or 0))
    esperado = fondo + efectivo
    diferencia = declarado - esperado
    resumen = dict(apertura_id=apertura_activa.id, fondo=float(fondo), efectivo=float(efectivo),
                   transferencias=float(transferencias), ventas=float(efectivo + transferencias),
                   esperado=float(esperado), declaracion=float(declarado), diferencia=float(diferencia))
    db.session.add(MovimientosCaja(tipo_movimiento='CIERRE', monto=float(esperado),
        usuario_id=session['username'], efectivo_declarado=float(declarado),
        diferencia=float(diferencia), resumen_corte=resumen))
    registrar_auditoria('CERRAR_CAJA',
        f'Corte de {session["username"]}. Fondo: ${fondo:.2f}, ventas efectivo: ${efectivo:.2f}, '
        f'transferencias: ${transferencias:.2f}, esperado: ${esperado:.2f}, '
        f'declarado: ${declarado:.2f}, diferencia: ${diferencia:.2f}', commit=False)
    db.session.commit()
    flash('Corte registrado. Turno finalizado.', 'success')
    return redirect(url_for('index'))

@app.route('/cortes')
@role_required('admin')
def cortes():
    pagina = max(1, request.args.get('pagina', 1, type=int) or 1)
    registros = MovimientosCaja.query.filter_by(tipo_movimiento='CIERRE').order_by(
        MovimientosCaja.id.desc()).paginate(page=pagina, per_page=30, error_out=False)
    return render_template('cortes.html', registros=registros)


@app.route('/auditoria')
@role_required('admin')
def auditoria():
    grupos = {
        'usuarios': ('Usuarios', {
            'CREAR_USUARIO': 'Creación de usuario', 'EDITAR_USUARIO': 'Edición de usuario',
            'ELIMINAR_USUARIO': 'Eliminación de usuario'}),
        'caja': ('Caja', {'ABRIR_CAJA': 'Apertura de caja', 'CERRAR_CAJA': 'Cierre de caja'}),
        'pedidos': ('Pedidos', {
            'CREAR_PEDIDO': 'Creación de pedido', 'ENVIAR_CAJA': 'Envío a caja',
            'COBRAR_PEDIDO': 'Pedido cobrado / cerrado', 'CANCELAR_PEDIDO': 'Pedido cancelado'}),
        'cambios': ('Cambios en pedidos', {
            'AGREGAR_PRODUCTO': 'Producto agregado', 'ELIMINAR_PRODUCTO': 'Producto eliminado'}),
        'sesiones': ('Sesiones', {'CERRAR_SESION': 'Cierre de sesión'}),
        'catalogo': ('Catálogo', {'CREAR_PRODUCTO': 'Creación de producto', 'EDITAR_PRODUCTO': 'Edición de producto',
                                 'ELIMINAR_PRODUCTO_CATALOGO': 'Eliminación de producto', 'CREAR_CATEGORIA': 'Creación de categoría',
                                 'ELIMINAR_CATEGORIA': 'Eliminación de categoría'})
    }
    etiquetas = {clave: nombre for _, acciones in grupos.values() for clave, nombre in acciones.items()}
    hoy = datetime.now().date().isoformat()
    filtros = {
        'accion': request.args.get('accion', '').strip(),
        'periodo': request.args.get('periodo', 'hoy'),
        'desde': request.args.get('desde', hoy), 'hasta': request.args.get('hasta', hoy),
        'usuario': request.args.get('usuario', '').strip(),
        'folio': request.args.get('folio', '').strip()
    }
    consulta = Auditoria.query
    error = None
    try:
        accion = filtros['accion']
        if accion in grupos:
            consulta = consulta.filter(Auditoria.accion.in_(grupos[accion][1]))
        elif accion in etiquetas:
            consulta = consulta.filter(Auditoria.accion == accion)
        elif accion:
            raise ValueError('Selecciona una acción válida.')
        if filtros['periodo'] == 'hoy':
            inicio = datetime.fromisoformat(hoy)
            consulta = consulta.filter(Auditoria.fecha_hora >= inicio,
                                       Auditoria.fecha_hora < inicio + timedelta(days=1))
        elif filtros['periodo'] == 'rango':
            desde = datetime.strptime(filtros['desde'], '%Y-%m-%d') if filtros['desde'] else None
            hasta = datetime.strptime(filtros['hasta'], '%Y-%m-%d') if filtros['hasta'] else None
            if not desde and not hasta:
                raise ValueError('Indica al menos una fecha para el rango.')
            if desde and hasta and desde > hasta:
                raise ValueError('La fecha inicial no puede ser posterior a la final.')
            if desde:
                consulta = consulta.filter(Auditoria.fecha_hora >= desde)
            if hasta:
                consulta = consulta.filter(Auditoria.fecha_hora < hasta + timedelta(days=1))
        elif filtros['periodo'] != 'todo':
            raise ValueError('Selecciona un periodo válido.')
        if filtros['usuario']:
            consulta = consulta.filter(Auditoria.usuario_nombre == filtros['usuario'])
        if filtros['folio']:
            consulta = consulta.filter(Auditoria.pedido.has(Pedidos.folio.contains(filtros['folio'], autoescape=True)))
    except (ValueError, OverflowError) as exc:
        error = str(exc) if str(exc).endswith('.') else 'Revisa las fechas del rango.'
    registros = [] if error else consulta.order_by(Auditoria.fecha_hora.desc(), Auditoria.id.desc()).all()
    usuarios = [fila[0] for fila in db.session.query(Auditoria.usuario_nombre).distinct().order_by(Auditoria.usuario_nombre).all()]
    return render_template('auditoria.html', registros=registros, grupos=grupos,
                           etiquetas=etiquetas, filtros=filtros, usuarios=usuarios, error=error)

@app.route('/auditoria/ticket/<int:pedido_id>')
@role_required('admin')
def ticket_auditoria(pedido_id):
    pedido = Pedidos.query.get_or_404(pedido_id)
    return render_template('ticket.html', pedido=pedido, vista_auditoria=True)

@app.route('/auditoria/registro/<int:registro_id>/ticket')
@role_required('admin')
def ticket_registro_auditoria(registro_id):
    registro = Auditoria.query.get_or_404(registro_id)
    if registro.ticket_snapshot:
        pedido = dict(registro.ticket_snapshot)
        pedido['fecha'] = datetime.fromisoformat(pedido['fecha'])
        return render_template('ticket.html', pedido=pedido, vista_auditoria=True,
                               nota_ticket='Contenido guardado al registrar esta acción.')
    pedido = Pedidos.query.get_or_404(registro.pedido_id)
    return render_template('ticket.html', pedido=pedido, vista_auditoria=True,
                           nota_ticket='Registro anterior sin copia: se muestra el contenido actual del ticket.')

@app.route('/enviar_caja/<int:pedido_id>', methods=['POST'])
@role_required('user', 'admin')
@escritura_serializada
@operacion_repetible
def enviar_caja(pedido_id):
    pedido = Pedidos.query.get_or_404(pedido_id)
    if session['tipo_usuario'] == 'user' and pedido.usuario_id != session['username']:
        return jsonify({'success': False, 'message': 'No puedes enviar este pedido a caja'}), 403
    
    if pedido.estado != 'ABIERTA':
        if request.accept_mimetypes.best == 'application/json':
            return jsonify({'success': False, 'message': 'Solo se pueden enviar pedidos en estado ABIERTA'}), 400
        flash('Solo se pueden enviar pedidos en estado ABIERTA', 'error')
        return redirect(request.referrer or url_for('index'))
    if not pedido.products or not pedido.total or pedido.total <= 0:
        return jsonify({'success': False, 'message': 'Agrega productos antes de enviar la cuenta a caja'}), 400
    
    pedido.estado = 'ENVIADA_A_CAJA'
    registrar_auditoria('ENVIAR_CAJA', f'Pedido {pedido.folio} enviado a caja por {session["username"]}', pedido.id, commit=False)
    confirmar_cambio()

    socketio.emit('ticket_enviado_caja', {
        'id': pedido.id, 'folio': pedido.folio, 'usuario_id': pedido.usuario_id
    }, to='notificaciones_caja')
    
    if request.accept_mimetypes.best == 'application/json':
        return jsonify({'success': True})
    return redirect(request.referrer or url_for('index'))

@app.route('/agregar_producto_pedido/<int:pedido_id>', methods=['POST'])
@role_required('user', 'admin')
@escritura_serializada
@operacion_repetible
def agregar_producto_pedido(pedido_id):
    pedido = Pedidos.query.get_or_404(pedido_id)
    
    # Verificar que el pedido pertenezca al usuario y esté ABIERTA
    if pedido.usuario_id != session['username'] or pedido.estado != 'ABIERTA':
        return jsonify({'success': False, 'message': 'No puedes editar este pedido'}), 403
    
    producto_id = request.form.get('producto_id')
    try:
        cantidad = int(request.form.get('cantidad', 1))
        if cantidad <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': 'La cantidad debe ser un entero positivo'}), 400
    
    partes = str(producto_id or '').split('_')
    if len(partes) not in (1, 2) or not all(p.isdigit() for p in partes):
        return jsonify({'success': False, 'message': 'Selecciona un producto válido'}), 400
    producto = db.session.get(Product, int(partes[0]))
    if not producto:
        return jsonify({'success': False, 'message': 'Producto no encontrado'}), 404
    nombre, precio = producto.name, producto.price
    if len(partes) == 2:
        variante = db.session.get(ProductVariant, int(partes[1]))
        if not variante or variante.product_id != producto.id:
            return jsonify({'success': False, 'message': 'Selecciona un tamaño válido'}), 400
        nombre, precio = f'{producto.name} {variante.size}', variante.price
    esperado = request.form.get('precio_esperado')
    if esperado is not None:
        try:
            cambio = Decimal(esperado) != Decimal(str(precio))
        except InvalidOperation:
            cambio = True
        if cambio:
            return jsonify(success=False, codigo='PRECIO_CAMBIO', precio=precio,
                           message='El precio cambió. Revisa el importe y confirma nuevamente.'), 409

    
    # Agregar producto al pedido
    productos_actuales = pedido.products if pedido.products else []
    for renglon in productos_actuales:
        renglon.setdefault('linea_id', uuid4().hex)
    
    # Verificar si el producto ya está en el pedido (comparar por nombre para evitar problemas con IDs compuestos)
    producto_existente = next((p for p in productos_actuales
                              if str(p['id']) == producto_id and p['precio'] == precio), None)
    
    if producto_existente:
        producto_existente['cantidad'] += cantidad
    else:
        productos_actuales.append({
            'id': producto_id,
            'nombre': nombre,
            'precio': precio,
            'cantidad': cantidad,
            'linea_id': uuid4().hex
        })
    
    pedido.products = productos_actuales
    pedido.total = float(sum((Decimal(str(p['precio'])) * p['cantidad'] for p in productos_actuales), Decimal('0')))
    
    # Marcar el campo products como modificado para que SQLAlchemy lo guarde
    flag_modified(pedido, 'products')
    
    registrar_auditoria('AGREGAR_PRODUCTO', f'Agregado {cantidad}x {nombre} al pedido {pedido.folio}', pedido.id, commit=False)
    confirmar_cambio({'success': True, 'message': 'Producto agregado al pedido'})
    
    # Emitir evento para actualizar vista del mesero
    socketio.emit('pedido_actualizado', {'id': pedido.id, 'usuario_id': session['username']})
    
    return jsonify({'success': True, 'message': 'Producto agregado al pedido'})

@app.route('/eliminar_producto_pedido/<int:pedido_id>', methods=['POST'])
@role_required('user', 'admin')
@escritura_serializada
@operacion_repetible
def eliminar_producto_pedido(pedido_id):
    pedido = Pedidos.query.get_or_404(pedido_id)
    
    # Verificar que el pedido pertenezca al usuario y esté ABIERTA
    if pedido.usuario_id != session['username'] or pedido.estado != 'ABIERTA':
        if request.accept_mimetypes.best == 'application/json':
            return jsonify({'success': False, 'message': 'No puedes editar este pedido'}), 403
        flash('No puedes editar este pedido', 'error')
        return redirect(request.referrer or url_for('index'))
    
    producto_id = request.form.get('producto_id')
    
    productos_actuales = pedido.products if pedido.products else []
    
    # Encontrar y eliminar el producto (comparar por ID que viene del formulario)
    linea_id = request.form.get('linea_id')
    if linea_id:
        producto_a_eliminar = next((p for p in productos_actuales if p.get('linea_id') == linea_id and str(p['id']) == producto_id), None)
    else:
        coincidencias = [p for p in productos_actuales if str(p['id']) == producto_id]
        if len(coincidencias) > 1:
            return jsonify(success=False, message='Recarga las mesas para identificar el renglón correcto'), 409
        producto_a_eliminar = coincidencias[0] if coincidencias else None
    
    if producto_a_eliminar:
        productos_actuales.remove(producto_a_eliminar)
        
        pedido.products = productos_actuales
        pedido.total = float(sum((Decimal(str(p['precio'])) * p['cantidad'] for p in productos_actuales), Decimal('0')))
        
        # Marcar el campo products como modificado para que SQLAlchemy lo guarde
        flag_modified(pedido, 'products')
        
        
        registrar_auditoria('ELIMINAR_PRODUCTO', f'Eliminado {producto_a_eliminar["nombre"]} del pedido {pedido.folio}', pedido.id, commit=False)
        confirmar_cambio()
        
        # Emitir evento para actualizar vista del mesero
        socketio.emit('pedido_actualizado', {'id': pedido.id, 'usuario_id': session['username']})
        
        if request.accept_mimetypes.best == 'application/json':
            return jsonify({'success': True})
        return redirect(request.referrer or url_for('index'))
    else:
        if request.accept_mimetypes.best == 'application/json':
            return jsonify({'success': False, 'message': 'Producto no encontrado en el pedido'}), 404
        flash('Producto no encontrado en el pedido', 'error')
        return redirect(request.referrer or url_for('index'))

@app.route('/create', methods=['POST'])
@role_required('admin')
@escritura_serializada
def create():
    imagen = None
    try:
        datos = datos_producto(request.form)
        variantes = variantes_validas(request.form.getlist('size[]'), request.form.getlist('price[]'))
        imagen = guardar_imagen(request.files.get('image'), app.config['UPLOAD_FOLDER'])
        producto = Product(**datos, image=imagen or '')
        db.session.add(producto)
        db.session.flush()
        for tamano, precio in variantes:
            db.session.add(ProductVariant(size=tamano, price=precio, product_id=producto.id))
        registrar_auditoria('CREAR_PRODUCTO', f'Producto {producto.name} creado', commit=False)
        db.session.commit()
        flash('Producto creado con éxito', 'success')
    except Exception as exc:
        db.session.rollback()
        if imagen:
            borrar_imagen(imagen, app.config['UPLOAD_FOLDER'])
        flash(str(exc) if isinstance(exc, ValueError) else 'No se pudo guardar el producto', 'error')
    return redirect(request.referrer or url_for('index'))

@app.route('/create_category', methods=['POST'])
@role_required('admin')
@escritura_serializada
def create_category():
    try:
        nombre = nombre_valido(request.form.get('name'))
        if any(c.name.casefold() == nombre.casefold() for c in Category.query.all()):
            raise ValueError('La categoría ya existe')
        db.session.add(Category(name=nombre))
        registrar_auditoria('CREAR_CATEGORIA', f'Categoría {nombre} creada', commit=False)
        db.session.commit()
        flash('Categoría creada con éxito', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(str(exc) if isinstance(exc, ValueError) else 'No se pudo guardar la categoría', 'error')
    return redirect(request.referrer or url_for('index'))

@app.route('/delete_category', methods=['POST'])
@role_required('admin')
@escritura_serializada
def delete_category():
    try:
        categoria = db.session.get(Category, int(request.form.get('categoria', '')))
        if not categoria:
            raise ValueError('La categoría no existe')
        if Product.query.filter_by(categoria=categoria.id).first():
            raise ValueError('La categoría contiene productos; muévelos o elimínalos primero')
        nombre = categoria.name
        db.session.delete(categoria)
        registrar_auditoria('ELIMINAR_CATEGORIA', f'Categoría {nombre} eliminada', commit=False)
        db.session.commit()
        flash('Categoría eliminada con éxito', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(str(exc) if isinstance(exc, ValueError) else 'No se pudo eliminar la categoría', 'error')
    return redirect(request.referrer or url_for('index'))

@app.route('/admin', methods=['GET'])
@role_required('admin')
def admin():
    return render_template('admin.html', users=Users.query.filter_by(activo=True).all())

@app.route('/edit_user/<int:id>', methods=['POST'])
@role_required('admin')
@escritura_serializada
def edit_user(id):
    user = Users.query.get_or_404(id)

    if request.method == 'POST':
        new_username = request.form['username']
        new_rol = request.form['rol']
        if not new_username.strip() or new_rol not in ('admin', 'user', 'cajero'):
            flash('Revisa el nombre y el rol del usuario', 'error')
            return redirect(url_for('admin'))
        if Users.query.filter(Users.username == new_username, Users.id != user.id).first():
            flash('El nombre de usuario ya está registrado', 'error')
            return redirect(url_for('admin'))
        
        # Validar que el usuario no cambie su propio rol a algo que no sea admin
        if user.username == session.get('username') and new_rol != 'admin':
            flash('No puedes cambiar tu propio rol a algo diferente de admin', 'error')
            return redirect(request.referrer or url_for('admin'))
        
        anterior = user.username
        propio = anterior == session.get('username')
        # Las referencias al nombre se actualizan juntas dentro de la transacción.
        db.session.execute(text('PRAGMA defer_foreign_keys = ON'))
        registrar_auditoria('EDITAR_USUARIO', f'Usuario {anterior} editado por {session["username"]}', commit=False)
        Pedidos.query.filter_by(usuario_id=anterior).update({'usuario_id': new_username})
        Pedidos.query.filter_by(cajero_id=anterior).update({'cajero_id': new_username})
        MovimientosCaja.query.filter_by(usuario_id=anterior).update({'usuario_id': new_username})
        user.username = new_username
        user.rol = new_rol
        user.version_sesion += 1
        
        # Actualizar contraseña si se proporciona
        password = request.form.get('password')
        if password and password.strip():
            user.set_password(password)
        
        db.session.commit()
        if propio:
            session['username'] = user.username
            session['version_sesion'] = user.version_sesion
        desconectar_usuario(user.id)
        
        return redirect(request.referrer or url_for('admin'))

@app.route('/delete_user/<int:id>', methods=['POST'])
@role_required('admin')
@escritura_serializada
def delete_user(id):
    user = Users.query.get_or_404(id)
    
    # Validar que el usuario no se elimine a sí mismo
    if user.username == session.get('username'):
        flash('No puedes eliminar tu propio usuario', 'error')
        return redirect(request.referrer or url_for('admin'))
    
    # Verificar si el usuario tiene pedidos ACTIVOS (solo bloquear si hay pedidos abiertos)
    pedidos_activos = Pedidos.query.filter(Pedidos.usuario_id == user.username,
                                          Pedidos.estado.in_(('ABIERTA', 'ENVIADA_A_CAJA'))).first()
    if pedidos_activos:
        flash('No puedes eliminar un usuario que tiene pedidos activos', 'error')
        return redirect(request.referrer or url_for('admin'))
    
    if apertura_caja_activa(user.username):
        flash('Cierra la caja del usuario antes de darlo de baja', 'error')
        return redirect(url_for('admin'))
    
    # Registrar auditoría antes de eliminar
    registrar_auditoria('ELIMINAR_USUARIO', f'Usuario {user.username} dado de baja por {session["username"]}', commit=False)
    
    user.activo = False
    user.version_sesion += 1
    db.session.commit()
    desconectar_usuario(user.id)
    return redirect(request.referrer or url_for('admin'))

@app.route('/edit/<int:id>', methods=['POST'])
@role_required('admin')
@escritura_serializada
def edit(id):
    producto = Product.query.get_or_404(id)
    nueva_imagen = None
    anterior = producto.image
    try:
        datos = datos_producto(request.form, producto.id, producto.stock)
        ids = request.form.getlist('variant_id[]')
        tamanos, precios = request.form.getlist('size[]'), request.form.getlist('price[]')
        if len(ids) != len(tamanos) or len(ids) != len(precios) or len(set(ids)) != len(ids):
            raise ValueError('Revisa las variantes del producto')
        cambios, usados = [], set()
        for identificador, tamano, precio in zip(ids, tamanos, precios):
            variante = db.session.get(ProductVariant, int(identificador))
            if not variante or variante.product_id != producto.id:
                raise ValueError('La variante no pertenece a este producto')
            if not tamano.strip() and not precio.strip():
                cambios.append((variante, None))
            else:
                cambios.append((variante, variantes_validas([tamano], [precio], usados)[0]))
        enviados = {int(i) for i in ids}
        for variante in producto.variants:
            if variante.id not in enviados:
                clave = variante.size.casefold()
                if clave in usados:
                    raise ValueError('No puede haber tamaños duplicados')
                usados.add(clave)
        nuevas = variantes_validas(request.form.getlist('new_size[]'), request.form.getlist('new_price[]'), usados)
        nueva_imagen = guardar_imagen(request.files.get('image'), app.config['UPLOAD_FOLDER'])
        for campo, valor in datos.items():
            setattr(producto, campo, valor)
        if nueva_imagen:
            producto.image = nueva_imagen
        for variante, valores in cambios:
            if valores is None:
                db.session.delete(variante)
            else:
                variante.size, variante.price = valores
        for tamano, precio in nuevas:
            db.session.add(ProductVariant(size=tamano, price=precio, product_id=producto.id))
        registrar_auditoria('EDITAR_PRODUCTO', f'Producto {producto.name} actualizado', commit=False)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        if nueva_imagen:
            borrar_imagen(nueva_imagen, app.config['UPLOAD_FOLDER'])
        flash(str(exc) if isinstance(exc, ValueError) else 'No se pudo actualizar el producto', 'error')
        return redirect(request.referrer or url_for('index'))
    if nueva_imagen and anterior and not Product.query.filter_by(image=anterior).first():
        try:
            borrar_imagen(anterior, app.config['UPLOAD_FOLDER'])
        except OSError:
            app.logger.warning('No se pudo retirar una imagen anterior')
    flash('Producto actualizado con éxito', 'success')
    return redirect(request.referrer or url_for('index'))

@app.route('/delete/<int:id>', methods=['POST'])
@role_required('admin')
@escritura_serializada
def delete(id):
    producto = Product.query.get_or_404(id)
    for pedido in Pedidos.query.filter(Pedidos.estado.in_(('ABIERTA', 'ENVIADA_A_CAJA'))).all():
        if any(str(p.get('id', '')).split('_')[0] == str(id) for p in pedido.products or []):
            flash('El producto está en una cuenta pendiente; termina esa cuenta antes de eliminarlo', 'error')
            return redirect(request.referrer or url_for('index'))
    imagen, nombre = producto.image, producto.name
    try:
        for variante in producto.variants:
            db.session.delete(variante)
        db.session.delete(producto)
        registrar_auditoria('ELIMINAR_PRODUCTO_CATALOGO', f'Producto {nombre} eliminado del catálogo', commit=False)
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash('No se pudo eliminar el producto', 'error')
        return redirect(request.referrer or url_for('index'))
    if imagen and not Product.query.filter_by(image=imagen).first():
        try:
            borrar_imagen(imagen, app.config['UPLOAD_FOLDER'])
        except OSError:
            app.logger.warning('No se pudo retirar una imagen del catálogo')
    flash('Producto eliminado con éxito', 'success')
    return redirect(request.referrer or url_for('index'))

@app.route('/inventario')
@role_required('admin')
def inventario():
    products = Product.query.all()
    categorias = Category.query.all()

    cat = defaultdict(list)
    for product in products:
        cat[product.category.name].append(product)
    return render_template('inventario.html', cat=cat, categoriaslist=categorias)


if __name__ == '__main__':
    desarrollo = os.environ.get('FLASK_DEBUG') == '1'
    socketio.run(app, debug=desarrollo, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)
