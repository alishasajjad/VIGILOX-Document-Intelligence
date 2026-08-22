# Deployment

## What this deploys

Five containers from **one image**. The image is built once and run with
different commands, so the API, the worker and the migration step cannot
drift apart in their dependencies or their code.

```
proxy      nginx        the only thing with a published port
api        the image    uvicorn, no published port
worker     the image    the pipeline, no ports at all
migrate    the image    alembic upgrade head, runs once, exits
postgres   postgres:18  the database AND the durable job queue
```

**There is no Redis.** The queue is PostgreSQL, using
`FOR UPDATE SKIP LOCKED` with worker leases. That is not a compromise: a
job row and the document row it produces commit in the same transaction,
which a separate broker cannot give you. Adding Redis would add a second
thing to run, back up and reason about, in exchange for losing that.

## Before the first deploy

```
1. cp .env.example .env          and fill in the real values
2. docker compose build
3. docker compose run --rm migrate
4. docker compose up -d
5. python scripts/verification/validate_deployment.py \
       --base-url https://<your host> --expect-public
```

Step 5 is not optional. See [Validation](#validation) below.

### The values you must set

| Variable | Why it has no default |
|---|---|
| `GROQ_API_KEY` | a secret |
| `POSTGRES_PASSWORD` | a secret |
| `VIGILOX_ENVIRONMENT=production` | turns on the startup checks that refuse an unsafe configuration |
| `VIGILOX_REVIEW_IDENTITY_MODE=trusted_headers` | `local_env` gives every reviewer the same identity |
| `VIGILOX_TRUSTED_PROXIES` | the addresses whose identity headers are believed |

The compose file uses `${VAR:?}` for the secrets, so a missing one stops
the stack from starting rather than starting it with an empty value.

**In `production`, the API refuses to start** if the identity mode is
`local_env`, or if it is `trusted_headers` with no trusted proxies
configured. Refusing to start is deliberate: a service that comes up and
quietly mis-attributes review decisions is discovered by auditing them
afterwards, which is far worse than one that would not start.

## The network shape

```
internet
   |
   v
 proxy    :443 / :80        <- the only published port
   |
   |  network: edge
   v
  api                       <- no published port
   |
   |  network: internal
   v
postgres  <-  worker
```

**The api container must not publish a port.** With one, everything the
proxy does — stripping identity headers, rate limiting, denying `/docs`
and `/metrics` — is bypassable by connecting to the api port directly.
`validate_deployment.py --expect-public` is how you find out whether that
happened.

`postgres` is on the internal network only. The worker is on the internal
network only: it makes outbound calls to the extraction provider and
accepts nothing.

## What the proxy is responsible for

### Stripping the identity headers

```nginx
proxy_set_header X-VIGILOX-REVIEWER-ID   "";
proxy_set_header X-VIGILOX-REVIEWER-ROLE "";
```

Then injecting authoritative values from whatever authenticates the user.

**nginx forwards unknown request headers by default**, so not mentioning
a header is not stripping it. Without these two lines, anyone who can
reach the service can name themselves `ADMIN` and write review decisions
and audit entries under any identity they choose. This is the single most
important line in the proxy configuration.

`VIGILOX_TRUSTED_PROXIES` is the second lock: the API only believes those
headers from a peer in that list, so reaching the api container directly
does not work either.

**No identity provider is faked here.** There is no IdP in this
repository and none is invented. With nothing in front of the proxy, the
strip removes the client's headers and nothing replaces them, and the
deployment fails closed: documents can be uploaded and read, nothing can
be approved. That is the correct posture, and it is not the same as being
open. Wire a real IdP into the `auth_request` boundary before anyone
needs to approve anything.

### Rate limiting

Four zones, because the routes cost very different amounts:

| Zone | Route | Why |
|---|---|---|
| upload | `POST /api/v1/document-jobs` | each one becomes an OCR run |
| batch | `POST /api/v1/document-batches` | one request, many OCR runs |
| analyze | `POST /api/v1/documents/analyze` | synchronous OCR, holds a worker thread |
| review | `POST .../reviews` | writes an audit entry |

**The catch-all has no limit, deliberately.** Job status polling goes
through it, and a limit there makes a working upload look hung to the
async UI.

**The proxy is the authoritative limiter.** The application also has one,
and it is **process-local**: it keeps counters in the memory of one
process. With N API replicas the effective limit is N times the
configured value, and a restart forgets everything. It is
defence-in-depth for a direct-to-container request and nothing more. Do
not rely on it in a multi-process or multi-replica deployment.

### Refusing what should not be public

```
/metrics          private ranges only
/health/workers   private ranges only
/docs             denied
/redoc            denied
/openapi.json     denied
```

None of these are credentials. They are a map of the service, how loaded
it is, and a form for calling every route.

### TLS

**No certificate is committed.** A self-signed certificate in a
repository is TLS with a publicly known private key, which is worse than
none because it looks like protection.

The HTTPS server block in `docker/nginx/nginx.conf` is present and
commented out. Uncomment it, mount real certificates, and the HSTS
header the application already sends becomes meaningful — it is sent
only when the request arrived over HTTPS, so it cannot lock a
non-HTTPS deployment out of itself.

## Volumes

```
vigilox_pgdata      PostgreSQL data
vigilox_documents   managed source documents
vigilox_pending     pending job source files
```

**`documents` and `pending` are separate volumes, and must stay that
way.** A pending file has no document row yet, by definition, so if it
sits under the managed root the integrity scan classes it as an orphan —
and orphans are the one class reconciliation deletes automatically.
Documents would disappear mid-processing. The application refuses to
start if the pending root is nested inside the managed one; the volume
layout is what makes that impossible to arrive at by accident.

All three need backing up. See
[backup-restore.md](../operations/backup-restore.md).

## OCR model loading

The API and the worker are configured in opposite directions, on
purpose:

```
VIGILOX_API_EAGER_PIPELINE=false      measured 3 ms of startup
VIGILOX_WORKER_EAGER_PIPELINE=true    measured 2929 ms of startup
```

The API does not run OCR except through the legacy synchronous
`/analyze` route, which a deployment using the job API may never call.
Loading PaddleOCR into every replica for it costs a few hundred megabytes
each, resident, permanently.

The worker runs OCR on every job, so loading lazily buys nothing and
costs the first job's lease. Eager also means a broken model install
makes the container **fail to start**, where the deploy can see it,
rather than failing the first document — which looks like a bad document
rather than a bad deployment.

**Consequence to be honest about: with the API lazy, `/health/ready`
passing does not mean OCR models are loaded in that process.** It means
the database and the storage root are reachable. Nothing in the API's
readiness touches the model.

Models are baked into the image at build time, so a container start needs
no network. The model cache volume contains models only — never document
or user data.

## Validation

```
# from outside, as the internet sees it
python scripts/verification/validate_deployment.py \
    --base-url https://<public host> --expect-public

# from inside the network, where the restricted endpoints answer
python scripts/verification/validate_deployment.py \
    --base-url http://api:8000
```

It probes a **running** deployment rather than reading the configuration,
which is the only way to catch the class of problem that passes every
test in the repository:

- an environment variable set in the wrong compose file
- a proxy started from a stale config
- a volume that did not mount
- a migration nobody ran
- the api container published directly, bypassing the proxy

It uploads nothing, runs no OCR, calls no provider, and modifies nothing.

Run it from both addresses. The public run should show `/metrics`,
`/health/workers` and `/docs` refused; the internal run is where worker
health can actually be read.

## Rolling a new version

```
1. docker compose build
2. docker compose run --rm migrate         # additive migrations first
3. docker compose up -d --no-deps api
4. docker compose up -d --no-deps worker   # up to 400s to drain
5. python scripts/verification/validate_deployment.py ...
```

Migrations run before the new code, and must be additive — the old code
is still serving while step 3 rolls. A migration that drops a column the
running version selects takes the service down between steps 2 and 3.

The worker takes up to 400 seconds to stop because it finishes the
document it is holding. See [shutdown.md](../operations/shutdown.md).

## What is deliberately absent

| Not here | Why |
|---|---|
| Redis | the queue is PostgreSQL, transactionally with the documents |
| Prometheus / Grafana / Alertmanager | the application exposes `/metrics`; no monitoring stack is deployed with it, and claiming otherwise would be false |
| A TLS certificate | a committed private key is not TLS |
| An identity provider | none exists here; the boundary is provided and fails closed |
| `pg_dump` in the application image | an operator tool; the postgres image has a version-matched one |
| A cluster-wide rate limiter | the application's is process-local and says so |

## Where things are

| | |
|---|---|
| Monitoring and alerts | [monitoring.md](../operations/monitoring.md) |
| Backup and restore | [backup-restore.md](../operations/backup-restore.md) |
| Shutdown behaviour | [shutdown.md](../operations/shutdown.md) |
| Architecture | [overview.md](../architecture/overview.md) |
