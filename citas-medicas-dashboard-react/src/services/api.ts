import type { ApiResult } from '../types'

export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: 'same-origin',
    headers: {
      'X-Patient-Portal': '1',
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  })
  const contentType = response.headers.get('content-type') || ''
  if (!contentType.includes('application/json')) {
    throw new Error(response.ok ? 'El servidor devolvió una respuesta inesperada.' : `Error de conexión (${response.status}).`)
  }
  const data = await response.json() as T & ApiResult
  if (!response.ok) throw new Error(data.error || 'No se pudo completar la solicitud.')
  return data
}
