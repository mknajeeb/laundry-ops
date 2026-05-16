import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

const API_PREFIXES = [
  'media',
  'admin',
  'auth',
  'api',
  'dashboard',
  'orders',
  'checkout',
  'checkout_bulk',
  'checkout_log',
  'checkout_undo',
  'upload_orders',
  'upload_orders_portal_csv',
  'upload_conflicts',
  'upload_batches',
  'rinse',
  'employees',
  'issues',
  'order_processing',
  'order_tickets',
  'folder_shift',
  'geofence',
  'attendance',
  'maintenance',
  'inventory',
]

/** @type {import('vite').UserConfigFn} */
export default defineConfig(({ mode }) => {
  // Repo-root `.env`: same PORT as `python run.py` / gunicorn (defaults 8000).
  const root = path.resolve(__dirname, '..')
  const env = loadEnv(mode, root, '')
  const backend =
    env.VITE_DEV_API_PROXY ||
    `http://127.0.0.1:${env.PORT || '8000'}`

  const proxy = Object.fromEntries(
    API_PREFIXES.map((p) => [`/${p}`, { target: backend, changeOrigin: true }])
  )

  return {
    // Use repo-root `.env` (next to Flask DB vars). Only `VITE_*` keys are exposed to the client bundle.
    envDir: root,
    plugins: [react()],
    build: {
      chunkSizeWarningLimit: 900,
      rollupOptions: {
        output: {
          /** Split MUI into its own chunk (large); rest stays in shared vendor to avoid circular deps. */
          manualChunks(id) {
            if (!id.includes('node_modules')) return
            if (id.includes('@mui')) return 'mui'
            return 'vendor'
          },
        },
      },
    },
    server: {
      port: Number(env.VITE_DEV_PORT || 5052),
      proxy,
      // Avoid stale UI during local dev (browser caching the old JS graph).
      headers: {
        'Cache-Control': 'no-store',
      },
    },
  }
})
