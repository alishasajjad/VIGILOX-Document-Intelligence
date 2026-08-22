# VIGILOX Document Intelligence — v1 Production Readiness

**Status: development complete. The next action is deployment.**

This is the authoritative release document. Where a number appears here it
was measured, and where something is unverified it says so.

---

## 1. Release decision

| | |
|---|---|
| Software, configuration and test suites | ✅ complete |
| Deployment package | ✅ ready for server build |
| Deterministic gate | ✅ **71 / 71 suites — FAILED 0, BLOCKED 0, MISSING 0** |
| Real-provider gate | ⛔ **6 suites not run — no Groq allowance left today.** Running it would compete with the evaluation for the same exhausted window |
| 63-document evaluation | ⛔ **57 / 63 — EXTERNAL_BLOCKED on Groq tokens-per-day.** All six shortfalls are HTTP 429, nothing else. Progress preserved, resumes without re-scoring. See §12 |
| **False AUTO_ACCEPT** | **not yet determinable** — requires 63/63. Release-critical: it must be 0 before release |
| Local Docker image build | ⚠️ **UNVERIFIED** — Docker is not installed in the development environment |
| Real-browser visual pass | ⚠️ needs a human look — see §17 |

**Decision: the software is ready. The release gate is NOT yet satisfied.**

Two of the three outstanding items are environment limitations, not code
defects — the Docker build and the visual pass. Every container artifact
is statically validated and every command is written down; nothing in the
application is waiting on them.

The third is a genuine gate and it is not optional:

> **The 63-document evaluation must reach 63/63 and false AUTO_ACCEPT
> must be 0 before this release ships.**

It stopped at 57/63 because the Groq daily allowance ran out mid-run, not
because anything failed — every one of the six shortfalls is a
`RateLimitError` 429, with no assertion, import or file error among them. Resume when the allowance resets, confirm the
numbers against the baselines in §12, and only then treat this document
as a release approval.

---

## 1b. The gate, in full

```
MODE: STANDARD (no real dependencies)
PASSED  : 71
FAILED  : 0
BLOCKED : 0
MISSING : 0

SKIPPED : 6 test(s) not executed in this mode:
  - REAL DEPENDENCY TESTS (6 tests)
  This run is NOT the full release gate.
```

**71 + 6 = 77**, which matches the 77 test files on disk exactly — that
equality is now asserted by `tests/deployment/test_phase12_test_coverage.py`
rather than assumed. Two further files sit in `tests/legacy/`, excluded
with a written reason.

The runner labels its own output *"Full release gate not yet proven"* when
real dependencies are skipped. That label is why this section can be
trusted: the tool refuses to overstate what it ran.

### The real-dependency group

Six suites, roughly 6,400 Groq tokens each. **Not run**, and not reported
as blocked-by-attempt either, because attempting it now would draw from
the same rolling allowance the 63-document evaluation needs to finish —
and the evaluation is the release-critical item.

```bash
# when the allowance has reset, and after the evaluation completes
python scripts/verification/run_phase7c7g_regressions.py --only-real
```

Four of these six had **never been executed by any runner** before this
cycle. See §2.

---

## 2. What was found and fixed in this cycle

Listed first because it is the part that matters most for judging
release risk. All of these were found by tests written during Phase 11
and 12 — none by luck.

### A real security vulnerability

**`trusted_headers` mode trusted reviewer identity headers without
verifying the request source.** Any client able to reach the backend
could name itself `ADMIN`, approve documents, and write audit entries
under any identity it chose — with the audit trail recording the
impersonated name, which is what makes it serious rather than merely
wrong. Auditing afterwards would show a plausible reviewer approving
things.

Fixed by restricting trusted headers to peers configured in
`VIGILOX_TRUSTED_PROXIES`, verified in both directions (accepted from a
configured address, refused from an unconfigured one). Production now
**refuses to start** in this mode without a proxy configuration.

