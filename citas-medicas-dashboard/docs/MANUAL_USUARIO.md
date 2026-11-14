# Manual de usuario — Clínica San José

## Inicio de sesión

1. Entre a `http://127.0.0.1:5000/login`.
2. Use su correo y contraseña.
3. Si el administrador activó 2FA, ingrese el código de 6 dígitos (app Authenticator, correo o SMS).

## Dashboard

Muestra citas del día, inasistencia, ingresos, médicos más solicitados y gráficos. Use **PDF** o **Excel** para exportar el periodo (7/30/90 días).

## Pacientes y citas

- **Pacientes:** registre nombre, correo y teléfono.
- **Citas:** elija paciente, médico, fecha, hora y si es presencial o telemedicina. El sistema evita que el médico tenga dos citas a la misma hora. Si el modelo estima alto riesgo de inasistencia, se envía un recordatorio reforzado.
- **Portal del paciente:** regístrese desde la página de inicio de sesión o entre con su cuenta de paciente. Al iniciar sesión se abre **Agendar mi cita**: elija especialidad, médico, fecha y hora. El portal muestra si el horario está ocupado antes de confirmar; si se ocupa durante el proceso, el sistema rechaza la reserva y permite elegir otro horario.

## Expediente

En **Expediente** seleccione al paciente, complete tipo de sangre, alergias y antecedentes. El médico agrega **evolución** (nota y diagnóstico). Cada consulta del expediente queda en **Auditoría**.

## Recetas

El médico indica medicamentos e indicaciones. Descargue el **PDF** para el paciente o la farmacia.

## Telemedicina

1. Agende la cita como telemedicina.
2. En **Telemedicina**, el paciente **confirma asistencia** (sale de la sala de espera).
3. Si acepta ser grabado, pulse **Consentir grabación**.
4. **Entrar** abre la videollamada Jitsi (permita cámara y micrófono).

## Facturación y pagos

Recepción genera la factura. Si el paciente tiene seguro, se calcula copago. **Cobrar en línea** simula Stripe y deja referencia de pago. El historial está en **Pagos**.

## Seguridad (2FA)

En **2FA / Acceso** genere un secreto TOTP, agréguelo a Google Authenticator y confirme el código. También puede activar códigos por correo (en esta demo aparecen en **Notificaciones**).

## Auditor

El rol auditor solo consulta la bitácora: quién vio o editó qué expediente y cuándo. Los registros no se pueden borrar.

## Cerrar sesión

Use **Cerrar sesión** en el menú de cuenta.
