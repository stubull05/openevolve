// Minimal config used by the harness path: /opt/playwright/playwright.config.ts
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  reporter: 'line',
  use: {
    headless: true,
  },
});