The general lesson: *a header is only as trustworthy as the hop that set
it*, and "it is behind a proxy" is a deployment assumption until the
application checks.

### Middleware ordering

Security headers were **absent from 429 responses**. The rate limiter
answers without calling through, so a response built inside it never
reached the header middleware. Found by a test that checks headers on a
rate-limited response rather than only on a 200.

### Pool and threadpool disagreement

The API admitted 40 concurrent requests against 15 servable database
connections. The surplus did not queue — it timed out waiting for a
connection and returned 500 from a perfectly healthy database. Both
numbers now derive from `VIGILOX_REQUEST_CONCURRENCY`, and the failure
mode is queueing.

### The API never released its connection pool

Deleting service objects does not close pooled connections; the engine
outlives them. Each replica exited with up to 20 sockets open, which
PostgreSQL notices only on its next read — so a rolling deploy was
briefly charged for two replicas' connections against a `max_connections`
sized for one. The failure would present as `FATAL: sorry, too many
clients already` during a deploy that changed nothing about load.

### The worker could not be stopped on Windows

The main thread blocked in an untimed `thread.join()`. Signals are
delivered to the main thread, and the handler is what sets the stop
event — so on Linux the interruptible lock acquire works, but on Windows
it deadlocks. Measured: `STATUS_CONTROL_C_EXIT`, document abandoned. A
bounded join fixes it on every platform, and `SIGBREAK` is now
registered alongside `SIGTERM` and `SIGINT`.

### A layering inversion

`ReviewerIdentityService` imported upward into `backend/app/api/` — the
only inversion in the repository. "Is this peer trusted" is a question
about the network, not about HTTP, so the definitions moved to
`backend/app/core/trusted_peers.py`, below both callers. The structure
audit now reports zero.

### A timing-dependent test that lied about its subject

`test_phase9_concurrency_load.py` drained everything its shared harness
had ever created rather than the jobs under test. An earlier test parks
five jobs with a backoff; once the backoff elapsed the worker
legitimately claimed 8 + 5 = 13 and the assertion failed with *"status
reads are interfering with claiming"* — which had nothing to do with it.
It passed on a fast machine and failed under gate load. Both drains are
now scoped to their own jobs.

### Documentation that named a flag that does not exist

The runbook told an operator to run `reconcile_storage.py --report`. The
script has no such flag; its dry run is the default. An invented flag is
worse than an invented path — a path fails obviously, while a plausible
flag makes an operator doubt their own typing during an incident. Fixed,
and the documentation test now verifies **flags** against each script's
own argparse definitions, with a self-check proving the detector can
still fail.

### The deployment validator read three keys that do not exist

Written in 11.15, and its first real run against a live instance produced
four failures of which **three were its own bugs**:

- it looked for `capacity.database_connections_per_process`; readiness
  publishes `max_connections_per_process`. So it always took the
  not-reported branch and announced *"this deployment predates Phase
  11.2"* about a deployment that did not.
- it read `state` from `/health/workers`; the route publishes `status`.
  `None` then fell through to the stranded-work branch, so it reported
  the paging condition on every single run.
- it accepted `--expect-public` and then **ignored it**, failing on
  `/metrics` and `/docs` answering at an *internal* address — which is
  exactly who they are for.

A validator that cries wolf is worse than no validator: it teaches an
operator to stop reading the output. Fixed; the same run now reports
9 PASS, 2 WARN (correctly, for an internal probe), 1 SKIP, and one
genuine FAIL — `NO_WORKER` with queued work, which is true of this
machine.

### The residue cleanup script would have deleted real uploads

`clean_test_residue.py` identifies test rows **by filename**, and three of
its patterns are `guard_license.jpg`, `id_card.jpg` and `sia_badge.jpg` —
the sample filenames. Anyone trying the product uploads exactly those, so
a genuine upload and a test row are indistinguishable in the row itself.

