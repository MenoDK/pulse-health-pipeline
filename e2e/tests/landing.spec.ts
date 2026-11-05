import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { leaveSplash, watch } from './helpers';

test.describe('landing page', () => {
  test('shows the loading stage, then the page, without a single console problem or third-party request', async ({
    page,
  }) => {
    const problems = watch(page);
    await page.goto('/?lang=en');
    await expect(page.locator('#splash')).toBeVisible();
    await leaveSplash(page);
    await expect(page.getByRole('heading', { level: 1 })).toContainText('A pipeline you can');
    await expect(page.getByRole('heading', { level: 1 })).toContainText('kill and trust.');
    await expect(page.getByRole('link', { name: /Open the lab/ }).first()).toBeVisible();
    expect(problems).toEqual([]);
  });

  test('the tour tabs swap in output that was recorded from the real code', async ({ page }) => {
    await page.goto('/?lang=en');
    await leaveSplash(page);
    const tabs = page.getByRole('group', { name: 'Explore the product' });
    const output = page.getByRole('region', { name: 'Example output' });

    await tabs.getByRole('button', { name: /Sync/ }).click();
    await expect(output).toContainText("$ pulse sync | jq -c '{status, queued, totals}'");
    await expect(output).toContainText('A full re-read ignores the stored position');
    await expect(output).toContainText('"applied":1');

    await tabs.getByRole('button', { name: /Queue/ }).click();
    // a transcript inserted as HTML would swallow anything that looks like a tag, and ">>>" is the first thing to go
    await expect(output).toContainText('>>> queue.counts(engine)');
    await expect(output).toContainText('taken_over=5');
    await expect(output).toContainText('duplicate=10');
    await expect(output).toContainText('175, 10');

    await tabs.getByRole('button', { name: /Indicators/ }).click();
    await expect(output).toContainText('refused: the percentage 67% is not in the report');
    await expect(output).toContainText('refused: the text contains a token shaped like a stored pseudonym');

    await tabs.getByRole('button', { name: /Search/ }).click();
    await expect(output).toContainText('(no note matches)');
    await expect(output).toContainText("{'lexical': 1, 'vector': 1}");
    await expect(output).toContainText('hybrid 0.94 0.87'); // the hybrid row, overall (whitespace is normalised)

    await tabs.getByRole('button', { name: /Privacy/ }).click();
    await expect(output).toContainText('matches=())');
    await expect(output).toContainText("matches=(('sync_runs', 'error', 1),)");
    await expect(tabs.getByRole('button', { name: /Privacy/ })).toHaveAttribute('aria-pressed', 'true');
  });

  test('no recorded output holds anything shaped like a secret or a national identifier', async ({ page }) => {
    await page.goto('/?lang=en');
    const text = await page.evaluate(() => JSON.stringify((window as unknown as { TRANSCRIPTS: object }).TRANSCRIPTS));
    expect(text).not.toMatch(/AKIA[0-9A-Z]{16}|-----BEGIN|gh[pousr]_[A-Za-z0-9]{20}|Bearer [A-Za-z0-9]{12}/);
    expect(text).not.toMatch(/\d{11}/); // the registry's identifiers are eleven digits: none may be printed
  });

  test('the figures under the hood are numbers, and the four captions are there', async ({ page }) => {
    await page.goto('/?lang=en');
    await leaveSplash(page);
    const figures = await page.locator('.numbers strong').allTextContents();
    expect(figures).toHaveLength(4);
    for (const figure of figures) expect(figure, `"${figure}" is a placeholder, not a measurement`).toMatch(/^\d+$/);
  });

  test('every hard part offers a recipe and a link that opens the lab on the right tab', async ({ page }) => {
    await page.goto('/?lang=en#hard-parts');
    await leaveSplash(page);
    const list = page.getByRole('group', { name: 'Hard parts to try' });
    const parts: [string, RegExp][] = [
      ['Lose a record', /lab\.html#sync$/],
      ['Kill a worker', /lab\.html#queue$/],
      ['Slow the gateway', /lab\.html#queue$/],
      ['Lose an acknowledgement', /lab\.html#queue$/],
      ['Let a model change a number', /lab\.html#indicators$/],
      ['Search for the idea', /lab\.html#search$/],
      ['Knock without a certificate', /lab\.html#queue$/],
      ['Look for a person', /lab\.html#privacy$/],
    ];
    for (const [name, href] of parts) {
      await list.getByRole('button', { name }).click();
      await expect(page.getByText('You should see', { exact: true })).toBeVisible();
      await expect(page.getByRole('link', { name: 'Try it in the lab' })).toHaveAttribute('href', href);
    }
  });

  test('the theme switch is applied, remembered across reloads, and nothing leaves the page', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'light' });
    await page.goto('/?lang=en');
    await leaveSplash(page);
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
    await page.getByRole('button', { name: 'Use the dark theme' }).click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  });

  test('works with reduced motion and still reveals every section', async ({ browser }) => {
    const context = await browser.newContext({ reducedMotion: 'reduce' });
    const page = await context.newPage();
    await page.goto('/?lang=en');
    await leaveSplash(page);
    await page.locator('#faq').scrollIntoViewIfNeeded();
    await expect(page.getByRole('heading', { name: /Asked often/ })).toBeVisible();
    await context.close();
  });

  test('has no horizontal scroll on a phone', async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 360, height: 740 } });
    const page = await context.newPage();
    await page.goto('/?lang=en');
    await leaveSplash(page);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
    await context.close();
  });

  test('the hero artwork keeps every label inside its frame and inside its own box', async ({ page }) => {
    await page.goto('/?lang=en');
    await leaveSplash(page);
    const outside = await page.evaluate(() => {
      const frame = document.querySelector('.hero-art svg');
      if (!frame) return ['no artwork'];
      const box = frame.getBoundingClientRect();
      const bad: string[] = [];
      for (const t of frame.querySelectorAll('text')) {
        const r = t.getBoundingClientRect();
        if (r.left < box.left - 1 || r.right > box.right + 1) bad.push(`${t.textContent} leaves the frame`);
        // the card or pill a label sits in: the smallest rect that contains the label's start
        const host = [...frame.querySelectorAll('rect')]
          .map((rect) => ({ rect, b: rect.getBoundingClientRect() }))
          .filter(({ b }) => b.left <= r.left + 2 && b.right >= r.left && b.top <= r.top + 2 && b.bottom >= r.bottom - 2)
          .sort((a, c) => a.b.width * a.b.height - c.b.width * c.b.height)[0];
        if (host && r.right > host.b.right + 1) bad.push(`${t.textContent} runs past the box it sits in`);
      }
      return bad;
    });
    expect(outside).toEqual([]);
  });
});

for (const scheme of ['light', 'dark'] as const) {
  test(`accessibility: the landing page has no WCAG A/AA violations (${scheme})`, async ({ browser }) => {
    const context = await browser.newContext({ colorScheme: scheme, reducedMotion: 'reduce' });
    const page = await context.newPage();
    await page.goto('/?lang=en');
    await leaveSplash(page);
    const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
    expect(results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`)).toEqual([]);
    await context.close();
  });
}
