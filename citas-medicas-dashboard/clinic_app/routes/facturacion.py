"""Facturación, historial de pagos, seguros/copagos y pasarela simulada (Stripe-ready)."""

from datetime import datetime
import math
import uuid
from io import BytesIO

from flask import Blueprint, jsonify, request, send_file

from clinic_app.infrastructure.database import get_cursor
from clinic_app.routes.auth import login_required, roles_required
from clinic_app.services.auditoria import registrar_auditoria
from clinic_app.services.pdf_util import pdf_factura, pdf_texto

facturacion_bp = Blueprint("facturacion", __name__, url_prefix="/api")


@facturacion_bp.route("/facturas", methods=["GET"])
@login_required
def listar_facturas():
    paciente_id = request.args.get("paciente_id")
    saldo_pendiente = """ROUND(
        COALESCE(f.monto, 0) + COALESCE(f.impuestos, 0) - COALESCE(f.descuentos, 0)
        + COALESCE(f.copago, 0)
        - COALESCE((SELECT SUM(pg.monto) FROM pagos pg
                    WHERE pg.factura_id = f.id AND pg.estado = 'pagado'), 0),
        2
    ) AS saldo_pendiente"""
    with get_cursor() as cur:
        if cur._is_sql_server:
            if paciente_id:
                rows = cur.execute(
                    f"""SELECT TOP 100 f.*, p.nombre AS paciente, c.fecha AS fecha_cita,
                              {saldo_pendiente}
                       FROM facturas f
                       JOIN citas c ON c.id = f.cita_id
                       JOIN pacientes p ON p.id = c.paciente_id
                       WHERE c.paciente_id=?
                       ORDER BY COALESCE(f.fecha_pago, c.fecha) DESC""",
                    (paciente_id,),
                ).fetchall()
            else:
                rows = cur.execute(
                    f"""SELECT TOP 100 f.*, p.nombre AS paciente, c.fecha AS fecha_cita,
                              {saldo_pendiente}
                       FROM facturas f
                       JOIN citas c ON c.id = f.cita_id
                       JOIN pacientes p ON p.id = c.paciente_id
                       ORDER BY COALESCE(f.fecha_pago, c.fecha) DESC"""
                ).fetchall()
        else:
            if paciente_id:
                rows = cur.execute(
                    f"""SELECT f.*, p.nombre AS paciente, c.fecha AS fecha_cita,
                              {saldo_pendiente}
                       FROM facturas f
                       JOIN citas c ON c.id = f.cita_id
                       JOIN pacientes p ON p.id = c.paciente_id
                       WHERE c.paciente_id=?
                       ORDER BY COALESCE(f.fecha_pago, c.fecha) DESC LIMIT 100""",
                    (paciente_id,),
                ).fetchall()
            else:
                rows = cur.execute(
                    f"""SELECT f.*, p.nombre AS paciente, c.fecha AS fecha_cita,
                              {saldo_pendiente}
                       FROM facturas f
                       JOIN citas c ON c.id = f.cita_id
                       JOIN pacientes p ON p.id = c.paciente_id
                       ORDER BY COALESCE(f.fecha_pago, c.fecha) DESC LIMIT 100"""
                ).fetchall()
    return jsonify([dict(r) for r in rows])


