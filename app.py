from flask import jsonify, render_template, request, redirect, url_for, flash, session
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

app, socketio = init_app()
app.secret_key = b'_5#y2L"F4Q8z\n\xec]/'

# Agregar filtro personalizado para parsear JSON en templates
def from_json(value):
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value

app.jinja_env.filters['from_json'] = from_json

# Decorador para verificar rol
def role_required(*allowed_roles):
    def decorator(f):
        def wrapped(*args, **kwargs):
            if 'username' not in session:
                return redirect(url_for('login'))
            if session.get('tipo_usuario') not in allowed_roles:
                flash('No tienes permiso para acceder a esta página', 'error')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        wrapped.__name__ = f.__name__
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
            db.session.add(auditoria)
            if commit:
                db.session.commit()

# Función para registrar movimiento de cajaa
def registrar_movimiento_caja(tipo_movimiento, monto=None, monto_inicial=None, pedido_id=None, commit=True):
    if 'username' in session:
        movimiento = MovimientosCaja(
            tipo_movimiento=tipo_movimiento,
            monto=monto,
            monto_inicial=monto_inicial,
            usuario_id=session['username'],
            pedido_id=pedido_id
        )
        db.session.add(movimiento)
        if commit:
            db.session.commit()

from models import db

db.init_app(app)

with app.app_context():
    db.create_all()

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def obtener_base_nombre(nombre):
    partes = nombre.lower().split()
    if partes[-1] in ['chico', 'mediano', 'grande']:
        return ' '.join(partes[:-1])
    return nombre.lower()

@app.route('/')
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
        return render_template('index_cajero.html', cat=cat, categoriaslist=categorias, pedidos_por_usuario=pedidos_por_usuario, usuarios=usuarios, caja_abierta=caja_abierta, monto_inicial=monto_inicial)
    else:
        return redirect(url_for('login'))

@socketio.on('connect')
def conectar_notificaciones():
    if 'username' not in session:
        return False
    if session.get('tipo_usuario') == 'cajero':
        join_room('notificaciones_caja')


@socketio.on('nuevo_pedido')
def pedido_handler(data):
    if 'username' not in session or session.get('tipo_usuario') not in ('user', 'admin'):
        emit('pedido_error', {'error': 'No tienes permiso para crear pedidos'})
        return
    try:
        if not isinstance(data, dict) or not isinstance(data.get('productos'), list) or not data['productos']:
            raise ValueError('El pedido debe contener productos')

        productos = []
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
            if producto.category.name.lower() in ('cervezas', 'bebidas'):
                if producto.stock is None or producto.stock < cantidad:
                    raise ValueError('No hay stock suficiente para el producto ' + producto.name)
                producto.stock -= cantidad
            productos.append({'id': '_'.join(partes), 'nombre': nombre, 'precio': precio, 'cantidad': cantidad})

        pedido = Pedidos(
            folio=generar_folio(),
            estado='ABIERTA',
            total=sum(p['precio'] * p['cantidad'] for p in productos),
            state='pendiente',
            fecha=datetime.now(),
            products=productos,
            usuario_id=session['username']
        )
        db.session.add(pedido)
        db.session.flush()
        
        # Registrar auditoría
        registrar_auditoria('CREAR_PEDIDO', f'Pedido {pedido.folio} creado por {session["username"]}', pedido.id, commit=False)
        db.session.commit()
        
        # Emitir evento para actualizar vista del mesero en tiempo real
        socketio.emit('nuevo_pedido_creado', {'id': pedido.id, 'folio': pedido.folio, 'usuario_id': session['username']})

        emit('pedido_creado', {'id': pedido.id, 'total': pedido.total, 'state': pedido.state, 'fecha': pedido.fecha.strftime('%Y-%m-%d %H:%M:%S')})
    except Exception as e:
        db.session.rollback()
        print('Error al crear el pedido: ' + str(e))
        emit('pedido_error', {'error': str(e)})

