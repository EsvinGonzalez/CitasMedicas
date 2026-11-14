const form = document.getElementById('portal-booking-form');
const specialtySelect = document.getElementById('specialty-select');
const doctorSelect = document.getElementById('doctor-select');
const dateInput = document.getElementById('date-select');
const timeInput = document.getElementById('time-select');
const modalitySelect = document.getElementById('modality-select');
const reasonInput = document.getElementById('reason-input');
const submitButton = document.getElementById('booking-submit');
const feedback = document.getElementById('availability-message');
const feedbackCopy = feedback.querySelector('.portal-feedback__copy');

let doctors = [];
let slotAvailable = false;
let checkedSlot = '';
let availabilityRequest = 0;
let saving = false;

function slotKey() {
  return [doctorSelect.value, dateInput.value, timeInput.value].join('|');
}

function showFeedback(type, title, detail = '', busyTimes = []) {
  feedback.className = `portal-feedback portal-feedback--${type}`;
  feedback.hidden = false;
  feedback.querySelector('.portal-feedback__icon').textContent =
    type === 'available' ? '✓' : type === 'busy' ? '!' : '…';
  feedbackCopy.replaceChildren();

  const heading = document.createElement('strong');
  heading.textContent = title;
  feedbackCopy.append(heading);
  if (detail) {
    const description = document.createElement('span');
    description.textContent = detail;
    feedbackCopy.append(description);
  }
  if (busyTimes.length) {
    const times = document.createElement('div');
    times.className = 'portal-feedback__times';
    const label = document.createElement('span');
    label.textContent = `Ocupadas: ${busyTimes.join(', ')}`;
    times.append(label);
    feedbackCopy.append(times);
  }
}

function resetAvailability() {
  availabilityRequest += 1;
  slotAvailable = false;
  checkedSlot = '';
  submitButton.disabled = true;
  feedback.hidden = true;
  feedbackCopy.replaceChildren();
}

async function readJson(response, message) {
  const contentType = response.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) {
    throw new Error(response.ok ? message : `No se pudo completar la solicitud (HTTP ${response.status}).`);
  }
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || message);
  return data;
}

function fillDoctors(specialtyId) {
  doctorSelect.replaceChildren(new Option(
    specialtyId ? 'Selecciona un médico' : 'Primero selecciona una especialidad',
    ''
  ));
  const filtered = doctors.filter(doctor => String(doctor.especialidad_id) === specialtyId);
  for (const doctor of filtered) {
    doctorSelect.add(new Option(doctor.nombre, doctor.id));
  }
  doctorSelect.disabled = filtered.length === 0;
  if (specialtyId && filtered.length === 0) {
    doctorSelect.replaceChildren(new Option('No hay médicos disponibles en esta especialidad', ''));
  }
}

async function checkAvailability() {
  resetAvailability();
  if (!doctorSelect.value || !dateInput.value || !timeInput.value) return;

  const date = new Date(`${dateInput.value}T00:00:00`);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  if (Number.isNaN(date.getTime()) || date < today) {
    showFeedback('busy', 'La fecha no es válida', 'Elige hoy o un día posterior.');
    return;
  }

  const requestId = availabilityRequest;
  const requestedSlot = slotKey();
  submitButton.disabled = true;
  showFeedback('checking', 'Revisando disponibilidad', 'Un momento, estamos comprobando este horario.');
  const params = new URLSearchParams({
    medico_id: doctorSelect.value,
    fecha: dateInput.value,
    hora: timeInput.value
  });

  try {
    const response = await fetch(`/api/citas/disponibilidad?${params}`, {
      credentials: 'same-origin',
      headers: {'X-Patient-Portal': '1'}
    });
    const data = await readJson(response, 'No se pudo comprobar el horario.');
    if (requestId !== availabilityRequest || requestedSlot !== slotKey()) return;

    if (!data.disponible) {
      showFeedback('busy', 'Ese horario está ocupado', data.mensaje, data.horarios_ocupados || []);
      return;
    }

    slotAvailable = true;
    checkedSlot = requestedSlot;
    showFeedback('available', '¡Horario disponible!', data.mensaje);
    submitButton.disabled = !modalitySelect.value || saving;
  } catch (error) {
    if (requestId !== availabilityRequest) return;
    showFeedback('busy', 'No pudimos verificar el horario', error.message);
  }
}

