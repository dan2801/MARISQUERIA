from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    price = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(200), nullable=True)
    stock = db.Column(db.Integer, nullable=True)
    image = db.Column(db.String(200), nullable=True)
    categoria = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    variants = db.relationship('ProductVariant', backref='product', lazy=True)

class ProductVariant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    size = db.Column(db.String(80), nullable=False)
    price = db.Column(db.Float, nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    products = db.relationship('Product', backref='category', lazy=True)

class Users(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False)
    password = db.Column(db.String(80), nullable=False)
    rol = db.Column(db.String(80), nullable=False)

    def set_password(self, password):
        self.password = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password, password)
    pedidos = db.relationship('Pedidos', foreign_keys='Pedidos.usuario_id', backref='user', lazy=True)

class Pedidos(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    folio = db.Column(db.String(20), unique=True, nullable=True)
    estado = db.Column(db.String(20), default='ABIERTA')  # ABIERTA, ENVIADA_A_CAJA, COBRADA, CANCELADA
    state = db.Column(db.String(20), default='pendiente')  # Mantener por compatibilidad
    fecha = db.Column(db.DateTime, default=datetime.now())
    fecha_cobro = db.Column(db.DateTime, nullable=True)
    products = db.Column(db.JSON)
    total = db.Column(db.Float)
    usuario_id = db.Column(db.String(80), db.ForeignKey('users.username'), nullable=False)
    cajero_id = db.Column(db.String(80), db.ForeignKey('users.username'), nullable=True)

class PedidoHistorico(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    productos = db.Column(db.Text)  # o relación si usas modelo relacional
    total = db.Column(db.Float)
    fecha = db.Column(db.DateTime, default=datetime.now())

class Auditoria(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.String(80), nullable=False)
    usuario_nombre = db.Column(db.String(80), nullable=False)
    rol = db.Column(db.String(80), nullable=False)
    accion = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    fecha_hora = db.Column(db.DateTime, default=datetime.now())
    pedido_id = db.Column(db.Integer, db.ForeignKey('pedidos.id'), nullable=True)

class MovimientosCaja(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tipo_movimiento = db.Column(db.String(50), nullable=False)  # APERTURA, VENTA, CIERRE
    monto = db.Column(db.Float, nullable=True)
    monto_inicial = db.Column(db.Float, nullable=True)  # Dinero inicial al abrir caja
    usuario_id = db.Column(db.String(80), db.ForeignKey('users.username'), nullable=False)
    fecha_hora = db.Column(db.DateTime, default=datetime.now())
    pedido_id = db.Column(db.Integer, db.ForeignKey('pedidos.id'), nullable=True)