@app.route('/guardar_historico', methods=['POST'])
@role_required('cajero', 'admin')
def guardar_historico():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or type(data.get('pedido_id')) is not int:
        return jsonify({'success': False, 'message': 'Pedido inválido'}), 400

    # Datos del pedido actual
    pedido_id = data.get('pedido_id')

    pedido = Pedidos.query.get(pedido_id)
    if not pedido:
        return jsonify({'success': False, 'message': 'Pedido no encontrado'}), 404
    
    # Verificar que el pedido no esté ya cobrado
    if pedido.estado != 'ENVIADA_A_CAJA':
        return jsonify({'success': False, 'message': 'Solo se pueden cobrar pedidos enviados a caja'}), 400
    
    # Cambiar estado a COBRADA en lugar de eliminar
    pedido.estado = 'COBRADA'
    pedido.fecha_cobro = datetime.now()
    pedido.cajero_id = session['username']
    
    # Guardar en histórico
    historico = PedidoHistorico(
        productos=json.dumps(pedido.products) if pedido.products else "[]",
        total=pedido.total,
        fecha=datetime.now()
    )
    db.session.add(historico)
    
    # Registrar movimiento de caja
    registrar_movimiento_caja('VENTA', monto=pedido.total, pedido_id=pedido.id, commit=False)
    
    # Registrar auditoría
    registrar_auditoria('COBRAR_PEDIDO', f'Pedido {pedido.folio} cobrado por {session["username"]}', pedido.id, commit=False)
    
    db.session.commit()
    
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
def delete_pedido(pedido_id):
    pedido = Pedidos.query.get_or_404(pedido_id)

    if session['tipo_usuario'] == 'user' and pedido.usuario_id != session['username']:
        return jsonify({'success': False, 'message': 'No puedes cancelar este pedido'}), 403
    if pedido.estado not in ('ABIERTA', 'ENVIADA_A_CAJA'):
        return jsonify({'success': False, 'message': 'El pedido ya fue cobrado o cancelado'}), 400

    # Las existencias se reservaron al crear o ampliar el pedido.
    for item in pedido.products or []:
        producto = db.session.get(Product, int(str(item['id']).split('_')[0]))
        if producto and producto.category.name.lower() in ('cervezas', 'bebidas'):
            producto.stock = (producto.stock or 0) + item['cantidad']

    # Cambiar estado a CANCELADA en lugar de eliminar
    pedido.estado = 'CANCELADA'
    
    # Registrar auditoría
    registrar_auditoria('CANCELAR_PEDIDO', f'Pedido {pedido.folio} cancelado por {session["username"]}', pedido.id, commit=False)
    
    db.session.commit()

    # Emitir evento para que todos actualicen en tiempo real
    socketio.emit('pedido_eliminado', {'id': pedido_id})

    return {'success': True}

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = Users.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session['username'] = user.username
            session['tipo_usuario'] = user.rol
            return redirect(url_for('index'))
        else:
            flash('Usuario o contraseña incorrectos', 'error')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
@role_required('admin')
def register():
    if request.method == 'POST' and session['tipo_usuario'] == 'admin':
        username = request.form['username']
        password = request.form['password']
        rol = request.form['rol']
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
def logout():
    if 'username' in session:
        registrar_auditoria('CERRAR_SESION', f'Usuario {session["username"]} cerró sesión')
    session.pop('username', None)
    session.pop('tipo_usuario', None)
    return redirect(url_for('login'))

@app.route('/abrir_caja', methods=['POST'])
@role_required('cajero', 'admin')
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
    
    monto_inicial = request.form.get('monto_inicial')
    monto_inicial = float(monto_inicial) if monto_inicial else 0.0
    
    registrar_movimiento_caja('APERTURA', monto_inicial=monto_inicial)
    registrar_auditoria('ABRIR_CAJA', f'Caja abierta por {session["username"]} con monto inicial: ${monto_inicial}')
    flash(f'Caja abierta correctamente. Monto inicial: ${monto_inicial}', 'success')
    return redirect(url_for('index'))

