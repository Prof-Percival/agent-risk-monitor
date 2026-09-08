import { describe, expect, it } from 'vitest';
import { batchSchema, eventSchema } from '../src/events.js';

const valid = {
  event_id: 'evt-1',
  agent_id: 'agent-1',
  timestamp: '2026-09-08T10:15:00Z',
  type: 'file_read',
  payload: { path: '/home/app/.env' },
};

describe('event validation', () => {
  it('accepts an event with the required envelope', () => {
    expect(eventSchema.safeParse(valid).success).toBe(true);
  });

  it('accepts optional tags', () => {
    expect(eventSchema.safeParse({ ...valid, tags: ['prod', 'eu'] }).success).toBe(true);
  });

  it.each(['event_id', 'agent_id', 'timestamp', 'type', 'payload'])('requires %s', (field) => {
    const { [field]: _removed, ...without } = valid as Record<string, unknown>;

    expect(eventSchema.safeParse(without).success).toBe(false);
  });

  it('requires a timestamp carrying an offset, so ordering is not guesswork', () => {
    expect(eventSchema.safeParse({ ...valid, timestamp: '2026-09-08 10:15' }).success).toBe(false);
    expect(eventSchema.safeParse({ ...valid, timestamp: '2026-09-08T12:15:00+02:00' }).success).toBe(true);
  });

  it('keeps the payload open, since each event type carries its own shape', () => {
    const shellCommand = { ...valid, type: 'shell_command', payload: { command: 'ls -la' } };

    expect(eventSchema.safeParse(shellCommand).success).toBe(true);
  });

  it('rejects an empty batch and one over the limit', () => {
    expect(batchSchema.safeParse({ events: [] }).success).toBe(false);
    expect(batchSchema.safeParse({ events: Array(501).fill(valid) }).success).toBe(false);
    expect(batchSchema.safeParse({ events: [valid] }).success).toBe(true);
  });

  it('accepts a batch holding a bad item, so the endpoint can report on each one', () => {
    const batch = { events: [valid, { nonsense: true }] };

    expect(batchSchema.safeParse(batch).success).toBe(true);
  });
});
