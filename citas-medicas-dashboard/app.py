"""
app.py
API REST + servidor del Dashboard — Clínica San José.

    pip install -r requirements.txt
    python seed_data.py
    python app.py
    -> http://localhost:5000
    -> http://localhost:5000/api/docs
"""

import hashlib
import hmac
import json
import os
import re
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import requests
from dotenv import dotenv_values, load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from flask.sessions import SecureCookieSessionInterface

load_dotenv(Path(__file__).with_name(".env.local"))
load_dotenv(Path(__file__).with_name(".env"))

from clinic_app.infrastructure.database import get_cursor, init_db
from clinic_app.routes.auth import autenticar_usuario, auth_bp, login_required, roles_required
from clinic_app.routes.catalogos import catalogos_bp
from clinic_app.routes.citas_crud import citas_bp
from clinic_app.routes.expedientes import expedientes_bp
from clinic_app.routes.facturacion import facturacion_bp
from clinic_app.routes.portal_citas import portal_citas_bp
from clinic_app.routes.recetas import recetas_bp
from clinic_app.routes.reportes import reportes_bp

app = Flask(__name__)

app.secret_key = os.environ.get("SECRET_KEY", "dev-clinica-san-jose-cambiar-en-produccion")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)


class PortalSessionInterface(SecureCookieSessionInterface):
    def get_cookie_name(self, app: Flask) -> str:
        cookie_name = app.config["SESSION_COOKIE_NAME"]
        if (
            request.headers.get("X-Patient-Portal") == "1"
            or request.path in {"/agendar-cita", "/logout-paciente"}
        ):
            return f"{cookie_name}_portal"
        return cookie_name

    def save_session(self, app: Flask, session, response) -> None:
        if session.get("rol") == "paciente" or session.get("pending_portal_login"):
            request.environ["HTTP_X_PATIENT_PORTAL"] = "1"
        super().save_session(app, session, response)


app.session_interface = PortalSessionInterface()

app.register_blueprint(auth_bp)
app.register_blueprint(catalogos_bp)
app.register_blueprint(citas_bp)
app.register_blueprint(expedientes_bp)
app.register_blueprint(recetas_bp)
app.register_blueprint(facturacion_bp)
app.register_blueprint(portal_citas_bp)
app.register_blueprint(reportes_bp)

SECCIONES = {
    "pacientes", "medicos", "citas", "facturacion", "usuario",
    "expedientes", "historial", "especialidades", "recetas",
    "pagos", "reportes", "auditoria", "seguridad", "notificaciones",
}

DIDIT_WORKFLOW_ID_DEFAULT = "f40132be-a2ec-49be-ad49-310ece971a96"
DIDIT_LOCAL_CONFIG = dotenv_values(Path(__file__).with_name(".env.local"))
DIDIT_API_KEY = (
    DIDIT_LOCAL_CONFIG.get("DIDIT_API_KEY")
    or os.environ.get("DIDIT_API_KEY")
    or ""
).strip()
DIDIT_WORKFLOW_ID = (
    DIDIT_LOCAL_CONFIG.get("DIDIT_WORKFLOW_ID")
    or os.environ.get("DIDIT_WORKFLOW_ID")
    or DIDIT_WORKFLOW_ID_DEFAULT
).strip()
DIDIT_VERIFICATION_URL = (
    DIDIT_LOCAL_CONFIG.get("DIDIT_VERIFICATION_URL")
    or os.environ.get("DIDIT_VERIFICATION_URL")
    or ""
).strip()
DIDIT_WEBHOOK_SECRET = (
    DIDIT_LOCAL_CONFIG.get("DIDIT_WEBHOOK_SECRET")
    or os.environ.get("DIDIT_WEBHOOK_SECRET")
    or ""
).strip()


def rows_to_dicts(rows):
    return [dict(r) for r in rows]


def rango_fechas(dias: int):
    hasta = datetime.now().date()
    desde = hasta - timedelta(days=dias)
    return desde.isoformat(), hasta.isoformat()


def inicio_periodo_mensual(meses: int):
    meses = max(1, min(int(meses), 120))
    hoy = datetime.now().date()
    indice_mes = hoy.year * 12 + hoy.month - 1 - (meses - 1)
    anio, mes = divmod(indice_mes, 12)
    return f"{anio:04d}-{mes + 1:02d}-01"


