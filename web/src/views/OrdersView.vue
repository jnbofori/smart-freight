<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'

import * as optimizeApi from '@/api/optimize'
import * as ordersApi from '@/api/orders'
import {
  EQUIPMENT_OPTIONS,
  SERVICE_OPTIONS,
  type Order,
  type OrderPayload,
} from '@/types'

const loading = ref(false)
const saving = ref(false)
const dispatchingId = ref<number | null>(null)
const orders = ref<Order[]>([])
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)

const emptyForm = (): OrderPayload => ({
  ordno: '',
  reference: null,
  origin_city: '',
  destination_city: '',
  origin_address: '',
  destination_address: '',
  weight_lbs: 0,
  skid_spots: 0,
  linear_feet: 0,
  dim_weight: null,
  pieces: 1,
  stackable: false,
  height_in: null,
  service: 'LTL',
  equipment_required: 'any',
  requires_liftgate: false,
  residential: false,
  inside_delivery: false,
  appointment: false,
  dangerous_goods: false,
  heated: false,
  delivery_window_start: null,
  delivery_window_end: null,
})

const form = reactive<OrderPayload>(emptyForm())

function errorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    return String(err.response?.data?.detail ?? err.message)
  }
  return 'Request failed'
}

async function load() {
  loading.value = true
  try {
    orders.value = await ordersApi.listOrders()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  Object.assign(form, emptyForm())
  dialogVisible.value = true
}

function openEdit(row: Order) {
  editingId.value = row.id
  Object.assign(form, {
    ordno: row.ordno,
    reference: row.reference,
    origin_city: row.origin_city,
    destination_city: row.destination_city,
    origin_address: row.origin_address,
    destination_address: row.destination_address,
    weight_lbs: row.weight_lbs,
    skid_spots: row.skid_spots,
    linear_feet: row.linear_feet,
    dim_weight: row.dim_weight,
    pieces: row.pieces,
    stackable: row.stackable,
    height_in: row.height_in,
    service: row.service,
    equipment_required: row.equipment_required,
    requires_liftgate: row.requires_liftgate,
    residential: row.residential,
    inside_delivery: row.inside_delivery,
    appointment: row.appointment,
    dangerous_goods: row.dangerous_goods,
    heated: row.heated,
    delivery_window_start: row.delivery_window_start,
    delivery_window_end: row.delivery_window_end,
  })
  dialogVisible.value = true
}

function formatWindow(start: string | null, end: string | null): string {
  if (!start && !end) return '—'
  const fmt = (v: string | null) => {
    if (!v) return '?'
    const d = new Date(v)
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }
  return `${fmt(start)}–${fmt(end)}`
}

async function save() {
  if (
    !form.ordno.trim() ||
    !form.origin_city.trim() ||
    !form.destination_city.trim() ||
    !form.origin_address.trim() ||
    !form.destination_address.trim()
  ) {
    ElMessage.warning('Order number, origin, and destination are required')
    return
  }
  saving.value = true
  try {
    const payload: OrderPayload = {
      ...form,
      reference: form.reference || null,
      dim_weight: form.dim_weight ?? null,
      height_in: form.height_in ?? null,
      delivery_window_start: form.delivery_window_start || null,
      delivery_window_end: form.delivery_window_end || null,
    }
    if (editingId.value == null) {
      await ordersApi.createOrder(payload)
      ElMessage.success('Order created')
    } else {
      await ordersApi.updateOrder(editingId.value, payload)
      ElMessage.success('Order updated')
    }
    dialogVisible.value = false
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    saving.value = false
  }
}

async function remove(row: Order) {
  try {
    await ElMessageBox.confirm(`Delete order ${row.ordno}?`, 'Confirm', { type: 'warning' })
    await ordersApi.deleteOrder(row.id)
    ElMessage.success('Order deleted')
    await load()
  } catch (err) {
    if (err === 'cancel' || err === 'close') return
    ElMessage.error(errorMessage(err))
  }
}

async function dispatch(row: Order) {
  dispatchingId.value = row.id
  try {
    const disp = await optimizeApi.dispatchOrder(row.id, true)
    if (disp.chosen_unit_number) {
      const rejectHint = disp.rejects
        .slice(0, 3)
        .map((r) => `${r.unit_number}: ${r.reason}`)
        .join('; ')
      ElMessage.success(
        `${disp.ordno} → ${disp.chosen_unit_number}` +
          (rejectHint ? ` · Others: ${rejectHint}` : ''),
      )
    } else {
      ElMessage.warning(disp.reason || 'No capable truck')
    }
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    dispatchingId.value = null
  }
}

onMounted(load)
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-xl font-semibold text-slate-900">Orders</h1>
        <p class="text-sm text-slate-500">Shipments awaiting vehicle assignment</p>
      </div>
      <el-button type="primary" @click="openCreate">Add order</el-button>
    </div>

    <div class="rounded-lg bg-white p-4 shadow-sm">
      <el-table v-loading="loading" :data="orders" stripe empty-text="No orders">
        <el-table-column prop="ordno" label="Ordno" min-width="110" />
        <el-table-column label="Lane" min-width="280">
          <template #default="{ row }">
            <div class="text-sm leading-snug">
              <div class="text-slate-800">{{ row.origin_address || row.origin_city }}</div>
              <div class="text-slate-400">→ {{ row.destination_address || row.destination_city }}</div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="weight_lbs" label="Weight" width="90" />
        <el-table-column prop="skid_spots" label="Skids" width="80" />
        <el-table-column prop="linear_feet" label="Feet" width="80" />
        <el-table-column prop="height_in" label="Ht in" width="80" />
        <el-table-column prop="service" label="Service" width="120" />
        <el-table-column label="Window" width="130">
          <template #default="{ row }">
            {{ formatWindow(row.delivery_window_start, row.delivery_window_end) }}
          </template>
        </el-table-column>
        <el-table-column prop="equipment_required" label="Equip" width="110" />
        <el-table-column label="Flags" min-width="200">
          <template #default="{ row }">
            <div class="flex flex-wrap gap-1">
              <el-tag v-if="row.stackable" size="small" type="success">Stackable</el-tag>
              <el-tag v-if="row.requires_liftgate" size="small">Liftgate</el-tag>
              <el-tag v-if="row.residential" size="small" type="info">Residential</el-tag>
              <el-tag v-if="row.inside_delivery" size="small" type="info">Inside</el-tag>
              <el-tag v-if="row.appointment" size="small" type="warning">Appt</el-tag>
              <el-tag v-if="row.heated" size="small" type="warning">Heated</el-tag>
              <el-tag v-if="row.dangerous_goods" size="small" type="danger">DG</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="Status" width="110">
          <template #default="{ row }">
            <el-tag
              :type="
                row.status === 'assigned'
                  ? 'success'
                  : row.status === 'delivered'
                    ? 'warning'
                    : 'info'
              "
              size="small"
            >
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="assigned_truck_id" label="Truck" width="80" />
        <el-table-column prop="assigned_driver_id" label="Driver" width="80" />
        <el-table-column label="" width="220" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'unassigned'"
              link
              type="success"
              :loading="dispatchingId === row.id"
              @click="dispatch(row)"
            >
              Dispatch
            </el-button>
            <el-button link type="primary" @click="openEdit(row)">Edit</el-button>
            <el-button link type="danger" @click="remove(row)">Delete</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId == null ? 'Add order' : 'Edit order'"
      width="720px"
      destroy-on-close
    >
      <el-form label-position="top" class="grid grid-cols-2 gap-x-4">
        <el-form-item label="Order number">
          <el-input v-model="form.ordno" />
        </el-form-item>
        <el-form-item label="Reference">
          <el-input v-model="form.reference" />
        </el-form-item>
        <el-form-item label="Origin city">
          <el-input v-model="form.origin_city" />
        </el-form-item>
        <el-form-item label="Destination city">
          <el-input v-model="form.destination_city" />
        </el-form-item>
        <el-form-item label="Origin address" class="col-span-2">
          <el-input v-model="form.origin_address" placeholder="Street, City, ON" />
        </el-form-item>
        <el-form-item label="Destination address" class="col-span-2">
          <el-input v-model="form.destination_address" placeholder="Street, City, ON" />
        </el-form-item>
        <el-form-item label="Weight (lb)">
          <el-input-number v-model="form.weight_lbs" :min="0" class="w-full!" />
        </el-form-item>
        <el-form-item label="Pieces">
          <el-input-number v-model="form.pieces" :min="1" class="w-full!" />
        </el-form-item>
        <el-form-item label="Skid spots">
          <el-input-number v-model="form.skid_spots" :min="0" :step="0.5" class="w-full!" />
        </el-form-item>
        <el-form-item label="Linear feet">
          <el-input-number v-model="form.linear_feet" :min="0" :step="0.5" class="w-full!" />
        </el-form-item>
        <el-form-item label="Dim weight">
          <el-input-number v-model="form.dim_weight" :min="0" class="w-full!" />
        </el-form-item>
        <el-form-item label="Height (in)">
          <el-input-number v-model="form.height_in" :min="0" class="w-full!" />
        </el-form-item>
        <el-form-item label="Service">
          <el-select v-model="form.service" class="w-full">
            <el-option v-for="s in SERVICE_OPTIONS" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item label="Equipment required">
          <el-select v-model="form.equipment_required" class="w-full">
            <el-option v-for="e in EQUIPMENT_OPTIONS" :key="e" :label="e" :value="e" />
          </el-select>
        </el-form-item>
        <el-form-item label="Window start (ISO)">
          <el-input
            v-model="form.delivery_window_start"
            placeholder="2026-10-17T08:00:00"
          />
        </el-form-item>
        <el-form-item label="Window end (ISO)">
          <el-input
            v-model="form.delivery_window_end"
            placeholder="2026-10-17T11:00:00"
          />
        </el-form-item>
        <el-form-item label="Delivery / stack flags" class="col-span-2">
          <div class="flex flex-wrap gap-4">
            <el-checkbox v-model="form.stackable">Stackable</el-checkbox>
            <el-checkbox v-model="form.requires_liftgate">Liftgate</el-checkbox>
            <el-checkbox v-model="form.residential">Residential</el-checkbox>
            <el-checkbox v-model="form.inside_delivery">Inside delivery</el-checkbox>
            <el-checkbox v-model="form.appointment">Appointment</el-checkbox>
            <el-checkbox v-model="form.heated">Heated</el-checkbox>
            <el-checkbox v-model="form.dangerous_goods">Dangerous goods</el-checkbox>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">Cancel</el-button>
        <el-button type="primary" :loading="saving" @click="save">Save</el-button>
      </template>
    </el-dialog>
  </div>
</template>
