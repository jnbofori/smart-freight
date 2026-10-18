<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'

import * as driversApi from '@/api/drivers'
import {
  DRIVER_STATUSES,
  LICENCE_CLASSES,
  type Driver,
  type DriverPayload,
} from '@/types'

const loading = ref(false)
const saving = ref(false)
const drivers = ref<Driver[]>([])
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)

const emptyForm = (): DriverPayload => ({
  code: '',
  name: '',
  status: 'available',
  licence_class: 'DZ',
  can_dangerous_goods: false,
  can_heated: false,
  can_liftgate_runs: true,
  shift_start_min: 6 * 60,
  shift_end_min: 20 * 60,
  max_duty_hours: 13,
  max_drive_hours: 13,
  home_terminal_city: '',
  truck_id: 1,
})

const form = reactive<DriverPayload>(emptyForm())

function minsToLabel(mins: number): string {
  const h = Math.floor(mins / 60)
  const m = mins % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

function errorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    return String(err.response?.data?.detail ?? err.message)
  }
  return 'Request failed'
}

async function load() {
  loading.value = true
  try {
    drivers.value = await driversApi.listDrivers()
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

function openEdit(row: Driver) {
  editingId.value = row.id
  Object.assign(form, {
    code: row.code,
    name: row.name,
    status: row.status,
    licence_class: row.licence_class,
    can_dangerous_goods: row.can_dangerous_goods,
    can_heated: row.can_heated,
    can_liftgate_runs: row.can_liftgate_runs,
    shift_start_min: row.shift_start_min,
    shift_end_min: row.shift_end_min,
    max_duty_hours: row.max_duty_hours,
    max_drive_hours: row.max_drive_hours,
    home_terminal_city: row.home_terminal_city,
    truck_id: row.truck_id,
  })
  dialogVisible.value = true
}

async function save() {
  if (!form.code.trim() || !form.name.trim()) {
    ElMessage.warning('Code and name are required')
    return
  }
  saving.value = true
  try {
    if (editingId.value == null) {
      await driversApi.createDriver({ ...form })
      ElMessage.success('Driver created')
    } else {
      await driversApi.updateDriver(editingId.value, { ...form })
      ElMessage.success('Driver updated')
    }
    dialogVisible.value = false
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    saving.value = false
  }
}

async function remove(row: Driver) {
  try {
    await ElMessageBox.confirm(`Delete driver ${row.code}?`, 'Confirm', { type: 'warning' })
    await driversApi.deleteDriver(row.id)
    ElMessage.success('Driver deleted')
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
        <h1 class="text-xl font-semibold text-slate-900">Drivers</h1>
        <p class="text-sm text-slate-500">Availability, licences, and working hours</p>
      </div>
      <el-button type="primary" @click="openCreate">Add driver</el-button>
    </div>

    <div class="rounded-lg bg-white p-4 shadow-sm">
      <el-table v-loading="loading" :data="drivers" stripe empty-text="No drivers">
        <el-table-column prop="code" label="Code" width="90" />
        <el-table-column prop="name" label="Name" min-width="160" />
        <el-table-column prop="licence_class" label="Licence" width="90" />
        <el-table-column label="Shift" width="120">
          <template #default="{ row }">
            {{ minsToLabel(row.shift_start_min) }}–{{ minsToLabel(row.shift_end_min) }}
          </template>
        </el-table-column>
        <el-table-column prop="max_duty_hours" label="Max duty h" width="100" />
        <el-table-column prop="max_drive_hours" label="Max drive h" width="110" />
        <el-table-column label="Quals" min-width="180">
          <template #default="{ row }">
            <div class="flex flex-wrap gap-1">
              <el-tag v-if="row.can_dangerous_goods" size="small" type="danger">DG</el-tag>
              <el-tag v-if="row.can_heated" size="small" type="warning">Heated</el-tag>
              <el-tag v-if="row.can_liftgate_runs" size="small">Liftgate</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="home_terminal_city" label="Terminal" min-width="110" />
        <el-table-column prop="truck_id" label="Truck ID" width="90" />
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
      :title="editingId == null ? 'Add driver' : 'Edit driver'"
      width="640px"
      destroy-on-close
    >
      <el-form label-position="top" class="grid grid-cols-2 gap-x-4">
        <el-form-item label="Code">
          <el-input v-model="form.code" />
        </el-form-item>
        <el-form-item label="Name">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="Licence">
          <el-select v-model="form.licence_class" class="w-full">
            <el-option v-for="c in LICENCE_CLASSES" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="Status">
          <el-select v-model="form.status" class="w-full">
            <el-option v-for="s in DRIVER_STATUSES" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item label="Shift start (min from midnight)">
          <el-input-number v-model="form.shift_start_min" :min="0" :max="1440" class="w-full!" />
        </el-form-item>
        <el-form-item label="Shift end (min from midnight)">
          <el-input-number v-model="form.shift_end_min" :min="0" :max="1440" class="w-full!" />
        </el-form-item>
        <el-form-item label="Max duty hours">
          <el-input-number v-model="form.max_duty_hours" :min="1" :max="24" :step="0.5" class="w-full!" />
        </el-form-item>
        <el-form-item label="Max drive hours">
          <el-input-number v-model="form.max_drive_hours" :min="1" :max="24" :step="0.5" class="w-full!" />
        </el-form-item>
        <el-form-item label="Home terminal">
          <el-input v-model="form.home_terminal_city" />
        </el-form-item>
        <el-form-item label="Truck ID">
          <el-input-number v-model="form.truck_id" :min="1" class="w-full!" />
        </el-form-item>
        <el-form-item label="Qualifications" class="col-span-2">
          <div class="flex flex-wrap gap-4">
            <el-checkbox v-model="form.can_dangerous_goods">Dangerous goods</el-checkbox>
            <el-checkbox v-model="form.can_heated">Heated</el-checkbox>
            <el-checkbox v-model="form.can_liftgate_runs">Liftgate runs</el-checkbox>
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
