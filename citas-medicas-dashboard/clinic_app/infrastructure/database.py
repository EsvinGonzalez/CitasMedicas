"""Capa de acceso a datos para SQL Server, PostgreSQL y SQLite."""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg2
import pyodbc
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

load_dotenv()

DB_URL = os.environ.get("DIRECT_URL") or os.environ.get("DATABASE_URL")
DB_PATH = str(Path(__file__).resolve().parents[2] / "clinica.db")


def normalize_dsn(dsn):
    if not dsn:
        return dsn
    parts = urlsplit(dsn)
    qs = parse_qsl(parts.query, keep_blank_values=True)
    qs = [(k, v) for k, v in qs if k.lower() != "pgbouncer"]
    clean_query = urlencode(qs, doseq=True)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, clean_query, parts.fragment))


class RowAdapter(dict):
    """Fila compatible con sqlite3.Row: soporta claves y acceso por índice entero."""

    def __init__(self, description, record):
        self._columns = [d[0] for d in (description or [])]
        self._record = tuple(record)
        super().__init__(dict(zip(self._columns, self._record)))

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._record[key]
        return dict.__getitem__(self, key)

    def __iter__(self):
        return iter(self._columns)


class CursorAdapter:
    """Adapta SQL con marcadores ? a PostgreSQL y normaliza las filas devueltas."""

    def __init__(self, cursor):
        self._cursor = cursor
        self._last_insert_id = None
        conn = getattr(cursor, "connection", None)
        self._is_postgres = conn is not None and "psycopg2" in str(type(conn)).lower()
        self._is_sql_server = conn is not None and "pyodbc" in str(type(conn)).lower()

    @property
    def lastrowid(self):
        if self._last_insert_id is not None:
            return self._last_insert_id
        try:
            return getattr(self._cursor, 'lastrowid', None)
        except Exception:
            return None

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    def lock_appointment_slots(self, paciente_id, medico_id, fecha, hora):
        if self._is_sql_server:
            self.execute(
                """SELECT TOP 1 id FROM citas WITH (UPDLOCK, HOLDLOCK)
                   WHERE medico_id=? AND fecha=? AND hora=?
                   AND estado IN ('confirmada','completada')""",
                (medico_id, fecha, hora),
            )
            self.execute(
                """SELECT TOP 1 id FROM citas WITH (UPDLOCK, HOLDLOCK)
                   WHERE paciente_id=? AND fecha=? AND hora=?
                   AND estado IN ('confirmada','completada')""",
                (paciente_id, fecha, hora),
            )
        elif self._is_postgres:
            llaves = sorted((
                f"cita:medico:{medico_id}:{fecha}:{hora}",
                f"cita:paciente:{paciente_id}:{fecha}:{hora}",
            ))
            for llave in llaves:
                self.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (llave,)).fetchone()
        elif isinstance(self._cursor.connection, sqlite3.Connection):
            self._cursor.execute("BEGIN IMMEDIATE")

    def execute(self, sql, params=None):
        sql_native = sql
        if self._is_postgres:
            sql_native = sql.replace('?', '%s')
            if 'INSERT OR IGNORE' in sql_native.upper():
                sql_native = sql_native.replace('INSERT OR IGNORE INTO', 'INSERT INTO')
                sql_native = sql_native + ' ON CONFLICT DO NOTHING'

        is_insert = sql_native.lstrip().upper().startswith('INSERT INTO')
        if self._is_postgres and is_insert and 'RETURNING' not in sql_native.upper():
            sql_native = sql_native + ' RETURNING id'

        self._last_insert_id = None
        try:
            if params is None:
                self._cursor.execute(sql_native)
            else:
                self._cursor.execute(sql_native, params)
        except Exception:
            raise

        if is_insert and self._is_postgres:
            try:
                row = self._cursor.fetchone()
                if row:
                    self._last_insert_id = row[0]
            except Exception:
                self._last_insert_id = getattr(self._cursor, 'lastrowid', None)
        elif (
            is_insert
            and self._is_sql_server
            and "OUTPUT INSERTED" not in sql_native.upper()
        ):
            try:
                self._cursor.execute("SELECT CAST(SCOPE_IDENTITY() AS int)")
                row = self._cursor.fetchone()
                if row:
                    self._last_insert_id = row[0]
            except Exception:
                self._last_insert_id = getattr(self._cursor, 'lastrowid', None)
        elif is_insert and not self._is_postgres:
            self._last_insert_id = getattr(self._cursor, 'lastrowid', None)

        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        return RowAdapter(self._cursor.description, row)

    def fetchall(self):
        rows = self._cursor.fetchall()
        return [RowAdapter(self._cursor.description, row) for row in rows]

    def fetchmany(self, size=None):
        rows = self._cursor.fetchmany(size)
        return [RowAdapter(self._cursor.description, row) for row in rows]


