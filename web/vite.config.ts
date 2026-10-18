import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import type { ProxyOptions } from 'vite'
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'

const apiTarget = process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000'

/** Proxy API calls, but let SPA refreshes (Accept: text/html) hit Vite. */
function apiProxy(): ProxyOptions {
  return {
    target: apiTarget,
    changeOrigin: true,
    bypass(req) {
      const accept = req.headers.accept ?? ''
      if (accept.includes('text/html')) {
        return '/index.html'
      }
    },
  }
}

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // Same-origin proxy so auth cookies work with localhost vs 127.0.0.1
      '/auth': apiProxy(),
      '/trucks': apiProxy(),
      '/orders': apiProxy(),
      '/drivers': apiProxy(),
      '/optimize': apiProxy(),
      '/health': apiProxy(),
    },
  },
})
