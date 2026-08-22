# Production Runbook

Operational tasks, in the order you are likely to need them. Every
command here is for the stack that actually exists — five compose
services: `proxy`, `api`, `worker`, `migrate`, `postgres`.

For *why* things are shaped the way they are, see
[deployment.md](../deployment/deployment.md). This file is what to type.

---

## Start the stack

```bash
docker compose build
docker compose up -d postgres
docker compose run --rm migrate
docker compose up -d api worker proxy
docker compose ps
```

`migrate` runs to completion and exits — it is not a long-running
service. Run it **before** `api` and `worker`, every time.

Then validate, from outside:

```bash
python scripts/verification/validate_deployment.py \
    --base-url https://<public host> --expect-public
```

## Stop the stack

Order matters. Reversed, the worker loses its database mid-document.

```bash
docker compose stop proxy      # no new requests arrive
docker compose stop worker     # up to 400s: it finishes its document
docker compose stop api        # 30s
docker compose stop postgres   # last; the others write to it
```

## Restart one service

```bash
docker compose restart api
docker compose restart worker      # up to 400s to drain
docker compose restart proxy       # picks up a changed nginx config
```

Restarting `api` drops in-flight HTTP requests only, all short.
Restarting `worker` finishes the document it holds first.

## Run migrations

```bash
docker compose run --rm migrate                          # upgrade head
docker compose run --rm migrate alembic current          # where am I
docker compose run --rm migrate alembic history          # what exists
docker compose run --rm migrate alembic check            # any drift
```

Locally, without containers:

```bash
alembic upgrade head
alembic current
```

`alembic check` reporting drift means the models and the migrations
disagree — a migration was not generated for a model change.

---

## Health checks

```bash
curl -fsS  http://localhost/health          # process alive
curl -fsS  http://localhost/health/ready     # DB + storage reachable
curl -fsS  http://localhost/health/workers   # internal only
```

| Endpoint | Probe it as | Failing means |
|---|---|---|
| `/health` | liveness | the process is wedged; restart it |
| `/health/ready` | readiness | the database or storage root is unreachable |
| `/health/workers` | **alert only, never readiness** | nothing is draining the queue |

**`/health/workers` must not be a load-balancer probe.** The API serves
uploads, reads and reviews perfectly with no worker running — the uploads
simply queue. Failing readiness on a worker problem would take the API
out of the load balancer and turn one outage into two.

## Worker heartbeat

```bash
curl -fsS http://localhost/health/workers | python -m json.tool
```

```
HEALTHY      a worker checked in recently
DRAINING     a worker is shutting down on purpose
STALE        a worker checked in, but not lately  -> it died
NO_WORKER    nothing has ever checked in          -> never started
```

`STALE` vs `NO_WORKER` is the pair that matters: a worker that died
versus a deployment where one was never started (a missing compose
service, a typo in the command). Different cause, different fix, and they
look identical if all you have is "no recent heartbeat".

The single field worth paging on:

```
queue_waiting_with_no_worker == 1
```

That is the outage where every other check is green — uploads accepted,
202 returned, nothing processed.

## Queue inspection

```bash
docker compose exec -T postgres psql -U vigilox -d vigilox_document_intelligence -c \
  "select status, count(*) from document_jobs group by status order by 2 desc;"
```

A healthy idle system reads `QUEUED 0, PROCESSING 0, RETRY_WAIT 0`. A
healthy busy one reads `PROCESSING` equal to total worker concurrency,
with `QUEUED` draining. One worker drains roughly 3 documents a minute.

`COMPLETED` and `FAILED` grow forever until
`scripts/maintenance/purge_finished_jobs.py` runs. They are row counts,
not rates.

## Investigate one job

```bash
curl -fsS http://localhost/api/v1/document-jobs/<job id> | python -m json.tool
```

```bash
docker compose exec -T postgres psql -U vigilox -d vigilox_document_intelligence -c \
  "select id, status, attempt_count, max_attempts, worker_id,
          lease_expires_at, safe_error_code, next_attempt_at
     from document_jobs where id = '<job id>';"
```

`safe_error_code` is deliberately a *safe* code — it never carries OCR
text, extracted values or filenames. For detail, find the structured log
lines by `request_id`.

## Logs

```bash
docker compose logs -f worker
docker compose logs -f api
docker compose logs --since 30m api | grep '"level": "ERROR"'
```

Logs are structured JSON. Correlate an API request with its worker
processing by `request_id`.

