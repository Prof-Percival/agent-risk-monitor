import { describe, expect, it } from 'vitest';
import { loadConfig } from '../src/config.js';

const base = {
  DATABASE_URL: 'postgres://user:pass@localhost:5432/db',
  API_KEYS: 'a-key-of-sixteen:client-one',
};

describe('configuration', () => {
  it('maps each key to the client it belongs to', () => {
    const config = loadConfig({ ...base, API_KEYS: 'a-key-of-sixteen:one,another-long-key-x:two' });

    expect(config.clientsByKey.get('a-key-of-sixteen')).toBe('one');
    expect(config.clientsByKey.get('another-long-key-x')).toBe('two');
  });

  it('refuses a key short enough to guess', () => {
    expect(() => loadConfig({ ...base, API_KEYS: 'short:client' })).toThrow(/shorter than 16/);
  });

  it('refuses a key with no client to attribute it to', () => {
    expect(() => loadConfig({ ...base, API_KEYS: 'a-key-of-sixteen:' })).toThrow(/no client name/);
  });

  it('refuses an entry that is not key:client', () => {
    expect(() => loadConfig({ ...base, API_KEYS: 'no-separator-here-x' })).toThrow(/not key:client/);
  });

  it('refuses to start with no database', () => {
    expect(() => loadConfig({ API_KEYS: base.API_KEYS })).toThrow(/DATABASE_URL/);
  });

  it('refuses to start with no keys, so the service is never open', () => {
    expect(() => loadConfig({ DATABASE_URL: base.DATABASE_URL })).toThrow(/API_KEYS/);
  });

  it('ignores blank entries left by a trailing comma', () => {
    const config = loadConfig({ ...base, API_KEYS: 'a-key-of-sixteen:one, ,' });

    expect(config.clientsByKey.size).toBe(1);
  });

  it('defaults the limits that keep a request from flooding or hanging', () => {
    const config = loadConfig(base);

    expect(config.bodyLimitBytes).toBe(512 * 1024);
    expect(config.requestTimeoutMs).toBe(10_000);
    expect(config.connectionTimeoutMs).toBe(15_000);
  });

  it('takes the limits from the environment when they are set', () => {
    const config = loadConfig({
      ...base,
      BODY_LIMIT_BYTES: '1024',
      REQUEST_TIMEOUT_MS: '2000',
      CONNECTION_TIMEOUT_MS: '3000',
    });

    expect(config.bodyLimitBytes).toBe(1024);
    expect(config.requestTimeoutMs).toBe(2000);
    expect(config.connectionTimeoutMs).toBe(3000);
  });

  it('refuses a log level it does not recognise', () => {
    expect(() => loadConfig({ ...base, LOG_LEVEL: 'chatty' })).toThrow(/LOG_LEVEL/);
  });
});
