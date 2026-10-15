# config.py - Ruta única de la base de datos (la usan app.py y export.py)
import os
import shutil


def get_database_path():
    # 1) Permite forzar la ruta con una variable de entorno (recomendado en Render)
    forced = os.environ.get('DATABASE_PATH')
    if forced:
        os.makedirs(os.path.dirname(os.path.abspath(forced)), exist_ok=True)
        return forced

    # 2) Disco persistente de Render (/data), si está montado y es escribible
    if os.path.isdir('/data') and os.access('/data', os.W_OK):
        path = '/data/elecciones.db'
        if not os.path.exists(path) and os.path.exists('elecciones.db'):
            shutil.copy('elecciones.db', path)
        return path

    # 3) PythonAnywhere
    home = os.path.expanduser('~')
    if os.path.isdir(os.path.join(home, 'SCPN')):
        return os.path.join(home, 'SCPN', 'elecciones.db')

    # 4) Render sin disco: /tmp (se pierde al reiniciar)
    if os.environ.get('RENDER'):
        return '/tmp/elecciones.db'

    # 5) Local
    return 'elecciones.db'


DATABASE = get_database_path()
