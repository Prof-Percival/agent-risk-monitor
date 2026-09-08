# Agent Risk Monitor

Receives activity events from AI agents, stores them, analyzes them against risk rules, and exposes the
resulting alerts for querying.

Three parts sharing one PostgreSQL database:

| Part | Stack | Job |
|---|---|---|
| `services/ingestion` | TypeScript, Fastify | accepts events, stores them, serves the read API |
| `services/analyzer` | Python | reads events, applies rules, writes alerts |
| `db/migrations` | SQL | the schema both sides agree on |

## Running it

Docker is the only requirement.

```bash
docker compose up -d --build
curl http://localhost:8080/health/ready
```

That starts PostgreSQL, applies migrations, runs the ingestion service on port 8080, and starts the
analyzer watching for new events.

```bash
docker compose logs -f analyzer     # watch alerts being raised
docker compose stop                 # stop, keeping the data
docker compose down -v              # stop and delete the data
```

The database is published on port 5433 rather than 5432 so it does not fight a PostgreSQL already
installed on the machine.

## Sending an event

Every endpoint except the health probes needs an API key.

```bash
curl -X POST http://localhost:8080/v1/events \
  -H 'Content-Type: application/json' \
  -H 'X-Api-Key: dev-agent-key-0000000001' \
  -d '{
    "event_id": "evt-0001",
    "agent_id": "agent-7",
    "timestamp": "2026-09-08T10:15:00Z",
    "type": "file_read",
    "payload": { "path": "/home/app/.aws/credentials" },
    "tags": ["prod"]
  }'
```

## Reading the insights

```bash
KEY='X-Api-Key: dev-dashboard-key-000001'

curl -H "$KEY" 'http://localhost:8080/v1/alerts?hours=24'
curl -H "$KEY" 'http://localhost:8080/v1/alerts?agent_id=agent-7&rule=secret_file_access'
curl -H "$KEY" 'http://localhost:8080/v1/agents/agent-7/summary?hours=24'
curl -H "$KEY" 'http://localhost:8080/v1/agents/agent-7/timeline?hours=24'
```

## Configuration

Everything is environment based, with local defaults in `compose.yaml`. See `.env.example`.

`SOLUTION.md` covers the design and the trade-offs.
