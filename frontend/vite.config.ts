import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Every backend path the SPA calls. Listed once so adding an API surface is a
// one-line change here rather than a silent 404 that looks like a UI bug.
//
// '/reports/' keeps its trailing slash deliberately. The SPA owns the client
// route '/reports', and the API owns '/reports/<report>'; proxying the bare
// prefix would hand the page itself to the backend, which answers 404. The
// real fix is to namespace the whole API under '/api' — worth doing, but it
// touches the deployed edge config, so it is not bundled into this change.
const API_PATHS = ['/health', '/upload-invoice', '/clear-cache', '/invoices', '/products', '/item-types', '/reports/']

// Overridable so the dev server can point at a backend running somewhere other
// than the default port — e.g. verifying a branch against a local instance
// while the containerised one still holds :8000.
const target = process.env.VITE_API_TARGET || 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: Object.fromEntries(
      API_PATHS.map((path) => [path, { target, changeOrigin: true, secure: false }])
    )
  }
})
