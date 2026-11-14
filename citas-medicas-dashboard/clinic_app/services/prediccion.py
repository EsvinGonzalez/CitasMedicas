"""
Predicción de inasistencia (no-show) con regresión logística entrenada
sobre el historial local: tasa del paciente, día/hora y especialidad.
"""

from datetime import datetime

from clinic_app.infrastructure.database import get_cursor


UMBRAL = 0.35
_modelo = None


def _sigmoid(z):
    if z < -30:
        return 0.0
    if z > 30:
        return 1.0
    import math
    return 1.0 / (1.0 + math.exp(-z))


def _features(historial_pac, dia_semana, hora_num, tasa_esp):
    return [
        1.0,
        historial_pac,
        1.0 if dia_semana >= 5 else 0.0,
        1.0 if hora_num >= 16 else 0.0,
        tasa_esp,
    ]


def _entrenar():
    global _modelo
    with get_cursor() as cur:
        rows = cur.execute(
            """SELECT c.paciente_id, c.especialidad_id, c.fecha, c.hora, c.estado
               FROM citas c
               WHERE c.estado IN ('completada','no_asistio')"""
        ).fetchall()

    if len(rows) < 20:
        _modelo = {"w": [ -1.2, 2.4, 0.35, 0.25, 1.1 ]}
        return _modelo

    from collections import defaultdict
    hist = defaultdict(lambda: [0, 0])
    esp = defaultdict(lambda: [0, 0])
    for r in rows:
        hist[r["paciente_id"]][1] += 1
        esp[r["especialidad_id"]][1] += 1
        if r["estado"] == "no_asistio":
            hist[r["paciente_id"]][0] += 1
            esp[r["especialidad_id"]][0] += 1

    X, y = [], []
    for r in rows:
        hp = hist[r["paciente_id"]][0] / hist[r["paciente_id"]][1]
        te = esp[r["especialidad_id"]][0] / esp[r["especialidad_id"]][1]
        dt = datetime.strptime(r["fecha"], "%Y-%m-%d")
        hora = int(str(r["hora"])[:2])
        X.append(_features(hp, dt.weekday(), hora, te))
        y.append(1.0 if r["estado"] == "no_asistio" else 0.0)

    w = [0.0] * 5
    lr = 0.08
    for _ in range(250):
        grads = [0.0] * 5
        for xi, yi in zip(X, y):
            z = sum(wi * xii for wi, xii in zip(w, xi))
            p = _sigmoid(z)
            err = p - yi
            for j in range(5):
                grads[j] += err * xi[j]
        n = len(X)
        w = [wi - lr * g / n for wi, g in zip(w, grads)]
    _modelo = {"w": w}
    return _modelo


def predecir_inasistencia(paciente_id, especialidad_id, fecha, hora):
    modelo = _modelo or _entrenar()
    with get_cursor() as cur:
        tot = cur.execute(
            "SELECT COUNT(*) FROM citas WHERE paciente_id=? AND estado IN ('completada','no_asistio')",
            (paciente_id,),
        ).fetchone()[0]
        nos = cur.execute(
            "SELECT COUNT(*) FROM citas WHERE paciente_id=? AND estado='no_asistio'",
            (paciente_id,),
        ).fetchone()[0]
        et = cur.execute(
            "SELECT COUNT(*) FROM citas WHERE especialidad_id=? AND estado IN ('completada','no_asistio')",
            (especialidad_id,),
        ).fetchone()[0]
        en = cur.execute(
            "SELECT COUNT(*) FROM citas WHERE especialidad_id=? AND estado='no_asistio'",
            (especialidad_id,),
        ).fetchone()[0]
    hp = (nos / tot) if tot else 0.12
    te = (en / et) if et else 0.12
    dt = datetime.strptime(fecha, "%Y-%m-%d")
    hora_num = int(str(hora)[:2])
    x = _features(hp, dt.weekday(), hora_num, te)
    z = sum(wi * xii for wi, xii in zip(modelo["w"], x))
    return round(_sigmoid(z), 4)


def guardar_prediccion(cita_id, probabilidad):
    reforzado = 1 if probabilidad >= UMBRAL else 0
    with get_cursor(commit=True) as cur:
        cur.execute(
            """INSERT INTO predicciones_noshow
               (cita_id, probabilidad, umbral, recordatorio_reforzado, creado_en)
               VALUES (?,?,?,?,?)""",
            (cita_id, probabilidad, UMBRAL, reforzado, datetime.now().isoformat()),
        )
        cur.execute("UPDATE citas SET riesgo_noshow=? WHERE id=?", (probabilidad, cita_id))
    return reforzado == 1
