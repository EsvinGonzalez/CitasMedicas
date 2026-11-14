"""
seed_data.py
Genera datos de ejemplo realistas para demostrar el dashboard:
especialidades, médicos, pacientes, citas (últimos 90 días) y facturas.

Ejecutar una sola vez:
    python seed_data.py
Vuelve a crear la base de datos desde cero cada vez que se ejecuta.
"""

import random
from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

from clinic_app.infrastructure.database import DB_PATH, get_cursor, init_db

random.seed(42)

ESPECIALIDADES = [
    ("Medicina General", "#0F6B5C", 20, 18000),
    ("Pediatría",        "#2E86AB", 25, 22000),
    ("Ginecología",      "#B8433C", 30, 28000),
    ("Cardiología",      "#C9A227", 30, 35000),
    ("Dermatología",     "#6B4C9A", 20, 24000),
    ("Odontología",      "#3E7C4A", 30, 20000),
    ("Traumatología",    "#A85A2E", 30, 30000),
    ("Psicología",       "#4A6FA5", 45, 26000),
]

NOMBRES = ["María", "José", "Ana", "Luis", "Carmen", "Carlos", "Laura", "Miguel",
           "Sofía", "Jorge", "Valentina", "Andrés", "Camila", "Diego", "Paula",
           "Fernando", "Isabella", "Ricardo", "Daniela", "Javier", "Lucía", "Pedro",
           "Gabriela", "Mateo", "Elena", "Roberto", "Natalia", "Sergio", "Adriana"]
APELLIDOS = ["García", "Rodríguez", "Martínez", "López", "Hernández", "González",
             "Pérez", "Sánchez", "Ramírez", "Torres", "Flores", "Rivera", "Gómez",
             "Díaz", "Reyes", "Morales", "Vargas", "Castro", "Ortiz", "Jiménez"]

ESTADOS_PASADO = ["completada"] * 72 + ["no_asistio"] * 13 + ["cancelada"] * 15
ESTADOS_FUTURO = ["confirmada"]
METODOS_PAGO = ["tarjeta"] * 5 + ["efectivo"] * 3 + ["seguro"] * 2
MOTIVOS = ["Consulta de control", "Primera consulta", "Seguimiento", "Chequeo anual",
           "Consulta por síntomas", "Renovación de receta", "Resultados de laboratorio"]


def nombre_aleatorio():
    return f"{random.choice(NOMBRES)} {random.choice(APELLIDOS)} {random.choice(APELLIDOS)}"


