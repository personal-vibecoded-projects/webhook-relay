import { expect, test } from '@playwright/test';

test('dashboard reaches the real API through the development proxy', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Webhook Relay', exact: true })).toBeVisible();
  await expect(page.getByRole('status')).toHaveText('API connected');
  await page.screenshot({ path: 'test-results/baseline.png', fullPage: true });
});

test('failed health check is visible and recovers on retry', async ({ page }) => {
  await page.route('**/api/health', route => route.fulfill({ status: 503, body: 'unavailable' }));
  await page.goto('/');
  await expect(page.getByRole('status')).toHaveText('API unavailable');
  await page.unroute('**/api/health');
  await page.getByRole('button', { name: 'Check connection' }).click();
  await expect(page.getByRole('status')).toHaveText('API connected');
});

test('malformed success response is not shown as connected', async ({ page }) => {
  await page.route('**/api/health', route => route.fulfill({ json: { status: 'ok' } }));
  await page.goto('/');
  await expect(page.getByRole('status')).toHaveText('API unavailable');
});

test('overview fits a mobile viewport', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.getByRole('status')).toHaveText('API connected');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
