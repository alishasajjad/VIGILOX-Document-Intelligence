import argparse
import json
import os
import sys
import urllib.error
import urllib.request

from pathlib import Path


# ==========================================================
# VALIDATE A RUNNING DEPLOYMENT
# PHASE 11.15
# ==========================================================
#
# Point this at a deployment that is already up and it reports
# whether the things that matter are actually true of it.
#
# Not a test suite. The tests assert properties of the
# repository -- that the code does the right thing, that the
# compose file says the right thing. This asks a DEPLOYMENT,
# over HTTP, from outside, whether the configuration that was
# supposed to be applied was applied.
#
# Those are different questions and only the second one
# catches:
#
#   an environment variable set in the wrong compose file
#   a proxy started from a stale config
#   a volume that did not mount
#   a migration nobody ran
#   TLS terminated somewhere that strips the headers
#   the api container published directly, bypassing the proxy
#
# Every one of those passes every test in the repository.
#
#
# WHAT IT WILL NOT DO
# ----------------------------------------------------------
# It does not upload a document, does not run OCR, and does
# not call the extraction provider. Running a real document
# through a production deployment as a health check costs
# money, writes a row, and leaves a file.
#
# It does not modify anything. Every request is a GET, except
# the identity-spoofing probe, which is deliberately shaped so
# that the FAILURE it is testing for is the only outcome that
# writes.
# ==========================================================


PROJECT_ROOT = (
    Path(
        __file__
    )
    .resolve()
    .parents[2]
)

if str(
    PROJECT_ROOT
) not in sys.path:

    sys.path.insert(
        0,
        str(
            PROJECT_ROOT
        ),
    )


# ==========================================================
# RESULTS
# ==========================================================

PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"
SKIP = "SKIP"


class Report:

    def __init__(
        self,
    ) -> None:

        self.rows = []


    def record(
        self,
        *,
        outcome: str,
        check: str,
        detail: str,
    ) -> None:

        self.rows.append(
            {
                "outcome": outcome,
                "check": check,
                "detail": detail,
            }
        )

        marker = {
            PASS: "[PASS]",
            FAIL: "[FAIL]",
            WARN: "[WARN]",
            SKIP: "[SKIP]",
        }[outcome]

        print(
            f"{marker} {check}"
        )

        if detail:

            for line in detail.splitlines():

                print(
                    f"       {line}"
                )


    def count(
        self,
        outcome: str,
    ) -> int:

        return len(
            [
                row
                for row in self.rows
                if row["outcome"] == outcome
            ]
        )


# ==========================================================
# HTTP
# ==========================================================

def fetch(
    url: str,
    *,
    headers: dict | None = None,
    timeout: float = 20.0,
) -> tuple[int, dict, bytes]:

    """
    A GET that treats an error status as a result rather than
    an exception.

    A 403 from /metrics is the correct answer, and code that
    raises on it cannot distinguish "correctly refused" from
    "unreachable".
    """

    request = urllib.request.Request(
        url,
        method="GET",
    )

    for name, value in (
        headers
        or {}
    ).items():

        request.add_header(
            name,
            value,
        )

    try:

        with urllib.request.urlopen(
            request,
            timeout=timeout,
        ) as response:

            return (
                response.status,
                dict(
                    response.headers
                ),
                response.read(),
            )

    except urllib.error.HTTPError as error:

        return (
            error.code,
            dict(
                error.headers
                or {}
            ),
            error.read()
            or b"",
        )


# ==========================================================
# THE CHECKS
# ==========================================================

def check_liveness(
    report: Report,
    base: str,
) -> None:

    try:
        status, _, body = fetch(
            f"{base}/health"
        )

    except Exception as error:

        report.record(
            outcome=FAIL,
            check="the service answers /health",
            detail=(
                f"{type(error).__name__}: {error}\n"
                "Nothing below can be checked against a "
                "service that is not answering."
            ),
        )
        return

    report.record(
        outcome=(
            PASS
            if status == 200
            else FAIL
        ),
        check="the service answers /health",
        detail=f"HTTP {status}",
    )


