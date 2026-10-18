<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'

import * as trucksApi from '@/api/trucks'
import {
  TRAILER_SIZES,
  TRUCK_STATUSES,
  VEHICLE_CLASSES,
  type Truck,
  type TruckPayload,
} from '@/types'

const loading = ref(false)
const saving = ref(false)
const trucks = ref<Truck[]>([])
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)

const emptyForm = (): TruckPayload => ({
  unit_number: '',
  vehicle_class: 'truck',
  axle_count: 2,
  max_weight_lbs: null,
  max_skid_spots: null,
  max_linear_feet: null,
  max_interior_height_in: null,
  has_trailer: false,
  trailer_unit: null,
  trailer_size_class: 'none',
  has_liftgate: false,
  has_dock_height: true,
  heated: false,
  home_terminal_city: '',
  current_address: '',
  current_lat: null,
  current_lng: null,
  status: 'available',
})

const form = reactive<TruckPayload>(emptyForm())

function errorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    return String(err.response?.data?.detail ?? err.message)
  }
  return 'Request failed'
}

async function load() {
  loading.value = true
  try {
    trucks.value = await trucksApi.listTrucks()
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

function openEdit(row: Truck) {
  editingId.value = row.id
  Object.assign(form, {
    unit_number: row.unit_number,
    vehicle_class: row.vehicle_class,
    axle_count: row.axle_count,
    max_weight_lbs: row.max_weight_lbs,
    max_skid_spots: row.max_skid_spots,
    max_linear_feet: row.max_linear_feet,
    max_interior_height_in: row.max_interior_height_in,
    has_trailer: row.has_trailer,
    trailer_unit: row.trailer_unit,
    trailer_size_class: row.trailer_size_class,
    has_liftgate: row.has_liftgate,
    has_dock_height: row.has_dock_height,
    heated: row.heated,
    home_terminal_city: row.home_terminal_city,
    current_address: row.current_address || '',
    current_lat: row.current_lat,
    current_lng: row.current_lng,
    status: row.status,
  })
  dialogVisible.value = true
}

async function save() {
  if (!form.unit_number.trim()) {
    ElMessage.warning('Unit number is required')
    return
  }
  saving.value = true
  try {
    const payload: TruckPayload = {
      ...form,
      max_weight_lbs: form.max_weight_lbs || null,
      max_skid_spots: form.max_skid_spots ?? null,
      max_linear_feet: form.max_linear_feet ?? null,
      max_interior_height_in: form.max_interior_height_in || null,
      trailer_unit: form.trailer_unit || null,
    }
    if (editingId.value == null) {
      await trucksApi.createTruck(payload)
      ElMessage.success('Truck created')
    } else {
      await trucksApi.updateTruck(editingId.value, payload)
      ElMessage.success('Truck updated')
    }
    dialogVisible.value = false
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    saving.value = false
  }
}

async function remove(row: Truck) {
  try {
    await ElMessageBox.confirm(`Delete ${row.unit_number}?`, 'Confirm', { type: 'warning' })
    await trucksApi.deleteTruck(row.id)
    ElMessage.success('Truck deleted')
    await load()
  } catch (err) {
    if (err === 'cancel' || err === 'close') return
    ElMessage.error(errorMessage(err))
  }
}

onMounted(load)
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-xl font-semibold text-slate-900">Trucks</h1>
        <p class="text-sm text-slate-500">Fleet capacity and equipment capabilities</p>
      </div>
      <el-button type="primary" @click="openCreate">Add truck</el-button>
    </div>

    <div class="rounded-lg bg-white p-4 shadow-sm">
      <el-table v-loading="loading" :data="trucks" stripe empty-text="No trucks">
        <el-table-column prop="unit_number" label="Unit" min-width="110" />
        <el-table-column prop="vehicle_class" label="Class" width="100" />
        <el-table-column prop="axle_count" label="Axles" width="80" />
        <el-table-column prop="max_weight_lbs" label="Max lb" width="100" />
        <el-table-column prop="max_skid_spots" label="Skids" width="80" />
        <el-table-column prop="max_linear_feet" label="Feet" width="80" />
        <el-table-column prop="max_interior_height_in" label="Height in" width="100" />
        <el-table-column label="Trailer" min-width="120">
          <template #default="{ row }">
            <span v-if="row.has_trailer">{{ row.trailer_unit || row.trailer_size_class }}</span>
            <span v-else class="text-slate-400">—</span>
          </template>
        </el-table-column>
        <el-table-column label="Flags" min-width="160">
          <template #default="{ row }">
            <div class="flex flex-wrap gap-1">
              <el-tag v-if="row.has_liftgate" size="small">Liftgate</el-tag>
              <el-tag v-if="row.heated" size="small" type="warning">Heated</el-tag>
              <el-tag v-if="row.has_dock_height" size="small" type="info">Dock</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="home_terminal_city" label="Terminal" min-width="110" />
        <el-table-column prop="current_address" label="Current place" min-width="140" show-overflow-tooltip />
        <el-table-column prop="status" label="Status" width="120" />
        <el-table-column label="" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">Edit</el-button>
            <el-button link type="danger" @click="remove(row)">Delete</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId == null ? 'Add truck' : 'Edit truck'"
      width="640px"
      destroy-on-close
    >
      <el-form label-position="top" class="grid grid-cols-2 gap-x-4">
        <el-form-item label="Unit number" class="col-span-2">
          <el-input v-model="form.unit_number" placeholder="Truck #202" />
        </el-form-item>
        <el-form-item label="Vehicle class">
          <el-select v-model="form.vehicle_class" class="w-full">
            <el-option v-for="c in VEHICLE_CLASSES" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="Axle count">
          <el-input-number v-model="form.axle_count" :min="2" :max="8" class="w-full!" />
        </el-form-item>
        <el-form-item label="Max weight (lb)">
          <el-input-number v-model="form.max_weight_lbs" :min="1" controls-position="right" class="w-full!" />
        </el-form-item>
        <el-form-item label="Max skid spots">
          <el-input-number v-model="form.max_skid_spots" :min="0" controls-position="right" class="w-full!" />
        </el-form-item>
        <el-form-item label="Max linear feet">
          <el-input-number v-model="form.max_linear_feet" :min="0" controls-position="right" class="w-full!" />
        </el-form-item>
        <el-form-item label="Interior height (in)">
          <el-input-number
            v-model="form.max_interior_height_in"
            :min="1"
            controls-position="right"
            class="w-full!"
          />
        </el-form-item>
        <el-form-item label="Trailer size">
          <el-select v-model="form.trailer_size_class" class="w-full">
            <el-option v-for="s in TRAILER_SIZES" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item label="Trailer unit">
          <el-input v-model="form.trailer_unit" placeholder="Trailer #530129" />
        </el-form-item>
        <el-form-item label="Home terminal">
          <el-input v-model="form.home_terminal_city" />
        </el-form-item>
        <el-form-item label="Current place" class="col-span-2">
          <el-input
            v-model="form.current_address"
            placeholder="Defaults to home terminal; set after Simulate"
          />
        </el-form-item>
        <el-form-item label="Status">
          <el-select v-model="form.status" class="w-full">
            <el-option v-for="s in TRUCK_STATUSES" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item label="Capabilities" class="col-span-2">
          <div class="flex flex-wrap gap-4">
            <el-checkbox v-model="form.has_trailer">Has trailer</el-checkbox>
            <el-checkbox v-model="form.has_liftgate">Liftgate</el-checkbox>
            <el-checkbox v-model="form.has_dock_height">Dock height</el-checkbox>
            <el-checkbox v-model="form.heated">Heated</el-checkbox>
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
