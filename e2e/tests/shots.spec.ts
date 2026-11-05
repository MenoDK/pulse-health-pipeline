import { type Page, expect, test } from '@playwright/test';
import { active, card, cards, leaveSplash, openLab, press, resetLab, tab, valueLocator } from './helpers';

// Only with SHOTS=1 (`make screenshots`): these are the pictures in the README, taken from the real lab.
test.skip(process.env.SHOTS !== '1', 'screenshots are taken on request');
test.use({ viewport: { width: 1360, height: 860 }, colorScheme: 'light', contextOptions: { reducedMotion: 'reduce' } });

const OUT = process.env.SHOTS_DIR ?? '../docs/img';
const settle = async (page: Page) => {
  await page.evaluate(() => window.scrollTo(0, 0)); // clicking scrolled the page; the picture starts at the top
  await page.waitForTimeout(5000); // let the confirmation toast leave
};

async function loadEverything(page: Page): Promise<void> {
  await openLab(page, 'Sync');
  await press(page, 'Sync');
  await expect(valueLocator(card(page, 'Sync'), 'Written')).not.toHaveText('0');
}

test('landing', async ({ page }) => {
  await page.goto('/?lang=en');
  await leaveSplash(page);
  await page.screenshot({ path: `${OUT}/landing.png` });
});

test('lab: a worker dies holding five messages and the next one takes them over', async ({ page, request }) => {
  await resetLab(request);
  await loadEverything(page);
  await tab(page, 'Queue').click();
  await press(page, 'Crash a worker');
  await card(page, 'A worker claims 5 messages and dies').waitFor();
  await press(page, '+10 minutes');
  await press(page, 'Drain now');
  await expect(valueLocator(card(page, 'Drain'), 'Taken over from a dead worker')).toHaveText('5');
  await page.setViewportSize({ width: 1360, height: 1500 });
  await settle(page);
  await page.screenshot({ path: `${OUT}/lab-queue.png` });
  await resetLab(request);
});

test('lab: a model that rounds a number is refused', async ({ page, request }) => {
  await resetLab(request);
  await loadEverything(page);
  await tab(page, 'Indicators').click();
  await press(page, 'Rounds a percentage');
  await active(page).getByText('What the check found').waitFor();
  await page.setViewportSize({ width: 1360, height: 1500 });
  await settle(page);
  await page.screenshot({ path: `${OUT}/lab-indicators.png` });
  await resetLab(request);
});

test('lab: four ways to search, measured', async ({ page, request }) => {
  await resetLab(request);
  await openLab(page, 'Search');
  await press(page, 'a typo');
  await press(page, 'Run the evaluation');
  await active(page).locator('table.matrix tbody tr').nth(3).waitFor();
  await cards(page).first().waitFor();
  await page.setViewportSize({ width: 1360, height: 1500 });
  await settle(page);
  await page.screenshot({ path: `${OUT}/lab-search.png` });
});

test('lab: looking for forty people in every column of the database', async ({ page, request }) => {
  await resetLab(request);
  await loadEverything(page);
  await tab(page, 'Privacy').click();
  await press(page, 'Search the whole database');
  await card(page, 'The search').waitFor();
  await page.setViewportSize({ width: 1360, height: 1300 });
  await settle(page);
  await page.screenshot({ path: `${OUT}/lab-privacy.png` });
  await resetLab(request);
});
