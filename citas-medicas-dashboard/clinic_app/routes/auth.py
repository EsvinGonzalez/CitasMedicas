"""
auth.py
Autenticación, 2FA (TOTP / correo / SMS simulado) y RBAC.
"""

import random
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from clinic_app.infrastructure.database import get_cursor
from clinic_app.services.totp import generar_secreto, uri_otpauth, verify_totp

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

ROLES = ("admin", "medico", "recepcionista", "paciente", "auditor")

PERMISOS = {
    "pacientes.crear": ("admin", "recepcionista"),
    "pacientes.ver": ("admin", "recepcionista", "medico", "auditor", "paciente"),
    "medicos.crear": ("admin",),
    "citas.crear": ("admin", "recepcionista", "paciente"),
    "citas.editar": ("admin", "recepcionista"),
    "citas.eliminar": ("admin",),
    "expediente.ver": ("admin", "medico", "recepcionista", "auditor", "paciente"),
    "expediente.editar": ("admin", "medico"),
    "recetas.crear": ("admin", "medico"),
    "facturacion.crear": ("admin", "recepcionista"),
    "auditoria.ver": ("admin", "auditor"),
    "reportes.ver": ("admin", "auditor", "recepcionista", "medico"),
}


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            if request.accept_mimetypes.accept_html and not request.path.startswith("/api"):
                return redirect(url_for("login"))
            return jsonify({"error": "Debes iniciar sesión para continuar"}), 401
        return f(*args, **kwargs)
    return wrapper


def roles_required(*roles_permitidos):
    def decorador(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                if request.accept_mimetypes.accept_html and not request.path.startswith("/api"):
                    return redirect(url_for("login"))
                return jsonify({"error": "Debes iniciar sesión para continuar"}), 401
            if session.get("rol") not in roles_permitidos:
                if request.accept_mimetypes.accept_html and not request.path.startswith("/api"):
                    return redirect(url_for("index"))
                return jsonify({"error": "No tienes permiso para realizar esta acción"}), 403
            return f(*args, **kwargs)
        return wrapper
    return decorador


def _iniciar_sesion(user):
    session.clear()
    session["user_id"] = user["id"]
    session["nombre"] = user["nombre"]
    session["email"] = user["email"]
    session["rol"] = user["rol"]


def _emitir_codigo_otp(usuario_id, canal):
    codigo = f"{random.randint(0, 999999):06d}"
    expira = (datetime.now() + timedelta(minutes=10)).isoformat()
    with get_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO codigos_2fa (usuario_id, codigo, canal, expira_en, usado) VALUES (?,?,?,?,0)",
            (usuario_id, codigo, canal, expira),
        )
        user = cur.execute("SELECT email FROM usuarios WHERE id=?", (usuario_id,)).fetchone()
        cur.execute(
            """INSERT INTO notificaciones
               (paciente_id, cita_id, canal, tipo, asunto, mensaje, estado, creado_en)
               VALUES (NULL, NULL, ?, '2fa', 'Código de verificación', ?, 'enviada', ?)""",
            (canal, f"Código para {user['email'] if user else usuario_id}: {codigo}", datetime.now().isoformat()),
        )
    return codigo


def _consumir_codigo_otp(usuario_id, token):
    ahora = datetime.now().isoformat()
    with get_cursor(commit=True) as cur:
        row = cur.execute(
            """SELECT * FROM codigos_2fa
               WHERE usuario_id=? AND codigo=? AND usado=0 AND expira_en>=?
               ORDER BY id DESC LIMIT 1""",
            (usuario_id, token, ahora),
        ).fetchone()
        if not row:
            return False
        cur.execute("UPDATE codigos_2fa SET usado=1 WHERE id=?", (row["id"],))
    return True