@app.route('/cerrar_caja', methods=['POST'])
@role_required('cajero', 'admin')
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
    
    total_ventas = sum(v.monto for v in ventas if v.monto)
    monto_inicial = apertura_activa.monto_inicial if apertura_activa.monto_inicial else 0.0
    total_esperado = monto_inicial + total_ventas
    
    registrar_movimiento_caja('CIERRE', total_esperado)
    registrar_auditoria('CERRAR_CAJA', f'Caja cerrada por {session["username"]}. Monto inicial: ${monto_inicial}, Ventas: ${total_ventas}, Total esperado: ${total_esperado}')
    
    flash(f'Caja cerrada. Monto inicial: ${monto_inicial}, Ventas: ${total_ventas}, Total esperado: ${total_esperado}', 'success')
    return redirect(url_for('index'))

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
        'sesiones': ('Sesiones', {'CERRAR_SESION': 'Cierre de sesión'})
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

@app.route('/enviar_caja/<int:pedido_id>', methods=['POST'])
@role_required('user', 'admin')
def enviar_caja(pedido_id):
    pedido = Pedidos.query.get_or_404(pedido_id)
    if session['tipo_usuario'] == 'user' and pedido.usuario_id != session['username']:
        return jsonify({'success': False, 'message': 'No puedes enviar este pedido a caja'}), 403
    
    if pedido.estado != 'ABIERTA':
        if request.accept_mimetypes.best == 'application/json':
            return jsonify({'success': False, 'message': 'Solo se pueden enviar pedidos en estado ABIERTA'}), 400
        flash('Solo se pueden enviar pedidos en estado ABIERTA', 'error')
        return redirect(request.referrer or url_for('index'))
    
    pedido.estado = 'ENVIADA_A_CAJA'
    registrar_auditoria('ENVIAR_CAJA', f'Pedido {pedido.folio} enviado a caja por {session["username"]}', pedido.id)
    db.session.commit()

    socketio.emit('ticket_enviado_caja', {
        'id': pedido.id, 'folio': pedido.folio, 'usuario_id': pedido.usuario_id
    }, to='notificaciones_caja')
    
    if request.accept_mimetypes.best == 'application/json':
        return jsonify({'success': True})
    return redirect(request.referrer or url_for('index'))

@app.route('/agregar_producto_pedido/<int:pedido_id>', methods=['POST'])
@role_required('user', 'admin')
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
    
    producto = Product.query.get(producto_id)
    if not producto:
        return jsonify({'success': False, 'message': 'Producto no encontrado'}), 404

    if producto.category.name.lower() in ('cervezas', 'bebidas'):
        if producto.stock is None or producto.stock < cantidad:
            return jsonify({'success': False, 'message': 'Stock insuficiente'}), 400
        producto.stock -= cantidad
    
    # Agregar producto al pedido
    productos_actuales = pedido.products if pedido.products else []
    
    # Verificar si el producto ya está en el pedido (comparar por nombre para evitar problemas con IDs compuestos)
    producto_existente = next((p for p in productos_actuales if p['nombre'] == producto.name), None)
    
    if producto_existente:
        producto_existente['cantidad'] += cantidad
        producto_existente['precio'] = producto.price  # Actualizar precio actual
    else:
        productos_actuales.append({
            'id': str(producto.id),
            'nombre': producto.name,
            'precio': producto.price,
            'cantidad': cantidad
        })
    
    pedido.products = productos_actuales
    pedido.total = sum(p['precio'] * p['cantidad'] for p in productos_actuales)
    
    # Marcar el campo products como modificado para que SQLAlchemy lo guarde
    flag_modified(pedido, 'products')
    
    db.session.commit()
    
    registrar_auditoria('AGREGAR_PRODUCTO', f'Agregado {cantidad}x {producto.name} al pedido {pedido.folio}', pedido.id)
    
    # Emitir evento para actualizar vista del mesero
    socketio.emit('pedido_actualizado', {'id': pedido.id, 'usuario_id': session['username']})
    
    return jsonify({'success': True, 'message': 'Producto agregado al pedido'})

