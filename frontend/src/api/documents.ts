import client from './client'
import type { DocInfo } from '../types'

export const docsApi = {
  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return client.post<DocInfo>('/documents/upload', form)
  },

  list: () => client.get<{ documents: DocInfo[]; total: number }>('/documents/list'),

  remove: (id: string) => client.delete(`/documents/${id}`),
}
