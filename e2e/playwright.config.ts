import { defineConfig } from '@playwright/test';

// Point E2E_BASE_URL at the running demo. It must be a secure origin (localhost or https): `make e2e` shares the API
// container's network and uses http://localhost:8000, from the host the demo is http://localhost:8300.
const baseURL = process.env.E2E_BASE_URL ?? 'http://localhost:8300';

export default defineConfig({
  testDir: './tests',
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false, // the lab drives one database, one clock and two stand-ins, so tests run one at a time
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['list']] : [['list']],
  use: {
    baseURL,
    trace: 'retain-on-failure',
  },
});
