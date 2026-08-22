# Security

What protects this service, what does not, and where the edges are. Read
[deployment.md](../deployment/deployment.md) for how to configure it and
[production-runbook.md](../operations/production-runbook.md) for how to
operate it.

## The identity boundary

**This is the most important section in the document.**

The reviewer identity comes from two request headers:

```
X-VIGILOX-REVIEWER-ID
X-VIGILOX-REVIEWER-ROLE
```

The browser is **never** authoritative about either. Two independent
mechanisms enforce that, and both are needed.

### 1. The proxy strips them

```nginx
proxy_set_header X-VIGILOX-REVIEWER-ID   "";
proxy_set_header X-VIGILOX-REVIEWER-ROLE "";
```

nginx forwards unknown request headers by default, so **not mentioning a
header is not stripping it**. Whatever authenticates the user injects
authoritative values after the strip.

### 2. The application only believes a trusted peer

`VIGILOX_TRUSTED_PROXIES` lists the addresses, CIDR ranges or literal
peers whose forwarded identity is honoured. Anything from anywhere else
is refused, so reaching the api container directly does not work either.

Nothing configured means nothing is trusted — a deployment that forgot
the list refuses identity headers rather than accepting them from anyone.

### A vulnerability found and fixed before release

**Phase 11.5 found a real hole.** `trusted_headers` mode honoured the
identity headers **without checking where the request came from**. Any
client able to reach the backend could name itself `ADMIN`, approve
documents, and write audit entries under any identity it chose — with the
audit trail recording the impersonated name, which is the part that makes
it serious. Reviewing the audit log afterwards would show a plausible
reviewer approving things.

The fix is the peer check above. Verified in both directions: a request
from a configured proxy address is accepted; the identical request from
an unconfigured address is refused. `VIGILOX_TRUSTED_PROXIES` is now
mandatory in production for this mode, and the application **refuses to
start** without it.

The lesson is the general one: *a header is only as trustworthy as the
hop that set it*, and "we put it behind a proxy" is a deployment
assumption, not an enforced property, until the application checks.

### Production fails closed

With `VIGILOX_ENVIRONMENT=production`, startup **refuses** two
configurations outright:

| Refused | Why |
|---|---|
| `local_env` identity mode | every reviewer gets the same identity, so every decision in the audit trail carries one name |
| `trusted_headers` with no trusted proxies | see above |

Refusing to start is deliberate. A service that comes up and quietly
mis-attributes review decisions is discovered by auditing them later,
which is far worse than one that would not start.

**No identity provider is faked.** None exists in this repository and none
is invented. With nothing in front of the proxy, the strip removes the
client's headers and nothing replaces them: uploads and reads work,
nothing can be approved. That is a fail-closed integration boundary, and
it is not the same as being open.

## Authorization

Three roles, checked server-side on every action:

```
VIEWER      read only
REVIEWER    read, and submit review decisions
ADMIN       everything a reviewer can do
```

A `VIEWER` attempting a review action is refused by the API, not by the
UI hiding a button. The UI hides the button as well, because showing an
action that will fail is bad design — but the check that matters is the
server's.

**One review per document**, enforced by a database unique constraint
(`uq_human_reviews_document_id`) rather than by an application check. A
constraint cannot be raced; two concurrent submissions produce one
success and one integrity error.

## Rate limiting

Two layers, and the difference between them matters.

| Layer | Scope | Role |
|---|---|---|
| nginx `limit_req_zone` | the whole deployment | **authoritative** |
| the application limiter | one process | defence-in-depth only |

**The application limiter is process-local and this is stated plainly
everywhere it appears.** It keeps counters in one process's memory: with
N API replicas the effective limit is N times the configured value, and a
restart forgets everything. It is a backstop for a request that reaches a
container directly. It is **not** a cluster-wide limit and must not be
described as one.

Four proxy zones, because the routes cost very different amounts:

| Zone | Route | Cost |
|---|---|---|
| upload | `POST /api/v1/document-jobs` | one OCR run |
| batch | `POST /api/v1/document-batches` | many OCR runs |
| analyze | `POST /api/v1/documents/analyze` | synchronous OCR, holds a thread |
| review | `POST /api/v1/documents/{id}/reviews` | an audit write |

The catch-all has **no** limit, deliberately: job-status polling goes
through it, and limiting it makes a working upload look hung.

## Security headers

```
Content-Security-Policy
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy
Permissions-Policy
Cross-Origin-Opener-Policy
Strict-Transport-Security   (only when the request arrived over HTTPS)
```

Applied by pure ASGI middleware — not `BaseHTTPMiddleware`, which
buffers response bodies.

**They are present on error responses and on 429s.** That is the part
usually missed, and it was a real bug here: the rate limiter answers
without calling through, so a 429 built inside it never passed through
the header middleware. Registration order was wrong and the 429 carried
no CSP and no `nosniff`. Found by the test that checks headers on a
rate-limited response rather than only on a 200.

