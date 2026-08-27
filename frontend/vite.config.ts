import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 开发期将 /api 代理到本地 FastAPI 服务
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
