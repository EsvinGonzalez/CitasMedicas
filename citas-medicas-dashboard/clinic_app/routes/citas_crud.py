"""
citas_crud.py
Endpoints de administración de citas: crear, listar, editar, cancelar,
marcar como completada (con generación de factura) y eliminar.

Reglas de negocio por rol:
- paciente:       solo ve y agenda/cancela SUS PROPIAS citas.
- recepcionista:  crea, edita y cancela citas de cualquier paciente.
- medico:         marca sus citas como completadas.
- admin:          acceso total, incluida la eliminación definitiva.
"""

from datetime import datetime

from flask import Blueprint, jsonify, request, session

from clinic_app.infrastructure.database import get_cursor
from clinic_app.routes.auth import login_required, roles_required

citas_bp = Blueprint("citas_crud", __name__, url_prefix="/api/citas")


def _paciente_id_de_usuario_actual():
    with get_cursor() as cur:
        row = cur.execute(
            "SELECT paciente_id, email FROM usuarios WHERE id=?", (session["user_id"],)
        ).fetchone()
        if not row:
            return None
        if row["paciente_id"]:
            return row["paciente_id"]
        paciente = cur.execute(
            "SELECT id FROM pacientes WHERE email=?", (row["email"],)
        ).fetchone()
    return paciente["id"] if paciente else None


@citas_bp.route("", methods=["GET"])
@login_required
def listar():
    fecha = request.args.get("fecha")
    estado = request.args.get("estado")
    medico_id = request.args.get("medico_id")
    limite = int(request.args.get("limite", 50))

    condiciones, params = [], []
    if fecha:
        condiciones.append("c.fecha = ?"); params.append(fecha)
    if estado:
        condiciones.append("c.estado = ?"); params.append(estado)
    if medico_id:
        condiciones.append("c.medico_id = ?"); params.append(medico_id)

    if session.get("rol") == "paciente":
        condiciones.append("c.paciente_id = ?")
        params.append(_paciente_id_de_usuario_actual())

    where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
    params.append(limite)

    with get_cursor() as cur:
        paginacion = (
            "OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY"
            if cur._is_sql_server else "LIMIT ?"
        )
        rows = cur.execute(
            f"""SELECT c.id, c.fecha, c.hora, c.estado, c.motivo, c.modalidad, c.riesgo_noshow,
                       p.id AS paciente_id, p.nombre AS paciente,
                       m.id AS medico_id, m.nombre AS medico,
                       e.nombre AS especialidad, e.color
                FROM citas c
                JOIN pacientes p ON p.id = c.paciente_id
                JOIN medicos m ON m.id = c.medico_id
                JOIN especialidades e ON e.id = c.especialidad_id
                {where}
                ORDER BY c.fecha DESC, c.hora DESC
                {paginacion}""",
            params,
        ).fetchall()

    return jsonify([dict(r) for r in rows])


@citas_bp.route("/<int:cita_id>", methods=["GET"])
@login_required
def obtener(cita_id):
    with get_cursor() as cur:
        cita = cur.execute(
            """SELECT c.*, p.nombre AS paciente, m.nombre AS medico, e.nombre AS especialidad
               FROM citas c
               JOIN pacientes p ON p.id = c.paciente_id
               JOIN medicos m ON m.id = c.medico_id
               JOIN especialidades e ON e.id = c.especialidad_id
               WHERE c.id = ?""",
            (cita_id,),
        ).fetchone()

    if not cita:
        return jsonify({"error": "Cita no encontrada"}), 404
    if session.get("rol") == "paciente" and cita["paciente_id"] != _paciente_id_de_usuario_actual():
        return jsonify({"error": "No tienes acceso a esta cita"}), 403

    return jsonify(dict(cita))