HSTS is conditional on the request being HTTPS, so it cannot lock a
non-HTTPS deployment out of itself.

## CORS

**Wildcard is rejected.** `VIGILOX_CORS_ORIGINS=*` is refused rather than
honoured — a wildcard on an API that accepts uploads and review
decisions is an invitation.

The default is **same-origin**: the UI is served by the same application
that serves the API, so no CORS headers are needed at all. Configure
origins only if you split them.

## Upload validation

| Check | Behaviour |
|---|---|
| MIME type | allow-list; anything else refused at the door |
| Size | bounded; an oversize body is refused before it is read into memory |
| Empty upload | refused |
| Filename | never used to build a path — see below |
| Long filename | bounded and truncated for display, never for storage |

**The filename never reaches the filesystem.** Managed storage derives
its path from the document id:

```
<root>/<document id>/original.<ext>
```

The document id is validated against `^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$`,
which admits no `/`, no `\`, no `..`, no drive letter and no absolute
path. Pending sources are named by the store, never by the caller, and
the generated name is **re-validated on the read path** — a name arriving
from a database row is data, and data gets validated.

Every resolved path is checked to be under its root after resolution, so
a symlink cannot lead out of the tree. The archive extraction in the
restore script applies the same rule to tar members.

## Output safety

Untrusted text reaches the browser from four places: filenames, OCR text,
extracted field values, and reviewer notes. All four are rendered through
`textContent` and DOM construction, never `innerHTML`. A test asserts the
source contains no `innerHTML =` assignment, and self-checks that the
detector can still fail.

API error responses carry a **safe** code and a safe message. They never
echo OCR text, extracted values, a filename, a stack trace, or a database
error string.

## Request identity and errors

Every request carries a `request_id`, returned in the response and
present on every log line for that request. That is how an operator
correlates a user's report with the worker processing that followed,
without any identifier needing to appear in an error message.

## Logging privacy

Never logged, and asserted by a probe that drives real requests with a
hostile filename and a reviewer note and then greps every record:

```
OCR text
extracted field values
document images
identity numbers
reviewer corrections and notes
the database password
the Groq key
raw .env contents
```

`log_event` has a **closed** nine-field signature — no `**kwargs`.
Convenient ad-hoc logging is exactly how an extracted value ends up in a
log line during debugging and stays there.

uvicorn's access log is **off** (`--no-access-log`): it writes full
request paths, and this application's paths carry document ids. The proxy
keeps an access log with a deliberately chosen format instead.

## Metrics privacy

No metric label carries a document id, a job id, a filename, a reviewer
identity, or any OCR or extracted text.

A Prometheus label value creates a separate time series and the scraper
holds every series it has ever seen: `document_id` would be one series
per document, forever, and a filename would be that *plus*
user-controlled text inside a monitoring system.

Route labels are **templates** — `/api/v1/documents/{id}`, never the id.
Anything unrecognised collapses to `other` rather than being passed
through, because an unrecognised path is precisely the case that would
otherwise leak an identifier. Asserted against **rendered** output, since
the question is what actually gets scraped.

`/metrics` is off in production unless `VIGILOX_METRICS_ENABLED`, and
restricted to private ranges by the proxy.

## What is not exposed

| Refused by the proxy | Why |
|---|---|
| `/docs`, `/redoc`, `/openapi.json` | together, the complete route surface, every schema and every field name, plus a form for calling each route |
| `/metrics` | queue depth, worker state, route names — a map of the service |
| `/health/workers` | how loaded the service is and whether anyone is watching |

None are credentials. All are useful to somebody probing.

## Known limitations

Stated because a security document that claims completeness is not one.

1. **No authentication is included.** The boundary is provided and fails
   closed; wiring a real IdP is a deployment step.
2. **The application rate limiter is process-local.** The proxy is the
   authoritative limiter. Do not rely on the application's in a
   multi-replica deployment.
3. **No TLS certificate ships.** The HTTPS server block is present and
   commented out. A committed private key would be worse than nothing.
4. **`POST /api/v1/documents/analyze`** is retained for backward
   compatibility and does **not** share the async path's exact-duplicate
   short-circuit guarantees. It records source fingerprints, but its
   duplicate behaviour is intentionally legacy. The production frontend
   uses the async job API.
5. **Field confidence is not a probability of correctness.** It measures
   OCR/evidence support strength. A semantically wrong field can carry
   very high confidence — see the evaluation notes. Do not use it as a
   security or correctness signal.
6. **Audit history is append-only by convention**, not by a database
   constraint. A database superuser can alter it.
7. **Backups are not encrypted at rest** by these scripts. That is the
   backup destination's job, and it needs configuring.
