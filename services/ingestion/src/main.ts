import { loadConfig } from './config.js';
import { buildPool, buildServer } from './server.js';

const config = loadConfig();
const pool = buildPool(config);
const app = buildServer(config, pool);

async function shutdown(signal: string): Promise<void> {
  app.log.info({ signal }, 'shutting down');
  await app.close();
  await pool.end();
  process.exit(0);
}

for (const signal of ['SIGTERM', 'SIGINT'] as const) {
  process.on(signal, () => void shutdown(signal));
}

try {
  await app.listen({ port: config.port, host: '0.0.0.0' });
} catch (error) {
  app.log.fatal({ err: error }, 'failed to start');
  process.exit(1);
}