def check_readiness(
    report: Report,
    base: str,
) -> None:

    status, _, body = fetch(
        f"{base}/health/ready",
        timeout=60,
    )

    try:
        payload = json.loads(
            body
        )

    except Exception:
        payload = {}

    if status != 200:

        report.record(
            outcome=FAIL,
            check="readiness passes",
            detail=(
                f"HTTP {status}\n"
                "The database or the storage root is "
                "unreachable from the API container. Check "
                "the volume mounts and DATABASE_URL."
            ),
        )
        return

    report.record(
        outcome=PASS,
        check="readiness passes",
        detail=(
            "database and storage reachable from the API "
            "process"
        ),
    )

    # ------------------------------------------------------
    # THE POOL AND THE THREAD POOL MUST AGREE
    # ------------------------------------------------------
    #
    # Phase 11.2. If the API admits more concurrent requests
    # than it has database connections to serve, the surplus
    # do not queue -- they time out waiting for a connection
    # and return 500 from a database that is perfectly
    # healthy. Both numbers derive from one setting, and this
    # is where a deployment that overrode one of them shows
    # up.

    capacity = payload.get(
        "capacity",
        {},
    )

    admitted = capacity.get(
        "request_concurrency"
    )

    # max_connections_per_process, which is what readiness
    # actually publishes. An earlier version of this script
    # looked for "database_connections_per_process" -- a name
    # nothing produces -- and therefore always took the branch
    # below, reporting "this deployment predates Phase 11.2"
    # about a deployment that did not.
    #
    # A validator that reports a false negative is worse than
    # one that reports nothing: it teaches an operator to
    # ignore its output.
    servable = capacity.get(
        "max_connections_per_process"
    )

    if admitted is None or servable is None:

        report.record(
            outcome=WARN,
            check="admitted concurrency matches servable",
            detail=(
                "readiness reported no capacity block, or "
                "not the keys expected.\n"
                f"keys present: {sorted(capacity)}"
            ),
        )

    elif admitted > servable:

        report.record(
            outcome=FAIL,
            check="admitted concurrency matches servable",
            detail=(
                f"{admitted} requests admitted concurrently "
                f"against {servable} database connections.\n"
                "The surplus will fail with 500 while the "
                "database is healthy. Both numbers come from "
                "VIGILOX_REQUEST_CONCURRENCY; something has "
                "overridden one of them."
            ),
        )

    else:

        report.record(
            outcome=PASS,
            check="admitted concurrency matches servable",
            detail=(
                f"{admitted} admitted, {servable} database "
                "connections per process"
            ),
        )


def check_security_headers(
    report: Report,
    base: str,
) -> None:

    status, headers, _ = fetch(
        f"{base}/health"
    )

    required = {
        "content-security-policy",
        "x-content-type-options",
        "x-frame-options",
        "referrer-policy",
    }

    present = {
        name.lower()
        for name in headers
    }

    missing = sorted(
        required - present
    )

    report.record(
        outcome=(
            PASS
            if not missing
            else FAIL
        ),
        check="security headers are present",
        detail=(
            f"{len(required)} required headers all present"
            if not missing
            else "missing: "
            + ", ".join(
                missing
            )
            + "\nThe security middleware is not in the chain, "
            "or the proxy is stripping them."
        ),
    )

    # ------------------------------------------------------
    # AND ON AN ERROR RESPONSE TOO
    # ------------------------------------------------------
    #
    # The case that is usually missed. A middleware that
    # answers without calling through -- a rate limiter
    # returning 429 -- returns a response the header
    # middleware never sees, unless the ordering is right.

    status, headers, _ = fetch(
        f"{base}/api/v1/documents/"
        "definitely-not-a-real-document-id"
    )

    present = {
        name.lower()
        for name in headers
    }

    missing = sorted(
        required - present
    )

    report.record(
        outcome=(
            PASS
            if not missing
            else FAIL
        ),
        check="security headers on an error response",
        detail=(
            f"HTTP {status} carries all {len(required)} "
            "headers"
            if not missing
            else f"HTTP {status} is missing: "
            + ", ".join(
                missing
            )
        ),
    )


