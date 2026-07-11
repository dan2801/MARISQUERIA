from flask import jsonify, render_template, request, redirect, url_for, flash, session
from collections import defaultdict
from werkzeug.utils import secure_filename
import os
from models import db, Product, Category, Users, ProductVariant, Pedidos, PedidoHistorico, Auditoria, MovimientosCaja
from flask_socketio import emit
from datetime import datetime
import json
from __init__ import init_app
import jinja2
from sqlalchemy.orm.attributes import flag_modified

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
def registrar_auditoria(accion, descripcion=None, pedido_id=None):
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
            db.session.commit()

# Función para registrar movimiento de cajaa
def registrar_movimiento_caja(tipo_movimiento, monto=None, monto_inicial=None, pedido_id=None):
    if 'username' in session:
        movimiento = MovimientosCaja(
            tipo_movimiento=tipo_movimiento,
            monto=monto,
            monto_inicial=monto_inicial,
            usuario_id=session['username'],
            pedido_id=pedido_id
        )
        db.session.add(movimiento)
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

@socketio.on('nuevo_pedido')
def pedido_handler(data):
    try:
        print("datosss: ", data)
        pedido = Pedidos(
            folio=generar_folio(),
            estado='ABIERTA',
            total=data['total'],
            state=data['state'],
            fecha=datetime.now(),
            products=data[ 'productos'],
            usuario_id=session['username']
        )
        db.session.add(pedido)
        db.session.commit()
        
        # Registrar auditoría
        registrar_auditoria('CREAR_PEDIDO', f'Pedido {pedido.folio} creado por {session["username"]}', pedido.id)
        
        # Emitir evento para actualizar vista del mesero en tiempo real
        socketio.emit('nuevo_pedido_creado', {'id': pedido.id, 'folio': pedido.folio, 'usuario_id': session['username']})

        for item in data['productos']:
            producto = Product.query.filter_by(name=item['nombre']).first()
            print("productooooooo: ",producto)
            if producto: 
                categoria_nombre = producto.category.name.lower()

                if categoria_nombre in ["cervezas", "bebidas"]:
                    if producto.stock >= item['cantidad']:
                        producto.stock -= item['cantidad']
                    else:
                        print('No hay stock suficiente para el producto ' + producto.name)
                        emit('pedido_error', {'error': 'No hay stock suficiente para el producto ' + producto.name})
                        db.session.rollback()
                        return
                
        db.session.commit()
        emit('pedido_creado', {'id': pedido.id, 'total': pedido.total, 'state': pedido.state, 'fecha': pedido.fecha.strftime('%Y-%m-%d %H:%M:%S')})
    except Exception as e:
        db.session.rollback()
        print('Error al crear el pedido: ' + str(e))
        emit('pedido_error', {'error': str(e)})

@app.route('/guardar_historico', methods=['POST'])
def guardar_historico():
    data = request.get_json()

    # Datos del pedido actual
    pedido_id = data.get('pedido_id')

    pedido = Pedidos.query.get(pedido_id)
    if not pedido:
        return jsonify({'success': False, 'message': 'Pedido no encontrado'}), 404
    
    # Verificar que el pedido no esté ya cobrado
    if pedido.estado == 'COBRADA':
        return jsonify({'success': False, 'message': 'Este pedido ya fue cobrado'}), 400
    
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
    registrar_movimiento_caja('VENTA', pedido.total, pedido.id)
    
    # Registrar auditoría
    registrar_auditoria('COBRAR_PEDIDO', f'Pedido {pedido.folio} cobrado por {session["username"]}', pedido.id)
    
    db.session.commit()
    
    # Emitir evento para que el cajero actualice su vista
    socketio.emit('pedido_cobrado', {'id': pedido.id, 'folio': pedido.folio})
    
    return jsonify({'success': True, 'message': 'Pedido cobrado y guardado en historial'})

@app.route('/ticket/<int:id>')
def ticket(id):
    pedido = Pedidos.query.get(id)
    return render_template('ticket.html', pedido=pedido)

@app.route('/delete_pedido/<int:pedido_id>', methods=['POST'])
def delete_pedido(pedido_id):
    pedido = Pedidos.query.get_or_404(pedido_id)

    # Cambiar estado a CANCELADA en lugar de eliminar
    pedido.estado = 'CANCELADA'
    
    # Registrar auditoría
    registrar_auditoria('CANCELAR_PEDIDO', f'Pedido {pedido.folio} cancelado por {session["username"]}', pedido.id)
    
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
def register():
    if request.method == 'POST' and session['tipo_usuario'] == 'admin':
        username = request.form['username']
        password = request.form['password']
        rol = request.form['rol']
        user = Users(username=username, rol=rol)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return redirect(request.referrer or url_for('admin'))
    else:
        return redirect(url_for('index'))

@app.route('/reportes', methods=['GET'])
@role_required('admin')
def reportes():
    reportes = PedidoHistorico.query.all()
    return render_template('reportes.html', reportes=reportes)

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
    registros = Auditoria.query.order_by(Auditoria.fecha_hora.desc()).all()
    return render_template('auditoria.html', registros=registros)

@app.route('/enviar_caja/<int:pedido_id>', methods=['POST'])
@role_required('user', 'admin')
def enviar_caja(pedido_id):
    pedido = Pedidos.query.get_or_404(pedido_id)
    
    if pedido.estado != 'ABIERTA':
        flash('Solo se pueden enviar pedidos en estado ABIERTA', 'error')
        return redirect(request.referrer or url_for('index'))
    
    pedido.estado = 'ENVIADA_A_CAJA'
    registrar_auditoria('ENVIAR_CAJA', f'Pedido {pedido.folio} enviado a caja por {session["username"]}', pedido.id)
    db.session.commit()
    
    flash('Pedido enviado a caja correctamente', 'success')
    return redirect(request.referrer or url_for('index'))

@app.route('/agregar_producto_pedido/<int:pedido_id>', methods=['POST'])
@role_required('user', 'admin')
def agregar_producto_pedido(pedido_id):
    pedido = Pedidos.query.get_or_404(pedido_id)
    
    # Verificar que el pedido pertenezca al usuario y esté ABIERTA
    if pedido.usuario_id != session['username'] or pedido.estado != 'ABIERTA':
        return jsonify({'success': False, 'message': 'No puedes editar este pedido'}), 403
    
    producto_id = request.form.get('producto_id')
    cantidad = int(request.form.get('cantidad', 1))
    
    producto = Product.query.get(producto_id)
    if not producto:
        return jsonify({'success': False, 'message': 'Producto no encontrado'}), 404
    
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
    
    # Actualizar stock si es bebida/cerveza
    if producto.category.name.lower() in ["cervezas", "bebidas"]:
        if producto.stock >= cantidad:
            producto.stock -= cantidad
        else:
            return jsonify({'success': False, 'message': 'Stock insuficiente'}), 400
    
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
        return jsonify({'success': False, 'message': 'No puedes editar este pedido'}), 403
    
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
        
        return jsonify({'success': True, 'message': 'Producto eliminado del pedido'})
    else:
        return jsonify({'success': False, 'message': 'Producto no encontrado en el pedido'}), 404

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
        user.username = request.form['username']
        user.rol = request.form['rol']
        
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