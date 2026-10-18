import type {
  BreakdownApproveResponse,
  BreakdownReportResponse,
  CancelResponse,
  DispatchResponse,
  DriverAbsenceResponse,
  OptimizeResponse,
  SimulateResponse,
} from '@/types'
import { api } from './client'

export async function getOptimizePlan(): Promise<OptimizeResponse> {
  const { data } = await api.get<OptimizeResponse>('/optimize')
  return data
}

export async function runOptimize(
  persist = true,
  planningDate?: string | null,
): Promise<OptimizeResponse> {
  const { data } = await api.post<OptimizeResponse>('/optimize', {
    persist,
    ...(planningDate ? { planning_date: planningDate } : {}),
  })
  return data
}

export async function resetOptimize(): Promise<void> {
  await api.post('/optimize/reset')
}

export async function simulateMidday(): Promise<SimulateResponse> {
  const { data } = await api.post<SimulateResponse>('/optimize/simulate')
  return data
}

export async function dispatchOrder(
  orderId: number,
  persist = true,
): Promise<DispatchResponse> {
  const { data } = await api.post<DispatchResponse>('/optimize/dispatch', {
    order_id: orderId,
    persist,
  })
  return data
}

export async function reportBreakdown(truckId: number): Promise<BreakdownReportResponse> {
  const { data } = await api.post<BreakdownReportResponse>('/optimize/breakdown', {
    truck_id: truckId,
  })
  return data
}

export async function approveBreakdown(
  truckId: number,
  rescueTruckId: number,
  persist = true,
): Promise<BreakdownApproveResponse> {
  const { data } = await api.post<BreakdownApproveResponse>('/optimize/breakdown/approve', {
    truck_id: truckId,
    rescue_truck_id: rescueTruckId,
    persist,
  })
  return data
}

export async function cancelOrder(
  orderId: number,
  persist = true,
): Promise<CancelResponse> {
  const { data } = await api.post<CancelResponse>('/optimize/cancel', {
    order_id: orderId,
    persist,
  })
  return data
}

export async function reportDriverAbsence(
  driverId: number,
  persist = true,
): Promise<DriverAbsenceResponse> {
  const { data } = await api.post<DriverAbsenceResponse>('/optimize/driver-absence', {
    driver_id: driverId,
    persist,
  })
  return data
}
