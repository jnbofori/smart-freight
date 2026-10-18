import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import AppLayout from '@/layouts/AppLayout.vue'
import LoginView from '@/views/LoginView.vue'
import DriversView from '@/views/DriversView.vue'
import OptimizeView from '@/views/OptimizeView.vue'
import OrdersView from '@/views/OrdersView.vue'
import TrucksView from '@/views/TrucksView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: LoginView,
      meta: { public: true },
    },
    {
      path: '/',
      component: AppLayout,
      children: [
        { path: '', redirect: '/optimize' },
        { path: 'optimize', name: 'optimize', component: OptimizeView },
        { path: 'trucks', name: 'trucks', component: TrucksView },
        { path: 'drivers', name: 'drivers', component: DriversView },
        { path: 'orders', name: 'orders', component: OrdersView },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.bootstrapped) {
    await auth.fetchMe()
  }
  if (to.meta.public) {
    if (auth.isAuthenticated && to.name === 'login') {
      return { name: 'optimize' }
    }
    return true
  }
  if (!auth.isAuthenticated) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  return true
})

export default router
