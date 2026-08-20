# VIGILOX Document Intelligence

A production-oriented document intelligence service that ingests security
and identity documents, extracts structured information with OCR and an
LLM, validates every field against its own OCR evidence, and routes
uncertain results to a human reviewer with a full audit trail.

Supported document types:

- Guard licences
- SIA badges
- ID cards

---

## Why this design

The system is built around one rule: **every extracted value must be
traceable to the pixels it came from.**

Each OCR line gets an explicit stable ID (`L0`, `L1`, `L2`, …). The LLM
must cite those IDs when it reports a field, and the evidence validator
independently re-checks that the reported value actually appears in the
cited lines. A value the model "tidied up" fails that check and is
flagged rather than silently trusted.

Two further invariants shape the architecture:

- **Machine extraction is immutable.** A human correction never
  overwrites what the machine produced. Corrections are overlaid as
  *effective values* with `HUMAN_CORRECTION` provenance, so the original
  output stays auditable forever.
- **The client is never authoritative.** Reviewer identity is resolved
  server-side. A browser-supplied `reviewer_id` is accepted in the
  request body for backward compatibility and deliberately ignored.

---

## Pipeline

```text
Upload
  → bounded temporary file
  → OCR (PaddleOCR) with explicit line IDs
  → structured LLM extraction (Groq)
  → schema validation
  → OCR evidence validation
  → field confidence
  → date / expiry / logical validation
  → anomaly detection
  → machine review decision
  → permanent source storage
  → PostgreSQL persistence
  → human review (when required)
  → final effective record
  → audit history
```

---

## Architecture

Dependency direction is strictly one-way:

```text
frontend/            HTML + CSS + JS, served by FastAPI
    ↓
backend/app/api/     HTTP concerns only: routing, errors, validation, request IDs
    ↓
backend/app/services/    OCR, extraction, validation, review, storage
    ↓
database/            SQLAlchemy engine, ORM models, repositories
```

The API layer holds no OCR or extraction logic, the frontend never
imports Python, and `database/` imports nothing from `backend/`. The
import graph is verified to contain zero inversions and zero layer skips.

`database/` owns only the SQLAlchemy engine, ORM models, repositories and
DB-level exceptions. Services that merely *use* the database —
`PersistenceService` and `DocumentQueryService` — are application
orchestration and live in `backend/app/services/`.

See [`docs/architecture/overview.md`](docs/architecture/overview.md) for
the measured import graph.

---

## Project structure

```text
VIGILOX-Document-Intelligence/
├── backend/app/
│   ├── main.py              FastAPI application and routes
│   ├── api/                 error_handlers, request_validation,
│   │                        request_context, schemas
│   ├── core/                logging, paths
│   ├── domain/              extraction schemas
│   └── services/            19 application services
│
├── database/                engine, models, repositories
│                            (infrastructure only)
│
├── frontend/
│   ├── pages/               index.html, review_detail.html
│   └── static/              dashboard.css, dashboard.js,
│                            review_detail.js
│
├── tests/
│   ├── unit/                9   isolated logic
│   ├── integration/         10  services + PostgreSQL
│   ├── api/                 8   HTTP contracts
│   ├── security/            2   reviewer identity, duplicate review
│   ├── storage/             5   path safety, deletion, reconciliation
│   ├── dashboard/           4   dashboard/backend contracts
│   ├── e2e/                 3   full workflows
│   ├── real_dependencies/   6   real PaddleOCR + Groq + PostgreSQL
│   └── legacy/              2   quarantined, superseded (see its README)
│
├── evaluation/              images, ground_truth, results, reports, archive
├── scripts/                 evaluation, verification, maintenance, development
├── docs/                    architecture, phases
├── storage/                 runtime managed documents (gitignored)
├── samples/                 synthetic test documents
├── requirements.txt
└── .env.example
```

---

## Setup

Requires **Python 3.13** and a running **PostgreSQL** instance.

```powershell
cd C:\Users\DELL\Desktop\Intern\VIGILOX-Document-Intelligence

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Environment variables

Copy the template and fill it in:

```powershell
Copy-Item .env.example .env
```

| Variable | Required | Purpose |
| --- | --- | --- |
| `GROQ_API_KEY` | yes | LLM structured extraction |
| `DATABASE_URL` | yes | `postgresql+psycopg://user:pass@host:port/db` |
| `VIGILOX_LOG_LEVEL` | no | `DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL`, default `INFO` |
| `DOCUMENT_STORAGE_DIR` | no | Overrides the managed storage root |
| `VIGILOX_REVIEW_IDENTITY_MODE` | no | `local_env` (default) or `trusted_headers` |
| `VIGILOX_LOCAL_REVIEWER_ID` | no | Reviewer id used in `local_env` mode |
| `VIGILOX_LOCAL_REVIEWER_ROLE` | no | `VIEWER`/`REVIEWER`/`ADMIN`, default `REVIEWER` |

