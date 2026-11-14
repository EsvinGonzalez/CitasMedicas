export type Doctor = {
  id: number
  nombre: string
  especialidad_id: number
  especialidad: string
}

export type Appointment = {
  id: number
  fecha: string
  hora: string
  estado: string
  medico: string
  especialidad: string
  modalidad: string
}

export type Account = {
  nombre: string
  email: string
}

export type ChatMessage = {
  id: number
  sender: 'assistant' | 'visitor'
  text: string
  action?: { label: string; href: string }
}

export type ApiResult = {
  error?: string
  disponible?: boolean
  mensaje?: string
  horarios_ocupados?: string[]
  requiere_2fa?: boolean
  success?: boolean
  nombre?: string
  email?: string
}
