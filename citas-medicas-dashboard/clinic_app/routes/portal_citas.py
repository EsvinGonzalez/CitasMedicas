"""Portal de autogestión de citas para pacientes."""

from datetime import datetime

from flask import Blueprint, jsonify, render_template, request, session

from clinic_app.infrastructure.database import get_cursor
from clinic_app.routes.auth import roles_required
from clinic_app.routes.citas_crud import _paciente_id_de_usuario_actual

portal_citas_bp = Blueprint("portal_citas", __name__)


@portal_citas_bp.route("/agendar-cita")
@roles_required("paciente")
def agendar():
    return render_template(
        "portal_citas.html",
        user=session.get("nombre", "Paciente"),
    )


@portal_citas_bp.route("/api/citas/disponibilidad")
@roles_required("paciente")
def disponibilidad():
    paciente_id = _paciente_id_de_usuario_actual()
    if not paciente_id:
        return jsonify({
            "error": "Tu cuenta aún no está vinculada a un expediente de paciente. Comunícate con recepción.",
        }), 409

    try:
        medico_id = int(request.args.get("medico_id", ""))
        fecha = request.args.get("fecha", "")
        hora = request.args.get("hora", "")
        fecha_consulta = datetime.strptime(fecha, "%Y-%m-%d").date()
        hora_consulta = datetime.strptime(hora, "%H:%M").time()
    except (TypeError, ValueError):
        return jsonify({"error": "Selecciona un médico, una fecha y una hora válidos."}), 400

    ahora = datetime.now()
    if fecha_consulta < ahora.date() or (
        fecha_consulta == ahora.date() and hora_consulta <= ahora.time()
    ):
        return jsonify({"error": "Selecciona una fecha y hora futuras."}), 400

    with get_cursor() as cur:
        medico = cur.execute(
            "SELECT id FROM medicos WHERE id=? AND activo=1", (medico_id,)
        ).fetchone()
        if not medico:
            return jsonify({"error": "El médico seleccionado no está disponible."}), 404

        horario_ocupado = cur.execute(
            """SELECT id FROM citas
               WHERE medico_id=? AND fecha=? AND hora=?
               AND estado IN ('confirmada','completada')""",
            (medico_id, fecha, hora),
        ).fetchone()
        cita_paciente = cur.execute(
            """SELECT id FROM citas
               WHERE paciente_id=? AND fecha=? AND hora=?
               AND estado IN ('confirmada','completada')""",
            (paciente_id, fecha, hora),
        ).fetchone()

        horarios = cur.execute(
            """SELECT hora FROM citas
               WHERE medico_id=? AND fecha=?
               AND estado IN ('confirmada','completada')
               ORDER BY hora""",
            (medico_id, fecha),
        ).fetchall()

    horas_ocupadas = sorted({str(row["hora"])[:5] for row in horarios})
    disponible = not horario_ocupado and not cita_paciente
    if horario_ocupado:
        mensaje = "Ese horario ya está ocupado con este médico. Elige otra hora o un médico diferente."
    elif cita_paciente:
        mensaje = "Ya tienes una cita a esa hora. Elige otro horario."
    else:
        mensaje = "¡Horario disponible! Puedes continuar y confirmar tu cita."

    return jsonify({
        "disponible": disponible,
        "mensaje": mensaje,
        "horarios_ocupados": horas_ocupadas,
    })
