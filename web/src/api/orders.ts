import type { Order, OrderPayload } from '@/types'
import { api } from './client'

export async function listOrders(): Promise<Order[]> {
  const { data } = await api.get<Order[]>('/orders')
  return data
}

export async function getOrder(id: number): Promise<Order> {
  const { data } = await api.get<Order>(`/orders/${id}`)
  return data
}

export async function createOrder(payload: OrderPayload): Promise<Order> {
  const { data } = await api.post<Order>('/orders', payload)
  return data
}

export async function updateOrder(id: number, payload: Partial<OrderPayload>): Promise<Order> {
  const { data } = await api.patch<Order>(`/orders/${id}`, payload)
  return data
}

export async function deleteOrder(id: number): Promise<void> {
  await api.delete(`/orders/${id}`)
}