@facturacion_bp.route("/facturas", methods=["POST"])
@roles_required("admin", "recepcionista")
def crear_factura():
    data = request.get_json(force=True) or {}
    cita_id = data.get("cita_id")
    monto = data.get("monto")
    if not cita_id or monto is None:
        return jsonify({"error": "cita_id y monto son obligatorios"}), 400

    try:
        cita_id = int(cita_id)
        monto_num = float(monto)
    except (TypeError, ValueError):
        return jsonify({"error": "La cita y el monto deben ser válidos"}), 400

    if not math.isfinite(monto_num):
        return jsonify({"error": "El monto debe ser mayor que cero"}), 400
    monto_num = round(monto_num, 2)
    if monto_num <= 0:
        return jsonify({"error": "El monto debe ser mayor que cero"}), 400

    try:
        impuestos = float(data.get("impuestos") or 0)
        descuentos = float(data.get("descuentos") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "Impuestos y descuentos deben ser cantidades válidas"}), 400
    if not math.isfinite(impuestos) or not math.isfinite(descuentos) or impuestos < 0 or descuentos < 0:
        return jsonify({"error": "Impuestos y descuentos no pueden ser negativos"}), 400
    impuestos = round(impuestos, 2)
    descuentos = round(descuentos, 2)
    if descuentos > monto_num + impuestos:
        return jsonify({"error": "El descuento no puede ser mayor que el subtotal"}), 400

    servicio = str(data.get("servicio") or "Consulta").strip()
    datos_fiscales = str(data.get("datos_fiscales") or "").strip()
    copago = 0
    with get_cursor() as cur:
        cita = cur.execute("SELECT paciente_id FROM citas WHERE id=?", (cita_id,)).fetchone()
        if not cita:
            return jsonify({"error": "Cita no encontrada"}), 404
        factura_existente = cur.execute(
            "SELECT id FROM facturas WHERE cita_id=?", (cita_id,)
        ).fetchone()
        if factura_existente:
            return jsonify({"error": "Esta cita ya tiene una factura"}), 409
        if cur._is_sql_server:
            seguro = cur.execute(
                "SELECT TOP 1 copago_pct FROM seguros WHERE paciente_id=? AND activo=1 ORDER BY id DESC",
                (cita["paciente_id"],),
            ).fetchone()
        else:
            seguro = cur.execute(
                "SELECT copago_pct FROM seguros WHERE paciente_id=? AND activo=1 LIMIT 1",
                (cita["paciente_id"],),
            ).fetchone()
        if seguro:
            copago = round(float(monto_num) * float(seguro["copago_pct"]) / 100, 2)
    with get_cursor(commit=True) as cur:
        cur.execute(
            """INSERT INTO facturas (cita_id, servicio, monto, impuestos, descuentos, datos_fiscales, copago, metodo_pago, pasarela, estado)
               VALUES (?,?,?,?,?,?,?,?,?, 'pendiente')""",
            (cita_id, servicio, monto_num, impuestos, descuentos, datos_fiscales,
             copago, data.get("metodo_pago", "pasarela"), data.get("pasarela", "simulada")),
        )
        if cur._is_sql_server:
            factura = cur.execute(
                "SELECT TOP 1 id FROM facturas WHERE cita_id=? ORDER BY id DESC",
                (cita_id,),
            ).fetchone()
        else:
            factura = cur.execute(
                "SELECT id FROM facturas WHERE cita_id=? ORDER BY id DESC LIMIT 1",
                (cita_id,),
            ).fetchone()
        fid = factura["id"] if factura else None
    registrar_auditoria("crear", "facturacion", "factura", fid)
    return jsonify({"id": fid, "copago": copago, "mensaje": "Factura generada"}), 201


@facturacion_bp.route("/facturas/<int:factura_id>/datos-fiscales", methods=["PATCH"])
@roles_required("admin", "recepcionista")
def actualizar_datos_fiscales(factura_id):
    data = request.get_json(silent=True) or {}
    datos_fiscales = str(data.get("datos_fiscales") or "").strip()
    if not datos_fiscales:
        return jsonify({"error": "Completa los datos fiscales antes de guardar."}), 400

    with get_cursor(commit=True) as cur:
        factura = cur.execute(
            "SELECT id FROM facturas WHERE id=?", (factura_id,)
        ).fetchone()
        if not factura:
            return jsonify({"error": "Factura no encontrada."}), 404
        cur.execute(
            "UPDATE facturas SET datos_fiscales=? WHERE id=?",
            (datos_fiscales, factura_id),
        )
    registrar_auditoria("actualizar", "facturacion", "datos_fiscales", factura_id)
    return jsonify({"success": True, "mensaje": "Datos fiscales guardados."})