function renderAppointments(items) {
  const list = document.getElementById('upcoming-list');
  const count = document.getElementById('upcoming-count');
  list.replaceChildren();
  const now = new Date();
  const upcoming = items
    .filter(item => item.estado === 'confirmada')
    .filter(item => new Date(`${String(item.fecha).slice(0, 10)}T${String(item.hora).slice(0, 5)}:00`) >= now)
    .sort((a, b) => `${a.fecha}T${a.hora}`.localeCompare(`${b.fecha}T${b.hora}`))
    .slice(0, 3);

  count.textContent = String(upcoming.length);
  if (!upcoming.length) {
    const empty = document.createElement('p');
    empty.className = 'portal-empty';
    empty.textContent = 'Todavía no tienes citas próximas. Cuando reserves, aparecerán aquí.';
    list.append(empty);
    return;
  }

  for (const appointment of upcoming) {
    const card = document.createElement('article');
    card.className = 'portal-appointment';
    const day = new Date(`${String(appointment.fecha).slice(0, 10)}T12:00:00`);
    const date = document.createElement('span');
    date.className = 'portal-appointment__date';
    const dayNumber = document.createElement('strong');
    dayNumber.textContent = new Intl.DateTimeFormat('es-GT', {day: '2-digit'}).format(day);
    const month = document.createElement('small');
    month.textContent = new Intl.DateTimeFormat('es-GT', {month: 'short'}).format(day).replace('.', '');
    date.append(dayNumber, month);

    const details = document.createElement('span');
    details.className = 'portal-appointment__details';
    const specialty = document.createElement('strong');
    specialty.textContent = appointment.especialidad || 'Consulta médica';
    const doctor = document.createElement('small');
    doctor.textContent = appointment.medico || 'Médico';
    const status = document.createElement('span');
    status.className = 'portal-appointment__status';
    status.textContent = `${String(appointment.hora).slice(0, 5)} · Confirmada`;
    details.append(specialty, doctor, status);
    card.append(date, details);
    list.append(card);
  }
}

async function loadAppointments() {
  const response = await fetch('/api/citas', {
    credentials: 'same-origin',
    headers: {'X-Patient-Portal': '1'}
  });
  const appointments = await readJson(response, 'No se pudieron cargar tus citas.');
  if (!Array.isArray(appointments)) throw new Error('El servidor devolvió datos incompletos.');
  renderAppointments(appointments);
}

async function loadPortalData() {
  const response = await fetch('/api/medicos', {
    credentials: 'same-origin',
    headers: {'X-Patient-Portal': '1'}
  });
  const doctorData = await readJson(response, 'No se pudieron cargar los médicos.');
  if (!Array.isArray(doctorData)) throw new Error('El servidor devolvió datos incompletos.');

  doctors = doctorData;
  const specialties = new Map(doctors.map(doctor => [String(doctor.especialidad_id), doctor.especialidad]));
  for (const [id, name] of specialties) specialtySelect.add(new Option(name, id));
  await loadAppointments();
}

specialtySelect.addEventListener('change', () => {
  resetAvailability();
  fillDoctors(specialtySelect.value);
});
doctorSelect.addEventListener('change', checkAvailability);
dateInput.addEventListener('change', checkAvailability);
timeInput.addEventListener('change', checkAvailability);
dateInput.addEventListener('input', resetAvailability);
timeInput.addEventListener('input', resetAvailability);
modalitySelect.addEventListener('change', () => {
  submitButton.disabled = !slotAvailable || checkedSlot !== slotKey() || !modalitySelect.value || saving;
});

form.addEventListener('submit', async event => {
  event.preventDefault();
  if (!form.reportValidity()) return;
  if (!slotAvailable || checkedSlot !== slotKey()) {
    await checkAvailability();
    return;
  }

  saving = true;
  submitButton.disabled = true;
  submitButton.querySelector('span').textContent = 'Confirmando…';
  try {
    const response = await fetch('/api/citas', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Patient-Portal': '1'
      },
      credentials: 'same-origin',
      body: JSON.stringify({
        medico_id: doctorSelect.value,
        fecha: dateInput.value,
        hora: timeInput.value,
        modalidad: modalitySelect.value,
        motivo: reasonInput.value.trim()
      })
    });
    const data = await readJson(response, 'No se pudo confirmar tu cita.');
    form.reset();
    fillDoctors('');
    resetAvailability();
    showFeedback('available', '¡Tu cita está confirmada!', 'Ya aparece en tu agenda de próximas citas.');
    try {
      await loadAppointments();
    } catch (error) {
      showFeedback('available', '¡Tu cita está confirmada!', `No se pudo actualizar la lista: ${error.message}`);
    }
  } catch (error) {
    showFeedback('busy', 'No se pudo confirmar la cita', error.message);
    if (error.message.includes('ocupado') || error.message.includes('duplicar')) {
      await checkAvailability();
    }
  } finally {
    saving = false;
    submitButton.querySelector('span').textContent = 'Confirmar mi cita';
    submitButton.disabled = !slotAvailable || checkedSlot !== slotKey() || !modalitySelect.value;
  }
});

const now = new Date();
dateInput.min = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
fillDoctors('');
loadPortalData().catch(error => {
  const list = document.getElementById('upcoming-list');
  list.replaceChildren();
  const message = document.createElement('p');
  message.className = 'portal-empty portal-empty--error';
  message.textContent = error.message || 'No se pudo cargar el portal. Actualiza la página.';
  list.append(message);
  showFeedback('busy', 'No se pudieron cargar los datos', error.message);
});
