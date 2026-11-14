"""Recetas electrónicas en PDF vinculadas al expediente."""

from datetime import datetime

from flask import Blueprint, jsonify, request, send_file, session
from io import BytesIO

from clinic_app.infrastructure.database import get_cursor
from clinic_app.routes.auth import login_required, roles_required
from clinic_app.services.auditoria import registrar_auditoria
from clinic_app.services.pdf_util import pdf_texto

recetas_bp = Blueprint("recetas", __name__, url_prefix="/api/recetas")


@recetas_bp.route("", methods=["GET"])
@login_required
def listar():
    with get_cursor() as cur:
        sql = """SELECT r.*, p.nombre AS paciente, m.nombre AS medico
                   FROM recetas r
                   JOIN expedientes e ON e.id = r.expediente_id
                   JOIN pacientes p ON p.id = e.paciente_id
                   LEFT JOIN medicos m ON m.id = r.medico_id
                   ORDER BY r.creado_en DESC"""
        if cur._is_sql_server:
            sql = """SELECT TOP 80 r.*, p.nombre AS paciente, m.nombre AS medico
                       FROM recetas r
                       JOIN expedientes e ON e.id = r.expediente_id
                       JOIN pacientes p ON p.id = e.paciente_id
                       LEFT JOIN medicos m ON m.id = r.medico_id
                       ORDER BY r.creado_en DESC"""
        rows = cur.execute(sql).fetchall()
    return jsonify([dict(r) for r in rows])


@recetas_bp.route("", methods=["POST"])
@roles_required("admin", "medico")
def crear():
    data = request.get_json(force=True) or {}
    try:
        paciente_id = int(data.get("paciente_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "Selecciona un paciente válido."}), 400
    medicamentos = (data.get("medicamentos") or "").strip()
    if not medicamentos:
        return jsonify({"error": "Indica al menos un medicamento."}), 400

    if session.get("rol") == "medico":
        with get_cursor() as cur:
            medico = cur.execute(
                "SELECT medico_id FROM usuarios WHERE id=?", (session["user_id"],)
            ).fetchone()
        medico_id = medico["medico_id"] if medico else None
        if not medico_id:
            return jsonify({"error": "Tu cuenta no está vinculada a un registro médico."}), 403
    else:
        try:
            medico_id = int(data.get("medico_id"))
        except (TypeError, ValueError):
            return jsonify({"error": "Selecciona el médico responsable de la receta."}), 400

    with get_cursor() as cur:
        paciente = cur.execute(
            "SELECT id FROM pacientes WHERE id=?", (paciente_id,)
        ).fetchone()
        if not paciente:
            return jsonify({"error": "Paciente no encontrado."}), 404
        medico = cur.execute(
            "SELECT id FROM medicos WHERE id=? AND activo=1", (medico_id,)
        ).fetchone()
        if not medico:
            return jsonify({"error": "Médico no encontrado o inactivo."}), 404
        cita_id = data.get("cita_id")
        if cita_id:
            try:
                cita_id = int(cita_id)
            except (TypeError, ValueError):
                return jsonify({"error": "La cita seleccionada no es válida."}), 400
            cita = cur.execute(
                "SELECT paciente_id, medico_id FROM citas WHERE id=?", (cita_id,)
            ).fetchone()
            if not cita or cita["paciente_id"] != paciente_id or cita["medico_id"] != medico_id:
                return jsonify({"error": "La cita debe pertenecer al paciente y médico seleccionados."}), 400

    from clinic_app.routes.expedientes import _asegurar_expediente
    exp = _asegurar_expediente(paciente_id)
    with get_cursor(commit=True) as cur:
        cur.execute(
            """INSERT INTO recetas (expediente_id, cita_id, medico_id, medicamentos, dosis, frecuencia, duracion_tratamiento, vigencia, indicaciones, creado_en)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (exp["id"], cita_id, medico_id, medicamentos,
             data.get("dosis", ""), data.get("frecuencia", ""),
             data.get("duracion_tratamiento", ""), data.get("vigencia", ""),
             data.get("indicaciones", ""), datetime.now().isoformat()),
        )
        rid = cur.lastrowid
    registrar_auditoria("crear", "recetas", "receta", rid)
    return jsonify({"id": rid, "mensaje": "Receta emitida"}), 201


@recetas_bp.route("/<int:receta_id>/medico", methods=["PATCH"])
@roles_required("admin")
def asignar_medico(receta_id):
    data = request.get_json(silent=True) or {}
    try:
        medico_id = int(data.get("medico_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "Selecciona un médico válido."}), 400

    with get_cursor() as cur:
        medico = cur.execute(
            "SELECT id FROM medicos WHERE id=? AND activo=1", (medico_id,)
        ).fetchone()
        if not medico:
            return jsonify({"error": "Médico no encontrado o inactivo."}), 404
        receta = cur.execute(
            "SELECT id FROM recetas WHERE id=?", (receta_id,)
        ).fetchone()
        if not receta:
            return jsonify({"error": "Receta no encontrada."}), 404

    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE recetas SET medico_id=? WHERE id=?", (medico_id, receta_id)
        )
    registrar_auditoria("actualizar", "recetas", "receta_medico", receta_id)
    return jsonify({"success": True, "mensaje": "Médico responsable asignado a la receta."})


@recetas_bp.route("/<int:receta_id>/pdf", methods=["GET"])
@login_required
def descargar_pdf(receta_id):
    with get_cursor() as cur:
        r = cur.execute(
            """SELECT r.*, p.nombre AS paciente, m.nombre AS medico
               FROM recetas r
               JOIN expedientes e ON e.id = r.expediente_id
               JOIN pacientes p ON p.id = e.paciente_id
               LEFT JOIN medicos m ON m.id = r.medico_id
               WHERE r.id=?""",
            (receta_id,),
        ).fetchone()
    if not r:
        return jsonify({"error": "Receta no encontrada"}), 404
    lineas = [
        f"Paciente: {r['paciente']}",
        f"Médico: {r['medico'] or 'No asignado'}",
        f"Fecha: {r['creado_en'][:10]}",
        "",
        "Medicamentos:",
        r["medicamentos"],
        f"Dosis: {r['dosis'] or '—'}",
        f"Frecuencia: {r['frecuencia'] or '—'}",
        f"Duración: {r['duracion_tratamiento'] or '—'}",
        f"Vigencia: {r['vigencia'] or '—'}",
        "",
        "Indicaciones:",
        r["indicaciones"] or "Según criterio médico.",
        "",
        "Documento electrónico vinculado al expediente clínico.",
    ]
    pdf = pdf_texto("Receta electrónica", lineas)
    registrar_auditoria("ver", "recetas", "receta_pdf", receta_id)
    as_attachment = request.args.get("download") == "1"
    return send_file(
        BytesIO(pdf),
        mimetype="application/pdf",
        as_attachment=as_attachment,
        download_name=f"receta-{receta_id}.pdf",
    )
