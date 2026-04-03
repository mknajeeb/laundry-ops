import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Must match where Flask runs: `python run.py` uses port 8000 by default.
// Override: VITE_DEV_API_PROXY=http://127.0.0.1:5000 npm run dev
const backend = process.env.VITE_DEV_API_PROXY || 'http://127.0.0.1:8000'

const API_PREFIXES = [
  'auth',
  'api',
  'dashboard',
  'orders',
  'checkout',
  'checkout_bulk',
  'checkout_log',
  'checkout_undo',
  'upload_orders',
  'upload_conflicts',
  'upload_batches',
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

const proxy = Object.fromEntries(
  API_PREFIXES.map((p) => [`/${p}`, { target: backend, changeOrigin: true }])
)

export default defineConfig({
  plugins: [react()],
  server: {
    port: Number(process.env.VITE_DEV_PORT || 5052),
    proxy,
    // Avoid stale UI during local dev (browser caching the old JS graph).
    headers: {
      'Cache-Control': 'no-store',
    },
  },
})
