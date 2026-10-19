import hashlib
import json
from functools import wraps
from flask import request, jsonify, g, session
from models import db, Users, OperacionPedido


def operacion_repetible(f):
    """La respuesta se persiste en la misma transacción que el cambio."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        g.operacion_pedido = None
        clave = request.headers.get('Idempotency-Key')
        if clave:
            if not 16 <= len(clave) <= 64 or not all(c.isascii() and (c.isalnum() or c == '-') for c in clave):
                return jsonify(success=False, message='Identificador de operación inválido'), 400
            datos = request.get_json(silent=True) if request.is_json else request.form.to_dict(flat=False)
            if isinstance(datos, dict):
                datos = {k: v for k, v in datos.items() if k != 'csrf_token'}
            huella = hashlib.sha256(json.dumps([request.path, datos], sort_keys=True).encode()).hexdigest()
            usuario = Users.query.filter_by(username=session['username']).one()
            anterior = db.session.get(OperacionPedido, clave)
            if anterior:
                if anterior.usuario_id != usuario.id or anterior.huella != huella:
                    return jsonify(success=False, message='La operación no coincide con el envío original'), 409
                return jsonify(anterior.respuesta)
            g.operacion_pedido = dict(clave=clave, usuario_id=usuario.id, huella=huella)
        return f(*args, **kwargs)
    return wrapped


def confirmar_cambio(respuesta=None):
    operacion = getattr(g, 'operacion_pedido', None)
    if operacion:
        db.session.add(OperacionPedido(**operacion, respuesta=respuesta or {'success': True}))
    db.session.commit()