def seed():
    init_db()

    with get_cursor(commit=True) as cur:
        # --- Especialidades ---
        # init_db() already inserts some; IGNORE avoids UNIQUE collisions.
        for nombre, color, dur, tarifa in ESPECIALIDADES:
            cur.execute(
                "INSERT OR IGNORE INTO especialidades (nombre, color, duracion_min, tarifa_base) "
                "VALUES (?,?,?,?)",
                (nombre, color, dur, tarifa),
            )
        especialidad_ids = [row[0] for row in cur.execute("SELECT id FROM especialidades").fetchall()]

        # --- Médicos (1-3 por especialidad) ---
        medico_ids_por_especialidad = {eid: [] for eid in especialidad_ids}
        for eid in especialidad_ids:
            for _ in range(random.randint(2, 3)):
                nombre = f"Dr. {nombre_aleatorio()}"
                cedula = f"MED-{random.randint(10000,99999)}"
                cur.execute(
                    "INSERT INTO medicos (nombre, cedula, especialidad_id, activo) VALUES (?,?,?,1)",
                    (nombre, cedula, eid),
                )
                medico_ids_por_especialidad[eid].append(cur.lastrowid)

        # --- Pacientes ---
        paciente_ids = []
        hoy = datetime.now()
        for _ in range(160):
            nombre = nombre_aleatorio()
            email = nombre.lower().replace(" ", ".") + "@correo.com"
            telefono = f"9{random.randint(1000,9999)}-{random.randint(1000,9999)}"
            fecha_registro = (hoy - timedelta(days=random.randint(0, 400))).strftime("%Y-%m-%d")
            cur.execute(
                "INSERT INTO pacientes (nombre, email, telefono, fecha_registro) VALUES (?,?,?,?)",
                (nombre, email, telefono, fecha_registro),
            )
            paciente_ids.append(cur.lastrowid)

        # --- Citas: últimos 90 días + próximos 10 días ---
        citas_creadas = []
        for offset in range(-90, 11):
            fecha_dia = hoy + timedelta(days=offset)
            # Menos citas los domingos, más entre semana
            dia_semana = fecha_dia.weekday()  # 0=lunes ... 6=domingo
            if dia_semana == 6:
                n_citas = random.randint(0, 3)
            elif dia_semana == 5:
                n_citas = random.randint(3, 8)
            else:
                n_citas = random.randint(8, 16)

            for _ in range(n_citas):
                eid = random.choice(especialidad_ids)
                medico_id = random.choice(medico_ids_por_especialidad[eid])
                paciente_id = random.choice(paciente_ids)
                hora = f"{random.randint(7,17):02d}:{random.choice(['00','15','30','45'])}"
                estado = random.choice(ESTADOS_PASADO) if offset < 0 else random.choice(ESTADOS_FUTURO)
                motivo = random.choice(MOTIVOS)
                creado_en = (fecha_dia - timedelta(days=random.randint(1, 20))).strftime("%Y-%m-%d")
                cur.execute(
                    """INSERT INTO citas
                       (paciente_id, medico_id, especialidad_id, fecha, hora, estado, modalidad, motivo, creado_en)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (paciente_id, medico_id, eid, fecha_dia.strftime("%Y-%m-%d"),
                     hora, estado, "telemedicina" if random.random() < 0.12 else "presencial",
                     motivo, creado_en),
                )
                citas_creadas.append((cur.lastrowid, eid, estado, fecha_dia))

        # --- Facturas para citas completadas ---
        tarifas = {eid: tarifa for (_, _, _, tarifa), eid in
                   zip(ESPECIALIDADES, especialidad_ids)}
        for cita_id, eid, estado, fecha_dia in citas_creadas:
            if estado == "completada":
                base = tarifas[eid]
                monto = round(base * random.uniform(0.85, 1.35), -2)
                metodo = random.choice(METODOS_PAGO)
                fecha_pago = fecha_dia.strftime("%Y-%m-%d")
                cur.execute(
                    "INSERT INTO facturas (cita_id, monto, metodo_pago, fecha_pago, estado) "
                    "VALUES (?,?,?,?,'pagada')",
                    (cita_id, monto, metodo, fecha_pago),
                )

        # --- Usuarios de demostración (uno por rol) ---
        primer_medico_id = next(iter(medico_ids_por_especialidad.values()))[0]
        primer_paciente_id = paciente_ids[0]
        ahora = datetime.now().isoformat()

        cur.execute(
            """INSERT OR IGNORE INTO usuarios (nombre, email, password_hash, rol, dosfa_activo, activo, creado_en)
               VALUES (?,?,?,?,0,1,?)""",
            ("Administrador", "admin@clinicasanjose.com",
             generate_password_hash("Admin1234"), "admin", ahora),
        )
        cur.execute(
            """INSERT OR IGNORE INTO usuarios (nombre, email, password_hash, rol, dosfa_activo, activo, creado_en)
               VALUES (?,?,?,?,0,1,?)""",
            ("Recepción", "recepcion@clinicasanjose.com",
             generate_password_hash("Recepcion1234"), "recepcionista", ahora),
        )
        cur.execute(
            """INSERT INTO usuarios
               (nombre, email, password_hash, rol, medico_id, dosfa_activo, activo, creado_en)
               VALUES (?,?,?,?,?,0,1,?)""",
            ("Dr. Demostración", "medico@clinicasanjose.com",
             generate_password_hash("Medico1234"), "medico", primer_medico_id, ahora),
        )
        cur.execute(
            """INSERT INTO usuarios
               (nombre, email, password_hash, rol, paciente_id, dosfa_activo, activo, creado_en)
               VALUES (?,?,?,?,?,0,1,?)""",
            ("Paciente Demostración", "paciente@clinicasanjose.com",
             generate_password_hash("Paciente1234"), "paciente", primer_paciente_id, ahora),
        )
        cur.execute(
            """INSERT INTO usuarios
               (nombre, email, password_hash, rol, dosfa_activo, activo, creado_en)
               VALUES (?,?,?,?,0,1,?)""",
            ("Auditoría Clínica", "auditor@clinicasanjose.com",
             generate_password_hash("Auditor1234"), "auditor", ahora),
        )

        for pid in paciente_ids[:40]:
            cur.execute(
                """INSERT OR IGNORE INTO expedientes
                   (paciente_id, tipo_sangre, alergias, antecedentes, creado_en, actualizado_en)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (pid, random.choice(["O+", "O-", "A+", "B+", "AB+"]), "Ninguna conocida",
                 "Sin antecedentes relevantes", ahora, ahora),
            )
        for pid in paciente_ids[:25]:
            cur.execute(
                "INSERT INTO seguros (paciente_id, aseguradora, poliza, copago_pct, activo) VALUES (?,?,?,?,1)",
                (pid, random.choice(["INS", "Pan-American", "Sagicor"]), f"POL-{random.randint(10000,99999)}",
                 random.choice([10, 20, 30])),
            )

        teles = cur.execute(
            "SELECT id FROM citas WHERE modalidad='telemedicina' AND estado='confirmada' LIMIT 12"
        ).fetchall()
        for row in teles:
            cid = row[0]
            cur.execute(
                """INSERT OR IGNORE INTO teleconsultas (cita_id, sala_codigo, estado, asistencia_confirmada)
                   VALUES (?, ?, 'sala_espera', 0)""",
                (cid, f"ClinicaSanJose-cita-{cid}"),
            )

    print(f"Base de datos poblada correctamente -> {DB_PATH}")
    print(f"  Especialidades: {len(especialidad_ids)}")
    print(f"  Médicos: {sum(len(v) for v in medico_ids_por_especialidad.values())}")
    print(f"  Pacientes: {len(paciente_ids)}")
    print(f"  Citas: {len(citas_creadas)}")
    print("  Usuarios demo:")
    print("    admin@clinicasanjose.com / Admin1234")
    print("    recepcion@clinicasanjose.com / Recepcion1234")
    print("    medico@clinicasanjose.com / Medico1234")
    print("    paciente@clinicasanjose.com / Paciente1234")
    print("    auditor@clinicasanjose.com / Auditor1234")


if __name__ == "__main__":
    seed()
