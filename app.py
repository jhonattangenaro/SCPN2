# app.py - Versión 2.8 con respaldo JSON
import sqlite3
import os
import json
import base64
import hashlib
import secrets
import shutil
from flask import Flask, render_template, request, jsonify, g, session, redirect, url_for, flash, Response
from datetime import datetime, timedelta
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=365)

# ---------- Base de datos ----------
from config import DATABASE
import database
app.config['MAX_CONTENT_LENGTH'] = 64 * 1024 * 1024  # respaldos de hasta 64 MB

SECRETARIAS_INICIALES = [
    ("DESPACHO DEL GOBERNADOR", 192),
    ("SECRETARIA CULTURAL", 264),
    ("SECRETARIA DE ADMINISTRACION Y FINANZAS", 253),
    ("SECRETARIA DE AMBIENTE", 62),
    ("SECRETARIA DE ASUNTOS ESTRATEGICOS Y PROYECTOS ESPECIALES", 8),
    ("SECRETARIA DE CIENCIA, TECNOLOGIA E INNOVACION", 29),
    ("SECRETARIA DE COMUNICACION E INFORMACION", 67),
    ("SECRETARIA DE DESARROLLO AGROINDUSTRIAL", 8),
    ("SECRETARIA DE DESARROLLO SOCIAL", 48),
    ("SECRETARIA DE ECONOMIA PRODUCTIVA", 16),
    ("SECRETARIA DE EDUCACION", 1540),
    ("SECRETARIA DE JUVENTUD", 22),
    ("SECRETARIA DE MANTENIMIENTO Y SERVICIOS GENERALES", 671),
    ("SECRETARIA DE PLANIFICACION PODER POPULAR COMUNAL", 115),
    ("SECRETARIA DE RELIGION Y CULTO", 17),
    ("SECRETARIA DE SEGURIDAD CIUDADANA", 2130),
    ("SECRETARIA DEL ADULTO MAYOR", 107),
    ("SECRETARIA DEL TALENTO HUMANO", 457),
    ("SECRETARIA DEL TURISMO", 52),
    ("SECRETARIA GENERAL DE GOBIERNO", 378),
    ("SECRETARIA POLITICA", 1178),
    ("SECRETARIA UNICA DEL SISTEMA INTEGRAL DE PROTECCION DE NIÑOS, NIÑAS Y ADOLESCENTES", 29),
]