@auth_bp.route("/login", methods=["POST"])
def api_login():
    payload = request.get_json(silent=True) or request.form
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))

    user = autenticar_usuario(email, password)
    if user is None:
        return jsonify({"error": "Usuario o contraseña incorrectos"}), 401

    if user.get("dosfa_activo"):
        metodo = user.get("metodo_2fa") or "totp"
        session.clear()
        session["pending_user_id"] = user["id"]
        session["pending_2fa_metodo"] = metodo
        if user["rol"] == "paciente":
            session["pending_portal_login"] = True
        if metodo in ("email", "sms"):
            _emitir_codigo_otp(user["id"], metodo)
        return jsonify({
            "success": True,
            "requiere_2fa": True,
            "metodo": metodo,
            "portal": user["rol"] == "paciente",
        })

    _iniciar_sesion(user)
    destino = "portal_citas.agendar" if user["rol"] == "paciente" else "index"
    return jsonify({"success": True, "redirect": url_for(destino)})


@auth_bp.route("/verificar-2fa", methods=["POST"])
def api_verificar_2fa():
    payload = request.get_json(silent=True) or request.form
    token = str(payload.get("token", "") or "").strip()
    user_id = session.get("pending_user_id")
    metodo = session.get("pending_2fa_metodo", "totp")

    if not user_id:
        return jsonify({"error": "Sesión de verificación no iniciada"}), 401

    user = obtener_usuario_por_id(user_id)
    if not user:
        return jsonify({"error": "Usuario inválido"}), 401

    ok = False
    if metodo == "totp" and user.get("secreto_2fa"):
        ok = verify_totp(user["secreto_2fa"], token)
    else:
        ok = _consumir_codigo_otp(user_id, token)

    if not ok:
        return jsonify({"error": "Código de verificación inválido"}), 401

    _iniciar_sesion(user)
    destino = "portal_citas.agendar" if user["rol"] == "paciente" else "index"
    return jsonify({"success": True, "redirect": url_for(destino)})


@auth_bp.route("/registro", methods=["POST"])
def api_registro():
    payload = request.get_json(silent=True) or request.form
    nombre = str(payload.get("nombre", "")).strip()
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    rol = "paciente"

    if not nombre or not email or len(password) < 8:
        return jsonify({"error": "Nombre, correo y contraseña válida son obligatorios"}), 400

    if "@" not in email:
        return jsonify({"error": "Ingresa un correo electrónico válido"}), 400

    with get_cursor(commit=True) as cur:
        existe = cur.execute("SELECT id FROM usuarios WHERE email = ?", (email,)).fetchone()
        if existe:
            return jsonify({"error": "El correo electrónico ya está registrado"}), 409

        limite = "TOP 1 " if cur._is_sql_server else ""
        sufijo_limite = "" if cur._is_sql_server else " LIMIT 1"
        paciente = cur.execute(
            f"SELECT {limite}id FROM pacientes WHERE LOWER(email)=? ORDER BY id{sufijo_limite}",
            (email,),
        ).fetchone()
        if paciente:
            paciente_id = paciente["id"]
        else:
            cur.execute(
                """INSERT INTO pacientes (nombre, email, fecha_registro)
                   VALUES (?,?,?)""",
                (nombre, email, datetime.now().date().isoformat()),
            )
            paciente_id = cur.lastrowid

        cur.execute(
            """INSERT INTO usuarios (
                nombre, email, password_hash, rol, secreto_2fa, dosfa_activo, metodo_2fa,
                medico_id, paciente_id, activo, creado_en
            ) VALUES (?,?,?,?,?,?,?,?,?,1,?)""",
            (
                nombre,
                email,
                generate_password_hash(password),
                rol,
                None,
                0,
                "totp",
                None,
                paciente_id,
                datetime.now().date().isoformat(),
            ),
        )
    return jsonify({
        "success": True,
        "mensaje": "Cuenta creada correctamente. Ya puedes iniciar sesión para agendar.",
    }), 201


@auth_bp.route("/2fa/iniciar", methods=["POST"])
@login_required
def iniciar_totp():
    secreto = generar_secreto()
    session["pending_totp_secret"] = secreto
    email = session.get("email", "usuario")
    return jsonify({"secreto": secreto, "otpauth": uri_otpauth(secreto, email)})


