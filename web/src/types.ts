export interface User {
  id: number
  email: string
  full_name: string
  created_at: string
}

export interface Driver {
  id: number
  code: string
  name: string
  status: string
  licence_class: string
  can_dangerous_goods: boolean
  can_heated: boolean
  can_liftgate_runs: boolean
  shift_start_min: number
  shift_end_min: number
  max_duty_hours: number
  max_drive_hours: number
  home_terminal_city: string
  truck_id: number
  created_at: string
}

export type DriverPayload = {
  code: string
  name: string
  status: string
  licence_class: string
  can_dangerous_goods: boolean
  can_heated: boolean
  can_liftgate_runs: boolean
  shift_start_min: number
  shift_end_min: number
  max_duty_hours: number
  max_drive_hours: number
  home_terminal_city: string
  truck_id: number
}

export interface Truck {
  id: number
  unit_number: string
  vehicle_class: string
  axle_count: number
  max_weight_lbs: number
  max_skid_spots: number
  max_linear_feet: number
  max_interior_height_in: number
  has_trailer: boolean
  trailer_unit: string | null
  trailer_size_class: string
  has_liftgate: boolean
  has_dock_height: boolean
  heated: boolean
  home_terminal_city: string
  current_address: string
  current_lat: number | null
  current_lng: number | null
  status: string
  created_at: string
}

export type TruckPayload = {
  unit_number: string
  vehicle_class: string
  axle_count: number
  max_weight_lbs?: number | null
  max_skid_spots?: number | null
  max_linear_feet?: number | null
  max_interior_height_in?: number | null
  has_trailer: boolean
  trailer_unit?: string | null
  trailer_size_class: string
  has_liftgate: boolean
  has_dock_height: boolean
  heated: boolean
  home_terminal_city: string
  current_address?: string
  current_lat?: number | null
  current_lng?: number | null
  status: string
}

export interface Order {
  id: number
  ordno: string
  reference: string | null
  origin_city: string
  destination_city: string
  origin_address: string
  destination_address: string
  weight_lbs: number
  skid_spots: number
  linear_feet: number
  dim_weight: number | null
  pieces: number
  stackable: boolean
  height_in: number | null
  service: string
  equipment_required: string
  requires_liftgate: boolean
  residential: boolean
  inside_delivery: boolean
  appointment: boolean
  dangerous_goods: boolean
  heated: boolean
  delivery_window_start: string | null
  delivery_window_end: string | null
  status: string
  assigned_truck_id: number | null
  assigned_driver_id: number | null
  stop_seq: number | null
  created_at: string
}

export type OrderPayload = {
  ordno: string
  reference?: string | null
  origin_city: string
  destination_city: string
  origin_address: string
  destination_address: string
  weight_lbs: number
  skid_spots: number
  linear_feet: number
  dim_weight?: number | null
  pieces: number
  stackable: boolean
  height_in?: number | null
  service: string
  equipment_required: string
  requires_liftgate: boolean
  residential: boolean
  inside_delivery: boolean
  appointment: boolean
  dangerous_goods: boolean
  heated: boolean
  delivery_window_start?: string | null
  delivery_window_end?: string | null
  status?: string
  assigned_truck_id?: number | null
  assigned_driver_id?: number | null
}

export interface CapacityUsage {
  weight_lbs: number
  skid_spots: number
  linear_feet: number
  remaining_weight_lbs: number
  remaining_skid_spots: number
  remaining_linear_feet: number
}

export interface LoadPlacement {
  order_id: number
  ordno: string
  column_index: number
  layer: number
  floor_spots: number
  skid_spots: number
  linear_feet: number
  height_in: number | null
  stackable: boolean
  stacked: boolean
  stop_seq: number
  load_seq: number
}

export interface RouteStop {
  order_id: number
  ordno: string
  seq: number
  destination_city: string
  destination_address: string
  eta_min: number
  travel_min_from_prev: number
  lat: number | null
  lng: number | null
  weather_note: string
}

export interface MapPoint {
  lat: number
  lng: number
}

export interface AssignmentRoute {
  stops: RouteStop[]
  total_distance_m: number
  total_drive_min: number
  corridor: string
  path: MapPoint[]
  depot_lat: number | null
  depot_lng: number | null
  depot_label: string
  /** After Simulate: start marker is truck current place, not morning depot */
  truck_at_start?: boolean
}

