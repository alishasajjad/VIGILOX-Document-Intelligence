# Architecture Overview

## Layering

Dependency direction is strictly one-way. Nothing below reaches upward.

```text
frontend/                  HTML + CSS + JS. No Python. Talks HTTP only.
    ↓
backend/app/main.py        FastAPI app, routes, lifespan
backend/app/api/           error contract, upload validation, request IDs
    ↓
backend/app/services/      OCR, extraction, validation, review, storage,
                           persistence, queries
backend/app/core/          logging, path anchors      (cross-cutting)
backend/app/domain/        extraction schemas, job states,
                           classification, duplicates,
                           finding normalization      (cross-cutting)
    ↓
database/                  SQLAlchemy engine, ORM models, repositories
```

Rules that hold today, verified programmatically:

- The API layer contains **no** OCR or extraction business logic. It
  validates HTTP input, calls a service, and maps failures to stable
  error codes.
- `frontend/` never imports Python. It is served by FastAPI as static
  files and pages, and consumes the JSON API.
- `database/` owns the SQLAlchemy engine, ORM models, repositories and
  DB-level exceptions, and nothing else. It imports from `backend/` in
  exactly two places, both of them `backend/app/domain/job_states`:

  ```text
  database/models.py            -> backend.app.domain.job_states
  database/job_repositories.py  -> backend.app.domain.job_states
  ```

  This is the cross-cutting exemption below, not an inversion.
  `ACTIVE_STATUSES` defines which job statuses count as active, and the
  partial unique index in `models.py` is generated from it so that the
  index, the queries and the tests cannot disagree about what "active"
  means. Restating the tuple in `database/` to satisfy the rule would
  buy a cleaner diagram at the price of two definitions of a value the
  database enforces. See Phase 10.3.
- No layer skips. The API layer reaches the database only through a
  service.

The actual import graph, measured across `backend/` and `database/`:

```text
backend/app/services  -> database                18
backend/app/services  -> backend/app/domain      15
backend/app/main.py   -> backend/app/services    10
backend/app/services  -> backend/app/core         7
backend/app/main.py   -> backend/app/api          5
backend/app/api       -> backend/app/core         2
backend/app/main.py   -> backend/app/core         2
database              -> backend/app/domain       2
backend/app/api       -> backend/app/services     1
backend/app/main.py   -> backend/app/domain       1
backend/app/main.py   -> database                 1
```

Zero inversions, zero skips. `core/` (logging, paths) and `domain/` are
cross-cutting and may be imported from any layer, which is what the two
`database -> backend/app/domain` edges are.

`domain/` is where a rule lives when it belongs to the product rather
than to a service: the extraction schema, the job state machine, what
counts as a supported document, what counts as the same source bytes,
and how findings are presented. Nothing in it touches the database,
performs I/O, or decides anything a service has already decided -- the
Phase 10.6 suite asserts that for `findings.py` by reading its AST.

### How this was reached

Phase 8.1 originally left `persistence_service.py` and
`query_service.py` inside `database/`, where they imported *upward* into
`backend/app/services/`. That was inherited from the pre-Phase-8 layout,
where both sat beside those services as flat siblings inside `src/`, so
nothing looked inverted.

Inspection showed neither file is infrastructure:

- `PersistenceService` runs a transaction across four repositories, calls
  `DocumentStorageService` to write the permanent source file, and
  performs *compensating filesystem cleanup* when persistence fails.
  Deciding what to undo on failure is a business rule.
- `DocumentQueryService` coordinates five repositories and builds the
  final effective record through `FinalRecordService` — provenance,
  effective values and usability semantics.

Both are application orchestration that happens to own database access,
so both moved to `backend/app/services/`. The repositories are the real
infrastructure and stayed put.

One further edge was removed at the same time: `main.py` imported
`DuplicateHumanReviewError` directly from `database/repositories.py`,
skipping the service layer. That exception is a domain concept — its own
docstring calls it "the application-level protection layer" — and
`PersistenceService` is what raises it, so the API now catches it from
the service layer instead. It still lives in `repositories.py` where it
is defined; only the import path changed.

## Application composition

Services are constructed once in the FastAPI lifespan and stored on
`app.state`:

| `app.state` | Type |
| --- | --- |
| `pipeline` | `DocumentPipelineService` |
| `persistence` | `PersistenceService` |
| `document_query` | `DocumentQueryService` |
| `human_review` | `HumanReviewService` |
| `reviewer_identity` | `ReviewerIdentityService` |
| `readiness` | `ReadinessService` |

This is deliberate, plain composition rather than a DI framework. It also
makes tests straightforward: a test swaps one attribute on `app.state`
for a double and restores it afterwards.

## Request lifecycle

Starlette builds the middleware stack outermost-first:

```text
ServerErrorMiddleware        -> renders unhandled 500s
  └── RequestIDMiddleware    -> generates the authoritative request ID
        └── ExceptionMiddleware  -> APIError / HTTPException / 422
              └── router
```

This ordering has a consequence worth remembering: an unhandled
exception is rendered by `ServerErrorMiddleware`, which sits **outside**
the correlation middleware. A `send` wrapper in that middleware can
therefore never attach `X-Request-ID` to a 500.

The request ID is attached in two places to cover every path:

- `RequestIDMiddleware` — successful responses
- each handler in `api/error_handlers.py` — all four error paths

## Evidence provenance

The core guarantee is that extracted values are traceable to pixels.

1. `ocr_service` assigns each line a stable ID: `L0`, `L1`, `L2`, …
2. `extraction_service` must cite those exact IDs in `source_line_ids`.
3. `evidence_validator` independently re-checks that the reported value
   appears in the cited lines, after normalizing case and punctuation.
4. `confidence_service` derives field confidence from the minimum OCR
   confidence across the cited evidence lines.

Step 3 is a genuine adversarial check, not a formality. Dates are the
only values permitted to be reformatted (normalized to `YYYY-MM-DD`);
every other text field must be a verbatim substring of its evidence.
When the LLM reorders a name such as `SAMPLE,JANE` into `Jane Sample`,
evidence validation fails and raises `FULL_NAME_EVIDENCE_MISMATCH`.

## Immutability and effective values

`document_analyses.extraction` is written once and never mutated.

A human `CORRECT` action stores corrections separately. The final record
is computed on read by `final_record_service`:

| Final status | `is_final` | `is_usable` | `effective_values` |
| --- | --- | --- | --- |
| `AUTO_ACCEPTED` | yes | yes | machine values |
| `PENDING_REVIEW` | no | no | `None` |
| `APPROVED` | yes | yes | machine values |
| `CORRECTED` | yes | yes | machine values + corrections overlaid |
| `REJECTED` | yes | no | `None` |

Corrected fields carry `HUMAN_CORRECTION` provenance in
`value_sources`; untouched fields stay `MACHINE`.

## Trust boundaries

**Reviewer identity.** The client is never authoritative.
`ReviewerIdentityService` resolves the reviewer server-side in one of two
modes: `local_env` for development, or `trusted_headers` behind a proxy
that authenticates and injects `X-VIGILOX-REVIEWER-ID` /
`X-VIGILOX-REVIEWER-ROLE` while stripping anything the client sent. The
request body still accepts `reviewer_id` for backward compatibility and
the backend deliberately ignores it.

**Request correlation.** The server always generates its own `uuid4`. A
client-supplied `X-Request-ID` is sanitized and retained separately as a
non-authoritative tracing value; it never becomes the authoritative ID.

**Uploads.** Content type is restricted to JPEG/PNG/WEBP. Size is bounded
at 10 MiB by counting actual streamed bytes — `Content-Length` is not
trusted. Client filenames are metadata only and never become paths.

## Storage lifecycle

Success path: temporary file → pipeline → permanent managed storage →
PostgreSQL row referencing it.

Failure path: temporary file always removed; partial permanent storage
compensated.

Deletion is **database-first**, deliberately. A database row pointing at
a missing file is worse than an orphan file on disk, because an orphan is
detectable and reconcilable while a dangling reference is not.

`storage_reconciliation_service` therefore only ever deletes
`ORPHAN_STORAGE`. It never touches `MISSING_STORAGE`,
`UNMANAGED_ENTRY`, or healthy records, and a dry run mutates nothing.

## Observability

