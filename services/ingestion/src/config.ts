import { z } from 'zod';

const schema = z.object({
  DATABASE_URL: z.string().min(1),
  PORT: z.coerce.number().int().positive().default(8080),
  LOG_LEVEL: z.enum(['fatal', 'error', 'warn', 'info', 'debug', 'trace']).default('info'),
  API_KEYS: z.string().min(1),
  BODY_LIMIT_BYTES: z.coerce.number().int().positive().default(512 * 1024),
  REQUEST_TIMEOUT_MS: z.coerce.number().int().positive().default(10_000),
  CONNECTION_TIMEOUT_MS: z.coerce.number().int().positive().default(15_000),
});

export type Config = {
  databaseUrl: string;
  port: number;
  logLevel: string;
  bodyLimitBytes: number;
  requestTimeoutMs: number;
  connectionTimeoutMs: number;
  clientsByKey: Map<string, string>;
};

/** `API_KEYS` is `key:client` pairs, comma separated, so a key is always attributable to a caller. */
function parseKeys(raw: string): Map<string, string> {
  const clients = new Map<string, string>();

  for (const pair of raw.split(',')) {
    const trimmed = pair.trim();
    if (trimmed === '') continue;

    const separator = trimmed.indexOf(':');
    if (separator <= 0) {
      throw new Error(`API_KEYS entry is not key:client: ${trimmed}`);
    }

    const key = trimmed.slice(0, separator).trim();
    const client = trimmed.slice(separator + 1).trim();

    if (key.length < 16) throw new Error('API_KEYS contains a key shorter than 16 characters');
    if (client === '') throw new Error(`API_KEYS entry has no client name: ${key}`);

    clients.set(key, client);
  }

  if (clients.size === 0) throw new Error('API_KEYS defines no usable keys');

  return clients;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  const parsed = schema.safeParse(env);

  if (!parsed.success) {
    const problems = parsed.error.issues.map((issue) => `${issue.path.join('.')}: ${issue.message}`);
    throw new Error(`Configuration is not usable:\n  ${problems.join('\n  ')}`);
  }

  return {
    databaseUrl: parsed.data.DATABASE_URL,
    port: parsed.data.PORT,
    logLevel: parsed.data.LOG_LEVEL,
    bodyLimitBytes: parsed.data.BODY_LIMIT_BYTES,
    requestTimeoutMs: parsed.data.REQUEST_TIMEOUT_MS,
    connectionTimeoutMs: parsed.data.CONNECTION_TIMEOUT_MS,
    clientsByKey: parseKeys(parsed.data.API_KEYS),
  };
}
