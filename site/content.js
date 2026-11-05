/* Content for the landing page and the lab. Everything the page says about behaviour is backed by a test; the output in
   the tour is recorded from the real code (scripts/record_transcripts.py) and CI fails if it drifts. */
window.SITE = {
  name: 'pulse',
  short: 'pulse',
  title: 'pulse · a data pipeline you can kill and trust',
  logo: 'heart',
  repo: 'https://github.com/MenoDK/pulse-health-pipeline',
  accent: {
    light: { fill: '#22b8cf', ink: '#0b6677', on: '#06222a', soft: '#d8f3f8', onNavy: '#5fd8e8' },
    dark: { fill: '#3cc6db', ink: '#8be6f3', on: '#06222a', soft: '#12343c', onNavy: '#5fd8e8' },
  },
  loading: {
    context: 'Pipeline',
    title: 'Taking a pulse',
    text: 'Checking the database, the queue and the last heartbeat before showing you anything.',
    icon: 'heart',
    satellites: ['database', 'route', 'clock'],
    foot: 'Local demo · fictitious data, stand-ins for both outside systems, nothing leaves this machine',
    sketch: 'M10 96H66l12-36 18 72 14-52 8 16H196l12-30 16 60 12-30H334',
  },
  lab: { href: 'lab.html', cta: 'Enter the lab' },

  hero: {
    eyebrow: 'Data pipeline · a sync that resumes, a queue that survives, numbers a model cannot change',
    lead: 'A pipeline you can',
    soft: 'kill and trust.',
    text: 'A regional health registry feeds an analytics layer and reports to a national gateway. Pulse is the plumbing between them, built for the day something fails: it resumes where it stopped, it never sends a report twice, a worker that dies hands its work to the next, the indicators are computed in code with exact arithmetic, and a language model may word the summary but cannot change a number in it. Everything runs on generated data, with stand-ins for both outside systems.',
    primary: { label: 'Open the lab', href: 'lab.html' },
    secondary: { label: 'See how it works', href: '#tour', icon: 'layers' },
    pilot: 'Runs on your laptop · Docker and one command, nothing to sign up for',
    proof: [
      { icon: 'check', a: 'Every guarantee is proven by sabotage', b: 'a break must turn a test red' },
      { icon: 'flask', a: 'Every failure is a button', b: 'in a lab you can click' },
    ],
    top: ['PULSE', 'Resumes. Never repeats. Shows its work.'],
    status: { icon: 'heart', small: 'What the tests pin', strong: 'A sync killed between two pages resumes from the last committed position, loses nothing and repeats nothing.' },
    art: `<svg viewBox="0 50 500 620" role="img" aria-label="An illustration with invented numbers. A registry feeds a sync step, then a queue, then a gateway reached over mutual TLS. Below, a heartbeat trace marks the position the sync would resume from. Under it, the queue as four counters: pending, sending, done and one dead message. Last, three indicator bars against their targets, and a line of narrator text refused because it says 63 percent where the report says 63.4.">
      <g class="a-line"><path d="M0 150H500M0 270H500M0 390H500M0 510H500M0 630H500M100 50V670M250 50V670M400 50V670"/></g>
      <circle cx="440" cy="161" r="58" class="a-soft"/>

      <g>
        <rect x="14" y="135" width="96" height="52" rx="12" class="a-body"/>
        <text x="62" y="157" text-anchor="middle" class="a-text">REGISTRY</text>
        <text x="62" y="173" text-anchor="middle" class="a-text-s">stand-in</text>
        <rect x="140" y="135" width="84" height="52" rx="12" class="a-body"/>
        <text x="182" y="157" text-anchor="middle" class="a-text">SYNC</text>
        <text x="182" y="173" text-anchor="middle" class="a-text-s">resumable</text>
        <rect x="254" y="135" width="84" height="52" rx="12" class="a-body"/>
        <text x="296" y="157" text-anchor="middle" class="a-text">QUEUE</text>
        <text x="296" y="173" text-anchor="middle" class="a-text-s">leases</text>
        <rect x="368" y="135" width="118" height="52" rx="12" class="a-body"/>
        <text x="427" y="157" text-anchor="middle" class="a-text">GATEWAY</text>
        <text x="427" y="173" text-anchor="middle" class="a-text-s">mTLS · 201 / 409</text>
      </g>
      <path d="M112 161H136M226 161H250M340 161H364" class="a-dash"/>
      <path d="M130 154l7 7-7 7M244 154l7 7-7 7M358 154l7 7-7 7" class="a-accent-s"/>

      <g>
        <rect x="14" y="203" width="472" height="80" rx="16" class="a-body"/>
        <text x="30" y="223" class="a-text-s">sync position · resumes from the last committed page</text>
        <path d="M30 257H120l10-15 14 31 12-24 8 8H250l10-21 14 38 10-17H330l8-8 10 14 8-6H470" class="a-accent-s"/>
        <circle cx="470" cy="257" r="4" class="a-accent pulse"/>
      </g>

      <g>
        <rect x="14" y="299" width="472" height="92" rx="16" class="a-body"/>
        <text x="30" y="319" class="a-text-s">outbox · a claim reads a batch, however large the backlog</text>
        <rect x="30" y="331" width="100" height="44" rx="10" class="a-line"/>
        <text x="42" y="349" class="a-text-s">pending</text>
        <text x="42" y="367" class="a-text">12</text>
        <rect x="146" y="331" width="100" height="44" rx="10" class="a-line"/>
        <text x="158" y="349" class="a-text-s">sending</text>
        <text x="158" y="367" class="a-text">3</text>
        <rect x="262" y="331" width="100" height="44" rx="10" class="a-line"/>
        <text x="274" y="349" class="a-text-s">done</text>
        <text x="274" y="367" class="a-text">480</text>
        <rect x="378" y="331" width="92" height="44" rx="10" class="a-bad-f" fill-opacity="0.3"/>
        <rect x="378" y="331" width="92" height="44" rx="10" class="a-line"/>
        <text x="390" y="349" class="a-text-s">dead</text>
        <text x="390" y="367" class="a-text">1</text>
      </g>

      <g>
        <rect x="14" y="407" width="472" height="98" rx="16" class="a-body"/>
        <text x="30" y="426" class="a-text-s">indicators · exact fractions, targets are ticks</text>
        <text x="30" y="445" class="a-text-s">chronic follow-up</text>
        <rect x="190" y="436" width="280" height="10" rx="5" class="a-line"/>
        <rect x="190" y="436" width="200" height="10" rx="5" class="a-accent"/>
        <path d="M386 432V450" class="a-line"/>
        <text x="30" y="459" class="a-text-s">child check-ups</text>
        <rect x="190" y="450" width="280" height="10" rx="5" class="a-line"/>
        <rect x="190" y="450" width="160" height="10" rx="5" class="a-accent"/>
        <path d="M400 446V464" class="a-line"/>
        <text x="30" y="473" class="a-text-s">adults screened</text>
        <rect x="190" y="464" width="280" height="10" rx="5" class="a-line"/>
        <rect x="190" y="464" width="230" height="10" rx="5" class="a-accent"/>
        <path d="M358 460V478" class="a-line"/>
        <rect x="26" y="480" width="448" height="20" rx="8" class="a-bad-f" fill-opacity="0.3"/>
        <path d="M38 485l8 8M46 485l-8 8" class="a-bad"/>
        <text x="58" y="494" class="a-text-s">narrator says 63% · the report says 63.4% → refused</text>
      </g>
    </svg>`,
  },

  principles: {
    lead: ['Plumbing is where', 'trust is lost.'],
    items: [
      ['refresh', 'A sync that resumes'],
      ['route', 'A queue that survives'],
      ['gauge', 'Numbers computed in code'],
      ['fingerprint', 'Identifiers stored nowhere'],
    ],
  },

  tour: {
    eyebrow: 'A tour of the whole thing',
    title: ['Five ways a pipeline', 'quietly goes wrong.'],
    text: 'Pick a tab. The output below is recorded from the real code on a scratch database; CI records it again and fails if it ever stops being true.',
    tag: 'Recorded output',
    tabs: [
      {
        id: 'sync',
        label: 'Sync',
        icon: 'refresh',
        title: 'Start where you stopped. Lose nothing. Repeat nothing.',
        text: 'Records are read in pages ordered by time and id. A page and the new position are committed in one transaction, so a crash between pages loses nothing and repeats nothing. Between runs only a timestamp is kept, and the next run starts a few minutes before it, because a record can be committed in the source after one with a later timestamp. A version guard makes that re-read free: an older copy can never overwrite a newer one.',
        lab: 'lab.html#sync',
        transcript: (window.TRANSCRIPTS || {}).sync || '',
      },
      {
        id: 'queue',
        label: 'Queue',
        icon: 'route',
        title: 'A report goes out once, even when the worker dies.',
        text: 'Every encounter and the message that reports it are written in the same transaction. A worker claims messages with SKIP LOCKED and a lease, and every result it records names the worker: one whose lease was taken over cannot overwrite the one that took over. After three failures in a row it stops and hands the rest of the batch back without spending their attempts. The gateway sees an idempotency key, so a repeat is answered, not stored twice.',
        lab: 'lab.html#queue',
        transcript: (window.TRANSCRIPTS || {}).queue || '',
      },
      {
        id: 'indicators',
        label: 'Indicators',
        icon: 'chart',
        title: 'A model may word it. It may not change a number.',
        text: 'Five indicators are counted in SQL from one REPEATABLE READ snapshot and scored with exact fractions: no float between the counts and the score. A narrator turns them into prose, and every number in that prose must be one the report contains, in the same role: a percentage must be one of the report’s percentages. Text that fails is replaced by the template’s own, and the response says why.',
        lab: 'lab.html#indicators',
        transcript: (window.TRANSCRIPTS || {}).indicators || '',
      },
      {
        id: 'search',
        label: 'Search',
        icon: 'search',
        title: 'Four ways to find a note, and what each one measures.',
        text: 'Notes are indexed in PostgreSQL with pgvector and a generated tsvector. Keyword and vector results are combined by reciprocal rank fusion, which needs no weights. Thirty-six labelled queries measure all four methods. The hybrid beats either list alone and only ties the weighted sum it could have been replaced by; the reason to choose it is that it has nothing to tune.',
        lab: 'lab.html#search',
        transcript: (window.TRANSCRIPTS || {}).search || '',
      },
      {
        id: 'privacy',
        label: 'Privacy',
        icon: 'fingerprint',
        title: 'To prove an identifier is nowhere, look everywhere.',
        text: 'The registry sends a name and a national identifier. The pipeline checks the identifier’s check digits and then stores neither: a person is a keyed hash, a month of birth and a team. A scan walks every text, JSON and character column of every table for the real values, and says how many columns it examined, because a scan that looked at nothing proves nothing.',
        lab: 'lab.html#privacy',
        transcript: (window.TRANSCRIPTS || {}).privacy || '',
      },
    ],
    modulesTitle: 'Everything in the box.',
    modulesNote: 'Each part has its own tests and a place in the lab',
    modules: [
      ['refresh', 'pulse sync', 'Incremental synchronisation with keyset paging, an overlap window, a version guard and an advisory lock so two runs cannot race. Records that do not fit are counted and dropped, never half-applied, and a failed run reports its kind of failure and quotes nothing.'],
      ['route', 'pulse drain · requeue', 'A transactional outbox with leases, fencing and deterministic jitter. Messages that run out of attempts end in dead, which is a state a person looks at: requeue gives them a fresh set.'],
      ['chart', 'pulse indicators', 'Five counts in SQL, exact scoring with a band per indicator, a narrator interface, and the check that stands between a model and a number.'],
      ['search', 'pulse search · eval', 'Keyword, vector, rank-fused and weighted search over the same notes, and the evaluation that compares them on labelled queries.'],
      ['heart', '/health', 'Per component, with a rule for how the parts add up: the age of the oldest due message for the queue, a heartbeat for the worker, the last success for the sync.'],
      ['flask', 'lab + stand-ins', 'Two small servers play the registry and the national gateway, and a lab moves the clock and breaks them. Refused unless asked for, and refused in production.'],
    ],
    transparency: {
      strong: 'Honest about the demo.',
      text: 'Both outside systems are stand-ins that live in this repository, and every person is generated. The lab has no login, so it answers only to localhost, and the service refuses to start with it on outside a development environment. The embedder in the search matches spelling, not meaning. Nothing here has been connected to a real registry or a real gateway.',
    },
  },

  challenges: {
    eyebrow: 'The hard parts',
    title: ['Go on,', 'make it lose a record.'],
    text: 'These are eight things that are easy to claim and hard to get right. Each has a recipe, what you should see, and a button that opens the lab on that exact tab.',
    items: [
      {
        label: 'Lose a record',
        icon: 'clock',
        access: 'Lab · Sync',
        title: 'Make a record arrive after its time.',
        text: 'A source can commit a record after one that carries a later timestamp.',
        steps: [
          'In <code>Sync</code>, press “A week of work”, then “Sync”.',
          'Press “A record arrives 2 minutes late”, then “Sync”.',
          'Press “A record arrives 1 hour late”, then “Sync”, then “Full re-read”.',
        ],
        expect: 'The two-minute record is inside the overlap window and is written. The one-hour record is not: the second sync writes nothing, and the full re-read finds it. That is the limit of an overlap window, stated rather than hidden: a longer delay needs a full re-read.',
        lab: 'lab.html#sync',
      },
      {
        label: 'Kill a worker',
        icon: 'alert',
        access: 'Lab · Queue',
        title: 'Let a worker die holding five messages.',
        text: 'Its messages must not be lost, and must not be stuck.',
        steps: [
          'In <code>Sync</code>, press “Sync”. Open <code>Queue</code>.',
          'Press “Crash a worker”: five messages are claimed and abandoned.',
          'Read the five messages under “The queue”: they are <code>sending</code>, held by a worker that no longer exists.',
          'Press “+10 minutes”, then “Drain now”.',
        ],
        expect: 'The messages stay in <code>sending</code> until their lease runs out. After that they are claimed first, before anything that is merely pending, and the drain card says <code>Taken over from a dead worker: 5</code>. Their attempt was counted when they were first claimed, so a message that kills its worker every time still ends dead instead of looping for ever.',
        lab: 'lab.html#queue',
      },
      {
        label: 'Slow the gateway',
        icon: 'plug',
        access: 'Lab · Queue',
        title: 'Make every call outlast its timeout.',
        text: 'Fifty timeouts in a row should not cost fifty attempts.',
        steps: [
          'In <code>Queue</code>, press “Slower than the timeout”.',
          'Press “Drain now” and wait a few seconds.',
          'Read “Gave up early because” and “Given back untouched”.',
        ],
        expect: 'After three transport failures in a row the worker stops and gives the rest of the batch back, with the attempt the claim spent refunded. Without that rule a batch of fifty against an unreachable gateway is fifty timeouts, longer than the lease, and fifty attempts spent in one cycle.',
        lab: 'lab.html#queue',
      },
      {
        label: 'Lose an acknowledgement',
        icon: 'route',
        access: 'Lab · Queue',
        title: 'Make the gateway keep a report and then fail to say so.',
        text: 'The sender cannot tell a lost request from a lost answer.',
        steps: [
          'In <code>Sync</code>, press “Sync”. In <code>Queue</code>, press “Keeps the report, then fails to answer”, then “Drain everything due”.',
          'Press “Healthy”, then “+1 hour”, then “Drain everything due” again.',
          'Compare “Reports it holds” with “Duplicates it refused”.',
        ],
        expect: 'The first drain gets an error for every report, although the gateway stored each one. The second sends them again with the same idempotency key, the gateway answers “duplicate”, and the pipeline counts that as delivered: “Already held by the gateway” equals the number of reports, and the gateway holds each of them exactly once.',
        lab: 'lab.html#queue',
      },
      {
        label: 'Let a model change a number',
        icon: 'chart',
        access: 'Lab · Indicators',
        title: 'Swap in a narrator that is wrong in a way you would not notice.',
        text: 'Fluent text with one number that is not in the data.',
        steps: [
          'In <code>Sync</code>, press “Sync”. Open <code>Indicators</code>.',
          'Press “Rounds a percentage”, then “Invents a forecast”, then “Names a person”.',
          'Read “What the check found” each time.',
        ],
        expect: 'Each is refused and replaced by the template’s text, and the response names the defect: a percentage that is not in the report, a forecast that appears nowhere in the data, a token shaped like a stored pseudonym.',
        lab: 'lab.html#indicators',
      },
      {
        label: 'Search for the idea',
        icon: 'search',
        access: 'Lab · Search',
        title: 'Ask in words the note does not use.',
        text: 'A spelling embedder is not a sentence model, and the numbers say so.',
        steps: [
          'In <code>Search</code>, press “a typo”, then “a question in other words”.',
          'Press “Run the evaluation”.',
          'Look at the “gap” column.',
        ],
        expect: 'A typo is found by the vector side and missed by the keyword side. A question that shares no letters with its answer is weak for every method: the “gap” column is the lowest in every row, which the README states as the limit of this embedder.',
        lab: 'lab.html#search',
      },
      {
        label: 'Knock without a certificate',
        icon: 'lock',
        access: 'Lab · Queue',
        title: 'Open a connection to the gateway with and without a client certificate.',
        text: 'Mutual TLS fails at the handshake, before any HTTP.',
        steps: [
          'In <code>Queue</code>, press “Connect with the certificate”.',
          'Press “Connect without it”.',
          'Read both cards.',
        ],
        expect: 'With the certificate the gateway answers its health check. Without it the handshake is refused and the card names the error. The certificates are generated when the stack starts and never committed.',
        lab: 'lab.html#queue',
      },
      {
        label: 'Look for a person',
        icon: 'fingerprint',
        access: 'Lab · Privacy',
        title: 'Search the whole database for the names and identifiers it was given.',
        text: 'Not trusting the code that was meant to drop them.',
        steps: [
          'In <code>Sync</code>, press “Sync”. Open <code>Privacy</code>.',
          'Press “Search the whole database”.',
          'Read “Columns examined” and “Rows that contain one”.',
        ],
        expect: 'The scan reads every text, JSON and character column of every table and finds none of the forty people’s names, identifiers or registry ids. What is stored for them is a keyed hash, a month of birth and a team.',
        lab: 'lab.html#privacy',
      },
    ],
  },

  run: {
    eyebrow: 'Run it in a minute',
    title: ['One command.', 'A pipeline you can break.'],
    text: 'You need Docker and make. The stack is the API, a Celery worker and scheduler, PostgreSQL with pgvector, Redis, and two stand-ins. Nothing leaves your machine.',
    steps: [
      ['terminal', 'Clone', 'git clone, then cd into the folder.'],
      ['play', 'Start', 'make demo builds the image and starts seven containers with the lab on, bound to the loopback of your machine.'],
      ['globe', 'Open', 'http://localhost:8300 is this page. Press “Enter the lab”.'],
      ['flask', 'Break it', 'Use the hard parts above, or run make smoke for the checks that talk to the running stack.'],
    ],
    terminal: {
      title: 'bash',
      lines: [
        '# 1. get the code',
        'git clone https://github.com/MenoDK/pulse-health-pipeline.git',
        'cd pulse-health-pipeline',
        '# 2. start the stack (builds one image, nothing to configure)',
        'make demo',
        '# 3. open http://localhost:8300 and press “Enter the lab”',
        '# or read the numbers without a browser',
        'make smoke',
        'make eval',
      ],
    },
  },

  under: {
    eyebrow: 'Under the hood',
    title: ['Plain parts,', 'serious edges.'],
    text: 'The interesting code is short on purpose. The decisions behind it are written down with the alternatives that lost.',
    stackTitle: 'What it is built with',
    stack: [
      { group: 'Language', items: ['Python 3.11 to 3.13', 'mypy --strict · ruff', 'Pydantic at every edge', 'Exact fractions: no float in the score'] },
      { group: 'Data', items: ['PostgreSQL 16 + pgvector', 'Alembic migrations, round-tripped in a test', 'Partial indexes for the hot queries', 'A generated tsvector column'] },
      { group: 'Pipeline', items: ['FastAPI · Celery · Redis', 'Transactional outbox', 'Leases, fencing, SKIP LOCKED', 'OAuth client credentials + mutual TLS'] },
      { group: 'Quality', items: ['pytest against a real PostgreSQL', 'Hypothesis against a plain-Python reference', 'A sabotage script that must be caught', 'Playwright + axe · 14 languages'] },
      { group: 'Delivery', items: ['Multi-stage Dockerfile, non-root, read-only', 'Compose with health checks', 'GitHub Actions · pinned gitleaks', 'make demo'] },
    ],
    proofTitle: 'What is measured, and the records behind it',
    numbers: [
      ['550', 'tests, run against a real PostgreSQL, a real Redis and real HTTP servers'],
      ['158', 'sabotages of the code, each caught by the tests that guard it'],
      ['36', 'labelled search queries, four methods, one table'],
      ['8', 'decision records, each with the alternatives that lost'],
    ],
    decisions: [
      ['A queue with leases and fencing', 'ADR 0002: why messages live in PostgreSQL, and what a worker whose lease was taken over may not do.', 'docs/adr/0002-a-queue-with-leases-and-fencing.md'],
      ['An overlap window and a version guard', 'ADR 0003: why a sync re-reads a little, and why that costs nothing.', 'docs/adr/0003-an-overlap-window-and-a-version-guard.md'],
      ['Rank fusion over a weighted sum', 'ADR 0004: what the evaluation shows, and what it does not.', 'docs/adr/0004-rank-fusion-over-a-weighted-sum.md'],
      ['A check between the model and the number', 'ADR 0005: what the narrator may say, and how a refusal is shown.', 'docs/adr/0005-a-check-between-the-model-and-the-number.md'],
    ],
    measuredOn: 'Measured on 2026-11-05. Counts come from the commands in the README, not from memory.',
    future: [
      ['A sentence embedder behind the same interface', 'so the “gap” queries can be measured against something that reads meaning.'],
      ['A re-keying job for pseudonyms', 'the key id is already stored with every pseudonym, so a rotation can find the rows.'],
      ['A reconciliation count against the registry', 'to notice the record that the overlap window cannot.'],
      ['Backups and a restore drill for the database', 'which this repository deliberately leaves to the platform it runs on.'],
    ],
  },

  about: {
    why: 'Pulse is the unglamorous part of my work and the part people end up trusting: moving data between systems that do not trust each other. The shapes in it (a resumable sync, an outbox, a lease, a check on what a model says) come from integrations I have built and operated. The code in this repository is written fresh, tested against a real database, and breakable on purpose.',
  },

  faq: [
    ['Why is the queue in PostgreSQL and not in RabbitMQ or Kafka?', 'Because the message has to be written in the same transaction as the change that caused it, and a separate broker cannot join that transaction. Redis here only carries the schedule. The cost is polling and a throughput ceiling that a broker would not have; the claim reads a batch however large the backlog, which a plan test pins on 200 000 rows (ADR 0002).'],
    ['Is this exactly-once delivery?', 'No. It is at-least-once delivery with an idempotency key, which at the receiver behaves like exactly-once. The “keeps the report, then fails to answer” scenario in the lab is the case that matters: the pipeline sends again, and the answer “duplicate” is counted as delivered.'],
    ['Why not trust the model to word the numbers?', 'Because the failure is invisible: a fluent sentence with one rounded figure reads as correct. The check is cheap, deterministic and runs on every response, and it has a stated limit: numbers spelled out in words are not detected (ADR 0005).'],
    ['Is the hybrid search better?', 'Than either list alone, yes, on these 36 queries. Than a weighted sum of the raw scores, it ties on recall and is a hundredth behind on MRR, which is one query moving one place. Rank fusion earns its place because it has no weight to tune and no scale to convert, not because it scores higher (ADR 0004).'],
    ['Why does the lab have no login?', 'It runs on your machine, answers only to localhost, and refuses a request whose Host or Origin it does not own, so a page on another site cannot press its buttons. The service refuses to start with the lab on outside a development environment (ADR 0007).'],
    ['Is any of this real health data?', 'No. Every person is generated from syllables and random digits with valid check digits, and both outside systems are stand-ins that live in this repository. The shapes are realistic; the data and the numbers are not, and the indicator targets are illustrative.'],
  ],

  closing: {
    eyebrow: 'Your turn',
    title: ['Make the', 'pipeline fail.'],
    button: 'Open the lab',
    fine: 'Local only · fictitious data · nothing is sent anywhere',
  },
};