# ---------- Auth ----------
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def superuser_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if not session.get('is_superuser'):
            flash('Acceso denegado. Se requieren permisos de superusuario.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if session.get('is_superuser') or session.get('is_full_access'):
            return f(*args, **kwargs)
        flash('Acceso denegado. Se requieren permisos de administrador.', 'danger')
        return redirect(url_for('dashboard'))
    return decorated

def can_view_module(module):
    if session.get('is_superuser') or session.get('is_full_access'):
        return True
    db = get_db()
    mod_perm = db.execute(
        "SELECT can_view FROM user_permissions WHERE user_id=? AND module=?",
        (session['user_id'], module)
    ).fetchone()
    if mod_perm and mod_perm['can_view']:
        return True
    ep = db.execute(
        "SELECT COUNT(*) as c FROM user_entity_permissions WHERE user_id=? AND module=?",
        (session['user_id'], module)
    ).fetchone()
    return ep and ep['c'] > 0

def permission_required(module):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            if session.get('is_superuser') or session.get('is_full_access'):
                return f(*args, **kwargs)
            if not can_view_module(module):
                flash(f'No tienes permisos para acceder al módulo {module}.', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated
    return decorator

# ---------- Init BD ----------
def init_db():
    print(f"Inicializando BD en: {database.describe()}", flush=True)
    conn = database.connect()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            username     TEXT    UNIQUE NOT NULL,
            password     TEXT    NOT NULL,
            full_name    TEXT    NOT NULL,
            is_superuser INTEGER NOT NULL DEFAULT 0,
            is_full_access INTEGER NOT NULL DEFAULT 0,
            is_active    INTEGER NOT NULL DEFAULT 1,
            created_at   TEXT    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS user_permissions (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id  INTEGER NOT NULL,
            module   TEXT    NOT NULL,
            can_view INTEGER NOT NULL DEFAULT 0,
            can_edit INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, module)
        );
        CREATE TABLE IF NOT EXISTS user_entity_permissions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            module     TEXT    NOT NULL,
            entity_id  INTEGER NOT NULL,
            can_edit   INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, module, entity_id)
        );
        CREATE TABLE IF NOT EXISTS secretarias (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            name             TEXT    UNIQUE NOT NULL,
            empleados        INTEGER NOT NULL DEFAULT 0,
            votos_reportados INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS institutos (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            name             TEXT    UNIQUE NOT NULL,
            empleados        INTEGER NOT NULL DEFAULT 0,
            votos_reportados INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS jubilados (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            name             TEXT    UNIQUE NOT NULL,
            total            INTEGER NOT NULL DEFAULT 0,
            votos_reportados INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS secretarias_history (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            entidad_id    INTEGER NOT NULL,
            timestamp     TEXT    NOT NULL,
            votos_sumados INTEGER NOT NULL,
            user_id       INTEGER,
            FOREIGN KEY (entidad_id) REFERENCES secretarias(id)
        );
        CREATE TABLE IF NOT EXISTS institutos_history (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            entidad_id    INTEGER NOT NULL,
            timestamp     TEXT    NOT NULL,
            votos_sumados INTEGER NOT NULL,
            user_id       INTEGER,
            FOREIGN KEY (entidad_id) REFERENCES institutos(id)
        );
        CREATE TABLE IF NOT EXISTS jubilados_history (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            entidad_id    INTEGER NOT NULL,
            timestamp     TEXT    NOT NULL,
            votos_sumados INTEGER NOT NULL,
            user_id       INTEGER,
            FOREIGN KEY (entidad_id) REFERENCES jubilados(id)
        );
    """)

    try:
        cursor.execute("ALTER TABLE users ADD COLUMN is_full_access INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    existing = cursor.execute("SELECT id FROM users WHERE username='admin'").fetchone()
    if not existing:
        cursor.execute(
            "INSERT INTO users (username, password, full_name, is_superuser, is_full_access, created_at) VALUES (?,?,?,1,0,?)",
            ('admin', hash_password('admin123'), 'Administrador del Sistema', datetime.now().isoformat())
        )
        print("✅ Superusuario 'admin' creado (contraseña: admin123)")

    # Las secretarías iniciales se cargan UNA sola vez; así, si las eliminas,
    # no reaparecen al reiniciar la app.
    cursor.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    if not cursor.execute("SELECT 1 FROM meta WHERE key='secretarias_seeded'").fetchone():
        for name, emp in SECRETARIAS_INICIALES:
            cursor.execute(
                "INSERT OR IGNORE INTO secretarias (name, empleados) VALUES (?,?)", (name, emp)
            )
        cursor.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('secretarias_seeded','1')")

    conn.commit()
    conn.close()
    print("✅ Base de datos inicializada")

init_db()

try:
    from export import export_bp
    app.register_blueprint(export_bp)
    print("✅ Blueprint de exportación registrado")
except Exception as e:
    print(f"❌ Error registrando blueprint: {e}")

# ---------- Helpers BD ----------
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = database.connect()
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

@app.before_request
def refresh_entity_modules():
    if 'user_id' in session and not (session.get('is_superuser') or session.get('is_full_access')):
        db = get_db()
        ep_mods = db.execute(
            "SELECT DISTINCT module FROM user_entity_permissions WHERE user_id=?",
            (session['user_id'],)
        ).fetchall()
        session['entity_modules'] = [r['module'] for r in ep_mods]
    else:
        session['entity_modules'] = []

def get_user_permissions(user_id):
    if session.get('is_superuser') or session.get('is_full_access'):
        return {mod: {'can_view': True, 'can_edit': True}
                for mod in ['secretarias', 'institutos', 'jubilados', 'grafico_general']}
    db = get_db()
    perms = db.execute("SELECT module, can_view, can_edit FROM user_permissions WHERE user_id=?", (user_id,)).fetchall()
    return {p['module']: {'can_view': bool(p['can_view']), 'can_edit': bool(p['can_edit'])} for p in perms}

def get_allowed_entity_ids(user_id, module):
    if session.get('is_superuser') or session.get('is_full_access'):
        return None
    db = get_db()
    mod_perm = db.execute(
        "SELECT can_view FROM user_permissions WHERE user_id=? AND module=?",
        (user_id, module)
    ).fetchone()
    if mod_perm and mod_perm['can_view']:
        return None
    rows = db.execute(
        "SELECT entity_id FROM user_entity_permissions WHERE user_id=? AND module=?",
        (user_id, module)
    ).fetchall()
    return {r['entity_id'] for r in rows}

def can_edit_entity(user_id, module, entity_id):
    if session.get('is_superuser') or session.get('is_full_access'):
        return True
    db = get_db()
    mod_perm = db.execute(
        "SELECT can_edit FROM user_permissions WHERE user_id=? AND module=?",
        (user_id, module)
    ).fetchone()
    if mod_perm and mod_perm['can_edit']:
        return True
    ep = db.execute(
        "SELECT can_edit FROM user_entity_permissions WHERE user_id=? AND module=? AND entity_id=?",
        (user_id, module, entity_id)
    ).fetchone()
    return bool(ep and ep['can_edit'])

# ---------- API stats (SIN jubilados) ----------
@app.route('/api/stats')
@login_required
def api_stats():
    db = get_db()
    rs = db.execute("SELECT COALESCE(SUM(empleados),0) te, COALESCE(SUM(votos_reportados),0) tv FROM secretarias").fetchone()
    ri = db.execute("SELECT COALESCE(SUM(empleados),0) te, COALESCE(SUM(votos_reportados),0) tv FROM institutos").fetchone()
    return jsonify({
        'secretarias': {'total': rs['te'], 'votos': rs['tv']},
        'institutos':  {'total': ri['te'], 'votos': ri['tv']},
    })

# ---------- API: todas las entidades ----------
@app.route('/api/entidades_todas')
@login_required
def api_entidades_todas():
    db = get_db()
    result = []
    sec_rows = db.execute(
        "SELECT id, name, empleados AS total, votos_reportados AS votos FROM secretarias ORDER BY name"
    ).fetchall()
    for r in sec_rows:
        result.append({
            'id': f'sec_{r["id"]}',
            'name': r['name'],
            'modulo': 'secretarias',
            'total': r['total'],
            'votos': r['votos'],
        })
    ins_rows = db.execute(
        "SELECT id, name, empleados AS total, votos_reportados AS votos FROM institutos ORDER BY name"
    ).fetchall()
    for r in ins_rows:
        result.append({
            'id': f'ins_{r["id"]}',
            'name': r['name'],
            'modulo': 'institutos',
            'total': r['total'],
            'votos': r['votos'],
        })
    return jsonify(result)

# ---------- Auth routes ----------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE username=? AND password=? AND is_active=1",
            (username, hash_password(password))
        ).fetchone()
        if user:
            session.permanent = True
            session['user_id']     = user['id']
            session['username']    = user['username']
            session['full_name']   = user['full_name']
            session['is_superuser']= bool(user['is_superuser'])
            session['is_full_access'] = bool(user['is_full_access'])
            session['permissions'] = get_user_permissions(user['id'])
            if not (session['is_superuser'] or session['is_full_access']):
                ep_mods = db.execute(
                    "SELECT DISTINCT module FROM user_entity_permissions WHERE user_id=?",
                    (user['id'],)
                ).fetchall()
                session['entity_modules'] = [r['module'] for r in ep_mods]
            else:
                session['entity_modules'] = []
            flash(f'Bienvenido, {user["full_name"]}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Usuario o contraseña incorrectos.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Sesión cerrada correctamente.', 'info')
    return redirect(url_for('login'))

# ---------- Dashboard ----------
@app.route('/')
@login_required
def dashboard():
    db = get_db()
    rs = db.execute("SELECT COALESCE(SUM(empleados),0) te, COALESCE(SUM(votos_reportados),0) tv FROM secretarias").fetchone()
    ri = db.execute("SELECT COALESCE(SUM(empleados),0) te, COALESCE(SUM(votos_reportados),0) tv FROM institutos").fetchone()
    stats = {
        'secretarias': {'total': rs['te'], 'votos': rs['tv']},
        'institutos':  {'total': ri['te'], 'votos': ri['tv']},
    }
    return render_template('dashboard.html', stats=stats)

# ---------- Admin usuarios ----------
MODULES = ['secretarias', 'institutos', 'jubilados', 'grafico_general']

@app.route('/admin/usuarios')
@admin_required
def admin_usuarios():
    db = get_db()
    users = db.execute("SELECT * FROM users ORDER BY is_superuser DESC, full_name").fetchall()
    secretarias = db.execute("SELECT id, name FROM secretarias ORDER BY name").fetchall()
    institutos   = db.execute("SELECT id, name FROM institutos ORDER BY name").fetchall()
    jubilados    = db.execute("SELECT id, name FROM jubilados ORDER BY name").fetchall()
    entidades = {
        'secretarias': [dict(r) for r in secretarias],
        'institutos':  [dict(r) for r in institutos],
        'jubilados':   [dict(r) for r in jubilados],
    }
    entity_perms = {}
    entity_counts = {}
    mod_perms = {}
    tipo_perms = {}
    for u in users:
        ep_rows = db.execute(
            "SELECT module, entity_id FROM user_entity_permissions WHERE user_id=?", (u['id'],)
        ).fetchall()
        ep_list = [f"{r['module']}_{r['entity_id']}" for r in ep_rows]
        entity_perms[u['id']] = ep_list
        counts = {mod: sum(1 for k in ep_list if k.startswith(f"{mod}_")) for mod in MODULES if mod != 'grafico_general'}
        entity_counts[u['id']] = counts

        mp_rows = db.execute(
            "SELECT module, can_view, can_edit FROM user_permissions WHERE user_id=?", (u['id'],)
        ).fetchall()
        mod_perms[u['id']] = {r['module']: dict(r) for r in mp_rows}

        tp = {}
        for mod in MODULES:
            if mod == 'grafico_general':
                tp[mod] = 'global' if mod in mod_perms[u['id']] else 'none'
            else:
                if mod in mod_perms[u['id']]:
                    tp[mod] = 'global'
                elif counts.get(mod, 0) > 0:
                    tp[mod] = 'especifico'
                else:
                    tp[mod] = 'none'
        tipo_perms[u['id']] = tp

    return render_template('admin_usuarios.html',
        users=[dict(u) for u in users], modules=MODULES,
        entidades=entidades, entity_perms=entity_perms,
        entity_counts=entity_counts, mod_perms=mod_perms,
        tipo_perms=tipo_perms,
        current_is_superuser=session['is_superuser']
    )

@app.route('/admin/usuarios/crear', methods=['POST'])
@admin_required
def crear_usuario():
    db = get_db()
    username  = request.form.get('username', '').strip()
    password  = request.form.get('password', '')
    full_name = request.form.get('full_name', '').strip()

    if not username or not password or not full_name:
        flash('Todos los campos son obligatorios.', 'danger')
        return redirect(url_for('admin_usuarios'))

    existing = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if existing:
        flash('El nombre de usuario ya existe.', 'danger')
        return redirect(url_for('admin_usuarios'))

    is_superuser = 0
    is_full_access = 0
    if session.get('is_superuser'):
        is_superuser = 1 if request.form.get('is_superuser') else 0
        is_full_access = 1 if request.form.get('is_full_access') else 0

    db.execute(
        "INSERT INTO users (username, password, full_name, is_superuser, is_full_access, created_at) VALUES (?,?,?,?,?,?)",
        (username, hash_password(password), full_name, is_superuser, is_full_access, datetime.now().isoformat())
    )
    db.commit()
    user = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if not is_superuser and not is_full_access:
        _save_permissions(db, user['id'], request.form)
    db.commit()
    flash(f'Usuario "{full_name}" creado exitosamente.', 'success')
    return redirect(url_for('admin_usuarios'))

@app.route('/admin/usuarios/<int:user_id>/permisos', methods=['POST'])
@admin_required
def actualizar_permisos(user_id):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        flash('Usuario no encontrado.', 'danger')
        return redirect(url_for('admin_usuarios'))

    if user['is_superuser'] and not session.get('is_superuser'):
        flash('No tienes permisos para modificar a un superusuario.', 'danger')
        return redirect(url_for('admin_usuarios'))

    if session.get('is_superuser') and user['id'] != session['user_id']:
        new_full_access = 1 if request.form.get('is_full_access') else 0
        db.execute("UPDATE users SET is_full_access=? WHERE id=?", (new_full_access, user_id))
        db.commit()

    if user['is_full_access']:
        db.execute("DELETE FROM user_permissions WHERE user_id=?", (user_id,))
        db.execute("DELETE FROM user_entity_permissions WHERE user_id=?", (user_id,))
        db.commit()
        flash('Permisos actualizados (Acceso Total activo).', 'success')
        return redirect(url_for('admin_usuarios'))

    db.execute("DELETE FROM user_permissions WHERE user_id=?", (user_id,))
    db.execute("DELETE FROM user_entity_permissions WHERE user_id=?", (user_id,))
    db.commit()
    _save_permissions(db, user_id, request.form)
    db.commit()
    flash('Permisos actualizados correctamente.', 'success')
    return redirect(url_for('admin_usuarios'))

def _save_permissions(db, uid, form):
    for mod in MODULES:
        if mod == 'grafico_general':
            tipo_perm = form.get(f'tipo_perm_{mod}', 'none')
            if tipo_perm == 'global':
                db.execute(
                    "INSERT OR REPLACE INTO user_permissions (user_id, module, can_view, can_edit) VALUES (?,?,1,0)",
                    (uid, mod)
                )
        else:
            tipo_perm = form.get(f'tipo_perm_{mod}', 'none')
            if tipo_perm == 'global':
                can_edit = 1 if form.get(f'global_edit_{mod}') else 0
                db.execute(
                    "INSERT OR REPLACE INTO user_permissions (user_id, module, can_view, can_edit) VALUES (?,?,1,?)",
                    (uid, mod, can_edit)
                )
            elif tipo_perm == 'especifico':
                entity_ids = form.getlist(f'entities_{mod}')
                for eid in entity_ids:
                    try:
                        db.execute(
                            "INSERT OR REPLACE INTO user_entity_permissions (user_id, module, entity_id, can_edit) VALUES (?,?,?,1)",
                            (uid, mod, int(eid))
                        )
                    except Exception:
                        pass

@app.route('/admin/usuarios/<int:user_id>/toggle', methods=['POST'])
@admin_required
def toggle_usuario(user_id):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        return jsonify({'status': 'error', 'message': 'Usuario no encontrado'}), 404

    if user['is_superuser'] and not session.get('is_superuser'):
        return jsonify({'status': 'error', 'message': 'No puedes desactivar a un superusuario'}), 403

    new_status = 0 if user['is_active'] else 1
    db.execute("UPDATE users SET is_active=? WHERE id=?", (new_status, user_id))
    db.commit()
    return jsonify({'status': 'success', 'is_active': new_status})

@app.route('/admin/usuarios/<int:user_id>/reset_password', methods=['POST'])
@admin_required
def reset_password(user_id):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        flash('Usuario no encontrado.', 'danger')
        return redirect(url_for('admin_usuarios'))

    if user['is_superuser'] and not session.get('is_superuser'):
        flash('No puedes resetear la contraseña de un superusuario.', 'danger')
        return redirect(url_for('admin_usuarios'))

    new_pass = request.form.get('new_password', '')
    if not new_pass:
        flash('La contraseña no puede estar vacía.', 'danger')
        return redirect(url_for('admin_usuarios'))
    db.execute("UPDATE users SET password=? WHERE id=?", (hash_password(new_pass), user_id))
    db.commit()
    flash('Contraseña actualizada correctamente.', 'success')
    return redirect(url_for('admin_usuarios'))

# ---------- Admin entidades ----------
@app.route('/admin/entidades')
@admin_required
def admin_entidades():
    db = get_db()
    secretarias = db.execute("SELECT * FROM secretarias ORDER BY name").fetchall()
    institutos   = db.execute("SELECT * FROM institutos ORDER BY name").fetchall()
    jubilados    = db.execute("SELECT * FROM jubilados ORDER BY name").fetchall()
    return render_template('admin_entidades.html',
        secretarias=[dict(r) for r in secretarias],
        institutos=[dict(r) for r in institutos],
        jubilados=[dict(r) for r in jubilados]
    )

@app.route('/admin/entidades/crear', methods=['POST'])
@admin_required
def crear_entidad():
    tipo  = request.form.get('tipo')
    name  = request.form.get('name', '').strip()
    total = request.form.get('total', 0)
    if not tipo or not name:
        flash('Tipo y nombre son obligatorios.', 'danger')
        return redirect(url_for('admin_entidades'))
    db = get_db()
    try:
        total = int(total)
        if tipo == 'secretarias':
            db.execute("INSERT INTO secretarias (name, empleados) VALUES (?,?)", (name, total))
        elif tipo == 'institutos':
            db.execute("INSERT INTO institutos (name, empleados) VALUES (?,?)", (name, total))
        elif tipo == 'jubilados':
            db.execute("INSERT INTO jubilados (name, total) VALUES (?,?)", (name, total))
        db.commit()
        flash(f'"{name}" registrado exitosamente en {tipo}.', 'success')
    except sqlite3.IntegrityError:
        flash(f'Ya existe una entidad con ese nombre en {tipo}.', 'danger')
    except ValueError:
        flash('El total debe ser un número.', 'danger')
    return redirect(url_for('admin_entidades'))

@app.route('/admin/entidades/<tipo>/<int:eid>/editar', methods=['POST'])
@admin_required
def editar_entidad(tipo, eid):
    db = get_db()
    name  = request.form.get('name', '').strip()
    total = request.form.get('total', 0)
    try:
        total = int(total)
        if tipo == 'secretarias':
            db.execute("UPDATE secretarias SET name=?, empleados=? WHERE id=?", (name, total, eid))
        elif tipo == 'institutos':
            db.execute("UPDATE institutos SET name=?, empleados=? WHERE id=?", (name, total, eid))
        elif tipo == 'jubilados':
            db.execute("UPDATE jubilados SET name=?, total=? WHERE id=?", (name, total, eid))
        db.commit()
        flash('Entidad actualizada correctamente.', 'success')
    except Exception as e:
        flash(f'Error: {e}', 'danger')
    return redirect(url_for('admin_entidades'))

TIPOS_ENTIDAD = ('secretarias', 'institutos', 'jubilados')

def _borrar_entidades(db, tipo, ids):
    """Borra entidades + historial + permisos. Devuelve cuántas se eliminaron."""
    if tipo not in TIPOS_ENTIDAD or not ids:
        return 0
    marks = ','.join('?' * len(ids))
    db.execute(f"DELETE FROM {tipo}_history WHERE entidad_id IN ({marks})", ids)
    db.execute("DELETE FROM user_entity_permissions WHERE module=? AND entity_id IN (%s)" % marks, [tipo] + ids)
    cur = db.execute(f"DELETE FROM {tipo} WHERE id IN ({marks})", ids)
    return cur.rowcount

@app.route('/admin/entidades/<tipo>/<int:eid>/eliminar', methods=['POST'])
@superuser_required
def eliminar_entidad(tipo, eid):
    if tipo not in TIPOS_ENTIDAD:
        flash('Tipo de entidad inválido.', 'danger')
        return redirect(url_for('admin_entidades'))
    db = get_db()
    n = _borrar_entidades(db, tipo, [eid])
    db.commit()
    flash('Entidad eliminada.' if n else 'La entidad no existe.', 'success' if n else 'warning')
    return redirect(url_for('admin_entidades'))

@app.route('/admin/entidades/<tipo>/eliminar_multiple', methods=['POST'])
@superuser_required
def eliminar_entidades_multiple(tipo):
    if tipo not in TIPOS_ENTIDAD:
        flash('Tipo de entidad inválido.', 'danger')
        return redirect(url_for('admin_entidades'))
    try:
        ids = sorted({int(x) for x in request.form.getlist('ids')})
    except ValueError:
        flash('Selección inválida.', 'danger')
        return redirect(url_for('admin_entidades'))
    if not ids:
        flash('No seleccionaste ninguna entidad.', 'warning')
        return redirect(url_for('admin_entidades'))
    db = get_db()
    try:
        n = 0
        for i in range(0, len(ids), 500):          # lotes (límite de variables de SQLite)
            n += _borrar_entidades(db, tipo, ids[i:i+500])
        db.commit()
        flash(f'{n} entidad(es) eliminada(s) de {tipo}.', 'success')
    except Exception as e:
        db.rollback()
        flash(f'Error al eliminar: {e}', 'danger')
    return redirect(url_for('admin_entidades'))

# ---------- Respaldo / Restaurar ----------
@app.route('/admin/respaldo')
@admin_required
def admin_respaldo():
    db = get_db()
    stats = {
        'users':                db.execute("SELECT COUNT(*) c FROM users").fetchone()['c'],
        'secretarias':          db.execute("SELECT COUNT(*) c FROM secretarias").fetchone()['c'],
        'institutos':           db.execute("SELECT COUNT(*) c FROM institutos").fetchone()['c'],
        'jubilados':            db.execute("SELECT COUNT(*) c FROM jubilados").fetchone()['c'],
        'secretarias_history':  db.execute("SELECT COUNT(*) c FROM secretarias_history").fetchone()['c'],
        'institutos_history':   db.execute("SELECT COUNT(*) c FROM institutos_history").fetchone()['c'],
        'jubilados_history':    db.execute("SELECT COUNT(*) c FROM jubilados_history").fetchone()['c'],
    }
    return render_template('admin_respaldo.html', stats=stats)


@app.route('/admin/respaldo/descargar')
@admin_required
def descargar_respaldo():
    db = get_db()
    tablas = [
        'users', 'secretarias', 'institutos', 'jubilados',
        'user_permissions', 'user_entity_permissions',
        'secretarias_history', 'institutos_history', 'jubilados_history'
    ]
    backup = {
        'app': 'SCPN - Consulta Popular Nacional 2026',
        'version': '1.0',
        'fecha_generacion': datetime.now().isoformat(),
        'generado_por': session.get('username', 'desconocido'),
        'datos': {}
    }
    for tabla in tablas:
        try:
            rows = db.execute(f"SELECT * FROM {tabla}").fetchall()
            backup['datos'][tabla] = [dict(r) for r in rows]
        except Exception as e:
            print(f"⚠ Error exportando {tabla}: {e}")
            backup['datos'][tabla] = []

    # Guardar copia local adicional
    try:
        carpeta = os.path.dirname(os.path.abspath(DATABASE))
        ruta_copia = os.path.join(carpeta, 'ultimo_respaldo.json')
        with open(ruta_copia, 'w', encoding='utf-8') as f:
            json.dump(backup, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠ No se pudo guardar copia local del respaldo: {e}")

    json_bytes = json.dumps(backup, ensure_ascii=False, indent=2).encode('utf-8')
    fname = f"respaldo_scpn_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    return Response(
        json_bytes,
        mimetype='application/json',
        headers={'Content-Disposition': f'attachment; filename={fname}'}
    )


@app.route('/admin/respaldo/importar', methods=['POST'])
@admin_required
def importar_respaldo():
    ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    t0 = datetime.now()

    def fin(msg, cat):
        print(f"[IMPORTAR] {cat.upper()}: {msg}", flush=True)
        if ajax:
            return jsonify(ok=(cat == 'success'), message=msg)
        flash(msg, cat)
        return redirect(url_for('admin_respaldo'))

    print(f"[IMPORTAR] Petición recibida ({request.content_length or 0} bytes)", flush=True)
    archivo = request.files.get('archivo')
    if not archivo or not archivo.filename:
        return fin('No se seleccionó ningún archivo.', 'danger')
    if not archivo.filename.lower().endswith('.json'):
        return fin('El archivo debe tener extensión .json', 'danger')

    modo = request.form.get('modo', 'reemplazar')
    if modo not in ('reemplazar', 'fusionar'):
        modo = 'reemplazar'

    try:
        data = json.loads(archivo.read().decode('utf-8-sig'))
    except Exception as e:
        return fin(f'Error al leer el JSON: {e}', 'danger')

    if not isinstance(data, dict) or not isinstance(data.get('datos'), dict):
        return fin('Estructura de respaldo inválida (falta la clave "datos").', 'danger')
    if not str(data.get('app', '')).startswith('SCPN'):
        return fin('Este archivo no parece ser un respaldo de SCPN.', 'danger')

    tablas_orden = [
        'users', 'secretarias', 'institutos', 'jubilados',
        'user_permissions', 'user_entity_permissions',
        'secretarias_history', 'institutos_history', 'jubilados_history'
    ]

    conn = get_db()
    admin_actual = None
    if session.get('user_id'):
        row = conn.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
        admin_actual = dict(row) if row else None

    totales = {}
    try:
        if modo == 'reemplazar':
            for t in reversed(tablas_orden):
                conn.execute(f"DELETE FROM {t}")

        for tabla in tablas_orden:
            rows = data['datos'].get(tabla, [])
            if not isinstance(rows, list) or not rows:
                continue

            # Solo columnas que existen en la tabla (evita inyección y errores)
            validas = {r['name'] for r in conn.execute(f"PRAGMA table_info({tabla})")}
            lotes = {}
            for row in rows:
                if not isinstance(row, dict):
                    continue
                cols = tuple(c for c in row.keys() if c in validas)
                if cols:
                    lotes.setdefault(cols, []).append([row[c] for c in cols])

            verbo = 'INSERT OR REPLACE' if modo == 'fusionar' else 'INSERT OR IGNORE'
            insertados = 0
            for cols, valores in lotes.items():
                col_names = ','.join(f'"{c}"' for c in cols)
                una = '(' + ','.join('?' * len(cols)) + ')'
                por_lote = max(1, 900 // len(cols))        # límite de variables por sentencia
                # Varias filas por sentencia y varias sentencias por viaje (importante con Turso)
                stmts = []
                for i in range(0, len(valores), por_lote):
                    chunk = valores[i:i + por_lote]
                    params = [v for fila in chunk for v in fila]
                    stmts.append((f"{verbo} INTO {tabla} ({col_names}) VALUES " + ','.join([una] * len(chunk)), params))
                conn.batch(stmts)
                insertados += len(valores)
            totales[tabla] = insertados

        # Garantizar que el admin que importa siga existiendo
        if admin_actual:
            existe = conn.execute("SELECT 1 FROM users WHERE id=?", (admin_actual['id'],)).fetchone()
            if not existe:
                conn.execute("DELETE FROM users WHERE username=?", (admin_actual['username'],))
                conn.execute(
                    "INSERT INTO users (id, username, password, full_name, is_superuser, is_full_access, is_active, created_at) "
                    "VALUES (?,?,?,?,?,?,1,?)",
                    (admin_actual['id'], admin_actual['username'], admin_actual['password'],
                     admin_actual['full_name'], admin_actual['is_superuser'],
                     admin_actual.get('is_full_access', 0), admin_actual['created_at'])
                )

        # Reajustar AUTOINCREMENT
        for tabla in tablas_orden:
            maxid = conn.execute(f"SELECT COALESCE(MAX(id),0) FROM {tabla}").fetchone()[0]
            conn.execute("UPDATE sqlite_sequence SET seq=? WHERE name=?", (maxid, tabla))

        conn.commit()
        try:
            conn.sync()
        except Exception as e:
            print(f"[IMPORTAR] aviso al sincronizar: {e}", flush=True)
        resumen = ' · '.join(f"{k}: {v}" for k, v in totales.items() if v)
        msg_ok = f'✅ Respaldo importado correctamente (modo: {modo}, {(datetime.now()-t0).total_seconds():.1f}s). {resumen}'
    except Exception as e:
        conn.rollback()
        return fin(f'❌ Error al importar el respaldo (no se modificó nada): {e}', 'danger')
    return fin(msg_ok, 'success')

# ---------- Módulos ----------
@app.route('/secretarias')
@login_required
@permission_required('secretarias')
def secretarias_list():
    db = get_db()
    rows = db.execute("SELECT * FROM secretarias ORDER BY name").fetchall()
    allowed = get_allowed_entity_ids(session['user_id'], 'secretarias')
    entidades = []
    for r in rows:
        if allowed is None or r['id'] in allowed:
            d = dict(r)
            d['can_edit'] = can_edit_entity(session['user_id'], 'secretarias', r['id'])
            entidades.append(d)
    return render_template('module_list.html',
        titulo='Secretarías', modulo='secretarias',
        entidades=entidades, campo_total='empleados')

@app.route('/secretarias/<int:eid>')
@login_required
def secretaria_detail(eid):
    db = get_db()
    allowed = get_allowed_entity_ids(session['user_id'], 'secretarias')
    if allowed is not None and eid not in allowed:
        flash('No tienes acceso a esta secretaría.', 'danger')
        return redirect(url_for('secretarias_list'))
    row = db.execute("SELECT * FROM secretarias WHERE id=?", (eid,)).fetchone()
    if not row: return "No encontrado", 404
    history = db.execute(
        "SELECT h.*, u.full_name FROM secretarias_history h LEFT JOIN users u ON h.user_id=u.id WHERE h.entidad_id=? ORDER BY h.timestamp DESC",
        (eid,)
    ).fetchall()
    return render_template('module_detail.html',
        titulo='Secretaría', modulo='secretarias', entidad=dict(row),
        campo_total='empleados', history=[dict(h) for h in history],
        can_edit=can_edit_entity(session['user_id'], 'secretarias', eid))

@app.route('/secretarias/<int:eid>/votos', methods=['POST'])
@login_required
def update_votos_secretaria(eid):
    if not can_edit_entity(session['user_id'], 'secretarias', eid):
        return jsonify({'status': 'error', 'message': 'Sin permisos de edición'}), 403
    return _update_votos(get_db(), 'secretarias', eid, 'empleados', 'secretarias_history')

@app.route('/secretarias/<int:eid>/votos/<int:hid>/delete', methods=['POST'])
@login_required
def delete_voto_secretaria(eid, hid):
    if not can_edit_entity(session['user_id'], 'secretarias', eid):
        return jsonify({'status': 'error', 'message': 'Sin permisos'}), 403
    return _delete_voto(get_db(), 'secretarias', eid, hid, 'empleados', 'secretarias_history')

@app.route('/institutos')
@login_required
@permission_required('institutos')
def institutos_list():
    db = get_db()
    rows = db.execute("SELECT * FROM institutos ORDER BY name").fetchall()
    allowed = get_allowed_entity_ids(session['user_id'], 'institutos')
    entidades = []
    for r in rows:
        if allowed is None or r['id'] in allowed:
            d = dict(r)
            d['can_edit'] = can_edit_entity(session['user_id'], 'institutos', r['id'])
            entidades.append(d)
    return render_template('module_list.html',
        titulo='Institutos', modulo='institutos',
        entidades=entidades, campo_total='empleados')

@app.route('/institutos/<int:eid>')
@login_required
def instituto_detail(eid):
    db = get_db()
    allowed = get_allowed_entity_ids(session['user_id'], 'institutos')
    if allowed is not None and eid not in allowed:
        flash('No tienes acceso a este instituto.', 'danger')
        return redirect(url_for('institutos_list'))
    row = db.execute("SELECT * FROM institutos WHERE id=?", (eid,)).fetchone()
    if not row: return "No encontrado", 404
    history = db.execute(
        "SELECT h.*, u.full_name FROM institutos_history h LEFT JOIN users u ON h.user_id=u.id WHERE h.entidad_id=? ORDER BY h.timestamp DESC",
        (eid,)
    ).fetchall()
    return render_template('module_detail.html',
        titulo='Instituto', modulo='institutos', entidad=dict(row),
        campo_total='empleados', history=[dict(h) for h in history],
        can_edit=can_edit_entity(session['user_id'], 'institutos', eid))

@app.route('/institutos/<int:eid>/votos', methods=['POST'])
@login_required
def update_votos_instituto(eid):
    if not can_edit_entity(session['user_id'], 'institutos', eid):
        return jsonify({'status': 'error', 'message': 'Sin permisos de edición'}), 403
    return _update_votos(get_db(), 'institutos', eid, 'empleados', 'institutos_history')

@app.route('/institutos/<int:eid>/votos/<int:hid>/delete', methods=['POST'])
@login_required
def delete_voto_instituto(eid, hid):
    if not can_edit_entity(session['user_id'], 'institutos', eid):
        return jsonify({'status': 'error', 'message': 'Sin permisos'}), 403
    return _delete_voto(get_db(), 'institutos', eid, hid, 'empleados', 'institutos_history')

# ---------- Rutas de Jubilados (ocultas en UI) ----------
@app.route('/jubilados')
@login_required
@permission_required('jubilados')
def jubilados_list():
    db = get_db()
    rows = db.execute("SELECT * FROM jubilados ORDER BY name").fetchall()
    allowed = get_allowed_entity_ids(session['user_id'], 'jubilados')
    entidades = []
    for r in rows:
        if allowed is None or r['id'] in allowed:
            d = dict(r)
            d['can_edit'] = can_edit_entity(session['user_id'], 'jubilados', r['id'])
            entidades.append(d)
    return render_template('module_list.html',
        titulo='Jubilados', modulo='jubilados',
        entidades=entidades, campo_total='total')

@app.route('/jubilados/<int:eid>')
@login_required
def jubilado_detail(eid):
    db = get_db()
    allowed = get_allowed_entity_ids(session['user_id'], 'jubilados')
    if allowed is not None and eid not in allowed:
        flash('No tienes acceso a este grupo.', 'danger')
        return redirect(url_for('jubilados_list'))
    row = db.execute("SELECT * FROM jubilados WHERE id=?", (eid,)).fetchone()
    if not row: return "No encontrado", 404
    history = db.execute(
        "SELECT h.*, u.full_name FROM jubilados_history h LEFT JOIN users u ON h.user_id=u.id WHERE h.entidad_id=? ORDER BY h.timestamp DESC",
        (eid,)
    ).fetchall()
    return render_template('module_detail.html',
        titulo='Jubilados', modulo='jubilados', entidad=dict(row),
        campo_total='total', history=[dict(h) for h in history],
        can_edit=can_edit_entity(session['user_id'], 'jubilados', eid))

@app.route('/jubilados/<int:eid>/votos', methods=['POST'])
@login_required
def update_votos_jubilado(eid):
    if not can_edit_entity(session['user_id'], 'jubilados', eid):
        return jsonify({'status': 'error', 'message': 'Sin permisos de edición'}), 403
    return _update_votos(get_db(), 'jubilados', eid, 'total', 'jubilados_history')

@app.route('/jubilados/<int:eid>/votos/<int:hid>/delete', methods=['POST'])
@login_required
def delete_voto_jubilado(eid, hid):
    if not can_edit_entity(session['user_id'], 'jubilados', eid):
        return jsonify({'status': 'error', 'message': 'Sin permisos'}), 403
    return _delete_voto(get_db(), 'jubilados', eid, hid, 'total', 'jubilados_history')

def _update_votos(db, tabla, eid, campo_total, history_table):
    row = db.execute(f"SELECT * FROM {tabla} WHERE id=?", (eid,)).fetchone()
    if not row:
        return jsonify({'status': 'error', 'message': 'No encontrado'}), 404
    try:
        votos = int(request.form['votos'])
        if votos < 0:
            return jsonify({'status': 'error', 'message': 'Los votos no pueden ser negativos'}), 400
        new_total = row['votos_reportados'] + votos
        if new_total > row[campo_total]:
            return jsonify({'status': 'error', 'message': 'Excede el total registrado'}), 400
        db.execute(f"UPDATE {tabla} SET votos_reportados=? WHERE id=?", (new_total, eid))
        db.execute(
            f"INSERT INTO {history_table} (entidad_id, timestamp, votos_sumados, user_id) VALUES (?,?,?,?)",
            (eid, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), votos, session.get('user_id'))
        )
        db.commit()
        history = db.execute(
            f"SELECT h.*, u.full_name FROM {history_table} h LEFT JOIN users u ON h.user_id=u.id WHERE h.entidad_id=? ORDER BY h.timestamp DESC",
            (eid,)
        ).fetchall()
        return jsonify({'status': 'success', 'new_votos': new_total, 'history': [dict(h) for h in history]})
    except ValueError:
        return jsonify({'status': 'error', 'message': 'Valor inválido'}), 400

def _delete_voto(db, tabla, eid, hid, campo_total, history_table):
    entry = db.execute(f"SELECT * FROM {history_table} WHERE id=? AND entidad_id=?", (hid, eid)).fetchone()
    if not entry:
        return jsonify({'status': 'error', 'message': 'Registro no encontrado'}), 404
    db.execute(f"DELETE FROM {history_table} WHERE id=?", (hid,))
    total = db.execute(
        f"SELECT COALESCE(SUM(votos_sumados),0) FROM {history_table} WHERE entidad_id=?", (eid,)
    ).fetchone()[0]
    db.execute(f"UPDATE {tabla} SET votos_reportados=? WHERE id=?", (total, eid))
    db.commit()
    history = db.execute(
        f"SELECT h.*, u.full_name FROM {history_table} h LEFT JOIN users u ON h.user_id=u.id WHERE h.entidad_id=? ORDER BY h.timestamp DESC",
        (eid,)
    ).fetchall()
    return jsonify({'status': 'success', 'new_votos': total, 'history': [dict(h) for h in history]})

# ---------- Gráfico general ----------
@app.route('/grafico')
@login_required
@permission_required('grafico_general')
def grafico_general():
    db = get_db()
    rs = db.execute("SELECT COALESCE(SUM(empleados),0) te, COALESCE(SUM(votos_reportados),0) tv FROM secretarias").fetchone()
    ri = db.execute("SELECT COALESCE(SUM(empleados),0) te, COALESCE(SUM(votos_reportados),0) tv FROM institutos").fetchone()
    total = rs['te'] + ri['te']
    votos = rs['tv'] + ri['tv']

    logo_b64 = ''
    try:
        logo_path = os.path.join(app.static_folder, 'logo.png')
        if os.path.exists(logo_path):
            with open(logo_path, 'rb') as f:
                logo_b64 = base64.b64encode(f.read()).decode('utf-8')
    except Exception:
        pass

    return render_template('grafico_general.html',
        total_empleados=total,
        total_votos_reportados=votos,
        votos_faltantes=total - votos,
        logo_b64=logo_b64,
    )

@app.route('/grafico_general')
@login_required
def grafico_general_legacy():
    return redirect(url_for('grafico_general'))

# ---------- API para entidades ----------
@app.route('/api/stats/entidades')
@login_required
def api_stats_entidades():
    modulo = request.args.get('modulo', '')
    db = get_db()
    if modulo == 'secretarias':
        rows = db.execute(
            "SELECT name, empleados AS total, votos_reportados AS votos FROM secretarias ORDER BY name"
        ).fetchall()
    elif modulo == 'institutos':
        rows = db.execute(
            "SELECT name, empleados AS total, votos_reportados AS votos FROM institutos ORDER BY name"
        ).fetchall()
    elif modulo == 'jubilados':
        rows = db.execute(
            "SELECT name, total, votos_reportados AS votos FROM jubilados ORDER BY name"
        ).fetchall()
    else:
        return jsonify([])
    return jsonify([{'name': r['name'], 'total': r['total'], 'votos': r['votos']} for r in rows])

@app.route('/test')
def test():
    return "✅ App v2.8 funcionando"

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8060))
    app.run(debug=True, host='0.0.0.0', port=port)
