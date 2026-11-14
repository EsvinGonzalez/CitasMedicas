"""Telemedicina: sala Jitsi, espera virtual y consentimiento de grabación."""

from datetime import datetime

from flask import Blueprint, jsonify, request

from clinic_app.infrastructure.database import get_cursor
from clinic_app.routes.auth import login_required, roles_required
from clinic_app.services.auditoria import registrar_auditoria

telemedicina_bp = Blueprint("telemedicina", __name__, url_prefix="/api/telemedicina")


def _sala(cita_id):
    return f"ClinicaSanJose-cita-{cita_id}"


def _parse_sala_from_url(enlace):
    """Normaliza el enlace de Jitsi y devuelve el identificador de la sala."""
    enlace = (enlace or "").strip()
    if not enlace:
        return None
    if enlace.startswith("http://") or enlace.startswith("https://"):
        # Acepta URLs completas de meet.jit.si o un enlace directo a Jitsi
        import urllib.parse
        parts = urllib.parse.urlparse(enlace)
        if parts.netloc:
            path = parts.path.strip('/').split('/')[-1]
            return path or parts.path.strip('/') or None
        return enlace.strip('/').split('/')[-1] or None
    return enlace.strip('/')


def _obtener_o_crear(cita_id):
    with get_cursor() as cur:
        row = cur.execute("SELECT * FROM teleconsultas WHERE cita_id=?", (cita_id,)).fetchone()
        cita = cur.execute("SELECT * FROM citas WHERE id=?", (cita_id,)).fetchone()
    if not cita:
        return None, None
    if row:
        return dict(row), dict(cita)
    with get_cursor(commit=True) as cur:
        cur.execute(
            """INSERT INTO teleconsultas (cita_id, sala_codigo, estado)
               VALUES (?,?, 'sala_espera')""",
            (cita_id, _sala(cita_id)),
        )
        tid = cur.lastrowid
    with get_cursor() as cur:
        return dict(cur.execute("SELECT * FROM teleconsultas WHERE id=?", (tid,)).fetchone()), dict(cita)


@telemedicina_bp.route("", methods=["POST"])
@roles_required("admin", "recepcionista", "medico")
def crear():
    data = request.get_json(force=True) or {}
    cita_id = data.get("cita_id")
    tipo_cita = data.get("tipo_cita") or data.get("tipo") or "virtual"
    if tipo_cita not in ("presencial", "virtual"):
        tipo_cita = "virtual"
    enlace_sala = (data.get("enlace_sala") or "").strip()
    documentos = (data.get("documentos_compartidos") or "").strip()
    asistencia_confirmada = 1 if str(data.get("asistencia_confirmada", "0")) == "1" else 0

    if not cita_id:
        return jsonify({"error": "Debe seleccionar una cita"}), 400

    with get_cursor() as cur:
        cita = cur.execute("SELECT id, modalidad, estado FROM citas WHERE id=?", (cita_id,)).fetchone()
        if not cita:
            return jsonify({"error": "Cita no encontrada"}), 404

    sala_id = _parse_sala_from_url(enlace_sala)
    if not sala_id:
        sala_id = _sala(cita_id)

    estado = 'sala_espera'
    if asistencia_confirmada:
        estado = 'en_curso'

    with get_cursor(commit=True) as cur:
        cur.execute(
            """INSERT OR REPLACE INTO teleconsultas
               (cita_id, tipo_cita, sala_codigo, enlace_sala, estado,
                asistencia_confirmada, consentimiento_grabacion,
                documentos_compartidos, iniciado_en)
               VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)""",
            (cita_id, tipo_cita, sala_id, enlace_sala or f"https://meet.jit.si/{sala_id}",
             estado, asistencia_confirmada, documentos or "Sin documentos",
             datetime.now().isoformat() if asistencia_confirmada else None),
        )
    registrar_auditoria("crear", "telemedicina", "teleconsulta", cita_id)
    return jsonify({"mensaje": "Enlace de telemedicina creado", "cita_id": cita_id, "sala_codigo": sala_id, "jitsi_url": enlace_sala or f"https://meet.jit.si/{sala_id}"}), 201


@telemedicina_bp.route("", methods=["GET"])
@login_required
def listar():
    with get_cursor() as cur:
        rows = cur.execute(
            """SELECT c.id AS cita_id, c.fecha, c.hora, c.estado, c.modalidad,
                      p.nombre AS paciente, m.nombre AS medico, e.nombre AS especialidad,
                      COALESCE(t.tipo_cita, 'virtual') AS tipo_cita,
                      t.estado AS sala_estado, t.asistencia_confirmada,
                      t.consentimiento_grabacion, t.sala_codigo, t.enlace_sala,
                      COALESCE(t.documentos_compartidos, 'Sin documentos') AS documentos_compartidos
               FROM citas c
               JOIN pacientes p ON p.id = c.paciente_id
               JOIN medicos m ON m.id = c.medico_id
               JOIN especialidades e ON e.id = c.especialidad_id
               LEFT JOIN teleconsultas t ON t.cita_id = c.id
               WHERE c.modalidad='telemedicina' AND c.estado='confirmada'
               ORDER BY c.fecha, c.hora"""
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@telemedicina_bp.route("/<int:cita_id>", methods=["GET"])
@login_required
def detalle(cita_id):
    tele, cita = _obtener_o_crear(cita_id)
    if not cita:
        return jsonify({"error": "Cita no encontrada"}), 404
    url = f"https://meet.jit.si/{tele['sala_codigo']}"
    registrar_auditoria("ver", "telemedicina", "teleconsulta", cita_id)
    return jsonify({**tele, "jitsi_url": url, "cita": cita})


@telemedicina_bp.route("/<int:cita_id>/asistencia", methods=["POST"])
@login_required
def confirmar_asistencia(cita_id):
    tele, cita = _obtener_o_crear(cita_id)
    if not cita:
        return jsonify({"error": "Cita no encontrada"}), 404
    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE teleconsultas SET asistencia_confirmada=1, estado='en_curso', iniciado_en=? WHERE cita_id=?",
            (datetime.now().isoformat(), cita_id),
        )
    registrar_auditoria("editar", "telemedicina", "asistencia", cita_id)
    return jsonify({"mensaje": "Asistencia confirmada", "jitsi_url": f"https://meet.jit.si/{tele['sala_codigo']}"})


@telemedicina_bp.route("/<int:cita_id>/consentimiento", methods=["POST"])
@login_required
def consentimiento(cita_id):
    data = request.get_json(silent=True) or {}
    aceptar = 1 if data.get("acepta") else 0
    _, cita = _obtener_o_crear(cita_id)
    if not cita:
        return jsonify({"error": "Cita no encontrada"}), 404
    with get_cursor(commit=True) as cur:
        cur.execute(
            """UPDATE teleconsultas SET consentimiento_grabacion=?, grabacion_habilitada=?
               WHERE cita_id=?""",
            (aceptar, aceptar, cita_id),
        )
    registrar_auditoria("editar", "telemedicina", "consentimiento", cita_id)
    return jsonify({"mensaje": "Consentimiento registrado", "grabacion": bool(aceptar)})


@telemedicina_bp.route("/<int:cita_id>/finalizar", methods=["POST"])
@roles_required("admin", "medico")
def finalizar(cita_id):
    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE teleconsultas SET estado='finalizada', finalizado_en=? WHERE cita_id=?",
            (datetime.now().isoformat(), cita_id),
        )
    return jsonify({"mensaje": "Teleconsulta finalizada"})
