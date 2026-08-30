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
  build: {
    // 拆分 vendor 包: antd 与图标占大头且很少变动, 单独成块可长期命中浏览器缓存
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('@ant-design/icons')) return 'icons'
          if (id.includes('/antd/') || id.includes('@rc-component')) return 'antd'
          if (/node_modules\/(react|react-dom|react-router|react-router-dom)\//.test(id)) return 'react'
          return 'vendor'
        },
      },
    },
  },
})
