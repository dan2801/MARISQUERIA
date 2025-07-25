from flask import render_template, request, redirect, url_for, flash, session
from collections import defaultdict
from werkzeug.utils import secure_filename
import os
from models import db, Product, Category, User
from app import app

db.init_app(app)

with app.app_context():
    db.create_all()

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    print(session)
    rol = session.get('tipo_usuario')

    products = Product.query.all()
    categorias = Category.query.all()

    cat = defaultdict(list)
    for product in products:
        cat[product.category.name].append(product)

    if rol == 'admin':
        return render_template('index.html', cat=cat, categoriaslist=categorias)
    elif rol == 'user':
        return render_template('index_user.html', cat=cat, categoriaslist=categorias)
    else:
        return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session['username'] = user.username
            session['tipo_usuario'] = user.rol
            return redirect(url_for('index'))
        else:
            flash('Usuario o contraseña incorrectos', 'error')
            print("Usuario o contraseña incorrectos", session)
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST' and session['tipo_usuario'] == 'admin':
        username = request.form['username']
        password = request.form['password']
        rol = request.form['rol']
        user = User(username=username, rol=rol)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return redirect(url_for('admin'))
    else:
        return redirect(url_for('index'))

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
    stock = int(request.form['stock'])
    image = request.files['image']

    # Validar nombre duplicado (insensible a mayúsculas)
    existing_product = Product.query.filter(Product.name.ilike(name)).first()
    if existing_product:
        flash("El producto ya existe", "error")
        return redirect(url_for('index'))

    # Validar imagen
    if not image or not allowed_file(image.filename):
        flash("Imagen inválida", "error")
        return redirect(url_for('index'))

    # Generar nombre del archivo
    ext = image.filename.rsplit('.', 1)[1].lower()
    filename = secure_filename(f"{name}.{ext}")
    image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

    # Si el archivo ya existe, elimínalo para evitar conflictos
    if os.path.exists(image_path):
        os.remove(image_path)

    try:
        # Guardar imagen
        image.save(image_path)

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

        flash("Producto creado con éxito", "success")
        return redirect(url_for('index'))

    except Exception as e:
        # En caso de error, eliminar la imagen guardada
        if os.path.exists(image_path):
            os.remove(image_path)
        flash("Error al crear el producto", "error")
        print(e)
        return redirect(url_for('index'))

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
        return redirect(url_for('index'))

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
    return redirect(url_for('index'))

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
        return redirect(url_for('admin'))

@app.route('/delete_user/<int:id>', methods=['POST'])
def delete_user(id):
    if 'username' not in session:
        return redirect(url_for('login'))
    if session['tipo_usuario'] == 'admin':
        user = User.query.get_or_404(id)
        db.session.delete(user)
        db.session.commit()
        return redirect(url_for('admin'))

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

        # Obtener archivo
        imagen_file = request.files['image']

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

    return redirect(url_for('index'))


@app.route('/delete/<int:id>', methods=['POST'])
def delete(id):
    if 'username' not in session:
        return redirect(url_for('login'))
    product = Product.query.get_or_404(id)

    if request.method == 'POST' and session['tipo_usuario'] == 'admin':
        # Eliminar imagen del sistema si existe
        if product.image:
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], product.image)
            if os.path.exists(image_path):
                os.remove(image_path)
    
        db.session.delete(product)
        db.session.commit()
        return redirect(url_for('index'))

@app.route('/inventario', methods=['GET'])
def inventario():
    if 'username' not in session:
        return redirect(url_for('login'))

    if session['tipo_usuario'] == 'admin':
        return render_template('inventario.html')
    else:
        return redirect(url_for('index'))