Its report listed 25 candidates, two of which were real documents. There
is no marker that could separate them, and adding one would put test
awareness into production code. So the guard is procedural: `--delete`
now refuses unless given `--id` (only ids that appear in the report) or
`--all-candidates`, and the report names which candidates are matched
*only* by a sample filename.

### An evaluation metric measuring the wrong thing

See §12. The critical-field baseline was corrected from 99.40% (167/168)
to **99.05% (208/210)** — same predictions, correct denominator.

---

## 3. Final repository structure

```
backend/
  app/
    api/        HTTP surface: routes, middleware, schemas, rate limit
    core/       cross-cutting: logging, timing, paths, trusted_peers
    domain/     vocabulary: findings, duplicates, job_states
    services/   the work: pipeline, extraction, evidence, persistence,
                worker, metrics, health, storage, identity
  worker.py     the worker entrypoint
database/       models, engine/pool, repositories
migrations/     Alembic; owns the schema
frontend/
  pages/        five HTML pages
  static/       css/ design system, js/ modules, favicon assets
docker/
  entrypoint.sh one image, three roles
  nginx/        proxy config + tls/ (empty, gitignored)
docs/
  api/ architecture/ deployment/ evaluation/ operations/
  release/ security/ phases/
evaluation/     corpus, ground truth, results, archived reports
scripts/
  development/  studies and benchmarks
  evaluation/   runner and metrics
  maintenance/  backup, restore, reconcile, purge
  verification/ regression runner, structure audit, deployment validator
tests/          unit, integration, api, security, storage, jobs,
                dashboard, intelligence, deployment, e2e,
                real_dependencies
storage/        runtime business data, never packaged
output/         generated, never packaged
```

**Layering rule:** `api → services → database`, with `core/` and
`domain/` available to all. Zero inversions, asserted by
`scripts/verification/audit_repository_structure.py`.

`database/` may import `backend/app/domain/` — that is the deliberate
exception, so a repository and a model can agree on the job-state
vocabulary without either owning it.

---

## 4. Architecture

Five containers from **one image**. The API, worker and migration step
run different commands against the same build, so their dependencies and
code cannot drift apart.

```
internet → proxy (nginx, the only published port)
             → api (uvicorn, no published port)
                  → postgres (rows AND the durable queue)
                  → managed documents volume
                  → pending uploads volume
           worker (no ports at all) → postgres, volumes, Groq (outbound)
           migrate (same image, alembic upgrade head, exits)
```

Full diagram and rationale:
[docs/architecture/overview.md](../architecture/overview.md).

**No Redis.** The queue is PostgreSQL: a job row and the document row it
produces commit in the same transaction, which a separate broker cannot
give you. Adding one would mean another thing to run, back up and reason
about, in exchange for losing that.

---

## 5. API

Sixteen documented routes. Business resources under `/api/v1/`; the three
probes deliberately unversioned, because an orchestrator's liveness probe
should not have to know the API version.

Reference: [docs/api/api.md](../api/api.md).

Two decisions worth recording:

- **`GET /api/v1/documents/{id}` carries no `response_model`.** Pydantic's
  `response_model` *filters* a response — undeclared keys are silently
  dropped. Attaching one would have quietly deleted the `findings` block
  the day it shipped, with no error anywhere. A test asserts all eight
  top-level keys are present in the live response.
- **`POST /api/v1/documents/analyze` is retained** for backward
  compatibility and is **not** semantically identical to the async path:
  it records source fingerprints, but the exact-duplicate short-circuit
  guarantees belong to the job API. Documented rather than papered over.

---

## 6. Worker, jobs and batches

```
QUEUED → PROCESSING → COMPLETED
              ↓
          RETRY_WAIT → PROCESSING → …
              ↓
            FAILED
```

Stages: `READING`, `OCR`, `EXTRACTING`, `VALIDATING`, `PERSISTING`.
Batch statuses add `COMPLETED_WITH_FAILURES`.

