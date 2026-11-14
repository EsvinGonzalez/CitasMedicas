const path = window.location.pathname;
const seccion = path.split('/').filter(Boolean)[0] || 'dashboard';
const escaparHtml = (value) => String(value ?? '').replace(/[&<>"']/g, character => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[character]));

async function leerRespuestaApi(respuesta, mensajePorDefecto) {
  const contentType = respuesta.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    const data = await respuesta.json();
    if (!respuesta.ok) throw new Error(data.error || mensajePorDefecto);
    return data;
  }

  if (!respuesta.ok) {
    throw new Error(
      `El servidor devolvió un error (HTTP ${respuesta.status}) en lugar de JSON. `
      + 'La cita podría haberse guardado; revisa el listado antes de volver a intentarlo.'
    );
  }
  throw new Error(`El servidor devolvió una respuesta inesperada. ${mensajePorDefecto}`);
}

let pagosRegistrados = new Map();
let especialidadesParaMedicos = [];
let medicosParaRecetas = [];
let medicosParaHistorial = [];
let usuarioPuedeAsignarMedicoHistorial = false;
let usuarioPuedeAsignarMedicoReceta = false;

const config = {
  pacientes: {
    title: 'Pacientes',
    endpoint: '/api/pacientes',
    columns: ['Nombre', 'DPI', 'Email', 'Teléfono', 'Fecha registro', 'Datos faltantes'],
    renderForm: () => `
      <form id="form-paciente" class="module-form">
        <div class="field-grid">
          <div class="field">
            <label>Nombre completo</label>
            <input type="text" name="nombre" placeholder="Ej. Ana López" required>
          </div>
          <div class="field">
            <label>DPI</label>
            <input type="text" name="dpi" placeholder="Ej. 1234567890101 o ABC123" maxlength="20" pattern="[A-Za-z0-9]+" title="El DPI solo puede contener letras y números" autocomplete="off">
            <button type="button" class="table-action" id="validar-dpi">Validar DPI</button>
            <p id="estado-validacion-dpi" class="form-status" role="status" aria-live="polite" hidden></p>
          </div>
          <div class="field">
            <label>Email</label>
            <input type="email" name="email" placeholder="ana@correo.com">
          </div>
          <div class="field">
            <label>Teléfono</label>
            <input type="tel" name="telefono" placeholder="8888-8888">
          </div>
        </div>
        <div class="form-actions">
          <button type="submit" class="btn-primary">Guardar paciente</button>
        </div>
      </form>
    `,
    renderRows: (items) => items.map(p => `
      <tr>
        <td>${escaparHtml(p.nombre)}</td>
        <td>${p.dpi ? escaparHtml(p.dpi) : `<input class="table-inline-input" id="paciente-${Number(p.id)}-dpi" placeholder="Agregar DPI" aria-label="DPI de ${escaparHtml(p.nombre)}">`}</td>
        <td>${p.email ? escaparHtml(p.email) : `<input class="table-inline-input" id="paciente-${Number(p.id)}-email" type="email" placeholder="Agregar correo" aria-label="Correo de ${escaparHtml(p.nombre)}">`}</td>
        <td>${p.telefono ? escaparHtml(p.telefono) : `<input class="table-inline-input" id="paciente-${Number(p.id)}-telefono" type="tel" placeholder="Agregar teléfono" aria-label="Teléfono de ${escaparHtml(p.nombre)}">`}</td>
        <td>${escaparHtml(p.fecha_registro || '—')}</td>
        <td>${p.dpi && p.email && p.telefono ? 'Completo' : `<button class="table-action" type="button" onclick="guardarDatosPaciente(${Number(p.id)})">Guardar datos</button>`}</td>
      </tr>
    `).join(''),
    bindSubmit: () => {
      const form = document.getElementById('form-paciente');
      const campoDpi = form.elements.namedItem('dpi');
      const campoNombre = form.elements.namedItem('nombre');
      const botonValidar = document.getElementById('validar-dpi');
      const estadoValidacion = document.getElementById('estado-validacion-dpi');

      botonValidar.addEventListener('click', async () => {
        if (!campoDpi.value.trim() || !campoDpi.checkValidity()) {
          campoDpi.reportValidity();
          return;
        }

        const ventana = window.open('about:blank', '_blank');
        if (!ventana) {
          estadoValidacion.hidden = false;
          estadoValidacion.textContent = 'Permite las ventanas emergentes para abrir la verificación de Didit.';
          return;
        }
        ventana.opener = null;
        botonValidar.disabled = true;
        estadoValidacion.hidden = false;
        estadoValidacion.textContent = 'Iniciando verificación de identidad...';

        try {
          const respuesta = await fetch('/api/validar-dpi', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            credentials: 'same-origin',
            body: JSON.stringify({dpi: campoDpi.value.trim()})
          });
          const datos = await respuesta.json();
          if (!respuesta.ok) throw new Error(
            [datos.error, datos.message, datos.detalle].filter(Boolean).map(value =>
              typeof value === 'string' ? value : JSON.stringify(value)
            ).join(' ')
            || 'No se pudo iniciar la verificación.'
          );
          const urlVerificacion = new URL(datos.url);
          if (urlVerificacion.origin !== 'https://verify.didit.me') {
            throw new Error('Didit devolvió una dirección de verificación no válida.');
          }
          ventana.location.replace(urlVerificacion.href);
          if (datos.modo === 'enlace' || !datos.session_id) {
            estadoValidacion.textContent = 'Completa la verificación en Didit. Con este enlace fijo no podemos consultar el resultado ni autocompletar el nombre; ingrésalo manualmente al regresar.';
            botonValidar.disabled = false;
            return;
          }
          estadoValidacion.textContent = 'Completa la verificación en la ventana de Didit. Consultaremos el resultado al cerrarla.';

          let consultando = false;
          const limite = Date.now() + 15 * 60 * 1000;
          const intervalo = window.setInterval(async () => {
            if (consultando) return;
            if (Date.now() >= limite) {
              window.clearInterval(intervalo);
              estadoValidacion.textContent = 'La verificación tardó demasiado. Puedes volver a intentarlo.';
              botonValidar.disabled = false;
              return;
            }
            if (!ventana.closed) return;

            consultando = true;
            try {
              const resultadoRespuesta = await fetch(
                `/api/obtener-datos-dpi/${encodeURIComponent(datos.session_id)}`,
                {credentials: 'same-origin'}
              );
              const resultado = await resultadoRespuesta.json();
              if (!resultadoRespuesta.ok) throw new Error(resultado.error || 'No se pudo consultar el resultado.');
              if (resultado.aprobado) {
                window.clearInterval(intervalo);
                campoNombre.value = resultado.nombre_completo;
                estadoValidacion.textContent = 'Identidad verificada. Se completó el nombre del paciente.';
                botonValidar.disabled = false;
              } else if (['DECLINED', 'EXPIRED', 'ABANDONED', 'KYC EXPIRED'].includes(String(resultado.status).toUpperCase())) {
                window.clearInterval(intervalo);
                estadoValidacion.textContent = `La verificación no fue aprobada (${resultado.status}).`;
                botonValidar.disabled = false;
              } else {
                estadoValidacion.textContent = 'La verificación sigue en proceso. Consultando nuevamente...';
              }
            } catch (error) {
              window.clearInterval(intervalo);
              estadoValidacion.textContent = error.message || 'No se pudo consultar el resultado.';
              botonValidar.disabled = false;
            } finally {
              consultando = false;
            }
          }, 3000);
        } catch (error) {
          ventana.close();
          estadoValidacion.textContent = error.message || 'No se pudo iniciar la verificación.';
          botonValidar.disabled = false;
        }
      });

      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const data = Object.fromEntries(new FormData(form).entries());
        const res = await fetch('/api/pacientes', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify(data)
        });
        const result = await res.json();
        if (!res.ok) {
          alert(result.error || 'No se pudo guardar el paciente');
          return;
        }
        form.reset();
        cargarListado();
        alert('Paciente registrado correctamente');
      });
    }
  },
  medicos: {
    title: 'Médicos',
    endpoint: '/api/medicos',
    columns: ['Nombre', 'Especialidad', 'Colegiado', 'Horario', 'Sucursal', 'Estado', 'Acción'],
    renderForm: () => `
      <form id="form-medico" class="module-form">
        <div class="field-grid">
          <div class="field">
            <label>Nombre</label>
            <input type="text" name="nombre" placeholder="Ej. Dr. José Ruiz" required>
          </div>
          <div class="field">
            <label>Cédula</label>
            <input type="text" name="cedula" placeholder="MED-12345" required>
          </div>
          <div class="field">
            <label>Especialidad</label>
            <select name="especialidad_id" id="select-especialidad" required>
              <option value="">Selecciona una especialidad</option>
            </select>
          </div>
          <div class="field">
            <label>Colegiado</label>
            <input type="text" name="colegiado" placeholder="CR-12345">
          </div>
          <div class="field">
            <label>Horario</label>
            <input type="text" name="horario" placeholder="Lun-Vie 08:00-16:00">
          </div>
          <div class="field">
            <label>Sucursal</label>
            <input type="text" name="sucursal" placeholder="San José Central">
          </div>
        </div>
        <div class="form-actions">
          <button type="submit" class="btn-primary">Guardar médico</button>
        </div>
      </form>
    `,
    renderRows: (items) => items.map(m => `
      <tr>
        <td>${escaparHtml(m.nombre)}</td>
        <td>${escaparHtml(m.especialidad)}</td>
        <td>${m.colegiado ? escaparHtml(m.colegiado) : `<input class="table-inline-input" id="medico-${Number(m.id)}-colegiado" placeholder="Agregar colegiado" aria-label="Colegiado de ${escaparHtml(m.nombre)}">`}</td>
        <td>${m.horario ? escaparHtml(m.horario) : `<input class="table-inline-input" id="medico-${Number(m.id)}-horario" placeholder="Agregar horario" aria-label="Horario de ${escaparHtml(m.nombre)}">`}</td>
        <td>${m.sucursal ? escaparHtml(m.sucursal) : `<input class="table-inline-input" id="medico-${Number(m.id)}-sucursal" placeholder="Agregar sede" aria-label="Sede de ${escaparHtml(m.nombre)}">`}</td>
        <td><span class="badge badge--confirmada">Activo</span></td>
        <td>${m.especialidad_id ? '—' : `
          <select id="especialidad-medico-${Number(m.id)}" aria-label="Especialidad para ${escaparHtml(m.nombre)}">
            <option value="">Asignar especialidad</option>
            ${especialidadesParaMedicos.map(especialidad => `<option value="${Number(especialidad.id)}">${escaparHtml(especialidad.nombre)}</option>`).join('')}
          </select>
          <button type="button" class="table-action" onclick="asignarEspecialidadMedico(${Number(m.id)})">Guardar</button>
        `}${(!m.colegiado || !m.horario || !m.sucursal) ? `<button type="button" class="table-action" onclick="guardarDatosMedico(${Number(m.id)})">Completar perfil</button>` : 'Perfil completo'}</td>
      </tr>
    `).join(''),
    bindSubmit: async () => {
      const form = document.getElementById('form-medico');
      const select = document.getElementById('select-especialidad');
      const especialidades = await fetch('/api/especialidades', {credentials: 'same-origin'}).then(r => r.json());
      especialidadesParaMedicos = Array.isArray(especialidades) ? especialidades : [];
      select.innerHTML = '<option value="">Selecciona una especialidad</option>'
        + especialidadesParaMedicos.map(e => `<option value="${e.id}">${escaparHtml(e.nombre)}</option>`).join('');
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const payload = Object.fromEntries(new FormData(form).entries());
        const res = await fetch('/api/medicos', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (!res.ok) {
          alert(data.error || 'No se pudo guardar el médico');
          return;
        }
        form.reset();
        cargarListado();
        alert('Médico registrado correctamente');
      });
    }
  },
  citas: {
    title: 'Citas',
    endpoint: '/api/citas',
    columns: ['Paciente', 'Médico', 'Especialidad', 'Fecha', 'Hora', 'Estado', 'Acciones'],
    renderForm: async () => `
      <form id="form-cita" class="module-form">
        <div class="field-grid">
          <div class="field">
            <label>Paciente</label>
            <select name="paciente_id" id="select-paciente" required>
              <option value="">Selecciona un paciente</option>
            </select>
          </div>
          <div class="field">
            <label>Médico</label>
            <input type="text" id="input-medico" list="medicos-disponibles" placeholder="Escribe el nombre del médico" autocomplete="off" required>
            <datalist id="medicos-disponibles"></datalist>
            <input type="hidden" name="medico_id" id="select-medico">
            <small class="field-hint">Escribe para buscar entre los médicos registrados.</small>
          </div>
          <div class="field">
            <label>Fecha</label>
            <input type="date" name="fecha" required>
          </div>
          <div class="field">
            <label>Hora</label>
            <input type="time" name="hora" required>
          </div>
          <div class="field">
            <label>Modalidad</label>
            <select name="modalidad" required>
              <option value="">Selecciona una modalidad</option>
              <option value="presencial">Presencial</option>
              <option value="telemedicina">Telemedicina</option>
            </select>
          </div>
          <div class="field field--full">
            <label>Motivo</label>
            <textarea name="motivo" rows="3" placeholder="Motivo de la consulta"></textarea>
          </div>
        </div>
        <div class="form-actions">
          <button type="submit" class="btn-primary" id="guardar-cita">Guardar cita</button>
        </div>
        <p id="cita-disponibilidad" class="form-status" role="status" hidden></p>
      </form>
    `,
    renderRows: (items) => items.map(c => {
      const estadoLabel = {
        confirmada: 'Confirmada', completada: 'Completada',
        cancelada: 'Cancelada', no_asistio: 'No asistió'
      }[c.estado] || c.estado;
      const horaProgramada = new Date(`${String(c.fecha).slice(0, 10)}T${String(c.hora).slice(0, 5)}:00`);
      const puedeMarcarInasistencia = !Number.isNaN(horaProgramada.getTime()) && horaProgramada <= new Date();
      return `
        <tr>
          <td>${c.paciente}</td>
          <td>${c.medico}</td>
          <td>${c.especialidad}</td>
          <td>${c.fecha}</td>
          <td>${c.hora}</td>
          <td><span class="badge badge--${c.estado}">${estadoLabel}</span></td>
          <td class="table-actions cita-actions">
            ${c.estado === 'confirmada' ? `<button class="table-action table-action--arrived" type="button" onclick="confirmarLlegada(${c.id})">Llegó</button>
            <button class="table-action table-action--cancel" type="button" onclick="cancelarCita(${c.id})">Cancelar</button>
            <button class="table-action table-action--no-show" type="button" onclick="marcarNoAsistio(${c.id})" ${puedeMarcarInasistencia ? '' : 'disabled title="Disponible después de la hora de la cita"'}>No asistió</button>
            <button class="table-action" type="button" onclick="editarCita(${c.id}, '${c.fecha}', '${c.hora}', ${c.medico_id}, '${(c.motivo || '').replace(/'/g, "\\'")}')">Reprogramar</button>` : ''}
            <button class="table-action table-action--delete" type="button" onclick="eliminarCita(${c.id})">Eliminar</button>
          </td>
        </tr>
      `;
    }).join(''),
    bindSubmit: async () => {
      const form = document.getElementById('form-cita');
      const pacientes = await fetch('/api/pacientes', {credentials: 'same-origin'}).then(r => r.json());
      const medicos = await fetch('/api/medicos', {credentials: 'same-origin'}).then(r => r.json());
      const especialidades = await fetch('/api/especialidades', {credentials: 'same-origin'}).then(r => r.json());
      document.getElementById('select-paciente').innerHTML = Array.isArray(pacientes) && pacientes.length
        ? '<option value="">Selecciona un paciente</option>' + pacientes.map(p => `<option value="${p.id}">${p.nombre}</option>`).join('')
        : '<option value="">No hay pacientes disponibles</option>';
      const listaMedicos = document.getElementById('medicos-disponibles');
      const inputMedico = document.getElementById('input-medico');
      const idMedico = document.getElementById('select-medico');
      if (Array.isArray(medicos)) {
        listaMedicos.replaceChildren(...medicos.map(m => {
          const option = document.createElement('option');
          option.value = `${m.nombre} - ${m.especialidad}`;
          return option;
        }));
      }
      inputMedico.addEventListener('input', () => {
        const nombre = inputMedico.value.trim().toLocaleLowerCase();
        const medico = Array.isArray(medicos) && medicos.find(m =>
          m.nombre.toLocaleLowerCase() === nombre
          || `${m.nombre} - ${m.especialidad}`.toLocaleLowerCase() === nombre
        );
        idMedico.value = medico ? medico.id : '';
      });
      const puedeAgendar = Array.isArray(pacientes) && pacientes.length > 0
        && Array.isArray(medicos) && medicos.length > 0;
      document.getElementById('guardar-cita').disabled = !puedeAgendar;
      if (!puedeAgendar) {
        const disponibilidad = document.getElementById('cita-disponibilidad');
        disponibilidad.hidden = false;
        disponibilidad.textContent = !pacientes?.length
          ? 'Registra un paciente antes de agendar una cita.'
          : !especialidades?.length
            ? 'Registra primero una especialidad y un médico para poder agendar.'
            : 'Registra un médico activo para poder agendar.';
      }
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const botonGuardar = document.getElementById('guardar-cita');
        if (botonGuardar.disabled) return;
        if (!idMedico.value) {
          inputMedico.focus();
          inputMedico.setCustomValidity('Escribe y selecciona un médico registrado.');
          inputMedico.reportValidity();
          inputMedico.addEventListener('input', () => inputMedico.setCustomValidity(''), {once: true});
          return;
        }
        const payload = Object.fromEntries(new FormData(form).entries());
        botonGuardar.disabled = true;
        try {
          const res = await fetch('/api/citas', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify(payload)
          });
          const data = await leerRespuestaApi(res, 'No se pudo guardar la cita');
          form.reset();
          await cargarListado();
          const extra = data.recordatorio_reforzado
            ? ` Se envió recordatorio reforzado (riesgo de inasistencia ${(data.riesgo_noshow * 100).toFixed(0)}%).`
            : '';
          alert('Cita registrada correctamente.' + extra);
        } catch (error) {
          alert(error.message || 'No se pudo guardar la cita');
          await cargarListado();
        } finally {
          botonGuardar.disabled = false;
        }
      });
    }
  },
  facturacion: {
    title: 'Facturación',
    endpoint: '/api/facturas',
    columns: ['Paciente', 'Fecha cita', 'Servicio', 'Monto', 'Impuestos', 'Descuentos', 'Datos fiscales', 'Estado', 'Acciones'],
    renderForm: () => `
      <form id="form-factura" class="module-form facturacion-form">
        <div class="facturacion-form-head">
          <span>GENERAR FACTURA</span>
        </div>
        <div class="facturacion-form-grid">
          <div class="facturacion-grid-cell facturacion-grid-cell--cita">
            <label>Cita</label>
            <select id="select-cita" name="cita_id" required>
              <option value="">Selecciona una cita</option>
            </select>
          </div>
          <div class="facturacion-grid-cell">
            <label>Paciente</label>
            <input type="text" name="paciente" id="factura-paciente" placeholder="Paciente" readonly>
          </div>
          <div class="facturacion-grid-cell">
            <label>Especialidad</label>
            <input type="text" name="servicio" id="factura-servicio" placeholder="Especialidad" readonly>
          </div>
          <div class="facturacion-grid-cell">
            <label for="factura-monto">Monto (Q)</label>
            <input type="number" id="factura-monto" name="monto" min="0.01" step="0.01" placeholder="Ingresa el monto" required>
          </div>
          <div class="facturacion-grid-cell facturacion-grid-cell--fiscal">
            <label for="factura-datos-fiscales">Datos fiscales</label>
            <input type="text" id="factura-datos-fiscales" name="datos_fiscales" placeholder="Nombre, NIT y dirección">
          </div>
        </div>

        <div class="form-actions">
          <button type="submit" class="btn-primary">Generar factura</button>
        </div>
      </form>
    `,
    renderRows: (items) => items.map(f => `
      <tr>
        <td>${f.paciente}</td>
        <td>${f.fecha_cita || f.fecha_pago || '—'}</td>
        <td>${f.servicio || 'Consulta'}</td>
        <td>Q ${Number(f.monto).toLocaleString('es-GT')}</td>
        <td>Q ${Number(f.impuestos || 0).toLocaleString('es-GT')}</td>
        <td>Q ${Number(f.descuentos || 0).toLocaleString('es-GT')}</td>
        <td>${f.datos_fiscales ? escaparHtml(f.datos_fiscales) : `<input class="table-inline-input" id="factura-fiscal-${Number(f.id)}" placeholder="Agregar nombre y NIT" aria-label="Datos fiscales de factura ${Number(f.id)}">`}</td>
        <td><span class="badge badge--${f.estado === 'pagada' ? 'completada' : 'confirmada'}">${f.estado}</span></td>
        <td class="table-actions">
          <a class="table-action" href="/api/facturas/${f.id}/pdf?layout=invoice-v2" target="_blank" rel="noopener">Ver factura</a>
          <a class="table-action" href="/api/facturas/${f.id}/pdf?download=1&layout=invoice-v2">Descargar factura</a>
          ${Number(f.saldo_pendiente) > 0 ? `<button class="table-action" type="button" onclick="pagarFactura(${f.id}, ${Number(f.saldo_pendiente)})">Cobrar en línea</button>` : escaparHtml(f.referencia_pago || 'Pagada')}
          ${!f.datos_fiscales ? `<button class="table-action" type="button" onclick="guardarDatosFiscales(${Number(f.id)})">Guardar datos fiscales</button>` : ''}
        </td>
      </tr>
    `).join(''),
    bindSubmit: async () => {
      const [citaResponse, facturaResponse] = await Promise.all([
        fetch('/api/citas', {credentials: 'same-origin'}),
        fetch('/api/facturas', {credentials: 'same-origin'})
      ]);
      const [citas, facturas] = await Promise.all([citaResponse.json(), facturaResponse.json()]);
      if (!citaResponse.ok || !Array.isArray(citas)) {
        throw new Error(citas.error || 'No se pudieron cargar las citas');
      }
      if (!facturaResponse.ok || !Array.isArray(facturas)) {
        throw new Error(facturas.error || 'No se pudieron cargar las facturas');
      }

      const selectCita = document.getElementById('select-cita');
      const paciente = document.getElementById('factura-paciente');
      const servicio = document.getElementById('factura-servicio');
      const citasFacturadas = new Set(facturas.map(factura => String(factura.cita_id)));
      for (const cita of citas.filter(item => !citasFacturadas.has(String(item.id)))) {
        const option = document.createElement('option');
        option.value = cita.id;
        option.textContent = `${cita.paciente} - ${cita.fecha}`;
        option.dataset.paciente = cita.paciente || '';
        option.dataset.servicio = cita.especialidad || 'Consulta';
        selectCita.append(option);
      }
      if (selectCita.options.length === 1) {
        selectCita.options[0].textContent = 'No hay citas pendientes de facturar';
      }
      selectCita.addEventListener('change', () => {
        const opcion = selectCita.selectedOptions[0];
        paciente.value = opcion?.dataset.paciente || '';
        servicio.value = opcion?.dataset.servicio || '';
      });

      document.getElementById('form-factura').addEventListener('submit', async (e) => {
        e.preventDefault();
        const payload = Object.fromEntries(new FormData(e.target).entries());
        payload.cita_id = Number(selectCita.value);
        payload.monto = Number(document.getElementById('factura-monto').value);
        const res = await fetch('/api/facturas', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (!res.ok) {
          alert(data.error || 'No se pudo generar la factura');
          return;
        }
        e.target.reset();
        paciente.value = '';
        servicio.value = '';
        cargarListado();
        alert('Factura generada' + (data.copago ? ` (copago Q ${data.copago})` : ''));
      });
    }
  },
  especialidades: {
    title: 'Especialidades',
    endpoint: '/api/especialidades',
    columns: ['Nombre', 'Descripción', 'Médicos asociados', 'Duración estándar'],
    renderForm: () => `
      <form id="form-esp" class="module-form">
        <div class="field-grid">
          <div class="field"><label>Nombre</label><input name="nombre" required></div>
          <div class="field"><label>Descripción</label><textarea name="descripcion" rows="2" placeholder="Consulta general, control, etc."></textarea></div>
          <div class="field"><label>Duración</label><input type="number" name="duracion_min" value="30"></div>
          <div class="field"><label>Tarifa</label><input type="number" name="tarifa_base" value="25000"></div>
        </div>
        <div class="form-actions"><button class="btn-primary" type="submit">Guardar</button></div>
      </form>`,
    renderRows: (items) => items.map(e => `<tr><td>${escaparHtml(e.nombre)}</td><td>${escaparHtml(e.descripcion || '—')}</td><td>${Number(e.medicos ?? 0)}</td><td>${Number(e.duracion_min) || 30} min</td></tr>`).join(''),
    bindSubmit: () => {
      document.getElementById('form-esp').addEventListener('submit', async (e) => {
        e.preventDefault();
        const payload = Object.fromEntries(new FormData(e.target).entries());
        const res = await fetch('/api/especialidades', {method:'POST', headers:{'Content-Type':'application/json'}, credentials:'same-origin', body: JSON.stringify(payload)});
        const data = await res.json();
        if (!res.ok) return alert(data.error || 'Error');
        e.target.reset(); cargarListado();
      });
    }
  },
  expedientes: {
    title: 'Expediente clínico',
    endpoint: '/api/expedientes',
    columns: ['Paciente', 'Sangre', 'Alergias', 'Actualizado'],
    renderForm: () => `
      <form id="form-exp" class="module-form">
        <div class="field-grid">
          <div class="field field--full"><label>Paciente</label><select id="select-pac-exp"></select></div>
          <div class="field"><label>Tipo de sangre</label><input name="tipo_sangre" placeholder="O+"></div>
          <div class="field field--full"><label>Alergias</label><input name="alergias"></div>
          <div class="field field--full"><label>Antecedentes</label><textarea name="antecedentes" rows="2"></textarea></div>
          <div class="field field--full"><label>Nota de evolución</label><textarea name="nota" rows="3" placeholder="Solo médicos"></textarea></div>
          <div class="field field--full"><label>Diagnóstico</label><input name="diagnostico"></div>
        </div>
        <div class="form-actions">
          <button class="btn-primary" type="submit">Guardar ficha</button>
          <button class="table-action" type="button" id="btn-evo">Registrar evolución</button>
        </div>
      </form>`,
    renderRows: (items) => items.map(e => `<tr><td>${e.paciente}</td><td>${e.tipo_sangre||'—'}</td><td>${e.alergias||'—'}</td><td>${(e.actualizado_en||'').slice(0,10)}</td></tr>`).join(''),
    bindSubmit: async () => {
      const pacientes = await fetch('/api/pacientes', {credentials:'same-origin'}).then(r=>r.json());
      document.getElementById('select-pac-exp').innerHTML = pacientes.map(p=>`<option value="${p.id}">${p.nombre}</option>`).join('');
      const cargarFicha = async () => {
        const pid = document.getElementById('select-pac-exp').value;
        const res = await fetch(`/api/expedientes/paciente/${pid}`, {credentials:'same-origin'});
        const data = await res.json();
        if (!res.ok) return;
        const f = document.getElementById('form-exp');
        f.tipo_sangre.value = data.expediente.tipo_sangre || '';
        f.alergias.value = data.expediente.alergias || '';
        f.antecedentes.value = data.expediente.antecedentes || '';
        const extra = document.getElementById('extra-panel');
        extra.innerHTML = `<h3>Evoluciones</h3>` + (data.evoluciones||[]).map(ev => `<p class="evo-note"><strong>${ev.medico||'Médico'}</strong> · ${ev.creado_en}<br>${ev.diagnostico||''}<br>${ev.nota}</p>`).join('') || '<p>Sin notas.</p>';
      };
      document.getElementById('select-pac-exp').addEventListener('change', cargarFicha);
      await cargarFicha();
      document.getElementById('form-exp').addEventListener('submit', async (e) => {
        e.preventDefault();
        const pid = document.getElementById('select-pac-exp').value;
        const payload = Object.fromEntries(new FormData(e.target).entries());
        const res = await fetch(`/api/expedientes/paciente/${pid}`, {method:'PUT', headers:{'Content-Type':'application/json'}, credentials:'same-origin', body: JSON.stringify(payload)});
        const data = await res.json();
        if (!res.ok) return alert(data.error||'Error');
        cargarListado(); cargarFicha(); alert('Expediente guardado');
      });
      document.getElementById('btn-evo').addEventListener('click', async () => {
        const pid = document.getElementById('select-pac-exp').value;
        const f = document.getElementById('form-exp');
        const res = await fetch(`/api/expedientes/paciente/${pid}/evolucion`, {method:'POST', headers:{'Content-Type':'application/json'}, credentials:'same-origin', body: JSON.stringify({nota: f.nota.value, diagnostico: f.diagnostico.value})});
        const data = await res.json();
        if (!res.ok) return alert(data.error||'Solo médicos pueden registrar evolución');
        f.nota.value=''; cargarFicha();
      });
    }
  },
  historial: {
    title: 'Historial clínico',
    endpoint: '/api/expedientes/historial',
    columns: ['Paciente', 'Fecha', 'Médico', 'Diagnóstico', 'Nota de evolución', 'Auditado por'],
    renderForm: () => `
      <form id="form-historial" class="module-form">
        <div class="field-grid">
          <div class="field">
            <label>Paciente</label>
            <select id="sel-hist-paciente">
              <option value="">Todos los pacientes</option>
            </select>
          </div>
          <div class="field">
            <label>Desde</label>
            <input type="date" id="hist-desde">
          </div>
          <div class="field">
            <label>Hasta</label>
            <input type="date" id="hist-hasta">
          </div>
        </div>
        <div class="form-actions">
          <button class="btn-primary" type="button" id="btn-hist-filtrar">Filtrar historial</button>
        </div>
      </form>
    `,
    renderRows: (items) => items.map(e => `
      <tr>
        <td>${e.paciente || '—'}</td>
        <td>${(e.fecha || '').slice(0, 16) || '—'}</td>
        <td>${escaparHtml(e.medico || 'Sin médico')}${(!e.medico || e.medico === 'Sin médico') && usuarioPuedeAsignarMedicoHistorial ? `<div class="table-actions"><select id="medico-evolucion-${Number(e.evolucion_id)}" aria-label="Asignar médico a evolución"><option value="">Selecciona médico</option>${medicosParaHistorial.map(m => `<option value="${Number(m.id)}">${escaparHtml(m.nombre)}</option>`).join('')}</select><button class="table-action" type="button" onclick="asignarMedicoEvolucion(${Number(e.evolucion_id)})">Guardar</button></div>` : ''}</td>
        <td>${e.diagnostico || 'Sin diagnóstico'}</td>
        <td>${e.nota_evolucion || 'Sin nota'}</td>
        <td>${e.auditado_por || 'Sistema'}</td>
      </tr>
    `).join(''),
    bindSubmit: async () => {
      const [pacientes, medicos, sesion] = await Promise.all([
        fetch('/api/pacientes', {credentials: 'same-origin'}).then(r => r.json()),
        fetch('/api/medicos', {credentials: 'same-origin'}).then(r => r.json()),
        fetch('/api/auth/sesion', {credentials: 'same-origin'}).then(r => r.json()),
      ]);
      medicosParaHistorial = Array.isArray(medicos) ? medicos : [];
      usuarioPuedeAsignarMedicoHistorial = sesion.rol === 'admin';
      const select = document.getElementById('sel-hist-paciente');
      select.innerHTML = `<option value="">Todos los pacientes</option>` + pacientes.map(p => `<option value="${p.id}">${p.nombre}</option>`).join('');

      const btn = document.getElementById('btn-hist-filtrar');
      btn.addEventListener('click', async () => {
        const qs = new URLSearchParams();
        const paciente_id = select.value;
        const desde = document.getElementById('hist-desde').value;
        const hasta = document.getElementById('hist-hasta').value;
        if (paciente_id) qs.set('paciente_id', paciente_id);
        if (desde) qs.set('desde', desde);
        if (hasta) qs.set('hasta', hasta);

        current.endpoint = '/api/expedientes/historial' + (qs.toString() ? `?${qs.toString()}` : '');
        await cargarListado();
      });
    }
  },
  recetas: {
    title: 'Recetas electrónicas',
    endpoint: '/api/recetas',
    columns: ['Paciente', 'Médico', 'Medicamento/dosis', 'Frecuencia', 'Duración', 'Vigencia', 'PDF'],
    renderForm: () => `
      <form id="form-receta" class="module-form">
        <div class="field-grid">
          <div class="field field--full"><label>Paciente</label><select name="paciente_id" id="sel-rec-pac" required><option value="">Selecciona un paciente</option></select></div>
          <div class="field field--full" id="campo-medico-receta"><label>Médico responsable</label><select name="medico_id" id="sel-rec-med" required><option value="">Selecciona un médico</option></select></div>
          <div class="field field--full"><label>Medicamentos</label><textarea name="medicamentos" rows="6" required placeholder="Escribe un medicamento por línea"></textarea></div>
          <div class="field"><label>Dosis</label><input name="dosis" placeholder="1 tableta"></div>
          <div class="field"><label>Frecuencia</label><input name="frecuencia" placeholder="cada 12h"></div>
          <div class="field"><label>Duración</label><input name="duracion_tratamiento" placeholder="7 días"></div>
          <div class="field"><label>Vigencia</label><input type="date" name="vigencia"></div>
          <div class="field field--full"><label>Indicaciones adicionales</label><textarea name="indicaciones" rows="2"></textarea></div>
        </div>
        <div class="form-actions"><button class="btn-primary" type="submit">Emitir receta</button></div>
      </form>`,
    renderRows: (items) => items.map(r => `
      <tr>
        <td>${escaparHtml(r.paciente)}</td>
        <td>${escaparHtml(r.medico || 'No asignado')}</td>
        <td>${escaparHtml(r.medicamentos)}</td>
        <td>${escaparHtml(r.frecuencia || '—')}</td>
        <td>${escaparHtml(r.duracion_tratamiento || '—')}</td>
        <td>${escaparHtml(r.vigencia || '—')}</td>
        <td class="table-actions">
          ${!r.medico_id && usuarioPuedeAsignarMedicoReceta ? `
            <select id="medico-receta-${Number(r.id)}" aria-label="Médico responsable de receta ${Number(r.id)}">
              <option value="">Asignar médico</option>
              ${medicosParaRecetas.map(medico => `<option value="${Number(medico.id)}">${escaparHtml(medico.nombre)}</option>`).join('')}
            </select>
            <button type="button" class="table-action" onclick="asignarMedicoReceta(${Number(r.id)})">Guardar</button>
          ` : ''}
          <a class="table-action" href="/api/recetas/${r.id}/pdf" target="_blank" rel="noopener">Ver PDF</a>
          <a class="table-action" href="/api/recetas/${r.id}/pdf?download=1">Descargar</a>
        </td>
      </tr>
    `).join(''),
    bindSubmit: async () => {
      const [respuestaPacientes, respuestaMedicos, respuestaSesion] = await Promise.all([
        fetch('/api/pacientes', {credentials:'same-origin'}),
        fetch('/api/medicos', {credentials:'same-origin'}),
        fetch('/api/auth/sesion', {credentials:'same-origin'}),
      ]);
      const pacientes = await respuestaPacientes.json();
      medicosParaRecetas = await respuestaMedicos.json();
      const sesion = await respuestaSesion.json();
      usuarioPuedeAsignarMedicoReceta = sesion.rol === 'admin';
      const campoMedico = document.getElementById('campo-medico-receta');
      if (sesion.rol === 'medico') {
        campoMedico.hidden = true;
        document.getElementById('sel-rec-med').required = false;
      }
      document.getElementById('sel-rec-pac').innerHTML = '<option value="">Selecciona un paciente</option>' + pacientes.map(p=>`<option value="${Number(p.id)}">${escaparHtml(p.nombre)}</option>`).join('');
      if (Array.isArray(medicosParaRecetas)) {
        document.getElementById('sel-rec-med').innerHTML = '<option value="">Selecciona un médico</option>'
          + medicosParaRecetas.map(m=>`<option value="${Number(m.id)}">${escaparHtml(m.nombre)}</option>`).join('');
      } else {
        medicosParaRecetas = [];
      }
      document.getElementById('form-receta').addEventListener('submit', async (e) => {
        e.preventDefault();
        const payload = Object.fromEntries(new FormData(e.target).entries());
        const res = await fetch('/api/recetas', {method:'POST', headers:{'Content-Type':'application/json'}, credentials:'same-origin', body: JSON.stringify(payload)});
        const data = await res.json();
        if (!res.ok) return alert(data.error||'Solo médicos pueden emitir recetas');
        e.target.reset(); cargarListado();
      });
    }
  },
  pagos: {
    title: 'Pagos',
    endpoint: '/api/pagos',
    columns: ['Paciente', 'Factura', 'Monto', 'Método', 'Fecha', 'Referencia', 'Estado', 'Acciones'],
    renderForm: () => `
      <form id="form-pago" class="module-form payment-form">
        <div class="payment-form-grid">
          <div class="payment-cell">
            <label for="select-factura-pago">Factura</label>
            <select name="factura_id" id="select-factura-pago" required>
              <option value="">Factura</option>
            </select>
          </div>
          <div class="payment-cell">
            <label for="monto-pago">Monto (Q)</label>
            <input type="number" id="monto-pago" name="monto" min="0.01" step="0.01" placeholder="Ingresa el monto" required>
          </div>
          <div class="payment-cell">
            <label for="metodo-pago">Método</label>
            <select id="metodo-pago" name="metodo_pago" required>
              <option value="">Método</option>
              <option value="efectivo">Efectivo</option>
              <option value="tarjeta">Tarjeta</option>
              <option value="transferencia">Transferencia</option>
            </select>
          </div>
          <div class="payment-cell">
            <label for="fecha-pago">Fecha</label>
            <input type="date" id="fecha-pago" name="fecha_pago" required>
          </div>
          <div class="payment-cell">
            <label for="referencia-pago">Referencia</label>
            <input type="text" id="referencia-pago" name="referencia" placeholder="Referencia">
          </div>
        </div>
        <p id="saldo-factura-pago" class="form-status" role="status" hidden></p>
        <div class="form-actions">
          <button type="submit" class="btn-primary">Registrar pago</button>
        </div>
      </form>

      <section class="pagos-dashboard">
        <table class="citas-table pagos-table">
          <thead>
            <tr>
              <th>Cobrado hoy</th>
              <th>Pendiente de cobro</th>
              <th>Pagos registrados</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td id="pagos-cobrado-hoy">Q 0.00</td>
              <td id="pagos-saldo-pendiente">Q 0.00</td>
              <td id="pagos-cantidad">0</td>
            </tr>
          </tbody>
        </table>
      </section>` ,
    renderRows: (items) => {
      pagosRegistrados = new Map(items.map(p => [String(p.id), p]));
      return items.map(p => `<tr><td>${p.paciente || '—'}</td><td>${p.factura_id || p.factura || '—'}</td><td>Q ${Number(p.monto).toLocaleString('es-GT', {minimumFractionDigits: 2})}</td><td>${p.metodo_pago || p.pasarela || '—'}</td><td>${p.fecha_pago || p.fecha || p.creado_en || '—'}</td><td>${p.referencia || '—'}</td><td>${p.estado}</td><td><button class="table-action" type="button" onclick="verPago(${p.id})">Ver</button></td></tr>`).join('');
    },
    bindSubmit: async () => {
      const form = document.getElementById('form-pago');
      if (!form) return;
      const select = document.getElementById('select-factura-pago');
      const saldo = document.getElementById('saldo-factura-pago');
      const monto = document.getElementById('monto-pago');
      const facturasResponse = await fetch('/api/facturas', {credentials: 'same-origin'});
      const facturas = await facturasResponse.json();
      if (!facturasResponse.ok || !Array.isArray(facturas)) {
        throw new Error(facturas.error || 'No se pudieron cargar las facturas');
      }
      const pagosResponse = await fetch('/api/pagos', {credentials: 'same-origin'});
      const pagos = await pagosResponse.json();
      if (!pagosResponse.ok || !Array.isArray(pagos)) {
        throw new Error(pagos.error || 'No se pudieron cargar los pagos');
      }
      const hoy = new Date();
      const fechaHoy = `${hoy.getFullYear()}-${String(hoy.getMonth() + 1).padStart(2, '0')}-${String(hoy.getDate()).padStart(2, '0')}`;
      const formatoMonto = amount => `Q ${Number(amount).toLocaleString('es-GT', {minimumFractionDigits: 2})}`;
      const cobradoHoy = pagos
        .filter(pago => pago.estado === 'pagado' && String(pago.fecha_pago || '').slice(0, 10) === fechaHoy)
        .reduce((total, pago) => total + Number(pago.monto || 0), 0);
      document.getElementById('pagos-cobrado-hoy').textContent = formatoMonto(cobradoHoy);
      document.getElementById('pagos-saldo-pendiente').textContent = formatoMonto(
        facturas.reduce((total, factura) => total + Math.max(0, Number(factura.saldo_pendiente) || 0), 0)
      );
      document.getElementById('pagos-cantidad').textContent = String(pagos.length);
      for (const factura of facturas.filter(f => Number(f.saldo_pendiente) > 0)) {
        const option = document.createElement('option');
        option.value = factura.id;
        option.textContent = `${factura.id} - ${factura.paciente} - Saldo Q ${Number(factura.saldo_pendiente).toLocaleString('es-GT', {minimumFractionDigits: 2})}`;
        option.dataset.saldo = factura.saldo_pendiente;
        select.append(option);
      }
      if (select.options.length === 1) {
        select.options[0].textContent = 'No hay facturas pendientes';
      }
      select.addEventListener('change', () => {
        const saldoPendiente = Number(select.selectedOptions[0]?.dataset.saldo);
        saldo.hidden = !Number.isFinite(saldoPendiente) || saldoPendiente <= 0;
        saldo.textContent = saldo.hidden
          ? ''
          : `Saldo pendiente: Q ${saldoPendiente.toLocaleString('es-GT', {minimumFractionDigits: 2})}`;
        monto.max = saldo.hidden ? '' : String(saldoPendiente);
      });
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const payload = Object.fromEntries(new FormData(form).entries());
        payload.moneda = 'Q';
        payload.pasarela = 'simulada';
        const res = await fetch('/api/pagos/checkout', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          credentials: 'same-origin',
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (!res.ok) return alert(data.error || 'No se pudo registrar el pago');
        form.reset();
        saldo.hidden = true;
        saldo.textContent = '';
        monto.max = '';
        await cargarListado();
        alert(data.mensaje || 'Pago registrado');
      });
    }
  },
  reportes: {
    title: 'Reportes y auditoría',
    endpoint: '/api/reportes/citas-por-especialidad?dias=30',
    columns: ['Especialidad', 'Citas', 'Participación'],
    renderForm: () => `
      <section class="report-dashboard">
        <form class="report-controls" id="form-filtros-reportes">
          <div class="report-control">
            <label for="reporte-dias">Rango de fechas</label>
            <select id="reporte-dias" name="dias">
              <option value="7">Últimos 7 días</option>
              <option value="30" selected>Últimos 30 días</option>
              <option value="90">Últimos 90 días</option>
            </select>
          </div>
          <div class="report-control">
            <label for="reporte-especialidad">Especialidad</label>
            <select id="reporte-especialidad" name="especialidad_id"><option value="">Todas</option></select>
          </div>
          <div class="report-control">
            <label for="reporte-medico">Médico</label>
            <select id="reporte-medico" name="medico_id"><option value="">Todos</option></select>
          </div>
          <div class="report-actions">
            <button type="submit" class="btn-primary report-filter">Aplicar filtros</button>
            <a class="btn-primary report-export" id="reporte-exportar-pdf" href="/api/reportes/exportar.pdf?dias=30">Exportar PDF</a>
            <a class="table-action" id="reporte-exportar-csv" href="/api/reportes/exportar.csv?dias=30">Excel / CSV</a>
          </div>
        </form>

        <div class="report-summary-grid">
          <article class="summary-card">
            <span class="summary-icon summary-icon--blue">▦</span>
            <div class="summary-content">
              <span class="summary-label">Citas atendidas</span>
              <span class="summary-value" id="reporte-atendidas">—</span>
              <span class="summary-delta" id="reporte-periodo-atendidas">Del período seleccionado</span>
            </div>
          </article>
          <article class="summary-card">
            <span class="summary-icon summary-icon--green">◌</span>
            <div class="summary-content">
              <span class="summary-label">Ingresos totales</span>
              <span class="summary-value" id="reporte-ingresos">—</span>
              <span class="summary-delta">Facturas pagadas</span>
            </div>
          </article>
          <article class="summary-card">
            <span class="summary-icon summary-icon--amber">⌁</span>
            <div class="summary-content">
              <span class="summary-label">Inasistencias</span>
              <span class="summary-value" id="reporte-inasistencias">—</span>
              <span class="summary-delta">Pacientes que no llegaron</span>
            </div>
          </article>
          <article class="summary-card">
            <span class="summary-icon summary-icon--violet">♞</span>
            <div class="summary-content">
              <span class="summary-label">Cancelaciones</span>
              <span class="summary-value" id="reporte-canceladas">—</span>
              <span class="summary-delta">Citas canceladas</span>
            </div>
          </article>
        </div>

        <div class="report-analytics">
          <section class="chart-panel bar-panel">
            <div class="chart-heading">
              <span>Citas atendidas por semana</span>
            </div>
            <div class="bar-chart" id="reporte-barras"><p class="tabla-vacia">Cargando datos…</p></div>
          </section>

          <section class="chart-panel pie-panel">
            <div class="chart-heading">
              <span>Citas por especialidad</span>
            </div>
            <div class="donut-wrap">
              <div class="donut-chart" id="reporte-dona" style="background:conic-gradient(#e5eaf1 0deg 360deg)">
                <div class="donut-core">
                  <span id="reporte-total-citas">0</span>
                </div>
              </div>
            </div>
            <div class="pie-legend" id="reporte-leyenda"></div>
          </section>
        </div>
      </section>
    `,
    renderRows: (items) => {
      const total = items.reduce((sum, item) => sum + Number(item.total || 0), 0);
      return items.map(item => {
        const porcentaje = total ? Math.round((Number(item.total || 0) / total) * 100) : 0;
        return `<tr><td>${escaparHtml(item.especialidad)}</td><td>${item.total}</td><td>${porcentaje}%</td></tr>`;
      }).join('');
    },
    bindSubmit: async () => {
      const especialidades = await fetch('/api/especialidades', {credentials: 'same-origin'}).then(r => r.json());
      const medicos = await fetch('/api/medicos', {credentials: 'same-origin'}).then(r => r.json());
      const especialidadSelect = document.getElementById('reporte-especialidad');
      const medicoSelect = document.getElementById('reporte-medico');
      especialidadSelect.innerHTML += (Array.isArray(especialidades) ? especialidades : []).map(item =>
        `<option value="${item.id}">${escaparHtml(item.nombre)}</option>`
      ).join('');

      const llenarMedicos = () => {
        const especialidadId = especialidadSelect.value;
        const opciones = (Array.isArray(medicos) ? medicos : []).filter(item =>
          !especialidadId || String(item.especialidad_id) === especialidadId
        );
        medicoSelect.innerHTML = `<option value="">Todos</option>${opciones.map(item =>
          `<option value="${item.id}">${escaparHtml(item.nombre)}</option>`
        ).join('')}`;
      };
      especialidadSelect.addEventListener('change', llenarMedicos);
      llenarMedicos();
      document.getElementById('form-filtros-reportes').addEventListener('submit', event => {
        event.preventDefault();
        cargarReporteDatos();
      });
    }
  },
  auditoria: {
    title: 'Auditoría inmutable',
    endpoint: '/api/reportes/auditoria',
    columns: ['Fecha y hora', 'Usuario', 'Módulo', 'Acción', 'Registro afectado', 'Detalle del cambio', 'IP'],
    renderForm: () => `
      <form id="form-audit-filter" class="audit-filter-grid">
        <label class="audit-control"><span>Usuario</span><select name="usuario" id="audit-usuario"><option value="">Todos</option></select></label>
        <label class="audit-control"><span>Módulo</span><select name="modulo" id="audit-modulo"><option value="">Todos</option></select></label>
        <label class="audit-control"><span>Acción</span><select name="accion" id="audit-accion"><option value="">Todas</option></select></label>
        <label class="audit-control"><span>Desde</span><input type="date" name="desde"></label>
        <label class="audit-control"><span>Hasta</span><input type="date" name="hasta"></label>
        <div class="audit-filter-actions">
          <button type="submit" class="audit-filter-button">Filtrar</button>
          <button type="button" class="audit-export-button" id="audit-exportar">Exportar PDF</button>
        </div>
      </form>
    `,
    renderRows: (items) => items.map((a) => {
      const instant = new Date(a.creado_en);
      const fecha = Number.isNaN(instant.getTime()) ? escaparHtml(a.creado_en) : instant.toLocaleDateString('es-ES');
      const hora = Number.isNaN(instant.getTime()) ? '' : instant.toLocaleTimeString('es-ES', {hour: '2-digit', minute: '2-digit', second: '2-digit'});
      const actionKinds = {crear: 'create', enviar: 'send', editar: 'update', eliminar: 'delete', reconstruir: 'history', ver: 'read'};
      const actionKind = actionKinds[a.accion] || 'neutral';
      const actionLabel = escaparHtml(a.accion || 'sin acción').replace(/_/g, ' ');
      return `<tr>
        <td><strong>${fecha}</strong><small class="audit-cell-sub">${hora}</small></td>
        <td>${escaparHtml(a.usuario_email || 'Sistema')}</td>
        <td>${escaparHtml(a.modulo || '—')}</td>
        <td><span class="audit-action audit-action--${actionKind}">${actionLabel}</span></td>
        <td>${escaparHtml(`${a.recurso || ''} ${a.recurso_id || ''}`.trim() || '—')}</td>
        <td>${escaparHtml(a.detalle || '—')}</td>
        <td class="audit-ip">${escaparHtml(a.ip || '—')}</td>
      </tr>`;
    }).join(''),
    bindSubmit: async () => {
      const form = document.getElementById('form-audit-filter');
      const response = await fetch('/api/reportes/auditoria/opciones', {credentials: 'same-origin'});
      const options = await response.json();
      const populate = (id, values, firstLabel) => {
        const select = document.getElementById(id);
        select.innerHTML = `<option value="">${firstLabel}</option>${values.map(value =>
          `<option value="${escaparHtml(value)}">${escaparHtml(value)}</option>`
        ).join('')}`;
      };
      populate('audit-usuario', options.usuarios || [], 'Todos');
      populate('audit-modulo', options.modulos || [], 'Todos');
      populate('audit-accion', options.acciones || [], 'Todas');
      form.addEventListener('submit', event => {
        event.preventDefault();
        paginaAuditoria = 1;
        cargarListado();
      });
      document.getElementById('audit-exportar').addEventListener('click', () => {
        const params = construirFiltrosAuditoria();
        window.location.href = `/api/reportes/auditoria/exportar.pdf?${params}`;
      });
    }
  },
  notificaciones: {
    title: 'Notificaciones',
    endpoint: '/api/reportes/notificaciones',
    columns: ['Fecha', 'Canal', 'Tipo', 'Paciente', 'Asunto', 'Estado', 'Alerta interna'],
    renderForm: () => `
      <section class="notifications-dashboard">
        <div class="notifications-layout">
          <section class="notifications-column">
            <div class="notifications-card">
              <div class="notifications-card-title">Canales activos</div>
              <div class="notifications-list">
                <div class="notifications-row">
                  <span class="notifications-icon">✉</span>
                  <span class="notifications-name">Correo electrónico</span>
                  <span class="toggle"><input type="checkbox" checked></span>
                </div>
                <div class="notifications-row">
                  <span class="notifications-icon sms-icon">✆</span>
                  <span class="notifications-name">SMS</span>
                  <span class="toggle"><input type="checkbox" checked></span>
                </div>
                <div class="notifications-row">
                  <span class="notifications-icon internal-icon">!</span>
                  <span class="notifications-name">Notificación interna</span>
                  <span class="toggle"><input type="checkbox"></span>
                </div>
              </div>
            </div>

            <div class="notifications-card">
              <div class="notifications-card-title">Eventos que disparan aviso</div>
              <div class="events-list">
                <div class="event-row"><span class="event-check">✓</span><span>Cita agendada</span></div>
                <div class="event-row"><span class="event-check">✓</span><span>Recordatorio 24h antes</span></div>
                <div class="event-row"><span class="event-check">✓</span><span>Cita cancelada</span></div>
                <div class="event-row"><span class="event-check">✓</span><span>Receta lista</span></div>
                <div class="event-row"><span class="event-check">✓</span><span>Factura generada</span></div>
                <div class="event-row"><span class="event-check">✓</span><span>Sobreasignación de sala</span></div>
              </div>
            </div>
          </section>

          <section class="notifications-column">
            <div class="notifications-card activity-card">
              <div class="notifications-card-title">Actividad reciente</div>
              <div class="activity-list">
                <div class="activity-row">
                  <span class="activity-icon">✉</span>
                  <div>
                    <strong>Recordatorio de cita</strong>
                    <p>Enviado a la agenda</p>
                    <span class="activity-status sent">Enviado</span>
                  </div>
                  <span class="activity-time">hace 8 min</span>
                </div>
                <div class="activity-row">
                  <span class="activity-icon sms-icon">✆</span>
                  <div>
                    <strong>Confirmación de cita</strong>
                    <p>SMS a agenda</p>
                    <span class="activity-status pending">Pendiente</span>
                  </div>
                  <span class="activity-time">hace 24 min</span>
                </div>
                <div class="activity-row">
                  <span class="activity-icon">✉</span>
                  <div>
                    <strong>Factura generada</strong>
                    <p>Fact. 0003 – Análisis general</p>
                    <span class="activity-status sent">Enviado</span>
                  </div>
                  <span class="activity-time">hace 1 h</span>
                </div>
                <div class="activity-row">
                  <span class="activity-icon internal-icon">!</span>
                  <div>
                    <strong>Receta lista</strong>
                    <p>Envío fallido — correo no encontrado</p>
                    <span class="activity-status failed">Fallido</span>
                  </div>
                  <span class="activity-time">hace 2 h</span>
                </div>
              </div>
            </div>
          </section>
        </div>

        <div class="notifications-log">
          <div class="notifications-log-title">Bitácora de envíos</div>
          <table class="citas-table report-table">
            <thead>
              <tr>
                <th>Destinatario</th>
                <th>Tipo</th>
                <th>Canal</th>
                <th>Fecha</th>
                <th>Estado</th>
              </tr>
            </thead>
            <tbody>
              <tr><td>correo</td><td>Recordatorio de cita</td><td>Correo</td><td>2026-09-09 21:07</td><td><span class="status sent-status">Enviado</span></td></tr>
              <tr><td>agenda</td><td>Confirmación de cita</td><td>SMS</td><td>2026-09-09 20:51</td><td><span class="status pending-status">Pendiente</span></td></tr>
              <tr><td>factura</td><td>Factura generada</td><td>Interna</td><td>2026-09-09 20:12</td><td><span class="status sent-status">Enviado</span></td></tr>
              <tr><td>receta</td><td>Receta lista</td><td>Correo</td><td>2026-09-09 19:03</td><td><span class="status failed-status">Fallido</span></td></tr>
            </tbody>
          </table>
        </div>
      </section>
    `,
    renderRows: (items) => items.map(n => `<tr><td>${n.creado_en}</td><td>${n.canal}</td><td>${n.tipo}</td><td>${n.paciente||'—'}</td><td>${n.asunto}</td><td>${n.estado}</td><td>${n.alerta || '—'}</td></tr>`).join('')
  },
  seguridad: {
    title: '2FA / Acceso',
    endpoint: '/api/usuario',
    columns: ['Nombre', 'Correo', 'Rol', 'Estado'],
    renderForm: () => `
      <div class="module-form">
        <p>Active un segundo factor: app autenticadora (TOTP), correo o SMS (demo: el código queda en Notificaciones).</p>
        <div class="form-actions">
          <button class="btn-primary" type="button" id="btn-totp">Generar secreto TOTP</button>
          <button class="table-action" type="button" id="btn-mail">Activar 2FA correo</button>
        </div>
        <p id="totp-uri"></p>
        <form id="form-totp-ok" class="module-form">
          <div class="field"><label>Código de 6 dígitos</label><input name="token" maxlength="6" required></div>
          <button class="btn-primary" type="submit">Confirmar TOTP</button>
        </form>
      </div>`,
    renderRows: (user) => `<tr><td>${user.nombre}</td><td>${user.email}</td><td>${user.rol}</td><td>${user.estado}</td></tr>`,
    bindSubmit: () => {
      document.getElementById('btn-totp').onclick = async () => {
        const res = await fetch('/api/auth/2fa/iniciar', {method:'POST', credentials:'same-origin'});
        const data = await res.json();
        document.getElementById('totp-uri').textContent = data.otpauth || data.error;
      };
      document.getElementById('btn-mail').onclick = async () => {
        const res = await fetch('/api/auth/2fa/activar', {method:'POST', headers:{'Content-Type':'application/json'}, credentials:'same-origin', body: JSON.stringify({metodo:'email'})});
        const data = await res.json();
        const token = prompt(data.mensaje + '\nIngrese el código (también está en Notificaciones):');
        if (!token) return;
        const r2 = await fetch('/api/auth/2fa/confirmar-canal', {method:'POST', headers:{'Content-Type':'application/json'}, credentials:'same-origin', body: JSON.stringify({token})});
        const d2 = await r2.json();
        alert(d2.mensaje || d2.error);
      };
      document.getElementById('form-totp-ok').onsubmit = async (e) => {
        e.preventDefault();
        const token = new FormData(e.target).get('token');
        const res = await fetch('/api/auth/2fa/activar', {method:'POST', headers:{'Content-Type':'application/json'}, credentials:'same-origin', body: JSON.stringify({metodo:'totp', token})});
        const data = await res.json();
        alert(data.mensaje || data.error);
      };
    }
  },
  usuario: {
    title: 'Usuario',
    endpoint: '/api/usuario',
    columns: ['Nombre', 'Correo', 'Rol', 'Estado'],
    renderForm: () => `
      <div class="module-form account-card">
        <div class="account-card__avatar">SJ</div>
        <div>
          <strong>Perfil de usuario</strong>
          <p>Consulta la cuenta que está activa en este momento.</p>
        </div>
      </div>
    `,
    renderRows: (user) => `
      <tr>
        <td>${user.nombre || '—'}</td>
        <td>${user.email || '—'}</td>
        <td>${user.rol || '—'}</td>
        <td><span class="badge badge--completada">${user.estado || 'Activa'}</span></td>
      </tr>
    `
  }
};

const current = config[seccion] || config.pacientes;
let paginaAuditoria = 1;

document.getElementById('section-title').textContent = seccion === 'citas'
  ? 'Nueva cita'
  : seccion === 'auditoria' ? 'Buscar en el registro' : `Registrar ${current.title}`;
document.getElementById('module-title').textContent = current.title;

document.getElementById('tabla-head').innerHTML = current.columns.map(c => `<th>${c}</th>`).join('');

document.getElementById('fecha-actual').textContent = new Date().toLocaleDateString('es-ES', {
  weekday: 'long', day: '2-digit', month: 'long', year: 'numeric'
});

function parametrosReporte() {
  const form = document.getElementById('form-filtros-reportes');
  const params = new URLSearchParams();
  if (!form) return params;
  for (const [key, value] of new FormData(form).entries()) {
    if (value) params.set(key, value);
  }
  return params;
}

async function cargarReporteDatos() {
  const params = parametrosReporte();
  const query = params.toString();
  const filtros = query ? `?${query}` : '';
  const dias = Number(params.get('dias') || 30);
  document.getElementById('reporte-exportar-pdf').href = `/api/reportes/exportar.pdf${filtros}`;
  document.getElementById('reporte-exportar-csv').href = `/api/reportes/exportar.csv${filtros}`;

  const obtener = async ruta => {
    const response = await fetch(`/api/reportes/${ruta}${filtros}`, {credentials: 'same-origin'});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'No se pudo cargar el reporte.');
    return data;
  };

  const tbody = document.getElementById('tabla-registros');
  try {
    const [especialidades, periodos, finanzas] = await Promise.all([
      obtener('citas-por-especialidad'),
      obtener('citas-por-periodo'),
      obtener('financieros'),
    ]);
    const atendidas = periodos.reduce((sum, row) => sum + Number(row.completadas || 0), 0);
    const inasistencias = periodos.reduce((sum, row) => sum + Number(row.inasistencias || 0), 0);
    const canceladas = periodos.reduce((sum, row) => sum + Number(row.canceladas || 0), 0);
    const totalCitas = periodos.reduce((sum, row) => sum + Number(row.total || 0), 0);

    document.getElementById('reporte-atendidas').textContent = atendidas;
    document.getElementById('reporte-ingresos').textContent = `Q ${new Intl.NumberFormat('es-GT', {minimumFractionDigits: 2, maximumFractionDigits: 2}).format(Number(finanzas.ingresos || 0))}`;
    document.getElementById('reporte-inasistencias').textContent = inasistencias;
    document.getElementById('reporte-canceladas').textContent = canceladas;
    document.getElementById('reporte-periodo-atendidas').textContent = `Últimos ${dias} días`;
    document.getElementById('reporte-total-citas').textContent = totalCitas;
    tbody.innerHTML = especialidades.length
      ? current.renderRows(especialidades)
      : `<tr><td colspan="${current.columns.length}" class="tabla-vacia">No hay especialidades registradas.</td></tr>`;
    pintarBarrasReporte(periodos);
    pintarDonaReporte(especialidades, totalCitas);
  } catch (error) {
    tbody.innerHTML = `<tr><td colspan="${current.columns.length}" class="tabla-vacia">${escaparHtml(error.message || 'No se pudo cargar el reporte.')}</td></tr>`;
    document.getElementById('reporte-barras').innerHTML = '<p class="tabla-vacia">No se pudieron cargar las citas del período.</p>';
    document.getElementById('reporte-leyenda').textContent = '';
  }
}

function pintarBarrasReporte(periodos) {
  const contenedor = document.getElementById('reporte-barras');
  const semanas = new Map();
  periodos.forEach(row => {
    const fecha = new Date(`${String(row.periodo).slice(0, 10)}T00:00:00`);
    if (Number.isNaN(fecha.getTime())) return;
    fecha.setDate(fecha.getDate() - ((fecha.getDay() + 6) % 7));
    const clave = `${fecha.getFullYear()}-${String(fecha.getMonth() + 1).padStart(2, '0')}-${String(fecha.getDate()).padStart(2, '0')}`;
    const semana = semanas.get(clave) || {fecha, total: 0};
    semana.total += Number(row.completadas || 0);
    semanas.set(clave, semana);
  });
  const datos = [...semanas.values()].sort((a, b) => a.fecha - b.fecha);
  if (!datos.some(semana => semana.total > 0)) {
    contenedor.innerHTML = '<p class="tabla-vacia">Sin citas atendidas en este período.</p>';
    return;
  }
  const maximo = Math.max(...datos.map(semana => semana.total));
  contenedor.innerHTML = datos.map((semana, indice) => {
    const altura = Math.max(8, Math.round((semana.total / maximo) * 100));
    const etiqueta = semana.fecha.toLocaleDateString('es-GT', {day: '2-digit', month: 'short'});
    return `<div class="bar-wrap"><b class="report-bar-total">${semana.total}</b><div class="bar bar-${indice % 5 + 1}" style="height:${altura}%" title="${semana.total} citas atendidas"></div><small>${etiqueta}</small></div>`;
  }).join('');
}

function pintarDonaReporte(especialidades, totalCitas) {
  const dona = document.getElementById('reporte-dona');
  const leyenda = document.getElementById('reporte-leyenda');
  const colores = ['#2a5298', '#c9a84c', '#1a9e6e', '#d45b3c', '#2e86ab', '#8793a3'];
  if (!totalCitas) {
    dona.style.background = 'conic-gradient(#e5eaf1 0deg 360deg)';
    leyenda.innerHTML = '<div class="tabla-vacia">Sin citas en este período.</div>';
    return;
  }
  let acumulado = 0;
  const segmentos = [];
  leyenda.innerHTML = especialidades.filter(row => Number(row.total) > 0).map((row, indice) => {
    const porcentaje = Number(row.total) / totalCitas * 100;
    const inicio = acumulado;
    acumulado += porcentaje;
    segmentos.push(`${colores[indice % colores.length]} ${inicio}% ${acumulado}%`);
    return `<div><span class="legend-swatch" style="background:${colores[indice % colores.length]}"></span>${escaparHtml(row.especialidad)} <b>${porcentaje.toFixed(0)}%</b></div>`;
  }).join('');
  dona.style.background = `conic-gradient(${segmentos.join(', ')})`;
}

function construirFiltrosAuditoria() {
  const form = document.getElementById('form-audit-filter');
  const params = new URLSearchParams();
  if (!form) return params;
  for (const [key, value] of new FormData(form).entries()) {
    if (value) params.set(key, value);
  }
  return params;
}

function renderizarPaginacionAuditoria(data) {
  const footer = document.getElementById('audit-paginacion');
  if (!footer) return;
  const first = data.total ? (data.pagina - 1) * data.por_pagina + 1 : 0;
  const last = Math.min(data.pagina * data.por_pagina, data.total);
  footer.innerHTML = `
    <span class="audit-pagination-summary">Mostrando ${first}-${last} de ${data.total}. Registro de solo lectura.</span>
    <div class="audit-pagination-controls">
      <button type="button" data-audit-page="${data.pagina - 1}" aria-label="Página anterior" ${data.pagina <= 1 ? 'disabled' : ''}>‹</button>
      <span>${data.pagina} / ${data.paginas}</span>
      <button type="button" data-audit-page="${data.pagina + 1}" aria-label="Página siguiente" ${data.pagina >= data.paginas ? 'disabled' : ''}>›</button>
    </div>`;
  footer.querySelectorAll('[data-audit-page]').forEach(button => {
    button.addEventListener('click', () => {
      paginaAuditoria = Number(button.dataset.auditPage);
      cargarListado();
    });
  });
}

async function cargarAuditoria() {
  const tbody = document.getElementById('tabla-registros');
  const params = construirFiltrosAuditoria();
  params.set('pagina', paginaAuditoria);
  params.set('por_pagina', 10);
  try {
    const response = await fetch(`${current.endpoint}?${params}`, {credentials: 'same-origin'});
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || 'No se pudo cargar la auditoría.');
    tbody.innerHTML = data.items.length
      ? current.renderRows(data.items)
      : `<tr><td colspan="${current.columns.length}" class="tabla-vacia">No hay actividad para los filtros seleccionados.</td></tr>`;
    renderizarPaginacionAuditoria(data);
  } catch (error) {
    tbody.innerHTML = `<tr><td colspan="${current.columns.length}" class="tabla-vacia">${escaparHtml(error.message || 'No se pudo cargar la auditoría.')}</td></tr>`;
    renderizarPaginacionAuditoria({pagina: 1, paginas: 1, por_pagina: 10, total: 0});
  }
}

async function cargarListado() {
  if (seccion === 'auditoria') return cargarAuditoria();
  if (seccion === 'reportes') return cargarReporteDatos();
  try {
    const res = await fetch(current.endpoint, { credentials: 'same-origin' });
    const data = await res.json();
    const tbody = document.getElementById('tabla-registros');
    if (!data || (Array.isArray(data) && data.length === 0)) {
      const mensaje = seccion === 'citas'
        ? 'No hay citas registradas. Agenda la primera con el formulario.'
        : 'No hay registros aún.';
      tbody.innerHTML = `<tr><td colspan="${current.columns.length}" class="tabla-vacia">${mensaje}</td></tr>`;
      return;
    }
    if (data.error) {
      tbody.innerHTML = `<tr><td colspan="${current.columns.length}" class="tabla-vacia">${data.error}</td></tr>`;
      return;
    }
    tbody.innerHTML = current.renderRows(data);
  } catch (err) {
    document.getElementById('tabla-registros').innerHTML = '<tr><td colspan="6" class="tabla-vacia">No se pudieron cargar los registros.</td></tr>';
  }
}

async function pagarFactura(id, saldoPendiente) {
  const monto = Number(saldoPendiente);
  if (!Number.isFinite(monto) || monto <= 0) {
    alert('La factura no tiene un saldo pendiente válido.');
    return;
  }
  const res = await fetch('/api/pagos/checkout', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    credentials: 'same-origin',
    body: JSON.stringify({factura_id: id, monto, metodo_pago: 'tarjeta'})
  });
  const data = await res.json();
  if (!res.ok) return alert(data.error || 'No se pudo cobrar');
  await cargarListado();
  alert(`${data.mensaje}: ${data.referencia}\nSaldo pendiente: Q ${Number(data.saldo_pendiente).toLocaleString('es-GT', {minimumFractionDigits: 2})}`);
}

async function guardarCambiosDeFila(url, payload, mensajeError) {
  try {
    const response = await fetch(url, {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      credentials: 'same-origin',
      body: JSON.stringify(payload),
    });
    const data = await leerRespuestaApi(response, mensajeError);
    await cargarListado();
    alert(data.mensaje || 'Datos guardados.');
  } catch (error) {
    alert(error.message || mensajeError);
  }
}

function guardarDatosPaciente(pacienteId) {
  const campos = ['dpi', 'email', 'telefono'];
  const payload = {};
  for (const campo of campos) {
    const input = document.getElementById(`paciente-${pacienteId}-${campo}`);
    if (input) payload[campo] = input.value.trim();
  }
  if (!Object.values(payload).some(Boolean)) return alert('Completa al menos uno de los datos antes de guardar.');
  return guardarCambiosDeFila(`/api/pacientes/${pacienteId}`, payload, 'No se pudieron actualizar los datos del paciente.');
}

function guardarDatosMedico(medicoId) {
  const campos = ['colegiado', 'horario', 'sucursal'];
  const payload = {};
  for (const campo of campos) {
    const input = document.getElementById(`medico-${medicoId}-${campo}`);
    if (input) payload[campo] = input.value.trim();
  }
  if (!Object.values(payload).some(Boolean)) return alert('Completa al menos uno de los datos del perfil.');
  return guardarCambiosDeFila(`/api/medicos/${medicoId}`, payload, 'No se pudo actualizar el perfil del médico.');
}

function guardarDatosFiscales(facturaId) {
  const input = document.getElementById(`factura-fiscal-${facturaId}`);
  const datos = input?.value.trim();
  if (!datos) return alert('Escribe el nombre, NIT y dirección para continuar.');
  return guardarCambiosDeFila(
    `/api/facturas/${facturaId}/datos-fiscales`,
    {datos_fiscales: datos},
    'No se pudieron guardar los datos fiscales.'
  );
}

async function asignarMedicoEvolucion(evolucionId) {
  const select = document.getElementById(`medico-evolucion-${evolucionId}`);
  if (!select?.value) return alert('Selecciona el médico que atendió esta evolución.');
  try {
    const response = await fetch(`/api/expedientes/historial/${evolucionId}/medico`, {
      method: 'PATCH', headers: {'Content-Type': 'application/json'}, credentials: 'same-origin',
      body: JSON.stringify({medico_id: select.value}),
    });
    const data = await leerRespuestaApi(response, 'No se pudo asignar el médico.');
    await cargarListado();
    alert(data.mensaje || 'Médico asignado.');
  } catch (error) {
    alert(error.message || 'No se pudo asignar el médico.');
  }
}

function verPago(id) {
  const pago = pagosRegistrados.get(String(id));
  if (!pago) {
    alert('No se encontraron los datos de este pago. Actualiza el listado e inténtalo de nuevo.');
    return;
  }
  alert([
    `Pago: ${pago.id}`,
    `Factura: ${pago.factura_id}`,
    `Paciente: ${pago.paciente || '—'}`,
    `Monto: Q ${Number(pago.monto).toLocaleString('es-GT', {minimumFractionDigits: 2})}`,
    `Método: ${pago.metodo_pago || '—'}`,
    `Fecha: ${pago.fecha_pago || pago.creado_en || '—'}`,
    `Referencia: ${pago.referencia || '—'}`,
    `Estado: ${pago.estado || '—'}`
  ].join('\n'));
}

async function confirmarAsistencia(citaId) {
  const res = await fetch(`/api/telemedicina/${citaId}/asistencia`, {method:'POST', credentials:'same-origin'});
  const data = await res.json();
  if (!res.ok) return alert(data.error);
  await cargarListado();
  if (data.jitsi_url) abrirUrl(data.jitsi_url);
}

async function consentirGrabacion(citaId) {
  const res = await fetch(`/api/telemedicina/${citaId}/consentimiento`, {
    method:'POST', headers:{'Content-Type':'application/json'}, credentials:'same-origin',
    body: JSON.stringify({acepta: true})
  });
  const data = await res.json();
  alert(data.mensaje || data.error);
  cargarListado();
}

async function abrirSala(citaId) {
  const res = await fetch(`/api/telemedicina/${citaId}`, {credentials:'same-origin'});
  const data = await res.json();
  if (!res.ok) return alert(data.error);
  abrirUrl(data.jitsi_url);
}

function abrirUrl(url) {
  const box = document.getElementById('jitsi-box');
  if (box) {
    box.innerHTML = `<iframe class="jitsi-frame" src="${url}" allow="camera; microphone; fullscreen; display-capture" title="Teleconsulta"></iframe>`;
  } else {
    window.open(url, '_blank');
  }
}

async function editarCita(id, fechaActual, horaActual, medicoActual, motivoActual) {
  const fecha = prompt('Nueva fecha (AAAA-MM-DD):', fechaActual);
  if (fecha === null) return;
  const hora = prompt('Nueva hora (HH:MM):', horaActual);
  if (hora === null) return;
  const motivo = prompt('Motivo:', motivoActual);
  if (motivo === null) return;
  const res = await fetch(`/api/citas/${id}`, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    credentials: 'same-origin',
    body: JSON.stringify({fecha, hora, medico_id: medicoActual, motivo})
  });
  const data = await res.json();
  if (!res.ok) return alert(data.error || 'No se pudo actualizar la cita');
  await cargarListado();
  alert('Cita actualizada correctamente');
}

async function cancelarCita(id) {
  if (!confirm('¿Cancelar esta cita?')) return;
  const motivo = prompt('Motivo de cancelación (opcional):');
  if (motivo === null) return;
  const res = await fetch(`/api/citas/${id}/cancelar`, {
    method: 'PATCH',
    headers: {'Content-Type': 'application/json'},
    credentials: 'same-origin',
    body: JSON.stringify({motivo})
  });
  const data = await res.json();
  if (!res.ok) return alert(data.error || 'No se pudo cancelar la cita');
  await cargarListado();
}

async function confirmarLlegada(id) {
  if (!confirm('¿Confirmas que el paciente llegó a la cita?')) return;
  const res = await fetch(`/api/citas/${id}/completar`, {
    method: 'PATCH', headers: {'Content-Type': 'application/json'},
    credentials: 'same-origin', body: JSON.stringify({})
  });
  const data = await res.json();
  if (!res.ok) return alert(data.error || 'No se pudo confirmar la llegada');
  await cargarListado();
}

async function marcarNoAsistio(id) {
  if (!confirm('¿Confirmas que el paciente no se presentó?')) return;
  const res = await fetch(`/api/citas/${id}/inasistencia`, {method: 'PATCH', credentials: 'same-origin'});
  const data = await res.json();
  if (!res.ok) return alert(data.error || 'No se pudo registrar la inasistencia');
  await cargarListado();
}

async function eliminarCita(id) {
  if (!confirm('¿Eliminar definitivamente esta cita?')) return;
  const res = await fetch(`/api/citas/${id}`, {method: 'DELETE', credentials: 'same-origin'});
  const data = await res.json();
  if (!res.ok) return alert(data.error || 'No se pudo eliminar la cita');
  await cargarListado();
}

async function asignarEspecialidadMedico(medicoId) {
  const select = document.getElementById(`especialidad-medico-${medicoId}`);
  if (!select?.value) return alert('Selecciona una especialidad para continuar.');

  try {
    const response = await fetch(`/api/medicos/${medicoId}`, {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      credentials: 'same-origin',
      body: JSON.stringify({especialidad_id: select.value}),
    });
    const data = await leerRespuestaApi(response, 'No se pudo asignar la especialidad.');
    await cargarListado();
    alert(data.mensaje || 'Especialidad asignada.');
  } catch (error) {
    alert(error.message || 'No se pudo asignar la especialidad.');
  }
}

async function asignarMedicoReceta(recetaId) {
  const select = document.getElementById(`medico-receta-${recetaId}`);
  if (!select?.value) return alert('Selecciona el médico responsable de la receta.');

  try {
    const response = await fetch(`/api/recetas/${recetaId}/medico`, {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      credentials: 'same-origin',
      body: JSON.stringify({medico_id: select.value}),
    });
    const data = await leerRespuestaApi(response, 'No se pudo asignar el médico.');
    await cargarListado();
    alert(data.mensaje || 'Médico asignado.');
  } catch (error) {
    alert(error.message || 'No se pudo asignar el médico.');
  }
}

async function exportarListadoPdf() {
  const tabla = document.querySelector('.panel__body--table table');
  if (!tabla) return alert('No se encontró el listado para exportar.');
  const columnas = [...tabla.querySelectorAll('thead th')]
    .map((th, index) => ({nombre: th.innerText.trim(), index}))
    .filter(columna => !/acciones|opciones|\bpdf\b/i.test(columna.nombre));
  const filas = [...tabla.querySelectorAll('tbody tr')].filter(tr => !tr.querySelector('.tabla-vacia'));
  if (!filas.length) return alert('No hay registros en el listado para exportar.');
  const datos = filas.map(fila => columnas.map(col => {
    const celda = fila.cells[col.index];
    const controles = celda ? [...celda.querySelectorAll('input,select,textarea')] : [];
    if (controles.length) return controles.map(control => control.value).join(' ');
    return celda?.innerText.trim().replace(/\s+/g, ' ') || '';
  }));
  try {
    const response = await fetch('/api/reportes/listado.pdf', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, credentials: 'same-origin',
      body: JSON.stringify({titulo: current.title, columnas: columnas.map(col => col.nombre), filas: datos}),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error || 'No se pudo generar el PDF.');
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${seccion}-${new Date().toISOString().slice(0, 10)}.pdf`;
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch (error) {
    alert(error.message || 'No se pudo descargar el PDF.');
  }
}

function exportarListadoCsv() {
  const tabla = document.querySelector('.panel__body--table table');
  if (!tabla) return alert('No se encontró el listado para exportar.');
  const encabezados = [...tabla.querySelectorAll('thead th')];
  const indices = encabezados.map((th, index) => ({th, index})).filter(({th}) => !/acciones|opciones/i.test(th.textContent)).map(({index}) => index);
  if (!indices.length) return alert('El listado todavía no tiene columnas para exportar.');
  const filas = [...tabla.querySelectorAll('tbody tr')].filter(tr => !tr.querySelector('.tabla-vacia'));
  if (!filas.length) return alert('No hay registros en el listado para exportar.');
  const valorCelda = (celda) => {
    const controles = [...celda.querySelectorAll('input, select, textarea')];
    return controles.length ? controles.map(control => control.value).join(' ') : celda.innerText.trim().replace(/\s+/g, ' ');
  };
  const escapar = valor => `"${String(valor ?? '').replace(/"/g, '""')}"`;
  const matriz = [indices.map(index => encabezados[index].innerText.trim()), ...filas.map(fila => indices.map(index => valorCelda(fila.cells[index] || document.createElement('td'))))];
  const csv = '\uFEFF' + matriz.map(fila => fila.map(escapar).join(';')).join('\r\n');
  const url = URL.createObjectURL(new Blob([csv], {type: 'text/csv;charset=utf-8'}));
  const enlace = document.createElement('a');
  enlace.href = url;
  enlace.download = `${seccion}-${new Date().toISOString().slice(0, 10)}.csv`;
  enlace.click();
  URL.revokeObjectURL(url);
}

async function init() {
  document.getElementById('exportar-listado-csv')?.addEventListener('click', exportarListadoCsv);
  document.getElementById('exportar-listado-pdf')?.addEventListener('click', exportarListadoPdf);
  const formContainer = document.getElementById('form-container');
  const formMarkup = typeof current.renderForm === 'function' ? current.renderForm() : current.renderForm;
  formContainer.innerHTML = await Promise.resolve(formMarkup);
  if (typeof current.bindSubmit === 'function') {
    await Promise.resolve(current.bindSubmit());
  }
  await cargarListado();
}

init();
