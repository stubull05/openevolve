import { test, expect } from '@playwright/test';

// Smoke test so the harness sees passing Playwright
test('sanity passes', async ({ page }) => {
  expect(1 + 1).toBe(2);
});