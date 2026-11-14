"""
catalogos.py
Endpoints de solo lectura (y alta simple de pacientes) que alimentan los
formularios del frontend: selects de pacientes, médicos y especialidades.
"""

import re
from datetime import datetime

from flask import Blueprint, jsonify, request

from clinic_app.infrastructure.database import get_cursor
from clinic_app.routes.auth import login_required, roles_required

catalogos_bp = Blueprint("catalogos", __name__, url_prefix="/api")


@catalogos_bp.route("/pacientes", methods=["GET"])
@login_required
def listar_pacientes():
    busqueda = request.args.get("q", "").strip()
    with get_cursor() as cur:
        if busqueda:
            rows = cur.execute(
                """SELECT id, nombre, dpi, email, telefono, fecha_nacimiento, sexo, fecha_registro
                   FROM pacientes WHERE nombre LIKE ? OR dpi LIKE ?
                   ORDER BY fecha_registro DESC, id DESC""",
                (f"%{busqueda}%", f"%{busqueda}%"),
            ).fetchall()
        else:
            rows = cur.execute(
                "SELECT id, nombre, dpi, email, telefono, fecha_nacimiento, sexo, fecha_registro FROM pacientes ORDER BY fecha_registro DESC, id DESC"
            ).fetchall()
    return jsonify([dict(r) for r in rows])


@catalogos_bp.route("/pacientes", methods=["POST"])
@roles_required("admin", "recepcionista")
def crear_paciente():
    data = request.get_json(force=True) or {}
    nombre = (data.get("nombre") or "").strip()
    dpi = (data.get("dpi") or "").strip()
    if not nombre:
        return jsonify({"error": "El nombre es obligatorio"}), 400
    if dpi and not re.fullmatch(r"[A-Za-z0-9]+", dpi):
        return jsonify({"error": "El DPI solo puede contener letras y números"}), 400

    with get_cursor(commit=True) as cur:
        cur.execute(
            """INSERT INTO pacientes (nombre, dpi, email, telefono, fecha_nacimiento, sexo, fecha_registro)
               VALUES (?,?,?,?,?,?,?)""",
            (nombre, dpi or None, data.get("email", ""), data.get("telefono", ""),
             data.get("fecha_nacimiento"), data.get("sexo"),
             datetime.now().date().isoformat()),
        )
        nuevo_id = cur.lastrowid

    return jsonify({"id": nuevo_id, "nombre": nombre}), 201


@catalogos_bp.route("/pacientes/<int:paciente_id>", methods=["PATCH"])
@roles_required("admin", "recepcionista")
def actualizar_paciente(paciente_id):
    data = request.get_json(silent=True) or {}
    campos_permitidos = {"nombre", "dpi", "email", "telefono"}
    cambios = {}
    for campo in campos_permitidos.intersection(data):
        valor = str(data.get(campo) or "").strip()
        if campo == "nombre" and not valor:
            return jsonify({"error": "El nombre no puede quedar vacío."}), 400
        if campo == "dpi" and valor and not re.fullmatch(r"[A-Za-z0-9]+", valor):
            return jsonify({"error": "El DPI solo puede contener letras y números."}), 400
        if campo == "email" and valor and ("@" not in valor or "." not in valor.rsplit("@", 1)[-1]):
            return jsonify({"error": "Ingresa un correo electrónico válido."}), 400
        cambios[campo] = valor or None

    if not cambios:
        return jsonify({"error": "No hay datos para actualizar."}), 400

    with get_cursor(commit=True) as cur:
        paciente = cur.execute(
            "SELECT id FROM pacientes WHERE id=?", (paciente_id,)
        ).fetchone()
        if not paciente:
            return jsonify({"error": "Paciente no encontrado."}), 404
        asignaciones = ", ".join(f"{campo}=?" for campo in cambios)
        cur.execute(
            f"UPDATE pacientes SET {asignaciones} WHERE id=?",
            (*cambios.values(), paciente_id),
        )
    return jsonify({"success": True, "mensaje": "Datos del paciente actualizados."})


