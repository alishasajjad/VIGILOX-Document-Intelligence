# Monitoring and Alerting

## What ships, and what does not

**No monitoring stack is deployed with this application.** There is no
Prometheus, no Grafana and no Alertmanager in `docker-compose.yml`, and
none is included anywhere in this repository.

What the application provides is three endpoints. Everything below is a
recommendation for whatever monitoring you already run — not a
description of something that is running.

| Endpoint | Answers | Probe it as |
|---|---|---|
| `GET /health` | Is the process alive? | liveness |
| `GET /health/ready` | Can it reach the database and storage? | readiness |
| `GET /health/workers` | Is anything draining the queue? | alert only |
| `GET /metrics` | Prometheus text exposition | scrape |

`/metrics` is restricted to private ranges by the reverse proxy
([docker/nginx/vigilox-locations.conf](../../docker/nginx/vigilox-locations.conf))
and is **off by default in production** unless `VIGILOX_METRICS_ENABLED`
is set. Queue depth, failure rates and provider behaviour say how loaded
the service is, when it is struggling, and whether anyone is watching.

## Why worker health is not readiness

The distinction matters and it is easy to get backwards.

The API can serve uploads, reads and reviews perfectly well with **no
worker running at all** — the uploads simply queue. So a dead worker
must not fail `/health/ready`: doing so would take the API out of the
load balancer and turn a worker problem into an API outage, while the
queue it could not drain grew anyway.

This is the outage shape worth understanding: *every individual health
check green, and the product not working*. Uploads accepted, 202
returned, nothing processed. `/health/workers` exists to answer that
question and nothing else does.

## The four worker states

```
HEALTHY      a worker checked in recently
DRAINING     a worker is shutting down on purpose
STALE        a worker checked in, but not lately
NO_WORKER    nothing has ever checked in
```

**STALE versus NO_WORKER is the important pair.** The first is a worker
that died; the second is a deployment where one was never started — a
missing compose service, a typo in a command. Different cause, different
fix, and they look identical if all you have is "no recent heartbeat".

**DRAINING** exists so a rolling deploy does not look like a worker
failure for the length of the 400-second grace period. An alert that
fires on every deploy is an alert that gets muted.

### What counts as a heartbeat

The row in `worker_heartbeats` is written **from inside the worker's
run loop**. That is deliberate: a container that is running but wedged —
stuck on a socket, deadlocked, thrashing — writes nothing, while
`docker compose ps` still shows it up. "A worker container exists" and
"`VIGILOX_WORKER_CONCURRENCY` is set" both describe *intent*.

## Recommended alerts

Thresholds are starting points derived from the measured behaviour in
this repository, not universal values. Tune them against your own
traffic.

### Page immediately

| Condition | Expression | Why |
|---|---|---|
| Work waiting, no worker | `vigilox_queue_waiting_with_no_worker == 1` for 5m | The outage where every other check is green. Uploads accepted, nothing processed. |
| Readiness failing | `/health/ready` non-200 for 2m | The database or storage root is unreachable; the API cannot serve. |
| Database unavailable | `vigilox_metrics_database_available == 0` for 5m | Queue metrics could not be read at all. |
| 5xx rate | `rate(vigilox_http_requests_total{status="5xx"}[5m])` above 1% of total for 10m | Ordinary errors are 4xx; a sustained 5xx rate is the application failing. |

### Investigate during the day

