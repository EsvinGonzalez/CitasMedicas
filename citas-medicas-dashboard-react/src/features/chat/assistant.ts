type ChatAnswer = {
  text: string
  action?: { label: string; href: string }
}

export function answerChat(question: string, hasAccount: boolean): ChatAnswer {
  const text = question.toLocaleLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '')
  if (/(hola|buenas|saludos|buenos dias|buenas tardes)/.test(text)) {
    return { text: '¡Hola! Estoy aquí para ayudarte a usar el portal de pacientes. ¿Qué necesitas saber?' }
  }
  if (/(ocupad|lleno|disponib|horario|hora libre)/.test(text)) {
    return {
      text: 'Al elegir médico, fecha y hora, consulto la agenda actual. Si aparece ocupado, prueba otro horario; la cita se confirma solo si sigue libre al guardar.',
      action: hasAccount ? { label: 'Buscar un horario', href: '#reservar' } : { label: 'Ir al acceso de pacientes', href: '#acceso' },
    }
  }
  if (/(cuenta|registro|registr|contrasena|ingresar|iniciar sesion|login)/.test(text)) {
    return {
      text: 'Puedes crear tu cuenta con tu nombre, correo y una contraseña de al menos 8 caracteres. Si ya tienes cuenta, inicia sesión con tu correo y contraseña.',
      action: { label: hasAccount ? 'Ir a mis citas' : 'Crear cuenta o ingresar', href: hasAccount ? '#reservar' : '#acceso' },
    }
  }
  if (/(cancel|reprogram|cambiar cita)/.test(text)) {
    return { text: 'Para cancelar o reprogramar tu cita, solicita apoyo a recepción por los canales oficiales de la clínica. No puedo modificar citas desde este chat.' }
  }
  if (/(medicamento|sintoma|diagnost|tratamiento|dolor|receta|salud)/.test(text)) {
    return {
      text: 'Este asistente solo orienta sobre el uso del portal y no ofrece diagnósticos ni indicaciones médicas. Para una consulta de salud, agenda una cita con un profesional.',
      action: { label: hasAccount ? 'Agendar una consulta' : 'Acceder al portal', href: hasAccount ? '#reservar' : '#acceso' },
    }
  }
  if (/(medic|especialidad|doctor|doctora|profesional)/.test(text)) {
    return {
      text: 'Después de ingresar, en “Especialista” verás los médicos disponibles agrupados por especialidad. Selecciona uno para consultar su agenda.',
      action: { label: hasAccount ? 'Ver especialistas' : 'Crear cuenta o ingresar', href: hasAccount ? '#reservar' : '#acceso' },
    }
  }
  return { text: 'Puedo ayudarte con el registro, el inicio de sesión, los especialistas o la disponibilidad de horarios. Para otras consultas, comunícate con recepción por los canales oficiales de la clínica.' }
}