@facturacion_bp.route("/facturas/<int:factura_id>/pdf", methods=["GET"])
@login_required
def factura_pdf(factura_id):
    with get_cursor() as cur:
        row = cur.execute(
            """SELECT f.*, c.fecha AS fecha_cita, c.hora AS hora_cita, p.nombre AS paciente,
                      m.nombre AS medico, e.nombre AS especialidad
               FROM facturas f
               JOIN citas c ON c.id = f.cita_id
               JOIN pacientes p ON p.id = c.paciente_id
               LEFT JOIN medicos m ON m.id = c.medico_id
               LEFT JOIN especialidades e ON e.id = c.especialidad_id
               WHERE f.id=?""",
            (factura_id,),
        ).fetchone()
    if not row:
        return jsonify({"error": "Factura no encontrada"}), 404

    pdf = pdf_factura(dict(row))
    registrar_auditoria("ver", "facturacion", "factura_pdf", factura_id)
    as_attachment = request.args.get("download") == "1"
    respuesta = send_file(
        BytesIO(pdf),
        mimetype="application/pdf",
        as_attachment=as_attachment,
        download_name=f"factura-SJ-{factura_id:06d}.pdf",
    )
    respuesta.headers["Cache-Control"] = "private, no-store, no-cache, max-age=0, must-revalidate"
    respuesta.headers["Pragma"] = "no-cache"
    return respuesta


@facturacion_bp.route("/pagos", methods=["GET"])
@login_required
def historial_pagos():
    with get_cursor() as cur:
        if cur._is_sql_server:
            rows = cur.execute(
                """SELECT TOP 80 pg.id, pg.factura_id, pg.metodo_pago, pg.monto, pg.moneda,
                          pg.pasarela, pg.referencia, pg.estado, pg.fecha_pago,
                          pg.creado_en, f.monto AS factura_monto,
                          p.nombre AS paciente
                   FROM pagos pg
                   JOIN facturas f ON f.id = pg.factura_id
                   JOIN citas c ON c.id = f.cita_id
                   JOIN pacientes p ON p.id = c.paciente_id
                   ORDER BY pg.creado_en DESC"""
            ).fetchall()
        else:
            rows = cur.execute(
                """SELECT pg.id, pg.factura_id, pg.metodo_pago, pg.monto, pg.moneda,
                          pg.pasarela, pg.referencia, pg.estado, pg.fecha_pago,
                          pg.creado_en, f.monto AS factura_monto,
                          p.nombre AS paciente
                   FROM pagos pg
                   JOIN facturas f ON f.id = pg.factura_id
                   JOIN citas c ON c.id = f.cita_id
                   JOIN pacientes p ON p.id = c.paciente_id
                   ORDER BY pg.creado_en DESC LIMIT 80"""
            ).fetchall()
    return jsonify([dict(r) for r in rows])