@app.route('/eliminar_producto_pedido/<int:pedido_id>', methods=['POST'])
@role_required('user', 'admin')
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
    producto_a_eliminar = next((p for p in productos_actuales if p['id'] == producto_id), None)
    
    if producto_a_eliminar:
        productos_actuales.remove(producto_a_eliminar)
        
        pedido.products = productos_actuales
        pedido.total = sum(p['precio'] * p['cantidad'] for p in productos_actuales)
        
        # Marcar el campo products como modificado para que SQLAlchemy lo guarde
        flag_modified(pedido, 'products')
        
        db.session.commit()
        
        # Devolver stock si es bebida/cerveza
        producto = Product.query.get(producto_id.split('_')[0])  # Obtener ID base si es ID compuesto
        if producto and producto.category.name.lower() in ["cervezas", "bebidas"]:
            producto.stock += producto_a_eliminar['cantidad']
            db.session.commit()
        
        registrar_auditoria('ELIMINAR_PRODUCTO', f'Eliminado {producto_a_eliminar["nombre"]} del pedido {pedido.folio}', pedido.id)
        
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
def create():
    name = request.form['name'].strip()
    categoria_id = int(request.form['categoria'])
    price = float(request.form['price'])
    description = request.form['description'].strip()
    stock = request.form['stock']
    image = request.files.get('image')
    image_path = None

    # Validar nombre duplicado (insensible a mayúsculas)
    existing_product = Product.query.filter(Product.name.ilike(name)).first()
    if existing_product:
        flash("El producto ya existe", "error")
        return redirect(url_for('index'))

    # Validar imagen
    filename = ''
    if image and image.filename != '':
        if not allowed_file(image.filename):
            flash("Imagen inválida", "error")
            return redirect(url_for('index'))
        # Generar nombre del archivo
        ext = image.filename.rsplit('.', 1)[1].lower()
        filename = secure_filename(f"{name}.{ext}")
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        # Si el archivo ya existe, elimínalo para evitar conflictos
        if image and image.filename != '' and os.path.exists(image_path):
            os.remove(image_path)
        # Guardar imagen
        image.save(image_path)

    try:
        # Crear y guardar producto
        nuevo_producto = Product(
            name=name,
            categoria=categoria_id,
            price=price,
            description=description,
            stock=stock,
            image=filename
        )

        db.session.add(nuevo_producto)
        db.session.commit()

        sizes = request.form.getlist('size[]')
        prices = request.form.getlist('price[]')

        size_set = set()

        for size, price in zip(sizes, prices):
            if size and price:
                if size in size_set:
                    flash(f"Tamaño duplicado: '{size}'")
                size_set.add(size)
                variante = ProductVariant(size=size, price=float(price), product_id=nuevo_producto.id)
                db.session.add(variante)

        db.session.commit()

        flash("Producto creado con éxito", "success")
        return redirect(url_for('index'))

    except Exception as e:
        # En caso de error, eliminar la imagen guardada
        if image_path and os.path.exists(image_path):
            os.remove(image_path)
        flash("Error al crear el producto", "error")
        return redirect(request.referrer or url_for('index'))

@app.route('/create_category', methods=['GET', 'POST'])
@role_required('admin')
def create_category():

    if request.method == 'POST':
        name = request.form['name']
        nuevo_categoria = Category(name=name)
        existing_category = Category.query.filter(Category.name.ilike(name)).first()
        if existing_category:
            flash("La categoría ya existe", "error")
            return redirect(url_for('index'))
        db.session.add(nuevo_categoria)
        db.session.commit()
        return redirect(request.referrer or url_for('index'))

@app.route('/delete_category', methods=['GET', 'POST'])
@role_required('admin')
def delete_category():
    if request.method == 'POST':
        categoria_id = request.form['categoria']
        categoria = Category.query.filter_by(id=categoria_id).first()
        if categoria:
            db.session.delete(categoria)
            db.session.commit()
            flash("Categoría eliminada con éxito", "success")
        else:
            flash("La categoría no existe", "error")
    return redirect(request.referrer or url_for('index'))

@app.route('/admin', methods=['GET'])
@role_required('admin')
def admin():
    return render_template('admin.html', users=Users.query.all())

@app.route('/edit_user/<int:id>', methods=['POST'])
@role_required('admin')
def edit_user(id):
    user = Users.query.get_or_404(id)

    if request.method == 'POST':
        new_username = request.form['username']
        new_rol = request.form['rol']
        
        # Validar que el usuario no cambie su propio rol a algo que no sea admin
        if user.username == session.get('username') and new_rol != 'admin':
            flash('No puedes cambiar tu propio rol a algo diferente de admin', 'error')
            return redirect(request.referrer or url_for('admin'))
        
        user.username = new_username
        user.rol = new_rol
        
        # Actualizar contraseña si se proporciona
        password = request.form.get('password')
        if password and password.strip():
            user.set_password(password)
        
        db.session.commit()
        
        # Registrar auditoría
        registrar_auditoria('EDITAR_USUARIO', f'Usuario {user.username} editado por {session["username"]}')
        
        return redirect(request.referrer or url_for('admin'))

