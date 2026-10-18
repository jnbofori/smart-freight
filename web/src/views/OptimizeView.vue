<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'

import * as optimizeApi from '@/api/optimize'
import * as ordersApi from '@/api/orders'
import LoadVisualization from '@/components/LoadVisualization.vue'
import RouteMap from '@/components/RouteMap.vue'
import type {
  BreakdownApproveResponse,
  BreakdownReportResponse,
  CancelResponse,
  DispatchResponse,
  DriverAbsenceResponse,
  OptimizeResponse,
  Order,
  SimulateResponse,
  TruckAssignment,
} from '@/types'

const PROGRESS_STEPS = [
  { id: 'fleet', label: 'Loading fleet, drivers, and open orders' },
  { id: 'geocode', label: 'Geocoding delivery addresses' },
  { id: 'travel', label: 'Fetching live travel times and weather' },
  { id: 'assign', label: 'Assigning orders to trucks by corridor' },
  { id: 'reorder', label: 'Optimizing stop order (2-opt)' },
  { id: 'routes', label: 'Building route maps and capacity plans' },
] as const

/** Advance step index after these delays (ms) while the API request runs. */
const STEP_DELAYS_MS = [0, 2500, 8000, 18000, 32000, 48000]

const loading = ref(false)
const resetting = ref(false)
const simulating = ref(false)
const dispatching = ref(false)
const breakingDown = ref(false)
const result = ref<OptimizeResponse | null>(null)
const simulateResult = ref<SimulateResponse | null>(null)
const dispatchResult = ref<DispatchResponse | null>(null)
const breakdownReport = ref<BreakdownReportResponse | null>(null)
const breakdownApprove = ref<BreakdownApproveResponse | null>(null)
const absenceResult = ref<DriverAbsenceResponse | null>(null)
const persistedPlan = ref(false)
const vizOpen = ref(false)
const vizAssignment = ref<TruckAssignment | null>(null)
const pickupDialogOpen = ref(false)
const breakdownDialogOpen = ref(false)
const breakdownTruckId = ref<number | null>(null)
const approvalDialogOpen = ref(false)
const absenceDialogOpen = ref(false)
const absenceDriverId = ref<number | null>(null)
const reportingAbsence = ref(false)
const orderDialogOpen = ref(false)
const orderDetail = ref<Order | null>(null)
const orderDetailLoading = ref(false)
const cancellingOrder = ref(false)

const breakdownCandidates = computed(() =>
  (result.value?.assignments ?? []).filter((a) => (a.route?.stops?.length ?? a.order_ids.length) > 0),
)

const absenceCandidates = computed(() => {
  const seen = new Set<number>()
  const list: { driver_id: number; label: string }[] = []
  for (const a of result.value?.assignments ?? []) {
    if (a.driver_id == null || seen.has(a.driver_id)) continue
    seen.add(a.driver_id)
    list.push({
      driver_id: a.driver_id,
      label: `${a.driver_name || 'Driver'} (${a.driver_code || '—'}) · truck ${a.unit_number}`,
    })
  }
  return list
})

const busy = computed(
  () =>
    loading.value ||
    resetting.value ||
    simulating.value ||
    dispatching.value ||
    breakingDown.value ||
    cancellingOrder.value ||
    reportingAbsence.value,
)
const progressStep = ref(0)
const progressElapsedSec = ref(0)
const persistMode = ref(false)
let stepTimers: number[] = []
let elapsedTimer: number | null = null

const pickupForm = reactive({
  ordno: '',
  origin_city: 'Mississauga',
  destination_city: 'Markham',
  origin_address: '6700 Airport Rd, Mississauga, ON',
  destination_address: '111 Commerce Valley Dr W, Markham, ON',
  weight_lbs: 1200,
  skid_spots: 2,
  linear_feet: 4,
  pieces: 2,
  service: 'RUSH',
  equipment_required: 'any',
  requires_liftgate: false,
  heated: false,
})

const progressPercent = computed(() =>
  Math.min(95, Math.round(((progressStep.value + 1) / PROGRESS_STEPS.length) * 90)),
)

function errorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    return String(err.response?.data?.detail ?? err.message)
  }
  return 'Request failed'
}

function dutyLabel(mins: number): string {
  const total = Math.max(0, Math.round(mins))
  const h = Math.floor(total / 60)
  const m = total % 60
  if (h <= 0) return `${m}m`
  return `${h}h ${String(m).padStart(2, '0')}m`
}

