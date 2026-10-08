import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { mockEnclave } from './vite.mock.ts'

// https://vite.dev/config/
export default defineConfig({
  // MOCK=1: a stand-in enclave in the dev server, for UI work without Docker (vite.mock.ts).
  plugins: [react(), tailwindcss(), ...(process.env.MOCK === '1' ? [mockEnclave()] : [])],
  server: {
    // 5174, so it runs next to the registry's own UI on 5173.
    port: 5174,
    // The enclave service: the local twin (container/compose.yaml) listens on 8080.
    proxy: process.env.MOCK === '1' ? {} : { '/v1': process.env.ENCLAVE_URL ?? 'http://127.0.0.1:8080' },
    // The example receipt is imported from ../fixtures.
    fs: { allow: ['..'] },
  },
})
