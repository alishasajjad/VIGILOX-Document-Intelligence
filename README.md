<div align="center">

<img src="frontend/static/favicon.svg" alt="VIGILOX Logo" width="88">

# VIGILOX

### AI-Powered Document Intelligence for Security & Compliance

**OCR · Structured Extraction · Evidence Validation · Human Review · Audit Trail**

<br>

[![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Production_API-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-18-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![PaddleOCR](https://img.shields.io/badge/OCR-PaddleOCR-0052CC)](https://github.com/PaddlePaddle/PaddleOCR)
[![Groq](https://img.shields.io/badge/LLM-Groq-F55036)](https://groq.com/)
[![Docker](https://img.shields.io/badge/Docker-Configured-2496ED?logo=docker&logoColor=white)](#deployment)
[![Tests](https://img.shields.io/badge/Deterministic_Gate-72%2F72_Passing-brightgreen)](#testing)

<br>

[Overview](#overview) •
[Features](#key-features) •
[Architecture](#system-architecture) •
[Setup](#local-development) •
[API](#api-overview) •
[Testing](#testing) •
[Security](#security) •
[Deployment](#deployment) •
[Documentation](#documentation)

</div>

---

## Overview

**VIGILOX** is a production-oriented Document Intelligence platform designed for processing security and identity-related documents using OCR, structured AI extraction, evidence validation, deterministic rules, durable background processing, and human review.

The system can:

- ingest supported document images
- preserve the original source document
- extract OCR text
- convert OCR output into structured data
- validate extracted fields against OCR evidence
- assess image quality
- evaluate expiry and logical consistency
- route uncertain documents for human review
- preserve machine extraction separately from human corrections
- produce an authoritative final record
- maintain a complete audit history

VIGILOX is built around one core principle:

> **AI output should not become authoritative unless the supporting evidence and validation rules justify it.**

The platform combines machine intelligence, deterministic validation, durable processing, and human oversight instead of treating LLM output as unquestioned truth.

---

# Key Features

## Supported Documents

VIGILOX currently supports:

- Security Guard Licences
- ID Cards
- SIA Badges

Document type detection is automatic.

Unsupported or unrelated documents are handled as a separate domain outcome and are never silently treated as valid supported credentials.

---

## Document Processing

VIGILOX provides:

- Browser-based image upload
- Single-document processing
- Batch processing
- JPG, JPEG, PNG and WEBP support
- Actual-byte upload size validation
- Automatic document-type detection
- PaddleOCR-powered text extraction
- Groq-powered structured extraction
- Strict Pydantic schema validation
- Original source-image preservation
- Structured machine-readable output
- Durable PostgreSQL-backed processing jobs
- Retry and provider backoff handling
- Human review where required

---

## OCR Evidence Verification

Every extracted field can be linked back to the OCR lines that support it.

```text
Extracted Value
      ↓
OCR Evidence
      ↓
Original Source Image
      ↓
Bounding Box Highlight
```

The reviewer can inspect the original document and highlight the exact OCR evidence associated with an extracted value.

This makes extraction auditable instead of presenting AI output as an unexplained black box.

---

## Original Document Preservation

The original uploaded document is preserved independently of OCR and extracted data.

```text
Upload
  ↓
Pending Storage
  ↓
Worker Processing
  ↓
Managed Storage
  ↓
Document Image Endpoint
  ↓
Review Workspace
```

For successfully persisted documents, the Review Workspace loads the source directly from the same-origin image endpoint:

```text
/api/v1/documents/{document_id}/image
```

If an older or incomplete record genuinely has no source file, the UI presents a controlled unavailable state instead of leaving a broken browser image.

---

## Image Quality Assessment

VIGILOX performs deterministic image-quality measurements.

Current measured findings include:

- `IMAGE_BLURRY`
- `IMAGE_UNREADABLE`
- `IMAGE_TOO_DARK`
- `IMAGE_OVEREXPOSED`
- `ROTATION_CONCERN`
- `IMAGE_TOO_SMALL`

`IMAGE_LOW_CONTRAST` was intentionally not shipped because measurement showed the tested metric was unreliable on the available corpus.

Quality signals are designed to make machine routing more conservative.

They may escalate:

```text
AUTO_ACCEPT
    ↓
REVIEW_REQUIRED
```

but cannot clear an existing review requirement.

### Quality Calibration Scope

Current thresholds were calibrated using the available VIGILOX evaluation corpus and controlled image degradations.

They should not be interpreted as universal physical-image quality thresholds for every camera, scanner, lighting condition, or production population.

---

## Confidence Interpretation

VIGILOX uses **field-level confidence** based primarily on OCR/evidence support.

Confidence is **not treated as a calibrated probability that a semantic field is correct**.

A value may have extremely strong OCR evidence while still being assigned to the wrong semantic field.

For example:

```text
OCR reads a date correctly
        ↓
High OCR confidence
        ↓
Extraction assigns it to wrong date field
```

Therefore VIGILOX does not generate a misleading document-level confidence percentage.

### Calibration Finding

Confidence calibration analysis showed that higher field confidence did not reliably imply higher semantic correctness on the available benchmark.

The product therefore presents confidence as:

> **OCR and evidence support strength**

and not as:

> **probability that the extracted field is correct**

---

## Automated Decisioning

A typical machine-processing path is:

```text
Document
   ↓
OCR
   ↓
Structured Extraction
   ↓
Evidence Validation
   ↓
Date / Logical Validation
   ↓
Image Quality Assessment
   ↓
Findings
   ↓
Machine Decision
```

Documents that cannot be safely accepted automatically are routed according to authoritative machine decision rules.

---

# Unsupported Documents

A successfully identified unsupported document is treated as a **domain outcome**, not an infrastructure failure.

Typical semantics:

```text
Job Status:
COMPLETED

Document Type:
unknown

Supported:
false

Usable:
false

Retryable:
false

Effective Record:
none
```

Unsupported documents:

- can never auto-accept
- do not become usable final records
- do not automatically pollute the normal Review Queue
- remain auditable/discoverable where appropriate
- are not described using fraud, tamper, or suspicion language

Quality and classification remain separate concepts.

A blurry supported licence does not automatically become an unsupported document.

---

# Duplicate Detection

VIGILOX computes a SHA-256 fingerprint over the **original uploaded bytes**.

```text
Original Upload
      ↓
SHA-256
      ↓
Duplicate Lookup
      ↓
Existing Document / Active Job
```

Duplicate protection prevents accidental repeated OCR and LLM processing.

Supported duplicate outcomes include:

```text
DUPLICATE_DOCUMENT
DUPLICATE_IN_PROGRESS
```

Concurrent active duplicates are protected at the PostgreSQL level using an active-job partial unique index.

This avoids unsafe:

```text
check
then insert
```

race conditions.

### Duplicate Policy

Default behavior avoids unnecessary reprocessing.

A deliberate reprocess may be requested explicitly where supported.

The source fingerprint remains identical because the original bytes remain identical.

The hash is not exposed through normal public API or UI payloads.

---

# Batch Processing

VIGILOX supports both single and batch document workflows.

## Single Document

```text
Select File
   ↓
Preview
   ↓
Create Durable Job
   ↓
Worker Processing
   ↓
Completed Result
```

## Batch Upload

```text
Document A ─┐
Document B ─┼─→ Batch
Document C ─┘
               ↓
         Independent Jobs
```

Batch functionality includes:

- Per-file validation
- Independent child job states
- Partial success
- Duplicate handling
- Invalid-file preservation
- Completed-document links
- Failure isolation

One invalid or failed file does not invalidate successful siblings.

---

# Async Processing

Document analysis is performed using a durable PostgreSQL-backed job queue.

```text
Browser
   │
   ▼
FastAPI
   │
   ▼
Document Job
   │
   ▼
PostgreSQL
   │
   ▼
Worker
   │
   ├── OCR
   ├── Structured Extraction
   ├── Validation
   ├── Quality Assessment
   └── Persistence
   │
   ▼
Completed Document
```

Processing is independent of the browser session.

The browser may close while the server-side job continues.

---

## Job States

The durable job model uses a deliberately small state set:

```text
QUEUED
PROCESSING
RETRY_WAIT
COMPLETED
FAILED
```

`current_stage` provides advisory processing context without inventing fake progress percentages.

---

## Durable Worker Claims

Workers claim jobs using PostgreSQL row locking:

```sql
FOR UPDATE SKIP LOCKED
```

This allows multiple workers to compete safely for available jobs.

Worker leases protect against dead or abandoned workers.

A stale worker cannot silently overwrite the authoritative completion produced by a newer lease owner.

---

## Retry Handling

Infrastructure/provider failures are separated from structured-output recovery.

Typical behavior:

```text
429 Rate Limit
→ Job-level retry
→ RETRY_WAIT
→ Retry-After respected

5xx / Connection Failure
→ Job-level retry
→ Backoff

Malformed Structured Output
→ Bounded extraction-level recovery

Unsupported Document
→ Valid domain outcome
→ No provider retry
```

Retries are bounded and cannot continue indefinitely.

When configured attempts are exhausted:

```text
FAILED
ATTEMPTS_EXHAUSTED
```

may be returned.

---

# Human Review Workflow

The reviewer workspace provides:

- Original uploaded document
- OCR evidence overlays
- Extracted fields
- Field confidence
- Image quality
- Validation findings
- Final record state
- Technical information
- Review history
- Reviewer notes
- Approve action
- Correct action
- Reject action

Typical workflow:

```text
Open Review Queue
       ↓
Select Document
       ↓
Inspect Original Source
       ↓
Compare Extracted Fields
       ↓
Inspect OCR Evidence
       ↓
Review Findings
       ↓
Approve / Correct / Reject
       ↓
Final Record + Audit History
```

---

## Final Record States

VIGILOX keeps machine analysis separate from the final authoritative record.

| Final State | Final | Usable | Effective Source |
|---|---:|---:|---|
| `AUTO_ACCEPTED` | Yes | Yes | Machine |
| `PENDING_REVIEW` | No | No | Withheld |
| `APPROVED` | Yes | Yes | Machine |
| `CORRECTED` | Yes | Yes | Human overlay |
| `REJECTED` | Yes | No | None |
| `UNSUPPORTED` | Yes | No | None |

Machine extraction remains immutable.

Human corrections are applied as an overlay rather than rewriting the original machine extraction.

---

# Dashboard

The Dashboard provides operational visibility into:

- Total processed documents
- Pending reviews
- Automatically accepted documents
- Human-reviewed documents
- Review priority distribution
- Validity and expiry state
- Operational service state

Dashboard metrics are calculated from real PostgreSQL data.

The application does not display fabricated:

- AI accuracy scores
- fraud probabilities
- tamper probabilities
- generic risk percentages

---

# Document Library

The Documents page supports:

- Pagination
- Document-type filtering
- Final-state filtering
- Machine-decision filtering
- Expiry filtering
- Filename search
- Document-ID search
- Deterministic sorting

Sensitive OCR contents and extracted personal values are intentionally excluded from general search.

---

# System Architecture

```text
┌──────────────────────────────────────┐
│               Browser                │
│                                      │
│ Dashboard                            │
│ Upload                               │
│ Documents                            │
│ Review Queue                         │
│ Document Workspace                   │
└───────────────────┬──────────────────┘
                    │
                    ▼
┌──────────────────────────────────────┐
│               Nginx                  │
│                                      │
│ Reverse Proxy                        │
│ Rate Limits                          │
│ Security Boundary                    │
└───────────────────┬──────────────────┘
                    │
                    ▼
┌──────────────────────────────────────┐
│               FastAPI                │
│                                      │
│ Documents API                        │
│ Jobs / Batches API                   │
│ Review API                           │
│ Dashboard API                        │
│ Security                             │
│ Health / Metrics                     │
└─────────────┬─────────────────┬──────┘
              │                 │
              ▼                 ▼
┌────────────────────────┐   ┌────────────────────────┐
│       PostgreSQL       │   │    Pending Storage     │
│                        │   │                        │
│ Documents              │   │ In-flight job sources  │
│ Analyses               │   └──────────┬─────────────┘
│ Reviews                │              │
│ Audit Events           │              ▼
│ Jobs                   │   ┌────────────────────────┐
│ Batches                │   │         Worker         │
│ Worker Heartbeats      │   │                        │
└─────────────┬──────────┘   │ PaddleOCR              │
              │              │ Groq Extraction        │
              │              │ Evidence Validation    │
              │              │ Quality Assessment     │
              │              │ Persistence            │
              │              └──────────┬─────────────┘
              │                         │
              ▼                         ▼
┌──────────────────────────────────────────────┐
│          Managed Document Storage            │
│                                              │
│       Original uploaded source images        │
└──────────────────────────────────────────────┘
```

---

# Technology Stack

## Backend

- Python 3.13
- FastAPI
- Pydantic
- SQLAlchemy 2
- Psycopg 3

## Database

- PostgreSQL
- Alembic migrations

## AI & OCR

- PaddleOCR
- PaddlePaddle
- Groq API
- `openai/gpt-oss-20b`

## Frontend

- HTML5
- CSS3
- Vanilla JavaScript
- Responsive design system

## Infrastructure

- Docker
- Docker Compose
- Nginx
- PostgreSQL-backed durable worker queue

---

# Repository Structure

```text
VIGILOX-Document-Intelligence/
│
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── domain/
│   │   ├── services/
│   │   └── main.py
│   │
│   └── worker.py
│
├── database/
│   ├── database.py
│   ├── models.py
│   ├── repositories.py
│   └── job_repositories.py
│
├── migrations/
│
├── frontend/
│   ├── pages/
│   └── static/
│       ├── css/
│       ├── js/
│       └── favicon.svg
│
├── tests/
│   ├── api/
│   ├── dashboard/
│   ├── deployment/
│   ├── e2e/
│   ├── integration/
│   ├── intelligence/
│   ├── jobs/
│   ├── security/
│   ├── storage/
│   └── unit/
│
├── evaluation/
│   ├── archive/
│   └── reports/
│
├── scripts/
│   ├── development/
│   └── verification/
│
├── docs/
│   ├── architecture/
│   ├── deployment/
│   ├── operations/
│   ├── security/
│   ├── evaluation/
│   └── release/
│
├── docker/
│   ├── entrypoint.sh
│   └── nginx/
│
├── storage/
├── samples/
├── output/
│
├── Dockerfile
├── docker-compose.yml
├── alembic.ini
├── requirements.txt
├── .env.example
├── .dockerignore
└── README.md
```

> The exact repository tree may evolve as operational documentation and release artifacts are refined.

---

# Local Development

## Prerequisites

Install:

- Python 3.13
- PostgreSQL
- Git

Optional for container deployment:

- Docker
- Docker Compose

---

## 1. Clone the Repository

```bash
git clone <YOUR_REPOSITORY_URL>
cd VIGILOX-Document-Intelligence
```

---

## 2. Create a Virtual Environment

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

---

## 3. Install Dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

---

## 4. Configure Environment

Copy:

```text
.env.example
```

to:

```text
.env
```

Configure the required settings.

Typical examples include:

```env
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:PORT/DATABASE
GROQ_API_KEY=your_groq_api_key
```

The production extraction model defaults to:

```env
VIGILOX_GROQ_MODEL=openai/gpt-oss-20b
```

See `.env.example` for the complete configuration reference.

> Never commit `.env`, API keys, passwords, or real document data.

---

# Database Setup

Apply all migrations:

```powershell
python -m alembic upgrade head
```

Check the current revision:

```powershell
python -m alembic current
```

Check for model/schema drift:

```powershell
python -m alembic check
```

Production schema management should use Alembic migrations rather than ORM `create_all()`.

---

# Start the API

```powershell
python -m uvicorn backend.app.main:app --reload
```

Local application:

```text
http://127.0.0.1:8000
```

---

# Start the Worker

Open a second terminal:

```powershell
cd VIGILOX-Document-Intelligence
.\.venv\Scripts\Activate.ps1

python -m backend.worker
```

The worker initializes the OCR pipeline and claims durable jobs independently of browser sessions.

---

# Web Interface

| Page | URL |
|---|---|
| Dashboard | `/dashboard` |
| Upload Document | `/upload` |
| Documents | `/documents` |
| Review Queue | `/review` |
| Document Workspace | `/review/{document_id}` |

Browser tabs use VIGILOX branding and page-specific titles such as:

```text
Dashboard · VIGILOX
Upload Document · VIGILOX
Documents · VIGILOX
Review Queue · VIGILOX
Document Review · VIGILOX
```

---

# Health Checks

## Liveness

```http
GET /health
```

Example:

```json
{
  "status": "ok",
  "service": "vigilox-document-intelligence",
  "version": "0.1.0"
}
```

---

## Readiness

```http
GET /health/ready
```

Readiness verifies critical runtime dependencies without running OCR or calling the external AI provider.

Typical dependencies include:

- PostgreSQL
- Managed storage
- Service configuration
- Database connection capacity

Worker availability is monitored separately from API readiness.

---

# API Overview

Representative API groups include:

```text
/api/v1/documents
/api/v1/document-jobs
/api/v1/document-batches
/api/v1/reviewer
/api/v1/dashboard
```

Examples:

```http
POST /api/v1/document-jobs
GET  /api/v1/document-jobs/{job_id}

GET  /api/v1/documents
GET  /api/v1/documents/{document_id}
GET  /api/v1/documents/{document_id}/image

GET  /api/v1/dashboard/summary
```

A synchronous analysis endpoint is retained for compatibility where required.

The primary production browser flow uses asynchronous jobs.

---

# Error Contract

VIGILOX uses a consistent structured error envelope:

```json
{
  "status": "error",
  "detail": "Human-readable explanation",
  "error": {
    "code": "ERROR_CODE",
    "message": "Safe error message",
    "request_id": "request-id"
  }
}
```

Request identifiers are generated server-side and returned through:

```text
X-Request-ID
```

Error messages avoid exposing secrets, storage paths, or unnecessary internal details.

---

# Security

VIGILOX includes multiple defensive layers.

## Request Security

- Server-authoritative request IDs
- Strict upload validation
- Actual-byte size enforcement
- Content-type validation
- Safe identifiers
- Path traversal protection
- Symlink rejection
- Controlled error contracts

---

## Reviewer Identity

Production reviewer identity may be established through a trusted reverse proxy.

Reviewer identity headers are accepted only from explicitly configured trusted proxy sources.

Production fails closed when trusted-header authentication is configured unsafely.

Direct clients cannot safely elevate themselves by supplying privileged reviewer headers.

---

## Authorization

Reviewer actions remain server-authoritative.

Frontend visibility does not replace backend authorization.

Roles are enforced by the application according to the configured reviewer identity model.

---

## Browser Security

VIGILOX applies security headers including controls such as:

- Content Security Policy
- `X-Content-Type-Options`
- `X-Frame-Options`
- Referrer Policy
- Permissions Policy
- Cross-Origin Opener Policy

The frontend uses same-origin JavaScript, CSS, and document image resources.

Unsafe inline JavaScript and inline event handlers are avoided.

---

## CORS

The primary application is same-origin.

CORS is disabled unless explicitly required.

Wildcard production origins are rejected.

---

## Rate Limiting

Expensive write operations can be rate limited.

The application-level limiter is intentionally process-local and should be treated as defense-in-depth.

For multi-process production deployment, Nginx provides deployment-level request limiting.

Job-status polling is not treated the same way as expensive upload endpoints.

---

# Storage Safety

Pending uploads and managed document storage are intentionally separated.

```text
Pending Job Storage
        ≠
Managed Document Storage
```

This prevents in-flight files from being incorrectly classified as managed-storage orphans.

Storage protections include:

- Canonical storage roots
- Safe document identifiers
- Atomic writes
- Symlink rejection
- DB-first deletion
- Integrity reconciliation
- Orphan detection
- Missing-source detection

---

# Auditability

VIGILOX preserves the distinction between:

```text
Machine Extraction
Human Decision
Effective Record
```

This allows the system to answer:

- What did the machine originally extract?
- Which OCR evidence supported it?
- Why was review required?
- Who reviewed the document?
- What was corrected?
- What became the final usable record?

---

# Observability

VIGILOX provides structured operational logging without logging full document contents.

Logging avoids:

- OCR text
- extracted PII
- API keys
- database passwords
- reviewer correction contents
- managed filesystem paths

Useful operational events include:

```text
worker.starting
worker.warmup_complete
job.retry_scheduled
job.completed
```

---

# Metrics

Operational metrics are designed to avoid uncontrolled label cardinality.

Useful metric categories include:

- HTTP request volume
- HTTP latency
- Job queue depth
- Job state counts
- Job completion/failure counts
- Worker processing duration
- OCR duration
- LLM duration
- Provider rate-limit events
- Batch outcomes
- Worker heartbeat

Identifiers such as document IDs, filenames, and reviewer identities are not used as arbitrary high-cardinality metric labels.

Metrics exposure is configurable in production.

---

# Worker Health

Worker health is independent of API readiness.

The system distinguishes conditions such as:

```text
HEALTHY
STALE
NO_WORKER
```

A running API therefore does not falsely imply that a functioning worker is available.

---

# Testing

VIGILOX contains deterministic:

- Unit tests
- Integration tests
- API tests
- Security tests
- Storage tests
- Frontend tests
- Worker tests
- Job/concurrency tests
- Intelligence tests
- Migration tests
- Deployment configuration tests
- End-to-end regression tests

Run the standard deterministic regression gate:

```powershell
python scripts/verification/run_phase7c7g_regressions.py --exclude-real
```

Latest verified deterministic result:

```text
PASSED  : 72
FAILED  : 0
BLOCKED : 0
MISSING : 0
```

> `--exclude-real` intentionally excludes six real-dependency suites. It proves the deterministic release gate, not the complete external-provider release gate.

---

## Real Dependency Tests

When external dependencies and provider quota are available:

```powershell
python scripts/verification/run_phase7c7g_regressions.py --only-real
```

Real-provider suites are separated because they use:

- Real PaddleOCR
- Real Groq API
- Real PostgreSQL
- External provider quota

They should not be executed repeatedly without reason.

---

# Evaluation

VIGILOX includes an evaluation framework for comparing extracted values against labelled document fixtures.

Evaluation metrics include:

- Document-type accuracy
- Exact field accuracy
- Normalized field accuracy
- Known-field normalized accuracy
- Critical-field normalized accuracy
- Fully correct documents
- Machine decision distribution
- False automatic acceptance

A release-critical invariant is:

```text
False AUTO_ACCEPT = 0
```

Historical evaluation artifacts are archived before new final reports are generated.

---

## Critical-Field Baseline Correction

An earlier evaluation implementation maintained a separate critical-field definition and omitted production-critical `issuer` fields for relevant document types.

The originally reported historical metric was:

```text
99.40% (167 / 168)
```

After aligning evaluation with the authoritative production definition, the corrected historical baseline became:

```text
99.05% (208 / 210)
```

This difference reflects a **metric-definition correction**, not a model regression.

Evaluation and production now share the authoritative critical-field definition.

---

# Performance

Phase 9 performance measurement showed that OCR remains the dominant local processing cost.

Measured behavior included:

```text
POST /document-jobs
median ≈ 16 ms
p95    ≈ 21 ms

GET /document-jobs/{id}
median ≈ 3 ms
p95    ≈ 9 ms

Worker processing
median ≈ 17.4 s

Previous synchronous pipeline
median ≈ 18.4 s
```

The async architecture therefore improves **API and user-facing responsiveness**.

It does not claim to make CPU OCR processing itself dramatically faster.

---

# Pipeline Initialization

API and worker initialization are intentionally separable.

Measured startup behavior showed that lazy API pipeline initialization can significantly reduce API startup time, while workers benefit from loading OCR before claiming jobs.

The deployment configuration should choose initialization behavior deliberately.

---

# Deployment

VIGILOX includes:

- `Dockerfile`
- `.dockerignore`
- Docker Compose configuration
- Nginx reverse proxy configuration
- API role
- Worker role
- Migration role
- PostgreSQL service
- Persistent document storage
- Persistent pending-job storage

Conceptually:

```text
Public Traffic
     ↓
   Nginx
     ↓
   FastAPI
     ↓
 PostgreSQL
     ↑
   Worker

Managed Storage
Pending Storage
```

The backend API is not intended to be directly exposed publicly when production identity depends on the trusted reverse-proxy boundary.

---

## Docker Roles

A single application image supports operational roles such as:

```text
api
worker
migrate
```

This keeps API, worker, and migration code aligned to the same application build.

---

## Docker Validation Status

Docker and Compose configuration are included and covered by deterministic/static deployment tests.

Current verified state:

```text
Dockerfile / Compose Configuration     ✅
Static Deployment Contracts            ✅
Nginx Configuration Contracts          ✅
Application Container Runtime Build    ⚠️ Not executed in the development environment
```

The final Docker image build and production-stack smoke test should be performed on a host where Docker is available.

---

# Database Migrations in Production

Run migrations before starting a new application version:

```bash
alembic upgrade head
```

Verify state:

```bash
alembic current
alembic check
```

Production deployments should not depend on automatic ORM table creation.

---

# Backup & Restore

VIGILOX includes operational guidance for backing up:

- PostgreSQL
- Managed document storage
- Pending retryable job sources

Database rows and document files are related and should be backed up using a coordinated operational procedure.

A database dump and unrelated filesystem copy should not automatically be assumed transactionally consistent.

See the operational documentation under:

```text
docs/operations/
```

---

# Graceful Shutdown

The API and worker are designed for controlled shutdown.

Workers should:

- stop claiming new jobs
- avoid falsely completing interrupted work
- release/close database resources
- allow lease-based recovery where processing is interrupted

Durable job state remains represented in PostgreSQL.

---

# Deployment Checklist

Before exposing a production deployment:

```text
[ ] Production .env configured
[ ] GROQ_API_KEY configured
[ ] DATABASE_URL configured
[ ] PostgreSQL reachable

[ ] Alembic upgrade head completed
[ ] Alembic current verified
[ ] Alembic check clean

[ ] API starts successfully
[ ] Worker starts successfully
[ ] Reverse proxy starts successfully

[ ] /health returns 200
[ ] /health/ready returns ready
[ ] Worker health verified

[ ] Dashboard loads
[ ] Upload page loads
[ ] Documents page loads
[ ] Review Queue loads
[ ] Document Workspace loads

[ ] VIGILOX favicon renders
[ ] Static JS/CSS load correctly
[ ] Original document image renders
[ ] Evidence highlighting works

[ ] Duplicate detection works
[ ] Unsupported-document behavior works
[ ] Human review works

[ ] Deterministic regression gate passes
[ ] Production secrets are not committed
[ ] Reverse-proxy identity boundary is configured
[ ] Rate limiting is configured
[ ] Backup strategy is verified
[ ] Docker/runtime smoke test completed on deployment host
```

---

# Troubleshooting

## API Does Not Start

Check:

```powershell
python -m alembic current
python -m alembic check
```

Verify:

```text
DATABASE_URL
```

and other required configuration.

---

## Worker Starts but Documents Remain Queued

Confirm the worker is running:

```powershell
python -m backend.worker
```

Check:

- worker heartbeat
- PostgreSQL connectivity
- job state
- pending source availability
- worker logs

---

## Provider Rate Limited

Jobs may enter:

```text
RETRY_WAIT
```

VIGILOX respects provider retry behavior.

Typical state:

```text
PROVIDER_RATE_LIMITED
→ RETRY_WAIT
→ bounded retry
```

After all configured attempts are exhausted:

```text
FAILED
ATTEMPTS_EXHAUSTED
```

may be returned.

Provider quota and rate limits are external runtime constraints rather than application health failures.

---

## Original Document Does Not Display

Test the source endpoint directly:

```text
/api/v1/documents/{document_id}/image
```

If the source exists, the Document Workspace should render it as a same-origin image.

If an older record genuinely has no source file, VIGILOX presents a controlled unavailable state.

---

## Evidence Does Not Render

Confirm:

- original source image loaded successfully
- browser-reported image dimensions are available
- evidence toggle is enabled
- OCR evidence IDs exist for the selected field

Evidence overlays are only enabled when a usable source image is available.

---

# Design Principles

## Evidence Before Trust

AI output should be backed by source evidence.

## Fail Closed

Ambiguous or unsupported outcomes must not silently become usable records.

## Immutable Machine Extraction

Human corrections do not rewrite historical machine output.

## Durable Processing

Browser sessions are not job queues.

## PostgreSQL as the System of Record

Documents, analysis, jobs, reviews, and audit history remain durable.

## No Invented Intelligence

VIGILOX does not create unsupported:

- fraud probabilities
- tamper probabilities
- AI risk percentages
- document-level confidence percentages

## Human Oversight Where Uncertainty Matters

Automation reduces reviewer workload without removing reviewer authority.

---

# Known Limitations

Current known limitations include:

- OCR processing is CPU-bound.
- External AI processing remains subject to provider quota, rate limits, and availability.
- Image-quality thresholds are calibrated on the available evaluation corpus rather than every possible real-world camera population.
- Very small images may still contain readable text despite resolution warnings.
- Large dark regions may affect simple overexposure measurements.
- OCR/evidence confidence does not measure semantic field-assignment correctness.
- Some historical test records created before managed source persistence may not have an original source image.
- Application-level rate limiting is process-local; deployment-level Nginx limiting provides the broader production boundary.
- Docker configuration has been statically validated, but the final image/runtime stack must still be smoke-tested on a Docker-enabled deployment host.

---

# Documentation

Additional architecture, deployment, operations, security, evaluation, and release documentation is maintained under:

```text
docs/
├── architecture/
├── deployment/
├── operations/
├── security/
├── evaluation/
└── release/
```

The authoritative production-readiness report is maintained separately from this README.

---

# Future Improvements

Potential future extensions include:

- Additional credential types
- External identity provider and enterprise SSO integration
- Object-storage support
- Distributed worker scaling
- Expanded real-world evaluation corpus
- Reviewer analytics
- Multi-tenant organization support

---

# Security Notice

Never commit:

```text
.env
API keys
database passwords
real identity documents
private certificates
production document storage
pending uploads
```

Use synthetic or properly authorized documents for testing.

---

# License

This repository is intended for project-specific/private use unless a separate license is provided.

Do not assume permission to redistribute security-related document data, evaluation fixtures, third-party assets, or uploaded user documents.

---

<div align="center">

<img src="frontend/static/favicon.svg" alt="VIGILOX" width="54">

## VIGILOX

**Document Intelligence with Evidence, Validation and Human Oversight**

Built with<br>
**FastAPI · PostgreSQL · PaddleOCR · Groq · Docker**

<br>

[Back to Top](#vigilox)

</div>