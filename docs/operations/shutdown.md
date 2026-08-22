# Shutdown Behaviour

## What a container runtime actually does

```
docker compose stop        SIGTERM  ->  wait stop_grace_period  ->  SIGKILL
kubectl delete pod         SIGTERM  ->  wait terminationGracePeriodSeconds -> SIGKILL
```

There is no negotiation. The grace period is the entire budget, and
anything still running at the end of it is killed outright. So the two
services get different budgets, because they are holding different
things.

| Service | `stop_grace_period` | What it is waiting for |
|---|---|---|
| `api` | 30s | in-flight HTTP requests, all short |
| `worker` | 400s | the document currently in the pipeline |
| `proxy` | 30s | in-flight proxied requests |

The worker's number is not padding. Measured worst case for the full
pipeline is **268 seconds** (OCR 43s maximum, extraction up to 25s, with
retries inside the attempt), and the job lease is **360 seconds** — the
lease being the formal statement of how long one document may take. A
grace period below that means a routine deploy SIGKILLs the worker
mid-document, and then the lease-recovery path below runs on every
deploy instead of only after a crash.

`exec` in `docker/entrypoint.sh` is what makes any of this work: without
it the shell stays PID 1, and a shell does not forward signals. The
container would sit still for the whole grace period and then be killed.

## The API

`SIGTERM` → uvicorn stops accepting connections, finishes what is in
flight, runs the lifespan shutdown, exits 0.

The lifespan shutdown drops the service objects and then **disposes the
connection pool**. That last part is easy to leave out and the
consequence only appears under the conditions shutdown happens in:

Each API replica holds up to 20 PostgreSQL connections. Without
`dispose()`, the process exits with those sockets open; the kernel closes
them, but PostgreSQL only notices on its next read, and until then the
backends remain in `pg_stat_activity`. Start the replacement replica
before that happens and the server is briefly asked for two replicas'
worth of connections against a `max_connections` sized for one. The
failure is `FATAL: sorry, too many clients already`, during a deploy that
changed nothing about load.

`api.pool_disposed` in the log is the evidence it ran. Exit 0 alone is
not: a process killed between the last response and the lifespan resuming
also exits 0.

Non-zero exit on shutdown is avoided deliberately — a container runtime
reports it as a crash, and a deploy that looks like a crash gets rolled
back.

## The worker

```
first signal    stop claiming; finish the current document; exit 0
second signal   exit now, non-zero, recording worker.force_exit
```

The first signal does **not** interrupt the document in progress. It sets
a flag the run loop checks before claiming again, so the current job runs
to its natural end and is recorded truthfully. It also writes the
heartbeat as `DRAINING` **before** the wait begins — otherwise a rolling
deploy looks like a worker failure for the length of the grace period,
and an alert that fires on every deploy is an alert that gets muted.

A clean exit leaves the heartbeat at `STOPPED`. That is what distinguishes
"gone on purpose" from "died": a row left at `RUNNING` that stops
advancing is a dead worker, and monitoring pages on that one.

The second signal is the escape hatch for an operator who needs the
process gone now and should not have to reach for `SIGKILL` — which skips
the heartbeat write and every other bit of cleanup. It exits **non-zero**
on purpose: the worker abandoned a claimed job, and exiting 0 would
report success for work that did not happen.

## If the worker is killed hard

`SIGKILL`, an OOM kill, a host reboot, the end of the grace period. No
handler runs; nothing is written. The job is left `PROCESSING` with a
lease held by a process that no longer exists.

**What must not happen is the job being recorded as `COMPLETED`.** Only
the process that did the work knows what happened to it, and it is gone.
A completion timestamp written on its behalf is indistinguishable from
success forever afterwards — the quietest possible data-integrity
failure.

What does happen: the lease expires, and the next worker to look claims
it. That claim counts as an attempt, which matters — without it a
document that kills the worker is retried without limit, and each retry
kills the worker again.

```
lease held, worker gone     job stays PROCESSING
lease expires (360s)        job becomes claimable again
next claim                  attempt_count += 1, lease moves to the new worker
attempts exhausted          FAILED, with a safe error code
```

Recovery is therefore bounded by the lease, not by the crash. A worker
killed mid-document costs that document up to 360 seconds of delay and
one of its attempts, and costs the queue nothing permanently.

## Stopping the stack in the right order

```
1. docker compose stop proxy      no new requests arrive
2. docker compose stop worker     up to 400s; it finishes its document
3. docker compose stop api        30s
4. docker compose stop postgres   last, because the others write to it
```

Reversed, the worker loses its database mid-document and the job is
recovered by lease expiry instead of finishing — the crash path, entered
on purpose.

For a backup, this order is also the quiesce window: see
[backup-restore.md](backup-restore.md).

## Verifying it

`tests/deployment/test_phase11_graceful_shutdown.py` starts real
processes and signals them. It asserts exit codes, that the lifespan
shutdown ran, that PostgreSQL connections are actually released
afterwards, that the heartbeat ends at `STOPPED`, and that a job
abandoned by a vanished worker is recovered by the real claim query
rather than marked complete.

On Windows it sends `CTRL_BREAK_EVENT` rather than calling
`terminate()` — `terminate()` maps to `TerminateProcess`, which runs no
cleanup at all, so using it would test `SIGKILL` and report it as a
graceful shutdown. On Linux, where the containers run, it is a plain
`SIGTERM`.
