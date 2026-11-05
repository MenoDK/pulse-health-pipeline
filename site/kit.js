/* Site kit runtime. Renders the landing page, the sign-in page and the lab shell from window.SITE (content.js).
   No dependencies, no network requests of its own. Anything that came from an API is inserted with textContent. */
(() => {
  'use strict';

  /* ------------------------------------------------------------------ icons (24x24, stroke) */
  const ICONS = {
    shield: '<path d="M12 3l7.5 3v5.2c0 4.7-3.1 8.1-7.5 9.8-4.4-1.7-7.5-5.1-7.5-9.8V6L12 3z"/><path d="M9 12l2.2 2.2L15.5 10"/>',
    check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    lock: '<rect x="5" y="11" width="14" height="9.5" rx="2"/><path d="M8 11V8a4 4 0 018 0v3"/>',
    unlock: '<rect x="5" y="11" width="14" height="9.5" rx="2"/><path d="M8 11V8a4 4 0 017.6-1.7"/>',
    bolt: '<path d="M13 2.5L5 13.5h6l-1 8 8-11h-6l1-8z"/>',
    layers: '<path d="M12 3l9 5-9 5-9-5 9-5z"/><path d="M3 12.5l9 5 9-5"/><path d="M3 16.5l9 5 9-5"/>',
    search: '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
    doc: '<path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5M10 13h6M10 17h6"/>',
    cpu: '<rect x="7" y="7" width="10" height="10" rx="1.5"/><path d="M10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4"/>',
    branch: '<circle cx="7" cy="5.5" r="2.2"/><circle cx="7" cy="18.5" r="2.2"/><circle cx="17" cy="9" r="2.2"/><path d="M7 7.7v8.6M17 11.2c0 4-10 2-10 5.1"/>',
    terminal: '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/><path d="M7 10l3 2.2L7 14.5M12.5 15h4.5"/>',
    eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/>',
    'eye-off': '<path d="M3 3l18 18M10.6 5.7A9.6 9.6 0 0112 5.5c6 0 9.5 6.5 9.5 6.5a16 16 0 01-3.2 3.9M6.4 7.4A16 16 0 002.5 12S6 18.5 12 18.5c1.3 0 2.5-.3 3.5-.8"/><path d="M9.9 9.9a3 3 0 004.2 4.2"/>',
    cloud: '<path d="M7 18.5a4.5 4.5 0 01-.4-9 5.7 5.7 0 0111-1.2A4.9 4.9 0 0117 18.5H7z"/>',
    box: '<path d="M12 3l8.5 4.3v9.4L12 21l-8.5-4.3V7.3L12 3z"/><path d="M12 12l8.5-4.7M12 12v9M12 12L3.5 7.3"/>',
    chart: '<path d="M4 20V9M10 20V4M16 20v-8M22 20H2"/>',
    key: '<circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M16 7l3 3M14 9l2 2"/>',
    clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    users: '<circle cx="9" cy="8.5" r="3.2"/><path d="M3 20c0-3.4 2.7-6 6-6s6 2.6 6 6"/><path d="M16.5 5.6a3 3 0 010 5.8M18 14.4c1.8.8 3 2.7 3 5.6"/>',
    link: '<path d="M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 00-5.7 0l-3 3a4 4 0 005.7 5.7l1-1"/>',
    play: '<path d="M8 5.5v13l11-6.5z"/>',
    arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    'arrow-up-right': '<path d="M7 17L17 7M8 7h9v9"/>',
    'chevron-right': '<path d="M9 5l7 7-7 7"/>',
    'chevron-down': '<path d="M5 9l7 7 7-7"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M18.7 5.3l-1.6 1.6M6.9 17.1l-1.6 1.6"/>',
    moon: '<path d="M20 14.5A8.5 8.5 0 019.5 4a8.5 8.5 0 1010.5 10.5z"/>',
    menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
    x: '<path d="M6 6l12 12M18 6L6 18"/>',
    database: '<ellipse cx="12" cy="5.5" rx="8" ry="2.8"/><path d="M4 5.5v13c0 1.5 3.6 2.8 8 2.8s8-1.3 8-2.8v-13M4 12c0 1.5 3.6 2.8 8 2.8s8-1.3 8-2.8"/>',
    flask: '<path d="M9.5 3h5M10.5 3v6.2L5 18.5A2 2 0 006.7 21.5h10.6A2 2 0 0019 18.5l-5.5-9.3V3"/><path d="M8 15h8"/>',
    globe: '<circle cx="12" cy="12" r="8.8"/><path d="M3.2 12h17.6M12 3.2c3 2.8 3 14.8 0 17.6M12 3.2c-3 2.8-3 14.8 0 17.6"/>',
    mail: '<rect x="3" y="5.5" width="18" height="13" rx="2.5"/><path d="M3.5 7.5L12 13l8.5-5.5"/>',
    alert: '<path d="M12 3.5l9.5 16.5h-19L12 3.5z"/><path d="M12 10v4.5M12 17.4v.1"/>',
    server: '<rect x="3.5" y="4" width="17" height="6.5" rx="2"/><rect x="3.5" y="13.5" width="17" height="6.5" rx="2"/><path d="M7 7.2v.1M7 16.7v.1"/>',
    code: '<path d="M8.5 7L3.5 12l5 5M15.5 7l5 5-5 5M13.5 5l-3 14"/>',
    refresh: '<path d="M20 11a8 8 0 00-14.3-4M4 5v3.5h3.5M4 13a8 8 0 0014.3 4M20 19v-3.5h-3.5"/>',
    bot: '<rect x="4.5" y="8" width="15" height="11" rx="3"/><path d="M12 4v4M9 13v1.5M15 13v1.5M2.5 12.5v2M21.5 12.5v2"/><circle cx="12" cy="3.5" r="1"/>',
    spark: '<path d="M12 3l1.8 5.7L19.5 10.5l-5.7 1.8L12 18l-1.8-5.7L4.5 10.5l5.7-1.8L12 3z"/><path d="M19 17v4M17 19h4"/>',
    route: '<circle cx="6" cy="18" r="2.4"/><circle cx="18" cy="6" r="2.4"/><path d="M8.4 18H14a3.5 3.5 0 000-7h-4a3.5 3.5 0 010-7h5.6"/>',
    plug: '<path d="M9 3v5M15 3v5M6.5 8h11v3.5a5.5 5.5 0 01-11 0V8zM12 17v4"/>',
    radar: '<circle cx="12" cy="12" r="8.8"/><circle cx="12" cy="12" r="4.6"/><path d="M12 12l5.5-5.5"/><circle cx="12" cy="12" r="1"/>',
    wrench: '<path d="M14.5 6.5a4 4 0 005 5l-1 1-2-2-8.8 8.8a1.8 1.8 0 01-2.5-2.5L13 8l-2-2 1-1a4 4 0 002.5 1.5z"/>',
    scroll: '<path d="M8 4h10a2 2 0 012 2v11a3 3 0 01-3 3H7a3 3 0 003-3V6a2 2 0 00-2-2zM8 4a2 2 0 00-2 2v1h4"/><path d="M13 9h4M13 13h4"/>',
    gauge: '<path d="M4 17a8.5 8.5 0 1116 0"/><path d="M12 17l4-5.5"/><circle cx="12" cy="17" r="1.2"/>',
    network: '<circle cx="12" cy="5" r="2.3"/><circle cx="5" cy="18" r="2.3"/><circle cx="19" cy="18" r="2.3"/><path d="M11 7l-5 9M13 7l5 9M7.5 18h9"/>',
    fingerprint: '<path d="M6 14c0-4 2.5-7 6-7s6 3 6 7M9 20c0-2 .5-3.5.5-5.5a2.5 2.5 0 015 0c0 3-.5 4.5-1.5 7M12 12.5c0 3-.3 5-1.2 7.2M6.5 18c.8-1.5 1.5-3.6 1.5-6a4 4 0 018 0"/>',
    book: '<path d="M5 4.5h8a3 3 0 013 3V20a3 3 0 00-3-3H5V4.5zM19 4.5h-3"/><path d="M5 17.5V20"/>',
    pin: '<path d="M12 21s6-5.6 6-10.5a6 6 0 10-12 0C6 15.4 12 21 12 21z"/><circle cx="12" cy="10.5" r="2.3"/>',
    cog: '<circle cx="12" cy="12" r="3"/><path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M18.4 5.6l-1.8 1.8M7.4 16.6l-1.8 1.8"/>',
    heart: '<path d="M12 20s-7.5-4.6-7.5-10A4.3 4.3 0 0112 7.6 4.3 4.3 0 0119.5 10c0 5.4-7.5 10-7.5 10z"/>',
    hash: '<path d="M5 9h14M4 15h14M10 4L8 20M16 4l-2 16"/>',
    git: '<circle cx="12" cy="12" r="3"/><path d="M3 12h6M15 12h6"/>',
    leaf: '<path d="M5 19c0-8 5-14 15-14 0 10-6 15-14 15"/><path d="M5 19c3-5 6-8 10-10"/>',
    wave: '<path d="M2 12c2.5-6 4.5-6 7 0s4.5 6 7 0 4.5-6 6-3"/>',
  };

  /* ------------------------------------------------------------------ small helpers */
  const BASE = window.SITE;
  if (!BASE) throw new Error('content.js must define window.SITE before kit.js');
  let SITE = BASE; // the page content in the visitor's language (see "language" below); English until one is applied
  const $ = (sel, root = document) => root.querySelector(sel);
  const reduced = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'html') el.innerHTML = v; // trusted strings from content.js only
      else if (k === 'style') el.style.cssText = v; // CSSOM, not a style attribute: allowed by a strict CSP
      else if (k.startsWith('on')) el.addEventListener(k.slice(2).toLowerCase(), v);
      else el.setAttribute(k, v === true ? '' : String(v));
    }
    for (const kid of kids.flat(Infinity)) {
      if (kid === null || kid === undefined || kid === false) continue;
      el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }
  const DIRECTIONAL = new Set(['arrow', 'arrow-up-right', 'chevron-right']); // mirrored by CSS under dir="rtl"
  const icon = (name, size = 20) =>
    h('span', {
      class: DIRECTIONAL.has(name) ? 'ico dir' : 'ico',
      'aria-hidden': 'true',
      html: `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${ICONS[name] || ICONS.spark}</svg>`,
    });
  const store = {
    get(k, area = 'localStorage') {
      try {
        return window[area].getItem(k);
      } catch {
        return null;
      }
    },
    set(k, v, area = 'localStorage') {
      try {
        window[area].setItem(k, v);
      } catch {
        /* storage can be blocked: the page works without it */
      }
    },
    del(k, area = 'localStorage') {
      try {
        window[area].removeItem(k);
      } catch {
        /* ignore */
      }
    },
  };

  /* ------------------------------------------------------------------ theme + accent */
  function paintAccent(theme) {
    const a = SITE.accent[theme] || SITE.accent.light;
    const s = document.documentElement.style;
    s.setProperty('--accent', a.fill);
    s.setProperty('--accent-ink', a.ink);
    s.setProperty('--on-accent', a.on);
    s.setProperty('--accent-soft', a.soft);
    s.setProperty('--accent-on-navy', a.onNavy || a.fill);
  }
  function setTheme(theme) {
    document.documentElement.dataset.theme = theme;
    paintAccent(theme);
    store.set('theme', theme);
  }
  function currentTheme() {
    return document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
  }
  (function initTheme() {
    const saved = store.get('theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const theme = saved || (prefersDark ? 'dark' : 'light');
    document.documentElement.dataset.theme = theme;
    paintAccent(theme);
    // Follow the system while the visitor has not chosen a theme themselves.
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener?.('change', (e) => {
      if (store.get('theme')) return;
      const next = e.matches ? 'dark' : 'light';
      document.documentElement.dataset.theme = next;
      paintAccent(next);
      document.dispatchEvent(new CustomEvent('kit:theme'));
    });
  })();

  /* ------------------------------------------------------------------ language
     English is the source: the strings below and content.js. Every other language is an overlay loaded on demand:
       i18n/ui.js      page chrome (navigation, buttons, footer, author bio), shared by every site and kept identical
       i18n/<code>.js  this site's own content, same shape as window.SITE, only the text
     Whatever an overlay does not say falls back to English, so a half-translated language still works. */
  const LANGS = [
    ['en', 'English'], ['zh', '中文'], ['hi', 'हिन्दी'], ['es', 'Español'], ['fr', 'Français'], ['ar', 'العربية'], ['bn', 'বাংলা'],
    ['pt', 'Português'], ['ru', 'Русский'], ['ur', 'اردو'], ['id', 'Bahasa Indonesia'], ['de', 'Deutsch'], ['ja', '日本語'], ['ko', '한국어'],
  ];
  const LANG_CODES = LANGS.map(([code]) => code);
  const RTL = new Set(['ar', 'ur']);
  const HTML_LANG = { zh: 'zh-Hans', pt: 'pt-BR' };
  const UI_EN = {
    language: 'Language',
    home: '{name} home',
    'theme.light': 'Use the light theme',
    'theme.dark': 'Use the dark theme',
    'menu.open': 'Open menu',
    'menu.close': 'Close menu',
    'nav.main': 'Main',
    'nav.tour': 'Tour',
    'nav.hard': 'Hard parts',
    'nav.run': 'Run it',
    'nav.under': 'Under the hood',
    'nav.about': 'About',
    'nav.overview': 'Overview',
    'nav.source': 'Source',
    skip: 'Skip to content',
    'skip.form': 'Skip to the form',
    'skip.lab': 'Skip to the lab',
    copy: 'Copy',
    copied: 'Copied',
    'copy.manual': 'Select and copy',
    'art.note': 'Original illustration',
    'tour.group': 'Explore the product',
    'tour.output': 'Example output',
    'tour.open': 'Open this in the lab',
    'tour.tag': 'Real output',
    'hard.group': 'Hard parts to try',
    'hard.see': 'You should see',
    'hard.try': 'Try it in the lab',
    stack: 'Stack',
    measured: 'Measured, not claimed',
    'not.built': 'Not built yet',
    'about.eyebrow': 'Who built this',
    'about.repo': 'This repository',
    'faq.eyebrow': 'Questions',
    'faq.title1': 'Asked often,',
    'faq.title2': 'answered plainly.',
    'faq.text': 'Short answers. The long ones are in the decision records.',
    'footer.line1': '{name} · MIT licence · fictional data only',
    'footer.line2': 'Written by hand, tested against real services.',
    'password.show': 'Show password',
    'password.hide': 'Hide password',
    'auth.scene': 'Illustration',
    'auth.local': '{language} · local environment',
    'lab.sections': 'Lab sections',
    'lab.signout': 'Sign out',
    'author.role': 'Full-stack developer',
    'author.place': 'São Paulo, Brazil',
    'author.bio1': 'I build web, mobile and desktop products from the business rule to the deployment, and I have been doing it professionally since 2022: React, Next.js, TypeScript, Node.js and Python, with APIs, databases and applied AI.',
    'author.bio2': 'The projects I enjoy most are the ones where a failure has a cost: money that must add up, data that must stay inside a boundary, a retry that must not run twice. Those are the parts these repositories try to prove with tests, not describe.',
    'author.languages': 'English (technical, intermediate) · Spanish (intermediate) · Portuguese (native)',
  };
  let LANG = 'en';
  let UI = UI_EN;
  const t = (key, vars) => {
    let text = UI[key] ?? UI_EN[key] ?? key;
    if (vars) for (const [k, v] of Object.entries(vars)) text = text.replaceAll(`{${k}}`, v);
    return text;
  };
  const languageName = () => LANGS.find(([code]) => code === LANG)[1];

  /** Overlay the translated text on the English content. Shape comes from the base, so a stale or misspelt key in a
   *  translation is ignored here, and the language tests catch it; arrays merge by position. */
  function localize(base, over) {
    if (over === undefined || over === null) return base;
    if (Array.isArray(base)) return base.map((item, i) => localize(item, Array.isArray(over) ? over[i] : undefined));
    if (base && typeof base === 'object') {
      if (typeof over !== 'object') return base;
      const merged = {};
      for (const key of Object.keys(base)) merged[key] = localize(base[key], over[key]);
      return merged;
    }
    return typeof over === typeof base ? over : base;
  }
  function pickLanguage() {
    const asked = new URLSearchParams(location.search).get('lang'); // ?lang=ja for a link that opens in a language
    if (asked && LANG_CODES.includes(asked)) return asked;
    const saved = store.get('lang');
    if (saved && LANG_CODES.includes(saved)) return saved;
    for (const tag of navigator.languages || [navigator.language]) {
      const primary = String(tag).toLowerCase().split('-')[0];
      if (LANG_CODES.includes(primary)) return primary;
    }
    return 'en';
  }
  const scriptsLoaded = new Map();
  function loadScript(src) {
    if (!scriptsLoaded.has(src)) {
      scriptsLoaded.set(
        src,
        new Promise((resolve) => {
          const el = document.createElement('script');
          el.src = src;
          el.async = true;
          el.onload = () => resolve(true);
          el.onerror = () => resolve(false); // a missing translation must never take the page down
          document.head.append(el);
        })
      );
    }
    return scriptsLoaded.get(src);
  }
  async function applyLanguage(code) {
    let ui = {};
    let over;
    if (code !== 'en') {
      await Promise.all([loadScript('i18n/ui.js'), loadScript(`i18n/${code}.js`)]);
      ui = (window.KIT_UI || {})[code] || {};
      over = (window.SITE_I18N || {})[code];
    }
    LANG = code;
    UI = { ...UI_EN, ...ui };
    SITE = localize(BASE, over);
    const root = document.documentElement;
    root.lang = HTML_LANG[code] || code;
    root.dir = RTL.has(code) ? 'rtl' : 'ltr';
    document.title = SITE.title || SITE.name;
  }
  function languageSelect() {
    const select = h(
      'select',
      { class: 'lang-select', 'aria-label': t('language') },
      LANGS.map(([code, name]) => h('option', { value: code, lang: HTML_LANG[code] || code }, name))
    );
    select.value = LANG;
    select.addEventListener('change', () => switchLanguage(select.value));
    return h('span', { class: 'lang' }, icon('globe', 16), select);
  }
  async function switchLanguage(code) {
    store.set('lang', code);
    const url = new URL(location.href);
    if (url.searchParams.has('lang')) {
      // A ?lang= in the address outranks the saved choice, so a reload would put the old language back.
      url.searchParams.set('lang', code);
      history.replaceState(history.state, '', url);
    }
    if (document.body.dataset.page === 'lab') return location.reload(); // the lab body is built once and holds live state
    const y = window.scrollY;
    await applyLanguage(code);
    landing();
    window.scrollTo({ top: y, behavior: 'instant' }); // the page's smooth scrolling would animate from the top
    $('.lang-select')?.focus();
  }

  /* ------------------------------------------------------------------ loading stage (splash + inline) */
  const DEFAULT_SKETCH = 'M10 118C58 38 104 152 168 78S292 22 332 96';
  function stage(cfg, { compact = false } = {}) {
    const l = cfg || SITE.loading;
    const sats = (l.satellites || ['lock', 'search', 'check']).slice(0, 3);
    return h(
      'div',
      { class: `stage-screen${compact ? ' compact' : ''}`, role: 'status', 'aria-live': 'polite' },
      h('span', { class: 'loading-context' }, icon(l.icon || 'spark', 14), l.context || SITE.short),
      h(
        'div',
        { class: 'loading-stage' },
        h('svg', { class: 'loading-signature', viewBox: '0 0 340 160', 'aria-hidden': 'true', html: `<path d="${l.sketch || DEFAULT_SKETCH}"/>` }),
        h(
          'div',
          { class: 'loading-orb' },
          h('span', { class: 'loading-halo' }),
          h('span', { class: 'loading-wave' }),
          h('span', { class: 'loading-wave second' }),
          h('span', { class: 'loading-arc' }),
          h('span', { class: 'loading-face' }, icon(l.icon || 'spark', 34))
        ),
        sats.map((name, i) => h('span', { class: `loading-satellite satellite-${i}`, 'aria-hidden': 'true' }, icon(name, 15)))
      ),
      h(
        'div',
        { class: 'loading-copy' },
        h('h2', {}, l.title, h('span', { class: 'loading-dots', 'aria-hidden': 'true' }, h('i'), h('i'), h('i'))),
        h('p', {}, l.text)
      ),
      l.foot ? h('span', { class: 'loading-foot' }, icon('shield', 13), l.foot) : null
    );
  }
  const splashStartedAt = performance.now();
  function showSplash() {
    let el = $('#splash');
    if (!el) {
      el = h('div', { id: 'splash' });
      document.body.prepend(el);
    }
    el.replaceChildren(stage(SITE.loading));
  }
  function hideSplash() {
    const el = $('#splash');
    if (!el) return;
    const minimum = reduced() ? 0 : SITE.loading.minimumMs ?? 1100;
    const wait = Math.max(0, minimum - (performance.now() - splashStartedAt));
    setTimeout(() => {
      el.classList.add('done');
      setTimeout(() => el.remove(), 450);
    }, wait);
  }

  /* ------------------------------------------------------------------ shared pieces */
  const AUTHOR = {
    name: 'Davi Martins',
    initials: 'DM',
    github: 'https://github.com/MenoDK',
    linkedin: 'https://www.linkedin.com/in/davi-martins-43444a287/',
    // The wording is looked up when read, so it follows the language the visitor picked.
    get role() {
      return t('author.role');
    },
    get place() {
      return t('author.place');
    },
    get bio() {
      return [t('author.bio1'), t('author.bio2')];
    },
    get languages() {
      return t('author.languages');
    },
  };

  function brand(href) {
    return h('a', { class: 'brand', href: href || 'index.html', 'aria-label': t('home', { name: SITE.name }) }, h('span', { class: 'brand-mark' }, icon(SITE.logo || 'shield', 20)), SITE.name);
  }
  function themeButton() {
    const btn = h('button', { class: 'circle-btn', type: 'button' });
    const paint = () => {
      const dark = currentTheme() === 'dark';
      btn.replaceChildren(icon(dark ? 'sun' : 'moon', 17));
      btn.setAttribute('aria-label', t(dark ? 'theme.light' : 'theme.dark'));
    };
    btn.addEventListener('click', () => {
      setTheme(currentTheme() === 'dark' ? 'light' : 'dark');
      paint();
    });
    document.addEventListener('kit:theme', paint);
    paint();
    return btn;
  }
  function header({ links, cta, signin }) {
    const nav = h('nav', { class: 'nav', id: 'site-nav', 'aria-label': t('nav.main') }, links.map(([href, label]) => h('a', { href }, label)));
    const menu = h('button', { class: 'circle-btn menu-btn', type: 'button', 'aria-expanded': 'false', 'aria-controls': 'site-nav', 'aria-label': t('menu.open') }, icon('menu', 18));
    menu.addEventListener('click', () => {
      const open = nav.classList.toggle('open');
      menu.setAttribute('aria-expanded', String(open));
      menu.setAttribute('aria-label', t(open ? 'menu.close' : 'menu.open'));
      menu.replaceChildren(icon(open ? 'x' : 'menu', 18));
    });
    nav.addEventListener('click', (e) => {
      if (e.target.closest('a')) nav.classList.remove('open');
    });
    return h(
      'header',
      { class: 'header' },
      brand(),
      nav,
      h(
        'div',
        { class: 'header-actions' },
        languageSelect(),
        themeButton(),
        signin ? h('a', { class: 'header-link', href: signin.href }, signin.label, icon('arrow-up-right', 15)) : null,
        cta ? h('a', { class: 'button primary', href: cta.href }, cta.label, icon('arrow', 15)) : null,
        menu
      )
    );
  }
  function copyButton(getText) {
    const b = h('button', { class: 'copy', type: 'button' }, t('copy'));
    b.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(getText());
        b.textContent = t('copied');
      } catch {
        b.textContent = t('copy.manual');
      }
      setTimeout(() => (b.textContent = t('copy')), 1600);
    });
    return b;
  }
  let toastTimer;
  function toast(message, bad = false) {
    $('.toast')?.remove();
    const t = h('div', { class: `toast${bad ? ' bad' : ''}`, role: 'status' }, message);
    document.body.append(t);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.remove(), 4200);
  }
  function observeReveal(root) {
    const items = [...root.querySelectorAll('.reveal')];
    if (!('IntersectionObserver' in window) || reduced()) {
      items.forEach((i) => i.classList.add('in'));
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            e.target.classList.add('in');
            io.unobserve(e.target);
          }
        }
      },
      { rootMargin: '0px 0px -8% 0px' }
    );
    items.forEach((i) => io.observe(i));
  }
  const eyebrow = (text) => h('span', { class: 'eyebrow' }, h('i'), text);
  const heading = (tag, first, second) => h(tag, {}, first, second ? h('em', {}, second) : null);

  /* ------------------------------------------------------------------ landing */
  function landing() {
    const H = SITE.hero;
    const root = $('#root');
    const labHref = SITE.lab.href;

    // hero
    const hero = h(
      'section',
      { class: 'hero' },
      h(
        'div',
        { class: 'hero-copy', style: reduced() ? null : 'animation: loading-reveal 600ms var(--ease-out) both' },
        eyebrow(H.eyebrow),
        h('h1', {}, H.lead, h('em', {}, H.soft)),
        h('p', {}, H.text),
        h(
          'div',
          { class: 'hero-actions' },
          h('a', { class: 'button primary', href: H.primary.href }, H.primary.label, icon('arrow', 17)),
          h('a', { class: 'watch', href: H.secondary.href }, icon(H.secondary.icon || 'layers', 18), H.secondary.label)
        ),
        H.pilot ? h('div', { class: 'pilot' }, icon('shield', 15), H.pilot) : null,
        h(
          'div',
          { class: 'hero-proof' },
          H.proof.map((p) => h('div', {}, icon(p.icon, 21), h('span', {}, p.a, h('br'), h('strong', {}, p.b))))
        )
      ),
      h(
        'div',
        { class: 'visual-wrap' },
        h(
          'div',
          { class: 'hero-visual' },
          h('div', { class: 'hero-art float', 'aria-hidden': 'true', html: H.art }),
          h('div', { class: 'visual-top' }, h('span', {}, H.top[0]), h('span', {}, H.top[1])),
          h('small', { class: 'image-note' }, t('art.note'))
        ),
        h(
          'div',
          { class: 'status-card' },
          h('span', { class: 'ico status-icon' }, icon(H.status.icon, 24)),
          h('div', {}, h('small', {}, H.status.small), h('strong', {}, H.status.strong)),
          icon('check', 20)
        )
      )
    );

    // principles
    const P = SITE.principles;
    const principles = h(
      'div',
      { class: 'principles' },
      h('span', {}, P.lead[0], h('br'), h('strong', {}, P.lead[1])),
      P.items.map(([ic, text]) => h('div', {}, icon(ic, 19), text))
    );

    // tour: tabs + window stage + modules
    const T = SITE.tour;
    let tourIndex = 0;
    const tabsEl = h('div', { class: 'product-tabs', role: 'group', 'aria-label': t('tour.group') });
    const windowTitle = h('small');
    const windowBody = h('div', { class: 'window-body', role: 'region', tabindex: '0', 'aria-label': t('tour.output') });
    const capTitle = h('h3');
    const capText = h('p');
    const capLink = h('a', { class: 'text-link', href: labHref }, t('tour.open'), icon('arrow-up-right', 16));
    function paintTour() {
      const t = T.tabs[tourIndex];
      [...tabsEl.children].forEach((b, i) => b.setAttribute('aria-pressed', String(i === tourIndex)));
      windowTitle.textContent = `${SITE.short} · ${t.label}`;
      windowBody.replaceChildren(h('pre', { html: t.transcript }));
      windowBody.classList.remove('arrive');
      void windowBody.offsetWidth;
      if (!reduced()) windowBody.classList.add('arrive');
      capTitle.textContent = t.title;
      capText.textContent = t.text;
      capLink.setAttribute('href', t.lab || labHref);
    }
    T.tabs.forEach((t, i) =>
      tabsEl.append(
        h('button', { type: 'button', 'aria-pressed': 'false', onclick: () => { tourIndex = i; paintTour(); } }, icon(t.icon, 18), t.label, icon('arrow-up-right', 15))
      )
    );
    const tour = h(
      'section',
      { id: 'tour', class: 'section' },
      h(
        'div',
        { class: 'section-head reveal' },
        h('div', {}, eyebrow(T.eyebrow), heading('h2', T.title[0], T.title[1])),
        h('p', {}, T.text)
      ),
      tabsEl,
      h(
        'div',
        { class: 'window reveal' },
        h('div', { class: 'window-bar' }, h('span', {}, h('i'), h('i'), h('i')), windowTitle, h('span', { class: 'window-tag' }, T.tag || t('tour.tag'))),
        windowBody,
        h('div', { class: 'window-caption' }, h('div', {}, capTitle, capText), capLink)
      ),
      h('div', { class: 'modules-heading' }, h('h3', {}, T.modulesTitle), h('span', {}, T.modulesNote)),
      h(
        'div',
        { class: 'modules reveal' },
        T.modules.map(([ic, title, text], i) => h('article', {}, h('span', { class: 'module-number' }, String(i + 1).padStart(2, '0')), icon(ic, 23), h('h3', {}, title), h('p', {}, text)))
      ),
      h('div', { class: 'availability' }, icon('alert', 20), h('p', {}, h('strong', {}, T.transparency.strong), ' ', T.transparency.text))
    );

    // challenges (navy band)
    const C = SITE.challenges;
    let chalIndex = 0;
    const list = h('div', { class: 'profile-list', role: 'group', 'aria-label': t('hard.group') });
    const detail = h('div', { class: 'profile-detail' });
    function paintChal() {
      const c = C.items[chalIndex];
      [...list.children].forEach((b, i) => b.setAttribute('aria-pressed', String(i === chalIndex)));
      detail.replaceChildren(
        h('span', { class: 'chip-access' }, c.access),
        h('h3', {}, c.title),
        h('p', {}, c.text),
        h('ol', {}, c.steps.map((s) => h('li', {}, h('span', { html: s })))),
        h('div', { class: 'expect' }, h('small', {}, t('hard.see')), c.expect),
        h('a', { class: 'button primary', href: c.lab || labHref }, t('hard.try'), icon('arrow', 17)),
        h('span', { class: 'emblem', 'aria-hidden': 'true' }, icon(c.icon, 110))
      );
      if (!reduced()) {
        detail.classList.remove('arrive');
        void detail.offsetWidth;
        detail.classList.add('arrive');
      }
    }
    C.items.forEach((c, i) =>
      list.append(h('button', { type: 'button', 'aria-pressed': 'false', onclick: () => { chalIndex = i; paintChal(); } }, icon(c.icon, 19), c.label, icon('chevron-right', 16)))
    );
    const challenges = h(
      'section',
      { id: 'hard-parts', class: 'band' },
      h('div', { class: 'section-head' }, h('div', {}, eyebrow(C.eyebrow), heading('h2', C.title[0], C.title[1])), h('p', {}, C.text)),
      h('div', { class: 'band-layout' }, list, detail)
    );

    // run it
    const R = SITE.run;
    const termText = R.terminal.lines.map((l) => (l.startsWith('#') ? l : `$ ${l}`)).join('\n');
    const term = h(
      'div',
      { class: 'term reveal' },
      h('div', { class: 'term-bar' }, h('span', {}, R.terminal.title), copyButton(() => R.terminal.lines.filter((l) => !l.startsWith('#')).join('\n'))),
      h('pre', {}, h('code', { html: R.terminal.lines.map((l) => (l.startsWith('#') ? `<span class="c">${l}</span>` : `<span class="p">$</span> ${l}`)).join('\n') }))
    );
    void termText;
    const run = h(
      'section',
      { id: 'run', class: 'section' },
      h('div', { class: 'section-head reveal' }, h('div', {}, eyebrow(R.eyebrow), heading('h2', R.title[0], R.title[1])), h('p', {}, R.text)),
      h('div', { class: 'journey reveal' }, R.steps.map(([ic, title, text], i) => h('article', {}, h('span', { class: 'num' }, String(i + 1).padStart(2, '0')), icon(ic, 22), h('h3', {}, title), h('p', {}, text)))),
      term
    );

    // under the hood
    const U = SITE.under;
    const under = h(
      'section',
      { id: 'under-the-hood', class: 'section', style: 'padding-top:25px' },
      h('div', { class: 'section-head reveal' }, h('div', {}, eyebrow(U.eyebrow), heading('h2', U.title[0], U.title[1])), h('p', {}, U.text)),
      h(
        'div',
        { class: 'duo' },
        h(
          'article',
          { class: 'card reveal' },
          h('div', { class: 'card-top' }, h('span', {}, t('stack')), icon('layers', 18)),
          h('h3', {}, U.stackTitle),
          U.stack.map((g) => h('div', { class: 'stack-group' }, h('h4', {}, g.group), h('div', { class: 'pills' }, g.items.map((it) => h('span', { class: `pill${g.fresh ? ' new' : ''}` }, it))))),
          U.stackNote ? h('small', { class: 'fine' }, U.stackNote) : null
        ),
        h(
          'article',
          { class: 'card featured reveal' },
          h('div', { class: 'card-top' }, h('span', {}, t('measured')), icon('gauge', 18)),
          h('h3', {}, U.proofTitle),
          h('div', { class: 'numbers' }, U.numbers.map(([v, label]) => h('div', {}, h('strong', {}, v), h('span', {}, label)))),
          h('ul', { class: 'checks' }, U.decisions.map(([t, s, href]) => h('li', {}, icon('check', 16), h('div', {}, href ? h('a', { href: `${SITE.repo}/blob/main/${href}`, rel: 'noopener' }, t) : t, h('small', {}, s))))),
          h('small', { class: 'fine' }, U.measuredOn)
        )
      ),
      h(
        'div',
        { class: 'callout reveal' },
        icon('clock', 24),
        h('div', {}, h('h3', {}, t('not.built')), h('p', {}, U.future.map((f, i) => [i ? ' · ' : '', h('strong', {}, f[0]), ` ${f[1]}`])))
      )
    );

    // about
    const A = SITE.about;
    const about = h(
      'section',
      { id: 'about', class: 'section about' },
      h('div', { class: 'reveal' }, h('div', { class: 'portrait', 'aria-hidden': 'true' }, AUTHOR.initials), eyebrow(t('about.eyebrow')), h('h2', {}, AUTHOR.name, h('em', {}, AUTHOR.role))),
      h(
        'div',
        { class: 'reveal' },
        AUTHOR.bio.map((p) => h('p', {}, p)),
        A ? h('p', {}, A.why) : null,
        h('p', {}, AUTHOR.place, ' · ', AUTHOR.languages),
        h(
          'div',
          { class: 'about-links' },
          h('a', { class: 'button secondary', href: AUTHOR.github, rel: 'noopener' }, 'GitHub', icon('arrow-up-right', 16)),
          h('a', { class: 'button secondary', href: AUTHOR.linkedin, rel: 'noopener' }, 'LinkedIn', icon('arrow-up-right', 16)),
          h('a', { class: 'button ghost', href: SITE.repo, rel: 'noopener' }, t('about.repo'), icon('arrow-up-right', 16))
        )
      )
    );

    // faq
    const faq = h(
      'section',
      { id: 'faq', class: 'section faq' },
      h('div', { class: 'reveal' }, eyebrow(t('faq.eyebrow')), heading('h2', t('faq.title1'), t('faq.title2')), h('p', {}, t('faq.text'))),
      h('div', { class: 'reveal' }, SITE.faq.map(([q, a]) => h('details', {}, h('summary', {}, q, icon('chevron-down', 18)), h('p', {}, a))))
    );

    // closing + footer
    const Z = SITE.closing;
    const closing = h(
      'section',
      { class: 'closing reveal' },
      eyebrow(Z.eyebrow),
      heading('h2', Z.title[0], Z.title[1]),
      h('a', { class: 'button primary', href: labHref }, Z.button, icon('arrow', 17)),
      h('p', {}, Z.fine)
    );
    const footer = h(
      'footer',
      { class: 'footer' },
      brand(),
      h('p', {}, t('footer.line1', { name: SITE.name }), h('br'), t('footer.line2')),
      h('div', { class: 'footer-links' }, h('a', { href: SITE.repo, rel: 'noopener' }, t('nav.source')), h('a', { href: AUTHOR.github, rel: 'noopener' }, 'GitHub'), h('a', { href: AUTHOR.linkedin, rel: 'noopener' }, 'LinkedIn'))
    );

    root.replaceChildren(
      h('a', { class: 'skip', href: '#main' }, t('skip')),
      header({
        links: [['#tour', t('nav.tour')], ['#hard-parts', t('nav.hard')], ['#run', t('nav.run')], ['#under-the-hood', t('nav.under')], ['#about', t('nav.about')]],
        cta: { href: labHref, label: SITE.lab.cta || 'Enter the lab' },
        signin: SITE.lab.signin ? { href: labHref, label: SITE.lab.signin } : null,
      }),
      h('main', { id: 'main', tabindex: '-1' }, hero, principles, tour, challenges, run, under, about, faq, closing),
      footer
    );
    paintTour();
    paintChal();
    observeReveal(root);
  }

  /* ------------------------------------------------------------------ sign-in page (split layout) */
  function authPage(cfg) {
    return new Promise((resolve) => {
      let mode = 'login';
      let storyIndex = 0;
      let busy = false;
      const root = $('#root');
      const values = {};
      const card = h('div', { class: 'auth-card' });
      const story = h('div', { class: 'story-copy' });
      const art = h('div', { class: 'hero-art', 'aria-hidden': 'true', html: SITE.hero.art });

      function paintStory(i) {
        const s = cfg.stories[i];
        story.replaceChildren(h('div', { class: 'story-swap' }, h('h2', {}, s.title), h('p', {}, s.text)));
      }
      function field(f) {
        const input = h('input', {
          id: `f-${f.name}`,
          name: f.name,
          type: f.type || 'text',
          required: f.required === false ? null : true,
          autocomplete: f.autocomplete || 'off',
          placeholder: f.placeholder || '',
          minlength: f.minlength || null,
          spellcheck: 'false',
        });
        input.value = values[f.name] ?? f.default ?? '';
        input.addEventListener('input', () => (values[f.name] = input.value));
        values[f.name] = input.value;
        const wrap = h('span', { class: 'input-icon' }, icon(f.icon || 'key', 18), input);
        if (f.type === 'password') {
          const toggle = h('button', { type: 'button', 'aria-label': t('password.show'), 'aria-pressed': 'false' }, icon('eye', 18));
          toggle.addEventListener('click', () => {
            const show = input.type === 'password';
            input.type = show ? 'text' : 'password';
            toggle.setAttribute('aria-pressed', String(show));
            toggle.setAttribute('aria-label', t(show ? 'password.hide' : 'password.show'));
            toggle.replaceChildren(icon(show ? 'eye-off' : 'eye', 18));
          });
          wrap.append(toggle);
        }
        return h('div', { class: 'field' }, h('div', { class: 'field-label' }, h('label', { for: `f-${f.name}` }, f.label)), wrap);
      }
      function paintCard() {
        const m = cfg.modes[mode];
        const feedback = h('div', { class: 'feedback', role: 'alert', hidden: true });
        const submit = h('button', { class: 'button primary submit', type: 'submit' }, h('span', {}, m.submit), icon('arrow', 18));
        const form = h('form', { class: 'fields', novalidate: false }, m.fields.map(field), feedback, submit);
        form.addEventListener('submit', async (e) => {
          e.preventDefault();
          if (busy) return;
          busy = true;
          submit.setAttribute('aria-busy', 'true');
          submit.disabled = true;
          submit.firstChild.textContent = m.busy;
          feedback.hidden = true;
          try {
            await cfg.onSubmit(mode, { ...values });
            resolve();
          } catch (err) {
            feedback.hidden = false;
            feedback.className = 'feedback error';
            feedback.textContent = err instanceof Error ? err.message : String(err);
            submit.firstChild.textContent = m.submit;
          } finally {
            busy = false;
            submit.removeAttribute('aria-busy');
            submit.disabled = false;
          }
        });
        const kids = [
          h('span', { class: 'eyebrow' }, m.eyebrow),
          h('h1', {}, m.title),
          h('p', { class: 'lead' }, m.lead),
          form,
        ];
        if (m.switchTo) {
          kids.push(
            h('p', { class: 'auth-switch' }, `${m.switchText} `, h('button', { type: 'button', onclick: () => { mode = m.switchTo; paintCard(); } }, m.switchLabel))
          );
        }
        if (cfg.demo) {
          const select = h('select', { 'aria-label': cfg.demo.label }, h('option', { value: '', disabled: true, selected: true }, cfg.demo.placeholder), cfg.demo.options.map((o, i) => h('option', { value: String(i) }, o.label)));
          select.addEventListener('change', () => {
            const o = cfg.demo.options[Number(select.value)];
            storyIndex = o.story ?? storyIndex;
            paintStory(storyIndex);
            if (o.mode && o.mode !== mode) mode = o.mode;
            Object.assign(values, o.values);
            paintCard();
          });
          kids.push(
            h(
              'details',
              { class: 'demo' },
              h('summary', {}, h('span', { class: 'ico demo-icon' }, icon('users', 18)), h('span', {}, h('strong', {}, cfg.demo.title), h('small', {}, cfg.demo.subtitle)), icon('chevron-right', 18)),
              h('div', { class: 'demo-body' }, h('p', {}, cfg.demo.text), select, cfg.demo.note ? h('small', {}, cfg.demo.note) : null)
            )
          );
        }
        card.replaceChildren(...kids);
      }
      paintCard();
      paintStory(0);

      root.replaceChildren(
        h('a', { class: 'skip', href: '#auth-main' }, t('skip.form')),
        h(
          'main',
          { class: 'auth', id: 'auth-main' },
          h(
            'section',
            { class: 'auth-side' },
            h('div', { class: 'auth-top' }, brand(), h('div', { class: 'header-actions' }, languageSelect(), themeButton())),
            h('div', { class: 'auth-center' }, card),
            h('footer', { class: 'auth-bottom' }, h('span', {}, icon('shield', 15), cfg.bottom), h('small', {}, t('auth.local', { language: languageName() })))
          ),
          h('section', { class: 'auth-scene', 'aria-label': t('auth.scene') }, art, h('div', { class: 'auth-shade' }), h('span', { class: 'story-tag' }, h('i'), cfg.tag), story)
        )
      );
    });
  }

  /* ------------------------------------------------------------------ lab shell */
  const session = {
    key: () => store.get('lab-key', 'sessionStorage'),
    set: (k) => store.set('lab-key', k, 'sessionStorage'),
    clear: () => store.del('lab-key', 'sessionStorage'),
  };
  async function api(path, { method = 'GET', body, headers = {}, auth = true } = {}) {
    const init = { method, headers: { ...headers } };
    if (body !== undefined) {
      init.headers['content-type'] = init.headers['content-type'] || 'application/json';
      init.body = typeof body === 'string' ? body : JSON.stringify(body);
    }
    const key = session.key();
    if (auth && key && SITE.auth?.header) init.headers[SITE.auth.header] = key;
    const started = performance.now();
    const res = await fetch(path, init);
    const text = await res.text();
    let data = text;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      /* keep text */
    }
    return { ok: res.ok, status: res.status, data, ms: Math.round(performance.now() - started), headers: res.headers };
  }
  const pretty = (v) => (typeof v === 'string' ? v : JSON.stringify(v, null, 2));
  async function busy(btn, fn) {
    if (btn.disabled) return;
    btn.disabled = true;
    btn.setAttribute('aria-busy', 'true');
    try {
      return await fn();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), true);
    } finally {
      btn.disabled = false;
      btn.removeAttribute('aria-busy');
    }
  }
  const button = (label, onClick, { variant = 'secondary', ic, small = false } = {}) =>
    h('button', { type: 'button', class: `button ${variant}${small ? ' small' : ''}`, onclick: (e) => busy(e.currentTarget, onClick) }, label, ic ? icon(ic, 15) : null);
  const badge = (text, kind = '') => h('span', { class: `badge ${kind}` }, text);
  const out = (value, id) => h('pre', { class: 'out', id: id || null, tabindex: '0' }, value === null || value === undefined ? '' : pretty(value));
  const kv = (obj) => h('dl', { class: 'kv' }, Object.entries(obj).flatMap(([k, v]) => [h('dt', {}, k), h('dd', {}, v instanceof Node ? v : String(v))]));
  const box = (title, hint, ...kids) => h('section', { class: 'box' }, title ? h('h3', {}, title) : null, hint ? h('p', { class: 'hint' }, hint) : null, ...kids);
  const labelled = (text, control) => [h('label', { for: control.id }, text), control];

  function lab() {
    const L = window.LAB;
    const root = $('#root');
    function build() {
      const panels = {};
      const tabs = h('div', { class: 'tabs', role: 'tablist', 'aria-label': t('lab.sections') });
      const body = h('div', {});
      L.tabs.forEach((t, i) => {
        const tabEl = h('button', { type: 'button', role: 'tab', id: `tab-${t.id}`, 'aria-selected': 'false', 'aria-controls': `panel-${t.id}`, tabindex: '-1' }, icon(t.icon, 18), t.label);
        const panel = h('div', { role: 'tabpanel', id: `panel-${t.id}`, 'aria-labelledby': `tab-${t.id}`, hidden: true, tabindex: '0' });
        panels[t.id] = { panel, tabEl, rendered: false, def: t };
        tabEl.addEventListener('click', () => select(t.id));
        tabEl.addEventListener('keydown', (e) => {
          const order = L.tabs.map((x) => x.id);
          const at = order.indexOf(t.id);
          const move = { ArrowRight: 1, ArrowLeft: -1, Home: -at, End: order.length - 1 - at }[e.key];
          if (move === undefined) return;
          e.preventDefault();
          const next = order[(at + move + order.length) % order.length];
          select(next);
          panels[next].tabEl.focus();
        });
        tabs.append(tabEl);
        body.append(panel);
        void i;
      });
      let current = L.tabs[0].id;
      function select(id) {
        current = id;
        for (const [pid, p] of Object.entries(panels)) {
          const on = pid === id;
          p.tabEl.setAttribute('aria-selected', String(on));
          p.tabEl.tabIndex = on ? 0 : -1;
          p.panel.hidden = !on;
          if (on && !p.rendered) {
            p.rendered = true;
            Promise.resolve(p.def.render(p.panel, { api, h, icon, button, badge, out, kv, box, labelled, toast, pretty, copyButton, stage })).catch((e) =>
              toast(e instanceof Error ? e.message : String(e), true)
            );
          }
        }
        if (location.hash !== `#${id}`) history.replaceState(null, '', `#${id}`);
      }
      async function startOver() {
        await L.reset.run({ api });
        for (const p of Object.values(panels)) {
          p.rendered = false;
          p.panel.replaceChildren();
        }
        select(current);
        toast(L.reset.done || 'Back to a clean slate.');
      }
      const logout =
        SITE.auth && SITE.auth.logout !== false
          ? h('button', { class: 'button ghost small', type: 'button', onclick: () => { session.clear(); location.reload(); } }, t('lab.signout'))
          : null;
      root.replaceChildren(
        h('a', { class: 'skip', href: '#lab-main' }, t('skip.lab')),
        h('header', { class: 'header' }, brand(), h('nav', { class: 'nav', 'aria-label': t('nav.main') }, h('a', { href: 'index.html' }, t('nav.overview')), h('a', { href: 'index.html#hard-parts' }, t('nav.hard')), h('a', { href: SITE.repo, rel: 'noopener' }, t('nav.source'))), h('div', { class: 'header-actions' }, languageSelect(), themeButton(), logout)),
        h('main', { id: 'lab-main', tabindex: '-1' }, h('div', { class: 'lab-head arrive' }, eyebrow(L.eyebrow), h('h1', {}, L.title), h('p', {}, L.text), L.reset ? h('div', { class: 'row' }, button(L.reset.label, startOver, { small: true, ic: 'refresh' }), h('span', { class: 'hint-inline' }, L.reset.hint)) : null), h('div', { class: 'lab' }, tabs, body))
      );
      const wanted = location.hash.slice(1);
      select(panels[wanted] ? wanted : L.tabs[0].id);
    }
    if (SITE.auth && !session.key()) {
      SITE.auth.build(authPage, session).then(build);
    } else {
      build();
    }
  }

  /* ------------------------------------------------------------------ boot */
  window.Kit = { h, icon, ICONS, api, toast, pretty, button, badge, out, kv, box, labelled, copyButton, stage, session, store, authPage, AUTHOR, busy, setTheme, t, LANGS };
  const page = document.body.dataset.page;
  const boot = async () => {
    await applyLanguage(pickLanguage()); // English resolves at once; another language waits for its two small files
    showSplash();
    try {
      if (page === 'lab') lab();
      else landing();
    } finally {
      hideSplash();
    }
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
