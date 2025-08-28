import { defineConfig, devices } from '@playwright/test';

// Base URL comes from env (compose). Default is host.docker.internal:3000 for Docker -> Host.
const baseURL = process.env.FRONTEND_URL || 'http://host.docker.internal:3000';

export default defineConfig({
  testDir: '/opt/playwright/tests',
  timeout: 30_000,
  expect: { timeout: 5_000 },
  reporter: 'line',
  fullyParallel: false,
  use: {
    baseURL,
    headless: true,
    trace: 'off',
    video: 'off',
    screenshot: 'off',
    viewport: { width: 1366, height: 768 },
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
