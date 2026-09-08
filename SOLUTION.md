# Solution

Design notes and the trade-offs behind them. `README.md` covers how to run it.

## Contents

- [Shape of the system](#shape-of-the-system)
- [Why PostgreSQL is the integration point](#why-postgresql-is-the-integration-point)
- [Data model](#data-model)
- [Task 1: ingestion](#task-1-ingestion)
- [Task 2: analysis](#task-2-analysis)
- [Task 3: exposing insights](#task-3-exposing-insights)
- [Testing](#testing)
- [Operations](#operations)
- [Trade-offs and limits](#trade-offs-and-limits)
- [What I would do next](#what-i-would-do-next)

## Shape of the system

Three parts, one database:

| Part | Stack | Job |
|---|---|---|
| `services/ingestion` | TypeScript, Fastify | accepts events, stores them, serves the read API |
| `services/analyzer` | Python | claims unanalysed events, applies rules, writes alerts |
| `db/migrations` | SQL | the schema both sides agree on |

## Why PostgreSQL is the integration point

The two services never talk to each other. Node writes events, Python reads events and writes alerts,
Node reads both back. The database is the contract.

This was the main architectural choice. The alternative was a queue or broker between them, which is
closer to how this would look in production and would decouple the two properly. I turned it down
because it is another piece of infrastructure to stand up and reason about before anything works, and
storage was needed anyway, so using it as the meeting point adds no moving parts.

The cost is real and worth naming: both services know the schema, so a column rename is a change in two
languages at once. Migrations live in `db/` owned by neither service, so at least there is one place
that defines it.

## Data model

Two tables, in `db/migrations/001_init.sql`.

### `agent_events`

**`event_id` is the primary key.** Agents retry, so the same event arrives more than once and must not
land twice. Making the identifier the key lets the database decide, and the insert is
`ON CONFLICT (event_id) DO NOTHING`. I rejected reading first and inserting if absent: that leaves a
window where two deliveries of the same event both find nothing and both insert.

**`occurred_at` and `received_at` are separate columns.** `occurred_at` is the agent's clock and can
arrive late or skewed. `received_at` is ours and only ever moves forward. One column cannot answer both
"when did this happen" and "when did we learn about it", and which one you want differs by query: rules
reason about the agent's clock, the timeline orders on ours.

**`payload` is `jsonb`, alongside structured columns.** The envelope fields that every event has get
columns and indexes. The type-specific body is kept whole and unmodified, so a rule written later can
read a field nobody thought to extract today.

**`analyzed_at` marks progress, on the row itself.** The analyzer claims work with
`analyzed_at IS NULL OR analyzed_at < updated_at`, with a partial index on exactly that predicate, which
covers both a new event and one edited since it was last looked at.

I rejected a separate cursor or watermark table. A watermark is a single position, so it can fall
behind, and an event that produces no alerts would never advance it. It also breaks the moment two
analyzers run. Per-row state has neither problem.

### `agent_alerts`

**Unique on `(event_id, rule)`, written with `ON CONFLICT DO UPDATE`.** An event can be analysed more
than once, and doing so must not stack a second copy of the same finding. A constraint enforces that
whatever the caller does; checking for an existing alert first would be a race. The upsert refreshes
severity, summary and details, so re-analysing after a rule changes updates the wording in place.

Alerts reference events with `ON DELETE CASCADE`, and both tables carry the `agent_id` so the read
queries do not need a join to filter by agent.

## Task 1: ingestion

**Access control is API keys in an `X-Api-Key` header**, configured as `key:client` pairs so every key
maps to a named caller and a request can be attributed in the logs. Prototype grade on purpose: no JWTs,
no mTLS, no rotation. Config parsing refuses a key shorter than 16 characters and refuses to start with
no keys at all, so the service cannot come up accidentally open. One `onRequest` hook checks it, and the
health probes are the only things exempt.

**Validation is zod at the edge.** The envelope is strict: identifiers bounded, `timestamp` must carry
an offset so ordering is never guesswork, `payload` an open object because each event type has its own
shape.

**Bodies are capped at 512KB**, comfortably above the few hundred kilobytes these payloads run to.
`requestTimeout` caps a whole request and `connectionTimeout` closes a socket that has gone quiet. Both
are needed, for a reason described under [Testing](#testing).

**The batch endpoint validates the envelope only**, then checks each item as it stores it, so one bad
event returns a per-item rejection rather than losing the rest of the batch. This was a bug first: the
envelope validated every item, so a single malformed event rejected the whole request and the per-item
results the endpoint returns could never happen.

**Logging is structured and aimed at the failures worth troubleshooting.** A rejected body logs the
validation issues, a storage failure logs the error with its context, and a refused key logs the route
it was aimed at. Successes stay quiet.

## Task 2: analysis

**Rules are pure functions.** Each takes an `Analysis` (the event, the allowlist, and any history it
needs) and returns a `Finding` or `None`. No rule performs IO. Everything a rule needs is loaded before
it runs, which is why the 26 rule tests need no database and run in hundredths of a second. It also
means adding a rule is one function and one entry in a list.

**Five rules, spanning three shapes.** The count is not the point; covering the shapes is, because each
one needs something different from the code around it:

| Rule | Severity | Shape |
|---|---|---|
| `secret_file_access` | high | stateless, pattern over one field |
| `unapproved_domain` | medium | driven by configuration, not code |
| `remote_code_execution` | critical | pattern over command structure, not a command blocklist |
| `rapid_secret_reads` | high | needs history, so the context carries it |
| `privileged_tool_call` | high | inspects a nested structure |

`remote_code_execution` matches the shape of a download handed to an interpreter rather than listing bad
commands, because the list is endless and the shape is not. `rapid_secret_reads` fires at four or more
sensitive reads by one agent inside a window; a single credential read can be legitimate, sweeping
several in minutes is collection. Its history comes from a query in `db.py`, not from inside the rule,
so the rule stays testable.

**The analyzer is a CLI with two modes**, `once` and `watch`. `once` drains what is pending and exits,
which suits a cron entry or a manual run. `watch` polls on an interval, and is what compose runs. Two
modes covers both a scheduled job and a long-lived process without needing a scheduler for either.

**Claiming uses `FOR UPDATE SKIP LOCKED`** in one transaction per batch, so a second analyzer would take
different rows rather than duplicate work. Events are marked analysed and alerts written in the same
transaction, so a crash mid-batch leaves work to be redone rather than events silently marked done. The
`(event_id, rule)` constraint is what makes redoing it safe.

## Task 3: exposing insights

HTTP endpoints in the ingestion service, not a CLI:

| Endpoint | Answers |
|---|---|
| `GET /v1/alerts` | alerts in a window, filtered by `agent_id`, `rule`, `severity` |
| `GET /v1/agents/:id/summary` | totals, highest severity, top rules for a window |
| `GET /v1/agents/:id/timeline` | events and alerts interleaved |

A CLI would have needed its own database access, its own config, and its own auth to produce the same
JSON. Putting the reads in the service that already has all three was less code, and it leaves something
a dashboard can call directly rather than something a human has to run and copy out of. The service is
already the trusted boundary, so the same key mechanism covers reads.

**The timeline orders on `received_at`, not `occurred_at`.** This is the one place the two clocks
visibly matter. An event that arrives late has an old `occurred_at`, so ordering on the agent's clock
would show the event below alerts that were raised from it, which reads as an effect preceding its
cause. Ordering on our clock keeps cause before effect.

Windows and page sizes are bounded and return 400 outside their range, so a caller cannot ask for
everything by accident.

## Testing

Three suites, split by what they can actually catch.

**Unit tests, 47 of them, need nothing running.** 26 on the rules, because they are pure functions, and
21 on ingestion config and validation. These are fast enough to run on every save.

**End-to-end tests, 38 of them, in `tests/e2e`.** They talk to the running system over HTTP only, never
reaching into the database, and each test uses a unique `agent_id` so tests cannot satisfy each other's
assertions. They post to Node and read back what Python wrote.

These exist because the unit tests cannot see the seams, and the seams is where the bugs were. Every one
of the following was found by writing an end-to-end test, and none were visible to a unit test:

- The summary endpoint queried a table the schema never created. It passed locally only because an old
  volume still had a table from an earlier version of the migration. On any fresh database it was a 500.
- The migration runner was bind-mounted. Where the host path is not shared with the Docker VM the mount
  arrives as an empty directory, and the script then reported success having created nothing, so both
  services started against an empty database. Migrations are now baked into an image.
- The batch endpoint rejected a whole batch over one bad item, contradicting its own per-item results.
- A client that declared a `Content-Length` and then went quiet held its connection open past 40
  seconds. `requestTimeout` was set correctly, but Node only sweeps for expired requests every 30
  seconds and no per-socket timeout was set, so nothing closed an idle connection. `connectionTimeout`
  is a per-socket timer and ends it. A test now opens a raw socket and proves it.

`scripts/e2e.sh` brings the stack up, runs them, and tears it down, so a local run and a CI run are the
same command.

## Operations

**`docker compose up -d --build` is the whole thing.** PostgreSQL, migrations, ingestion, analyzer.

**Migrations are their own step**, applied by a one-shot service before either service starts,
recorded in `schema_migrations` so re-running is a no-op. Neither service owns the schema, because two
services share it. The runner exits non-zero if it finds no migrations at all, since reporting success
against an empty database is worse than failing.

**Configuration is environment variables with local defaults in `compose.yaml`.** No secrets in the
repo. `.env.example` documents every knob.

**The database is published on 5433**, not 5432, so it does not fight a PostgreSQL already installed on
the machine running it.

**CI runs four jobs on every push**: ingestion (typecheck and unit tests), analyzer (lint and unit
tests), the end-to-end suite against a real stack, and lint on the test package. The end-to-end job is
the one that matters, since it is the only one that would have caught any of the four bugs above.

## Trade-offs and limits

Things I chose knowingly, with what they cost:

- **Polling, not push.** Up to a five second lag between an event landing and its alert appearing. Fine
  for a monitor of this kind, and the first thing to change if it had to be near real time.
- **A shared database instead of a broker.** Simple to run, but both services know the schema.
- **`rapid_secret_reads` queries per file-read event.** Correct and indexed, but it is a query per event
  rather than a windowed aggregate, which would matter at high volume.
- **API keys in an environment variable.** Right for a prototype, and explicitly not a real secret
  store. Keys are compared directly, so there is no rotation story.
- **No rate limiting.** Not asked for, and it would be the next thing I added on a public path.
- **Single `001_init.sql`.** There is no migration history to demonstrate yet, and inventing one to look
  thorough would be noise.
- **Alert details are `jsonb` with no schema.** Flexible per rule, so a consumer has to know the rule to
  read them.

## What I would do next

In rough order of value:

1. Put a queue between ingestion and analysis, so alerts are raised on arrival rather than on a poll,
   and the two sides stop sharing a schema.
2. Move keys to a real secret store, and give them scopes, since submitting events and reading the
   dashboard are different privileges that currently share a mechanism.
3. Make rule thresholds configuration rather than constants, so tuning a noisy rule is not a deploy.
4. Add rate limiting and per-client quotas on the ingest path.
5. Track alerts through a lifecycle. Right now an alert is raised and read; nothing acknowledges,
   suppresses, or closes one, which is the first thing a real operator would want.