def get_connection():
    sql_server_connection = os.environ.get(
        "SQLSERVER_CONNECTION_STRING",
        "DRIVER={ODBC Driver 17 for SQL Server};SERVER=(local);DATABASE=sistema_medico;Trusted_Connection=yes;TrustServerCertificate=yes;",
    )
    try:
        return pyodbc.connect(sql_server_connection)
    except Exception as exc:
        print(f"[WARN] SQL Server local no disponible, intentando PostgreSQL: {exc}")

    if DB_URL:
        dsn = normalize_dsn(DB_URL)
        try:
            conn = psycopg2.connect(dsn, sslmode='require')
            return conn
        except Exception as exc:
            print(f"[WARN] PostgreSQL no disponible, usando SQLite local: {exc}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_cursor(commit=False):
    conn = get_connection()
    cur = CursorAdapter(conn.cursor())
    try:
        yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS especialidades (
    id SERIAL PRIMARY KEY,
    nombre TEXT NOT NULL UNIQUE,
    descripcion TEXT,
    color TEXT NOT NULL,
    duracion_min INTEGER NOT NULL DEFAULT 30,
    tarifa_base REAL NOT NULL DEFAULT 25000
);

CREATE TABLE IF NOT EXISTS medicos (
    id SERIAL PRIMARY KEY,
    nombre TEXT NOT NULL,
    cedula TEXT NOT NULL UNIQUE,
    colegiado TEXT,
    horario TEXT,
    sucursal TEXT,
    especialidad_id INTEGER NOT NULL REFERENCES especialidades(id),
    activo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS pacientes (
    id SERIAL PRIMARY KEY,
    nombre TEXT NOT NULL,
    dpi TEXT,
    email TEXT,
    telefono TEXT,
    fecha_nacimiento TEXT,
    sexo TEXT,
    fecha_registro TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS seguros (
    id SERIAL PRIMARY KEY,
    paciente_id INTEGER NOT NULL REFERENCES pacientes(id),
    aseguradora TEXT NOT NULL,
    poliza TEXT NOT NULL,
    copago_pct REAL NOT NULL DEFAULT 20,
    activo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS citas (
    id SERIAL PRIMARY KEY,
    paciente_id INTEGER NOT NULL REFERENCES pacientes(id),
    medico_id INTEGER NOT NULL REFERENCES medicos(id),
    especialidad_id INTEGER NOT NULL REFERENCES especialidades(id),
    fecha TEXT NOT NULL,
    hora TEXT NOT NULL,
    estado TEXT NOT NULL CHECK(estado IN ('confirmada','completada','cancelada','no_asistio')),
    modalidad TEXT NOT NULL DEFAULT 'presencial' CHECK(modalidad IN ('presencial','telemedicina')),
    motivo TEXT,
    riesgo_noshow REAL,
    creado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS facturas (
    id SERIAL PRIMARY KEY,
    cita_id INTEGER NOT NULL REFERENCES citas(id),
    servicio TEXT NOT NULL DEFAULT 'Consulta',
    monto REAL NOT NULL,
    impuestos REAL NOT NULL DEFAULT 0,
    descuentos REAL NOT NULL DEFAULT 0,
    datos_fiscales TEXT,
    copago REAL NOT NULL DEFAULT 0,
    metodo_pago TEXT NOT NULL,
    pasarela TEXT,
    referencia_pago TEXT,
    fecha_pago TEXT,
    estado TEXT NOT NULL DEFAULT 'pendiente'
);

CREATE TABLE IF NOT EXISTS pagos (
    id SERIAL PRIMARY KEY,
    factura_id INTEGER NOT NULL REFERENCES facturas(id),
    metodo_pago TEXT NOT NULL DEFAULT 'tarjeta' CHECK(metodo_pago IN ('efectivo','tarjeta','transferencia')),
    monto REAL NOT NULL,
    moneda TEXT NOT NULL DEFAULT 'Q',
    pasarela TEXT NOT NULL DEFAULT 'simulada',
    referencia TEXT,
    estado TEXT NOT NULL,
    fecha_pago TEXT NOT NULL,
    creado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usuarios (
    id SERIAL PRIMARY KEY,
    nombre TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    rol TEXT NOT NULL CHECK(rol IN ('admin','medico','recepcionista','paciente','auditor')),
    secreto_2fa TEXT,
    dosfa_activo INTEGER NOT NULL DEFAULT 0,
    metodo_2fa TEXT NOT NULL DEFAULT 'totp',
    medico_id INTEGER REFERENCES medicos(id),
    paciente_id INTEGER REFERENCES pacientes(id),
    activo INTEGER NOT NULL DEFAULT 1,
    creado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS expedientes (
    id SERIAL PRIMARY KEY,
    paciente_id INTEGER NOT NULL UNIQUE REFERENCES pacientes(id),
    tipo_sangre TEXT,
    alergias TEXT,
    antecedentes TEXT,
    creado_en TEXT NOT NULL,
    actualizado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evoluciones (
    id SERIAL PRIMARY KEY,
    expediente_id INTEGER NOT NULL REFERENCES expedientes(id),
    cita_id INTEGER REFERENCES citas(id),
    medico_id INTEGER REFERENCES medicos(id),
    diagnostico TEXT,
    nota TEXT NOT NULL,
    creado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recetas (
    id SERIAL PRIMARY KEY,
    expediente_id INTEGER NOT NULL REFERENCES expedientes(id),
    cita_id INTEGER REFERENCES citas(id),
    medico_id INTEGER REFERENCES medicos(id),
    medicamentos TEXT NOT NULL,
    dosis TEXT,
    frecuencia TEXT,
    duracion_tratamiento TEXT,
    vigencia TEXT,
    indicaciones TEXT,
    creado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS teleconsultas (
    id SERIAL PRIMARY KEY,
    cita_id INTEGER NOT NULL UNIQUE REFERENCES citas(id),
    tipo_cita TEXT NOT NULL DEFAULT 'virtual',
    sala_codigo TEXT NOT NULL,
    enlace_sala TEXT,
    estado TEXT NOT NULL DEFAULT 'sala_espera',
    asistencia_confirmada INTEGER NOT NULL DEFAULT 0,
    consentimiento_grabacion INTEGER NOT NULL DEFAULT 0,
    grabacion_habilitada INTEGER NOT NULL DEFAULT 0,
    documentos_compartidos TEXT,
    iniciado_en TEXT,
    finalizado_en TEXT
);

CREATE TABLE IF NOT EXISTS notificaciones (
    id SERIAL PRIMARY KEY,
    paciente_id INTEGER REFERENCES pacientes(id),
    cita_id INTEGER REFERENCES citas(id),
    canal TEXT NOT NULL,
    tipo TEXT NOT NULL,
    asunto TEXT NOT NULL,
    mensaje TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'enviada',
    alerta TEXT,
    creado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auditoria (
    id SERIAL PRIMARY KEY,
    usuario_id INTEGER,
    usuario_email TEXT,
    accion TEXT NOT NULL,
    modulo TEXT NOT NULL,
    recurso TEXT,
    recurso_id TEXT,
    detalle TEXT,
    ip TEXT,
    creado_en TEXT NOT NULL,
    hash_prev TEXT,
    hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS codigos_2fa (
    id SERIAL PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    codigo TEXT NOT NULL,
    canal TEXT NOT NULL,
    expira_en TEXT NOT NULL,
    usado INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS predicciones_noshow (
    id SERIAL PRIMARY KEY,
    cita_id INTEGER NOT NULL REFERENCES citas(id),
    probabilidad REAL NOT NULL,
    umbral REAL NOT NULL,
    recordatorio_reforzado INTEGER NOT NULL DEFAULT 0,
    creado_en TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_citas_fecha ON citas(fecha);
CREATE INDEX IF NOT EXISTS idx_citas_medico ON citas(medico_id);
CREATE INDEX IF NOT EXISTS idx_citas_especialidad ON citas(especialidad_id);
CREATE INDEX IF NOT EXISTS idx_facturas_fecha ON facturas(fecha_pago);
CREATE INDEX IF NOT EXISTS idx_usuarios_email ON usuarios(email);
CREATE INDEX IF NOT EXISTS idx_auditoria_recurso ON auditoria(recurso, recurso_id);
CREATE INDEX IF NOT EXISTS idx_notif_paciente ON notificaciones(paciente_id);
"""


def migrate():
    return init_db()


def repair_sqlite_ids(conn):
    """Backfill legacy SERIAL keys and keep them populated on future inserts."""
    cur = conn.cursor()
    tables = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    for (table_name,) in tables:
        safe_name = table_name.replace('"', '""')
        columns = cur.execute(f'PRAGMA table_info("{safe_name}")').fetchall()
        if not any(column[1] == "id" for column in columns):
            continue

        missing_rows = cur.execute(
            f'SELECT rowid FROM "{safe_name}" WHERE id IS NULL ORDER BY rowid'
        ).fetchall()
        max_id = cur.execute(
            f'SELECT COALESCE(MAX(id), 0) FROM "{safe_name}"'
        ).fetchone()[0]
        for (row_id,) in missing_rows:
            candidate_id = row_id
            collision = cur.execute(
                f'SELECT 1 FROM "{safe_name}" WHERE id=?', (candidate_id,)
            ).fetchone()
            if collision:
                max_id += 1
                candidate_id = max_id
            cur.execute(
                f'UPDATE "{safe_name}" SET id=? WHERE rowid=?',
                (candidate_id, row_id),
            )

        trigger_name = f'fill_id_{table_name}'.replace('"', '""')
        cur.execute(
            f'''CREATE TRIGGER IF NOT EXISTS "{trigger_name}"
                AFTER INSERT ON "{safe_name}"
                WHEN NEW.id IS NULL
                BEGIN
                    UPDATE "{safe_name}" SET id=NEW.rowid WHERE rowid=NEW.rowid;
                END'''
        )


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    try:
        table_exists = cur.execute(
            "SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'usuarios'"
        ).fetchone()
    except Exception:
        table_exists = cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='usuarios'"
        ).fetchone()

    if table_exists:
        es_sqlite = isinstance(conn, sqlite3.Connection)
        es_sql_server = "pyodbc" in str(type(conn)).lower()

        if es_sqlite:
            for tabla, columna, tipo in (
                ("pacientes", "dpi", "TEXT"),
                ("citas", "modalidad", "TEXT NOT NULL DEFAULT 'presencial'"),
                ("citas", "riesgo_noshow", "REAL"),
            ):
                columnas = cur.execute(f"PRAGMA table_info({tabla})").fetchall()
                if not any(fila[1] == columna for fila in columnas):
                    cur.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo}")
            for statement in [s.strip() for s in SCHEMA.strip().split(";") if s.strip()]:
                cur.execute(statement)
            repair_sqlite_ids(conn)
        elif es_sql_server:
            columnas = {
                (fila[0], fila[1])
                for fila in cur.execute(
                    """SELECT TABLE_NAME, COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
                       WHERE TABLE_NAME IN ('pacientes', 'citas')"""
                ).fetchall()
            }
            if ("pacientes", "dpi") not in columnas:
                cur.execute("ALTER TABLE pacientes ADD dpi NVARCHAR(20) NULL")
            if ("citas", "modalidad") not in columnas:
                cur.execute(
                    "ALTER TABLE citas ADD modalidad NVARCHAR(30) NOT NULL "
                    "CONSTRAINT DF_citas_modalidad DEFAULT 'presencial'"
                )
            if ("citas", "riesgo_noshow") not in columnas:
                cur.execute("ALTER TABLE citas ADD riesgo_noshow FLOAT NULL")
            cur.execute(
                """IF OBJECT_ID(N'predicciones_noshow', N'U') IS NULL
                   CREATE TABLE predicciones_noshow (
                       id INT IDENTITY(1,1) PRIMARY KEY,
                       cita_id INT NOT NULL REFERENCES citas(id),
                       probabilidad FLOAT NOT NULL,
                       umbral FLOAT NOT NULL,
                       recordatorio_reforzado INT NOT NULL DEFAULT 0,
                       creado_en NVARCHAR(40) NOT NULL
                   )"""
            )
        else:
            cur.execute("ALTER TABLE pacientes ADD COLUMN IF NOT EXISTS dpi TEXT")
            cur.execute(
                "ALTER TABLE citas ADD COLUMN IF NOT EXISTS modalidad "
                "TEXT NOT NULL DEFAULT 'presencial'"
            )
            cur.execute("ALTER TABLE citas ADD COLUMN IF NOT EXISTS riesgo_noshow REAL")
            for statement in [s.strip() for s in SCHEMA.strip().split(";") if s.strip()]:
                cur.execute(statement)

        try:
            row = cur.execute(
                "SELECT id FROM usuarios WHERE email = ?",
                ("admin@clinicasanjose.com",),
            ).fetchone()
            if row is None:
                cur.execute(
                    """
                    INSERT INTO usuarios
                    (nombre, email, password_hash, rol, secreto_2fa, dosfa_activo, metodo_2fa,
                     medico_id, paciente_id, activo, creado_en)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                    """,
                    (
                        "Administrador",
                        "admin@clinicasanjose.com",
                        generate_password_hash("Admin1234"),
                        "admin",
                        None,
                        0,
                        "totp",
                        None,
                        None,
                        "2026-01-01",
                    ),
                )
        except Exception:
            pass
        conn.commit()
        conn.close()
        return

    schema = SCHEMA
    if isinstance(conn, sqlite3.Connection):
        # SQLite treats SERIAL as an ordinary declared type, so a primary key
        # would remain NULL on inserts. Use SQLite's rowid-backed key instead.
        schema = schema.replace(
            "SERIAL PRIMARY KEY",
            "INTEGER PRIMARY KEY AUTOINCREMENT",
        )

    for statement in [s.strip() for s in schema.strip().split(";") if s.strip()]:
        cur.execute(statement)
    conn.commit()

    for nombre, color, dur, tarifa in [
        ("Medicina General", "#0F6B5C", 20, 18000),
        ("Cardiología", "#C9A227", 30, 35000),
        ("Dermatología", "#6B4C9A", 20, 24000),
    ]:
        cur.execute(
            """
            INSERT INTO especialidades (nombre, color, duracion_min, tarifa_base)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (nombre) DO NOTHING
            """,
            (nombre, color, dur, tarifa),
        )

    conn.commit()
    cur.execute("SELECT id FROM especialidades ORDER BY id LIMIT 1")
    default_especialidad = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM medicos")
    medicos_total = cur.fetchone()[0]
    if default_especialidad and medicos_total == 0:
        cur.execute(
            """
            INSERT INTO medicos (nombre, cedula, especialidad_id, activo)
            VALUES (?, ?, ?, 1)
            """,
            ("Dr. José Ruiz", "MED-1001", default_especialidad[0]),
        )
    cur.execute(
        """
        INSERT INTO usuarios
        (nombre, email, password_hash, rol, secreto_2fa, dosfa_activo, metodo_2fa,
         medico_id, paciente_id, activo, creado_en)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        ON CONFLICT (email) DO NOTHING
        """,
        (
            "Administrador",
            "admin@clinicasanjose.com",
            generate_password_hash("Admin1234"),
            "admin",
            None,
            0,
            "totp",
            None,
            None,
            "2026-01-01",
        ),
    )
    conn.commit()
    conn.close()