def didit_configuracion():
    api_key = DIDIT_API_KEY
    workflow_id = DIDIT_WORKFLOW_ID
    if workflow_id.startswith(("http://", "https://")):
        workflow_ids = re.findall(
            r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}",
            workflow_id,
        )
        workflow_id = workflow_ids[-1] if workflow_ids else ""

    try:
        workflow_id = str(uuid.UUID(workflow_id))
    except ValueError:
        return None, None, (jsonify({
            "error": "DIDIT_WORKFLOW_ID debe ser el UUID del workflow, no un enlace de la consola."
        }), 503)

    if not api_key:
        return None, None, (jsonify({
            "error": "Falta DIDIT_API_KEY. El enlace verify.didit.me que compartiste no es una clave API. "
                     "Copia una API key secreta desde Didit Business > Developers > API keys "
                     "y guárdala en .env.local; no la pongas en el código ni en el navegador."
        }), 503)
    if api_key.startswith(("http://", "https://")):
        return None, None, (jsonify({
            "error": "DIDIT_API_KEY contiene un enlace, no una clave API. Obtén la clave secreta "
                     "en Didit Business > Developers > API keys y guárdala en .env.local."
        }), 503)
    return api_key, workflow_id, None


def huella_dpi(dpi):
    dpi_normalizado = re.sub(r"[^A-Za-z0-9]", "", dpi).upper()
    return hmac.new(
        str(app.secret_key).encode("utf-8"),
        dpi_normalizado.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


@app.route("/webhook/didit", methods=["POST"])
def webhook_didit():
    if not DIDIT_WEBHOOK_SECRET:
        app.logger.error("Falta DIDIT_WEBHOOK_SECRET para autenticar los webhooks de Didit")
        return jsonify({"error": "El webhook de Didit no está configurado."}), 503

    raw_body = request.get_data(cache=True)
    timestamp = request.headers.get("X-Timestamp", "")
    firma_v2 = request.headers.get("X-Signature-V2", "")
    firma_raw = request.headers.get("X-Signature", "")

    try:
        timestamp_unix = int(timestamp)
    except ValueError:
        return jsonify({"error": "La marca de tiempo del webhook no es válida."}), 401
    if abs(time.time() - timestamp_unix) > 300:
        return jsonify({"error": "El webhook está vencido."}), 401

    firma_valida = False
    data = None
    if firma_v2:
        try:
            data = json.loads(raw_body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return jsonify({"error": "El cuerpo del webhook no contiene JSON válido."}), 400
        if isinstance(data, dict):
            cuerpo_canonico = json.dumps(
                data,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            firma_esperada = hmac.new(
                DIDIT_WEBHOOK_SECRET.encode("utf-8"),
                cuerpo_canonico,
                hashlib.sha256,
            ).hexdigest()
            firma_valida = hmac.compare_digest(firma_esperada, firma_v2)
    elif firma_raw:
        firma_esperada = hmac.new(
            DIDIT_WEBHOOK_SECRET.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        firma_valida = hmac.compare_digest(firma_esperada, firma_raw)

    if not firma_valida:
        return jsonify({"error": "La firma del webhook de Didit no es válida."}), 401

    if data is None:
        try:
            data = json.loads(raw_body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return jsonify({"error": "El cuerpo del webhook no contiene JSON válido."}), 400
    if not isinstance(data, dict):
        return jsonify({"error": "El cuerpo del webhook debe ser un objeto JSON."}), 400

    event_type = data.get("webhook_type") or data.get("event")
    session_id = data.get("session_id")
    status = data.get("status")
    app.logger.info(
        "Notificación de Didit recibida: tipo=%s sesión=%s estado=%s",
        event_type,
        session_id,
        status,
    )

    if isinstance(status, str) and status.casefold() == "approved":
        app.logger.info("La sesión de Didit %s fue aprobada.", session_id)

    return jsonify({"status": "received"}), 200


@app.route("/api/validar-dpi", methods=["POST"])
@roles_required("admin", "recepcionista")
def validar_dpi():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "El cuerpo de la solicitud debe ser un objeto JSON."}), 400
    dpi = str(data.get("dpi") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9]{1,20}", dpi):
        return jsonify({"error": "Ingresa un DPI válido, usando solo letras y números."}), 400

    if DIDIT_VERIFICATION_URL:
        enlace = urlsplit(DIDIT_VERIFICATION_URL)
        if (
            enlace.scheme != "https"
            or enlace.hostname != "verify.didit.me"
            or not re.fullmatch(r"/u/[A-Za-z0-9_-]+/?", enlace.path)
            or enlace.username
            or enlace.password
            or enlace.query
            or enlace.fragment
        ):
            app.logger.error("DIDIT_VERIFICATION_URL no tiene un formato de enlace verificado válido")
            return jsonify({"error": "El enlace fijo de verificación de Didit no es válido."}), 503
        return jsonify({
            "status": "success",
            "url": DIDIT_VERIFICATION_URL,
            "modo": "enlace",
        })

    api_key, workflow_id, error = didit_configuracion()
    if error:
        return error

    try:
        response = requests.post(
            "https://verification.didit.me/v3/session/",
            headers={
                "x-api-key": api_key,
                "Content-Type": "application/json",
            },
            json={"workflow_id": workflow_id},
            timeout=30,
        )
    except requests.RequestException as exc:
        app.logger.exception("No fue posible contactar la API de sesiones de Didit")
        return jsonify({
            "error": f"No fue posible iniciar la verificación con Didit: {exc}"
        }), 500

    try:
        resultado = response.json()
    except ValueError:
        if not response.ok:
            detalle = response.text[:1000]
            print("Respuesta de Didit:", response.status_code, detalle)
            app.logger.error(
                "Didit rechazó la creación de sesión (HTTP %s): %s",
                response.status_code,
                detalle,
            )
            return jsonify({
                "error": f"Didit respondió HTTP {response.status_code}.",
                "detalle": detalle,
            }), 502
        app.logger.error("Didit devolvió una respuesta no válida al crear una sesión")
        return jsonify({"error": "Didit devolvió una respuesta no válida."}), 502

    if not response.ok:
        detalle = resultado
        if isinstance(resultado, dict):
            detalle = resultado.get("detail") or resultado.get("message") or resultado
        detalle_texto = str(detalle)[:1000]
        print("Respuesta de Didit:", response.status_code, detalle_texto)
        app.logger.error(
            "Didit rechazó la creación de sesión (HTTP %s): %s",
            response.status_code,
            detalle_texto,
        )
        if response.status_code == 403:
            mensaje = (
                "Didit rechazó la solicitud con HTTP 403. La clave API no tiene permiso "
                "para crear sesiones en este workflow, pertenece a otra aplicación, o la "
                "aplicación restringe la IP del servidor. Verifica en Didit Business que la "
                "clave activa pertenezca a la misma aplicación del workflow y tenga permiso "
                "write:sessions. El UUID de la URL del panel identifica la clave; no es su secreto."
            )
        else:
            mensaje = f"Didit error {response.status_code}: {detalle_texto}"
        return jsonify({
            "status": "error",
            "message": mensaje,
            "detalle": detalle,
        }), response.status_code

    session_id = resultado.get("session_id") or resultado.get("id")
    url = resultado.get("url") or resultado.get("session_url")
    if not isinstance(session_id, str) or not isinstance(url, str) or not url.startswith("https://"):
        app.logger.error("La respuesta de Didit no incluyó session_id y url")
        return jsonify({"error": "Didit devolvió una sesión incompleta."}), 502

    sesiones_dpi = session.get("didit_dpi_sessions", {})
    if not isinstance(sesiones_dpi, dict):
        sesiones_dpi = {}
    sesiones_dpi[session_id] = huella_dpi(dpi)
    session["didit_dpi_sessions"] = dict(list(sesiones_dpi.items())[-20:])
    resultado_seguro = {
        "session_id": session_id,
        "url": url,
    }
    print("Respuesta de Didit:", response.status_code, {
        "session_id": session_id,
        "status": resultado.get("status"),
    })
    return jsonify({"status": "success", **resultado_seguro}), response.status_code


@app.route("/api/obtener-datos-dpi/<string:session_id>", methods=["GET"])
@roles_required("admin", "recepcionista")
def obtener_datos_dpi(session_id):
    try:
        session_id = str(uuid.UUID(session_id))
    except ValueError:
        return jsonify({"error": "Sesión de verificación no válida."}), 400

    sesiones_dpi = session.get("didit_dpi_sessions", {})
    huella_esperada = sesiones_dpi.get(session_id) if isinstance(sesiones_dpi, dict) else None
    if not huella_esperada:
        return jsonify({"error": "La sesión de verificación no pertenece a esta cuenta."}), 404

    api_key, _, error = didit_configuracion()
    if error:
        return error

    try:
        response = requests.get(
            f"https://verification.didit.me/v3/session/{session_id}/decision/",
            headers={"x-api-key": api_key},
            timeout=20,
        )
    except requests.RequestException:
        app.logger.exception("No fue posible consultar la sesión de Didit")
        return jsonify({"error": "No fue posible consultar la verificación con Didit."}), 502

    if not response.ok:
        app.logger.error("Didit rechazó la consulta de sesión (HTTP %s)", response.status_code)
        return jsonify({"error": "No fue posible recuperar el resultado de la verificación."}), 502

    try:
        resultado = response.json()
    except ValueError:
        app.logger.error("Didit devolvió una respuesta no válida al consultar una sesión")
        return jsonify({"error": "Didit devolvió una respuesta no válida."}), 502

    estado = str(resultado.get("status") or "")
    respuesta = {"status": estado, "aprobado": estado.upper() == "APPROVED"}
    if respuesta["aprobado"]:
        verificaciones = resultado.get("id_verifications") or []
        verificacion = next(
            (
                verificacion
                for verificacion in verificaciones
                if isinstance(verificacion, dict)
                and verificacion.get("full_name")
                and verificacion.get("document_number")
            ),
            None,
        )
        if not verificacion:
            return jsonify({"error": "La verificación fue aprobada, pero Didit no devolvió los datos del DPI."}), 502
        if not hmac.compare_digest(huella_esperada, huella_dpi(verificacion["document_number"])):
            sesiones_dpi.pop(session_id, None)
            session["didit_dpi_sessions"] = sesiones_dpi
            return jsonify({"error": "El número del documento verificado no coincide con el DPI ingresado."}), 409
        respuesta["nombre_completo"] = str(verificacion["full_name"]).strip()
        sesiones_dpi.pop(session_id, None)
        session["didit_dpi_sessions"] = sesiones_dpi
    elif estado.upper() in {"DECLINED", "EXPIRED", "ABANDONED", "KYC EXPIRED"}:
        sesiones_dpi.pop(session_id, None)
        session["didit_dpi_sessions"] = sesiones_dpi
    return jsonify(respuesta)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        payload = request.get_json(silent=True) or request.form
        email = str(payload.get("email", "")).strip().lower()
        password = str(payload.get("password", ""))
        otp_code = str(payload.get("otp", "") or "").strip()

        user = autenticar_usuario(email, password)
        if user is None:
            return jsonify({"error": "Usuario o contraseña incorrectos"}), 401

        if user.get("dosfa_activo") and user.get("secreto_2fa"):
            if not otp_code:
                return jsonify({"error": "Se requiere el código TOTP"}), 401
            from clinic_app.services.totp import verify_totp
            if not verify_totp(user["secreto_2fa"], otp_code):
                return jsonify({"error": "Código TOTP inválido"}), 401

        session.clear()
        session["user_id"] = user["id"]
        session["nombre"] = user["nombre"]
        session["email"] = user["email"]
        session["rol"] = user["rol"]
        destino = "portal_citas.agendar" if user["rol"] == "paciente" else "index"
        return jsonify({"success": True, "redirect": url_for(destino)})

    if session.get("user_id"):
        return redirect(url_for("index"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/logout-paciente")
def logout_paciente():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    return render_template("index.html", user=session.get("nombre", "Usuario"), seccion="dashboard")


@app.route("/api/docs")
def swagger_ui():
    return render_template("swagger.html")


@app.route("/api/openapi.yaml")
def openapi_spec():
    docs = Path(__file__).parent / "docs"
    return send_from_directory(docs, "openapi.yaml", mimetype="text/yaml")


@app.route("/<seccion>")
@login_required
def modulo_view(seccion):
    if seccion not in SECCIONES:
        return redirect(url_for("index"))
    return render_template("modulos.html", seccion=seccion, user=session.get("nombre", "Usuario"))


@app.route("/modulos/<string:seccion>")
@login_required
def modulos(seccion):
    if seccion not in SECCIONES:
        return redirect(url_for("index"))
    return render_template("modulos.html", seccion=seccion, user=session.get("nombre", "Usuario"))


@app.route("/api/usuario")
@login_required
def api_usuario():
    return jsonify({
        "nombre": session.get("nombre", "Usuario"),
        "email": session.get("email", ""),
        "rol": session.get("rol", ""),
        "estado": "Sesión activa",
    })


@app.route("/api/kpis")
@login_required
def api_kpis():
    dias = int(request.args.get("dias", 30))
    desde, hasta = rango_fechas(dias)
    hoy = datetime.now().date().isoformat()

    with get_cursor() as cur:
        citas_hoy = cur.execute("SELECT COUNT(*) FROM citas WHERE fecha = ?", (hoy,)).fetchone()[0]
        total_periodo = cur.execute(
            "SELECT COUNT(*) FROM citas WHERE fecha BETWEEN ? AND ? AND estado != 'confirmada'",
            (desde, hasta),
        ).fetchone()[0]
        no_asistio = cur.execute(
            "SELECT COUNT(*) FROM citas WHERE fecha BETWEEN ? AND ? AND estado = 'no_asistio'",
            (desde, hasta),
        ).fetchone()[0]
        tasa_inasistencia = round((no_asistio / total_periodo) * 100, 1) if total_periodo else 0.0
        ingresos = cur.execute(
            """SELECT COALESCE(SUM(f.monto), 0) FROM facturas f
               JOIN citas c ON c.id = f.cita_id
               WHERE f.fecha_pago BETWEEN ? AND ?""",
            (desde, hasta),
        ).fetchone()[0]
        medicos_activos = cur.execute("SELECT COUNT(*) FROM medicos WHERE activo = 1").fetchone()[0]
        pacientes_totales = cur.execute("SELECT COUNT(*) FROM pacientes").fetchone()[0]
        citas_pendientes = cur.execute(
            "SELECT COUNT(*) FROM citas WHERE estado = 'confirmada' AND fecha >= ?", (hoy,)
        ).fetchone()[0]

    return jsonify({
        "citas_hoy": citas_hoy,
        "tasa_inasistencia": tasa_inasistencia,
        "ingresos_periodo": round(ingresos, 2),
        "medicos_activos": medicos_activos,
        "pacientes_totales": pacientes_totales,
        "citas_pendientes": citas_pendientes,
        "periodo_dias": dias,
    })


@app.route("/api/citas-por-especialidad")
@login_required
def api_citas_por_especialidad():
    dias = int(request.args.get("dias", 30))
    desde, hasta = rango_fechas(dias)
    with get_cursor() as cur:
        rows = cur.execute(
            """SELECT e.nombre, e.color, COUNT(c.id) AS total
               FROM especialidades e
               LEFT JOIN citas c ON c.especialidad_id = e.id AND c.fecha BETWEEN ? AND ?
               GROUP BY e.id, e.nombre, e.color ORDER BY total DESC""",
            (desde, hasta),
        ).fetchall()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/tendencia-citas")
@login_required
def api_tendencia_citas():
    dias = int(request.args.get("dias", 30))
    desde, hasta = rango_fechas(dias)
    with get_cursor() as cur:
        rows = cur.execute(
            """SELECT fecha,
                      SUM(CASE WHEN estado='completada' THEN 1 ELSE 0 END) AS completadas,
                      SUM(CASE WHEN estado='no_asistio' THEN 1 ELSE 0 END) AS no_asistio,
                      SUM(CASE WHEN estado='cancelada' THEN 1 ELSE 0 END) AS canceladas,
                      COUNT(*) AS total
               FROM citas WHERE fecha BETWEEN ? AND ?
               GROUP BY fecha ORDER BY fecha ASC""",
            (desde, hasta),
        ).fetchall()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/ingresos-mensuales")
@login_required
def api_ingresos_mensuales():
    meses = int(request.args.get("meses", 6))
    desde = inicio_periodo_mensual(meses)
    with get_cursor() as cur:
        expresion_mes = (
            "CONVERT(char(7), fecha_pago, 126)" if cur._is_sql_server
            else "SUBSTR(fecha_pago, 1, 7)"
        )
        rows = cur.execute(
            f"""SELECT {expresion_mes} AS mes, SUM(monto) AS total
               FROM facturas WHERE fecha_pago >= ? AND fecha_pago IS NOT NULL
               GROUP BY {expresion_mes} ORDER BY mes ASC""",
            (desde,),
        ).fetchall()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/medicos-mas-solicitados")
@login_required
def api_medicos_mas_solicitados():
    dias = int(request.args.get("dias", 30))
    limite = max(1, min(int(request.args.get("limite", 6)), 100))
    desde, hasta = rango_fechas(dias)
    with get_cursor() as cur:
        paginacion = (
            "OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY"
            if cur._is_sql_server else "LIMIT ?"
        )
        rows = cur.execute(
            f"""SELECT m.nombre AS medico, e.nombre AS especialidad, e.color,
                      COUNT(c.id) AS total_citas,
                      SUM(CASE WHEN c.estado='no_asistio' THEN 1 ELSE 0 END) AS inasistencias
               FROM citas c
               JOIN medicos m ON m.id = c.medico_id
               JOIN especialidades e ON e.id = m.especialidad_id
               WHERE c.fecha BETWEEN ? AND ?
               GROUP BY m.id, m.nombre, e.nombre, e.color
               ORDER BY total_citas DESC {paginacion}""",
            (desde, hasta, limite),
        ).fetchall()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/citas-recientes")
@login_required
def api_citas_recientes():
    limite = max(1, min(int(request.args.get("limite", 12)), 100))
    with get_cursor() as cur:
        paginacion = (
            "OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY"
            if cur._is_sql_server else "LIMIT ?"
        )
        rows = cur.execute(
            f"""SELECT c.id, p.nombre AS paciente, m.nombre AS medico,
                      e.nombre AS especialidad, e.color, c.fecha, c.hora, c.estado, c.motivo
               FROM citas c
               JOIN pacientes p ON p.id = c.paciente_id
               JOIN medicos m ON m.id = c.medico_id
               JOIN especialidades e ON e.id = c.especialidad_id
               ORDER BY c.fecha DESC, c.hora DESC {paginacion}""",
            (limite,),
        ).fetchall()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/tasa-inasistencia-tendencia")
@login_required
def api_tasa_inasistencia_tendencia():
    meses = int(request.args.get("meses", 6))
    desde = inicio_periodo_mensual(meses)
    with get_cursor() as cur:
        expresion_mes = (
            "CONVERT(char(7), fecha, 126)" if cur._is_sql_server
            else "SUBSTR(fecha, 1, 7)"
        )
        rows = cur.execute(
            f"""SELECT {expresion_mes} AS mes,
                      SUM(CASE WHEN estado='no_asistio' THEN 1 ELSE 0 END) AS no_asistio,
                      COUNT(*) AS total
               FROM citas
               WHERE fecha >= ? AND estado != 'confirmada'
               GROUP BY {expresion_mes} ORDER BY mes ASC""",
            (desde,),
        ).fetchall()
    data = []
    for r in rows:
        tasa = round((r["no_asistio"] / r["total"]) * 100, 1) if r["total"] else 0
        data.append({"mes": r["mes"], "tasa_inasistencia": tasa, "total": r["total"]})
    return jsonify(data)


@app.route("/api/agenda-hoy")
@login_required
def api_agenda_hoy():
    hoy = datetime.now().date().isoformat()
    with get_cursor() as cur:
        paginacion = (
            "OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY"
            if cur._is_sql_server else "LIMIT ?"
        )
        rows = cur.execute(
            f"""SELECT c.hora, c.estado, p.nombre AS paciente, m.nombre AS medico, e.nombre AS especialidad
               FROM citas c
               JOIN pacientes p ON p.id=c.paciente_id
               JOIN medicos m ON m.id=c.medico_id
               JOIN especialidades e ON e.id=c.especialidad_id
               WHERE c.fecha=? ORDER BY c.hora {paginacion}""",
            (hoy, 8),
        ).fetchall()
    return jsonify(rows_to_dicts(rows))


if __name__ == "__main__":
    try:
        init_db()
    except Exception as exc:
        print("[WARN] No fue posible inicializar la base de datos PostgreSQL/Supabase:", exc)
        print("[WARN] El servidor Flask continuará con el arranque, pero los endpoints que dependan de la base de datos necesitarán una DATABASE_URL/DIRECT_URL válida.")
    app.run(debug=True, port=5000)
