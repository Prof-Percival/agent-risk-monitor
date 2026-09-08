import type { Pool } from 'pg';
import type { AgentEvent } from './events.js';

export type SaveResult = 'stored' | 'duplicate';

/**
 * Repeat delivery is normal, so the primary key decides rather than a read beforehand: a check and then
 * an insert leaves a window where two deliveries of one event both find nothing.
 */
export async function saveEvent(pool: Pool, event: AgentEvent): Promise<SaveResult> {
  const result = await pool.query(
    `INSERT INTO agent_events (event_id, agent_id, event_type, occurred_at, tags, payload)
     VALUES ($1, $2, $3, $4, $5, $6)
     ON CONFLICT (event_id) DO NOTHING`,
    [
      event.event_id,
      event.agent_id,
      event.type,
      event.timestamp,
      event.tags ?? [],
      JSON.stringify(event.payload),
    ],
  );

  return result.rowCount === 1 ? 'stored' : 'duplicate';
}

export type AlertRow = {
  alert_id: string;
  event_id: string;
  agent_id: string;
  rule: string;
  severity: string;
  summary: string;
  created_at: string;
};

export async function recentAlerts(
  pool: Pool,
  filters: { agentId?: string; rule?: string; severity?: string; hours: number; limit: number },
): Promise<AlertRow[]> {
  const result = await pool.query<AlertRow>(
    `SELECT alert_id, event_id, agent_id, rule, severity, summary, created_at
     FROM agent_alerts
     WHERE created_at >= now() - make_interval(hours => $1)
       AND ($2::text IS NULL OR agent_id = $2)
       AND ($3::text IS NULL OR rule = $3)
       AND ($4::text IS NULL OR severity = $4)
     ORDER BY created_at DESC
     LIMIT $5`,
    [filters.hours, filters.agentId ?? null, filters.rule ?? null, filters.severity ?? null, filters.limit],
  );

  return result.rows;
}

export type AgentSummary = {
  agent_id: string;
  window_start: string;
  window_end: string;
  total_alerts: number;
  total_events: number;
  max_severity: string | null;
  top_rules: { rule: string; count: number }[];
};

export async function agentSummary(pool: Pool, agentId: string, hours: number): Promise<AgentSummary> {
  const result = await pool.query(
    `WITH window_bounds AS (
         SELECT now() - make_interval(hours => $2) AS starts_at, now() AS ends_at
     ),
     agent_alerts AS (
         SELECT a.rule, a.severity
         FROM agent_alerts a, window_bounds w
         WHERE a.agent_id = $1 AND a.created_at BETWEEN w.starts_at AND w.ends_at
     )
     SELECT
         (SELECT starts_at FROM window_bounds) AS window_start,
         (SELECT ends_at FROM window_bounds) AS window_end,
         (SELECT count(*) FROM agent_alerts) AS total_alerts,
         (SELECT count(*) FROM agent_events e, window_bounds w
           WHERE e.agent_id = $1 AND e.received_at BETWEEN w.starts_at AND w.ends_at) AS total_events,
         (SELECT severity FROM agent_alerts
           ORDER BY array_position(ARRAY['critical','high','medium','low'], severity) LIMIT 1) AS max_severity,
         COALESCE((SELECT jsonb_agg(ranked)
                   FROM (SELECT rule, count(*)::int AS count FROM agent_alerts
                         GROUP BY rule ORDER BY count DESC, rule LIMIT 5) ranked), '[]'::jsonb) AS top_rules`,
    [agentId, hours],
  );

  const row = result.rows[0];

  return {
    agent_id: agentId,
    window_start: row.window_start,
    window_end: row.window_end,
    total_alerts: Number(row.total_alerts),
    total_events: Number(row.total_events),
    max_severity: row.max_severity,
    top_rules: row.top_rules,
  };
}

export type TimelineItem = {
  timestamp: string;
  kind: 'event' | 'alert';
  reference_id: string;
  brief: string;
};

/**
 * Ordered on the service clock rather than the agent's, because an event that arrives late would
 * otherwise appear before alerts already raised from it.
 */
export async function agentTimeline(
  pool: Pool,
  agentId: string,
  hours: number,
  limit: number,
): Promise<TimelineItem[]> {
  const result = await pool.query<TimelineItem>(
    `SELECT received_at AS timestamp, 'event' AS kind, event_id AS reference_id,
            event_type || ' at ' || to_char(occurred_at, 'YYYY-MM-DD"T"HH24:MI:SSOF') AS brief
     FROM agent_events
     WHERE agent_id = $1 AND received_at >= now() - make_interval(hours => $2)
     UNION ALL
     SELECT created_at AS timestamp, 'alert' AS kind, alert_id::text AS reference_id,
            severity || ': ' || summary AS brief
     FROM agent_alerts
     WHERE agent_id = $1 AND created_at >= now() - make_interval(hours => $2)
     ORDER BY timestamp DESC
     LIMIT $3`,
    [agentId, hours, limit],
  );

  return result.rows;
}
