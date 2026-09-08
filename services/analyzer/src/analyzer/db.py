from datetime import timedelta

import psycopg
from psycopg.rows import dict_row

from .models import Event, Finding

PENDING = """
SELECT event_id, agent_id, event_type, occurred_at, payload, tags
FROM agent_events
WHERE analyzed_at IS NULL OR analyzed_at < updated_at
ORDER BY updated_at
LIMIT %s
FOR UPDATE SKIP LOCKED
"""

PRIOR_SENSITIVE_READS = """
SELECT count(*)
FROM agent_events
WHERE agent_id = %s
  AND event_type = 'file_read'
  AND event_id <> %s
  AND occurred_at BETWEEN %s AND %s
  AND payload->>'path' ~ %s
"""

# One alert per event per rule, enforced by the database rather than by checking first, so
# re-analysis updates the wording instead of stacking duplicates.
UPSERT_ALERT = """
INSERT INTO alerts (event_id, agent_id, rule, severity, summary, details)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (event_id, rule) DO UPDATE
SET severity = EXCLUDED.severity,
    summary  = EXCLUDED.summary,
    details  = EXCLUDED.details
"""

SENSITIVE_PATH_REGEX = (
    r"(^|/)\.env(\.|$)|(^|/)id_(rsa|dsa|ecdsa|ed25519)$|\.aws/credentials$|(^|/)\.ssh/"
    r"|\.(pem|p12|pfx)$|(^|/)(credentials|secrets)\.(json|ya?ml)$|/var/run/secrets/"
)


def connect(database_url: str) -> psycopg.Connection:
    return psycopg.connect(database_url, row_factory=dict_row, autocommit=False)


def claim_pending(cursor: psycopg.Cursor, batch_size: int) -> list[Event]:
    cursor.execute(PENDING, (batch_size,))

    return [
        Event(
            event_id=row["event_id"],
            agent_id=row["agent_id"],
            event_type=row["event_type"],
            occurred_at=row["occurred_at"],
            payload=row["payload"],
            tags=list(row["tags"] or []),
        )
        for row in cursor.fetchall()
    ]


def prior_sensitive_reads(cursor: psycopg.Cursor, event: Event, window_minutes: int) -> int:
    cursor.execute(
        PRIOR_SENSITIVE_READS,
        (
            event.agent_id,
            event.event_id,
            event.occurred_at - timedelta(minutes=window_minutes),
            event.occurred_at,
            SENSITIVE_PATH_REGEX,
        ),
    )
    row = cursor.fetchone()

    return int(next(iter(row.values()))) if row else 0


def write_findings(cursor: psycopg.Cursor, event: Event, findings: list[Finding]) -> None:
    for finding in findings:
        cursor.execute(
            UPSERT_ALERT,
            (
                event.event_id,
                event.agent_id,
                finding.rule,
                finding.severity,
                finding.summary,
                psycopg.types.json.Json(finding.details),
            ),
        )


def mark_analyzed(cursor: psycopg.Cursor, event_ids: list[str]) -> None:
    cursor.execute(
        "UPDATE agent_events SET analyzed_at = now() WHERE event_id = ANY(%s)",
        (event_ids,),
    )
