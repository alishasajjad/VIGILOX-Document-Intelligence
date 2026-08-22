<div align="center">

# 🛡️ VIGILOX

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
[![Deployment](https://img.shields.io/badge/Deployment-Cloudflare_Tunnel-F38020?logo=cloudflare&logoColor=white)](#deployment)

<br>

[Overview](#overview) •
[Features](#key-features) •
[Architecture](#system-architecture) •
[Setup](#local-development) •
[API](#api-overview) •
[Testing](#testing) •
[Research](https://github.com/alishasajjad/VIGILOX-Document-Intelligence-Research) •
[Security](#security) •
[Deployment](#-deployment) •
[Documentation](#documentation)

</div>

---

## Overview

**VIGILOX** is a production-oriented Document Intelligence platform designed for processing security and identity-related documents using OCR, structured AI extraction, evidence validation, deterministic validation rules, durable background processing, and human review.

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
- maintain an audit history

VIGILOX is built around one core principle:

> **AI output should not become authoritative unless the supporting evidence and validation rules justify it.**

The platform combines machine intelligence with deterministic validation and human oversight instead of treating LLM output as unquestioned truth.

---

# Key Features

## Supported Documents

VIGILOX currently supports:

- Security Guard Licences
- ID Cards
- SIA Badges

Document type detection is automatic.

Unsupported or unrelated documents are handled separately and are never silently treated as valid supported credentials.

---

## Document Processing

VIGILOX provides:

- Browser-based image upload
- Single-document processing
- Batch processing
- JPG, JPEG, PNG and WEBP support
- Maximum upload-size validation
- Actual-byte validation
- Automatic document-type detection
- PaddleOCR-powered text extraction
- Groq-powered structured extraction
- Pydantic schema validation
- Original source-image preservation
- Structured machine-readable output
- Durable PostgreSQL-backed processing jobs
- Retry and provider-backoff handling
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

This makes extraction results auditable instead of presenting AI output as an unexplained black box.

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

For successfully persisted documents, the Review Workspace loads the source directly from:

```text
/api/v1/documents/{document_id}/image
```

The source document remains available independently of the structured extraction result.

---

## Image Quality Assessment

VIGILOX performs deterministic image-quality measurements.

Current findings include:

- `IMAGE_BLURRY`
- `IMAGE_UNREADABLE`
- `IMAGE_TOO_DARK`
- `IMAGE_OVEREXPOSED`
- `ROTATION_CONCERN`
- `IMAGE_TOO_SMALL`

Quality findings can make automatic processing more conservative.

For example:

```text
AUTO_ACCEPT
    ↓
REVIEW_REQUIRED
```

A quality finding can escalate a document for review but does not clear an existing review requirement.

---

## Confidence Interpretation

VIGILOX uses **field-level confidence** primarily to communicate OCR and evidence support.

Confidence is not treated as a calibrated probability that a semantic field is correct.

For example:

```text
OCR reads a date correctly
        ↓
Strong OCR confidence
        ↓
Extraction assigns it to the wrong field
```

A field can therefore have strong OCR support while still being semantically incorrect.

For this reason VIGILOX does not generate a misleading document-level confidence percentage.

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

Documents that cannot be safely accepted automatically are routed for human review according to the machine decision rules.

---

# Unsupported Documents

A successfully identified unsupported document is treated as a domain outcome rather than an infrastructure failure.

Typical result:

```text
Job Status:
COMPLETED

Document Type:
unknown

Supported:
false

Usable:
false

Effective Record:
none
```

Unsupported documents:

- cannot become automatically accepted supported records
- do not become usable final records
- remain represented as a completed processing outcome
- remain separate from normal supported-document decisioning

Quality assessment and document classification remain separate concerns.

---

# Duplicate Detection

VIGILOX computes a SHA-256 fingerprint over the original uploaded bytes.

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

The source fingerprint is not exposed through the normal public API or user interface.

---

# Batch Processing

VIGILOX supports both single-document and batch workflows.

## Single Document

```text
Select File
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
- Completed-document links
- Failure isolation

One invalid or failed file does not invalidate successful sibling files.

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

The browser does not act as the job queue.

---

## Job States

The durable job model uses:

```text
QUEUED
PROCESSING
RETRY_WAIT
COMPLETED
FAILED
```

`current_stage` provides processing context without displaying artificial progress percentages.

---

## Durable Worker Claims

Workers claim jobs using PostgreSQL row locking:

```sql
FOR UPDATE SKIP LOCKED
```

This allows multiple workers to compete safely for available jobs without processing the same queued job concurrently.

Worker leases are used for recovery when processing is interrupted.

---

## Retry Handling

Infrastructure/provider failures are handled separately from structured-output recovery.

Typical behavior:

```text
429 Rate Limit
→ RETRY_WAIT
→ Retry-After respected

5xx / Connection Failure
→ Job-level retry
→ Backoff

Malformed Structured Output
→ Bounded extraction recovery

Unsupported Document
→ Completed domain outcome
```

Retries are bounded.

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
- Image-quality information
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

Human corrections are applied as an overlay instead of rewriting the original machine extraction.

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

Dashboard values are calculated from PostgreSQL data.

The application does not generate fabricated fraud, tamper, risk, or document-confidence percentages.

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

Sensitive OCR contents and extracted personal values are intentionally excluded from global document search.

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

- PostgreSQL 18
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
- Cloudflare Quick Tunnel

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
│   ├── job_repositories.py
│   └── summary_repositories.py
│
├── migrations/
│   ├── env.py
│   └── versions/
│
├── frontend/
│   ├── pages/
│   └── static/
│       ├── css/
│       ├── js/
│       ├── favicon.svg
│       ├── favicon.ico
│       └── apple-touch-icon.png
│
├── tests/
│   ├── api/
│   ├── dashboard/
│   ├── deployment/
│   ├── e2e/
│   ├── integration/
│   ├── intelligence/
│   ├── jobs/
│   ├── real_dependencies/
│   ├── security/
│   ├── storage/
│   └── unit/
│
├── evaluation/
│   ├── archive/
│   ├── reports/
│   └── results/
│
├── scripts/
│   ├── development/
│   ├── evaluation/
│   ├── maintenance/
│   └── verification/
│
├── docs/
│   ├── api/
│   ├── architecture/
│   ├── deployment/
│   ├── evaluation/
│   ├── operations/
│   ├── release/
│   └── security/
│
├── docker/
│   ├── entrypoint.sh
│   └── nginx/
│
├── Dockerfile
├── docker-compose.yml
├── alembic.ini
├── requirements.txt
├── .env.example
├── .dockerignore
├── .gitattributes
├── .gitignore
├── LICENSE
└── README.md
```

---

# Local Development

## Prerequisites

Install:

- Python 3.13
- PostgreSQL
- Git

For the public tunnel:

- `cloudflared`

---

## 1. Clone the Repository

```bash
git clone https://github.com/alishasajjad/VIGILOX-Document-Intelligence.git
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

On Windows:

```powershell
Copy-Item .env.example .env
```

Configure required values.

Typical configuration:

```env
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:PORT/DATABASE
GROQ_API_KEY=your_groq_api_key
VIGILOX_GROQ_MODEL=openai/gpt-oss-20b
```

Development reviewer identity can be configured with:

```env
VIGILOX_REVIEW_IDENTITY_MODE=local_env
VIGILOX_LOCAL_REVIEWER_ID=local-reviewer
VIGILOX_LOCAL_REVIEWER_ROLE=REVIEWER
```

See `.env.example` for the complete configuration reference.

> Never commit `.env`, API keys, passwords, or real document data.

---

# Database Setup

Apply migrations:

```powershell
python -m alembic upgrade head
```

Check the current revision:

```powershell
python -m alembic current
```

Check model/schema drift:

```powershell
python -m alembic check
```

---

# Running VIGILOX Locally

The complete application uses:

```text
PostgreSQL
    +
FastAPI API
    +
Background Worker
```

## Terminal 1 — Start the API

```powershell
cd C:\path\to\VIGILOX-Document-Intelligence
.\.venv\Scripts\Activate.ps1

python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

For development with auto-reload:

```powershell
python -m uvicorn backend.app.main:app --reload
```

Local application:

```text
http://127.0.0.1:8000
```

---

## Terminal 2 — Start the Worker

```powershell
cd C:\path\to\VIGILOX-Document-Intelligence
.\.venv\Scripts\Activate.ps1

python -m backend.worker
```

The worker initializes the OCR pipeline and processes durable PostgreSQL jobs independently of browser sessions.

---

## Verify Local Health

```powershell
Invoke-WebRequest http://127.0.0.1:8000/health -UseBasicParsing
```

Expected:

```text
StatusCode : 200
```

---

# Web Interface

| Page | Route |
|---|---|
| Dashboard | `/dashboard` |
| Upload Document | `/upload` |
| Documents | `/documents` |
| Review Queue | `/review` |
| Document Workspace | `/review/{document_id}` |

Local examples:

```text
http://127.0.0.1:8000/dashboard
http://127.0.0.1:8000/upload
http://127.0.0.1:8000/documents
http://127.0.0.1:8000/review
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

Typical checks include:

- PostgreSQL
- Managed storage
- Service configuration
- Database connection capacity

Worker health is tracked independently.

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

The primary browser workflow uses asynchronous document jobs.

A synchronous analysis endpoint is also retained for compatibility.

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
- Controlled API error contracts

---

## Reviewer Identity

Development can use:

```env
VIGILOX_REVIEW_IDENTITY_MODE=local_env
```

Production reviewer identity support is implemented through trusted reverse-proxy headers.

Reviewer identity remains server-authoritative.

---

## Authorization

Reviewer actions are validated on the server.

Frontend visibility does not replace backend authorization.

---

## Browser Security

The application applies security controls including:

- Content Security Policy
- `X-Content-Type-Options`
- `X-Frame-Options`
- Referrer Policy
- Permissions Policy
- Cross-Origin Opener Policy

The frontend uses same-origin JavaScript, CSS, API, and document resources.

---

## CORS

The primary application is same-origin.

CORS is configurable for deployments where a different frontend origin is required.

---

## Rate Limiting

Upload endpoints include application-level rate-limiting support.

Nginx configuration is also included for deployment-level request controls.

---

# Storage Safety

Pending uploads and managed document storage are intentionally separated.

```text
Pending Job Storage
        ≠
Managed Document Storage
```

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

Operational logging avoids:

- OCR text
- extracted PII
- API keys
- database passwords
- reviewer correction contents
- managed filesystem paths

Examples of operational events include:

```text
worker.starting
worker.warmup_complete
job.retry_scheduled
job.completed
```

---

# Metrics

Operational metrics include areas such as:

- HTTP requests
- HTTP latency
- Job queue state
- Job completion/failure
- Worker activity
- OCR processing
- LLM processing
- Provider rate-limit events
- Batch outcomes
- Worker heartbeat

High-cardinality document identifiers and filenames are not used as metric labels.

---

# Worker Health

Worker health is tracked independently from API readiness.

Worker-health states include:

```text
HEALTHY
STALE
NO_WORKER
```

This keeps API availability and background-processing availability separate.

---

# Testing

VIGILOX contains:

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

Run the deterministic regression suite:

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

The `--exclude-real` mode separates deterministic tests from suites that require real external dependencies.

---

## Real Dependency Tests

When external provider quota and required dependencies are available:

```powershell
python scripts/verification/run_phase7c7g_regressions.py --only-real
```

These suites use real components including:

- PaddleOCR
- Groq API
- PostgreSQL

---

# Evaluation

VIGILOX includes an evaluation framework for comparing extraction output against labelled document fixtures.

Evaluation metrics include:

- Document-type accuracy
- Exact field accuracy
- Normalized field accuracy
- Known-field normalized accuracy
- Critical-field normalized accuracy
- Fully correct documents
- Machine decision distribution
- False automatic acceptance

A critical evaluation invariant is:

```text
False AUTO_ACCEPT = 0
```

Historical evaluation artifacts are archived alongside the evaluation framework.

---

## Historical Evaluation Baseline

Historical benchmark results include:

```text
Document type accuracy           100%
Exact field accuracy             95.92%
Normalized field accuracy        98.64%
Known-field normalized accuracy  98.49%
Fully correct documents          93.65%
False AUTO_ACCEPT                0
```

---

## Critical-Field Baseline Correction

An earlier evaluation metric maintained a separate critical-field definition and omitted the production-critical `issuer` field.

The earlier metric was:

```text
99.40% (167 / 168)
```

After aligning evaluation with the authoritative production definition:

```text
99.05% (208 / 210)
```

This was a metric-definition correction rather than a model regression.

---

# Performance

Measured architecture behavior showed that OCR is the dominant local processing cost.

Representative measurements include:

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

The asynchronous architecture improves API and browser responsiveness by moving OCR and extraction work into durable background processing.

---

# 🚀 Deployment

VIGILOX has been publicly deployed and tested using **Cloudflare Quick Tunnel**.

The deployed flow is:

```text
Internet
   ↓
Cloudflare Quick Tunnel
   ↓
FastAPI
   ↓
PostgreSQL
   ↑
Background Worker
   ↓
PaddleOCR + Groq
```

Cloudflare creates an HTTPS `trycloudflare.com` address for the running application.

The generated URL is intentionally not stored in this README because a tunnel session creates its own address.

---

## Verified Deployment Flow

The public deployment was tested through this complete workflow:

```text
Public HTTPS Access
        ↓
Dashboard
        ↓
Document Upload
        ↓
Durable Job
        ↓
Background Worker
        ↓
PaddleOCR
        ↓
Groq Extraction
        ↓
Validation
        ↓
PostgreSQL Persistence
        ↓
Document Workspace
        ↓
Original Document
        ↓
Evidence Highlighting
        ↓
Human Review
        ↓
Final Record
        ↓
Audit History
```

The public tunnel was used to verify:

- Dashboard
- Upload Document
- Documents
- Review Queue
- Document Workspace
- OCR processing
- Structured extraction
- Original-document rendering
- Evidence highlighting
- Human review
- Final-state persistence
- Audit information

---

# Running the Cloudflare Deployment

Before starting the public tunnel, make sure PostgreSQL is running.

Three terminals are then used.

## Terminal 1 — API

```powershell
cd C:\path\to\VIGILOX-Document-Intelligence
.\.venv\Scripts\Activate.ps1

python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

---

## Terminal 2 — Worker

```powershell
cd C:\path\to\VIGILOX-Document-Intelligence
.\.venv\Scripts\Activate.ps1

python -m backend.worker
```

---

## Terminal 3 — Cloudflare Tunnel

Using the 64-bit Windows `cloudflared` executable:

```powershell
cd $env:USERPROFILE\Downloads

.\cloudflared-windows-amd64.exe tunnel `
  --protocol http2 `
  --url http://127.0.0.1:8000
```

Cloudflare prints a generated HTTPS address similar to:

```text
https://generated-name.trycloudflare.com
```

Use that generated address to open VIGILOX.

For example:

```text
https://generated-name.trycloudflare.com/dashboard
https://generated-name.trycloudflare.com/upload
https://generated-name.trycloudflare.com/documents
https://generated-name.trycloudflare.com/review
```

The API, worker, PostgreSQL, and Cloudflare tunnel remain running while the demonstration environment is being used.

---

# Docker Configuration

The repository also includes:

- `Dockerfile`
- `.dockerignore`
- `docker-compose.yml`
- Nginx configuration
- API role
- Worker role
- Migration role
- PostgreSQL configuration
- Managed-storage configuration
- Pending-storage configuration

The same application image supports roles such as:

```text
api
worker
migrate
```

This keeps application code aligned across deployment responsibilities.

---

# Database Migrations

Apply migrations with:

```bash
alembic upgrade head
```

Verify:

```bash
alembic current
alembic check
```

---

# Backup & Restore

Operational backup and restore tooling is included for:

- PostgreSQL
- Managed document storage
- Pending job source storage

Documentation:

```text
docs/operations/backup-restore.md
```

---

# Graceful Shutdown

The API and worker include controlled shutdown behavior.

The worker can:

- stop claiming new jobs
- preserve durable job state
- release database resources
- allow interrupted work to recover according to lease rules

---

# Troubleshooting

## API Does Not Start

Check:

```powershell
python -m alembic current
python -m alembic check
```

Verify the configured:

```text
DATABASE_URL
```

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

Jobs can enter:

```text
RETRY_WAIT
```

Typical flow:

```text
PROVIDER_RATE_LIMITED
→ RETRY_WAIT
→ bounded retry
```

When all configured attempts are exhausted:

```text
FAILED
ATTEMPTS_EXHAUSTED
```

may be returned.

---

## Cloudflare Tunnel Does Not Start

Confirm the API first:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/health -UseBasicParsing
```

Check Cloudflare connectivity:

```powershell
Test-NetConnection api.trycloudflare.com -Port 443
Test-NetConnection region1.v2.argotunnel.com -Port 7844
```

If required:

```powershell
ipconfig /flushdns
```

Then start the tunnel again:

```powershell
.\cloudflared-windows-amd64.exe tunnel `
  --protocol http2 `
  --url http://127.0.0.1:8000
```

---

## Original Document Does Not Display

Test:

```text
/api/v1/documents/{document_id}/image
```

The Review Workspace loads the source image from this same-origin endpoint.

---

## Evidence Does Not Render

Confirm:

- the original source image loaded
- image dimensions are available
- evidence display is enabled
- OCR evidence IDs exist for the selected field

---

# Design Principles

## Evidence Before Trust

AI output should be backed by source evidence.

## Fail Closed

Ambiguous outcomes must not silently become usable final records.

## Immutable Machine Extraction

Human corrections do not rewrite historical machine output.

## Durable Processing

Browser sessions are not job queues.

## PostgreSQL as the System of Record

Documents, jobs, analysis, reviews, and audit history remain durable.

## No Invented Intelligence

VIGILOX does not generate unsupported:

- fraud probabilities
- tamper probabilities
- AI risk percentages
- document-level confidence percentages

## Human Oversight Where Uncertainty Matters

Automation reduces reviewer workload while preserving reviewer authority.

---

# Known Limitations

- OCR processing is CPU-bound.
- External AI processing depends on provider availability and quota.
- Image-quality thresholds are calibrated on the available evaluation corpus.
- OCR/evidence confidence does not measure semantic field-assignment correctness.
- Some historical test records created before managed-source persistence may not contain an original source image.
- The Cloudflare deployment runs through the local VIGILOX services and PostgreSQL environment.

---

# Documentation

Additional technical and operational documentation is maintained under:

```text
docs/
├── api/
├── architecture/
├── deployment/
├── evaluation/
├── operations/
├── release/
└── security/
```

Important documents include:

```text
docs/architecture/overview.md
docs/deployment/deployment.md
docs/evaluation/evaluation.md
docs/operations/backup-restore.md
docs/operations/monitoring.md
docs/operations/production-runbook.md
docs/operations/shutdown.md
docs/release/v1-production-readiness.md
docs/security/security.md
```

---

# 💻 Developer

### ALISHA SAJJAD

**AI Engineer · Python Developer · Generative AI & Agentic Systems Enthusiast**

Developed and engineered the VIGILOX Document Intelligence platform, including its OCR pipeline, AI extraction workflow, evidence validation system, durable processing architecture, human review workflow, production-oriented backend, and web interface.

**GitHub:**

[github.com/alishasajjad](https://github.com/alishasajjad)

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

Use synthetic or properly authorized documents for development and testing.

---

# 🔬 Research Repository

For detailed experiments, evaluation methodology, engineering decisions, and phase-by-phase technical notes, visit the dedicated research repository:

**[VIGILOX Document Intelligence Research](https://github.com/alishasajjad/VIGILOX-Document-Intelligence-Research)**

--- 

# License

VIGILOX is open-source software licensed under the [MIT License](LICENSE).

You are free to use, modify, and distribute the software in accordance with the terms of the license.

**Copyright © 2026 Alisha Sajjad**
---

<div align="center">

## 🛡️ VIGILOX

**Document Intelligence with Evidence, Validation and Human Oversight**

Built with<br>
**FastAPI · PostgreSQL · PaddleOCR · Groq · Docker**

<br>

**Developed by ALISHA SAJJAD**

<br>

[⬆ Back to Top](#️-vigilox)

</div>
