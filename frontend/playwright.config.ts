import { defineConfig } from '@playwright/test'

/* E2E 主链路(#72): 前端构建产物 + FastAPI 单进程后端, 全部跑在本地临时库。
   webServer 启动后端(初始化建表/迁移/种子用户), 前端产物由后端静态托管;
   因此本地/CI 都先 `npm run build` 再 `playwright test`(CI 里显式分步)。 */

const PORT = 8700

export default defineConfig({
  testDir: './e2e',
  timeout: 300_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : [['list']],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'cd .. && uv run uvicorn main:app --port 8700',
    port: PORT,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
    env: {
      SECREQ_DATABASE_URL: 'sqlite:///./e2e-secreq.db',
      SECREQ_SEED_PASSWORD: 'e2e-pass',
    },
  },
})
