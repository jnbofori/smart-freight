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
    <aside class="flex w-56 flex-col border-r border-white/10 bg-[#030718] text-[#F2F2F2]">
      <div class="border-b border-white/10 px-3 py-4">
        <img
          src="/trans-ontario-logo.png"
          alt="Trans Ontario Express"
          class="h-auto w-full"
        />
        <div class="mt-2 text-center text-[11px] font-medium tracking-wide text-[#F2F2F2]/70">
          Smart Freight
        </div>
      </div>
      <el-menu
        :default-active="active"
        router
        background-color="#030718"
        text-color="#F2F2F2"
        active-text-color="#FFFFFF"
        class="border-0! [&_.el-menu-item.is-active]:bg-[#1F4AEE]/25"
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
