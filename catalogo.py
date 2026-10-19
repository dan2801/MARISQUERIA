from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

from models import db, Category, Product


def nombre_valido(valor, etiqueta='nombre'):
    nombre = ' '.join((valor or '').split())
    if not nombre or len(nombre) > 80:
        raise ValueError(f'El {etiqueta} es obligatorio y admite hasta 80 caracteres')
    return nombre


def precio_valido(valor):
    try:
        numero = Decimal(valor or '')
        if not numero.is_finite() or numero <= 0 or numero > Decimal('9999999.99'):
            raise ValueError
        if numero != numero.quantize(Decimal('0.01')):
            raise ValueError
        return float(numero)
    except (InvalidOperation, ValueError):
        raise ValueError('El precio debe ser positivo y tener máximo dos decimales')


def datos_producto(formulario, producto_id=None, stock_anterior=0):
    nombre = nombre_valido(formulario.get('name'))
    try:
        categoria = db.session.get(Category, int(formulario.get('categoria', '')))
    except (ValueError, TypeError):
        categoria = None
    if not categoria:
        raise ValueError('Selecciona una categoría existente')
    if any(p.id != producto_id and p.name.casefold() == nombre.casefold()
           for p in Product.query.filter_by(categoria=categoria.id).all()):
        raise ValueError('Ya existe un producto con ese nombre en esta categoría')
    precio = precio_valido(formulario.get('price'))
    descripcion = (formulario.get('description') or '').strip()
    if len(descripcion) > 200:
        raise ValueError('La descripción admite hasta 200 caracteres')
    return dict(name=nombre, categoria=categoria.id, price=precio, description=descripcion,
                stock=stock_anterior or 0)


def variantes_validas(tamanos, precios, usados=None):
    if len(tamanos) != len(precios):
        raise ValueError('Revisa los tamaños y precios de las variantes')
    usados = usados if usados is not None else set()
    resultado = []
    for tamano, precio in zip(tamanos, precios):
        if not tamano.strip() and not precio.strip():
            continue
        nombre = nombre_valido(tamano, 'tamaño')
        if nombre.casefold() in usados:
            raise ValueError('No puede haber tamaños duplicados')
        usados.add(nombre.casefold())
        resultado.append((nombre, precio_valido(precio)))
    return resultado


def guardar_imagen(archivo, carpeta):
    if not archivo or not archivo.filename:
        return None
    extension = Path(archivo.filename).suffix.lower()
    cabecera = archivo.stream.read(8)
    archivo.stream.seek(0)
    valida = ((extension == '.png' and cabecera.startswith(b'\x89PNG\r\n\x1a\n')) or
              (extension in ('.jpg', '.jpeg') and cabecera.startswith(b'\xff\xd8\xff')) or
              (extension == '.gif' and cabecera[:6] in (b'GIF87a', b'GIF89a')))
    if not valida:
        raise ValueError('Selecciona una imagen PNG, JPG o GIF válida')
    directorio = Path(carpeta)
    directorio.mkdir(parents=True, exist_ok=True)
    nombre = uuid4().hex + extension
    ruta = directorio / nombre
    try:
        archivo.save(ruta)
    except Exception:
        ruta.unlink(missing_ok=True)
        raise
    return nombre


def borrar_imagen(nombre, carpeta):
    if nombre and Path(nombre).name == nombre:
        (Path(carpeta) / nombre).unlink(missing_ok=True)
