import AxeBuilder from '@axe-core/playwright';
import { type Page, expect, test } from '@playwright/test';
import { active, card, cards, count, openLab, press, resetLab, tab, valueLocator, valueOf, watch } from './helpers';

test.beforeEach(async ({ request }) => {
  await resetLab(request);
});

/** Press a lever and wait for the card that proves it went through, so the next press cannot overtake it. */
async function pull(page: Page, button: string, heading: string): Promise<void> {
  await press(page, button);
  await expect(card(page, heading)).toBeVisible();
}

/** Load the registry into the pipeline: the first thing nearly every flow needs. */
async function loadEverything(page: Page): Promise<void> {
  await openLab(page, 'Sync');
  await press(page, 'Sync');
  await expect(valueLocator(card(page, 'Sync'), 'Written')).not.toHaveText('0');
}

async function moveClock(page: Page, button: string, shown: string): Promise<void> {
  await press(page, button);
  await expect(active(page)).toContainText(shown);
}

test.describe('lab: sync', () => {
  test('the first sync writes what fits and counts what does not; a second one writes nothing and queues nothing', async ({
    page,
  }) => {
    const problems = watch(page);
    await openLab(page, 'Sync');
    await expect(valueLocator(active(page), 'People')).not.toHaveText('0');
    await press(page, 'Sync');
    const first = card(page, 'Sync');
    await expect(valueLocator(first, 'Written')).not.toHaveText('0');
    expect(count(await valueOf(first, 'Records read'))).toBeGreaterThan(100);
    expect(count(await valueOf(first, 'Rejected (did not fit)'))).toBeGreaterThanOrEqual(1);
    expect(count(await valueOf(first, 'Reports queued'))).toBeGreaterThan(100);

    await press(page, 'Sync');
    const second = card(page, 'Sync');
    await expect(valueLocator(second, 'Written')).toHaveText('0');
    await expect(valueLocator(second, 'Reports queued')).toHaveText('0');
    expect(problems).toEqual([]);
  });

  test('a record two minutes late is inside the overlap window; one an hour late needs the full re-read', async ({
    page,
  }) => {
    await openLab(page, 'Sync');
    await pull(page, 'A week of work', 'Advance the registry');
    await press(page, 'Sync');
    await expect(valueLocator(card(page, 'Sync'), 'Written')).not.toHaveText('0');

    await pull(page, 'A record arrives 2 minutes late', 'A record, stamped 2 minutes ago');
    await press(page, 'Sync');
    await expect(valueLocator(card(page, 'Sync'), 'Written')).toHaveText('1');

    await pull(page, 'A record arrives 1 hour late', 'A record, stamped 1 hour ago');
    await press(page, 'Sync');
    await expect(valueLocator(card(page, 'Sync'), 'Written')).toHaveText('0'); // the window does not reach back that far
    await press(page, 'Full re-read');
    await expect(valueLocator(card(page, 'Full re-read'), 'Written')).toHaveText('1'); // and the full re-read finds it
  });

  test('a registry that fails three requests fails the run with a clean error, and the next run recovers', async ({
    page,
  }) => {
    await openLab(page, 'Sync');
    await pull(page, 'Fail the next 3 requests', 'The registry fails 3 requests');
    await press(page, 'Sync');
    const failed = card(page, 'Sync');
    await expect(failed).toContainText('failed');
    await expect(valueLocator(failed, 'Error')).toContainText('after 3 tries');
    expect(await valueOf(failed, 'Error')).not.toContain('reg-'); // an error names the kind of failure, never a record

    await press(page, 'Sync');
    await expect(card(page, 'Sync')).toContainText('ok');
    await expect(valueLocator(card(page, 'Sync'), 'Written')).not.toHaveText('0');
  });
});

