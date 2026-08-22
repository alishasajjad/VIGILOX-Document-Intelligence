# API Reference

Sixteen documented routes plus five HTML pages and a favicon. The
generated OpenAPI document is authoritative for schemas; this page is the
narrative — what each route is *for*, and which ones you should not use.

The interactive documentation (`/docs`, `/redoc`, `/openapi.json`) is
enabled in the application and **denied by the production proxy**:
together they are the whole route surface, every schema and every field
name, plus a form for calling each route.

## The route surface

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/document-jobs` | **upload one document** (the production path) |
| GET | `/api/v1/document-jobs/{job_id}` | poll one job |
| POST | `/api/v1/document-batches` | upload many documents |
| GET | `/api/v1/document-batches/{batch_id}` | poll a batch, per-file |
| GET | `/api/v1/documents` | list documents |
| GET | `/api/v1/documents/{document_id}` | the full analysis |
| GET | `/api/v1/documents/{document_id}/image` | the source image |
| GET | `/api/v1/documents/{document_id}/history` | audit history |
| POST | `/api/v1/documents/{document_id}/reviews` | submit a review decision |
| GET | `/api/v1/reviews/queue` | what needs a human |
| GET | `/api/v1/dashboard/summary` | dashboard aggregates |
| GET | `/api/v1/reviewer/me` | who the server thinks you are |
| POST | `/api/v1/documents/analyze` | **legacy synchronous** — see below |
| GET | `/health` | liveness |
| GET | `/health/ready` | readiness |
| GET | `/health/workers` | is anything draining the queue |

Business resources are versioned under `/api/v1/`. The three probes are
deliberately **not** versioned: they are infrastructure, and an
orchestrator's liveness probe should not have to know the API version.

## The normal flow

```
POST /api/v1/document-jobs          multipart file
  -> 202 Accepted  {job_id, status: "QUEUED"}

GET  /api/v1/document-jobs/{job_id}
  -> 200 {status: "PROCESSING", stage: "OCR"}
  -> 200 {status: "COMPLETED", document_id: "..."}

GET  /api/v1/documents/{document_id}
  -> 200 the analysis, findings, decision, final record
```

**202, not 200.** The upload is accepted, not completed. The work happens
in a worker, and a 200 would imply the analysis was ready.

Poll the job endpoint, not the document endpoint: the `document_id` does
not exist until the job completes.

### Polling rate

The proxy deliberately applies **no rate limit** to the catch-all that
serves job status, because limiting it makes a working upload look hung
to the async UI. Poll at a sensible interval anyway — a document takes
tens of seconds, so once or twice a second is already generous.

## `POST /api/v1/documents/analyze` — legacy, and why it stays

Synchronous. It runs the whole pipeline inside the request and returns
the analysis directly.

**Retained deliberately for backward compatibility.** It is not dead code
and must not be removed in a cleanup pass. It is also not the path the
product uses, and it has real limitations:

- The request blocks for the full pipeline — a 28 s median, 43 s maximum
  for OCR alone, and a measured worst case of 268 s for the whole
  pipeline. Behind any normal proxy timeout, that is a failed request for
  a document that processed fine.
- It holds a request thread for the duration, so a handful of concurrent
  calls can consume the API's admitted concurrency.
- **Its exact-duplicate behaviour is intentionally different.** It
  records source fingerprints, but the short-circuit guarantees —
  `DUPLICATE_DOCUMENT`, `DUPLICATE_IN_PROGRESS`, and the partial unique
  index that makes the concurrent case race-free — belong to the async
  job path. Do not assume the two paths behave identically here; they do
  not, and that is a decision rather than an oversight.
- If the API is running with lazy OCR (the production default) the first
  call after a restart pays the model load.

New integrations should use `POST /api/v1/document-jobs`.

## Response shapes

### `GET /api/v1/documents/{document_id}`

Eight top-level keys, and **no `response_model`** on this route — on
purpose. Pydantic's `response_model` *filters* a response: any key not
declared in the model is silently dropped. Attaching one here would have
quietly deleted the `findings` block the day it shipped, with no error
anywhere. There is a test asserting the live response carries all eight
keys for exactly this reason.

```
document          identity, type, timestamps
analysis          extracted fields, per-field confidence, evidence
classification    document type and whether it is supported
duplicate         source-identity outcome, if any
findings          the normalized envelope (below)
decision          AUTO_ACCEPT / REVIEW_REQUIRED, priority
review            the human decision, if one exists
final_record      the effective values after any correction
```

### The findings envelope

One shape, five categories, three severities — and the domain detail is
preserved rather than flattened into a lowest common denominator.

```
findings.findings[]      each: code, category, severity, message,
                         field, source, plus its own domain fields
