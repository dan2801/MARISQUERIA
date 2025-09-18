from flask import jsonify, render_template, request, redirect, url_for, flash, session
from collections import defaultdict
from werkzeug.utils import secure_filename
import os
from models import db, Product, Category, Users, ProductVariant, Pedidos, PedidoHistorico
from flask_socketio import emit
from datetime import datetime
import json
from __init__ import init_app

app, socketio = init_app()
app.secret_key = b'_5#y2L"F4Q8z\n\xec]/'

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
    rol = session.get('tipo_usuario')

    products = Product.query.all()
    categorias = Category.query.all()

    cat = defaultdict(list)
    for product in products:
        cat[product.category.name].append(product)

    pedidos = Pedidos.query.all()

    if rol == 'admin':
        return render_template('index.html', cat=cat, categoriaslist=categorias)
    elif rol == 'user':
        return render_template('index_user.html', cat=cat, categoriaslist=categorias)
    elif rol == 'cajero':
        usuarios = Users.query.all()
        return render_template('index_cajero.html', cat=cat, categoriaslist=categorias, pedidos=pedidos, usuarios=usuarios)
    else:
        return redirect(url_for('login'))

@socketio.on('nuevo_pedido')
def pedido_handler(data):
    try:
        print("datosss: ", data)
        pedido = Pedidos(
            total=data['total'],
            state=data['state'],
            fecha=datetime.now(),
            products=data[ 'productos'],
            usuario_id=session['username']
        )
        db.session.add(pedido)

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
    
    historico = PedidoHistorico(
        productos=pedido.name,
        total=pedido.total,
        fecha=datetime.now()
    )
    db.session.add(historico)
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'Pedido guardado en historial'})

@app.route('/ticket/<int:id>')
def ticket(id):
    pedido = Pedidos.query.get(id)
    return render_template('ticket.html', pedido=pedido)

@app.route('/delete_pedido/<int:pedido_id>', methods=['POST'])
def delete_pedido(pedido_id):
    pedido = Pedidos.query.get_or_404(pedido_id)

    # Borrar el pedido
    db.session.delete(pedido)
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
def reportes():
    reportes = PedidoHistorico.query.all()
    return render_template('reportes.html', reportes=reportes)

@app.route('/logout', methods=['POST'])
def logout():
    session.pop('username', None)
    session.pop('tipo_usuario', None)
    return redirect(url_for('login'))

@app.route('/create', methods=['POST'])
def create():
    if 'username' not in session:
        return redirect(url_for('login'))
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
def create_category():
    if 'username' not in session:
        return redirect(url_for('login'))

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
def delete_category():
    if 'username' not in session:
        return redirect(url_for('login'))
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
def admin():
    if 'username' not in session:
        return redirect(url_for('login'))

    if session['tipo_usuario'] == 'admin':
        return render_template('admin.html', users=User.query.all())
    else:
        return redirect(url_for('index'))

@app.route('/edit_user/<int:id>', methods=['POST'])
def edit_user(id):
    if 'username' not in session:
        return redirect(url_for('login'))
    user = User.query.get_or_404(id)

    if request.method == 'POST' and session['tipo_usuario'] == 'admin':
        user.username = request.form['username']
        user.rol = request.form['rol']
        db.session.commit()
        return redirect(request.referrer or url_for('admin'))

@app.route('/delete_user/<int:id>', methods=['POST'])
def delete_user(id):
    if 'username' not in session:
        return redirect(url_for('login'))
    if session['tipo_usuario'] == 'admin':
        user = User.query.get_or_404(id)
        db.session.delete(user)
        db.session.commit()
        return redirect(request.referrer or url_for('admin'))

@app.route('/edit/<int:id>', methods=['POST'])
def edit(id):
    if 'username' not in session:
        return redirect(url_for('login'))
    product = Product.query.get_or_404(id)

    if request.method == 'POST' and session['tipo_usuario'] == 'admin':
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
def delete(id):
    if 'username' not in session:
        return redirect(url_for('login'))
    product = Product.query.get_or_404(id)

    for variant in product.variants:
        db.session.delete(variant)


    if request.method == 'POST' and session['tipo_usuario'] == 'admin':
        # Eliminar imagen del sistema si existe
        if product.image:
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], product.image)
            if os.path.exists(image_path):
                os.remove(image_path)
    
        db.session.delete(product)
        db.session.commit()
        return redirect(request.referrer or url_for('index'))

@app.route('/inventario')
def inventario():
    products = Product.query.all()
    categorias = Category.query.all()

    cat = defaultdict(list)
    for product in products:
        cat[product.category.name].append(product)

    if 'username' not in session:
        return redirect(url_for('login'))

    if session['tipo_usuario'] == 'admin':
        return render_template('inventario.html', cat=cat, categoriaslist=categorias)
    else:
        return redirect(url_for('index'))


if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)