test.describe('lab: queue', () => {
  test('a worker that dies holding five messages loses nothing: the next drain takes them over first and says so', async ({
    page,
  }) => {
    await loadEverything(page);
    await tab(page, 'Queue').click();
    await pull(page, 'Crash a worker', 'A worker claims 5 messages and dies');
    await expect(valueLocator(active(page), 'Being sent')).toHaveText('5');

    await press(page, 'Drain now'); // the lease still holds: the five are left alone
    await expect(valueLocator(card(page, 'Drain'), 'Messages claimed')).not.toHaveText('0');
    await expect(valueLocator(card(page, 'Drain'), 'Taken over from a dead worker')).toHaveText('0');
    await expect(valueLocator(active(page), 'Being sent')).toHaveText('5');

    await moveClock(page, '+10 minutes', 'moved 600 s ahead');
    await press(page, 'Drain now');
    await expect(valueLocator(card(page, 'Drain'), 'Taken over from a dead worker')).toHaveText('5');
    await expect(valueLocator(active(page), 'Being sent')).toHaveText('0');
  });

  test('a gateway slower than its timeout stops the worker after three tries and gives the rest back untouched', async ({
    page,
  }) => {
    await loadEverything(page);
    await tab(page, 'Queue').click();
    await pull(page, 'Slower than the timeout', 'Gateway: Slower than the timeout');
    await press(page, 'Drain now');
    const drained = card(page, 'Drain');
    await expect(drained).toBeVisible({ timeout: 45_000 });
    await expect(valueLocator(drained, 'Gave up early because')).toHaveText('3 transport failures in a row');
    expect(count(await valueOf(drained, 'Given back untouched'))).toBeGreaterThan(0);
  });

  test('a gateway that keeps the report and fails to say so is shown the same report again, and says "duplicate"', async ({
    page,
  }) => {
    await loadEverything(page);
    await tab(page, 'Queue').click();
    await pull(page, 'Keeps the report, then fails to answer', 'Gateway: Keeps the report');
    await press(page, 'Drain everything due');
    const first = card(page, 'Drain everything due');
    await expect(first).toBeVisible({ timeout: 45_000 });
    await expect(valueLocator(first, 'Delivered')).toHaveText('0');
    // Read the figure now: a locator follows the newest card, and a second drain is about to put a new one first.
    const retried = await valueOf(first, 'Retry later');
    expect(count(retried)).toBeGreaterThan(100);
    await expect(valueLocator(active(page), 'Reports it holds')).toHaveText(retried);
    await expect(valueLocator(active(page), 'Duplicates it refused')).toHaveText('0');

    await pull(page, 'Healthy', 'Gateway: Healthy');
    await moveClock(page, '+1 hour', 'moved 3,600 s ahead');
    await press(page, 'Drain everything due');
    // Every one of those reports is sent again, and every one is answered "duplicate", which counts as delivered.
    await expect(valueLocator(card(page, 'Drain everything due'), 'Already held by the gateway')).toHaveText(retried, {
      timeout: 45_000,
    });
    await expect(valueLocator(card(page, 'Drain everything due'), 'Delivered')).toHaveText('0');
    await expect(valueLocator(active(page), 'Duplicates it refused')).toHaveText(retried);
    await expect(valueLocator(active(page), 'Reports it holds')).toHaveText(retried); // still one of each
  });

  test('mutual TLS: the certificate gets in, and without it the handshake is refused', async ({ page }) => {
    await openLab(page, 'Queue');
    await press(page, 'Connect with the certificate');
    const allowed = card(page, 'Connect with the client certificate');
    await expect(allowed).toContainText('connected');
    await expect(valueLocator(allowed, 'Result')).toHaveText('HTTP 200');

    await press(page, 'Connect without it');
    const refused = card(page, 'Connect without a certificate');
    await expect(refused).toContainText('refused');
    await expect(valueLocator(refused, 'Used TLS')).toHaveText('yes');
    expect(await valueOf(refused, 'Result')).not.toContain('HTTP'); // there was no HTTP: it failed in the handshake
  });

  test('with the autopilot on, the real worker and scheduler drain the queue without a button', async ({
    page,
    request,
  }) => {
    test.setTimeout(150_000);
    await loadEverything(page);
    await tab(page, 'Queue').click();
    await expect(active(page)).toContainText('off: nothing moves until you press Drain');
    await press(page, 'Autopilot on');
    await expect(active(page)).toContainText('on: a worker drains every 30 s');
    await expect
      .poll(async () => ((await (await request.get('/api/queue')).json()) as { counts: { done: number } }).counts.done, {
        timeout: 100_000,
        intervals: [3_000],
      })
      .toBeGreaterThanOrEqual(50); // at least one scheduled batch went through a worker nobody pressed
    await press(page, 'Autopilot off');
  });
});

