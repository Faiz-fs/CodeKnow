import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Proxy API calls to the FastAPI backend during development.
      // All backend endpoints live under the /codeknow prefix on port 8080.
      '/codeknow': 'http://localhost:8080',
    },
  },
})