function clockLabel(mins: number): string {
  const total = Math.max(0, Math.round(mins))
  const h = Math.floor(total / 60) % 24
  const m = total % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

function isOutOfService(a: TruckAssignment): boolean {
  return a.truck_status === 'out_of_service'
}

function formatOrderDate(value: string | null | undefined): string {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(d)
}

function statusBadgeType(
  status: string,
): 'success' | 'warning' | 'info' | 'danger' | 'primary' {
  switch (status) {
    case 'assigned':
      return 'primary'
    case 'delivered':
      return 'success'
    case 'unassigned':
      return 'warning'
    case 'cancelled':
      return 'danger'
    default:
      return 'info'
  }
}

function statusLabel(status: string): string {
  if (!status) return '—'
  return status
    .split(/[_\s]+/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(' ')
}

const activeOrderFlags = computed(() => {
  const o = orderDetail.value
  if (!o) return [] as string[]
  const flags: string[] = []
  if (o.stackable) flags.push('Stackable')
  if (o.requires_liftgate) flags.push('Liftgate')
  if (o.residential) flags.push('Residential')
  if (o.inside_delivery) flags.push('Inside Delivery')
  if (o.appointment) flags.push('Appointment')
  if (o.dangerous_goods) flags.push('Dangerous Goods')
  if (o.heated) flags.push('Heated')
  return flags
})

async function openOrderDetail(orderId: number) {
  orderDialogOpen.value = true
  orderDetail.value = null
  orderDetailLoading.value = true
  try {
    orderDetail.value = await ordersApi.getOrder(orderId)
  } catch (err) {
    orderDialogOpen.value = false
    ElMessage.error(errorMessage(err))
  } finally {
    orderDetailLoading.value = false
  }
}

function applyCancelToPlan(cancelled: CancelResponse) {
  if (!result.value || cancelled.truck_id == null) return
  const truckId = cancelled.truck_id
  if (cancelled.assignment) {
    const idx = result.value.assignments.findIndex((a) => a.truck_id === truckId)
    if (idx >= 0) {
      result.value.assignments[idx] = cancelled.assignment
    } else {
      result.value.assignments.push(cancelled.assignment)
    }
  } else {
    result.value.assignments = result.value.assignments.filter((a) => a.truck_id !== truckId)
  }
  result.value.summary = {
    ...result.value.summary,
    orders_assigned: Math.max(0, (result.value.summary.orders_assigned ?? 0) - 1),
    trucks_used: result.value.assignments.length,
    drivers_used: new Set(
      result.value.assignments.map((a) => a.driver_id).filter((id): id is number => id != null),
    ).size,
  }
}

async function cancelAssignedOrder() {
  const order = orderDetail.value
  if (!order || order.status !== 'assigned') return
  try {
    await ElMessageBox.confirm(
      `Cancel order ${order.ordno}? It will be removed from the route and remaining stops re-optimized.`,
      'Cancel order',
      { type: 'warning', confirmButtonText: 'Cancel order', cancelButtonText: 'Keep' },
    )
  } catch {
    return
  }
  cancellingOrder.value = true
  try {
    const cancelled = await optimizeApi.cancelOrder(order.id, true)
    applyCancelToPlan(cancelled)
    orderDialogOpen.value = false
    orderDetail.value = null
    ElMessage.success(cancelled.reason || `Cancelled ${cancelled.ordno}`)
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    cancellingOrder.value = false
  }
}

function clearProgressTimers() {
  for (const t of stepTimers) window.clearTimeout(t)
  stepTimers = []
  if (elapsedTimer != null) {
    window.clearInterval(elapsedTimer)
    elapsedTimer = null
  }
}

function startProgress(persist: boolean) {
  clearProgressTimers()
  persistMode.value = persist
  progressStep.value = 0
  progressElapsedSec.value = 0
  elapsedTimer = window.setInterval(() => {
    progressElapsedSec.value += 1
  }, 1000)
  for (let i = 1; i < STEP_DELAYS_MS.length; i++) {
    const idx = i
    stepTimers.push(
      window.setTimeout(() => {
        if (loading.value) progressStep.value = Math.max(progressStep.value, idx)
      }, STEP_DELAYS_MS[idx]),
    )
  }
}

function openViz(a: TruckAssignment) {
  vizAssignment.value = a
  vizOpen.value = true
}

async function run(persist: boolean) {
  loading.value = true
  result.value = null
  simulateResult.value = null
  dispatchResult.value = null
  breakdownReport.value = null
  breakdownApprove.value = null
  absenceResult.value = null
  startProgress(persist)
  try {
    result.value = await optimizeApi.runOptimize(persist)
    progressStep.value = PROGRESS_STEPS.length - 1
    if (persist && result.value.summary.orders_assigned > 0) {
      persistedPlan.value = true
    }
    ElMessage.success(
      persist
        ? `Assigned ${result.value.summary.orders_assigned} orders`
        : `Dry run: ${result.value.summary.orders_assigned} would be assigned`,
    )
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    clearProgressTimers()
    loading.value = false
  }
}

onBeforeUnmount(() => clearProgressTimers())

async function loadPersistedPlan() {
  try {
    const plan = await optimizeApi.getOptimizePlan()
    if ((plan.summary.orders_assigned ?? 0) > 0) {
      result.value = plan
      persistedPlan.value = true
    }
  } catch {
    // No plan or not authenticated yet — leave empty state
  }
}

onMounted(() => {
  void loadPersistedPlan()
})

async function reset() {
  try {
    await ElMessageBox.confirm(
      'Clear all assignments and set trucks/drivers/orders back to available?',
      'Reset',
      { type: 'warning' },
    )
  } catch {
    return
  }
  resetting.value = true
  try {
    await optimizeApi.resetOptimize()
    result.value = null
    simulateResult.value = null
    dispatchResult.value = null
    breakdownReport.value = null
    breakdownApprove.value = null
    absenceResult.value = null
    persistedPlan.value = false
    vizOpen.value = false
    vizAssignment.value = null
    ElMessage.success('Assignments cleared')
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    resetting.value = false
  }
}

async function simulate() {
  simulating.value = true
  try {
    simulateResult.value = await optimizeApi.simulateMidday()
    const s = simulateResult.value.summary

    // Patch in-memory maps: truck now at current place; only remaining stops
    if (result.value) {
      for (const moved of simulateResult.value.trucks_moved) {
        if (moved.current_lat == null || moved.current_lng == null) continue
        const assignment = result.value.assignments.find((a) => a.truck_id === moved.truck_id)
        if (!assignment?.route) continue

        const stopById = new Map(assignment.route.stops.map((s) => [s.order_id, s]))
        const remainingStops = moved.remaining_order_ids
          .map((id) => stopById.get(id))
          .filter((s): s is NonNullable<typeof s> => s != null)
          .map((stop, i) => ({ ...stop, seq: i }))

        assignment.route = {
          ...assignment.route,
          depot_lat: moved.current_lat,
          depot_lng: moved.current_lng,
          depot_label: moved.current_address,
          truck_at_start: true,
          path: moved.path?.length ? moved.path : [],
          stops: remainingStops,
        }
        assignment.order_ids = remainingStops.map((stop) => stop.order_id)
        assignment.order_ordnos = remainingStops.map((stop) => stop.ordno)
        assignment.destinations = [
          ...new Set(remainingStops.map((stop) => stop.destination_address || stop.destination_city)),
        ]
      }
    }

    ElMessage.success(
      `Mid-day: ${s.trucks_moved} trucks advanced, ${s.orders_delivered} delivered, ${s.orders_remaining} remaining`,
    )
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    simulating.value = false
  }
}

function openPickupDialog() {
  pickupForm.ordno = `PU-${Date.now().toString().slice(-6)}`
  pickupDialogOpen.value = true
}

function openBreakdownDialog() {
  if (!breakdownCandidates.value.length) {
    ElMessage.warning('No trucks with remaining stops — run & persist (and Simulate) first')
    return
  }
  breakdownTruckId.value = breakdownCandidates.value[0]?.truck_id ?? null
  breakdownDialogOpen.value = true
}

function openAbsenceDialog() {
  if (!absenceCandidates.value.length) {
    ElMessage.warning('No drivers on the current plan — run & persist first')
    return
  }
  absenceDriverId.value = absenceCandidates.value[0]?.driver_id ?? null
  absenceDialogOpen.value = true
}

async function submitDriverAbsence() {
  if (absenceDriverId.value == null) {
    ElMessage.warning('Select a driver')
    return
  }
  const pick = absenceCandidates.value.find((d) => d.driver_id === absenceDriverId.value)
  try {
    await ElMessageBox.confirm(
      `Mark ${pick?.label ?? 'this driver'} absent? All assigned orders will be freed and the morning plan re-run without them.`,
      'Driver absence',
      { type: 'warning', confirmButtonText: 'Report absence', cancelButtonText: 'Cancel' },
    )
  } catch {
    return
  }
  reportingAbsence.value = true
  try {
    const res = await optimizeApi.reportDriverAbsence(absenceDriverId.value, true)
    absenceResult.value = res
    absenceDialogOpen.value = false
    simulateResult.value = null
    dispatchResult.value = null
    breakdownReport.value = null
    breakdownApprove.value = null
    if (res.plan) {
      result.value = res.plan
      persistedPlan.value = (res.plan.summary.orders_assigned ?? 0) > 0
    }
    ElMessage.success(res.reason || 'Driver marked absent; plan replanned')
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    reportingAbsence.value = false
  }
}

async function submitBreakdownReport() {
  if (breakdownTruckId.value == null) {
    ElMessage.warning('Select a truck')
    return
  }
  breakingDown.value = true
  try {
    const report = await optimizeApi.reportBreakdown(breakdownTruckId.value)
    breakdownReport.value = report
    breakdownApprove.value = null
    breakdownDialogOpen.value = false

    // Mark broken truck on map at breakdown location if present in result
    if (result.value) {
      const idx = result.value.assignments.findIndex((a) => a.truck_id === report.broken_truck_id)
      if (idx >= 0) {
        const a = result.value.assignments[idx]
        a.truck_status = 'out_of_service'
        if (a.route && report.breakdown_lat != null) {
          a.route = {
            ...a.route,
            depot_lat: report.breakdown_lat,
            depot_lng: report.breakdown_lng,
            depot_label: report.breakdown_address,
            truck_at_start: true,
          }
        }
      }
    }

    if (report.recommended_truck_id != null) {
      approvalDialogOpen.value = true
    } else {
      ElMessage.warning(report.reason || 'No capable rescue truck')
    }
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    breakingDown.value = false
  }
}

async function approveRescueTransfer() {
  const report = breakdownReport.value
  if (!report?.recommended_truck_id) return
  breakingDown.value = true
  try {
    const approved = await optimizeApi.approveBreakdown(
      report.broken_truck_id,
      report.recommended_truck_id,
      true,
    )
    breakdownApprove.value = approved
    approvalDialogOpen.value = false

    if (result.value && approved.assignment) {
      result.value.assignments = result.value.assignments.filter(
        (a) => a.truck_id !== approved.broken_truck_id,
      )
      const idx = result.value.assignments.findIndex(
        (a) => a.truck_id === approved.rescue_truck_id,
      )
      if (idx >= 0) {
        result.value.assignments[idx] = approved.assignment
      } else {
        result.value.assignments.push(approved.assignment)
      }
    }
    ElMessage.success(approved.reason || 'Rescue transfer approved')
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    breakingDown.value = false
  }
}

function cancelRescueTransfer() {
  approvalDialogOpen.value = false
  ElMessage.info(
    breakdownReport.value
      ? `${breakdownReport.value.broken_unit_number} remains OOS; load stranded until approved`
      : 'Breakdown cancelled',
  )
}

async function submitPickup() {
  if (!pickupForm.ordno.trim() || !pickupForm.origin_address.trim()) {
    ElMessage.warning('Ordno and pickup address are required')
    return
  }
  dispatching.value = true
  try {
    const order = await ordersApi.createOrder({
      ordno: pickupForm.ordno.trim(),
      reference: 'Mid-day pickup',
      origin_city: pickupForm.origin_city,
      destination_city: pickupForm.destination_city,
      origin_address: pickupForm.origin_address,
      destination_address: pickupForm.destination_address,
      weight_lbs: pickupForm.weight_lbs,
      skid_spots: pickupForm.skid_spots,
      linear_feet: pickupForm.linear_feet,
      pieces: pickupForm.pieces,
      stackable: false,
      height_in: null,
      service: pickupForm.service,
      equipment_required: pickupForm.equipment_required,
      requires_liftgate: pickupForm.requires_liftgate,
      residential: false,
      inside_delivery: false,
      appointment: false,
      dangerous_goods: false,
      heated: pickupForm.heated,
    })
    const disp = await optimizeApi.dispatchOrder(order.id, true)
    dispatchResult.value = disp
    pickupDialogOpen.value = false

    if (disp.chosen_unit_number && disp.assignment) {
      if (result.value) {
        const idx = result.value.assignments.findIndex(
          (a) => a.truck_id === disp.chosen_truck_id,
        )
        if (idx >= 0) {
          result.value.assignments[idx] = disp.assignment
        } else {
          result.value.assignments.push(disp.assignment)
        }
      } else {
        result.value = {
          assignments: [disp.assignment],
          unassigned: [],
          summary: {
            trucks_used: 1,
            drivers_used: 1,
            orders_assigned: 1,
            orders_unassigned: 0,
            orders_considered: 1,
          },
          planning_date: new Date().toISOString().slice(0, 10),
          routing_mode: 'static',
          weather_summary: '',
        }
      }
      ElMessage.success(
        `${disp.ordno} → ${disp.chosen_unit_number} (${Math.round(disp.travel_min_to_pickup ?? 0)} min to pickup)`,
      )
    } else {
      ElMessage.warning(disp.reason || 'No capable truck')
    }
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    dispatching.value = false
  }
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold text-slate-900">Load optimization</h1>
        <p class="text-sm text-slate-500">
          Corridor routing, truck + driver co-assign, LIFO door unload, live traffic when configured
        </p>
      </div>
      <div class="flex flex-wrap gap-2">
        <el-button :loading="loading" :disabled="busy" @click="run(false)">Dry run</el-button>
        <el-button type="primary" :loading="loading" :disabled="busy" @click="run(true)">
          Run &amp; persist
        </el-button>
        <el-button
          type="warning"
          :loading="simulating"
          :disabled="!persistedPlan || busy"
          @click="simulate"
        >
          Simulate
        </el-button>
        <el-button type="success" plain :loading="dispatching" :disabled="busy" @click="openPickupDialog">
          Add pickup
        </el-button>
        <el-button
          type="danger"
          :loading="breakingDown"
          :disabled="!persistedPlan || busy"
          @click="openBreakdownDialog"
        >
          Simulate breakdown
        </el-button>
        <el-button
          type="warning"
          plain
          :loading="reportingAbsence"
          :disabled="!persistedPlan || busy"
          @click="openAbsenceDialog"
        >
          Simulate driver absence
        </el-button>
        <el-button type="danger" plain :loading="resetting" :disabled="busy" @click="reset">
          Reset
        </el-button>
      </div>
    </div>

    <div
      v-if="simulateResult"
      class="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950"
    >
      <p class="mb-2 font-medium">
        Mid-day simulate:
        {{ simulateResult.summary.trucks_moved }} trucks moved ·
        {{ simulateResult.summary.orders_delivered }} delivered ·
        {{ simulateResult.summary.orders_remaining }} remaining aboard
      </p>
      <ul class="space-y-1 text-amber-900/80">
        <li v-for="t in simulateResult.trucks_moved" :key="t.truck_id">
          <strong>{{ t.unit_number }}</strong> now at {{ t.current_address }}
          (delivered {{ t.delivered_ordnos.join(', ') || '—' }};
          {{ t.remaining_order_ids.length }} left)
        </li>
      </ul>
    </div>

    <div
      v-if="dispatchResult"
      class="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-950"
    >
      <p class="mb-1 font-medium">{{ dispatchResult.reason || 'Dispatch result' }}</p>
      <ul v-if="dispatchResult.rejects.length" class="mt-2 max-h-40 space-y-1 overflow-y-auto text-emerald-900/70">
        <li v-for="r in dispatchResult.rejects" :key="r.truck_id">
          {{ r.unit_number }}: {{ r.reason }}
        </li>
      </ul>
    </div>

    <div
      v-if="absenceResult"
      class="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950"
    >
      <p class="mb-1 font-medium">{{ absenceResult.reason }}</p>
      <p class="text-amber-900/80">
        Absent:
        <strong>{{ absenceResult.driver_name }}</strong>
        ({{ absenceResult.driver_code }})
        <span v-if="absenceResult.unit_number"> · truck {{ absenceResult.unit_number }}</span>
        · freed {{ absenceResult.orders_freed }} order(s)
      </p>
    </div>

    <div
      v-if="breakdownReport"
      class="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-950"
    >
      <p class="mb-2 font-medium">{{ breakdownReport.reason }}</p>
      <ul class="space-y-1 text-rose-900/85">
        <li>
          <strong>Broken truck:</strong>
          {{ breakdownReport.broken_unit_number }}
        </li>
        <li>
          <strong>Driver:</strong>
          {{
            breakdownReport.broken_driver_name
              ? `${breakdownReport.broken_driver_name}${
                  breakdownReport.broken_driver_code
                    ? ` (${breakdownReport.broken_driver_code})`
                    : ''
                }`
              : '—'
          }}
        </li>
        <li>
          <strong>Location:</strong>
          {{ breakdownReport.breakdown_address || '—' }}
        </li>
        <li>
          <strong>Fulfilled:</strong>
          {{ breakdownReport.delivered_ordnos.join(', ') || 'none' }}
        </li>
        <li>
          <strong>Remaining:</strong>
          {{ breakdownReport.remaining_ordnos.join(', ') || '—' }}
        </li>
      </ul>
      <p v-if="breakdownReport.rejects.length" class="mt-3 mb-1 font-medium text-rose-900">
        Why other trucks cannot rescue
      </p>
      <ul
        v-if="breakdownReport.rejects.length"
        class="max-h-40 space-y-1 overflow-y-auto text-rose-900/70"
      >
        <li v-for="r in breakdownReport.rejects" :key="r.truck_id">
          {{ r.unit_number }}: {{ r.reason }}
        </li>
      </ul>
    </div>

    <div
      v-if="breakdownApprove"
      class="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-950"
    >
      <p class="mb-1 font-medium">{{ breakdownApprove.reason }}</p>
      <p class="text-emerald-900/80">
        Transferred:
        {{ breakdownApprove.transferred_ordnos.join(', ') || '—' }}
      </p>
    </div>

    <div
      v-if="loading"
      class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm"
      aria-live="polite"
    >
      <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 class="text-base font-semibold text-slate-900">
            {{ persistMode ? 'Running optimization…' : 'Dry run in progress…' }}
          </h2>
          <p class="text-sm text-slate-500">
            Geocoding and live routing can take a minute on first run.
          </p>
        </div>
        <span class="font-mono text-sm text-slate-500">{{ progressElapsedSec }}s</span>
      </div>
      <div class="mb-4 h-2 overflow-hidden rounded-full bg-slate-100">
        <div
          class="h-full rounded-full bg-slate-800 transition-all duration-700 ease-out"
          :style="{ width: `${progressPercent}%` }"
        />
      </div>
      <ol class="space-y-2.5">
        <li
          v-for="(step, i) in PROGRESS_STEPS"
          :key="step.id"
          class="flex items-start gap-3 text-sm"
        >
          <span
            class="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs font-medium"
            :class="
              i < progressStep
                ? 'bg-emerald-100 text-emerald-700'
                : i === progressStep
                  ? 'bg-slate-800 text-white'
                  : 'bg-slate-100 text-slate-400'
            "
          >
            <template v-if="i < progressStep">✓</template>
            <template v-else>{{ i + 1 }}</template>
          </span>
          <span
            :class="
              i < progressStep
                ? 'text-slate-500'
                : i === progressStep
                  ? 'font-medium text-slate-900'
                  : 'text-slate-400'
            "
          >
            {{ step.label }}
            <span v-if="i === progressStep" class="ml-1 inline-block animate-pulse text-slate-400">
              …
            </span>
          </span>
        </li>
      </ol>
    </div>

    <div v-if="result && !loading" class="grid gap-4 sm:grid-cols-5">
      <div class="rounded-lg bg-white p-4 shadow-sm">
        <div class="text-xs uppercase text-slate-400">Considered</div>
        <div class="text-2xl font-semibold">{{ result.summary.orders_considered }}</div>
      </div>
      <div class="rounded-lg bg-white p-4 shadow-sm">
        <div class="text-xs uppercase text-slate-400">Assigned</div>
        <div class="text-2xl font-semibold text-emerald-700">{{ result.summary.orders_assigned }}</div>
      </div>
      <div class="rounded-lg bg-white p-4 shadow-sm">
        <div class="text-xs uppercase text-slate-400">Unassigned</div>
        <div class="text-2xl font-semibold text-amber-700">{{ result.summary.orders_unassigned }}</div>
      </div>
      <div class="rounded-lg bg-white p-4 shadow-sm">
        <div class="text-xs uppercase text-slate-400">Trucks used</div>
        <div class="text-2xl font-semibold">{{ result.summary.trucks_used }}</div>
      </div>
      <div class="rounded-lg bg-white p-4 shadow-sm">
        <div class="text-xs uppercase text-slate-400">Drivers used</div>
        <div class="text-2xl font-semibold">{{ result.summary.drivers_used }}</div>
      </div>
    </div>

    <div
      v-if="result && !loading"
      class="flex flex-wrap items-center gap-3 text-sm text-slate-500"
    >
      <span>Planning date: {{ result.planning_date }}</span>
      <el-tag size="small" :type="result.routing_mode === 'live' ? 'success' : 'info'">
        Routing: {{ result.routing_mode }}
      </el-tag>
      <span v-if="result.weather_summary" class="text-amber-700">
        Weather: {{ result.weather_summary }}
      </span>
    </div>

    <div
      v-if="!result && !loading"
      class="rounded-lg bg-white p-8 text-center text-slate-500 shadow-sm"
    >
      <p class="mb-1 font-medium text-slate-700">No plan yet</p>
      <p class="text-sm">
        Run a dry run or persist to assign orders, build stop sequences, and show routes on the map.
      </p>
    </div>

    <template v-if="result && !loading">
      <div class="rounded-lg bg-white p-4 shadow-sm">
        <h2 class="mb-3 text-base font-semibold">Assignments</h2>
        <el-collapse v-if="result.assignments.length">
          <el-collapse-item
            v-for="a in result.assignments"
            :key="a.truck_id"
            :name="a.truck_id"
            :class="isOutOfService(a) ? 'sf-oos-assignment' : undefined"
          >
            <template #title>
              <span class="flex flex-wrap items-center gap-2 pr-2">
                <span>
                  {{ a.unit_number }} · {{ a.driver_name || 'No driver' }}
                  ({{ a.driver_code || '—' }}) · {{ a.route?.corridor || '—' }} —
                  {{ a.order_ordnos.length }} orders → {{ a.destinations.join(', ') }}
                </span>
                <el-tag v-if="isOutOfService(a)" type="danger" size="small" effect="dark">
                  Broken / OOS
                </el-tag>
              </span>
            </template>
            <div
              class="mb-3 rounded-md p-2"
              :class="isOutOfService(a) ? 'bg-rose-50 ring-1 ring-rose-200' : ''"
            >
              <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
                <div class="grid flex-1 gap-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
                  <div>
                    Driver:
                    <strong>{{ a.driver_name || '—' }}</strong>
                    <span v-if="a.driver_code" class="text-slate-400"> (#{{ a.driver_code }})</span>
                  </div>
                  <div>
                    Duty used:
                    <strong>{{ dutyLabel(a.duty_minutes_used) }}</strong>
                  </div>
                  <div>
                    Weight:
                    <strong>{{ a.usage.weight_lbs.toFixed(0) }}</strong> lb
                    <span class="text-slate-400">
                      ({{ a.usage.remaining_weight_lbs.toFixed(0) }} left)
                    </span>
                  </div>
                  <div>
                    Drive:
                    <strong>{{ dutyLabel(a.route?.total_drive_min ?? 0) }}</strong>
                    <span v-if="a.route?.total_distance_m" class="text-slate-400">
                      ({{ (a.route.total_distance_m / 1000).toFixed(1) }} km)
                    </span>
                  </div>
                </div>
                <el-button type="primary" plain size="small" @click="openViz(a)">
                  Visualize load
                </el-button>
              </div>
              <p v-if="isOutOfService(a)" class="mb-3 text-sm font-medium text-rose-800">
                Truck is out of service at
                {{ a.route?.depot_label || 'current location' }} — remaining load pending rescue.
              </p>
              <div v-if="a.route" class="mb-3">
                <RouteMap
                  :key="`${a.truck_id}-${a.order_ids.join('-')}-${a.route.path?.length ?? 0}-${a.truck_status}`"
                  :route="a.route"
                  :unit-number="a.unit_number"
                  :out-of-service="isOutOfService(a)"
                />
              </div>
            </div>
            <div v-if="a.route?.stops?.length" class="mb-3 overflow-x-auto">
              <table class="w-full text-left text-sm">
                <thead class="text-xs uppercase text-slate-400">
                  <tr>
                    <th class="py-1 pr-2">Stop</th>
                    <th class="py-1 pr-2">Ordno</th>
                    <th class="py-1 pr-2">Address</th>
                    <th class="py-1 pr-2">ETA</th>
                    <th class="py-1 pr-2">Travel</th>
                    <th class="py-1">Weather</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="s in a.route.stops"
                    :key="s.order_id"
                    class="cursor-pointer border-t border-slate-100 hover:bg-slate-50"
                    title="View order details"
                    @click="openOrderDetail(s.order_id)"
                  >
                    <td class="py-1 pr-2">#{{ s.seq + 1 }}</td>
                    <td class="py-1 pr-2 text-sky-700 underline-offset-2 hover:underline">
                      {{ s.ordno }}
                    </td>
                    <td class="py-1 pr-2">{{ s.destination_address || s.destination_city }}</td>
                    <td class="py-1 pr-2">{{ clockLabel(s.eta_min) }}</td>
                    <td class="py-1 pr-2">{{ dutyLabel(s.travel_min_from_prev) }}</td>
                    <td class="py-1 text-slate-500">{{ s.weather_note || '—' }}</td>
                  </tr>
                </tbody>
              </table>
              <p class="mt-1 text-xs text-slate-400">
                Stop #1 unloads first (door / LIFO). Click a row for order details.
              </p>
            </div>
            <div class="mb-2">
              <el-tag v-for="ordno in a.order_ordnos" :key="ordno" class="mr-1 mb-1" size="small">
                {{ ordno }}
              </el-tag>
            </div>
            <ul class="list-disc space-y-1 pl-5 text-sm text-slate-600">
              <li v-for="(r, i) in a.rationales" :key="i">{{ r }}</li>
            </ul>
          </el-collapse-item>
        </el-collapse>
        <p v-else class="text-sm text-slate-500">No assignments in this run.</p>
      </div>

      <div class="rounded-lg bg-white p-4 shadow-sm">
        <h2 class="mb-3 text-base font-semibold">Unassigned</h2>
        <el-table v-if="result.unassigned.length" :data="result.unassigned" stripe>
          <el-table-column prop="ordno" label="Ordno" width="140" />
          <el-table-column prop="reason" label="Reason" min-width="320" />
        </el-table>
        <p v-else class="text-sm text-emerald-700">All considered orders were assigned.</p>
      </div>
    </template>

    <el-dialog
      v-model="vizOpen"
      :title="
        vizAssignment
          ? `Load: ${vizAssignment.unit_number}${vizAssignment.driver_name ? ' · ' + vizAssignment.driver_name : ''}`
          : 'Load visualization'
      "
      width="920px"
      top="5vh"
      destroy-on-close
    >
      <LoadVisualization v-if="vizAssignment" :assignment="vizAssignment" />
    </el-dialog>

    <el-dialog
      v-model="pickupDialogOpen"
      title="Add mid-day pickup"
      width="560px"
      destroy-on-close
    >
      <p class="mb-4 text-sm text-slate-500">
        Creates a new order and dispatches it to the closest capable truck from its current place.
      </p>
      <el-form label-position="top" class="grid grid-cols-2 gap-x-4">
        <el-form-item label="Ordno" class="col-span-2">
          <el-input v-model="pickupForm.ordno" />
        </el-form-item>
        <el-form-item label="Pickup address" class="col-span-2">
          <el-input v-model="pickupForm.origin_address" />
        </el-form-item>
        <el-form-item label="Pickup city">
          <el-input v-model="pickupForm.origin_city" />
        </el-form-item>
        <el-form-item label="Delivery city">
          <el-input v-model="pickupForm.destination_city" />
        </el-form-item>
        <el-form-item label="Delivery address" class="col-span-2">
          <el-input v-model="pickupForm.destination_address" />
        </el-form-item>
        <el-form-item label="Weight (lb)">
          <el-input-number v-model="pickupForm.weight_lbs" :min="0" class="w-full!" />
        </el-form-item>
        <el-form-item label="Skids">
          <el-input-number v-model="pickupForm.skid_spots" :min="0" class="w-full!" />
        </el-form-item>
        <el-form-item label="Linear feet">
          <el-input-number v-model="pickupForm.linear_feet" :min="0" class="w-full!" />
        </el-form-item>
        <el-form-item label="Pieces">
          <el-input-number v-model="pickupForm.pieces" :min="1" class="w-full!" />
        </el-form-item>
        <el-form-item label="Flags" class="col-span-2">
          <div class="flex flex-wrap gap-4">
            <el-checkbox v-model="pickupForm.requires_liftgate">Liftgate</el-checkbox>
            <el-checkbox v-model="pickupForm.heated">Heated</el-checkbox>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pickupDialogOpen = false">Cancel</el-button>
        <el-button type="primary" :loading="dispatching" @click="submitPickup">
          Create &amp; dispatch
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="breakdownDialogOpen"
      title="Simulate truck breakdown"
      width="480px"
      destroy-on-close
    >
      <p class="mb-4 text-sm text-slate-500">
        Places the truck mid-route, marks it out of service, and proposes the closest capable rescue.
        Remaining freight is not moved until you approve.
      </p>
      <el-form label-position="top">
        <el-form-item label="Truck">
          <el-select v-model="breakdownTruckId" class="w-full" placeholder="Select truck">
            <el-option
              v-for="a in breakdownCandidates"
              :key="a.truck_id"
              :label="`${a.unit_number} · ${a.order_ordnos.length} remaining`"
              :value="a.truck_id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="breakdownDialogOpen = false">Cancel</el-button>
        <el-button type="danger" :loading="breakingDown" @click="submitBreakdownReport">
          Report breakdown
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="absenceDialogOpen"
      title="Simulate driver absence"
      width="480px"
      destroy-on-close
    >
      <p class="mb-4 text-sm text-slate-500">
        Marks the driver off (no-show). All assigned orders are freed and the morning plan is
        re-optimized without that driver — other trucks’ loads may reshuffle.
      </p>
      <el-form label-position="top">
        <el-form-item label="Driver">
          <el-select v-model="absenceDriverId" class="w-full" placeholder="Select driver">
            <el-option
              v-for="d in absenceCandidates"
              :key="d.driver_id"
              :label="d.label"
              :value="d.driver_id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="absenceDialogOpen = false">Cancel</el-button>
        <el-button type="warning" :loading="reportingAbsence" @click="submitDriverAbsence">
          Report absence
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="orderDialogOpen"
      width="680px"
      destroy-on-close
      class="sf-order-dialog"
      :show-close="true"
    >
      <template #header>
        <div v-if="orderDetail" class="pr-6">
          <div class="flex flex-wrap items-center gap-2">
            <h3 class="m-0 text-lg font-semibold tracking-tight text-slate-900">
              {{ orderDetail.ordno }}
            </h3>
            <el-tag
              :type="statusBadgeType(orderDetail.status)"
              effect="dark"
              round
              size="small"
            >
              {{ statusLabel(orderDetail.status) }}
            </el-tag>
            <el-tag type="info" effect="plain" round size="small">
              {{ orderDetail.service }}
            </el-tag>
          </div>
          <p class="mt-1 mb-0 text-sm text-slate-500">
            {{ orderDetail.reference || 'No reference' }}
            <span class="text-slate-300"> · </span>
            Created {{ formatOrderDate(orderDetail.created_at) }}
          </p>
        </div>
        <div v-else class="text-base font-semibold text-slate-800">Order Details</div>
      </template>

      <div v-if="orderDetailLoading" class="py-12 text-center text-slate-500">Loading…</div>
      <div v-else-if="orderDetail" class="space-y-5 text-sm text-slate-800">
        <section class="rounded-xl bg-slate-50/80 p-4 ring-1 ring-slate-200/80">
          <h4 class="mb-3 text-sm font-semibold text-slate-900">Route</h4>
          <div class="space-y-3">
            <div class="flex gap-3">
              <div
                class="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-teal-600 text-[10px] font-bold text-white"
              >
                A
              </div>
              <div class="min-w-0">
                <div class="text-sm font-semibold text-slate-700">Origin</div>
                <div class="text-slate-900">
                  {{ orderDetail.origin_address || orderDetail.origin_city }}
                </div>
                <div class="text-xs text-slate-500">{{ orderDetail.origin_city }}</div>
              </div>
            </div>
            <div class="ml-3 border-l-2 border-dashed border-slate-200 pl-6">
              <div class="flex gap-3">
                <div
                  class="-ml-[1.625rem] mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-sky-700 text-[10px] font-bold text-white"
                >
                  B
                </div>
                <div class="min-w-0">
                  <div class="text-sm font-semibold text-slate-700">Destination</div>
                  <div class="text-slate-900">
                    {{ orderDetail.destination_address || orderDetail.destination_city }}
                  </div>
                  <div class="text-xs text-slate-500">{{ orderDetail.destination_city }}</div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section>
          <h4 class="mb-3 text-sm font-semibold text-slate-900">Freight</h4>
          <div class="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <div class="rounded-lg bg-white p-3 ring-1 ring-slate-200/80">
              <div class="text-sm font-semibold text-slate-600">Weight</div>
              <div class="mt-0.5 text-base font-semibold tabular-nums text-slate-900">
                {{ orderDetail.weight_lbs.toFixed(0) }}
                <span class="text-sm font-medium text-slate-500">lb</span>
              </div>
            </div>
            <div class="rounded-lg bg-white p-3 ring-1 ring-slate-200/80">
              <div class="text-sm font-semibold text-slate-600">Skid Spots</div>
              <div class="mt-0.5 text-base font-semibold tabular-nums text-slate-900">
                {{ orderDetail.skid_spots }}
              </div>
            </div>
            <div class="rounded-lg bg-white p-3 ring-1 ring-slate-200/80">
              <div class="text-sm font-semibold text-slate-600">Linear Feet</div>
              <div class="mt-0.5 text-base font-semibold tabular-nums text-slate-900">
                {{ orderDetail.linear_feet }}
              </div>
            </div>
            <div class="rounded-lg bg-white p-3 ring-1 ring-slate-200/80">
              <div class="text-sm font-semibold text-slate-600">Pieces</div>
              <div class="mt-0.5 text-base font-semibold tabular-nums text-slate-900">
                {{ orderDetail.pieces }}
              </div>
            </div>
            <div class="rounded-lg bg-white p-3 ring-1 ring-slate-200/80">
              <div class="text-sm font-semibold text-slate-600">Height</div>
              <div class="mt-0.5 text-base font-semibold tabular-nums text-slate-900">
                {{ orderDetail.height_in != null ? `${orderDetail.height_in}"` : '—' }}
              </div>
            </div>
            <div class="rounded-lg bg-white p-3 ring-1 ring-slate-200/80">
              <div class="text-sm font-semibold text-slate-600">Dim Weight</div>
              <div class="mt-0.5 text-base font-semibold tabular-nums text-slate-900">
                {{ orderDetail.dim_weight != null ? orderDetail.dim_weight : '—' }}
              </div>
            </div>
          </div>
        </section>

        <section>
          <h4 class="mb-3 text-sm font-semibold text-slate-900">Requirements</h4>
          <dl class="mb-3 grid gap-3 sm:grid-cols-2">
            <div>
              <dt class="text-sm font-semibold text-slate-600">Equipment</dt>
              <dd class="mt-0.5 text-slate-900">{{ orderDetail.equipment_required }}</dd>
            </div>
            <div>
              <dt class="text-sm font-semibold text-slate-600">Stop Sequence</dt>
              <dd class="mt-0.5 text-slate-900">
                {{ orderDetail.stop_seq != null ? `#${orderDetail.stop_seq + 1}` : '—' }}
              </dd>
            </div>
          </dl>
          <div class="flex flex-wrap gap-1.5">
            <el-tag
              v-for="flag in activeOrderFlags"
              :key="flag"
              type="success"
              effect="light"
              size="small"
              round
            >
              {{ flag }}
            </el-tag>
            <span v-if="!activeOrderFlags.length" class="text-slate-500">
              No special handling flags
            </span>
          </div>
        </section>

        <section>
          <h4 class="mb-3 text-sm font-semibold text-slate-900">Delivery Window</h4>
          <dl class="grid gap-3 sm:grid-cols-2">
            <div class="rounded-lg bg-white p-3 ring-1 ring-slate-200/80">
              <dt class="text-sm font-semibold text-slate-600">Window Start</dt>
              <dd class="mt-0.5 text-slate-900">
                {{ formatOrderDate(orderDetail.delivery_window_start) }}
              </dd>
            </div>
            <div class="rounded-lg bg-white p-3 ring-1 ring-slate-200/80">
              <dt class="text-sm font-semibold text-slate-600">Window End</dt>
              <dd class="mt-0.5 text-slate-900">
                {{ formatOrderDate(orderDetail.delivery_window_end) }}
              </dd>
            </div>
          </dl>
        </section>
      </div>
      <template #footer>
        <div class="flex w-full flex-wrap justify-between gap-2">
          <el-button
            v-if="orderDetail?.status === 'assigned'"
            type="danger"
            plain
            :loading="cancellingOrder"
            :disabled="busy && !cancellingOrder"
            @click="cancelAssignedOrder"
          >
            Cancel order
          </el-button>
          <span v-else />
          <el-button type="primary" @click="orderDialogOpen = false">Close</el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog
      v-model="approvalDialogOpen"
      title="Dispatcher approval — rescue transfer"
      width="560px"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <div v-if="breakdownReport" class="space-y-3 text-sm">
        <ul class="space-y-1.5">
          <li>
            <strong>Broken truck:</strong>
            {{ breakdownReport.broken_unit_number }}
          </li>
          <li>
            <strong>Driver:</strong>
            {{
              breakdownReport.broken_driver_name
                ? `${breakdownReport.broken_driver_name}${
                    breakdownReport.broken_driver_code
                      ? ` (${breakdownReport.broken_driver_code})`
                      : ''
                  }`
                : '—'
            }}
          </li>
          <li>
            <strong>Location:</strong>
            {{ breakdownReport.breakdown_address }}
          </li>
          <li>
            <strong>Fulfilled:</strong>
            {{ breakdownReport.delivered_ordnos.join(', ') || 'none' }}
          </li>
          <li>
            <strong>Remaining:</strong>
            {{ breakdownReport.remaining_ordnos.join(', ') || '—' }}
          </li>
          <li v-if="breakdownReport.recommended_unit_number">
            <strong>Recommended rescue:</strong>
            {{ breakdownReport.recommended_unit_number }}
            ({{ Math.round(breakdownReport.travel_min_to_breakdown ?? 0) }} min to breakdown)
          </li>
        </ul>
        <p v-if="breakdownReport.rejects.length" class="font-medium text-slate-700">
          Why other trucks cannot rescue
        </p>
        <ul
          v-if="breakdownReport.rejects.length"
          class="max-h-36 space-y-1 overflow-y-auto text-slate-600"
        >
          <li v-for="r in breakdownReport.rejects" :key="r.truck_id">
            {{ r.unit_number }}: {{ r.reason }}
          </li>
        </ul>
      </div>
      <template #footer>
        <el-button @click="cancelRescueTransfer">Cancel</el-button>
        <el-button
          type="primary"
          :loading="breakingDown"
          :disabled="!breakdownReport?.recommended_truck_id"
          @click="approveRescueTransfer"
        >
          Approve transfer
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>
