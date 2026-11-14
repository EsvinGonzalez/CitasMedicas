import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { answerChat } from './features/chat/assistant'
import { requestJson } from './services/api'
import type { Account, ApiResult, Appointment, ChatMessage, Doctor } from './types'
import { formatAppointmentDate, localDate } from './utils/date'
import './App.css'

function App() {
  const [account, setAccount] = useState<Account | null>(null)
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login')
  const [authError, setAuthError] = useState('')
  const [authBusy, setAuthBusy] = useState(false)
  const [needsTwoFactor, setNeedsTwoFactor] = useState(false)
  const [twoFactorToken, setTwoFactorToken] = useState('')
  const [authName, setAuthName] = useState('')
  const [authEmail, setAuthEmail] = useState('')
  const [authPassword, setAuthPassword] = useState('')

  const [doctors, setDoctors] = useState<Doctor[]>([])
  const [appointments, setAppointments] = useState<Appointment[]>([])
  const [portalError, setPortalError] = useState('')
  const [doctorId, setDoctorId] = useState('')
  const [date, setDate] = useState('')
  const [time, setTime] = useState('')
  const [modality, setModality] = useState('presencial')
  const [reason, setReason] = useState('')
  const [availability, setAvailability] = useState<{ type: 'available' | 'busy' | 'checking'; text: string; busy?: string[] } | null>(null)
  const [bookingBusy, setBookingBusy] = useState(false)
  const [bookingMessage, setBookingMessage] = useState('')
  const [chatOpen, setChatOpen] = useState(false)
  const [chatInput, setChatInput] = useState('')
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([
    {
      id: 1,
      sender: 'assistant',
      text: '¡Hola! Soy el asistente virtual de Clínica San José. Puedo orientarte para crear tu cuenta y encontrar un horario disponible.',
    },
  ])
  const availabilitySequence = useRef(0)
  const chatMessageSequence = useRef(1)
  const chatEndRef = useRef<HTMLDivElement>(null)

  const specialties = useMemo(() => {
    const distinct = new Map<number, string>()
    for (const doctor of doctors) distinct.set(doctor.especialidad_id, doctor.especialidad)
    return [...distinct.entries()].sort((a, b) => a[1].localeCompare(b[1], 'es'))
  }, [doctors])

  const selectedDoctor = doctors.find(doctor => String(doctor.id) === doctorId)

  const refreshAppointments = useCallback(async () => {
    const data = await requestJson<Appointment[]>('/api/citas')
    if (!Array.isArray(data)) throw new Error('El servidor devolvió una lista de citas no válida.')
    setAppointments(data)
    setPortalError('')
  }, [])

  const loadPortal = useCallback(async () => {
    const [doctorData, appointmentData] = await Promise.all([
      requestJson<Doctor[]>('/api/medicos'),
      requestJson<Appointment[]>('/api/citas'),
    ])
    if (!Array.isArray(doctorData) || !Array.isArray(appointmentData)) {
      throw new Error('El servidor devolvió información incompleta.')
    }
    setDoctors(doctorData)
    setAppointments(appointmentData)
  }, [])

  const checkSession = useCallback(async () => {
    try {
      const session = await requestJson<Account & { autenticado: boolean; rol?: string }>('/api/auth/sesion')
      if (!session.autenticado) return
      if (session.rol !== 'paciente') {
        await requestJson('/api/auth/logout', { method: 'POST' })
        return
      }
      await loadPortal()
      // Restore the account only after the backend validates the saved session.
      setAccount({ nombre: session.nombre, email: session.email })
    } catch (error) {
      if (error instanceof Error && !error.message.includes('(401)')) setPortalError(error.message)
    }
  }, [loadPortal])

  useEffect(() => {
    // Rehydrate an existing patient login from the backend's signed session cookie.
    // oxlint-disable-next-line react/set-state-in-effect
    void checkSession()
  }, [checkSession])

  useEffect(() => {
    if (chatOpen) chatEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [chatMessages, chatOpen])

  function sendChatMessage(question = chatInput) {
    const trimmed = question.trim()
    if (!trimmed) return
    const answer = answerChat(trimmed, Boolean(account))
    setChatMessages(messages => [
      ...messages,
      { id: ++chatMessageSequence.current, sender: 'visitor', text: trimmed },
      { id: ++chatMessageSequence.current, sender: 'assistant', ...answer },
    ])
    setChatInput('')
  }

  const checkAvailability = useCallback(async (
    nextDoctorId = doctorId,
    nextDate = date,
    nextTime = time,
  ) => {
    const sequence = ++availabilitySequence.current
    setAvailability(null)
    setBookingMessage('')
    if (!nextDoctorId || !nextDate || !nextTime) return

    setAvailability({ type: 'checking', text: 'Comprobando disponibilidad…' })
    const query = new URLSearchParams({ medico_id: nextDoctorId, fecha: nextDate, hora: nextTime })
    try {
      const result = await requestJson<ApiResult>(`/api/citas/disponibilidad?${query}`)
      if (sequence !== availabilitySequence.current) return
      setAvailability(result.disponible
        ? { type: 'available', text: result.mensaje || 'El horario está disponible.' }
        : { type: 'busy', text: result.mensaje || 'Ese horario ya está ocupado.', busy: result.horarios_ocupados })
    } catch (error) {
      if (sequence !== availabilitySequence.current) return
      setAvailability({ type: 'busy', text: error instanceof Error ? error.message : 'No se pudo comprobar el horario.' })
    }
  }, [date, doctorId, time])

  async function submitAuth(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setAuthError('')
    setAuthBusy(true)
    try {
      if (authMode === 'register') {
        await requestJson('/api/auth/registro', {
          method: 'POST',
          body: JSON.stringify({ nombre: authName, email: authEmail, password: authPassword }),
        })
      }

      const login = await requestJson<ApiResult>('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email: authEmail, password: authPassword }),
      })
      if (login.requiere_2fa) {
        setNeedsTwoFactor(true)
        return
      }
      await finishLogin()
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : 'No se pudo iniciar sesión.')
    } finally {
      setAuthBusy(false)
    }
  }

  async function submitTwoFactor(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setAuthError('')
    setAuthBusy(true)
    try {
      await requestJson('/api/auth/verificar-2fa', {
        method: 'POST',
        body: JSON.stringify({ token: twoFactorToken }),
      })
      await finishLogin()
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : 'El código no es válido.')
    } finally {
      setAuthBusy(false)
    }
  }

  async function finishLogin() {
    const session = await requestJson<Account & { autenticado: boolean; rol?: string }>('/api/auth/sesion')
    if (!session.autenticado) throw new Error('No se pudo confirmar la sesión. Intenta ingresar de nuevo.')
    if (session.rol !== 'paciente') {
      await requestJson('/api/auth/logout', { method: 'POST' })
      throw new Error('Esta plataforma es para pacientes. Inicia sesión con una cuenta de paciente.')
    }
    await loadPortal()
    setAccount({ nombre: session.nombre, email: session.email })
    setNeedsTwoFactor(false)
    setAuthPassword('')
    setAuthError('')
    setPortalError('')
  }

  async function submitBooking(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!doctorId || !date || !time || !availability || availability.type !== 'available') return
    setBookingBusy(true)
    setBookingMessage('')
    try {
      await requestJson('/api/citas', {
        method: 'POST',
        body: JSON.stringify({
          medico_id: Number(doctorId),
          fecha: date,
          hora: time,
          modalidad: modality,
          motivo: reason.trim(),
        }),
      })
      setBookingMessage('Tu cita quedó confirmada. La verás en tu agenda.')
      setDoctorId('')
      setDate('')
      setTime('')
      setModality('presencial')
      setReason('')
      setAvailability(null)
      await refreshAppointments()
    } catch (error) {
      await checkAvailability()
      setBookingMessage(error instanceof Error ? error.message : 'No se pudo confirmar la cita.')
    } finally {
      setBookingBusy(false)
    }
  }

  async function signOut() {
    try {
      await requestJson('/api/auth/logout', { method: 'POST' })
    } catch (error) {
      setPortalError(error instanceof Error ? error.message : 'No se pudo cerrar la sesión.')
      return
    }
    setAccount(null)
    setDoctors([])
    setAppointments([])
    setPortalError('')
    setDoctorId('')
    setDate('')
    setTime('')
    setAuthMode('login')
    setNeedsTwoFactor(false)
  }

  const upcoming = appointments
    .filter(appointment => appointment.estado === 'confirmada')
    .filter(appointment => new Date(`${appointment.fecha.slice(0, 10)}T${appointment.hora.slice(0, 5)}:00`) >= new Date())
    .sort((a, b) => `${a.fecha}${a.hora}`.localeCompare(`${b.fecha}${b.hora}`))

  return (
    <div className="site-shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="Clínica San José, inicio">
          <span className="brand-mark"><span>+</span></span>
          <span className="brand-copy"><strong>San José</strong><small>CLÍNICA MÉDICA</small></span>
        </a>
        <nav className="top-links" aria-label="Navegación principal">
          <a href="#servicios">Nuestros servicios</a>
          <a href="#como-funciona">Cómo funciona</a>
        </nav>
        {account
          ? <div className="account-controls"><span className="welcome-name">Hola, {account.nombre.split(' ')[0]}</span><button className="quiet-button" onClick={() => void signOut()}>Cerrar sesión</button></div>
          : <a className="header-cta" href="#acceso">Acceso pacientes <span aria-hidden="true">↗</span></a>}
      </header>

      <main>
        <section className="hero">
          <div className="hero-copy">
            <div className="eyebrow"><span className="status-dot" /> CUIDAMOS DE TI, EN CADA MOMENTO</div>
            <h1>Tu salud merece<br />una atención <em>cercana.</em></h1>
            <p>Encuentra al especialista ideal y agenda tu consulta en línea, de forma simple, segura y cuando tú lo necesites.</p>
            <div className="hero-actions">
              <a className="primary-button" href={account ? '#reservar' : '#acceso'}>{account ? 'Agendar una cita' : 'Agenda tu consulta'} <span aria-hidden="true">→</span></a>
              <a className="text-link" href="#servicios">Conoce la clínica <span aria-hidden="true">↓</span></a>
            </div>
            <div className="hero-assurance"><span className="assurance-icon">✓</span><span>Atención confiable, con el cuidado que mereces.</span></div>
          </div>

          <div className="hero-visual" aria-label="Atención médica profesional">
            <div className="visual-glow" />
            <div className="visual-card visual-card-top"><span className="tiny-icon">✳</span><div><strong>Atención integral</strong><small>Especialistas a tu servicio</small></div></div>
            <div className="doctor-illustration">
              <div className="illustration-halo" />
              <div className="doctor-head"><div className="doctor-hair" /><div className="doctor-face"><i className="eye eye-left" /><i className="eye eye-right" /><i className="smile" /></div></div>
              <div className="doctor-neck" />
              <div className="doctor-coat"><span className="coat-neck" /><span className="coat-pocket">+</span><span className="stethoscope">⌁</span></div>
              <div className="doctor-hand" />
            </div>
            <div className="visual-cross">+</div><div className="visual-spark">✳</div>
            <div className="visual-card visual-card-bottom"><span className="calendar-icon">▦</span><div><strong>Reserva en línea</strong><small>Sin llamadas ni esperas</small></div><span className="card-arrow">↗</span></div>
          </div>
          <div className="hero-bottom-note"><span>01</span><span className="note-line" /><span>BIENESTAR A TU ALCANCE</span></div>
        </section>

        <section className="trust-strip" id="servicios">
          <span>Tu atención, más fácil</span><div><b>01</b><strong>Especialistas calificados</strong></div><div><b>02</b><strong>Agenda desde donde estés</strong></div><div><b>03</b><strong>Información segura</strong></div>
        </section>

        {!account && (
          <section className="access-section" id="acceso">
            <div className="access-copy">
              <span className="section-kicker">PORTAL PARA PACIENTES</span>
              <h2>Una forma más sencilla<br />de cuidar de ti.</h2>
              <p>Crea tu cuenta en pocos pasos. Después podrás consultar la disponibilidad real y reservar directamente con nuestros especialistas.</p>
              <div className="access-detail"><span>✓</span><p><strong>Tu información protegida</strong><small>Tu cuenta está vinculada al sistema de citas de la clínica.</small></p></div>
              <div className="access-detail"><span>✓</span><p><strong>Reserva confirmada al instante</strong><small>Si un horario se ocupa, podrás elegir otro enseguida.</small></p></div>
            </div>
            <div className="auth-card">
              {needsTwoFactor ? (
                <>
                  <span className="auth-kicker">VERIFICACIÓN DE SEGURIDAD</span><h3>Confirma tu acceso</h3>
                  <p className="auth-intro">Escribe el código de verificación de tu cuenta.</p>
                  <form onSubmit={event => void submitTwoFactor(event)} className="auth-form">
                    <label htmlFor="two-factor">Código de verificación</label><input id="two-factor" autoComplete="one-time-code" inputMode="numeric" value={twoFactorToken} onChange={event => setTwoFactorToken(event.target.value)} required />
                    {authError && <p className="form-error" role="alert">{authError}</p>}
                    <button className="form-submit" disabled={authBusy}>{authBusy ? 'Verificando…' : 'Verificar y continuar'} <span>→</span></button>
                  </form>
                  <button className="back-link" onClick={() => { setNeedsTwoFactor(false); setTwoFactorToken(''); setAuthError('') }}>← Volver al inicio de sesión</button>
                </>
              ) : (
                <>
                  <span className="auth-kicker">BIENVENIDO A TU ESPACIO DE SALUD</span><h3>{authMode === 'login' ? 'Qué gusto tenerte de vuelta.' : 'Comienza por aquí.'}</h3>
                  <p className="auth-intro">{authMode === 'login' ? 'Ingresa a tu cuenta para gestionar tus citas.' : 'Crea tu cuenta de paciente y agenda tu primera consulta.'}</p>
                  <div className="auth-tabs" role="tablist" aria-label="Acceso a la plataforma">
                    <button className={authMode === 'login' ? 'is-selected' : ''} onClick={() => { setAuthMode('login'); setAuthError('') }}>Iniciar sesión</button>
                    <button className={authMode === 'register' ? 'is-selected' : ''} onClick={() => { setAuthMode('register'); setAuthError('') }}>Crear cuenta</button>
                  </div>
                  <form onSubmit={event => void submitAuth(event)} className="auth-form">
                    {authMode === 'register' && <><label htmlFor="auth-name">Nombre completo</label><input id="auth-name" autoComplete="name" value={authName} onChange={event => setAuthName(event.target.value)} placeholder="Como aparece en tu identificación" required /></>}
                    <label htmlFor="auth-email">Correo electrónico</label><input id="auth-email" type="email" autoComplete="email" value={authEmail} onChange={event => setAuthEmail(event.target.value)} placeholder="tu@correo.com" required />
                    <div className="password-label"><label htmlFor="auth-password">Contraseña</label>{authMode === 'register' && <small>Mínimo 8 caracteres</small>}</div>
                    <input id="auth-password" type="password" autoComplete={authMode === 'login' ? 'current-password' : 'new-password'} minLength={authMode === 'register' ? 8 : undefined} value={authPassword} onChange={event => setAuthPassword(event.target.value)} placeholder="••••••••" required />
                    {authError && <p className="form-error" role="alert">{authError}</p>}
                    <button className="form-submit" disabled={authBusy}>{authBusy ? 'Un momento…' : authMode === 'login' ? 'Ingresar a mi cuenta' : 'Crear mi cuenta'} <span>→</span></button>
                  </form>
                  <p className="privacy-note"><span>▣</span> Tus datos se usan únicamente para gestionar tu atención médica.</p>
                </>
              )}
            </div>
          </section>
        )}

        {account && (
          <section className="booking-section" id="reservar">
            <div className="booking-heading">
              <span className="section-kicker">AGENDA EN LÍNEA <i /> PACIENTE</span>
              <h2>Agenda tu consulta</h2>
              <p>Elige al profesional y el horario que mejor se adapte a ti.</p>
            </div>
            <div className="booking-layout">
              <form className="booking-card" onSubmit={event => void submitBooking(event)}>
                {portalError && <p className="form-error" role="alert">{portalError} <button type="button" className="back-link" onClick={() => void checkSession()}>Reintentar</button></p>}
                <div className="booking-card-head"><span className="step-number">01</span><div><strong>Detalles de tu consulta</strong><small>Selecciona tus preferencias para ver disponibilidad.</small></div></div>
                <div className="fields-grid">
                  <div className="field field-wide"><label htmlFor="doctor">Especialista</label><select id="doctor" value={doctorId} onChange={event => { const value = event.target.value; setDoctorId(value); void checkAvailability(value, date, time) }} required><option value="">Selecciona un médico</option>{specialties.map(([specialtyId, name]) => <optgroup key={specialtyId} label={name}>{doctors.filter(doctor => doctor.especialidad_id === specialtyId).map(doctor => <option value={doctor.id} key={doctor.id}>{doctor.nombre}</option>)}</optgroup>)}</select>{selectedDoctor && <small className="field-hint">{selectedDoctor.especialidad}</small>}</div>
                  <div className="field"><label htmlFor="appointment-date">Fecha</label><input id="appointment-date" type="date" min={localDate()} value={date} onChange={event => { const value = event.target.value; setDate(value); void checkAvailability(doctorId, value, time) }} required /></div>
                  <div className="field"><label htmlFor="appointment-time">Hora</label><input id="appointment-time" type="time" step={1800} value={time} onChange={event => { const value = event.target.value; setTime(value); void checkAvailability(doctorId, date, value) }} required /></div>
                  <div className="field field-wide"><label htmlFor="modality">Tipo de consulta</label><select id="modality" value={modality} onChange={event => setModality(event.target.value)}><option value="presencial">Presencial — en la clínica</option><option value="telemedicina">En línea — telemedicina</option></select></div>
                  <div className="field field-wide"><label htmlFor="reason">Motivo de consulta <span className="optional">(opcional)</span></label><textarea id="reason" rows={3} maxLength={500} placeholder="Cuéntanos brevemente cómo podemos ayudarte." value={reason} onChange={event => setReason(event.target.value)} /></div>
                </div>
                {availability && <div className={`availability availability-${availability.type}`} role="status"><span>{availability.type === 'available' ? '✓' : availability.type === 'checking' ? '…' : '!'}</span><div><strong>{availability.type === 'available' ? 'Horario disponible' : availability.type === 'checking' ? 'Revisando agenda' : 'Horario no disponible'}</strong><p>{availability.text}</p>{availability.busy && availability.busy.length > 0 && <small>Horas ocupadas: {availability.busy.join(', ')}</small>}</div></div>}
                {bookingMessage && <p className={bookingMessage.includes('confirmada') ? 'booking-success' : 'form-error'} role="status">{bookingMessage}</p>}
                <button className="booking-submit" type="submit" disabled={!availability || availability.type !== 'available' || bookingBusy}>{bookingBusy ? 'Confirmando…' : 'Confirmar mi cita'} <span>→</span></button>
                <p className="booking-privacy">▣ &nbsp;La cita se confirma solo si el horario sigue disponible.</p>
              </form>

              <aside className="agenda-card">
                <div className="agenda-card-heading"><div><span className="section-kicker">TU ESPACIO PERSONAL</span><h3>Próximas citas</h3></div><span className="agenda-count">{upcoming.length}</span></div>
                {upcoming.length ? <div className="appointment-list">{upcoming.slice(0, 5).map(appointment => <article className="appointment-item" key={appointment.id}><div className="appointment-date"><strong>{new Date(`${appointment.fecha.slice(0, 10)}T12:00:00`).getDate()}</strong><small>{formatAppointmentDate(appointment.fecha).split(' ')[1]?.replace('.', '')}</small></div><div className="appointment-info"><strong>{appointment.especialidad}</strong><span>{appointment.medico}</span><small>{appointment.hora.slice(0, 5)} · {appointment.modalidad === 'telemedicina' ? 'En línea' : 'Presencial'}</small></div><span className="confirmed-mark">✓</span></article>)}</div> : <div className="empty-agenda"><span>▦</span><strong>Aún no tienes citas próximas</strong><p>Cuando reserves, encontrarás aquí los detalles de tu consulta.</p></div>}
                <div className="help-note"><span>i</span><p>¿Tienes dudas? Comunícate con recepción de la clínica para ayudarte.</p></div>
              </aside>
            </div>
          </section>
        )}

        <section className="how-section" id="como-funciona"><div><span className="section-kicker">CUIDARTE ES MÁS SIMPLE</span><h2>Tu cita, en tres pasos.</h2></div><div className="how-steps"><article><span>01</span><strong>Elige tu especialista</strong><p>Encuentra el profesional adecuado para ti.</p></article><article><span>02</span><strong>Busca un horario</strong><p>Verificamos la agenda en tiempo real.</p></article><article><span>03</span><strong>Confirma tu consulta</strong><p>Tu cita queda vinculada al sistema de la clínica.</p></article></div></section>
      </main>
      <footer className="footer"><a className="brand footer-brand" href="/"><span className="brand-mark"><span>+</span></span><span className="brand-copy"><strong>San José</strong><small>CLÍNICA MÉDICA</small></span></a><span>Tu salud, en buenas manos.</span><span>© {new Date().getFullYear()} Clínica San José</span></footer>
      <aside className={`chat-widget${chatOpen ? ' chat-widget-open' : ''}`} aria-label="Asistente virtual">
        {chatOpen && (
          <section className="chat-panel" aria-label="Chat con el asistente virtual">
            <header className="chat-header">
              <span className="chat-avatar" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M12 3.5a8.5 8.5 0 0 0-7.1 13.2L4 21l4.6-1.6A8.5 8.5 0 1 0 12 3.5Z" /><path d="M8.2 12.1h.1m3.7 0h.1m3.7 0h.1" /></svg></span>
              <span className="chat-heading"><strong>Asistente San José</strong><small><i /> Orientación virtual</small></span>
              <button className="chat-close" type="button" aria-label="Cerrar chat" onClick={() => setChatOpen(false)}>×</button>
            </header>
            <div className="chat-body" aria-live="polite">
              <p className="chat-date">HOY</p>
              {chatMessages.map(message => (
                <div className={`chat-message chat-message-${message.sender}`} key={message.id}>
                  <p>{message.text}</p>
                  {message.action && <a className="chat-action" href={message.action.href} onClick={() => setChatOpen(false)}>{message.action.label}<span>→</span></a>}
                </div>
              ))}
              {chatMessages.length === 1 && <div className="chat-suggestions">
                <span>¿En qué puedo ayudarte?</span>
                <button type="button" onClick={() => sendChatMessage('¿Cómo agendo una cita?')}>Agendar una cita</button>
                <button type="button" onClick={() => sendChatMessage('¿Qué hago si el horario está ocupado?')}>Horario ocupado</button>
                <button type="button" onClick={() => sendChatMessage('¿Cómo creo una cuenta?')}>Crear mi cuenta</button>
              </div>}
              <div ref={chatEndRef} />
            </div>
            <form className="chat-compose" onSubmit={event => { event.preventDefault(); sendChatMessage() }}>
              <label className="sr-only" htmlFor="chat-input">Escribe tu pregunta</label>
              <input id="chat-input" value={chatInput} onChange={event => setChatInput(event.target.value)} placeholder="Escribe tu pregunta…" maxLength={300} autoComplete="off" />
              <button type="submit" disabled={!chatInput.trim()} aria-label="Enviar mensaje">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m21 3-7.2 18-3.5-7.3L3 10.2 21 3Z" /><path d="M10.3 13.7 21 3" /></svg>
              </button>
            </form>
            <p className="chat-disclaimer">Asistente informativo · No sustituye una consulta médica</p>
          </section>
        )}
        <button className="chat-launcher" type="button" aria-label={chatOpen ? 'Cerrar asistente virtual' : 'Abrir asistente virtual'} aria-expanded={chatOpen} onClick={() => setChatOpen(open => !open)}>
          <span className="chat-launcher-halo" />
          {chatOpen
            ? <svg className="chat-launcher-icon chat-icon-close" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18" /></svg>
            : <svg className="chat-launcher-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11.5a7.5 7.5 0 0 1-7.5 7.5H6l-3 2 1-5a7.5 7.5 0 1 1 16-4.5Z" /><path d="M8 11.5h.1m3.9 0h.1m3.9 0h.1" /></svg>}
          {!chatOpen && <span className="chat-launcher-label">¿Necesitas ayuda?</span>}
        </button>
      </aside>
    </div>
  )
}

export default App
