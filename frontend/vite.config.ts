import path from 'node:path'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(import.meta.dirname, './src') } },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': { target: process.env.THREADSNAP_API_TARGET ?? 'http://127.0.0.1:8000', ws: true },
      '/health': { target: process.env.THREADSNAP_API_TARGET ?? 'http://127.0.0.1:8000' },
    },
  },
})
