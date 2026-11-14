"""Reportes analíticos y exportación PDF/CSV (Excel)."""

import csv
from datetime import date, datetime, timedelta
from io import BytesIO, StringIO

from flask import Blueprint, Response, jsonify, request, send_file

from clinic_app.infrastructure.database import get_cursor
from clinic_app.routes.auth import login_required, roles_required
from clinic_app.services.pdf_util import pdf_tabla, pdf_texto

reportes_bp = Blueprint("reportes", __name__, url_prefix="/api/reportes")


@reportes_bp.route("/listado.pdf", methods=["POST"])
@login_required
def exportar_listado_pdf():
    data = request.get_json(silent=True) or {}
    titulo = str(data.get("titulo") or "Listado")[:80]
    columnas = data.get("columnas")
    filas = data.get("filas")
    if not isinstance(columnas, list) or not isinstance(filas, list):
        return jsonify({"error": "El listado no tiene un formato válido."}), 400
    if not columnas or len(columnas) > 20 or len(filas) > 500:
        return jsonify({"error": "El PDF admite hasta 20 columnas y 500 filas por descarga."}), 400
    if not all(isinstance(fila, list) and len(fila) == len(columnas) for fila in filas):
        return jsonify({"error": "Las filas del listado no coinciden con sus columnas."}), 400
    encabezados = [str(columna)[:80] for columna in columnas]
    registros = [[str(valor or "").replace("\n", " ")[:300] for valor in fila] for fila in filas]
    pdf = pdf_tabla(
        f"Reporte de {titulo}", encabezados, registros,
        f"{len(filas)} registros · Generado {datetime.now().strftime('%d/%m/%Y, %H:%M')} · Administración Clínica San José",
    )
    return send_file(
        BytesIO(pdf), mimetype="application/pdf", as_attachment=True,
        download_name="listado-clinica.pdf",
    )


def _periodo_y_filtros(alias="c"):
    try:
        dias = max(1, min(365, int(request.args.get("dias", 30))))
    except ValueError as exc:
        raise ValueError("El periodo debe estar entre 1 y 365 días") from exc
    hasta = date.today()
    desde = hasta - timedelta(days=dias - 1)
    condiciones = [f"{alias}.fecha BETWEEN ? AND ?"]
    parametros = [desde.isoformat(), hasta.isoformat()]

    for parametro, columna in (("especialidad_id", "especialidad_id"), ("medico_id", "medico_id")):
        valor = request.args.get(parametro, "").strip()
        if valor:
            if not valor.isdigit() or int(valor) < 1:
                raise ValueError(f"El filtro {parametro} no es válido")
            condiciones.append(f"{alias}.{columna} = ?")
            parametros.append(int(valor))
    return dias, desde.isoformat(), hasta.isoformat(), condiciones, parametros