@citas_bp.route("", methods=["POST"])
@roles_required("admin", "recepcionista", "paciente")
def crear():
    data = request.get_json(force=True) or {}
    paciente_id = _paciente_id_de_usuario_actual() if session.get("rol") == "paciente" else data.get("paciente_id")
    medico_id = data.get("medico_id")
    fecha = str(data.get("fecha") or "").strip()
    hora = str(data.get("hora") or "").strip()
    motivo = (data.get("motivo") or "").strip()
    modalidad = data.get("modalidad") or "presencial"
    if modalidad not in ("presencial", "telemedicina"):
        modalidad = "presencial"

    if not all([paciente_id, medico_id, fecha, hora]):
        return jsonify({"error": "paciente_id, medico_id, fecha y hora son obligatorios"}), 400

    try:
        paciente_id = int(paciente_id)
        medico_id = int(medico_id)
        fecha_consulta = datetime.strptime(fecha, "%Y-%m-%d").date()
        hora_consulta = datetime.strptime(hora, "%H:%M").time()
    except (TypeError, ValueError):
        return jsonify({"error": "Selecciona un paciente, médico, fecha y hora válidos"}), 400

    if session.get("rol") == "paciente":
        ahora = datetime.now()
        if fecha_consulta < ahora.date() or (
            fecha_consulta == ahora.date() and hora_consulta <= ahora.time()
        ):
            return jsonify({"error": "Selecciona una fecha y hora futuras para tu cita."}), 400

    with get_cursor(commit=True) as cur:
        cur.lock_appointment_slots(paciente_id, medico_id, fecha, hora)
        medico = cur.execute(
            "SELECT especialidad_id FROM medicos WHERE id=? AND activo=1", (medico_id,)
        ).fetchone()
        if not medico:
            return jsonify({"error": "Médico no encontrado o inactivo"}), 404

        horario_ocupado = cur.execute(
            """SELECT id, fecha, hora FROM citas
               WHERE medico_id=? AND fecha=? AND hora=? AND estado IN ('confirmada','completada')""",
            (medico_id, fecha, hora),
        ).fetchone()
        if horario_ocupado:
            return jsonify({
                "error": "El horario ya está ocupado para este médico. Por favor, selecciona otro horario."
            }), 409

        cita_duplicada = cur.execute(
            """SELECT id FROM citas
               WHERE paciente_id=? AND fecha=? AND hora=?
               AND estado IN ('confirmada','completada')""",
            (paciente_id, fecha, hora),
        ).fetchone()
        if cita_duplicada:
            return jsonify({
                "error": "El paciente ya tiene una cita activa en esa fecha y hora. No se puede duplicar."
            }), 409

        obtener_id = "OUTPUT INSERTED.id" if cur._is_sql_server else ""
        cur.execute(
            f"""INSERT INTO citas
               (paciente_id, medico_id, especialidad_id, fecha, hora, estado, modalidad, motivo, creado_en)
               {obtener_id}
               VALUES (?,?,?,?,?, 'confirmada', ?, ?, ?)""",
            (paciente_id, medico_id, medico["especialidad_id"], fecha, hora, modalidad, motivo,
             datetime.now().isoformat()),
        )
        nueva_id = cur.fetchone()[0] if cur._is_sql_server else cur.lastrowid

    from clinic_app.services.prediccion import predecir_inasistencia, guardar_prediccion, UMBRAL
    from clinic_app.services.notificaciones import notificar_cita
    from clinic_app.services.auditoria import registrar_auditoria

    prob = predecir_inasistencia(int(paciente_id), medico["especialidad_id"], fecha, hora)
    reforzado = guardar_prediccion(nueva_id, prob)
    notificar_cita(
        nueva_id,
        "recordatorio" if not reforzado else "noshow_reforzado",
        "Cita confirmada — Clínica San José",
        f"Su cita quedó agendada el {fecha} a las {hora} ({modalidad}). "
        + (f"Riesgo de inasistencia estimado {int(prob*100)}%. Recuerde asistir." if reforzado else ""),
        reforzado=reforzado,
    )
    if modalidad == "telemedicina":
        from clinic_app.routes.telemedicina import _obtener_o_crear
        _obtener_o_crear(nueva_id)
    registrar_auditoria("crear", "citas", "cita", nueva_id)

    return jsonify({
        "id": nueva_id,
        "mensaje": "Cita creada correctamente",
        "riesgo_noshow": prob,
        "recordatorio_reforzado": reforzado,
        "umbral": UMBRAL,
    }), 201


