from app import app, db
from models import Category, Users, Product, ProductVariant
from werkzeug.security import generate_password_hash

with app.app_context():
    db.create_all()
    print('Base de datos inicializada correctamente')
    
    # Crear usuario admin por defecto
    if not Users.query.filter_by(username='admin').first():
        admin = Users(username='admin', rol='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        print('Usuario admin creado (usuario: admin, contraseña: admin123)')
    
    # Crear categorías típicas para marisquería
    categorias_marisqueria = [
        'Mariscos',
        'Cervezas', 
        'Bebidas',
        'Postres',
        'Otros'
    ]
    
    for cat_nombre in categorias_marisqueria:
        if not Category.query.filter_by(name=cat_nombre).first():
            categoria = Category(name=cat_nombre)
            db.session.add(categoria)
            print(f'Categoría creada: {cat_nombre}')
    
    # Crear algunos productos de ejemplo
    if not Product.query.first():
        # Obtener categorías
        cat_mariscos = Category.query.filter_by(name='Mariscos').first()
        cat_cervezas = Category.query.filter_by(name='Cervezas').first()
        cat_bebidas = Category.query.filter_by(name='Bebidas').first()
        
        # Productos de ejemplo
        productos_ejemplo = [
            {'name': 'Camarones', 'price': 150.0, 'description': 'Camarones frescos', 'stock': 50, 'categoria': cat_mariscos.id if cat_mariscos else 1},
            {'name': 'Pulpo', 'price': 200.0, 'description': 'Pulpo fresco', 'stock': 30, 'categoria': cat_mariscos.id if cat_mariscos else 1},
            {'name': 'Cerveza Corona', 'price': 35.0, 'description': 'Cerveza Corona 355ml', 'stock': 100, 'categoria': cat_cervezas.id if cat_cervezas else 2},
            {'name': 'Cerveza Pacifico', 'price': 30.0, 'description': 'Cerveza Pacifico 355ml', 'stock': 100, 'categoria': cat_cervezas.id if cat_cervezas else 2},
            {'name': 'Refresco Coca-Cola', 'price': 20.0, 'description': 'Refresco Coca-Cola 600ml', 'stock': 80, 'categoria': cat_bebidas.id if cat_bebidas else 3},
        ]
        
        for prod_data in productos_ejemplo:
            producto = Product(
                name=prod_data['name'],
                price=prod_data['price'],
                description=prod_data['description'],
                stock=prod_data['stock'],
                categoria=prod_data['categoria']
            )
            db.session.add(producto)
            print(f'Producto creado: {prod_data["name"]}')
    
    db.session.commit()
    print('Datos iniciales creados exitosamente')