- Claim: `SELECT … FOR UPDATE SKIP LOCKED`, with the `RETRY_WAIT` backoff
  comparison **inside the query** so a worker cannot ignore it.
- Claimable statuses derive from `CLAIMABLE_STATUSES` rather than string
  literals; a test puts a job in every status and asserts which come back.
- Lease 360 s. A worker that dies leaves the job `PROCESSING`;
  `reclaim_expired` returns it to `QUEUED` and **the abandoned attempt
  still counts**, so a document that repeatedly kills the worker fails as
  `ABANDONED` rather than retrying forever.
- **One bad file does not fail a batch.** Successful siblings stay
  successful and the summary distinguishes them.

---

## 7. Duplicates and unsupported documents

**Exact duplicate** — sha256 of the source bytes.
`DUPLICATE_DOCUMENT` (already completed) and `DUPLICATE_IN_PROGRESS`
(already active). The short-circuit happens **before** OCR and before the
provider. The concurrent case is protected by a PostgreSQL **partial
unique index**, not an application check — a constraint cannot be raced.

A duplicate is a **source-identity outcome**, never presented as fraud,
tamper or suspicion.

**Unsupported** — a first-class domain outcome, not an error. The job
reaches `COMPLETED` (the pipeline worked), it is non-retryable, the record
is **never** `AUTO_ACCEPT`, it does not become Review Queue noise, and the
UI explains why.

---

## 8. Confidence calibration — the conclusion that must not be softened

Measured across 441 fields:

```
range                       ~0.944 → 0.999999
mean over CORRECT fields    0.997323
mean over INCORRECT fields  0.999606     ← higher
AUC                         0.362        ← worse than chance
```

**Incorrect fields scored slightly higher than correct ones.** Confidence
measures how well OCR and the evidence support the text extracted. When
the model maps a correctly-read string to the wrong field, the evidence
for that string is excellent — so confidence is high and the value is
wrong.

Therefore confidence is **not** the probability a field is correct, not
AI certainty, not semantic accuracy, and there is deliberately **no
document-level confidence score**. It is a legitimate signal about
OCR/evidence support strength, which is what it measures.

**High confidence does not make an error harmless.**

---

## 9. Findings model

One envelope, five categories (`QUALITY`, `EVIDENCE`, `ANOMALY`, `DATE`,
`EXPIRY`), three severities (`ERROR`, `WARNING`, `INFO`) — with
domain detail preserved rather than flattened.

Normalization is a **backend** service. Business authority does not live
in JavaScript; the frontend holds human labels only.

**`quality_assessed` has three states and they are not collapsed:**
`null` = not assessed, `true` with zero findings = assessed and clean,
`true` with findings = assessed and flagged. "Not assessed" and
"assessed, nothing found" are different facts.

No risk score, fraud score, tamper score, or overall document
confidence — deliberately.

---

## 10. Security posture

Full detail: [docs/security/security.md](../security/security.md).

| | |
|---|---|
| Identity | proxy strips + injects; application believes only trusted peers |
| Production posture | refuses to start on `local_env` or `trusted_headers` without proxies |
| Authorization | `VIEWER` / `REVIEWER` / `ADMIN`, server-side |
| One review per document | database unique constraint, not an app check |
| Rate limiting | proxy authoritative; **application limiter is process-local and says so** |
| Security headers | on success, errors **and 429s** |
| CORS | wildcard **rejected**; same-origin default |
| Uploads | allow-listed MIME, 10 MiB from streamed bytes, filename never a path |
| Output | `textContent` only; no `innerHTML` assignment anywhere |
| Logs | strict allowlist, closed `log_event` signature, access log off |
| Metrics | no id, filename, reviewer or OCR text in any label; route templates only |
| Not exposed | `/docs`, `/redoc`, `/openapi.json` denied; `/metrics`, `/health/workers` private-range only |

---

## 11. Database, migrations and pooling

