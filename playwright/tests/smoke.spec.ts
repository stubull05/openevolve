import { test, expect } from '@playwright/test';
 
test('smoke: app is healthy', async ({ page }) => {
  // Hit the health check endpoint
  const response = await page.goto('/health');
  // A trivial assertion so the harness reports a pass
  expect(response?.ok()).toBe(true);
});
 
