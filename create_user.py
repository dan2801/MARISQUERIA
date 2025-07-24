from app import app
from models import db, User
from werkzeug.security import generate_password_hash

with app.app_context():
    nuevo_usuario = User(
        username='daniel',
        password=generate_password_hash('daniel'),  # Hashear la contraseña
        rol='user'
    )
    db.session.add(nuevo_usuario)
    db.session.commit()
    print("Usuario creado con éxito.")