@reportes_bp.route("/notificaciones")
@login_required
def notificaciones():
    with get_cursor() as cur:
        paginacion = "OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY" if cur._is_sql_server else "LIMIT ?"
        rows = cur.execute(
            f"""SELECT n.*, p.nombre AS paciente
               FROM notificaciones n
               LEFT JOIN pacientes p ON p.id = n.paciente_id
               ORDER BY n.creado_en DESC {paginacion}""",
            (80,),
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@reportes_bp.route("/citas-por-especialidad")
@login_required
def citas_por_especialidad():
    try:
        _, desde, hasta, _, _ = _periodo_y_filtros("c")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    join_conditions = ["c.especialidad_id = e.id", "c.fecha BETWEEN ? AND ?"]
    join_params = [desde, hasta]
    where_conditions, where_params = [], []
    if "medico_id" in request.args:
        join_conditions.append("c.medico_id = ?")
        join_params.append(int(request.args["medico_id"]))
    if "especialidad_id" in request.args:
        where_conditions.append("e.id = ?")
        where_params.append(int(request.args["especialidad_id"]))
    where = f"WHERE {' AND '.join(where_conditions)}" if where_conditions else ""
    with get_cursor() as cur:
        rows = cur.execute(
            f"""SELECT e.id AS especialidad_id, e.nombre AS especialidad, COUNT(c.id) AS total
               FROM especialidades e
               LEFT JOIN citas c ON {' AND '.join(join_conditions)}
               {where}
               GROUP BY e.id, e.nombre
               ORDER BY total DESC, e.nombre""",
            (*join_params, *where_params),
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@reportes_bp.route("/citas-por-medico")
@login_required
def citas_por_medico():
    try:
        _, desde, hasta, _, _ = _periodo_y_filtros("c")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    join_conditions = ["c.medico_id = m.id", "c.fecha BETWEEN ? AND ?"]
    join_params = [desde, hasta]
    where_conditions, where_params = [], []
    if "especialidad_id" in request.args:
        join_conditions.append("c.especialidad_id = ?")
        join_params.append(int(request.args["especialidad_id"]))
    if "medico_id" in request.args:
        where_conditions.append("m.id = ?")
        where_params.append(int(request.args["medico_id"]))
    where = f"WHERE {' AND '.join(where_conditions)}" if where_conditions else ""
    with get_cursor() as cur:
        rows = cur.execute(
            f"""SELECT m.id AS medico_id, m.nombre AS medico, e.nombre AS especialidad,
                      COUNT(c.id) AS total
               FROM medicos m
               JOIN especialidades e ON e.id = m.especialidad_id
               LEFT JOIN citas c ON {' AND '.join(join_conditions)}
               {where}
               GROUP BY m.id, m.nombre, e.nombre
               ORDER BY total DESC, m.nombre""",
            (*join_params, *where_params),
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@reportes_bp.route("/citas-por-periodo")
@login_required
def citas_por_periodo():
    try:
        _, _, _, condiciones, parametros = _periodo_y_filtros("c")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    with get_cursor() as cur:
        rows = cur.execute(
            f"""SELECT c.fecha AS periodo, COUNT(*) AS total,
                      SUM(CASE WHEN c.estado='completada' THEN 1 ELSE 0 END) AS completadas,
                      SUM(CASE WHEN c.estado='no_asistio' THEN 1 ELSE 0 END) AS inasistencias,
                      SUM(CASE WHEN c.estado='cancelada' THEN 1 ELSE 0 END) AS canceladas
               FROM citas c
               WHERE {' AND '.join(condiciones)}
               GROUP BY c.fecha
               ORDER BY periodo DESC""",
            parametros,
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@reportes_bp.route("/financieros")
@login_required
def financieros():
    try:
        dias, desde, hasta, condiciones, parametros = _periodo_y_filtros("c")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    filtros = " AND ".join(condiciones[1:])
    where_filtros = f"AND {filtros}" if filtros else ""
    with get_cursor() as cur:
        resumen = cur.execute(
            f"""SELECT
                   COALESCE(SUM(CASE WHEN f.estado='pagada' AND f.fecha_pago BETWEEN ? AND ? THEN f.monto ELSE 0 END),0) AS ingresos,
                   COALESCE(SUM(CASE WHEN f.estado='pendiente' THEN f.monto ELSE 0 END),0) AS pendientes,
                   SUM(CASE WHEN f.estado='pagada' AND f.fecha_pago BETWEEN ? AND ? THEN 1 ELSE 0 END) AS facturas_pagadas
               FROM facturas f JOIN citas c ON c.id=f.cita_id
               WHERE 1=1 {where_filtros}""",
            (desde, hasta, desde, hasta, *parametros[2:]),
        ).fetchone()
    return jsonify({
        "ingresos": round(float(resumen["ingresos"] or 0), 2),
        "pendientes": round(float(resumen["pendientes"] or 0), 2),
        "facturas_pagadas": resumen["facturas_pagadas"] or 0,
        "moneda": "Q",
        "periodo_dias": dias,
    })


@reportes_bp.route("/salas")
@login_required
def uso_salas_recursos():
    with get_cursor() as cur:
        paginacion = "OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY" if cur._is_sql_server else "LIMIT ?"
        rows = cur.execute(
            f"""SELECT c.fecha, c.hora, p.nombre AS paciente,
                      m.nombre AS medico, t.sala_codigo AS sala,
                      t.estado AS estado_sala,
                      COALESCE(t.documentos_compartidos, 'Sin documentos') AS documentos
               FROM teleconsultas t
               JOIN citas c ON c.id = t.cita_id
               JOIN pacientes p ON p.id = c.paciente_id
               JOIN medicos m ON m.id = c.medico_id
               ORDER BY c.fecha DESC, c.hora DESC
                    {paginacion}""",
                (80,),
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@reportes_bp.route("/auditoria")
@roles_required("admin", "auditor")
def auditoria_list():
    try:
        where, params = _filtros_auditoria()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    pagina = max(1, request.args.get("pagina", default=1, type=int))
    por_pagina = min(50, max(1, request.args.get("por_pagina", default=10, type=int)))
    total, rows = _consultar_auditoria(where, params, por_pagina, (pagina - 1) * por_pagina)
    paginas = max(1, (total + por_pagina - 1) // por_pagina)
    return jsonify({
        "items": [dict(row) for row in rows],
        "pagina": pagina,
        "paginas": paginas,
        "por_pagina": por_pagina,
        "total": total,
    })


@reportes_bp.route("/auditoria/opciones")
@roles_required("admin", "auditor")
def auditoria_opciones():
    with get_cursor() as cur:
        usuarios = cur.execute(
            "SELECT DISTINCT usuario_email FROM auditoria WHERE usuario_email IS NOT NULL AND usuario_email<>'' ORDER BY usuario_email"
        ).fetchall()
        modulos = cur.execute(
            "SELECT DISTINCT modulo FROM auditoria WHERE modulo IS NOT NULL AND modulo<>'' ORDER BY modulo"
        ).fetchall()
        acciones = cur.execute(
            "SELECT DISTINCT accion FROM auditoria WHERE accion IS NOT NULL AND accion<>'' ORDER BY accion"
        ).fetchall()
    return jsonify({
        "usuarios": [row[0] for row in usuarios],
        "modulos": [row[0] for row in modulos],
        "acciones": [row[0] for row in acciones],
    })


@reportes_bp.route("/auditoria/exportar.pdf")
@roles_required("admin", "auditor")
def auditoria_pdf():
    try:
        where, params = _filtros_auditoria()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    _, rows = _consultar_auditoria(where, params, 35, 0)
    lineas = []
    for row in rows:
        lineas.extend([
            f"{row['creado_en']} | {row['usuario_email'] or 'Sistema'} | {row['modulo']} | {row['accion']}",
            f"Registro: {row['recurso'] or ''} {row['recurso_id'] or ''} | IP: {row['ip'] or '—'}",
            f"Detalle: {row['detalle'] or '—'}",
            "",
        ])
    pdf = pdf_texto("Actividad de auditoria", lineas or ["No hay registros para los filtros seleccionados."])
    return send_file(
        BytesIO(pdf), mimetype="application/pdf", as_attachment=True,
        download_name="auditoria-clinica.pdf",
    )


def _filtros_auditoria():
    condiciones, params = [], []
    for parametro, columna in (("usuario", "usuario_email"), ("modulo", "modulo"), ("accion", "accion")):
        valor = request.args.get(parametro, "").strip()
        if valor:
            condiciones.append(f"{columna} = ?")
            params.append(valor)

    desde = request.args.get("desde", "").strip()
    hasta = request.args.get("hasta", "").strip()
    if desde:
        try:
            desde = datetime.strptime(desde, "%Y-%m-%d").date().isoformat()
        except ValueError as exc:
            raise ValueError("La fecha inicial no es válida") from exc
        condiciones.append("creado_en >= ?")
        params.append(desde)
    if hasta:
        try:
            limite_superior = datetime.strptime(hasta, "%Y-%m-%d").date() + timedelta(days=1)
        except ValueError as exc:
            raise ValueError("La fecha final no es válida") from exc
        condiciones.append("creado_en < ?")
        params.append(limite_superior.isoformat())

    where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
    return where, params


def _consultar_auditoria(where, params, limite, desplazamiento):
    with get_cursor() as cur:
        total = cur.execute(
            f"SELECT COUNT(*) AS total FROM auditoria {where}", params
        ).fetchone()["total"]
        if cur._is_sql_server:
            sql = f"SELECT * FROM auditoria {where} ORDER BY id DESC OFFSET ? ROWS FETCH NEXT ? ROWS ONLY"
            filas = cur.execute(sql, (*params, desplazamiento, limite)).fetchall()
        else:
            sql = f"SELECT * FROM auditoria {where} ORDER BY id DESC LIMIT ? OFFSET ?"
            filas = cur.execute(sql, (*params, limite, desplazamiento)).fetchall()
    return total, filas


@reportes_bp.route("/exportar.csv")
@login_required
def exportar_csv():
    try:
        _, _, _, condiciones, parametros = _periodo_y_filtros("c")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["paciente", "medico", "especialidad", "fecha", "hora", "estado", "modalidad"])
    with get_cursor() as cur:
        rows = cur.execute(
            f"""SELECT p.nombre, m.nombre, e.nombre, c.fecha, c.hora, c.estado, c.modalidad
               FROM citas c
               JOIN pacientes p ON p.id=c.paciente_id
               JOIN medicos m ON m.id=c.medico_id
               JOIN especialidades e ON e.id=c.especialidad_id
               WHERE {' AND '.join(condiciones)}
               ORDER BY c.fecha DESC, c.hora DESC""",
            parametros,
        ).fetchall()
    for r in rows:
        writer.writerow(list(r))
    data = "\ufeff" + output.getvalue()
    return Response(
        data.encode("utf-8"),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=reporte-citas.csv"},
    )


@reportes_bp.route("/exportar.pdf")
@login_required
def exportar_pdf():
    try:
        dias, desde, hasta, condiciones, parametros = _periodo_y_filtros("c")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    where = " AND ".join(condiciones)
    parametros_dimensiones = parametros[2:]
    with get_cursor() as cur:
        kpis = cur.execute(
            f"""SELECT COUNT(*) AS citas,
                      SUM(CASE WHEN c.estado='completada' THEN 1 ELSE 0 END) AS atendidas,
                      SUM(CASE WHEN c.estado='no_asistio' THEN 1 ELSE 0 END) AS inasistencias
               FROM citas c WHERE {where}""",
            parametros,
        ).fetchone()
        ingresos = cur.execute(
            f"""SELECT COALESCE(SUM(f.monto),0) AS total
               FROM facturas f JOIN citas c ON c.id=f.cita_id
               WHERE f.fecha_pago BETWEEN ? AND ? AND f.estado='pagada'
               {'AND ' + ' AND '.join(condiciones[1:]) if condiciones[1:] else ''}""",
            (desde, hasta, *parametros_dimensiones),
        ).fetchone()["total"]
        join_conditions = ["c.especialidad_id=e.id", "c.fecha BETWEEN ? AND ?"]
        join_params = [desde, hasta]
        where_specialty = ""
        if "medico_id" in request.args:
            join_conditions.append("c.medico_id=?")
            join_params.append(int(request.args["medico_id"]))
        if "especialidad_id" in request.args:
            where_specialty = "WHERE e.id=?"
            join_params.append(int(request.args["especialidad_id"]))
        top = cur.execute(
            f"""SELECT e.nombre, COUNT(c.id) AS total FROM especialidades e
               LEFT JOIN citas c ON {' AND '.join(join_conditions)}
               {where_specialty}
               GROUP BY e.id, e.nombre ORDER BY total DESC""",
            join_params,
        ).fetchall()
    lineas = [
        f"Periodo: {desde} a {hasta} ({dias} dias)",
        f"Citas: {kpis['citas']}",
        f"Citas atendidas: {kpis['atendidas'] or 0}",
        f"Inasistencias: {kpis['inasistencias'] or 0}",
        f"Ingresos: Q {ingresos}",
        "",
        "Citas por especialidad:",
    ]
    for r in top:
        lineas.append(f"  - {r['nombre']}: {r['total']}")
    pdf = pdf_texto("Reporte analitico", lineas)
    return send_file(BytesIO(pdf), mimetype="application/pdf", as_attachment=True,
                     download_name="reporte-clinica.pdf")