@citas_bp.route("/<int:cita_id>", methods=["PUT"])
@roles_required("admin", "recepcionista")
def editar(cita_id):
    data = request.get_json(force=True) or {}
    campos_permitidos = ("fecha", "hora", "medico_id", "motivo")
    campos = {c: data[c] for c in campos_permitidos if c in data}

    if not campos:
        return jsonify({"error": "No se enviaron campos para actualizar"}), 400

    with get_cursor() as cur:
        cita = cur.execute(
            "SELECT estado, paciente_id, medico_id FROM citas WHERE id=?", (cita_id,)
        ).fetchone()
    if not cita:
        return jsonify({"error": "Cita no encontrada"}), 404
    if cita["estado"] != "confirmada":
        return jsonify({"error": 'Solo se pueden editar citas en estado "confirmada"'}), 409

    if "medico_id" in campos:
        with get_cursor() as cur:
            medico = cur.execute(
                "SELECT especialidad_id FROM medicos WHERE id=? AND activo=1",
                (campos["medico_id"],),
            ).fetchone()
        if not medico:
            return jsonify({"error": "Médico no encontrado o inactivo"}), 404
        campos["especialidad_id"] = medico["especialidad_id"]

    with get_cursor() as cur:
        fecha = campos.get("fecha")
        hora = campos.get("hora")
        medico_id = campos.get("medico_id", cita["medico_id"])
        if fecha or hora or "medico_id" in campos:
            actual = cur.execute(
                "SELECT fecha, hora FROM citas WHERE id=?", (cita_id,)
            ).fetchone()
            choque = cur.execute(
                """SELECT id FROM citas
                   WHERE medico_id=? AND fecha=? AND hora=? AND id<>?
                   AND estado IN ('confirmada','completada')""",
                (medico_id, fecha or actual["fecha"], hora or actual["hora"], cita_id),
            ).fetchone()
            if choque:
                return jsonify({
                    "error": "El horario ya está ocupado para este médico. Por favor, selecciona otro horario."
                }), 409
            duplicada = cur.execute(
                """SELECT id FROM citas
                   WHERE paciente_id=? AND fecha=? AND hora=? AND id<>?
                   AND estado IN ('confirmada','completada')""",
                (cita["paciente_id"], fecha or actual["fecha"], hora or actual["hora"], cita_id),
            ).fetchone()
            if duplicada:
                return jsonify({
                    "error": "El paciente ya tiene otra cita activa en esa fecha y hora. No se puede duplicar."
                }), 409

    set_clause = ", ".join(f"{campo}=?" for campo in campos)
    with get_cursor(commit=True) as cur:
        cur.execute(f"UPDATE citas SET {set_clause} WHERE id=?", (*campos.values(), cita_id))

    from clinic_app.services.notificaciones import notificar_cita
    from clinic_app.services.auditoria import registrar_auditoria
    cita_full = None
    with get_cursor() as cur:
        cita_full = cur.execute("SELECT * FROM citas WHERE id=?", (cita_id,)).fetchone()
    if cita_full:
        notificar_cita(cita_id, "cambio", "Cita reprogramada", "Su cita fue modificada. Revise fecha y hora.")
    registrar_auditoria("editar", "citas", "cita", cita_id)

    return jsonify({"mensaje": "Cita actualizada correctamente"})


@citas_bp.route("/<int:cita_id>/cancelar", methods=["PATCH"])
@login_required
def cancelar(cita_id):
    data = request.get_json(silent=True) or {}
    motivo_cancelacion = str(data.get("motivo") or "").strip()
    with get_cursor() as cur:
        cita = cur.execute("SELECT * FROM citas WHERE id=?", (cita_id,)).fetchone()
    if not cita:
        return jsonify({"error": "Cita no encontrada"}), 404

    rol = session.get("rol")
    if rol == "paciente":
        if cita["paciente_id"] != _paciente_id_de_usuario_actual():
            return jsonify({"error": "Solo puedes cancelar tus propias citas"}), 403
    elif rol not in ("admin", "recepcionista"):
        return jsonify({"error": "No tienes permiso para cancelar citas"}), 403

    if cita["estado"] != "confirmada":
        return jsonify({"error": 'Solo se pueden cancelar citas en estado "confirmada"'}), 409

    with get_cursor(commit=True) as cur:
        cur.execute("UPDATE citas SET estado='cancelada' WHERE id=?", (cita_id,))

    from clinic_app.services.notificaciones import notificar_cita
    from clinic_app.services.auditoria import registrar_auditoria
    notificar_cita(cita_id, "cancelacion", "Cita cancelada", "Su cita fue cancelada. Puede reprogramar desde el portal.")
    detalle = f"Motivo de cancelación: {motivo_cancelacion}" if motivo_cancelacion else "Cita cancelada"
    registrar_auditoria("cancelar", "citas", "cita", cita_id, detalle)

    return jsonify({"mensaje": "Cita cancelada correctamente"})


