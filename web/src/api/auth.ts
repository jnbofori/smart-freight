import type { User } from '@/types'
import { api } from './client'

export async function login(email: string, password: string): Promise<User> {
  const { data } = await api.post<User>('/auth/login', { email, password })
  return data
}

export async function logout(): Promise<void> {
  await api.post('/auth/logout')
}

export async function fetchMe(): Promise<User> {
  const { data } = await api.get<User>('/auth/me')
  return data
}