In `trusted_headers` mode the reviewer arrives via
`X-VIGILOX-REVIEWER-ID` and `X-VIGILOX-REVIEWER-ROLE`, which an upstream
proxy must inject after authenticating and stripping any client-supplied
values.

`.env` is gitignored. Never commit it.

### Database

The schema is created from the SQLAlchemy models. A one-time constraint
helper exists for the single-review guarantee:

```powershell
.\.venv\Scripts\python.exe .\scripts\maintenance\apply_phase7c_unique_review_constraint.py
```

---

## Run the API

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

Then open:

| URL | Purpose |
| --- | --- |
| `http://127.0.0.1:8000/review` | Review queue dashboard |
| `http://127.0.0.1:8000/review/{document_id}` | Document review workspace |
| `http://127.0.0.1:8000/docs` | OpenAPI docs |
| `http://127.0.0.1:8000/health` | Liveness |
| `http://127.0.0.1:8000/health/ready` | Readiness |

### API

| Method | Route |
| --- | --- |
| `GET` | `/health` |
| `GET` | `/health/ready` |
| `POST` | `/api/v1/documents/analyze` |
| `GET` | `/api/v1/documents/{document_id}` |
| `GET` | `/api/v1/documents/{document_id}/image` |
| `POST` | `/api/v1/documents/{document_id}/reviews` |
| `GET` | `/api/v1/documents/{document_id}/history` |
| `GET` | `/api/v1/reviews/queue` |
| `GET` | `/api/v1/reviewer/me` |

Errors use a stable machine-readable contract:

```json
{
  "status": "error",
  "detail": "...",
  "error": {
    "code": "DOCUMENT_NOT_FOUND",
    "message": "Document not found.",
    "request_id": "..."
  }
}
```

Every response carries an `X-Request-ID` header. For errors it matches
`error.request_id`, and both appear in the structured logs.

---

## Tests

Tests are standalone scripts, not pytest. The project root must be
importable, so either export `PYTHONPATH` or use the `-m` form.

```powershell
$env:PYTHONIOENCODING = "utf-8"

# Full regression gate (recommended)
.\.venv\Scripts\python.exe .\scripts\verification\run_phase7c7g_regressions.py

# Production invariants: routes, log levels, secret safety
.\.venv\Scripts\python.exe .\scripts\verification\verify_phase7c7_final.py

# A single test, module form
.\.venv\Scripts\python.exe -m tests.api.test_phase7c_readiness

# A single test, path form
$env:PYTHONPATH = "."
.\.venv\Scripts\python.exe .\tests\api\test_phase7c_readiness.py
```

Real-dependency tests call PaddleOCR, Groq and PostgreSQL for real. They
consume Groq daily tokens and will fail with HTTP 429 once the quota is
exhausted — that is an external limit, not a code failure.

```powershell
.\.venv\Scripts\python.exe -m tests.real_dependencies.test_phase7c_real_provenance_e2e
```

---

## Evaluation

```powershell
$env:PYTHONPATH = "."
.\.venv\Scripts\python.exe .\scripts\evaluation\evaluation_runner.py
.\.venv\Scripts\python.exe .\scripts\evaluation\evaluation_metrics.py
```

Phase 6D benchmark over 63 synthetic documents:

| Metric | Result |
| --- | --- |
| Document type accuracy | 100% |
| Normalized field accuracy | 98.64% |
| Critical-field normalized accuracy | 99.40% |
| False `AUTO_ACCEPT` cases | 0 |

⚠️ These figures were measured **before** the Phase 7C.8 extraction-prompt
change (verbatim text rule). `evaluation/reports/` has not been
regenerated since. Re-run the evaluation before treating them as current.

---

## Security notes

- `.env`, API keys and database credentials are never committed or logged.
- Structured logs use an allowlist; secrets, authorization headers,
  request bodies and document contents can never reach them.
- Internal exceptions never reach an HTTP response. Traces stay
  server-side.
- Uploads are bounded at 10 MiB by counting actual streamed bytes, not
  `Content-Length`. Only JPEG, PNG and WEBP are accepted.
- Client filenames are metadata only and never become storage paths.
  Path traversal, unsafe IDs and symlinks are rejected.
- Deletion is database-first: a DB row pointing at a missing file is
  worse than an orphan file, because orphans are detectable and
  reconcilable.
- Automatic reconciliation only ever removes `ORPHAN_STORAGE`. It never
  touches `MISSING_STORAGE`, `UNMANAGED_ENTRY` or healthy records.
- `trusted_headers` reviewer mode **must** sit behind a reverse proxy that
  strips client-supplied identity headers and injects authenticated ones.

---

## Current limitations

- Processing is synchronous; a large upload blocks its request.
- No batching, background workers or queueing yet.
- Groq usage is subject to a daily token quota with no retry/backoff layer.
- Bounding boxes are captured but not yet used to highlight evidence on
  the document image.
- The review dashboard is desktop-oriented.
- Reviewer authentication is a trust boundary, not an identity provider;
  it expects an upstream authenticating proxy.
