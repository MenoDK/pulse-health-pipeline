import { type APIRequestContext, type Locator, type Page, expect } from '@playwright/test';

const BASE = new URL(process.env.E2E_BASE_URL ?? 'http://localhost:8300');

/** Collects what would make a reviewer frown: console errors, page errors (CSP violations land here) and third-party calls. */
export function watch(page: Page, { allowStatus = [] as number[] } = {}): string[] {
  const problems: string[] = [];
  page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`));
  page.on('console', (m) => {
    if (m.type() !== 'error' && m.type() !== 'warning') return;
    // Chromium logs every non-2xx fetch as an error. Allow only the statuses a test provokes on purpose.
    const status = /status of (\d{3})/.exec(m.text());
    if (status && allowStatus.includes(Number(status[1]))) return;
    problems.push(`console ${m.type()}: ${m.text()}`);
  });
  page.on('request', (r) => {
    const url = new URL(r.url());
    if (url.protocol !== 'data:' && url.protocol !== 'blob:' && url.host !== BASE.host) {
      problems.push(`third-party request: ${r.url()}`);
    }
  });
  return problems;
}

export async function leaveSplash(page: Page): Promise<void> {
  await expect(page.locator('#splash')).toHaveCount(0, { timeout: 10_000 });
}

/** Open the lab on a tab and wait until it is there. There is no sign-in: the lab is a local tool. */
export async function openLab(page: Page, name: string): Promise<void> {
  await page.goto(`/lab.html#${name.toLowerCase()}`);
  await leaveSplash(page);
  await expect(page.getByRole('tab', { name })).toHaveAttribute('aria-selected', 'true');
}

export const tab = (page: Page, name: string) => page.getByRole('tab', { name });

/** The tab panel that is open. Panels that were visited and left stay in the page, hidden, so every locator starts here. */
export const active = (page: Page) => page.locator('[role="tabpanel"]:not([hidden])');

/** A button of the open tab, by its exact name. */
export const press = (page: Page, name: string) => active(page).getByRole('button', { name, exact: true }).first().click();

/** The cards the open tab has produced (newest first). */
export const cards = (page: Page) => active(page).locator('.box.arrive');

/** The card of the open tab whose heading starts with `heading`. */
export const card = (page: Page, heading: string) =>
  active(page)
    .locator('.box.arrive')
    .filter({ has: page.locator('h3', { hasText: heading }) })
    .first();

/** The value shown next to a label ("Taken over from a dead worker" → "5"), inside a card or a whole tab. */
export const valueLocator = (scope: Locator, label: string): Locator =>
  scope
    .locator('dt')
    .filter({ hasText: new RegExp(`^${label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`) })
    .first()
    .locator('xpath=following-sibling::dd[1]');

export async function valueOf(scope: Locator, label: string): Promise<string> {
  return ((await valueLocator(scope, label).textContent()) ?? '').trim();
}

/** "1,234" → 1234 */
export const count = (text: string): number => Number(text.replace(/[^\d.-]/g, ''));

/** Put the whole demo back to a clean slate: empty database, both stand-ins reset, the clock back. */
export async function resetLab(request: APIRequestContext): Promise<void> {
  const res = await request.post('/api/lab/reset', { data: {} });
  expect(res.ok(), `resetting the lab answered ${res.status()}: ${await res.text()}`).toBeTruthy();
  for (const [path, body] of [
    ['/api/lab/autopilot', { on: false }],
    ['/api/lab/narrator', { mode: 'template' }],
    ['/api/lab/gateway/scenario', { name: 'normal' }],
  ] as const) {
    const r = await request.post(path, { data: body });
    expect(r.ok(), `${path} answered ${r.status()}: ${await r.text()}`).toBeTruthy();
  }
}