The application's access logging is **off** (`--no-access-log`): uvicorn
writes full paths, and this application's paths carry document ids
(`GET /api/v1/documents/<uuid>/image`). The proxy keeps an access log
with a deliberately chosen format instead.

Nothing in the log carries OCR text, extracted field values, identity
numbers, review notes, or credentials.

## Metrics

```bash
# from inside the private network only
curl -fsS http://api:8000/metrics | grep vigilox_
```

Off in production unless `VIGILOX_METRICS_ENABLED` is set, and restricted
to private ranges by the proxy. There is **no Prometheus, Grafana or
Alertmanager in this repository** — `/metrics` is an endpoint for
whatever you already run. Alert expressions:
[monitoring.md](monitoring.md).

---

## A stale worker

A worker that died holding a lease. The job stays `PROCESSING` until the
lease expires (360s), then any worker can claim it.

```bash
curl -fsS http://localhost/health/workers | python -m json.tool
docker compose logs --tail 200 worker
docker compose restart worker
```

Recovery is automatic and bounded by the lease. Do **not** hand-edit a
`PROCESSING` row to `COMPLETED` — only the process that did the work
knows what happened to it, and marking it complete is permanent and
indistinguishable from success.

To prune heartbeat rows for workers that will never return:

```bash
docker compose exec -T postgres psql -U vigilox -d vigilox_document_intelligence -c \
  "delete from worker_heartbeats
    where status = 'STOPPED' and last_seen_at < now() - interval '7 days';"
```

## A stuck job

```bash
# still leased, worker gone -> wait out the lease, it self-recovers
# attempts exhausted -> FAILED with a safe error code, by design

# run exactly one job, for investigation, without touching the queue head
python -m backend.worker --once
```

`claim_next` supports `only_job_ids`, which is how a single job is
reprocessed without claiming whatever is at the head of the queue.

## Provider 429 / quota exhausted

Groq rate limiting shows as **slowness before it shows as failure**: the
job layer retries with backoff.

```bash
docker compose logs --since 1h worker | grep rate_limited
curl -fsS http://api:8000/metrics | grep extraction_provider_total
```

What to do: nothing to the code. Wait for quota, or reduce
`VIGILOX_WORKER_CONCURRENCY` to slow arrival at the provider.

**Do not change extraction logic because of a 429.** It is a quota
signal, not a correctness signal.

### If it was the evaluation that ran out

The 63-document benchmark is the one thing here that can exhaust a daily
allowance on its own: 63 documents at roughly 4,500 tokens each against a
200,000/day limit.

```bash
# resume -- picks up only the samples that have no successful record
python -m scripts.evaluation.evaluation_runner

# score it -- refuses a partial run rather than reporting 56 as 63
python -m scripts.evaluation.evaluation_metrics
```

**Never pass `--reset`.** It discards completed predictions and makes you
pay for them again. Resuming is the default and it is safe: the runner
writes a `status: "failed"` row for a blocked sample, and only
`status: "success"` counts as done, so a resume retries exactly what is
missing.

Check what is outstanding before resuming:

```bash
python -c "import json,pathlib,collections; rows=[json.loads(l) for l in pathlib.Path('evaluation/results/predictions.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]; done={r['sample_id'] for r in rows if r.get('status')=='success'}; allids={json.loads(l)['sample_id'] for l in pathlib.Path('evaluation/ground_truth/labels.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()}; print(len(done),'/',len(allids),'done; missing:',sorted(allids-done))"
``` Do not switch models either — the
fallback model exists only for "this model does not exist", never for
rate limits.

## Disk nearly full

```bash
docker system df
docker compose exec -T api df -h /data/documents /data/pending
```

| Volume | Full means |
|---|---|
| `vigilox_documents` | **uploads can be lost.** Managed source documents are written before the analysis commits. Alert at 80% |
| `vigilox_pending` | uploads rejected at the door. Usually means jobs are not completing and their sources are not being cleaned up |
| `vigilox_pgdata` | PostgreSQL stops accepting writes — and the queue is in PostgreSQL, so processing stops too |

Reclaim safely:

```bash
python scripts/maintenance/purge_finished_jobs.py --help
python scripts/maintenance/reconcile_storage.py              # dry run: look first
python scripts/maintenance/reconcile_storage.py --apply      # then act
```

`reconcile_storage` deletes exactly one category: managed files with no
database row. It deliberately will **not** touch a row whose file is
missing (that is a data-loss incident and possibly a restore, not a
cleanup) nor anything it does not recognise.