@catalogos_bp.route("/medicos", methods=["GET"])
@login_required
def listar_medicos():
    with get_cursor() as cur:
        rows = cur.execute(
            """SELECT m.id, m.nombre, m.cedula, m.colegiado, m.horario, m.sucursal,
                      e.id AS especialidad_id, COALESCE(e.nombre, 'Sin especialidad') AS especialidad,
                      e.color
               FROM medicos m LEFT JOIN especialidades e ON e.id = m.especialidad_id
               WHERE m.activo = 1
               ORDER BY m.nombre"""
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@catalogos_bp.route("/medicos", methods=["POST"])
@roles_required("admin", "recepcionista")
def crear_medico():
    data = request.get_json(force=True) or {}
    nombre = (data.get("nombre") or "").strip()
    cedula = (data.get("cedula") or "").strip()
    try:
        especialidad_id = int(data.get("especialidad_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "Selecciona una especialidad válida."}), 400
    colegiado = (data.get("colegiado") or "").strip()
    horario = (data.get("horario") or "").strip()
    sucursal = (data.get("sucursal") or "").strip()

    if not nombre or not cedula or especialidad_id < 1:
        return jsonify({"error": "Nombre, cédula y especialidad son obligatorios"}), 400

    with get_cursor() as cur:
        especialidad = cur.execute(
            "SELECT id FROM especialidades WHERE id=?", (especialidad_id,)
        ).fetchone()
        if not especialidad:
            return jsonify({"error": "La especialidad seleccionada no existe."}), 400
        existe = cur.execute("SELECT id FROM medicos WHERE cedula=?", (cedula,)).fetchone()
        if existe:
            return jsonify({"error": "La cédula ya está registrada"}), 409

    with get_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO medicos (nombre, cedula, colegiado, horario, sucursal, especialidad_id, activo) VALUES (?, ?, ?, ?, ?, ?, 1)",
            (nombre, cedula, colegiado, horario, sucursal, especialidad_id),
        )
        nuevo_id = cur.lastrowid

    return jsonify({"id": nuevo_id, "nombre": nombre}), 201


@catalogos_bp.route("/medicos/<int:medico_id>", methods=["PATCH"])
@roles_required("admin", "recepcionista")
def actualizar_especialidad_medico(medico_id):
    data = request.get_json(silent=True) or {}
    cambios = {}
    if "especialidad_id" in data:
        try:
            especialidad_id = int(data.get("especialidad_id"))
        except (TypeError, ValueError):
            return jsonify({"error": "Selecciona una especialidad válida."}), 400
        with get_cursor() as cur:
            especialidad = cur.execute(
                "SELECT id FROM especialidades WHERE id=?", (especialidad_id,)
            ).fetchone()
        if not especialidad:
            return jsonify({"error": "La especialidad seleccionada no existe."}), 400
        cambios["especialidad_id"] = especialidad_id

    for campo in ("colegiado", "horario", "sucursal"):
        if campo in data:
            cambios[campo] = str(data.get(campo) or "").strip() or None
    if not cambios:
        return jsonify({"error": "No hay datos para actualizar."}), 400

    with get_cursor() as cur:
        medico = cur.execute(
            "SELECT id FROM medicos WHERE id=? AND activo=1", (medico_id,)
        ).fetchone()
        if not medico:
            return jsonify({"error": "Médico no encontrado o inactivo."}), 404

    with get_cursor(commit=True) as cur:
        asignaciones = ", ".join(f"{campo}=?" for campo in cambios)
        cur.execute(
            f"UPDATE medicos SET {asignaciones} WHERE id=?",
            (*cambios.values(), medico_id),
        )

    return jsonify({"success": True, "mensaje": "Datos del médico actualizados."})


@catalogos_bp.route("/especialidades", methods=["GET"])
@login_required
def listar_especialidades():
    with get_cursor() as cur:
        rows = cur.execute(
            """SELECT e.id, e.nombre, e.descripcion, e.color, e.duracion_min, e.tarifa_base,
                      COUNT(m.id) AS medicos
               FROM especialidades e
               LEFT JOIN medicos m ON m.especialidad_id = e.id AND m.activo = 1
               GROUP BY e.id, e.nombre, e.descripcion, e.color, e.duracion_min, e.tarifa_base
               ORDER BY e.nombre"""
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@catalogos_bp.route("/especialidades", methods=["POST"])
@roles_required("admin")
def crear_especialidad():
    data = request.get_json(force=True) or {}
    nombre = (data.get("nombre") or "").strip()
    descripcion = (data.get("descripcion") or "").strip()
    if not nombre:
        return jsonify({"error": "El nombre es obligatorio"}), 400
    with get_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO especialidades (nombre, descripcion, color, duracion_min, tarifa_base) VALUES (?,?,?,?,?)",
            (nombre, descripcion, data.get("color", "#0d6bb6"), int(data.get("duracion_min") or 30),
             float(data.get("tarifa_base") or 25000)),
        )
        nid = cur.lastrowid
    return jsonify({"id": nid, "nombre": nombre}), 201
