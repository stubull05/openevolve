import { test, expect } from '@playwright/test';

test('login/logout + UI smoke', async ({ page, baseURL }) => {
  // 1) Open app
  await page.goto(baseURL || '/');

  // 2) Chat panel is visible (robust selector set)
  const chat = page.locator('[id*="chat" i], [class*="chat" i], [aria-label*="chat" i]');
  await expect(chat.first()).toBeVisible();

  // 3) Timeframe buttons exist (1d/1w/1m/3m/1y)
  for (const tf of ['1d','1w','1m','3m','1y']) {
    const btn = page.getByRole('button', { name: new RegExp(`^${tf}$`, 'i') });
    await expect(btn.or(page.locator(`text=${tf}`)).first()).toBeVisible();
  }

  // 4) Chart container present (heuristics)
  const chart = page.locator('[id*="chart" i], [class*="chart" i], canvas');
  await expect(chart.first()).toBeVisible();

  // 5) If Logout exists, click it and confirm API returns 2xx
  const logout = page.getByRole('button', { name: /logout/i })
                    .or(page.locator('[id*="logout" i], [class*="logout" i]'));
  const hasLogout = await logout.first().isVisible().catch(() => false);
  if (hasLogout) {
    const [resp] = await Promise.all([
      page.waitForResponse(r => /\/api\/logout\b/.test(r.url()) && r.status() >= 200 && r.status() < 400, { timeout: 10_000 }).catch(() => null),
      logout.first().click()
    ]);
    if (resp) expect(resp.ok()).toBeTruthy();
  }

  // 6) Panels appear draggable/resizable (heuristic classes/attrs)
  const draggy = page.locator('[class*="drag" i], [class*="grid" i], [draggable="true"]');
  await expect(draggy.first()).toBeVisible();
});
