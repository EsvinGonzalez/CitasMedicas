# Portal independiente para pacientes

Este sitio es la plataforma pública de Clínica San José. Se ejecuta por separado del panel administrativo, pero utiliza el mismo backend, usuarios, pacientes y agenda; no crea una base de datos paralela.

## Probar localmente

1. Inicia el backend Flask del sistema de citas en `http://127.0.0.1:5000`.
2. Desde esta carpeta, ejecuta `npm run dev`.
3. Abre `http://127.0.0.1:5173`.
4. El paciente crea su cuenta o inicia sesión; después puede consultar médicos y horarios y confirmar una cita.

Vite reenvía `/api` al backend para que las cookies de sesión funcionen sin habilitar CORS abierto. El portal usa una cookie de sesión independiente a la del dashboard, por lo que ingresar o salir como paciente no cambia la sesión del personal. Para usar otro backend en desarrollo, define `BACKEND_URL` antes de iniciar Vite.

## Publicar con una URL propia

Genera los archivos estáticos con `npm run build` y publica `dist/` en el alojamiento del sitio público. La URL pública debe reenviar las solicitudes `/api/*` al backend Flask existente y conservar los encabezados `Set-Cookie` y `Cookie`. De ese modo el frontend se sirve desde su propia dirección, mientras la API y las reservas siguen conectadas al sistema actual. Usa HTTPS en producción y no coloques claves ni credenciales del backend en el frontend.

El dominio y el alojamiento de producción deben configurarse en el proveedor de despliegue. En desarrollo, el portal funciona en `http://127.0.0.1:5173`.

El portal incluye animaciones de interfaz que respetan la preferencia del dispositivo por movimiento reducido y un asistente virtual de preguntas frecuentes sobre acceso y reservas. El chat es informativo, no está conectado a personal de recepción ni proporciona orientación médica.
