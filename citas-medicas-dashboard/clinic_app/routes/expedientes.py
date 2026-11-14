"""Expediente clínico: ficha, evoluciones y acceso auditado."""

from datetime import datetime

from flask import Blueprint, jsonify, request, session

from clinic_app.infrastructure.database import get_cursor
from clinic_app.routes.auth import login_required, roles_required
from clinic_app.services.auditoria import registrar_auditoria

expedientes_bp = Blueprint("expedientes", __name__, url_prefix="/api/expedientes")


def _asegurar_expediente(paciente_id):
    with get_cursor() as cur:
        row = cur.execute("SELECT * FROM expedientes WHERE paciente_id=?", (paciente_id,)).fetchone()
    if row:
        return dict(row)
    ahora = datetime.now().isoformat()
    with get_cursor(commit=True) as cur:
        cur.execute(
            """INSERT INTO expedientes (paciente_id, tipo_sangre, alergias, antecedentes, creado_en, actualizado_en)
               VALUES (?, '', '', '', ?, ?)""",
            (paciente_id, ahora, ahora),
        )
        eid = cur.lastrowid
    with get_cursor() as cur:
        return dict(cur.execute("SELECT * FROM expedientes WHERE id=?", (eid,)).fetchone())


@expedientes_bp.route("", methods=["GET"])
@login_required
def listar():
    with get_cursor() as cur:
        rows = cur.execute(
            """SELECT e.*, p.nombre AS paciente, p.email, p.telefono
               FROM expedientes e JOIN pacientes p ON p.id = e.paciente_id
               ORDER BY p.nombre"""
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@expedientes_bp.route("/historial", methods=["GET"])
@login_required
def historial():
    """Historial cronológico de evoluciones con filtros y auditoría."""
    paciente_id = request.args.get("paciente_id")
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")

    where = []
    params = []
    if paciente_id:
        where.append("e.paciente_id = ?")
        params.append(int(paciente_id))
    if desde:
        where.append("date(ev.creado_en) >= ?")
        params.append(desde)
    if hasta:
        where.append("date(ev.creado_en) <= ?")
        params.append(hasta)

    sql_where = "WHERE " + " AND ".join(where) if where else ""

    with get_cursor() as cur:
        rows = cur.execute(f"""
            SELECT
                p.nombre AS paciente,
                ev.creado_en AS fecha,
                COALESCE(m.nombre, mc.nombre, 'Sin médico') AS medico,
                COALESCE(ev.diagnostico, 'Sin diagnóstico') AS diagnostico,
                COALESCE(ev.nota, 'Sin nota') AS nota_evolucion,
                COALESCE(a.usuario_email, 'Sistema') AS auditado_por,
                ev.id AS evolucion_id,
                ev.cita_id AS cita_id,
                c.fecha AS fecha_cita,
                c.estado AS estado_cita
            FROM evoluciones ev
            JOIN expedientes e ON e.id = ev.expediente_id
            JOIN pacientes p ON p.id = e.paciente_id
            LEFT JOIN medicos m ON m.id = ev.medico_id
            LEFT JOIN citas c ON c.id = ev.cita_id
            LEFT JOIN medicos mc ON mc.id = c.medico_id
            LEFT JOIN auditoria a
                ON a.modulo = 'expediente'
               AND a.recurso = 'evolucion'
               AND a.recurso_id = CAST(ev.id AS TEXT)
            {sql_where}
            ORDER BY ev.creado_en DESC
        """, params).fetchall()

    return jsonify([dict(r) for r in rows])


@expedientes_bp.route("/historial/<int:evolucion_id>/medico", methods=["PATCH"])
@roles_required("admin")
def asignar_medico_evolucion(evolucion_id):
    data = request.get_json(silent=True) or {}
    try:
        medico_id = int(data.get("medico_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "Selecciona un médico válido."}), 400
    with get_cursor() as cur:
        if not cur.execute("SELECT id FROM medicos WHERE id=? AND activo=1", (medico_id,)).fetchone():
            return jsonify({"error": "El médico no existe o está inactivo."}), 404
        if not cur.execute("SELECT id FROM evoluciones WHERE id=?", (evolucion_id,)).fetchone():
            return jsonify({"error": "La evolución no existe."}), 404
    with get_cursor(commit=True) as cur:
        cur.execute("UPDATE evoluciones SET medico_id=? WHERE id=?", (medico_id, evolucion_id))
    registrar_auditoria("actualizar", "expediente", "evolucion_medico", evolucion_id)
    return jsonify({"success": True, "mensaje": "Médico asignado al historial."})


@expedientes_bp.route("/paciente/<int:paciente_id>", methods=["GET"])
@login_required
def obtener(paciente_id):
    if session.get("rol") == "paciente":
        with get_cursor() as cur:
            propio = cur.execute("SELECT paciente_id FROM usuarios WHERE id=?", (session["user_id"],)).fetchone()
        if not propio or propio["paciente_id"] != paciente_id:
            return jsonify({"error": "No puedes ver este expediente"}), 403

    exp = _asegurar_expediente(paciente_id)
    with get_cursor() as cur:
        evo = cur.execute(
            """SELECT ev.*, COALESCE(m.nombre, mc.nombre, 'Sin médico') AS medico
               FROM evoluciones ev
               LEFT JOIN medicos m ON m.id = ev.medico_id
               LEFT JOIN citas c ON c.id = ev.cita_id
               LEFT JOIN medicos mc ON mc.id = c.medico_id
               WHERE ev.expediente_id=? ORDER BY ev.creado_en DESC""",
            (exp["id"],),
        ).fetchall()
        recetas = cur.execute(
            "SELECT * FROM recetas WHERE expediente_id=? ORDER BY creado_en DESC",
            (exp["id"],),
        ).fetchall()
        paciente = cur.execute("SELECT * FROM pacientes WHERE id=?", (paciente_id,)).fetchone()
    registrar_auditoria("ver", "expediente", "expediente", exp["id"], f"paciente {paciente_id}")
    return jsonify({
        "expediente": exp,
        "paciente": dict(paciente) if paciente else {},
        "evoluciones": [dict(r) for r in evo],
        "recetas": [dict(r) for r in recetas],
    })


@expedientes_bp.route("/paciente/<int:paciente_id>", methods=["PUT"])
@roles_required("admin", "medico", "recepcionista")
def actualizar(paciente_id):
    data = request.get_json(force=True) or {}
    exp = _asegurar_expediente(paciente_id)
    with get_cursor(commit=True) as cur:
        cur.execute(
            """UPDATE expedientes SET tipo_sangre=?, alergias=?, antecedentes=?, actualizado_en=?
               WHERE id=?""",
            (data.get("tipo_sangre", exp["tipo_sangre"]),
             data.get("alergias", exp["alergias"]),
             data.get("antecedentes", exp["antecedentes"]),
             datetime.now().isoformat(), exp["id"]),
        )
    registrar_auditoria("editar", "expediente", "expediente", exp["id"])
    return jsonify({"mensaje": "Expediente actualizado"})


@expedientes_bp.route("/paciente/<int:paciente_id>/evolucion", methods=["POST"])
@roles_required("admin", "medico")
def agregar_evolucion(paciente_id):
    data = request.get_json(force=True) or {}
    nota = (data.get("nota") or "").strip()
    if not nota:
        return jsonify({"error": "La nota clínica es obligatoria"}), 400
    exp = _asegurar_expediente(paciente_id)
    medico_id = None
    with get_cursor() as cur:
        row = cur.execute("SELECT medico_id FROM usuarios WHERE id=?", (session["user_id"],)).fetchone()
        if row:
            medico_id = row["medico_id"]
    with get_cursor(commit=True) as cur:
        cur.execute(
            """INSERT INTO evoluciones (expediente_id, cita_id, medico_id, diagnostico, nota, creado_en)
               VALUES (?,?,?,?,?,?)""",
            (exp["id"], data.get("cita_id"), medico_id, data.get("diagnostico", ""), nota,
             datetime.now().isoformat()),
        )
        nid = cur.lastrowid
    registrar_auditoria("crear", "expediente", "evolucion", nid)
    return jsonify({"id": nid, "mensaje": "Evolución registrada"}), 201
