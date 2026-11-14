# Manual técnico — Clínica San José

## Requisitos

- Python 3.10 o superior
- Navegador actual (cámara/micrófono para Jitsi)

## Instalación

```powershell
# Desde la raíz del repositorio:
cd .\citas-medicas-dashboard
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python seed_data.py
python app.py
```

Abrir `http://127.0.0.1:5000`.

## Cuentas demo

| Rol | Correo | Contraseña |
|---|---|---|
| Administrador | admin@clinicasanjose.com | Admin1234 |
| Recepcionista | recepcion@clinicasanjose.com | Recepcion1234 |
| Médico | medico@clinicasanjose.com | Medico1234 |
| Paciente | paciente@clinicasanjose.com | Paciente1234 |
| Auditor | auditor@clinicasanjose.com | Auditor1234 |

## Estructura

- `app.py` — punto de entrada Flask y dashboard
- `clinic_app/routes/` — blueprints de autenticación, catálogos, citas, expedientes, recetas, telemedicina, facturación y reportes
- `clinic_app/services/` — auditoría, notificaciones, predicción, PDF y TOTP
- `clinic_app/infrastructure/database.py` — conexión, esquema y migración
- `seed_data.py` — carga de datos de demostración
- `docs/openapi.yaml` — contrato de API

## Variables de entorno (producción)

`SECRET_KEY`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `STRIPE_API_KEY`.

Sin SMTP, las notificaciones se guardan igual (estado `enviada` en demo).

## API

Documentación interactiva: `/api/docs`.

## Pruebas rápidas

1. Agendar cita en telemedicina → aparece en Telemedicina.
2. Abrir un expediente → fila nueva en Auditoría.
3. Emitir receta (usuario médico) → PDF.
4. Generar factura y «Cobrar en línea».
5. Exportar PDF/CSV desde el dashboard.

## Migración a PostgreSQL

Sustituir `sqlite3` por SQLAlchemy + `DATABASE_URL`. El esquema evita tipos propietarios salvo `AUTOINCREMENT` (usar `SERIAL`/`IDENTITY`).