@citas_bp.route("/<int:cita_id>/inasistencia", methods=["PATCH"])
@roles_required("admin", "medico", "recepcionista")
def marcar_inasistencia(cita_id):
    with get_cursor() as cur:
        cita = cur.execute("SELECT id, estado, fecha, hora FROM citas WHERE id=?", (cita_id,)).fetchone()
    if not cita:
        return jsonify({"error": "Cita no encontrada"}), 404
    if cita["estado"] != "confirmada":
        return jsonify({"error": 'Solo se puede registrar inasistencia en citas "confirmadas"'}), 409
    fecha_hora = datetime.fromisoformat(
        f"{str(cita['fecha'])[:10]}T{str(cita['hora'])[:8]}"
    )
    if fecha_hora > datetime.now():
        return jsonify({"error": "La inasistencia solo se puede registrar después de la hora de la cita"}), 409

    with get_cursor(commit=True) as cur:
        cur.execute("UPDATE citas SET estado='no_asistio' WHERE id=?", (cita_id,))

    from clinic_app.services.auditoria import registrar_auditoria
    registrar_auditoria("no_asistio", "citas", "cita", cita_id, "Paciente no se presentó")
    return jsonify({"mensaje": "La inasistencia quedó registrada"})


@citas_bp.route("/<int:cita_id>/completar", methods=["PATCH"])
@roles_required("admin", "medico", "recepcionista")
def completar(cita_id):
    data = request.get_json(silent=True) or {}
    monto = data.get("monto")
    metodo_pago = data.get("metodo_pago", "efectivo")

    with get_cursor() as cur:
        cita = cur.execute("SELECT * FROM citas WHERE id=?", (cita_id,)).fetchone()
    if not cita:
        return jsonify({"error": "Cita no encontrada"}), 404
    if cita["estado"] != "confirmada":
        return jsonify({"error": 'Solo se pueden completar citas en estado "confirmada"'}), 409

    with get_cursor(commit=True) as cur:
        cur.execute("UPDATE citas SET estado='completada' WHERE id=?", (cita_id,))
        if monto:
            cur.execute(
                """INSERT INTO facturas (cita_id, monto, metodo_pago, fecha_pago, estado)
                   VALUES (?,?,?,?, 'pagada')""",
                (cita_id, monto, metodo_pago, datetime.now().date().isoformat()),
            )

    from clinic_app.services.auditoria import registrar_auditoria
    registrar_auditoria("completar", "citas", "cita", cita_id, "Paciente llegó a la cita")
    return jsonify({"mensaje": "Cita marcada como completada"})


@citas_bp.route("/<int:cita_id>", methods=["DELETE"])
@roles_required("admin")
def eliminar(cita_id):
    with get_cursor() as cur:
        existe = cur.execute("SELECT id FROM citas WHERE id=?", (cita_id,)).fetchone()
        if existe:
            tiene_historia = cur.execute(
                """SELECT
                       (SELECT COUNT(*) FROM evoluciones WHERE cita_id=?) AS evoluciones,
                       (SELECT COUNT(*) FROM recetas WHERE cita_id=?) AS recetas""",
                (cita_id, cita_id),
            ).fetchone()
    if not existe:
        return jsonify({"error": "Cita no encontrada"}), 404
    if tiene_historia["evoluciones"] or tiene_historia["recetas"]:
        return jsonify({"error": "No se puede eliminar una cita con evolución o receta clínica asociada; puedes cancelarla."}), 409

    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM teleconsultas WHERE cita_id=?", (cita_id,))
        cur.execute("DELETE FROM predicciones_noshow WHERE cita_id=?", (cita_id,))
        cur.execute("DELETE FROM notificaciones WHERE cita_id=?", (cita_id,))
        cur.execute("DELETE FROM facturas WHERE cita_id=?", (cita_id,))
        cur.execute("DELETE FROM citas WHERE id=?", (cita_id,))

    return jsonify({"mensaje": "Cita eliminada permanentemente"})