### The residue script needs telling what to delete

`scripts/maintenance/clean_test_residue.py` removes document rows left by
test runs. **It identifies them by filename**, and three of the patterns
it matches — `guard_license.jpg`, `id_card.jpg`, `sia_badge.jpg` — are the
sample filenames. Anyone trying the product uploads exactly those, so a
real upload and a test row can be indistinguishable.

It therefore refuses an untargeted delete:

```bash
python scripts/maintenance/clean_test_residue.py                    # report only
python scripts/maintenance/clean_test_residue.py --delete --id <id>  # exactly these
python scripts/maintenance/clean_test_residue.py --delete --all-candidates
```

The report marks which candidates are matched *only* by a sample
filename. Read that list before choosing `--all-candidates`.

**Never run this against production.** It exists for a development
database that has accumulated test rows.

## Database problem

```bash
curl -fsS http://localhost/health/ready          # is it reachable at all
docker compose logs --tail 200 postgres
docker compose exec -T postgres psql -U vigilox -d vigilox_document_intelligence -c \
  "select count(*) from pg_stat_activity where datname = current_database();"
```

`FATAL: sorry, too many clients already` — count the connections you
actually need: each API replica uses up to 20, each worker its
concurrency + 1. Scaling replicas without raising `max_connections`
produces this under exactly the load the scale-up was for.

If readiness reports `request_concurrency` above
`database_connections_per_process`, requests will fail with 500s while
the database is healthy. Both numbers derive from
`VIGILOX_REQUEST_CONCURRENCY`; something has overridden one of them.

---

## Backup

```bash
python scripts/maintenance/backup.py --output /backups --all
```

Quiesced, for a genuinely consistent pair:

```bash
docker compose stop proxy worker
# wait for PROCESSING to reach 0
python scripts/maintenance/backup.py --output /backups --all --quiesced
docker compose up -d worker proxy
```

Without `--quiesced` it is a **hot** backup: the database and the files
are captured at different instants and are not a transactionally
consistent pair. The manifest records which you took. Full reasoning:
[backup-restore.md](backup-restore.md).

## Restore

```bash
# verify first -- writes nothing
python scripts/maintenance/restore.py --input /backups/vigilox-backup-<stamp> --all

# then restore
python scripts/maintenance/restore.py --input /backups/vigilox-backup-<stamp> --all --confirm

# then check the two halves agree
python scripts/maintenance/reconcile_storage.py
```

The restore refuses an incomplete manifest, a checksum mismatch, a
populated target without `--force`, overlapping storage roots, a schema
revision that does not match the code, and an archive member that escapes
its destination.

## Rollback

```bash
# 1. application image only -- the usual case
docker compose down api worker
#    point the image tag at the previous version
docker compose up -d api worker

# 2. check the schema BEFORE considering a downgrade
docker compose run --rm migrate alembic current
docker compose run --rm migrate alembic history
```

**Do not downgrade the schema reflexively.** Most rollbacks do not need
it: migrations here are additive, so the previous application version
runs against the newer schema. Downgrading destroys the columns the newer
version wrote.

Downgrade only when the new revision is genuinely incompatible, and only
after taking a backup:

```bash
python scripts/maintenance/backup.py --output /backups --all --quiesced
docker compose run --rm migrate alembic downgrade -1
```

Restoring from backup is the last resort, not the first move — it
discards everything since the backup was taken.

## Deployment smoke test

After any deploy:

```bash
curl -fsS http://localhost/health
curl -fsS http://localhost/health/ready
curl -fsS http://localhost/health/workers | python -m json.tool
curl -fsS -o /dev/null -w '%{http_code}\n' http://localhost/favicon.ico
curl -fsS -o /dev/null -w '%{http_code}\n' http://localhost/dashboard
curl -fsS -o /dev/null -w '%{http_code}\n' http://localhost/upload
curl -fsS -o /dev/null -w '%{http_code}\n' http://localhost/documents
curl -fsS -o /dev/null -w '%{http_code}\n' http://localhost/review

python scripts/verification/validate_deployment.py \
    --base-url https://<public host> --expect-public
```

Render every page in a real browser and measure for layout overflow:

```bash
python scripts/verification/browser_acceptance.py     --base-url https://<public host>
```

Then one real upload through the browser, and watch it reach `COMPLETED`.

**Do not run the 63-document benchmark after a deploy.** It is an
expensive provider window, not a smoke test.