@app.route('/delete_user/<int:id>', methods=['POST'])
@role_required('admin')
def delete_user(id):
    user = Users.query.get_or_404(id)
    
    # Validar que el usuario no se elimine a sí mismo
    if user.username == session.get('username'):
        flash('No puedes eliminar tu propio usuario', 'error')
        return redirect(request.referrer or url_for('admin'))
    
    # Verificar si el usuario tiene pedidos ACTIVOS (solo bloquear si hay pedidos abiertos)
    pedidos_activos = Pedidos.query.filter_by(usuario_id=user.username, estado='ABIERTA').first()
    if pedidos_activos:
        flash('No puedes eliminar un usuario que tiene pedidos activos', 'error')
        return redirect(request.referrer or url_for('admin'))
    
    # Eliminar referencias al usuario en pedidos históricos para no violar foreign keys
    Pedidos.query.filter_by(usuario_id=user.username).update({'usuario_id': 'USUARIO_ELIMINADO'})
    Pedidos.query.filter_by(cajero_id=user.username).update({'cajero_id': None})
    
    # Eliminar referencias en movimientos de caja
    MovimientosCaja.query.filter_by(usuario_id=user.username).update({'usuario_id': 'USUARIO_ELIMINADO'})
    
    # Registrar auditoría antes de eliminar
    registrar_auditoria('ELIMINAR_USUARIO', f'Usuario {user.username} eliminado por {session["username"]}')
    
    db.session.delete(user)
    db.session.commit()
    return redirect(request.referrer or url_for('admin'))

@app.route('/edit/<int:id>', methods=['POST'])
@role_required('admin')
def edit(id):
    product = Product.query.get_or_404(id)

    if request.method == 'POST':
        product.name = request.form['name']
        product.categoria = int(request.form['categoria'])
        product.price = float(request.form['price'])
        product.description = request.form['description']

        if 'image' in request.files:
            imagen_file = request.files['image']
            if imagen_file.filename != '':
                # Eliminar imagen anterior
                if product.image:
                    old_path = os.path.join(app.config['UPLOAD_FOLDER'], product.image)
                    if os.path.exists(old_path):
                        os.remove(old_path)

                # Guardar nueva
                ext = imagen_file.filename.rsplit('.', 1)[1].lower()
                new_filename = f"{secure_filename(request.form['name'])}.{ext}"
                imagen_file.save(os.path.join(app.config['UPLOAD_FOLDER'], new_filename))
                product.image = new_filename

        db.session.commit()

        # Editar o eliminar variantes existentes
        variant_ids = request.form.getlist('variant_id[]')
        sizes = request.form.getlist('size[]')
        prices = request.form.getlist('price[]')

        for vid, size, price in zip(variant_ids, sizes, prices):
            variant = ProductVariant.query.get(int(vid))
            if size.strip() == '' or price.strip() == '':
                db.session.delete(variant)
            else:
                variant.size = size
                variant.price = float(price)
                
        # Nuevas variantes
        new_sizes = request.form.getlist('new_size[]')
        new_prices = request.form.getlist('new_price[]')
        for size, price in zip(new_sizes, new_prices):
            if size and price:
                db.session.add(ProductVariant(size=size, price=float(price), product_id=product.id))

        db.session.commit()

    return redirect(request.referrer or url_for('index'))


@app.route('/delete/<int:id>', methods=['POST'])
@role_required('admin')
def delete(id):
    product = Product.query.get_or_404(id)

    for variant in product.variants:
        db.session.delete(variant)


    if request.method == 'POST':
        # Eliminar imagen del sistema si existe
        if product.image:
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], product.image)
            if os.path.exists(image_path):
                os.remove(image_path)
    
        db.session.delete(product)
        db.session.commit()
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
    socketio.run(app, debug=True, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)
