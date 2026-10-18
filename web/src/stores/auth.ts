import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import * as authApi from '@/api/auth'
import type { User } from '@/types'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const bootstrapped = ref(false)

  const isAuthenticated = computed(() => user.value !== null)

  async function login(email: string, password: string) {
    user.value = await authApi.login(email, password)
  }

  async function logout() {
    try {
      await authApi.logout()
    } finally {
      user.value = null
    }
  }

  async function fetchMe() {
    try {
      user.value = await authApi.fetchMe()
    } catch {
      user.value = null
    } finally {
      bootstrapped.value = true
    }
  }

  return {
    user,
    bootstrapped,
    isAuthenticated,
    login,
    logout,
    fetchMe,
  }
})
