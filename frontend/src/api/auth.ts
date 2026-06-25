import client from './client'
import type { TokenResponse } from '../types'

export const authApi = {
  register: (username: string, password: string) =>
    client.post<TokenResponse>('/auth/register', { username, password }),

  login: (username: string, password: string) =>
    client.post<TokenResponse>('/auth/login', { username, password }),
}
