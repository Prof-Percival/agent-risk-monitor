import { z } from 'zod';

export const eventSchema = z.object({
  event_id: z.string().min(1).max(200),
  agent_id: z.string().min(1).max(200),
  timestamp: z.string().datetime({ offset: true }),
  type: z.string().min(1).max(100),
  payload: z.record(z.unknown()),
  tags: z.array(z.string().min(1).max(100)).max(50).optional(),
});

export type AgentEvent = z.infer<typeof eventSchema>;

export const batchSchema = z.object({
  events: z.array(eventSchema).min(1).max(500),
});