Alembic owns the schema; there is **no `create_all` in production**.
Seven tables plus the partial unique index.

Verified rather than assumed:

- upgrade from an **empty** database, then a second autogenerate produced
  **0 operations**
- `alembic check` clean
- downgrade to base leaves only `alembic_version`; upgrade rebuilds
  everything
- the partial index proven **partial**: a second active job for the same
  source is refused, and accepted once the earlier job completes
- expected tables **derived from the models**, not typed out — so a model
  added without a migration fails here

Pool, per process: `REQUEST_CONCURRENCY=20`, `POOL_SIZE=10`,
`MAX_OVERFLOW=10`, `max_connections_per_process=20`, timeout 10 s,
recycle 1800 s, `pool_pre_ping` on. Admitted concurrency and servable
connections derive from one number.

---

## 12. Final 63-document evaluation

Critical fields come from the **production** definition
(`DocumentAnomalyValidator.CRITICAL_FIELDS`), imported rather than
duplicated, with a test asserting the two agree.

### The baseline correction

Historical reports quote **99.40% (167/168)** for critical-field
normalised accuracy. **That figure is superseded.** It used an
evaluation-only list that omitted `issuer`, which production treats as
critical. On the **same predictions**, the production definition gives:

```
CORRECTED CRITICAL NORMALISED BASELINE:  99.05%  (208 / 210)
```

**No prediction changed and nothing got worse.** A denominator that was
too narrow was replaced by the correct one, and an error already
happening is now counted. This is a metric-definition fix, **not** a
model regression — and both facts are preserved here deliberately.

### Results — INCOMPLETE, blocked on provider quota

**57 of 63 documents scored. The final evaluation is NOT complete, and
this report does not claim it is.**

```
Groq on-demand tokens per day:  200,000
used at the point of refusal:   196,625
requested for the next document:  4,512  (later documents: ~6,100)
```

Six documents remain, all ID cards:

```
id_015  id_016  id_017  id_018  id_020  id_021
```

`id_019` completed during the retry loop as the rolling window freed
capacity, which is why the count is 57 rather than 56. Roughly 30,000
tokens of allowance are needed to finish the rest.

**Every one of the six is a `RateLimitError` 429.** Not an assertion, not
an `ImportError`, not a `FileNotFoundError`. That distinction is the whole
point of classifying a quota refusal separately from a failure: it says
the code was never the problem.

**What was preserved.** Every one of the 56 successful predictions is on
disk in `evaluation/results/predictions.jsonl`. Nothing was reset. The
runner records a `status: "failed"` row for a blocked sample and
`get_completed_sample_ids` counts only `status: "success"`, so a resume
retries exactly the seven that are missing and re-scores nothing that
already succeeded.

**Extraction logic was not touched.** A 429 on tokens-per-day is a quota
signal, not a correctness signal. Changing prompts, models, retry counts
or field handling in response to one would corrupt the very comparison
the run exists to make.

### How to finish it

When the allowance resets:

```bash
python -m scripts.evaluation.evaluation_runner    # resumes; do NOT pass --reset
python -m scripts.evaluation.evaluation_metrics
```

`evaluation_metrics` deliberately refuses to score a partial run. Run
against the current 57 it raises:

```
RuntimeError: Missing successful predictions for:
  id_015, id_016, id_017, id_018, id_020, id_021
```

rather than reporting metrics over 57 documents as though they were 63.
That refusal is correct, it was verified rather than assumed, and it is
why no accuracy percentage appears in this section.

### The one number that can be stated

The critical-field **denominator** is confirmed independently of the run:
21 SIA badges × 4 critical fields + 21 guard licences × 4 + 21 ID cards ×
2 = **210**, matching the production definition including `issuer`. That
is the corrected baseline's denominator, and it is arithmetic rather than
measurement.

The numerator, and therefore every accuracy figure and the
false-AUTO_ACCEPT count, requires 63/63.

### Release-critical