def check_identity_headers_are_stripped(
    report: Report,
    base: str,
) -> None:

    # ------------------------------------------------------
    # THE MOST IMPORTANT CHECK HERE
    # ------------------------------------------------------
    #
    # The reviewer identity comes from two headers. If the
    # proxy forwards a client's copy instead of stripping it
    # and injecting its own, then anyone who can reach the
    # service can name themselves ADMIN and write audit
    # entries under any identity they like.
    #
    # nginx forwards unknown request headers by default, so
    # NOT mentioning a header is not stripping it. This is
    # the check that catches a proxy started from a config
    # that predates the strip.
    #
    # GET only. It asks the service who it thinks the caller
    # is; it does not attempt to approve anything.

    status, _, body = fetch(
        f"{base}/api/v1/reviewer/me",
        headers={
            "X-VIGILOX-REVIEWER-ID": (
                "spoofed-deployment-validator"
            ),
            "X-VIGILOX-REVIEWER-ROLE": "ADMIN",
        },
    )

    try:
        payload = json.loads(
            body
        )

    except Exception:
        payload = {}

    identity = json.dumps(
        payload
    )

    if "spoofed-deployment-validator" in identity:

        report.record(
            outcome=FAIL,
            check=(
                "a client cannot assign its own reviewer "
                "identity"
            ),
            detail=(
                "THE SERVICE ACCEPTED A BROWSER-SUPPLIED "
                "IDENTITY.\n"
                "\n"
                "Anyone who can reach this deployment can "
                "name themselves ADMIN and write review "
                "decisions and audit entries under any "
                "identity.\n"
                "\n"
                "Either the proxy is not stripping "
                "X-VIGILOX-REVIEWER-ID and "
                "X-VIGILOX-REVIEWER-ROLE, or "
                "VIGILOX_TRUSTED_PROXIES includes an "
                "address it should not, or the api container "
                "is reachable directly.\n"
                "\n"
                "Do not put this deployment into service."
            ),
        )
        return

    if status == 200:

        # An identity came back, and it was not the one
        # supplied -- so the proxy replaced it, which is
        # exactly right.
        report.record(
            outcome=PASS,
            check=(
                "a client cannot assign its own reviewer "
                "identity"
            ),
            detail=(
                "the supplied identity was discarded and an "
                "authoritative one was used instead"
            ),
        )

    elif status in (
        401,
        403,
    ):

        # Fail-closed. No proxy is injecting an identity, so
        # nothing can be approved -- which is the correct
        # posture for a deployment with no identity provider
        # wired up, and is NOT the same as being open.
        report.record(
            outcome=PASS,
            check=(
                "a client cannot assign its own reviewer "
                "identity"
            ),
            detail=(
                f"HTTP {status}: the supplied identity was "
                "refused and no identity was injected.\n"
                "This deployment fails closed -- documents "
                "can be uploaded and read, nothing can be "
                "approved. Correct if no identity provider "
                "is wired up yet."
            ),
        )

    else:

        report.record(
            outcome=WARN,
            check=(
                "a client cannot assign its own reviewer "
                "identity"
            ),
            detail=(
                f"unexpected HTTP {status}; could not "
                "determine the outcome"
            ),
        )


