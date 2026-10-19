from flask import Flask
from flask_socketio import SocketIO
import os
import secrets
from pathlib import Path

app = Flask(__name__)
socketio = SocketIO(app)

UPLOAD_FOLDER = 'static/uploads'

def init_app():
    clave = os.environ.get('APP_SECRET_KEY')
    if not clave:
        carpeta = Path(app.instance_path)
        carpeta.mkdir(parents=True, exist_ok=True)
        archivo = carpeta / 'session.key'
        try:
            with archivo.open('x', encoding='utf-8') as salida:
                salida.write(secrets.token_hex(32))
        except FileExistsError:
            pass
        clave = archivo.read_text(encoding='utf-8').strip()
        if not clave:
            raise RuntimeError('La clave de sesión está vacía')
    app.config.update(SECRET_KEY=clave, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///products.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

    return app, socketio