**FALSE AUTO_ACCEPT MUST REMAIN 0.** A false AUTO_ACCEPT is a document
with a wrong critical field accepted without a human looking at it — the
one failure mode with no downstream check.

---

## 13. Performance

Preserving the Phase 9 conclusion precisely:

**Async improved request responsiveness. It did not make OCR processing
faster.** The work moved off the request path; it did not shrink.

```
OCR                   28 s median, 43 s maximum per document
extraction            1.18 s median, 25.31 s maximum
extraction worst      220 s
pipeline worst        268 s
lease                 360 s
job-system throughput ~90 jobs/s with an injected pipeline
                      (NOT a document-processing rate)
API eager OCR start   2929 ms
API lazy OCR start    3 ms
```

Load figures use an injected pipeline deliberately — burning provider
quota to measure queue mechanics would measure the provider, not the
queue.

---

## 14. Backup, restore and shutdown

**Backup** is database-first, then filesystem. An upload concurrent with
a hot backup restores as an orphan file (reconciliation clears it); the
reverse order restores a row pointing at nothing. Neither order is
consistent — this one is wrong in the recoverable direction.
`--quiesced` gives a genuinely consistent pair and is recorded as an
operator claim, with the script refusing if it finds evidence against it.

**Restore** verifies checksums before writing anything, and refuses: an
incomplete manifest, a checksum mismatch, a populated target without
`--force`, overlapping storage roots, a schema-revision mismatch, and an
archive member that escapes its destination.

Proven by a **real round trip** on synthetic data that deletes the
originals first and then asserts the pairing using the application's own
integrity scan.

**Shutdown** — api 30 s grace, worker 400 s against a measured 268 s
worst case and a 360 s lease. A worker killed hard leaves its job
`PROCESSING`, never `COMPLETED`: only the process that did the work knows
what happened, and a completion written on its behalf is permanent and
indistinguishable from success.

---

## 15. Observability

`/health` liveness, `/health/ready` readiness, `/health/workers` alert
only, `/metrics` Prometheus.

**`/health/workers` is deliberately not readiness.** The API serves
correctly with no worker — uploads queue — so failing readiness would
turn a worker problem into an API outage. The signal worth paging on is
`queue_waiting_with_no_worker`: the outage where every other check is
green and nothing is processed.

Worker states distinguish `STALE` (died) from `NO_WORKER` (never
started) — different cause, different fix, identical if all you have is
"no recent heartbeat". Heartbeats are written from **inside** the run
loop, so a container that is up but wedged writes nothing.

**No monitoring stack ships.** No Prometheus, Grafana or Alertmanager is
in this repository. Alert expressions are recommendations in
[docs/operations/monitoring.md](../operations/monitoring.md).

---

## 16. Container and deployment validation

**Docker is not installed in the development environment. The image has
never been built.** That is stated plainly and is not labelled as tested.

Statically validated:

- Dockerfile: two stages, non-root uid/gid 10001, models baked at build
  time (so a container start needs no network), `0750` on the document
  directories
- `.dockerignore`: the check **applies the real ignore rules** to 15
  sensitive paths rather than grepping, and self-checks that it does not
  exclude the application
- `docker-compose.yml`: parses under real YAML — 5 services, 3 volumes,
  2 networks, only the proxy publishes ports, grace periods 30/400/30 s
- `entrypoint.sh`: parses as POSIX `sh`; `exec` in every branch so the
  application is PID 1 and receives `SIGTERM`
- nginx config: structurally validated by tests (nginx is not installed
  either)
- `docker/nginx/tls/`: present, documented, and gitignored in both
  directions so a private key cannot be committed

What remains is one `docker compose build` and the smoke list in §19.

---

## 17. UI and browser acceptance

The interface is unchanged in design — Phase 11.17 was a restrained audit,
not a redesign. **Two real defects found and fixed.**