| Condition | Expression | Why |
|---|---|---|
| Worker heartbeat stale | `vigilox_workers{state="stale"} > 0` for 10m | A worker died. The queue may still be draining if others live. |
| Queue growing | `vigilox_job_queue_depth{status="QUEUED"}` rising for 30m | Arrival rate exceeds throughput. One worker drains roughly 3 documents a minute. |
| Failed jobs rising | `rate(vigilox_jobs_total{outcome="failed"}[15m])` above baseline | Non-transient failures: an unsupported input pattern, a broken model, a storage problem. |
| Provider rate limits persisting | `rate(vigilox_extraction_provider_total{outcome="rate_limited"}[15m])` sustained | Groq quota exhausted or throttling. Jobs retry, so this shows as slowness before it shows as failure. |
| Retry rate | `rate(vigilox_jobs_total{outcome="retried"}[15m])` climbing | Transient failures increasing. Often the leading indicator of a provider problem. |
| Slow pipeline | p95 of `vigilox_pipeline_stage_duration_seconds{stage="ocr"}` above 60s | OCR measured a 28s median and 43s maximum on the benchmark images. Well above that means CPU contention or a much larger input. |

### Infrastructure, from your host monitoring

The application cannot see these and does not pretend to.

| Condition | Why it matters here specifically |
|---|---|
| **Disk nearly full** on the document-storage volume | Managed source documents are written before the analysis commits. A full disk fails uploads, and it is the one condition that can lose a document that was accepted. Alert at 80%. |
| **Disk nearly full** on the pending-uploads volume | A full pending volume rejects uploads at the door. Usually means jobs are not completing and their sources are not being cleaned up. |
| **Disk nearly full** on the PostgreSQL volume | PostgreSQL stops accepting writes. The queue is in PostgreSQL, so this stops processing as well as recording. |
| **Memory** on a worker container | PaddleOCR is a few hundred megabytes resident per worker. An OOM kill mid-document loses an OCR pass and the job waits out its lease. |
| **PostgreSQL connection count** | Per *process*: each API replica uses up to 20, each worker its concurrency + 1. Scaling replicas without raising `max_connections` produces "FATAL: sorry, too many clients already" under exactly the load the scale-up was for. |

## Reading the queue metrics

```
vigilox_job_queue_depth{status="QUEUED"}       waiting to be claimed
vigilox_job_queue_depth{status="PROCESSING"}   claimed, in the pipeline
vigilox_job_queue_depth{status="RETRY_WAIT"}   failed transiently, backing off
vigilox_job_queue_depth{status="COMPLETED"}    cumulative, grows forever
vigilox_job_queue_depth{status="FAILED"}       cumulative, grows forever
```

`COMPLETED` and `FAILED` are row counts, not rates — they only ever
grow, until `scripts/maintenance/purge_finished_jobs.py` runs. Alert on
`rate(vigilox_jobs_total{outcome="failed"})` instead, which is a counter
of events.

A healthy idle system reads `QUEUED 0, PROCESSING 0, RETRY_WAIT 0`. A
healthy busy one reads `PROCESSING` equal to the total worker
concurrency, with `QUEUED` draining.

## What the metrics deliberately do not contain

No metric label carries a `document_id`, a `job_id`, a filename, a
reviewer identity, or any OCR or extracted text.

A Prometheus label value creates a separate time series, and the scraper
holds every series it has ever seen. `document_id` would be one series
per document, forever; a filename would be that *and* user-controlled
text inside a monitoring system.

Route labels are **templates** — `/api/v1/documents/{id}`, never the id.
Anything unrecognised collapses to `other` rather than being passed
through, because an unrecognised path is exactly the case that would
otherwise leak an identifier.

The identifiers are in the structured log, correlated by `request_id`.
That is the right place for high-cardinality detail: a log line is
written once and read when needed; a metric series is held forever.

`tests/deployment/test_phase11_observability.py` asserts this against
the **rendered** output rather than the source, because the question is
what actually gets scraped.

## Counters are per process

Each replica keeps its own counters. That is how Prometheus counters are
meant to work — it scrapes each replica separately and sums across them.
It is only wrong if someone reads one replica's numbers as the whole
deployment's.

Queue depth and worker state are the exception: they are read from
PostgreSQL at scrape time, because they are properties of the database
rather than of a replica. Two API processes each counting uploads would
each see part of the queue; one `SELECT` sees all of it.
