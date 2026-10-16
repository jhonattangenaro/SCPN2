# database.py - Capa de conexión: SQLite local o Turso (por HTTP) según variables de entorno.
#
#  - Sin TURSO_DATABASE_URL  -> usa sqlite3 normal (igual que antes).
#  - Con TURSO_DATABASE_URL + TURSO_AUTH_TOKEN -> usa la API HTTP de Turso (/v2/pipeline).
#    No necesita librerías nativas ni réplica local: los datos viven en Turso y persisten.
import base64
import json
import os
import sqlite3
import time

from config import DATABASE

TURSO_URL = os.environ.get('TURSO_DATABASE_URL', '').strip()
TURSO_TOKEN = os.environ.get('TURSO_AUTH_TOKEN', '').strip()
USE_TURSO = bool(TURSO_URL and TURSO_TOKEN)


def _http_base():
    u = TURSO_URL.rstrip('/')
    for old, new in (('libsql://', 'https://'), ('wss://', 'https://'), ('ws://', 'http://')):
        if u.startswith(old):
            u = new + u[len(old):]
    return u


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


class Cursor:
    def __init__(self, names, rows, rowcount=-1, lastrowid=None):
        self._names = names
        self._rows = rows
        self._i = 0
        self.rowcount = rowcount
        self.lastrowid = lastrowid

    def fetchone(self):
        if self._i >= len(self._rows):
            return None
        r = self._rows[self._i]
        self._i += 1
        return Row(r, self._names)

    def fetchall(self):
        out = [Row(r, self._names) for r in self._rows[self._i:]]
        self._i = len(self._rows)
        return out

    def __iter__(self):
        return iter(self.fetchall())


# ───────────────────────── Turso por HTTP ─────────────────────────
_session = None


def _get_session():
    global _session
    if _session is None:
        import requests
        _session = requests.Session()
    return _session


def _enc(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, (bytes, bytearray)):
        return {"type": "blob", "base64": base64.b64encode(bytes(v)).decode()}
    return {"type": "text", "value": str(v)}


def _dec(v):
    t = v.get("type")
    if t == "null":
        return None
    if t == "integer":
        return int(v["value"])
    if t == "float":
        return float(v["value"])
    if t == "blob":
        return base64.b64decode(v.get("base64", ""))
    return v.get("value")


def _is_dml(sql):
    w = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ''
    return w in ('INSERT', 'UPDATE', 'DELETE', 'REPLACE')


def _err(e):
    msg = e.get('message', str(e)) if isinstance(e, dict) else str(e)
    code = (e.get('code', '') if isinstance(e, dict) else '') or ''
    if 'CONSTRAINT' in code.upper() or 'constraint failed' in msg.lower():
        return sqlite3.IntegrityError(msg)
    return sqlite3.OperationalError(msg)


class HttpConnection:
    """Una 'conexión' = un stream de Turso (baton). Imita sqlite3: transacción implícita en DML."""
    BATCH = 20

    def __init__(self):
        self._base = _http_base()
        self._baton = None
        self._in_tx = False

    # --- transporte ---
    def _post(self, reqs):
        sess = _get_session()
        body = {"baton": self._baton, "requests": reqs}
        headers = {"Authorization": f"Bearer {TURSO_TOKEN}", "Content-Type": "application/json"}
        intentos = 4 if self._baton is None else 1
        ultimo = None
        for n in range(intentos):
            try:
                r = sess.post(self._base + "/v2/pipeline", data=json.dumps(body), headers=headers, timeout=60)
                if r.status_code in (502, 503, 504) and n < intentos - 1:
                    print(f"[TURSO] HTTP {r.status_code}, reintentando… {r.text[:200]}", flush=True)
                    time.sleep(1.5 * (n + 1))
                    continue
                if r.status_code != 200:
                    print(f"[TURSO] HTTP {r.status_code}: {r.text[:300]}", flush=True)
                    raise sqlite3.OperationalError(f"Turso respondió HTTP {r.status_code}: {r.text[:200]}")
                data = r.json()
                self._baton = data.get("baton")
                if data.get("base_url"):
                    self._base = data["base_url"].rstrip('/')
                return data.get("results", [])
            except sqlite3.OperationalError:
                raise
            except Exception as e:                       # red / DNS / timeout
                ultimo = e
                print(f"[TURSO] error de red: {e}", flush=True)
                if n < intentos - 1:
                    time.sleep(1.5 * (n + 1))
        raise sqlite3.OperationalError(f"No se pudo conectar con Turso: {ultimo}")

    @staticmethod
    def _stmt(sql, params):
        return {"type": "execute", "stmt": {"sql": sql, "args": [_enc(p) for p in params], "want_rows": True}}

    def _run(self, stmts):
        """Ejecuta [(sql, params)...] en un solo viaje. Devuelve lista de Cursor."""
        reqs, begin = [], False
        if not self._in_tx and any(_is_dml(s) for s, _ in stmts):
            reqs.append(self._stmt("BEGIN", ()))
            begin = True
        reqs += [self._stmt(s, p) for s, p in stmts]
        results = self._post(reqs)
        if begin:
            self._in_tx = True
        out = []
        for i, res in enumerate(results[1:] if begin else results):
            if res.get("type") == "error":
                raise _err(res.get("error"))
            r = res["response"]["result"]
            names = [c.get("name") for c in r.get("cols", [])]
            rows = [[_dec(v) for v in row] for row in r.get("rows", [])]
            last = r.get("last_insert_rowid")
            out.append(Cursor(names, rows, r.get("affected_row_count", -1), int(last) if last is not None else None))
        if begin and results and results[0].get("type") == "error":
            raise _err(results[0].get("error"))
        return out

    # --- API tipo sqlite3 ---
    def execute(self, sql, params=()):
        return self._run([(sql, tuple(params))])[0]

    def executemany(self, sql, seq):
        self.batch([(sql, tuple(p)) for p in seq])

    def batch(self, stmts):
        stmts = [(s, tuple(p)) for s, p in stmts]
        for i in range(0, len(stmts), self.BATCH):
            self._run(stmts[i:i + self.BATCH])

    def executescript(self, script):
        parts = [p.strip() for p in script.split(';') if p.strip()]
        for i in range(0, len(parts), self.BATCH):
            self._run([(p, ()) for p in parts[i:i + self.BATCH]])

    def cursor(self):
        return self

    def commit(self):
        if self._in_tx:
            self._post([{"type": "execute", "stmt": {"sql": "COMMIT"}}])
            self._in_tx = False

    def rollback(self):
        if self._in_tx:
            try:
                self._post([{"type": "execute", "stmt": {"sql": "ROLLBACK"}}])
            except Exception:
                pass
            self._in_tx = False

    def close(self):
        if self._baton:
            try:
                self._post([{"type": "close"}])
            except Exception:
                pass
        self._baton = None
        self._in_tx = False

    def sync(self):
        pass


# ───────────────────────── SQLite local ─────────────────────────
class _SqliteConn:
    def __init__(self, c):
        self._c = c

    def execute(self, sql, params=()):
        return self._c.execute(sql, params)

    def executemany(self, sql, seq):
        return self._c.executemany(sql, seq)

    def batch(self, stmts):
        for s, p in stmts:
            self._c.execute(s, p)

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


def connect(timeout=30):
    if USE_TURSO:
        return HttpConnection()
    c = sqlite3.connect(DATABASE, timeout=timeout)
    c.row_factory = sqlite3.Row
    return _SqliteConn(c)


def describe():
    return f"Turso ({TURSO_URL})" if USE_TURSO else f"SQLite local ({DATABASE})"
