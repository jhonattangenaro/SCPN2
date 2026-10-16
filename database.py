# database.py - Capa de conexión: SQLite local o Turso (libSQL) según variables de entorno.
#
#  - Sin TURSO_DATABASE_URL  -> usa sqlite3 normal (igual que antes).
#  - Con TURSO_DATABASE_URL + TURSO_AUTH_TOKEN -> réplica embebida de Turso:
#       lecturas rápidas desde un archivo local, escrituras enviadas a Turso (persisten).
import os
import sqlite3
import threading

from config import DATABASE

TURSO_URL = os.environ.get('TURSO_DATABASE_URL', '').strip()
TURSO_TOKEN = os.environ.get('TURSO_AUTH_TOKEN', '').strip()
USE_TURSO = bool(TURSO_URL and TURSO_TOKEN)

_lock = threading.RLock()      # un solo acceso a la vez a la conexión de Turso
_raw = None                    # conexión libsql compartida (singleton)


class Row(tuple):
    """Fila compatible con sqlite3.Row: row['col'], row[0], dict(row), keys()."""
    def __new__(cls, values, names):
        obj = super().__new__(cls, values)
        obj._names = list(names)
        return obj

    def keys(self):
        return list(self._names)

    def __getitem__(self, k):
        if isinstance(k, str):
            try:
                return tuple.__getitem__(self, self._names.index(k))
            except ValueError:
                raise IndexError(f"No existe la columna '{k}'")
        return tuple.__getitem__(self, k)


def _translate(exc):
    msg = str(exc)
    if 'constraint failed' in msg.lower():
        return sqlite3.IntegrityError(msg)
    return sqlite3.OperationalError(msg)


class Cursor:
    def __init__(self, cur):
        self._cur = cur
        self.rowcount = getattr(cur, 'rowcount', -1)
        self.lastrowid = getattr(cur, 'lastrowid', None)

    def _names(self):
        d = getattr(self._cur, 'description', None) or []
        return [c[0] for c in d]

    def fetchone(self):
        r = self._cur.fetchone()
        return None if r is None else Row(r, self._names())

    def fetchall(self):
        names = self._names()
        return [Row(r, names) for r in self._cur.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())


class Connection:
    """Envuelve sqlite3 o libsql con la misma interfaz."""
    def __init__(self, raw, shared=False, owns_lock=False):
        self._c = raw
        self._shared = shared
        self._locked = False
        if shared:
            _lock.acquire()
            self._locked = True

    def execute(self, sql, params=()):
        try:
            return Cursor(self._c.execute(sql, tuple(params)))
        except ValueError as e:                      # libsql lanza ValueError
            raise _translate(e) from None

    def executemany(self, sql, seq):
        try:
            return Cursor(self._c.executemany(sql, [tuple(x) for x in seq]))
        except ValueError as e:
            raise _translate(e) from None

    def executescript(self, script):
        try:
            self._c.executescript(script)
        except ValueError as e:
            raise _translate(e) from None

    def cursor(self):
        return self

    def commit(self):
        self._c.commit()

    def rollback(self):
        try:
            self._c.rollback()
        except Exception:
            pass

    def close(self):
        if self._shared:
            if self._locked:
                try:
                    self._c.rollback()           # descarta lo que no se confirmó
                except Exception:
                    pass
                self._locked = False
                _lock.release()
        else:
            self._c.close()

    def sync(self):
        if self._shared and hasattr(self._c, 'sync'):
            self._c.sync()


def _get_raw_libsql():
    global _raw
    if _raw is None:
        import libsql
        local = os.environ.get('TURSO_LOCAL_REPLICA', '/tmp/turso_replica.db')
        print(f"☁️  Conectando a Turso ({TURSO_URL}) con réplica local {local}", flush=True)
        _raw = libsql.connect(local, sync_url=TURSO_URL, auth_token=TURSO_TOKEN)
        _raw.sync()
        print("☁️  Turso sincronizado", flush=True)
    return _raw


def connect(timeout=30, autocommit_manual=False):
    """Devuelve una conexión. En modo Turso es compartida y se serializa con un lock."""
    if USE_TURSO:
        return Connection(_get_raw_libsql(), shared=True)
    c = sqlite3.connect(DATABASE, timeout=timeout)
    c.row_factory = sqlite3.Row
    return _SqliteConn(c)


class _SqliteConn:
    """Envoltorio mínimo para sqlite3 (mantiene commit/rollback/close/executescript)."""
    def __init__(self, c):
        self._c = c

    def execute(self, sql, params=()):
        return self._c.execute(sql, params)

    def executemany(self, sql, seq):
        return self._c.executemany(sql, seq)

    def executescript(self, script):
        return self._c.executescript(script)

    def cursor(self):
        return self

    def commit(self):
        self._c.commit()

    def rollback(self):
        self._c.rollback()

    def close(self):
        self._c.close()

    def sync(self):
        pass


def describe():
    return f"Turso ({TURSO_URL})" if USE_TURSO else f"SQLite local ({DATABASE})"