findings.counts          per severity
findings.categories      per category
findings.highest_severity
findings.quality_assessed   null | true | false   <- three states, see below
findings.total
```

**`quality_assessed` has three meaningful states and they must not be
collapsed:** `null` means quality was *not assessed*; `true` with zero
quality findings means *assessed and clean*; `true` with findings means
*assessed and flagged*. "Not assessed" and "assessed, nothing found" are
different facts about the document.

Each finding keeps what only it has — a quality finding its measured
value and threshold, an evidence finding its OCR line ids and support
state, an expiry finding the date and days remaining.

There is deliberately **no** risk score, fraud score, tamper score, or
overall document confidence.

### Per-field confidence

Present on every extracted field, and it means **OCR and evidence support
strength** — not the probability that the value is correct.

Measured across 441 fields: correct fields averaged 0.997, *incorrect*
fields averaged 0.9996, AUC 0.362. A semantically wrong value can carry
very high confidence, because the OCR evidence for the wrong text is
perfectly good. Do not surface it as certainty and do not gate on it.

## Errors

A stable envelope on every failure:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Not found.",
    "request_id": "..."
  }
}
```

The code is machine-readable and stable; the message is safe. Neither
ever contains OCR text, an extracted value, a filename, a stack trace, or
a database error string.

`request_id` is generated by the server on every request and appears on
every log line for that request — quote it in a bug report. A
client-supplied `X-Request-ID` is sanitised and kept separately as a
non-authoritative tracing value; it never becomes the authoritative id.

Security headers are present on error responses and on 429s, not only on
200s.

## Identity

```
GET /api/v1/reviewer/me   ->  who the server thinks you are
```

The browser is **never** authoritative. Identity comes from
`X-VIGILOX-REVIEWER-ID` / `X-VIGILOX-REVIEWER-ROLE`, which the proxy
strips from the client and re-injects, and which the application believes
only from a peer listed in `VIGILOX_TRUSTED_PROXIES`.

A `reviewer_id` in a review request body is accepted for backward
compatibility and **deliberately ignored**.

Roles: `VIEWER` (read), `REVIEWER` (read + review), `ADMIN`. Checks are
server-side; the UI hiding a button is a courtesy, not the control.

**One review per document**, enforced by a database unique constraint
rather than an application check — a constraint cannot be raced.

## Uploads

| | |
|---|---|
| Accepted types | JPEG, PNG, WEBP |
| Size limit | 10 MiB, counted from **actual streamed bytes** — `Content-Length` is not trusted |
| Filename | metadata only; it never becomes a path |
| Empty body | refused |

Storage paths derive from the validated document id
(`^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$`), which admits no separator, no
`..`, no drive letter and no absolute path.

## Not in the OpenAPI document

Served, but hidden — and each one is declared in a test, because
`include_in_schema=False` hides a route from review as effectively as it
hides it from the document.

```
/dashboard  /upload  /documents  /review  /review/{document_id}   HTML pages
/favicon.ico                                                      browser chrome
/metrics                        Prometheus; off in production unless enabled
/docs  /redoc  /openapi.json    framework docs; denied by the proxy
/review/static/                 the static mount
```