@facturacion_bp.route("/pagos/checkout", methods=["POST"])
@roles_required("admin", "recepcionista", "paciente")
def checkout():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "El cuerpo de la solicitud debe ser un objeto JSON"}), 400
    factura_id = data.get("factura_id")
    monto = data.get("monto")
    metodo_pago = str(data.get("metodo_pago") or "tarjeta").strip().lower()
    if metodo_pago not in {"efectivo", "tarjeta", "transferencia"}:
        return jsonify({"error": "Selecciona un método de pago válido"}), 400
    if not factura_id or monto is None:
        return jsonify({"error": "factura_id y monto son obligatorios"}), 400
    try:
        factura_id = int(factura_id)
        monto_num = float(monto)
    except (TypeError, ValueError):
        return jsonify({"error": "La factura y el monto deben ser válidos"}), 400
    if not math.isfinite(monto_num):
        return jsonify({"error": "El monto debe ser mayor que cero"}), 400
    monto_num = round(monto_num, 2)
    if monto_num <= 0:
        return jsonify({"error": "El monto debe ser mayor que cero"}), 400

    fecha_pago = str(data.get("fecha_pago") or datetime.now().date().isoformat())
    try:
        datetime.strptime(fecha_pago, "%Y-%m-%d")
    except ValueError:
        return jsonify({"error": "La fecha de pago debe tener formato AAAA-MM-DD"}), 400
    referencia = str(data.get("referencia") or "").strip() or f"sim_{uuid.uuid4().hex[:12]}"

    ahora = datetime.now().isoformat()
    with get_cursor(commit=True) as cur:
        fac = cur.execute("SELECT * FROM facturas WHERE id=?", (factura_id,)).fetchone()
        if not fac:
            return jsonify({"error": "Factura no encontrada"}), 404
        pagos_realizados = cur.execute(
            "SELECT COALESCE(SUM(monto), 0) AS total FROM pagos WHERE factura_id=? AND estado='pagado'",
            (factura_id,),
        ).fetchone()
        total_factura = (
            float(fac["monto"] or 0)
            + float(fac["impuestos"] or 0)
            - float(fac["descuentos"] or 0)
            + float(fac["copago"] or 0)
        )
        saldo = round(total_factura - float(pagos_realizados["total"] or 0), 2)
        if saldo <= 0:
            return jsonify({"error": "La factura ya está pagada"}), 409
        if monto_num > saldo:
            return jsonify({"error": f"El monto supera el saldo pendiente de Q {saldo:.2f}"}), 400

        cur.execute(
            """INSERT INTO pagos (factura_id, metodo_pago, monto, moneda, pasarela,
               referencia, estado, fecha_pago, creado_en)
               VALUES (?,?,?,?,?, ?, 'pagado', ?, ?)""",
            (factura_id, metodo_pago, monto_num, "Q", "simulada",
             referencia, fecha_pago, ahora),
        )
        pago_id = cur.lastrowid
        saldo_restante = round(saldo - monto_num, 2)
        pagada = saldo_restante <= 0
        cur.execute(
            """UPDATE facturas SET estado=?, metodo_pago=?, pasarela='simulada',
               referencia_pago=?, fecha_pago=? WHERE id=?""",
            (
                "pagada" if pagada else "pendiente",
                metodo_pago,
                referencia,
                fecha_pago if pagada else None,
                factura_id,
            ),
        )
    registrar_auditoria("crear", "facturacion", "pago", pago_id)
    return jsonify({
        "id": pago_id,
        "mensaje": "Pago procesado (pasarela simulada)",
        "referencia": referencia,
        "moneda": "Q",
        "saldo_pendiente": saldo_restante,
        "estado_factura": "pagada" if pagada else "pendiente",
    })


@facturacion_bp.route("/payments/stripe/webhook", methods=["POST"])
def stripe_webhook():
    """Punto de integración Stripe: en demo se registra el evento recibido."""
    payload = request.get_json(silent=True) or {}
    registrar_auditoria("webhook", "facturacion", "stripe", None, str(payload)[:300])
    return jsonify({"received": True})


@facturacion_bp.route("/seguros", methods=["GET"])
@login_required
def listar_seguros():
    with get_cursor() as cur:
        if cur._is_sql_server:
            rows = cur.execute(
                """SELECT TOP 100 s.*, p.nombre AS paciente
                   FROM seguros s
                   JOIN pacientes p ON p.id = s.paciente_id
                   ORDER BY p.nombre"""
            ).fetchall()
        else:
            rows = cur.execute(
                """SELECT s.*, p.nombre AS paciente FROM seguros s
                   JOIN pacientes p ON p.id = s.paciente_id ORDER BY p.nombre"""
            ).fetchall()
    return jsonify([dict(r) for r in rows])


@facturacion_bp.route("/seguros", methods=["POST"])
@roles_required("admin", "recepcionista")
def crear_seguro():
    data = request.get_json(force=True) or {}
    if not data.get("paciente_id") or not data.get("aseguradora") or not data.get("poliza"):
        return jsonify({"error": "paciente_id, aseguradora y poliza son obligatorios"}), 400
    with get_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO seguros (paciente_id, aseguradora, poliza, copago_pct, activo) VALUES (?,?,?,?,1)",
            (data["paciente_id"], data["aseguradora"], data["poliza"], data.get("copago_pct", 20)),
        )
        sid = cur.lastrowid
    return jsonify({"id": sid}), 201
