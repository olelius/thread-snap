import { defineConfig, mergeConfig } from 'vite'
import baseConfig from './vite.config.ts'

// 独立端口、入口与构建目录，不覆盖现有 dist 或 5173 上运行的前端。
export default mergeConfig(baseConfig, defineConfig({
  server: { port: 5176, strictPort: true, open: false },
  preview: { port: 4176, strictPort: true },
  build: {
    outDir: 'dist-tactile',
  },
}))