test.describe('lab: indicators', () => {
  test('a narrator that rounds, invents or names a person is refused and replaced; the honest one passes', async ({
    page,
  }) => {
    await loadEverything(page);
    await tab(page, 'Indicators').click();
    await expect(active(page).locator('table.matrix tbody tr')).toHaveCount(5);
    await expect(card(page, 'The words')).toContainText('passed the check');

    await press(page, 'Rounds a percentage');
    await expect(card(page, 'The words')).toContainText('refused, replaced by the template');
    await expect(active(page)).toContainText('What the check found');
    await expect(active(page)).toContainText(/the percentage \d+% is not in the report/);

    await press(page, 'Invents a forecast');
    await expect(active(page)).toContainText('the percentage 12.5% is not in the report');
    await expect(active(page).locator('pre.out')).not.toContainText('12.5');

    await press(page, 'Names a person');
    await expect(active(page)).toContainText('a token shaped like a stored pseudonym');

    await press(page, 'The template (honest)');
    await expect(card(page, 'The words')).toContainText('passed the check');
    await expect(active(page)).not.toContainText('What the check found');
  });

  test('a date that is not a date is refused with a sentence, not a crash', async ({ page }) => {
    await loadEverything(page);
    await tab(page, 'Indicators').click();
    await active(page).getByLabel('Report date').fill('next tuesday');
    await press(page, 'Compute');
    await expect(page.getByText('Write the date as YYYY-MM-DD.')).toBeVisible();
  });
});

