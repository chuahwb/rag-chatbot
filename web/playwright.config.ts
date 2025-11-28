/// <reference types="node" />
import { defineConfig } from '@playwright/test'

const PORT = Number(process.env.VITE_PORT ?? 4173)
const HOST = process.env.E2E_HOST ?? '127.0.0.1'

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  reporter: [
    ['list'],
    ['html', { open: 'never', outputFolder: 'test-results/playwright-report' }]
  ],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? `http://${HOST}:${PORT}`,
    headless: true,
    viewport: { width: 1200, height: 900 }
  },
  webServer: {
    command: `bash -c "npm run build && npm run preview -- --host=${HOST} --port ${PORT}"`,
    url: `http://${HOST}:${PORT}`,
    reuseExistingServer: !process.env.CI,
    stdout: 'pipe',
    stderr: 'pipe',
    timeout: 120 * 1000
  }
})

