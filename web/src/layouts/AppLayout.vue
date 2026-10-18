<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const active = computed(() => route.path)

async function onLogout() {
  await auth.logout()
  ElMessage.success('Logged out')
  await router.push({ name: 'login' })
}
</script>

<template>
  <div class="flex min-h-full">
    <aside class="flex w-56 flex-col border-r border-slate-200 bg-slate-900 text-slate-100">
      <div class="border-b border-slate-700 px-4 py-5">
        <div class="text-xs uppercase tracking-wider text-slate-400">Trans Ontario</div>
        <div class="text-lg font-semibold">Smart Freight</div>
      </div>
      <el-menu
        :default-active="active"
        router
        background-color="#0f172a"
        text-color="#e2e8f0"
        active-text-color="#ffffff"
        class="border-0!"
      >
        <el-menu-item index="/optimize">Optimize</el-menu-item>
        <el-menu-item index="/trucks">Trucks</el-menu-item>
        <el-menu-item index="/drivers">Drivers</el-menu-item>
        <el-menu-item index="/orders">Orders</el-menu-item>
      </el-menu>
    </aside>

    <div class="flex min-w-0 flex-1 flex-col">
      <header class="flex items-center justify-between border-b border-slate-200 bg-white px-6 py-3">
        <div class="text-sm text-slate-500">Dispatcher workspace</div>
        <div class="flex items-center gap-3">
          <span class="text-sm text-slate-700">
            {{ auth.user?.full_name || auth.user?.email }}
          </span>
          <el-button size="small" @click="onLogout">Logout</el-button>
        </div>
      </header>
      <main class="flex-1 p-6">
        <router-view />
      </main>
    </div>
  </div>
</template>
