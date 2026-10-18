import type { Driver, DriverPayload } from '@/types'
import { api } from './client'

export async function listDrivers(): Promise<Driver[]> {
  const { data } = await api.get<Driver[]>('/drivers')
  return data
}

export async function createDriver(payload: DriverPayload): Promise<Driver> {
  const { data } = await api.post<Driver>('/drivers', payload)
  return data
}

export async function updateDriver(id: number, payload: Partial<DriverPayload>): Promise<Driver> {
  const { data } = await api.patch<Driver>(`/drivers/${id}`, payload)
  return data
}

export async function deleteDriver(id: number): Promise<void> {
  await api.delete(`/drivers/${id}`)
}
