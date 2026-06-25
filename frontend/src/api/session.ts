import client from './client'
import type { Session, SessionDetail } from '../types'

export const sessionApi = {
  create: (title?: string) =>
    client.post<Session>('/sessions', { title: title || '新对话' }),

  list: () =>
    client.get<{ items: Session[] }>('/sessions'),

  get: (id: string) =>
    client.get<SessionDetail>(`/sessions/${id}`),

  rename: (id: string, title: string) =>
    client.patch<Session>(`/sessions/${id}`, { title }),

  delete: (id: string) =>
    client.delete(`/sessions/${id}`),
}
