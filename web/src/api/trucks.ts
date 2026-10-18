import type { Truck, TruckPayload } from '@/types'
import { api } from './client'

export async function listTrucks(): Promise<Truck[]> {
  const { data } = await api.get<Truck[]>('/trucks')
  return data
}

export async function createTruck(payload: TruckPayload): Promise<Truck> {
  const { data } = await api.post<Truck>('/trucks', payload)
  return data
}

export async function updateTruck(id: number, payload: Partial<TruckPayload>): Promise<Truck> {
  const { data } = await api.patch<Truck>(`/trucks/${id}`, payload)
  return data
}

export async function deleteTruck(id: number): Promise<void> {
  await api.delete(`/trucks/${id}`)
}
