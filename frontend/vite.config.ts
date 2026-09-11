import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import basicSsl from '@vitejs/plugin-basic-ssl'
import { VitePWA } from 'vite-plugin-pwa'

// Every backend path the SPA calls. Listed once so adding an API surface is a
// one-line change here rather than a silent 404 that looks like a UI bug.
//
// '/reports/' keeps its trailing slash deliberately. The SPA owns the client
// route '/reports', and the API owns '/reports/<report>'; proxying the bare
// prefix would hand the page itself to the backend, which answers 404. The
// real fix is to namespace the whole API under '/api' — worth doing, but it
// touches the deployed edge config, so it is not bundled into this change.
const API_PATHS = ['/health', '/upload-invoice', '/clear-cache', '/invoices', '/products', '/item-types', '/reports/', '/inventory/', '/auth/', '/sales']

// Overridable so the dev server can point at a backend running somewhere other
// than the default port — e.g. verifying a branch against a local instance
// while the containerised one still holds :8000.
const target = process.env.VITE_API_TARGET || 'http://localhost:8000'

// Camera access — the barcode scanner — requires a secure context, and the
// failure when it is missing is misleading: `navigator.mediaDevices` is simply
// undefined, which reads as a permissions problem the user was never asked
// about. `localhost` already counts as secure, so plain `npm run dev` on this
// machine is fine. What is not fine is the case that matters for testing a
// phone: opening the dev server at http://<lan-ip>:5173 from a handset.
//
// `VITE_HTTPS=1 npm run dev` serves over HTTPS with a self-signed certificate
// for exactly that. Opt-in rather than the default because the certificate has
// to be accepted by hand on each device, which is friction nobody developing
// on localhost should pay. Production is HTTPS regardless — Caddy at the edge,
// and the Cloudflare tunnel for dev.pharmagpt.co.
const useHttps = process.env.VITE_HTTPS === '1'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    ...(useHttps ? [basicSsl()] : []),
    // Installable, and able to open with no network at all. A counter that
    // cannot start because the shop's line is down is a counter that cannot
    // bill, so the shell is precached rather than fetched.
    VitePWA({
      registerType: 'autoUpdate',
      injectRegister: 'auto',
      includeAssets: ['favicon.ico', 'apple-touch-icon.png'],
      manifest: {
        name: 'PharmaGPT Counter',
        short_name: 'Counter',
        description: 'Pharmacy billing that keeps working when the line drops.',
        theme_color: '#1b5dfc',
        background_color: '#f4f5fa',
        display: 'standalone',
        orientation: 'portrait',
        start_url: '/sell',
        icons: [
          { src: 'pwa-192.png', sizes: '192x192', type: 'image/png' },
          { src: 'pwa-512.png', sizes: '512x512', type: 'image/png' },
          { src: 'pwa-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' }
        ]
      },
      workbox: {
        // The shell, plus the barcode decoder's WebAssembly — without it a
        // scan on a cold offline start would fail with nothing to explain it.
        globPatterns: ['**/*.{js,css,html,ico,png,svg,wasm,woff2}'],
        // zxing's module is a couple of megabytes; the default cap would
        // silently drop it from the precache.
        maximumFileSizeToCacheInBytes: 8 * 1024 * 1024,
        navigateFallback: 'index.html',
        // Never serve an API path from the navigation fallback: a cached
        // index.html answering a POST would look like a mysterious parse error.
        navigateFallbackDenylist: API_PATHS.map((path) => new RegExp(`^${path}`)),
        runtimeCaching: [
          {
            // The product master. The device's IndexedDB mirror is the real
            // offline source; this is a second belt for a cold start that has
            // a link but a slow one.
            urlPattern: ({ url }) =>
              url.pathname.startsWith('/products') || url.pathname.startsWith('/inventory/'),
            handler: 'NetworkFirst',
            options: {
              cacheName: 'product-master',
              networkTimeoutSeconds: 5,
              expiration: { maxEntries: 50, maxAgeSeconds: 7 * 24 * 60 * 60 },
              cacheableResponse: { statuses: [200] }
            }
          }
          // Deliberately nothing for /sales or /auth. A cached sale response
          // would be a lie about whether a bill had synced, and the outbox is
          // what makes that unnecessary.
        ]
      },
      devOptions: {
        // Off by default: a service worker caching a dev build is a confusing
        // way to spend an afternoon. `VITE_PWA_DEV=1` turns it on to test.
        enabled: process.env.VITE_PWA_DEV === '1',
        type: 'module'
      }
    })
  ],
  server: {
    // Bound to every interface only when serving HTTPS, since that is the one
    // mode where reaching it from another device is useful.
    ...(useHttps ? { host: true } : {}),
    proxy: Object.fromEntries(
      API_PATHS.map((path) => [path, { target, changeOrigin: true, secure: false }])
    )
  }
})
