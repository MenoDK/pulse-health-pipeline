"""initial schema: analytic layer, sync state, transmission queue, search index, health

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

DDL = [
    "CREATE EXTENSION IF NOT EXISTS vector",
    # --- analytic layer: pseudonymous keys only ------------------------------------------------------------------
    """CREATE TABLE teams (
        team_id text PRIMARY KEY,
        name text NOT NULL,
        kind text NOT NULL,
        active boolean NOT NULL,
        version integer NOT NULL CHECK (version >= 0),
        source_updated_at timestamptz NOT NULL
    )""",
    """CREATE TABLE subjects (
        subject_key text PRIMARY KEY,
        key_id text NOT NULL,
        team_id text,
        birth_month date NOT NULL CHECK (EXTRACT(DAY FROM birth_month) = 1),
        chronic boolean NOT NULL,
        registered_on date NOT NULL,
        registry_refreshed_on date NOT NULL,
        version integer NOT NULL CHECK (version >= 0),
        deleted boolean NOT NULL,
        source_updated_at timestamptz NOT NULL
    )""",
    "CREATE INDEX subjects_team_idx ON subjects (team_id) WHERE NOT deleted",
    """CREATE TABLE encounters (
        encounter_id text PRIMARY KEY,
        subject_key text NOT NULL,
        team_id text,
        kind text NOT NULL,
        occurred_on date NOT NULL,
        version integer NOT NULL CHECK (version >= 0),
        deleted boolean NOT NULL,
        source_updated_at timestamptz NOT NULL
    )""",
    "CREATE INDEX encounters_subject_idx ON encounters (subject_key, occurred_on DESC) WHERE NOT deleted",
    "CREATE INDEX encounters_kind_idx ON encounters (kind, occurred_on) WHERE NOT deleted",
    # --- sync ----------------------------------------------------------------------------------------------------
    """CREATE TABLE sync_state (
        entity text PRIMARY KEY,
        cursor_updated_at timestamptz,
        updated_at timestamptz NOT NULL
    )""",
    """CREATE TABLE sync_runs (
        id bigserial PRIMARY KEY,
        started_at timestamptz NOT NULL,
        finished_at timestamptz,
        status text NOT NULL CHECK (status IN ('running', 'ok', 'failed')),
        pages integer NOT NULL DEFAULT 0,
        fetched integer NOT NULL DEFAULT 0,
        applied integer NOT NULL DEFAULT 0,
        stale integer NOT NULL DEFAULT 0,
        rejected integer NOT NULL DEFAULT 0,
        error text
    )""",
    # --- transmission queue --------------------------------------------------------------------------------------
    """CREATE TABLE outbox (
        id bigserial PRIMARY KEY,
        idempotency_key text NOT NULL UNIQUE,
        kind text NOT NULL,
        payload jsonb NOT NULL,
        status text NOT NULL CHECK (status IN ('pending', 'sending', 'done', 'dead')),
        attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
        not_before timestamptz NOT NULL,
        lease_until timestamptz,
        locked_by text,
        last_status integer,
        last_error text,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        done_at timestamptz,
        CHECK ((status = 'sending') = (lease_until IS NOT NULL))
    )""",
    "CREATE INDEX outbox_due_idx ON outbox (not_before, id) WHERE status = 'pending'",
    "CREATE INDEX outbox_lease_idx ON outbox (lease_until, id) WHERE status = 'sending'",
    """CREATE TABLE outbox_attempts (
        id bigserial PRIMARY KEY,
        outbox_id bigint NOT NULL REFERENCES outbox (id) ON DELETE CASCADE,
        at timestamptz NOT NULL,
        outcome text NOT NULL,
        http_status integer,
        detail text
    )""",
    "CREATE INDEX outbox_attempts_idx ON outbox_attempts (outbox_id, id)",
    # --- search --------------------------------------------------------------------------------------------------
    """CREATE TABLE kb_chunks (
        id bigserial PRIMARY KEY,
        doc_id text NOT NULL,
        chunk_no integer NOT NULL,
        title text NOT NULL,
        category text NOT NULL,
        content text NOT NULL,
        embedding vector(256) NOT NULL,
        tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', title || ' ' || content)) STORED,
        UNIQUE (doc_id, chunk_no)
    )""",
    "CREATE INDEX kb_chunks_embedding_idx ON kb_chunks USING hnsw (embedding vector_cosine_ops)",
    "CREATE INDEX kb_chunks_tsv_idx ON kb_chunks USING gin (tsv)",
    # --- health --------------------------------------------------------------------------------------------------
    """CREATE TABLE health_samples (
        id bigserial PRIMARY KEY,
        at timestamptz NOT NULL,
        component text NOT NULL,
        status text NOT NULL CHECK (status IN ('ok', 'degraded', 'down')),
        latency_ms integer,
        detail text
    )""",
    "CREATE INDEX health_samples_idx ON health_samples (component, at DESC)",
    "CREATE TABLE heartbeats (component text PRIMARY KEY, at timestamptz NOT NULL)",
    "CREATE TABLE lab_state (key text PRIMARY KEY, value jsonb NOT NULL)",
]


def upgrade() -> None:
    for statement in DDL:
        op.execute(statement)


def downgrade() -> None:
    for table in (
        "lab_state",
        "heartbeats",
        "health_samples",
        "kb_chunks",
        "outbox_attempts",
        "outbox",
        "sync_runs",
        "sync_state",
        "encounters",
        "subjects",
        "teams",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")  # noqa: S608 (fixed names above, not input)
