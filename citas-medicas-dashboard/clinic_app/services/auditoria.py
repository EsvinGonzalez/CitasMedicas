"""Registro de auditoría inmutable con encadenamiento SHA-256."""

import hashlib
from datetime import datetime
from functools import wraps

from flask import request, session

from clinic_app.infrastructure.database import get_cursor


def _ultimo_hash():
    with get_cursor() as cur:
        limite = "SELECT TOP 1 hash FROM auditoria ORDER BY id DESC" if cur._is_sql_server else "SELECT hash FROM auditoria ORDER BY id DESC LIMIT 1"
        row = cur.execute(limite).fetchone()
    return row["hash"] if row else "genesis"


def registrar_auditoria(accion, modulo, recurso=None, recurso_id=None, detalle=None):
    prev = _ultimo_hash()
    creado = datetime.now().isoformat()
    usuario_id = session.get("user_id")
    email = session.get("email", "")
    ip = request.remote_addr if request else ""
    payload = "|".join([
        creado,
        str(usuario_id or ""),
        email,
        accion,
        modulo,
        str(recurso or ""),
        str(recurso_id or ""),
        str(detalle or ""),
        ip,
        prev,
    ])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    with get_cursor(commit=True) as cur:
        cur.execute(
            """INSERT INTO auditoria
               (usuario_id, usuario_email, accion, modulo, recurso, recurso_id,
                detalle, ip, creado_en, hash_prev, hash)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (usuario_id, email, accion, modulo, recurso, str(recurso_id) if recurso_id is not None else None,
             detalle, ip, creado, prev, digest),
        )


def auditar(accion, modulo, recurso=None):
    def decorador(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            resultado = f(*args, **kwargs)
            recurso_id = kwargs.get("cita_id") or kwargs.get("paciente_id") or kwargs.get("expediente_id")
            registrar_auditoria(accion, modulo, recurso, recurso_id)
            return resultado
        return wrapper
    return decorador