def check_metrics_is_not_public(
    report: Report,
    base: str,
    *,
    public: bool,
) -> None:

    # ------------------------------------------------------
    # WHETHER THIS IS A FAILURE DEPENDS ON WHERE YOU ARE
    # ------------------------------------------------------
    #
    # /metrics answering from inside the private network is
    # correct and expected -- that is who it is for. It is a
    # failure only when the address being probed is the one
    # the internet can reach.
    #
    # --expect-public says which. An earlier version of this
    # script accepted the flag and then ignored it, failing on
    # a correctly configured internal probe. Three of its four
    # reported failures on a development instance were that
    # bug rather than a finding, which is exactly how a
    # validator's output stops being read.
    # ------------------------------------------------------

    status, _, body = fetch(
        f"{base}/metrics"
    )

    exposed = (
        status == 200
        and b"vigilox_" in body
    )

    if not exposed:

        report.record(
            outcome=PASS,
            check="/metrics is not publicly readable",
            detail=f"HTTP {status}",
        )
        return

    if public:

        report.record(
            outcome=FAIL,
            check="/metrics is not publicly readable",
            detail=(
                "The metrics endpoint answered with real "
                "metrics at an address treated as PUBLIC.\n"
                "It reports queue depth, worker state and "
                "route names -- a map of the service and how "
                "loaded it is.\n"
                "Expected: refused by the proxy (403) or "
                "disabled in the application (404)."
            ),
        )
        return

    report.record(
        outcome=WARN,
        check="/metrics is not publicly readable",
        detail=(
            "answered here, which is expected for an "
            "internal address -- /metrics is for the "
            "monitoring system.\n"
            "Re-run against the public address with "
            "--expect-public to check what the internet can "
            "reach."
        ),
    )


def check_documentation_is_not_public(
    report: Report,
    base: str,
    *,
    public: bool,
) -> None:

    exposed = []

    for path in (
        "/docs",
        "/redoc",
        "/openapi.json",
    ):

        status, _, _ = fetch(
            f"{base}{path}"
        )

        if status == 200:
            exposed.append(
                path
            )

    if not exposed:

        report.record(
            outcome=PASS,
            check=(
                "the interactive API documentation is not "
                "published"
            ),
            detail=(
                "/docs, /redoc and /openapi.json are all "
                "refused"
            ),
        )
        return

    # Enabled in the application on purpose -- they are how
    # the API is read during development. The proxy is what
    # refuses them, so reachability only matters at the
    # public address.
    report.record(
        outcome=(
            FAIL
            if public
            else WARN
        ),
        check=(
            "the interactive API documentation is not "
            "published"
        ),
        detail=(
            "reachable: "
            + ", ".join(
                exposed
            )
            + (
                "\nTogether these are the complete route "
                "surface, every schema and every field "
                "name, plus a form for calling each route. "
                "The proxy must deny them."
                if public
                else "\nExpected at an internal address; "
                "they are enabled in the application "
                "deliberately and denied by the proxy. "
                "Re-run with --expect-public against the "
                "public address."
            )
        ),
    )


def check_worker_health(
    report: Report,
    base: str,
) -> None:

    status, _, body = fetch(
        f"{base}/health/workers",
        timeout=30,
    )

    if status in (
        401,
        403,
    ):

        report.record(
            outcome=SKIP,
            check="a worker is draining the queue",
            detail=(
                f"HTTP {status}: the proxy restricts "
                "/health/workers to private ranges, which is "
                "correct. Run this from inside the network "
                "to check worker health."
            ),
        )
        return

    if status != 200:

        report.record(
            outcome=WARN,
            check="a worker is draining the queue",
            detail=f"HTTP {status}",
        )
        return

    payload = json.loads(
        body
    )

    # "status", not "state". WorkerHealthService.evaluate()
    # returns state; the route publishes it as status. Reading
    # the service's name against the route's payload gave None,
    # which then fell through to the stranded-work branch and
    # reported the paging condition on every run.
    #
    # Same class of mistake as the capacity key above, and the
    # same lesson: read the payload the endpoint actually
    # returns, not the one the service builds.
    state = payload.get(
        "status"
    )

    stranded = payload.get(
        "queue_waiting_with_no_worker"
    )

    counts = payload.get(
        "workers",
        {},
    )

    if stranded:

        report.record(
            outcome=FAIL,
            check="a worker is draining the queue",
            detail=(
                f"state={state}, and there is work waiting "
                "with nothing able to do it.\n"
                "This is the outage where every other check "
                "is green: uploads accepted, 202 returned, "
                "nothing processed."
            ),
        )
        return

    if state == "NO_WORKER":

        report.record(
            outcome=WARN,
            check="a worker is draining the queue",
            detail=(
                "no worker has ever checked in. The queue is "
                "empty so nothing is stranded yet, but the "
                "first upload will sit there.\n"
                "Usually a missing compose service or a typo "
                "in the worker command."
            ),
        )
        return

    if state == "STALE":

        report.record(
            outcome=FAIL,
            check="a worker is draining the queue",
            detail=(
                "a worker checked in and then stopped. It "
                "died rather than never having started."
            ),
        )
        return

    report.record(
        outcome=PASS,
        check="a worker is draining the queue",
        detail=(
            f"status={state}, "
            f"{counts.get('running')} running, "
            f"{counts.get('total')} known, queue "
            f"{payload.get('queue', {}).get('ACTIVE_TOTAL')} "
            "active"
        ),
    )