@auth_bp.route("/2fa/activar", methods=["POST"])
@login_required
def activar_2fa():
    data = request.get_json(force=True) or {}
    metodo = data.get("metodo", "totp")
    token = str(data.get("token", "")).strip()
    user_id = session["user_id"]

    if metodo == "totp":
        secreto = session.get("pending_totp_secret")
        if not secreto or not verify_totp(secreto, token):
            return jsonify({"error": "Código TOTP inválido"}), 400
        with get_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE usuarios SET secreto_2fa=?, dosfa_activo=1, metodo_2fa='totp' WHERE id=?",
                (secreto, user_id),
            )
        session.pop("pending_totp_secret", None)
        return jsonify({"mensaje": "2FA TOTP activado"})

    if metodo in ("email", "sms"):
        _emitir_codigo_otp(user_id, metodo)
        session["pending_2fa_metodo_enroll"] = metodo
        return jsonify({"mensaje": f"Código enviado por {metodo} (revisa notificaciones en demo)"})

    return jsonify({"error": "Método no soportado"}), 400


@auth_bp.route("/2fa/confirmar-canal", methods=["POST"])
@login_required
def confirmar_canal_2fa():
    data = request.get_json(force=True) or {}
    token = str(data.get("token", "")).strip()
    metodo = session.get("pending_2fa_metodo_enroll", "email")
    if not _consumir_codigo_otp(session["user_id"], token):
        return jsonify({"error": "Código inválido"}), 400
    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE usuarios SET dosfa_activo=1, metodo_2fa=? WHERE id=?",
            (metodo, session["user_id"]),
        )
    return jsonify({"mensaje": f"2FA por {metodo} activado"})


@auth_bp.route("/permisos", methods=["GET"])
@login_required
def api_permisos():
    rol = session.get("rol")
    return jsonify({
        "rol": rol,
        "permisos": {k: rol in v for k, v in PERMISOS.items()},
        "roles": list(ROLES),
    })


@auth_bp.route("/sesion", methods=["GET"])
def api_sesion():
    if "user_id" not in session:
        return jsonify({"autenticado": False})
    return jsonify({
        "autenticado": True,
        "id": session["user_id"],
        "nombre": session.get("nombre", ""),
        "email": session.get("email", ""),
        "rol": session.get("rol", ""),
    })


@auth_bp.route("/logout", methods=["POST"])
@login_required
def api_logout():
    session.clear()
    return jsonify({"success": True})


def crear_usuario(
    nombre: str,
    email: str,
    password: str,
    rol: str = "recepcionista",
    secreto_2fa: str | None = None,
    dosfa_activo: int = 0,
    medico_id: int | None = None,
    paciente_id: int | None = None,
    metodo_2fa: str = "totp",
):
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO usuarios (
                nombre, email, password_hash, rol, secreto_2fa, dosfa_activo, metodo_2fa,
                medico_id, paciente_id, activo, creado_en
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                nombre.strip(),
                email.strip().lower(),
                generate_password_hash(password),
                rol,
                secreto_2fa,
                int(dosfa_activo),
                metodo_2fa,
                medico_id,
                paciente_id,
                datetime.now().strftime("%Y-%m-%d"),
            ),
        )
        return cur.lastrowid


def autenticar_usuario(email: str, password: str):
    email = (email or "").strip().lower()
    if not email or not password:
        return None

    with get_cursor() as cur:
        row = cur.execute(
            "SELECT * FROM usuarios WHERE email = ? AND activo = 1",
            (email,),
        ).fetchone()

    if not row:
        return None
    if not check_password_hash(row["password_hash"], password):
        return None
    return dict(row)


def obtener_usuario_por_id(user_id: int):
    with get_cursor() as cur:
        row = cur.execute(
            "SELECT * FROM usuarios WHERE id = ? AND activo = 1",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None