Structured JSON logs on the `vigilox.*` logger hierarchy. The formatter
uses a strict **allowlist** — `timestamp`, `level`, `logger`, `event`,
`message`, `request_id`, `document_id`, `reviewer_id`, `status_code`,
`error_code`, `error_type`. Anything else attached to a record is
dropped, so secrets, authorization headers and request bodies cannot
leak even by accident.

Exception traces are logged server-side and never returned to a client.

## Health vs readiness

`GET /health` is liveness only and dependency-free, so an orchestrator
never restarts a healthy process because PostgreSQL blipped.

`GET /health/ready` checks PostgreSQL connectivity, managed storage
availability/writability/safety, and required service initialization. It
never runs OCR or LLM inference. Failures return 503 with a stable reason
code and the exception class name only — never `str(exc)`, because
SQLAlchemy connection errors embed the database password.

## Deployed topology

The runtime picture, as distinct from the code layering above. Five
containers from **one image** — the API, the worker and the migration
step run different commands against the same build, so their dependencies
and their code cannot drift apart.

```
                          internet
                              │
                              ▼
                    ┌───────────────────┐
                    │  proxy  (nginx)   │  the only published port
                    │  :80 / :443       │  strips identity headers
                    └─────────┬─────────┘  injects authoritative ones
                              │            rate-limits by route cost
                              │            denies /docs /metrics
                  network: edge│
                              ▼
                    ┌───────────────────┐
                    │  api  (uvicorn)   │  no published port
                    │  lazy OCR         │  serves UI + JSON
                    └─────────┬─────────┘
                              │
              network: internal
                    ┌─────────┴──────────┬──────────────┐
                    ▼                    ▼              ▼
          ┌──────────────────┐  ┌────────────────┐  ┌──────────────┐
          │ postgres :5432   │  │ managed        │  │ pending      │
          │ rows AND the     │  │ documents      │  │ uploads      │
          │ durable queue    │  │ volume         │  │ volume       │
          └────────┬─────────┘  └────────────────┘  └──────────────┘
                   │                    ▲                  ▲
                   │  FOR UPDATE        │                  │
                   │  SKIP LOCKED       │                  │
                   ▼                    │                  │
          ┌──────────────────┐          │                  │
          │ worker           ├──────────┴──────────────────┘
          │ eager OCR        │
          │ no ports at all  │───────────► Groq  (outbound only)
          └──────────────────┘
                   │
                   └── migrate: same image, `alembic upgrade head`, exits
```

### Why each edge is shaped that way

**The api publishes no port.** With one, everything the proxy does —
stripping identity headers, rate limiting, denying `/docs` — is
bypassable by connecting directly.

**The queue is PostgreSQL, not Redis.** A job row and the document row it
produces commit in the same transaction. A separate broker cannot give
you that, and the price of adding one is a second thing to run, back up
and reason about.

**Two storage volumes, never one.** A pending file has no document row by
definition, so under the managed root the integrity scan classes it as an
orphan — and orphans are the one category reconciliation deletes
automatically. The application refuses to start if the pending root is
nested inside the managed one.

**The worker accepts nothing.** It makes outbound calls to the extraction
provider and takes no inbound connections, so it needs no ingress path at
all.

**OCR loading is opposite in the two roles.** The API is lazy (measured
3 ms of startup) because it never runs OCR except through the legacy
synchronous route; the worker is eager (2929 ms) because the model *is*
the job, and eager means a broken model install fails the container start
where a deploy can see it rather than failing the first document.

Consequence, stated because it is easy to assume otherwise: with the API
lazy, `/health/ready` passing does **not** mean OCR models are loaded in
that process.

### Where each concern is answered

| | |
|---|---|
| Configuration and commands | [../deployment/deployment.md](../deployment/deployment.md) |
| Day-to-day operations | [../operations/production-runbook.md](../operations/production-runbook.md) |
| Alerting | [../operations/monitoring.md](../operations/monitoring.md) |
| Backup and restore | [../operations/backup-restore.md](../operations/backup-restore.md) |
| Shutdown and recovery | [../operations/shutdown.md](../operations/shutdown.md) |
| Security posture | [../security/security.md](../security/security.md) |
