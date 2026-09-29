import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

/** Enable React transforms and proxy development API requests to Flask. */
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:5000',
        changeOrigin: true,
      },
    },
  },
})
