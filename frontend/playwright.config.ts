import { defineConfig, devices } from '@playwright/test';

// RMS_E2E_PORT lets a second dev server (e.g. :5174 against another API) be tested; default 5173.
const PORT = Number(process.env.RMS_E2E_PORT ?? 5173);
const baseURL = `http://localhost:${String(PORT)}`;

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL,
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'desktop-chrome', use: { ...devices['Desktop Chrome'] } },
    { name: 'desktop-firefox', use: { ...devices['Desktop Firefox'] } },
    { name: 'desktop-webkit', use: { ...devices['Desktop Safari'] } },
    { name: 'mobile-pixel-7', use: { ...devices['Pixel 7'] } },
    { name: 'mobile-iphone-14', use: { ...devices['iPhone 14'] } },
    { name: 'tablet-ipad', use: { ...devices['iPad (gen 7)'] } },
  ],
  webServer: {
    command: 'pnpm dev',
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
