from routes import *
from __init__ import init_app

app = init_app()
app.secret_key = b'_5#y2L"F4Q8z\n\xec]/'

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)