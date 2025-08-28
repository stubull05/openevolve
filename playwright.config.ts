import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: '/opt/playwright/tests',  // mount your real tests here if you want them to run
  reporter: 'line',
  use: { headless: true },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
});