**1. Silent load failures.** Four of the five pages' load-state containers
had no live region, so a screen-reader user got nothing when a page failed
to load. `upload.html` already did it correctly (`role="alert"`); the
other four now match. 11 containers gained a live role.

**2. A flex axis flip that wasted 180px of a card.**
`.toolbar-search` carries `flex: 1 1 260px` — correct in the row layout it
was written for, where 260px means *width*. At ≤767px the toolbar becomes
`flex-direction: column`, and `flex-basis` follows the main axis: the same
declaration now means *260px tall, and grow to fill*. The search field was
the only growable item in the column, so it absorbed the leftover space as
height — about 180px of empty card between the search hint and the first
filter on the Documents page.

Found by rendering the page at 520px with its data loaded and looking at
it. Reading the two rules side by side does not reveal it, because neither
is wrong on its own; it is the axis flip between them that changes what
the number means. Fixed with `flex: 0 0 auto` in the column block. The
filter card went from roughly 1140px tall to 575px.

**Branding**: a real VIGILOX mark (`favicon.svg`, five-size
`favicon.ico`, apple-touch icon, `/favicon.ico` route, all five pages
linked, no external URL). Titles are page-name-first because a tab
truncates at ~15 characters. Legibility verified by **rendering** at
16×16: 252/256 pixels opaque, luminance spread 172/255.

**Automated in a real browser.** `scripts/verification/browser_acceptance.py`
drives headless Chrome:

```bash
python scripts/verification/browser_acceptance.py
```

- every page rendered after its JavaScript ran, and asserted branded
- favicon served
- **horizontal overflow measured** at 8 widths from 320px to 1440px:
  `scrollWidth == clientWidth` on all four pages, so there is no
  page-level overflow at any of them
- 20 screenshots written to `output/browser-acceptance/`
- every request the browser made was served — no 404, no 500

Two traps worth knowing about, both hit during this work:

1. **Headless Chrome clamps `--window-size` to about 500px.** A 390px
   screenshot is a 512px layout cropped to 390, which looks exactly like
   horizontal overflow. It produced one reported defect that did not
   exist. Narrow widths are therefore rendered inside an iframe, which
   is not clamped, and overflow is *measured* rather than eyeballed.
2. **The application's CSP blocks an inline measuring script** — correctly.
   The measurement runs against captured post-JavaScript snapshots on a
   throwaway server rather than weakening production's CSP.

**Still wants a human look:** colour, visual balance, and anything behind
a click. The script cannot interact; upload flows, review submission and
tab switching are covered by the harness tests. Checklist in §20.

---

## 18. Exact deployment commands

```bash
# 1. prepare
cp .env.example .env
#    fill in: GROQ_API_KEY, POSTGRES_PASSWORD,
#             VIGILOX_ENVIRONMENT=production,
#             VIGILOX_REVIEW_IDENTITY_MODE=trusted_headers,
#             VIGILOX_TRUSTED_PROXIES=<proxy address>

# 2. build
docker compose build

# 3. database
docker compose up -d postgres

# 4. migrate  (before the app, every time)
docker compose run --rm migrate

# 5. application
docker compose up -d api worker proxy
docker compose ps

# 6. verify from OUTSIDE, as the internet sees it
python scripts/verification/validate_deployment.py \
    --base-url https://<public host> --expect-public

# 7. verify from INSIDE, where restricted endpoints answer
python scripts/verification/validate_deployment.py \
    --base-url http://api:8000
```

Stop, in this order — reversed, the worker loses its database
mid-document:

```bash
docker compose stop proxy
docker compose stop worker      # up to 400s
docker compose stop api
docker compose stop postgres
```

---

## 19. Post-deployment smoke test

```bash
curl -fsS  http://localhost/health
curl -fsS  http://localhost/health/ready
curl -fsS  http://localhost/health/workers | python -m json.tool
curl -fsS -o /dev/null -w '%{http_code}\n' http://localhost/favicon.ico
for page in dashboard upload documents review; do
  curl -fsS -o /dev/null -w "$page %{http_code}\n" http://localhost/$page
done
```

