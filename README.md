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

## Loading some data to look at

A fresh stack is empty. This posts a scenario that trips every rule, plus an agent whose activity is
ordinary and must stay quiet:

```bash
python3 scripts/seed.py
```

It goes through the HTTP API, not SQL, so everything it creates has been through validation and the
analyzer. Running it twice changes nothing, as the event ids are fixed. Standard library only, so there
is nothing to install.

## Inspecting the database

The database runs in a container but its port is published, so any client on the host can reach it.
Nothing appears automatically in a tool you already have: register a connection using these details.

| Setting | Value |
|---|---|
| Host | `localhost` |
| Port | `5433` |
| Database | `kyber` |
| Username | `kyber` |
| Password | `kyber` |

In pgAdmin that is Register, then Server. This adds one entry alongside whatever servers you already
have and touches none of them. If your pgAdmin is itself running in a container, use
`host.docker.internal` instead of `localhost`, because `localhost` there means the pgAdmin container.

On the command line, without installing anything:

```bash
docker compose exec db psql -U kyber -d kyber -c '\dt'
docker compose exec db psql -U kyber -d kyber -c 'SELECT rule, severity, count(*) FROM agent_alerts GROUP BY 1, 2 ORDER BY 1;'
```

Data lives in a named volume, so `docker compose stop` and `docker compose up` keep it. Only
`docker compose down -v` deletes it.

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

In PowerShell, `curl` is an alias for `Invoke-WebRequest`, which takes `-Headers` with a hashtable
rather than `-H` with a string, so the commands above fail on the header. Use `curl.exe` to get the real
curl, or the native equivalent:

```powershell
Invoke-RestMethod -Uri 'http://localhost:8080/v1/alerts?hours=24' `
  -Headers @{ 'X-Api-Key' = 'dev-dashboard-key-000001' } | ConvertTo-Json -Depth 6
```

`scripts/seed.py` prints whichever form suits the platform it ran on.

## Configuration

Everything is environment based, with local defaults in `compose.yaml`. See `.env.example`.

## Tests

Unit tests need nothing running. The rules are pure functions and the schemas are plain validation,
so both suites are fast.

```bash
cd services/ingestion && npm ci && npm run lint && npm test
cd services/analyzer  && pip install -e ".[dev]" && ruff check . && pytest -q
```

The end to end tests in `tests/e2e` are the ones that prove the two services actually meet. They post
to the Node API and read back what the Python analyzer wrote, over HTTP only. One command brings the
stack up, runs them, and tears it down:

```bash
./scripts/e2e.sh           # add --keep to leave the stack running
```

On Windows, run it as `bash scripts/e2e.sh`. Invoking a `.sh` file directly from PowerShell or cmd
hands it to Git Bash in a separate window that closes on exit, taking the output with it.

They also cover the two limits the brief sets, which no unit test can see: a body of a few hundred
kilobytes is accepted, one past the limit is refused, and a client that declares a body then stalls
gets closed rather than held open.

Against a stack that is already up:

```bash
pip install -e tests/e2e && pytest tests/e2e -q
```

CI runs all of the above on every push. `SOLUTION.md` covers the design and the trade-offs.
