import AxeBuilder from '@axe-core/playwright';
import { type Page, expect, test } from '@playwright/test';
import { leaveSplash, watch } from './helpers';

// The page ships in 14 languages. These tests are written against the page's own translation tables (they read
// `window.SITE_I18N`), so the same file guards every repository that uses the shared site kit.
const CODES = ['zh', 'hi', 'es', 'fr', 'ar', 'bn', 'pt', 'ru', 'ur', 'id', 'de', 'ja', 'ko'] as const;
const RTL = new Set(['ar', 'ur']);
const HTML_LANG: Record<string, string> = { zh: 'zh-Hans', pt: 'pt-BR' };

type Tables = Record<string, { hero: { lead: string } }>;

/** The headline the translation table promises for a language, read from the page that loaded it. */
const promisedHeadline = (page: Page, code: string): Promise<string> =>
  page.evaluate((c) => (window as unknown as { SITE_I18N: Tables }).SITE_I18N[c]?.hero.lead ?? '', code);

async function expectLanguage(page: Page, code: string): Promise<void> {
  const html = page.locator('html');
  await expect(html).toHaveAttribute('lang', HTML_LANG[code] ?? code);
  await expect(html).toHaveAttribute('dir', RTL.has(code) ? 'rtl' : 'ltr');
  const lead = (await promisedHeadline(page, code)).trim();
  expect(lead, `the page has no translation table for ${code}`).not.toBe('');
  await expect(page.getByRole('heading', { level: 1 })).toContainText(lead);
}

test.describe('languages', () => {
  test('opens in the language the link asks for, without a console problem or third-party request', async ({
    page,
  }) => {
    const problems = watch(page);
    await page.goto('/?lang=es');
    await leaveSplash(page);
    await expectLanguage(page, 'es');
    await expect(page.locator('.lang-select')).toHaveValue('es');
    expect(problems).toEqual([]);
  });

  test('falls back to English for a language the page does not have', async ({ page }) => {
    await page.goto('/?lang=xx');
    await leaveSplash(page);
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
    await expect(page.locator('html')).toHaveAttribute('dir', 'ltr');
    await expect(page.locator('.lang-select')).toHaveValue('en');
  });

  test('picks the visitor browser language when nothing else was asked', async ({ browser }) => {
    const context = await browser.newContext({ locale: 'de-DE' });
    const page = await context.newPage();
    await page.goto('/');
    await leaveSplash(page);
    await expectLanguage(page, 'de');
    await context.close();
  });

  test('switching language re-renders in place, keeps the scroll position, and is remembered', async ({ page }) => {
    const problems = watch(page);
    await page.goto('/?lang=en');
    await leaveSplash(page);
    await page.evaluate(() => {
      (window as unknown as { __alive: number }).__alive = 1;
    });
    await page.locator('#faq').scrollIntoViewIfNeeded();
    const before = await page.evaluate(() => window.scrollY);
    expect(before).toBeGreaterThan(300);

    await page.locator('.lang-select').first().selectOption('fr');
    await expectLanguage(page, 'fr');
    // Same document: nothing reloaded, so the marker survived and the visitor is still far down the page.
    expect(await page.evaluate(() => (window as unknown as { __alive?: number }).__alive)).toBe(1);
    const after = await page.evaluate(() => window.scrollY);
    expect(after).toBeGreaterThan(300);

    await page.reload(); // the address said ?lang=en, but the visitor has chosen since
    await leaveSplash(page);
    await expectLanguage(page, 'fr');

    await page.goto('/'); // no ?lang= this time: the choice has to come from storage
    await leaveSplash(page);
    await expectLanguage(page, 'fr');
    expect(problems).toEqual([]);
  });

  test('a language in the link wins over the one remembered', async ({ page }) => {
    await page.goto('/?lang=ja');
    await leaveSplash(page);
    await page.goto('/?lang=ko');
    await leaveSplash(page);
    await expectLanguage(page, 'ko');
  });

  test('the lab page follows the language too', async ({ page }) => {
    const problems = watch(page);
    await page.goto('/lab.html?lang=pt');
    await leaveSplash(page);
    await expect(page.locator('html')).toHaveAttribute('lang', 'pt-BR');
    await expect(page.locator('.lang-select')).toHaveValue('pt');
    await page.locator('.lang-select').first().selectOption('ar'); // the lab body holds live state, so this reloads
    await expect(page.locator('html')).toHaveAttribute('lang', 'ar');
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
    expect(problems).toEqual([]);
  });

  for (const code of CODES) {
    test(`${code}: renders its own headline, has no horizontal scroll on a phone and no console problem`, async ({
      browser,
    }) => {
      const context = await browser.newContext({ viewport: { width: 360, height: 740 } });
      const page = await context.newPage();
      const problems = watch(page);
      await page.goto(`/?lang=${code}`);
      await leaveSplash(page);
      await expectLanguage(page, code);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);
      expect(problems).toEqual([]);
      await context.close();
    });
  }

  for (const code of ['ar', 'ur'] as const) {
    test(`${code}: the artwork is English and keeps its left-to-right layout, so no label runs off its frame`, async ({
      page,
    }) => {
      await page.goto(`/?lang=${code}`);
      await leaveSplash(page);
      const outside = await page.evaluate(() => {
        const frame = document.querySelector('.hero-art svg');
        if (!frame) return -1;
        const box = frame.getBoundingClientRect();
        return [...frame.querySelectorAll('text')].filter((t) => {
          const r = t.getBoundingClientRect();
          return r.left < box.left - 1 || r.right > box.right + 1;
        }).length;
      });
      expect(outside).toBe(0);
    });
  }

  // Right-to-left is where layout and contrast regress first, and Chinese is where the type scale does.
  for (const code of ['ar', 'ur', 'zh'] as const) {
    test(`${code}: passes the accessibility scan`, async ({ page }) => {
      await page.goto(`/?lang=${code}`);
      await leaveSplash(page);
      const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
      expect(results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`)).toEqual(
        [],
      );
    });
  }
});
