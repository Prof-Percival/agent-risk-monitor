import Fastify, { type FastifyInstance } from 'fastify';
import pg from 'pg';
import type { Pool } from 'pg';
import type { Config } from './config.js';
import { batchSchema, eventSchema } from './events.js';
import {
  agentSummary,
  agentTimeline,
  recentAlerts,
  saveEvent,
} from './store.js';

const AUTHENTICATED = Symbol('client');

export function buildServer(config: Config, pool: Pool): FastifyInstance {
  const app = Fastify({
    logger: { level: config.logLevel },
    bodyLimit: config.bodyLimitBytes,
    requestTimeout: config.requestTimeoutMs,
    disableRequestLogging: false,
  });

  app.addHook('onRequest', async (request, reply) => {
    if (request.url.startsWith('/health')) return;

    const presented = request.headers['x-api-key'];
    const client = typeof presented === 'string' ? config.clientsByKey.get(presented) : undefined;

    if (client === undefined) {
      request.log.info({ route: request.url }, 'rejected a request with no usable API key');
      return reply.code(401).send({ error: 'unauthorized' });
    }

    (request as never as Record<symbol, string>)[AUTHENTICATED] = client;
  });

  app.setErrorHandler((error, request, reply) => {
    const status = error.statusCode ?? 500;

    if (status >= 500) {
      request.log.error({ err: error }, 'request failed');
      return reply.code(status).send({ error: 'internal error' });
    }

    request.log.warn({ err: error.message, status }, 'request refused');
    return reply.code(status).send({ error: error.message });
  });

  app.get('/health/live', async () => ({ status: 'ok' }));

  app.get('/health/ready', async (_request, reply) => {
    try {
      await pool.query('SELECT 1');
      return { status: 'ok' };
    } catch {
      return reply.code(503).send({ status: 'database unreachable' });
    }
  });

  app.post('/v1/events', async (request, reply) => {
    const parsed = eventSchema.safeParse(request.body);

    if (!parsed.success) {
      request.log.warn({ issues: parsed.error.issues }, 'rejected a malformed event');
      return reply.code(400).send({ error: 'invalid event', issues: parsed.error.issues });
    }

    const result = await saveEvent(pool, parsed.data);

    return reply.code(202).send({ event_id: parsed.data.event_id, result });
  });

  app.post('/v1/events/batch', async (request, reply) => {
    const parsed = batchSchema.safeParse(request.body);

    if (!parsed.success) {
      return reply.code(400).send({ error: 'invalid batch', issues: parsed.error.issues });
    }

    const results = [];

    // Sequential: one bad item must not lose the rest, and the per item outcome is what a caller needs
    // to decide what to resend.
    for (const [index, event] of parsed.data.events.entries()) {
      const item = eventSchema.safeParse(event);

      if (!item.success) {
        results.push({ index, accepted: false, issues: item.error.issues });
        continue;
      }

      try {
        const result = await saveEvent(pool, item.data);
        results.push({ index, event_id: item.data.event_id, accepted: true, result });
      } catch (error) {
        request.log.error({ err: error, index }, 'failed to store a batch item');
        results.push({ index, event_id: item.data.event_id, accepted: false, error: 'storage failed' });
      }
    }

    const accepted = results.filter((item) => item.accepted).length;

    return reply.code(202).send({
      submitted: results.length,
      accepted,
      rejected: results.length - accepted,
      results,
    });
  });

  app.get('/v1/alerts', async (request, reply) => {
    const query = request.query as Record<string, string | undefined>;
    const hours = Number(query.hours ?? 24);
    const limit = Number(query.limit ?? 100);

    if (!Number.isFinite(hours) || hours <= 0 || hours > 720) {
      return reply.code(400).send({ error: 'hours must be between 1 and 720' });
    }

    if (!Number.isFinite(limit) || limit <= 0 || limit > 500) {
      return reply.code(400).send({ error: 'limit must be between 1 and 500' });
    }

    const alerts = await recentAlerts(pool, {
      ...(query.agent_id !== undefined ? { agentId: query.agent_id } : {}),
      ...(query.rule !== undefined ? { rule: query.rule } : {}),
      ...(query.severity !== undefined ? { severity: query.severity } : {}),
      hours,
      limit,
    });

    return { window_hours: hours, count: alerts.length, alerts };
  });

  app.get('/v1/agents/:agentId/summary', async (request, reply) => {
    const { agentId } = request.params as { agentId: string };
    const hours = Number((request.query as Record<string, string>).hours ?? 24);

    if (!Number.isFinite(hours) || hours <= 0 || hours > 720) {
      return reply.code(400).send({ error: 'hours must be between 1 and 720' });
    }

    return agentSummary(pool, agentId, hours);
  });

  app.get('/v1/agents/:agentId/timeline', async (request, reply) => {
    const { agentId } = request.params as { agentId: string };
    const query = request.query as Record<string, string | undefined>;
    const hours = Number(query.hours ?? 24);
    const limit = Number(query.limit ?? 100);

    if (!Number.isFinite(hours) || hours <= 0 || hours > 720) {
      return reply.code(400).send({ error: 'hours must be between 1 and 720' });
    }

    const items = await agentTimeline(pool, agentId, hours, Math.min(Math.max(limit, 1), 500));

    return { agent_id: agentId, window_hours: hours, count: items.length, items };
  });

  return app;
}

export function buildPool(config: Config): Pool {
  return new pg.Pool({
    connectionString: config.databaseUrl,
    max: 10,
    connectionTimeoutMillis: 5_000,
    idleTimeoutMillis: 30_000,
  });
}