export interface TruckAssignment {
  truck_id: number
  unit_number: string
  driver_id: number | null
  driver_name: string | null
  driver_code: string | null
  truck_status: string | null
  duty_minutes_used: number
  order_ids: number[]
  order_ordnos: string[]
  destinations: string[]
  usage: CapacityUsage
  rationales: string[]
  reasoning_summary?: string
  placements: LoadPlacement[]
  max_skid_spots: number
  max_linear_feet: number
  max_interior_height_in: number
  route: AssignmentRoute | null
}

export interface UnassignedOrder {
  order_id: number
  ordno: string
  reason: string
}

export interface OptimizeResponse {
  assignments: TruckAssignment[]
  unassigned: UnassignedOrder[]
  summary: {
    trucks_used: number
    drivers_used: number
    orders_assigned: number
    orders_unassigned: number
    orders_considered: number
  }
  planning_date: string
  routing_mode: string
  weather_summary: string
  unassigned_summary?: string
}

export interface RouteHistoryStop {
  seq: number
  ordno: string
  destination: string
  eta_min: number
}

export interface RouteHistorySnapshot {
  truck_id: number
  unit_number: string
  driver_name: string
  driver_code: string
  order_ordnos: string[]
  destinations: string[]
  corridor: string
  reasoning_summary: string
  stops: RouteHistoryStop[]
}

export interface RouteHistoryEntry {
  id: number
  created_at: string
  event_type: string
  note: string
  truck_id: number
  unit_number: string
  snapshot: RouteHistorySnapshot
}

export interface RouteHistoryListResponse {
  truck_id: number | null
  unit_number: string
  entries: RouteHistoryEntry[]
}

export interface SimulatedTruck {
  truck_id: number
  unit_number: string
  delivered_order_ids: number[]
  delivered_ordnos: string[]
  remaining_order_ids: number[]
  current_address: string
  current_lat: number | null
  current_lng: number | null
  path: MapPoint[]
}

export interface SimulateResponse {
  trucks_moved: SimulatedTruck[]
  summary: {
    trucks_moved: number
    orders_delivered: number
    orders_remaining: number
  }
}

export interface DispatchReject {
  truck_id: number
  unit_number: string
  reason: string
}

export interface DispatchResponse {
  order_id: number
  ordno: string
  chosen_truck_id: number | null
  chosen_unit_number: string | null
  travel_min_to_pickup: number | null
  reason: string
  rejects: DispatchReject[]
  assignment: TruckAssignment | null
}

export interface BreakdownReportResponse {
  broken_truck_id: number
  broken_unit_number: string
  broken_driver_name: string | null
  broken_driver_code: string | null
  breakdown_address: string
  breakdown_lat: number | null
  breakdown_lng: number | null
  delivered_order_ids: number[]
  delivered_ordnos: string[]
  remaining_order_ids: number[]
  remaining_ordnos: string[]
  recommended_truck_id: number | null
  recommended_unit_number: string | null
  travel_min_to_breakdown: number | null
  reason: string
  rejects: DispatchReject[]
  preview_assignment: TruckAssignment | null
}

export interface BreakdownApproveResponse {
  broken_truck_id: number
  broken_unit_number: string
  rescue_truck_id: number | null
  rescue_unit_number: string | null
  travel_min_to_breakdown: number | null
  reason: string
  rejects: DispatchReject[]
  assignment: TruckAssignment | null
  transferred_order_ids: number[]
  transferred_ordnos: string[]
}

export interface CancelResponse {
  cancelled_order_id: number
  ordno: string
  truck_id: number | null
  unit_number: string | null
  reason: string
  assignment: TruckAssignment | null
  remaining_order_ids: number[]
  remaining_ordnos: string[]
}

export interface DriverAbsenceResponse {
  driver_id: number
  driver_name: string
  driver_code: string
  truck_id: number | null
  unit_number: string | null
  orders_freed: number
  reason: string
  plan: OptimizeResponse | null
}

export const VEHICLE_CLASSES = ['truck', 'tractor', 'van'] as const
export const TRAILER_SIZES = ['none', 'ft53'] as const
export const TRUCK_STATUSES = ['available', 'assigned', 'out_of_service'] as const
export const DRIVER_STATUSES = ['available', 'assigned', 'off', 'out_of_service'] as const
export const LICENCE_CLASSES = ['G', 'DZ', 'AZ'] as const
export const EQUIPMENT_OPTIONS = ['any', 'truck', 'trailer_53', 'tractor', 'van'] as const
export const SERVICE_OPTIONS = [
  'LTL',
  'OVERNIGHT',
  'RUSH',
  'SAME DAY',
  'OUT OF TOWN',
  'AFTER HOURS',
  'FLAT BED',
  'FTL',
  'EXPEDITE',
  'OTHER',
] as const