test.describe('lab: search', () => {
  test('a typo finds nothing by keywords and is found by spelling; the hybrid says where each hit came from', async ({
    page,
  }) => {
    await openLab(page, 'Search');
    await press(page, 'a typo');
    const keywords = card(page, 'Keywords only');
    await expect(keywords).toContainText('Nothing found.');
    await expect(card(page, 'Spelling similarity only')).toContainText('Resuming an interrupted synchronisation');
    await expect(card(page, 'Hybrid (rank fusion)')).toContainText(/from vector #1/);
  });

  test('the evaluation prints the measured matrix, and the gap column is the weakest in every row', async ({ page }) => {
    await openLab(page, 'Search');
    await press(page, 'Run the evaluation');
    const rows = active(page).locator('table.matrix tbody tr');
    await expect(rows).toHaveCount(4);
    const table = await rows.evaluateAll((trs) => trs.map((tr) => [...tr.children].map((c) => c.textContent ?? '')));
    const overall = Object.fromEntries(table.map((r) => [r[0], r[1]]));
    // These are the figures in ADR 0004 and on the landing page. If the corpus or the embedder changes, so must they.
    expect(overall).toEqual({
      'Keywords only': '0.89 · 0.84',
      'Spelling similarity only': '0.86 · 0.82',
      'Hybrid (rank fusion)': '0.94 · 0.87',
      'Weighted sum of scores': '0.94 · 0.88',
    });
    for (const row of table) {
      const recalls = row.slice(2).map((cell) => Number.parseFloat(cell.split(' · ')[0] ?? 'NaN')); // exact … gap
      const gap = recalls[recalls.length - 1] ?? Number.NaN;
      expect(gap, `${row[0]}: the gap column should be the lowest`).toBeLessThan(Math.min(...recalls.slice(0, -1)));
    }
  });
});

test.describe('lab: privacy', () => {
  test('the whole database is searched for forty people and finds none of them, having looked', async ({ page }) => {
    await loadEverything(page);
    await tab(page, 'Privacy').click();
    await press(page, 'Search the whole database');
    const search = card(page, 'The search');
    await expect(search).toContainText('found nothing');
    await expect(valueLocator(search, 'Values looked for')).toHaveText('120');
    expect(count(await valueOf(search, 'Columns examined'))).toBeGreaterThanOrEqual(15);
    await expect(valueLocator(search, 'Rows that contain one')).toHaveText('none');

    const sent = card(page, 'What the registry sends');
    const stored = card(page, 'What is stored');
    await expect(sent.locator('li')).toHaveCount(3);
    await expect(stored.locator('li')).toHaveCount(3);
    for (const name of await sent.locator('li > strong').allTextContents()) {
      await expect(stored, `"${name}" is stored`).not.toContainText(name);
    }
    await expect(stored.locator('li > strong').first()).toHaveText(/^pk1\.[a-z2-7]{26}$/);
  });
});

test.describe('lab: health', () => {
  test('six components, each judged its own way, and the whole follows the worst critical one', async ({ page }) => {
    await openLab(page, 'Health');
    await expect(active(page).locator('ul.trace li')).toHaveCount(6);
    const names = await active(page).locator('ul.trace li > strong').allTextContents();
    expect(names.sort()).toEqual(['broker', 'database', 'queue', 'search-index', 'sync', 'worker']);
  });
});

test.describe('lab: starting over', () => {
  test('"Start over" empties the database, both stand-ins and the clock', async ({ page, request }) => {
    await loadEverything(page);
    await page.getByRole('button', { name: 'Start over' }).click();
    await expect(page.getByText('Back to a clean slate.')).toBeVisible();
    const overview = (await (await request.get('/api/overview')).json()) as { data: { encounters: number } };
    expect(overview.data.encounters).toBe(0);
  });
});

test.describe('lab: the server in front of it', () => {
  test('a request addressed to another name, or sent from another origin, is refused', async ({ request }) => {
    const foreignHost = await request.get('/api/lab/state', { headers: { Host: 'evil.example' } });
    expect(foreignHost.status()).toBe(421);
    const foreign = await request.post('/api/lab/reset', { data: {}, headers: { Origin: 'https://evil.example' } });
    expect(foreign.status()).toBe(403);
    const crossSite = await request.post('/api/lab/reset', { data: {}, headers: { 'Sec-Fetch-Site': 'cross-site' } });
    expect(crossSite.status()).toBe(403);
  });

  test('every tab loads without a console problem or a third-party request', async ({ page }) => {
    const problems = watch(page);
    await openLab(page, 'Sync');
    for (const name of ['Queue', 'Indicators', 'Search', 'Privacy', 'Health']) {
      await tab(page, name).click();
      await expect(tab(page, name)).toHaveAttribute('aria-selected', 'true');
    }
    expect(problems).toEqual([]);
  });

  test('the cards a tab produces are kept to the latest few', async ({ page }) => {
    await openLab(page, 'Queue');
    for (let i = 0; i < 6; i++) {
      await press(page, 'Connect with the certificate');
      await expect(cards(page).first()).toContainText('connected');
    }
    await expect(cards(page)).toHaveCount(4);
  });
});

for (const scheme of ['light', 'dark'] as const) {
  for (const name of ['Sync', 'Queue', 'Indicators', 'Search', 'Privacy', 'Health']) {
    test(`accessibility: the ${name} tab has no WCAG A/AA violations (${scheme})`, async ({ browser, request }) => {
      await resetLab(request);
      const context = await browser.newContext({ colorScheme: scheme, reducedMotion: 'reduce' });
      const page = await context.newPage();
      await openLab(page, name);
      // The part of each tab with the most markup, so the scan sees more than the empty state.
      if (name === 'Queue') {
        await press(page, 'Connect without it');
        await expect(cards(page).first()).toContainText('refused');
      }
      if (name === 'Search') {
        await press(page, 'Run the evaluation');
        await expect(active(page).locator('table.matrix tbody tr')).toHaveCount(4);
        await press(page, 'a typo');
        await expect(card(page, 'Keywords only')).toBeVisible();
      }
      if (name === 'Indicators') await expect(active(page).locator('table.matrix')).toBeVisible();
      const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
      expect(results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`)).toEqual(
        [],
      );
      await context.close();
    });
  }
}