def check_branding(
    report: Report,
    base: str,
) -> None:

    status, headers, body = fetch(
        f"{base}/favicon.ico"
    )

    report.record(
        outcome=(
            PASS
            if status == 200 and body
            else FAIL
        ),
        check="the favicon is served",
        detail=(
            f"HTTP {status}, {len(body)} bytes, "
            + headers.get(
                "Content-Type",
                "no content type",
            )
            if status == 200
            else f"HTTP {status}: the browser tab will show "
            "a blank icon"
        ),
    )

    status, _, body = fetch(
        f"{base}/dashboard"
    )

    text = body.decode(
        "utf-8",
        errors="replace",
    )

    report.record(
        outcome=(
            PASS
            if "VIGILOX" in text
            and "favicon" in text
            else FAIL
        ),
        check="the dashboard page is branded",
        detail=(
            "the page names VIGILOX and links the icon"
            if "VIGILOX" in text
            and "favicon" in text
            else "the page did not reference VIGILOX and the "
            "icon; check the static mount"
        ),
    )


def check_schema_is_current(
    report: Report,
) -> None:

    # ------------------------------------------------------
    # NOT OVER HTTP
    # ------------------------------------------------------
    #
    # The application does not report its schema revision and
    # should not: an unauthenticated caller learning the
    # migration head learns which version is deployed.
    #
    # So this needs DATABASE_URL, and is skipped when run from
    # somewhere that does not have it -- which is most places
    # this script should be run from.

    url = os.getenv(
        "DATABASE_URL",
        "",
    ).strip()

    if not url:

        report.record(
            outcome=SKIP,
            check="the database schema is at head",
            detail=(
                "DATABASE_URL is not set here. Run this "
                "check from the migration container:\n"
                "  docker compose run --rm migrate "
                "alembic current"
            ),
        )
        return

    try:

        import sqlalchemy as sa

        from alembic.config import Config
        from alembic.script import ScriptDirectory

        head = ScriptDirectory.from_config(
            Config(
                str(
                    PROJECT_ROOT
                    / "alembic.ini"
                )
            )
        ).get_current_head()

        engine = sa.create_engine(
            url
        )

        try:

            with engine.connect() as connection:

                applied = connection.execute(
                    sa.text(
                        "select version_num "
                        "from alembic_version"
                    )
                ).scalar()

        finally:
            engine.dispose()

    except Exception as error:

        report.record(
            outcome=WARN,
            check="the database schema is at head",
            detail=(
                f"could not determine: "
                f"{type(error).__name__}: {error}"
            ),
        )
        return

    report.record(
        outcome=(
            PASS
            if applied == head
            else FAIL
        ),
        check="the database schema is at head",
        detail=(
            f"at {applied}"
            if applied == head
            else f"database is at {applied}, the code "
            f"expects {head}.\n"
            "Run the migration container. The application "
            "will fail on queries for columns that do not "
            "exist yet, which presents as unrelated errors."
        ),
    )


