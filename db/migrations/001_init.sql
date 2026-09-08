-- Events and alerts. Two services share this schema, so neither owns it.

CREATE TABLE IF NOT EXISTS agent_events (
    event_id     text PRIMARY KEY,
    agent_id     text        NOT NULL,
    event_type   text        NOT NULL,
    occurred_at  timestamptz NOT NULL,
    received_at  timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    tags         text[]      NOT NULL DEFAULT '{}',
    payload      jsonb       NOT NULL,
    analyzed_at  timestamptz
);

-- The analyzer claims work with analyzed_at IS NULL OR analyzed_at < updated_at, which covers both a new
-- event and one that changed after it was last looked at, and needs no separate cursor to fall behind.
CREATE INDEX IF NOT EXISTS ix_agent_events_pending
    ON agent_events (updated_at)
    WHERE analyzed_at IS NULL OR analyzed_at < updated_at;

-- occurred_at is the agent's clock and can arrive out of order. received_at is ours and only ever
-- increases, so it is what the analyzer and the timeline order by when the two disagree.
CREATE INDEX IF NOT EXISTS ix_agent_events_agent_occurred
    ON agent_events (agent_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS ix_agent_events_updated
    ON agent_events (updated_at);

CREATE INDEX IF NOT EXISTS ix_agent_events_type
    ON agent_events (event_type);

CREATE TABLE IF NOT EXISTS agent_alerts (
    alert_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id   text        NOT NULL REFERENCES agent_events (event_id) ON DELETE CASCADE,
    agent_id   text        NOT NULL,
    rule       text        NOT NULL,
    severity   text        NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    summary    text        NOT NULL,
    details    jsonb       NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (event_id, rule)
);

CREATE INDEX IF NOT EXISTS ix_agent_alerts_created
    ON agent_alerts (created_at DESC);

CREATE INDEX IF NOT EXISTS ix_agent_alerts_agent_created
    ON agent_alerts (agent_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_agent_alerts_rule
    ON agent_alerts (rule);
