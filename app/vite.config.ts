import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv, type ProxyOptions } from 'vite'
import { mockEnclave } from './vite.mock.ts'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = { ...loadEnv(mode, process.cwd(), ''), ...process.env }
  const mock = env.MOCK === '1'
  // Where /v1 goes: a Tinfoil enclave (VITE_ENCLAVE_URL, which the app also verifies with tinfoil-js),
  // or else the local twin (container/compose.yaml), on 8080 unless ENCLAVE_URL says otherwise.
  const target = env.VITE_ENCLAVE_URL || env.ENCLAVE_URL || 'http://127.0.0.1:8080'
  return {
    // MOCK=1: a stand-in enclave in the dev server, for UI work without Docker (vite.mock.ts).
    plugins: [react(), tailwindcss(), ...(mock ? [mockEnclave()] : [])],
    server: {
      // 5174, so it runs next to the registry's own UI on 5173.
      port: 5174,
      proxy: (mock ? {} : { '/v1': { target, changeOrigin: true } }) as Record<string, ProxyOptions>,
      // The example receipt is imported from ../fixtures.
      fs: { allow: ['..'] },
    },
  }
})
