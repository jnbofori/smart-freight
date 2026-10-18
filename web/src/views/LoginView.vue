<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import axios from 'axios'

import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const formRef = ref<FormInstance>()
const loading = ref(false)
const form = reactive({
  email: 'dispatcher@transontario.ca',
  password: 'changeme',
})

const rules: FormRules = {
  email: [
    { required: true, message: 'Email is required', trigger: 'blur' },
    { type: 'email', message: 'Enter a valid email', trigger: 'blur' },
  ],
  password: [{ required: true, message: 'Password is required', trigger: 'blur' }],
}

async function onSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  try {
    await auth.login(form.email, form.password)
    ElMessage.success('Welcome back')
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/optimize'
    await router.push(redirect)
  } catch (err) {
    const detail = axios.isAxiosError(err)
      ? (err.response?.data?.detail ?? err.message)
      : 'Login failed'
    ElMessage.error(String(detail))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="flex min-h-full items-center justify-center bg-slate-200 px-4">
    <div class="w-full max-w-md rounded-lg bg-white p-8 shadow-sm">
      <div class="mb-6">
        <div class="text-xs uppercase tracking-wider text-slate-400">Trans Ontario</div>
        <h1 class="text-2xl font-semibold text-slate-900">Smart Freight</h1>
        <p class="mt-1 text-sm text-slate-500">Sign in to plan loads and assign capacity.</p>
      </div>

      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent>
        <el-form-item label="Email" prop="email">
          <el-input v-model="form.email" type="email" autocomplete="username" />
        </el-form-item>
        <el-form-item label="Password" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            autocomplete="current-password"
            @keyup.enter="onSubmit"
          />
        </el-form-item>
        <el-button type="primary" class="w-full" :loading="loading" @click="onSubmit">
          Login
        </el-button>
      </el-form>

      <p class="mt-4 text-xs text-slate-400">
        Demo: dispatcher@transontario.ca / changeme
      </p>
    </div>
  </div>
</template>