def check_storage_roots_are_separate(
    report: Report,
) -> None:

    # Local check, same reasoning as the schema one: the
    # application does not publish its storage paths.

    try:

        from backend.app.services.document_storage_service import (  # noqa: E501
            DocumentStorageService,
        )

        from backend.app.services.job_source_store import (
            JobSourceStore,
        )

        managed = DocumentStorageService().storage_root

        pending = JobSourceStore().pending_root

    except Exception as error:

        report.record(
            outcome=SKIP,
            check=(
                "managed and pending storage are separate "
                "trees"
            ),
            detail=(
                f"not checkable from here: "
                f"{type(error).__name__}"
            ),
        )
        return

    overlapping = (
        managed == pending
        or managed in pending.parents
        or pending in managed.parents
    )

    report.record(
        outcome=(
            FAIL
            if overlapping
            else PASS
        ),
        check=(
            "managed and pending storage are separate trees"
        ),
        detail=(
            f"managed {managed}\npending {pending}"
            + (
                "\nTHEY OVERLAP. The integrity scan will "
                "class every in-flight upload as an orphan, "
                "and reconciliation deletes orphans."
                if overlapping
                else ""
            )
        ),
    )


# ==========================================================
# MAIN
# ==========================================================

def main() -> int:

    parser = argparse.ArgumentParser(
        description=(
            "Validate a running VIGILOX deployment from "
            "outside it."
        ),
    )

    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help=(
            "The address to probe. Use the PUBLIC address to "
            "check what the internet can reach; use the "
            "internal one to check worker health and "
            "metrics."
        ),
    )

    parser.add_argument(
        "--expect-public",
        action="store_true",
        help=(
            "Treat this address as internet-facing. "
            "Restricted endpoints answering here become "
            "failures rather than notes."
        ),
    )

    arguments = parser.parse_args()

    base = arguments.base_url.rstrip(
        "/"
    )

    print(
        "=" * 62
    )
    print(
        "VIGILOX DEPLOYMENT VALIDATION"
    )
    print(
        "=" * 62
    )
    print(
        f"  target: {base}"
    )
    print(
        "  treating this address as: "
        + (
            "PUBLIC"
            if arguments.expect_public
            else "internal / unspecified"
        )
    )
    print(
        "=" * 62
    )
    print()

    report = Report()

    check_liveness(
        report,
        base,
    )

    if report.count(
        FAIL
    ):

        print()
        print(
            "The service is not answering. Nothing else can "
            "be validated."
        )
        return 1

    check_readiness(
        report,
        base,
    )

    check_security_headers(
        report,
        base,
    )

    check_identity_headers_are_stripped(
        report,
        base,
    )

    check_metrics_is_not_public(
        report,
        base,
        public=arguments.expect_public,
    )

    check_documentation_is_not_public(
        report,
        base,
        public=arguments.expect_public,
    )

    check_worker_health(
        report,
        base,
    )

    check_branding(
        report,
        base,
    )

    check_schema_is_current(
        report
    )

    check_storage_roots_are_separate(
        report
    )

    print()
    print(
        "=" * 62
    )
    print(
        f"PASS {report.count(PASS)}   "
        f"FAIL {report.count(FAIL)}   "
        f"WARN {report.count(WARN)}   "
        f"SKIP {report.count(SKIP)}"
    )
    print(
        "=" * 62
    )

    if report.count(
        FAIL
    ):

        print()
        print(
            "FAILURES:"
        )

        for row in report.rows:

            if row["outcome"] == FAIL:

                print(
                    f"  - {row['check']}"
                )

        print()
        print(
            "Do not put this deployment into service until "
            "these are resolved."
        )

        return 1

    if report.count(
        SKIP
    ):

        print()
        print(
            "Some checks were skipped. A skipped check is "
            "not a passing one -- see the notes above for "
            "where to run each from."
        )

    print()
    print(
        "No failures."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
