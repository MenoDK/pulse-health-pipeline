/* The lab: six tabs, each one a way for a data pipeline to go wrong. Loaded before kit.js; it only declares things.
   Everything that came from the API is inserted as text, never as markup. The page can only talk to this server
   (strict CSP). Every button that changes something goes through /api/lab/*, which does not exist unless the lab is on. */
(() => {
  'use strict';

  const SCENARIOS = [
    ['normal', 'Healthy'],
    ['outage', 'Down (503)'],
    ['reject', 'Refuses every payload (400)'],
    ['rate-limit', 'Rate limit (429, wait 120 s)'],
    ['lose-ack', 'Keeps the report, then fails to answer'],
    ['slow', 'Slower than the timeout'],
    ['revoked', 'Revokes the credential'],
  ];
  const NARRATORS = [
    ['template', 'The template (honest)'],
    ['invents', 'Invents a forecast'],
    ['rounds', 'Rounds a percentage'],
    ['leaks', 'Names a person'],
  ];
  const QUERIES = [
    ['advisory lock', 'a word that is in the note'],
    ['synchronisaton', 'a typo'],
    ['retries', 'another form of a word'],
    ['why does a report never go out twice', 'a question in other words'],
  ];
  const MODES = [
    ['lexical', 'Keywords only'],
    ['vector', 'Spelling similarity only'],
    ['hybrid', 'Hybrid (rank fusion)'],
    ['weighted', 'Weighted sum of scores'],
  ];

  const kind = (status) => ({ ok: 'ok', done: 'ok', delivered: 'ok', duplicate: 'ok', degraded: 'warn', retry: 'warn', pending: 'warn', sending: 'warn', failed: 'bad', down: 'bad', dead: 'bad', skipped: 'warn' })[status] || '';
  const httpKind = (status) => (status >= 200 && status < 300 ? 'ok' : status >= 500 ? 'bad' : 'warn');
  const errorText = (r) => {
    const d = r.data;
    if (d && typeof d === 'object' && d.detail) return typeof d.detail === 'string' ? d.detail : JSON.stringify(d.detail);
    if (d && typeof d === 'object' && d.error) return String(d.error);
    return `The server answered ${r.status}.`;
  };
  const clock = (iso) => (iso ? new Date(iso).toLocaleString([], { hour12: false }) : '—');
  const number = (n) => new Intl.NumberFormat().format(n);
  /** replaceChildren that accepts arrays and skips null, which it would otherwise print as the word "null". */
  const fill = (el, ...kids) => el.replaceChildren(...kids.flat().filter((x) => x !== null && x !== undefined && x !== false));
  function push(target, card, keep = 4) {
    target.prepend(card);
    while (target.children.length > keep) target.lastElementChild.remove();
  }

  /** A card for a plain answer from the server: the status, how long it took, and the body as text. */
  function answer(k, title, r) {
    const { h, badge, out } = k;
    return h('div', { class: 'box arrive' }, h('h3', {}, title, ' ', badge(String(r.status), httpKind(r.status)), ' ', h('small', {}, `${r.ms} ms`)), out(r.data));
  }
  /** The same, for a call that is meant to succeed: a refusal becomes an error toast instead of a card. */
  async function act(k, log, title, path, body, after) {
    const r = await k.api(path, { method: 'POST', body: body || {} });
    if (!r.ok) throw new Error(errorText(r));
    push(log, answer(k, title, r));
    if (after) await after(r);
    return r;
  }

  let overview = null;
  const getOverview = () => {
    overview ||= fetch('/api/overview').then((r) => (r.ok ? r.json() : null)).catch(() => null);
    return overview;
  };
  /** A notice at the top of a tab when the server was started without the lab. */
  async function labNotice(k) {
    const o = await getOverview();
    if (o && o.lab) return null;
    return k.box('The lab is off on this server', 'Start it with LAB_MODE=true (make demo does) to use the buttons that change things. Everything that only reads still needs the API key.');
  }

  /** The clock the pipeline uses is the real one plus an offset the lab controls. */
  function clockBox(k, onMoved) {
    const { api, h, button, box, badge } = k;
    const now = h('span', {});
    async function show() {
      const r = await api('/api/lab/state');
      if (r.ok) fill(now, badge(`pipeline time ${clock(r.data.now)}`, ''), ' ', h('small', {}, r.data.offset_seconds ? `moved ${number(r.data.offset_seconds)} s ahead` : 'not moved'));
    }
    const move = (seconds, label) => button(label, async () => {
      const r = await api('/api/lab/clock', { method: 'POST', body: { seconds } });
      if (!r.ok) throw new Error(errorText(r));
      await show();
      if (onMoved) await onMoved();
    }, { small: true, ic: 'clock' });
    const el = box('Time', 'Leases, backoff, tokens and heartbeats all read the pipeline’s clock, so waiting is a button. Moving it only ever goes forward; Start over puts it back.',
      h('div', { 'aria-live': 'polite' }, now),
      h('div', { class: 'row' }, move(60, '+1 minute'), move(600, '+10 minutes'), move(3600, '+1 hour'), move(86400, '+1 day')));
    return { el, show };
  }

  /* ---------------------------------------------------------------- sync */
  async function syncTab(panel, k) {
    const { api, h, button, badge, box, kv } = k;
    const notice = await labNotice(k);
    const source = h('div', { 'aria-live': 'polite' });
    const history = h('div', {});
    const log = h('div', {});

    async function refresh() {
      const [s, runs] = await Promise.all([api('/api/lab/registry'), api('/api/sync/runs?limit=6')]);
      if (s.ok) {
        fill(source, kv({
          People: number(s.data.people),
          Encounters: number(s.data.encounters),
          Teams: number(s.data.teams),
          'Requests answered': number(s.data.requests),
          'Requests that will fail': String(s.data.fail_next),
        }));
      }
      if (!runs.ok) return;
      const positions = Object.entries(runs.data.positions);
      fill(history,
        positions.length ? kv(Object.fromEntries(positions.map(([entity, p]) => [`Position · ${entity}`, clock(p.updated_at)]))) : h('p', { class: 'hint' }, 'No position yet: the first run reads everything.'),
        runs.data.runs.length
          ? h('ul', { class: 'trace' }, runs.data.runs.map((r) => h('li', {},
            h('strong', {}, `#${r.id}`), badge(r.status, kind(r.status)),
            h('span', {}, `${number(r.fetched)} read · ${number(r.applied)} written · ${number(r.stale)} stale · ${number(r.rejected)} rejected`),
            r.error ? h('span', {}, r.error) : null)))
          : null);
    }
    const lever = (title, path, body) => async () => {
      await act(k, log, title, path, body);
      await refresh();
    };
    async function sync(full) {
      const r = await api('/api/sync/run', { method: 'POST', body: { full } });
      if (!r.ok) throw new Error(errorText(r));
      const d = r.data;
      push(log, h('div', { class: 'box arrive' },
        h('h3', {}, full ? 'Full re-read' : 'Sync', ' ', badge(d.status, kind(d.status)), ' ', h('small', {}, `${r.ms} ms`)),
        kv({
          'Records read': number(d.totals.fetched),
          'Written': number(d.totals.applied),
          'Already there or older': number(d.totals.stale),
          'Rejected (did not fit)': number(d.totals.rejected),
          'Reports queued': number(d.queued),
          Error: d.error || '—',
        })));
      await refresh();
    }

    panel.append(h('div', { class: 'cols' },
      h('div', {},
        notice,
        box('1 · The registry', 'A stand-in for the source system, with fictitious people. It lists three teams twice, as real registries do, and one person in a hundred has an identifier that fails its own check digits.', source),
        box('2 · Change it', 'Time moves in the registry too: records are added, corrected and withdrawn.',
          h('div', { class: 'row' },
            button('A week of work', lever('Advance the registry', '/api/lab/registry/advance', { new: 20, changed: 10, removed: 3 }), { small: true, ic: 'clock' }),
            button('A record arrives 2 minutes late', lever('A record, stamped 2 minutes ago, appears now', '/api/lab/registry/late-arrival', { behind_seconds: 120 }), { small: true, ic: 'alert' }),
            button('A record arrives 1 hour late', lever('A record, stamped 1 hour ago, appears now', '/api/lab/registry/late-arrival', { behind_seconds: 3600 }), { small: true, ic: 'alert' })),
          h('div', { class: 'row' }, button('Fail the next 3 requests', lever('The registry fails 3 requests', '/api/lab/registry/flaky', { next_requests: 3 }), { small: true, ic: 'plug' }))),
        box('3 · Synchronise', 'Sync reads from a little before the stored position, so a late record inside the overlap window is still seen. A full re-read ignores the position.',
          h('div', { class: 'row' },
            button('Sync', () => sync(false), { variant: 'primary', ic: 'refresh' }),
            button('Full re-read', () => sync(true), { ic: 'database' }))),
        box('What the pipeline has stored', null, history)),
      h('div', {}, log)));
    await refresh();
  }

  /* ---------------------------------------------------------------- queue */
  async function queueTab(panel, k) {
    const { api, h, button, badge, box, kv } = k;
    const notice = await labNotice(k);
    const counts = h('div', { 'aria-live': 'polite' });
    const waiting = h('div', {});
    const attempts = h('div', {});
    const gatewayState = h('div', {});
    const autopilotLine = h('span', {});
    const log = h('div', {});
    const time = clockBox(k, () => refresh());

    async function refresh() {
      const [q, g, s] = await Promise.all([api('/api/queue'), api('/api/lab/gateway'), api('/api/lab/state')]);
      if (q.ok) {
        const c = q.data.counts;
        fill(counts, kv({
          Pending: number(c.pending),
          'Being sent': number(c.sending),
          Done: number(c.done),
          Dead: c.dead ? badge(number(c.dead), 'bad') : '0',
          'Due now': number(q.data.due_now),
        }));
        fill(waiting, q.data.waiting.length
          ? h('ul', { class: 'trace' }, q.data.waiting.map((m) => h('li', {},
            h('strong', {}, `#${m.id}`), badge(m.status, kind(m.status)),
            h('span', {}, `attempt ${m.attempts} of ${q.data.limits.max_attempts}`),
            m.status === 'sending' ? h('span', {}, `lease until ${clock(m.lease_until)}`) : h('span', {}, `not before ${clock(m.not_before)}`),
            m.last_error ? h('span', {}, m.last_error) : null)))
          : h('p', { class: 'hint' }, 'Nothing is waiting.'));
        fill(attempts, q.data.recent_attempts.length
          ? h('ul', { class: 'trace' }, q.data.recent_attempts.map((a) => h('li', {},
            h('strong', {}, `#${a.message}`), badge(a.outcome, kind(a.outcome)), h('span', {}, a.http_status ? `HTTP ${a.http_status}` : 'no answer'), h('span', {}, a.detail))))
          : h('p', { class: 'hint' }, 'No attempt yet.'));
      }
      if (g.ok) {
        fill(gatewayState, kv({
          Scenario: g.data.scenario,
          'Reports it holds': number(g.data.received_unique),
          'Requests': number(g.data.requests),
          'Duplicates it refused': number(g.data.duplicates),
          'Tokens it issued': number(g.data.token_requests),
        }));
      }
      if (s.ok) fill(autopilotLine, badge(s.data.autopilot ? 'on: a worker drains every 30 s' : 'off: nothing moves until you press Drain', s.data.autopilot ? 'ok' : ''));
      await time.show();
    }
    const lever = (title, path, body) => async () => {
      await act(k, log, title, path, body);
      await refresh();
    };
    const TOTALS = ['claimed', 'taken_over', 'delivered', 'duplicate', 'retried', 'dead', 'released', 'lost_lease', 'reaped'];
    /** One batch is what the API (and a scheduled worker) does. "Everything due" repeats it until nothing is due or a
        worker gives up early, so a recipe can move a few hundred messages with one press. */
    async function drain(everything) {
      const total = Object.fromEntries(TOTALS.map((name) => [name, 0]));
      const notes = [];
      let stopped = null;
      let batches = 0;
      let took = 0;
      do {
        const r = await api('/api/queue/drain', { method: 'POST', body: {} });
        if (!r.ok) throw new Error(errorText(r));
        batches += 1;
        took += r.ms;
        for (const name of TOTALS) total[name] += r.data[name];
        notes.push(...r.data.notes);
        stopped = r.data.stopped;
        if (r.data.claimed === 0 || stopped) break;
      } while (everything && batches < 60);
      push(log, h('div', { class: 'box arrive' },
        h('h3', {}, everything ? 'Drain everything due' : 'Drain', ' ', badge(stopped ? 'stopped early' : 'finished', stopped ? 'warn' : 'ok'), ' ', h('small', {}, `${batches} batch${batches === 1 ? '' : 'es'} · ${took} ms`)),
        kv({
          'Messages claimed': number(total.claimed),
          'Taken over from a dead worker': number(total.taken_over),
          Delivered: number(total.delivered),
          'Already held by the gateway': number(total.duplicate),
          'Retry later': number(total.retried),
          Dead: number(total.dead),
          'Given back untouched': number(total.released),
          'Taken over, result dropped': number(total.lost_lease),
          'Gave up early because': stopped || '—',
          'Dead messages reaped': number(total.reaped),
        }),
        notes.length ? k.out(notes.join('\n')) : null));
      await refresh();
    }
    async function autopilot(on) {
      await act(k, log, on ? 'Switch the autopilot on' : 'Switch the autopilot off', '/api/lab/autopilot', { on });
      await refresh();
    }
    async function connect(withCertificate) {
      const r = await api('/api/lab/connector/check', { method: 'POST', body: { with_certificate: withCertificate } });
      if (!r.ok) throw new Error(errorText(r));
      const d = r.data;
      push(log, h('div', { class: 'box arrive' },
        h('h3', {}, withCertificate ? 'Connect with the client certificate' : 'Connect without a certificate', ' ', badge(d.ok ? 'connected' : 'refused', d.ok ? 'ok' : 'bad')),
        kv({ 'Used TLS': d.tls ? 'yes' : 'no', Result: d.detail })));
    }

    panel.append(h('div', { class: 'cols' },
      h('div', {},
        notice,
        box('1 · The gateway', 'A stand-in for the national gateway: OAuth client credentials, mutual TLS, an idempotent report endpoint, and ways to fail.',
          gatewayState,
          h('div', { class: 'row' }, SCENARIOS.map(([name, label]) => button(label, lever(`Gateway: ${label}`, '/api/lab/gateway/scenario', { name }), { small: true, variant: name === 'normal' ? 'primary' : 'secondary' }))),
          h('div', { class: 'row' }, button('Expire every token', lever('Expire every token', '/api/lab/gateway/expire-tokens', {}), { small: true, ic: 'key' }))),
        box('2 · The queue', 'Every encounter the sync wrote has a message here, written in the same transaction. A worker claims messages with a lease and a counted attempt.',
          counts, waiting,
          h('div', { class: 'row' },
            button('Drain now', () => drain(false), { variant: 'primary', ic: 'play' }),
            button('Drain everything due', () => drain(true), { ic: 'refresh' }),
            button('Crash a worker', lever('A worker claims 5 messages and dies', '/api/lab/queue/crash', { count: 5 }), { small: true, ic: 'alert' })),
          h('div', { class: 'row' },
            button('Autopilot on', () => autopilot(true), { small: true, ic: 'refresh' }),
            button('Autopilot off', () => autopilot(false), { small: true }),
            autopilotLine)),
        time.el,
        box('3 · Mutual TLS', 'The gateway wants a client certificate during the handshake. Without one it does not answer at all.',
          h('div', { class: 'row' },
            button('Connect with the certificate', () => connect(true), { small: true, ic: 'lock' }),
            button('Connect without it', () => connect(false), { small: true, ic: 'unlock' })))),
      h('div', {}, box('Recent attempts', 'Every attempt is a row, whoever made it.', attempts), log)));
    await refresh();
  }

  /* ---------------------------------------------------------------- indicators */
  async function indicatorsTab(panel, k) {
    const { api, h, button, badge, box, kv, labelled } = k;
    const notice = await labNotice(k);
    const report = h('div', { 'aria-live': 'polite' });
    const narration = h('div', {});
    const asOf = h('input', { type: 'text', id: 'as-of', inputmode: 'numeric', placeholder: 'YYYY-MM-DD', maxlength: '10', autocomplete: 'off' });
    let narrator = 'template';
    const narratorLine = h('span', {});

    function paintNarrator() {
      fill(narratorLine, badge(NARRATORS.find(([m]) => m === narrator)[1], narrator === 'template' ? 'ok' : 'warn'));
    }
    async function compute() {
      const date = asOf.value.trim();
      if (date && !/^\d{4}-\d{2}-\d{2}$/.test(date)) throw new Error('Write the date as YYYY-MM-DD.');
      const r = await api(`/api/indicators?narrate=true${date ? `&as_of=${date}` : ''}`);
      if (!r.ok) throw new Error(errorText(r));
      const d = r.data;
      fill(report,
        h('div', { class: 'box arrive' },
          h('h3', {}, `As of ${d.as_of}`, ' ', badge(d.score === null ? 'no score' : `${d.score} out of 10 · ${d.grade}`, d.grade === 'poor' ? 'bad' : d.grade === 'fair' ? 'warn' : 'ok')),
          h('p', { class: 'hint' }, d.indicators_with_data === 0
            ? 'Nobody to measure yet: run a sync first (the Sync tab).'
            : `${d.indicators_with_data} of ${d.indicators_total} indicators had somebody to measure.`),
          h('table', { class: 'matrix' },
            h('thead', {}, h('tr', {}, ['Indicator', 'Counted', 'Result', 'Target', 'Status'].map((t) => h('th', { scope: 'col' }, t)))),
            h('tbody', {}, d.indicators.map((i) => h('tr', {},
              h('th', { scope: 'row' }, i.name),
              h('td', {}, i.percent === null ? '—' : `${number(i.numerator)} of ${number(i.denominator)}`),
              h('td', {}, i.percent === null ? '—' : `${i.percent}%`),
              h('td', {}, `${i.target_percent}%`),
              h('td', {}, badge(i.status.replace('-', ' '), i.status === 'on-target' ? 'ok' : i.status === 'critical' ? 'bad' : 'warn'))))))));
      const n = d.narration;
      fill(narration, h('div', { class: 'box arrive' },
        h('h3', {}, 'The words', ' ', badge(n.accepted ? 'passed the check' : 'refused, replaced by the template', n.accepted ? 'ok' : 'bad')),
        kv({ 'Text came from': n.source, Narrator: NARRATORS.find(([m]) => m === narrator)[1] }),
        k.out(n.text),
        n.violations.length ? h('div', {}, h('p', { class: 'hint' }, 'What the check found:'), h('ul', { class: 'trace' }, n.violations.map((v) => h('li', {}, v)))) : null));
    }
    async function choose(mode) {
      const r = await api('/api/lab/narrator', { method: 'POST', body: { mode } });
      if (!r.ok) throw new Error(errorText(r));
      narrator = mode;
      paintNarrator();
      await compute();
    }
    const today = await api('/api/lab/state');
    if (today.ok) asOf.value = today.data.now.slice(0, 10);
    paintNarrator();

    panel.append(h('div', { class: 'cols' },
      h('div', {},
        notice,
        box('1 · The numbers', 'Five counts from one REPEATABLE READ snapshot, scored in exact arithmetic: no float between the counts and the score.',
          labelled('Report date', asOf),
          h('div', { class: 'row' }, button('Compute', compute, { variant: 'primary', ic: 'chart' }))),
        box('2 · The words', 'A narrator (a template, or a language model behind the same interface) turns the numbers into prose. Every number in that prose is checked against the report. These narrators are written to fail in ways a skimming reader would not notice.',
          h('div', { class: 'row' }, NARRATORS.map(([mode, label]) => button(label, () => choose(mode), { small: true, variant: mode === 'template' ? 'primary' : 'secondary', ic: mode === 'template' ? 'check' : 'alert' }))),
          h('div', { class: 'row' }, narratorLine))),
      h('div', {}, report, narration)));
    await compute();
  }

  /* ---------------------------------------------------------------- search */
  async function searchTab(panel, k) {
    const { api, h, button, badge, box, labelled, kv } = k;
    const notice = await labNotice(k);
    const results = h('div', { 'aria-live': 'polite' });
    const evaluation = h('div', {});
    const input = h('input', { type: 'text', id: 'search-query', placeholder: 'Ask the notes something', maxlength: '200', autocomplete: 'off' });

    async function ask(query) {
      if (!query.trim()) throw new Error('Type a question first.');
      input.value = query;
      const answers = await Promise.all(MODES.map(([mode]) => api(`/api/search?q=${encodeURIComponent(query)}&mode=${mode}&k=3`)));
      fill(results, MODES.map(([mode, label], i) => {
        const r = answers[i];
        if (!r.ok) return answer(k, label, r);
        return h('div', { class: 'box arrive' },
          h('h3', {}, label, ' ', badge(mode, '')),
          r.data.hits.length
            ? h('ol', { class: 'trace' }, r.data.hits.map((hit) => h('li', {},
              h('strong', {}, hit.title), h('small', {}, `${hit.category} · score ${hit.score}`),
              Object.keys(hit.ranks).length ? h('small', {}, `from ${Object.entries(hit.ranks).map(([list, n]) => `${list} #${n}`).join(' + ')}`) : null)))
            : h('p', { class: 'hint' }, 'Nothing found.'));
      }));
    }
    async function evaluate() {
      const r = await api('/api/search/eval');
      if (!r.ok) throw new Error(errorText(r));
      const kinds = ['exact', 'typo', 'form', 'natural', 'gap'];
      const cell = (score) => `${score.recall_at_3.toFixed(2)} · ${score.mrr.toFixed(2)}`;
      fill(evaluation, h('div', { class: 'box arrive' },
        h('h3', {}, '36 labelled queries', ' ', badge('recall@3 · MRR', '')),
        h('table', { class: 'matrix' },
          h('thead', {}, h('tr', {}, ['Method', 'All', ...kinds].map((t) => h('th', { scope: 'col' }, t)))),
          h('tbody', {}, MODES.map(([mode, label]) => h('tr', {},
            h('th', { scope: 'row' }, label),
            h('td', {}, cell(r.data[mode].all)),
            kinds.map((kd) => h('td', {}, cell(r.data[mode][kd]))))))),
        h('p', { class: 'hint' }, 'The hybrid beats either list alone; against the weighted sum it ties on recall and is a hundredth behind on MRR. The reason to prefer rank fusion is that it needs no weights and no conversion between scales, not that it scores higher here. “gap” queries share no letters with their answer: a spelling embedder cannot bridge them.')));
    }
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); window.Kit.busy(input, () => ask(input.value)); }
    });

    panel.append(h('div', { class: 'cols' },
      h('div', {},
        notice,
        box('1 · Ask', 'Thirty-odd short notes about how this pipeline works are indexed in PostgreSQL: pgvector for the vectors, a generated tsvector for the words. The same question goes to four methods.',
          labelled('Question', input),
          h('div', { class: 'row' }, button('Ask', () => ask(input.value), { variant: 'primary', ic: 'search' })),
          h('div', { class: 'row' }, QUERIES.map(([q, why]) => button(why, () => ask(q), { small: true })))),
        box('2 · Measure', 'Four methods on the same labelled queries. The numbers are computed here, now, from the database in front of you.',
          h('div', { class: 'row' }, button('Run the evaluation', evaluate, { ic: 'gauge' })),
          evaluation),
        box('How to read it', null, kv({ 'recall@3': 'the share of questions with a right note in the first three', MRR: 'one over the position of the first right note, averaged' }))),
      h('div', {}, results)));
  }

  /* ---------------------------------------------------------------- privacy */
  async function privacyTab(panel, k) {
    const { api, h, button, badge, box, kv } = k;
    const notice = await labNotice(k);
    const view = h('div', { 'aria-live': 'polite' });

    async function scan() {
      const r = await api('/api/lab/privacy');
      if (!r.ok) throw new Error(errorText(r));
      const d = r.data;
      fill(view,
        h('div', { class: 'box arrive' },
          h('h3', {}, 'What the registry sends for three people'),
          h('p', { class: 'hint' }, 'Fictitious. Generated from syllables and random digits with valid check digits.'),
          h('ul', { class: 'trace' }, d.registry_sample.map((p) => h('li', {}, h('strong', {}, p.name), h('span', {}, `identifier ${p.national_id}`), h('span', {}, `registry id ${p.id}`))))),
        h('div', { class: 'box arrive' },
          h('h3', {}, 'What is stored for the same three people'),
          d.stored_for_them.length
            ? h('ul', { class: 'trace' }, d.stored_for_them.map((s) => h('li', {}, h('strong', {}, s.subject_key), h('span', {}, `born in ${s.birth_month.slice(0, 7)}`), h('span', {}, `team ${s.team || '—'}`), h('span', {}, s.chronic ? 'chronic condition' : 'no chronic condition'))))
            : h('p', { class: 'hint' }, 'Nothing stored yet: run a sync first.'),
          h('p', { class: 'hint' }, 'A keyed hash, the month of birth and the team. No name, no identifier, no registry id.')),
        h('div', { class: 'box arrive' },
          h('h3', {}, 'The search', ' ', badge(d.scan.clean ? 'found nothing' : 'FOUND A VALUE', d.scan.clean ? 'ok' : 'bad')),
          kv({
            'Values looked for': number(d.searched_for),
            'Columns examined': number(d.scan.columns_examined),
            'Rows that contain one': d.scan.matches.length ? d.scan.matches.map(([t, c, n]) => `${t}.${c}: ${n}`).join('; ') : 'none',
          }),
          h('p', { class: 'hint' }, 'Every text, JSON and character column of every table, for every name, identifier and registry id of the first forty people. A scan that examined nothing would prove nothing, so it says how many columns it read. A test plants a value to prove the scan can see one.')));
    }

    panel.append(h('div', { class: 'cols' },
      h('div', {},
        notice,
        box('Prove it is nowhere', 'The pipeline checks the national identifier and keeps neither it nor the name. Rather than trust that, look for them everywhere.',
          h('div', { class: 'row' }, button('Search the whole database', scan, { variant: 'primary', ic: 'search' })))),
      h('div', {}, view)));
  }

  /* ---------------------------------------------------------------- health */
  async function healthTab(panel, k) {
    const { api, h, button, badge, box, kv } = k;
    const notice = await labNotice(k);
    const view = h('div', { 'aria-live': 'polite' });
    const time = clockBox(k, () => refresh());

    async function refresh() {
      const r = await api('/api/health');
      if (!r.ok) throw new Error(errorText(r));
      const d = r.data;
      const uptime = new Map(d.uptime.map((u) => [u.component, u]));
      fill(view, h('div', { class: 'box arrive' },
        h('h3', {}, 'The whole', ' ', badge(d.status, kind(d.status))),
        h('ul', { class: 'trace' }, d.checks.map((c) => {
          const u = uptime.get(c.component);
          return h('li', {},
            h('strong', {}, c.component), badge(c.status, kind(c.status)), h('span', {}, c.detail),
            u && u.uptime_percent !== null ? h('small', {}, `${u.uptime_percent}% of ${number(u.samples)} samples in 24 h`) : null);
        })),
        h('p', { class: 'hint' }, 'A critical component down (the database or the broker) takes the whole down. Anything else not ok only degrades it.')));
      await time.show();
    }

    panel.append(h('div', { class: 'cols' },
      h('div', {},
        notice,
        box('1 · Look', 'Six components, each judged by what matters for it: the age of the oldest due message for the queue (not its length), a heartbeat for the worker, the last success for the sync.',
          h('div', { class: 'row' }, button('Check now', refresh, { variant: 'primary', ic: 'heart' }))),
        time.el,
        box('2 · What to try', 'Move the clock two hours with the worker running: its heartbeat is two hours old until the next beat, and the whole turns degraded, not down. Crash a worker in the Queue tab and then move the clock: the queue ages.', kv({ 'Worker heartbeat': 'every 60 s, down after 3 missed', Queue: 'degraded after 15 min, down after 1 h', Sync: 'degraded after 6 h without a success' }))),
      h('div', {}, view)));
    await refresh();
  }

  window.LAB = {
    eyebrow: 'The lab',
    title: 'Make the pipeline fail.',
    text: 'Six ways for a data pipeline to go wrong, each backed by tests. Everything runs on this machine against fictitious data, with stand-ins for the two outside systems.',
    reset: {
      label: 'Start over',
      hint: 'Empties the database, resets both stand-ins, rebuilds the search index and puts the clock back.',
      done: 'Back to a clean slate.',
      run: async ({ api }) => {
        const r = await api('/api/lab/reset', { method: 'POST', body: {} });
        if (!r.ok) throw new Error(errorText(r));
      },
    },
    tabs: [
      { id: 'sync', label: 'Sync', icon: 'refresh', render: (p, k) => syncTab(p, k) },
      { id: 'queue', label: 'Queue', icon: 'route', render: (p, k) => queueTab(p, k) },
      { id: 'indicators', label: 'Indicators', icon: 'chart', render: (p, k) => indicatorsTab(p, k) },
      { id: 'search', label: 'Search', icon: 'search', render: (p, k) => searchTab(p, k) },
      { id: 'privacy', label: 'Privacy', icon: 'fingerprint', render: (p, k) => privacyTab(p, k) },
      { id: 'health', label: 'Health', icon: 'heart', render: (p, k) => healthTab(p, k) },
    ],
  };
})();