Then, in a browser: one real upload, watched through to `COMPLETED`, and
the document opened in the workspace.

**Do not run the 63-document benchmark after a deploy.** It is an
expensive provider window, not a smoke test.

---

## 20. Manual browser checklist

The one thing automation here cannot do.

```
[ ] favicon visible in the tab, not a blank page icon
[ ] all five titles read "<Page> · VIGILOX"
[ ] no console exception, no 404 for a static asset
[ ] /upload: single mode and batch mode are mutually exclusive
[ ] /upload: only one state paints at a time; preview is valid
[ ] /upload: "Try Again" does not conflict with "Analyze"
[ ] /documents: long filenames truncate, table scrolls, no page overflow
[ ] /review: queue renders; empty state reads as the good state
[ ] /review/{id}: tabs usable; source panel usable; evidence highlights
[ ] /review/{id}: "Submit Corrections" appears only in correction mode
[ ] /review/{id}: a reviewed record cannot submit a second review
[ ] duplicate outcome reads as source identity, not as fraud
[ ] unsupported outcome explains itself
[ ] widths: large desktop, laptop, tablet, phone — no page-level overflow
[ ] elements marked [hidden] are actually invisible
```

---

## 21. Known limitations

1. **Field confidence is not a correctness probability** (§8).
2. **Image quality is heuristic**, not calibrated against accuracy.
3. **`/analyze` duplicate semantics differ** from the async path,
   deliberately.
4. **The application rate limiter is process-local.** The proxy is
   authoritative.
5. **No identity provider ships.** The boundary fails closed.
6. **No TLS certificate ships.** A committed private key would be worse
   than nothing.
7. **No monitoring stack ships.**
8. **A hot backup is reconcilable, not consistent.**
9. **Readiness does not prove OCR models are loaded** when the API runs
   lazily — which is the production default.
10. **Audit history is append-only by convention**, not by constraint.
11. **Backups are not encrypted at rest** by these scripts.
12. **Docker build unverified locally** (§16).
13. **No automated real-browser render check** (§17).
14. `samples/id_card.jpg` is a photograph of an apparently real national
    identity card. It is gitignored and is not a runtime, test, build or
    documentation dependency. **Delete it locally before packaging or
    sharing this repository.**

---

## 22. Rollback

```bash
# 1. application image only -- the usual case
docker compose down api worker
#    point the image tag at the previous version
docker compose up -d api worker

# 2. check the schema BEFORE considering a downgrade
docker compose run --rm migrate alembic current
docker compose run --rm migrate alembic history
```

**Do not downgrade the schema reflexively.** Migrations here are
additive, so the previous application version runs against the newer
schema. Downgrading destroys the columns the newer version wrote.

Downgrade only when the new revision is genuinely incompatible, and only
after a backup:

```bash
python scripts/maintenance/backup.py --output /backups --all --quiesced
docker compose run --rm migrate alembic downgrade -1
```

Restoring from backup is the last resort, not the first move — it
discards everything since the backup was taken.

---

## 23. Where everything is documented

| | |
|---|---|
| Deployment | [docs/deployment/deployment.md](../deployment/deployment.md) |
| Operations | [docs/operations/production-runbook.md](../operations/production-runbook.md) |
| Monitoring | [docs/operations/monitoring.md](../operations/monitoring.md) |
| Backup / restore | [docs/operations/backup-restore.md](../operations/backup-restore.md) |
| Shutdown | [docs/operations/shutdown.md](../operations/shutdown.md) |
| Security | [docs/security/security.md](../security/security.md) |
| Architecture | [docs/architecture/overview.md](../architecture/overview.md) |
| API | [docs/api/api.md](../api/api.md) |
| Evaluation | [docs/evaluation/evaluation.md](../evaluation/evaluation.md) |
