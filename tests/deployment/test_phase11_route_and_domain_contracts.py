"""
==========================================================
PHASE 11.4 - ROUTE STRUCTURE AND DOMAIN CONTRACTS
==========================================================

WHY THE ROUTES WERE NOT REFACTORED
----------------------------------------------------------
backend/app/main.py holds sixteen route handlers inline and
runs to about three thousand lines, while the newer job
routes live in their own APIRouter. That inconsistency is
real, and moving the older routes into routers is still the
wrong change to make during a release cycle:

  - route match precedence depends on registration order,
    and /review/{document_id} sits beside /review
  - error handlers, request-context middleware and
    app.state wiring are all registered against the app in
    a specific order
  - the routes are covered by tests that assert responses,
    not structure, so a subtle precedence change would pass
    them

The benefit is readability. The risk is a silently
mis-registered route on a production deployment. So this
phase AUDITS the route surface instead of rearranging it,
and the audit is what a later refactor can be checked
against.


WHAT THIS SUITE IS PROTECTING

  1. THE ROUTE SURFACE IS WHAT WE THINK IT IS.
     Asserted against the OpenAPI document, which is what a
     client actually sees -- and which turned out to be the
     only reliable view: in this FastAPI version an included
     router appears in app.routes as a single opaque
     _IncludedRouter, so walking app.routes silently misses
     every job route.

  2. NO ROUTE IS SHADOWED.
     A literal path registered after a matching {parameter}
     route on the same prefix is unreachable, and nothing
     about that is visible in the code.

  3. VERSIONING IS CONSISTENT.
     Business resources under /api/v1. Process probes
     unversioned. Pages unversioned and out of the schema.

  4. THE DOMAIN VOCABULARY IS ACTUALLY USED.
     A constant that names a rule while the code implementing
     the rule spells it out separately is worse than no
     constant: it reads as a single definition and is not
     one. Phase 10.5 found a duplicated critical-field list
     hiding a real error, and Phase 10.6 found an
     evidence-flag parser reimplemented in JavaScript. This
     asserts the job-queue equivalent behaviourally.
"""

import json
import os
import subprocess
import sys
import tempfile
import uuid

from datetime import datetime, timedelta, timezone
from pathlib import Path


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
# ASSERTIONS
# ==========================================================

def assert_equal(
    actual,
    expected,
    message: str,
) -> None:

    if actual != expected:

        raise AssertionError(
            f"{message}\n"
            f"Expected: {expected!r}\n"
            f"Actual:   {actual!r}"
        )


def assert_true(
    value,
    message: str,
) -> None:

    if not value:
        raise AssertionError(
            message
        )


def section(
    title: str,
) -> None:

    print()
    print(
        "-" * 74
    )
    print(
        title
    )
    print(
        "-" * 74
    )


def ok(
    message: str,
) -> None:

    print(
        f"[PASS] {message}"
    )


# ==========================================================
# THE ROUTE SURFACE
# ==========================================================
#
# Read in a subprocess with the pipeline disabled. Importing
# the app builds PaddleOCR otherwise -- seconds and hundreds
# of megabytes for a test that only reads a route table.
# ==========================================================

def openapi_document() -> dict:

    code = """
import json

from fastapi.testclient import TestClient

from backend.app.main import app


with TestClient(app) as client:

    print(json.dumps(client.get("/openapi.json").json()))
"""

    environment = dict(
        os.environ
    )

    environment["PYTHONPATH"] = str(
        PROJECT_ROOT
    )

    environment["VIGILOX_API_EAGER_PIPELINE"] = "false"

    with tempfile.TemporaryDirectory() as directory:

        script = (
            Path(
                directory
            )
            / "spec.py"
        )

        script.write_text(
            code,
            encoding="utf-8",
        )

        completed = subprocess.run(
            [
                sys.executable,
                str(
                    script
                ),
            ],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(
                PROJECT_ROOT
            ),
            env=environment,
        )

    assert_equal(
        completed.returncode,
        0,
        (
            "The application must produce an OpenAPI "
            "document.\n"
            f"{completed.stdout[-2000:]}\n"
            f"{completed.stderr[-2000:]}"
        ),
    )

    lines = [
        line
        for line in completed.stdout.splitlines()
        if line.strip().startswith(
            "{"
        )
    ]

    assert_true(
        lines,
        "No JSON document was printed.",
    )

    return json.loads(
        lines[-1]
    )


ROUTE_TABLE_PROBE = '\nimport json\n\nfrom backend.app.main import app\n\n\nrows = []\nmounts = []\n\nfor route in app.routes:\n\n    path = getattr(route, "path", None)\n\n    if path is None:\n        continue\n\n    methods = getattr(route, "methods", None)\n\n    if methods is None:\n        mounts.append(path)\n        continue\n\n    rows.append(\n        {\n            "path": path,\n            "methods": sorted(\n                method.lower()\n                for method in methods\n            ),\n            "in_schema": bool(\n                getattr(\n                    route,\n                    "include_in_schema",\n                    False,\n                )\n            ),\n        }\n    )\n\nprint(\n    json.dumps(\n        {\n            "routes": rows,\n            "mounts": sorted(mounts),\n        }\n    )\n)\n'


def registered_routes() -> dict:

    """
    The route table, which is the only view that sees routes
    hidden from the OpenAPI document.

    Neither view is complete on its own. Routes on an included
    router are opaque in app.routes in this FastAPI version;
    routes with include_in_schema=False are absent from the
    document. TEST 1 uses the document, TEST 6 uses this, and
    between them every served path is accounted for.
    """

    code = ROUTE_TABLE_PROBE

    return _run_against_the_app(
        code,
        "The application must expose a route table.",
    )


def _run_against_the_app(
    code: str,
    failure: str,
) -> dict:

    environment = dict(
        os.environ
    )

    environment["PYTHONPATH"] = str(
        PROJECT_ROOT
    )

    environment["VIGILOX_API_EAGER_PIPELINE"] = "false"

    with tempfile.TemporaryDirectory() as directory:

        script = (
            Path(
                directory
            )
            / "probe.py"
        )

        script.write_text(
            code,
            encoding="utf-8",
        )

        completed = subprocess.run(
            [
                sys.executable,
                str(
                    script
                ),
            ],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(
                PROJECT_ROOT
            ),
            env=environment,
        )

    assert_equal(
        completed.returncode,
        0,
        (
            failure
            + chr(10)
            + completed.stdout[-2000:]
            + chr(10)
            + completed.stderr[-2000:]
        ),
    )

    lines = [
        line
        for line in completed.stdout.splitlines()
        if line.strip().startswith(
            "{"
        )
    ]

    assert_true(
        lines,
        "No JSON document was printed.",
    )

    return json.loads(
        lines[-1]
    )


# ==========================================================
# TEST 1 - THE ROUTE SURFACE
# ==========================================================

EXPECTED_API_PATHS = {
    "/api/v1/dashboard/summary": {
        "get",
    },
    "/api/v1/document-batches": {
        "post",
    },
    "/api/v1/document-batches/{batch_id}": {
        "get",
    },
    "/api/v1/document-jobs": {
        "post",
    },
    "/api/v1/document-jobs/{job_id}": {
        "get",
    },
    "/api/v1/documents": {
        "get",
    },
    "/api/v1/documents/analyze": {
        "post",
    },
    "/api/v1/documents/{document_id}": {
        "get",
    },
    "/api/v1/documents/{document_id}/history": {
        "get",
    },
    "/api/v1/documents/{document_id}/image": {
        "get",
    },
    "/api/v1/documents/{document_id}/reviews": {
        "post",
    },
    "/api/v1/reviewer/me": {
        "get",
    },
    "/api/v1/reviews/queue": {
        "get",
    },
    "/health": {
        "get",
    },
    "/health/ready": {
        "get",
    },
    "/health/workers": {
        "get",
    },
}


# ==========================================================
# THE ROUTES THAT ARE NOT IN THE DOCUMENT
# ==========================================================
#
# TEST 1 reads the OpenAPI document, which is the reliable
# view of the included routers in this FastAPI version. It has
# one blind spot, and 11.11 walked straight into it:
# include_in_schema=False removes a route from the document
# while leaving it fully served. /metrics and /favicon.ico
# were both added that way, and the exact-surface assertion
# that exists to force a review of every new route said
# nothing about either.
#
# So the hidden half is asserted too, from the route table
# rather than the document. Hidden is a deliberate property of
# a few specific routes -- pages, an icon, a scrape endpoint,
# the framework's own docs -- and every one of them still has
# to be listed by somebody.
# ==========================================================

EXPECTED_HIDDEN_PATHS = {

    # The HTML pages. Not API, and documenting them in an API
    # specification would suggest they were.
    "/dashboard": {"get"},
    "/documents": {"get"},
    "/review": {"get"},
    "/review/{document_id}": {"get"},
    "/upload": {"get"},

    # Browser chrome. Requested by every page load, useful to
    # nobody reading the API.
    "/favicon.ico": {"get"},

    # Prometheus scrape. Hidden AND refused in production
    # unless VIGILOX_METRICS_ENABLED, AND restricted to
    # private ranges by the proxy.
    "/metrics": {"get"},

    # FastAPI's own. Listed here so their presence is a
    # decision on the record rather than a default nobody
    # looked at -- see TEST 6.
    "/docs": {"get", "head"},
    "/docs/oauth2-redirect": {"get", "head"},
    "/redoc": {"get", "head"},
    "/openapi.json": {"get", "head"},
}


# The static mount. A Mount has no methods, so it cannot go
# in the table above, but it is part of what is served.
EXPECTED_MOUNTS = {
    "/review/static",
}


def test_route_surface():

    section(
        "TEST 1 - THE DOCUMENTED ROUTE SURFACE IS EXACTLY "
        "WHAT IS EXPECTED"
    )

    spec = openapi_document()

    actual = {
        path: {
            method.lower()
            for method in operations
            if method.lower()
            in (
                "get",
                "post",
                "put",
                "patch",
                "delete",
            )
        }
        for path, operations in spec[
            "paths"
        ].items()
    }

    assert_equal(
        sorted(
            actual
        ),
        sorted(
            EXPECTED_API_PATHS
        ),
        (
            "The documented route surface changed.\n"
            "This assertion is exact on purpose: a route "
            "added without being noticed here is a route "
            "nobody reviewed, and a route that disappears is "
            "a client breaking."
        ),
    )

    for path, methods in EXPECTED_API_PATHS.items():

        assert_equal(
            actual[path],
            methods,
            f"{path} must expose exactly {sorted(methods)}.",
        )

    ok(
        f"{len(actual)} documented paths, each with exactly "
        f"the expected methods"
    )


    # ------------------------------------------------------
    # THE JOB ROUTES ARE REACHABLE AT ALL
    # ------------------------------------------------------
    # Worth its own assertion. In this FastAPI version an
    # included router appears in app.routes as one opaque
    # _IncludedRouter with no path and no children reachable
    # by attribute, so anything auditing app.routes sees the
    # sixteen inline routes and none of the four job routes.
    #
    # An audit that cannot see a route cannot protect it.
    # ------------------------------------------------------

    job_paths = sorted(
        path
        for path in actual
        if "document-job" in path
        or "document-batch" in path
    )

    assert_equal(
        job_paths,
        [
            "/api/v1/document-batches",
            "/api/v1/document-batches/{batch_id}",
            "/api/v1/document-jobs",
            "/api/v1/document-jobs/{job_id}",
        ],
        (
            "All four async job routes must appear in the "
            "OpenAPI document. They live on an APIRouter, and "
            "walking app.routes does not find them in this "
            "FastAPI version -- which is why this suite reads "
            "the specification instead."
        ),
    )

    ok(
        "all 4 async job routes appear, which walking "
        "app.routes would have missed entirely"
    )


# ==========================================================
# TEST 2 - VERSIONING
# ==========================================================

def test_versioning_is_consistent():

    section(
        "TEST 2 - BUSINESS RESOURCES ARE VERSIONED, PROBES "
        "ARE NOT"
    )

    spec = openapi_document()

    unversioned = sorted(
        path
        for path in spec["paths"]
        if not path.startswith(
            "/api/v1/"
        )
    )

    assert_equal(
        unversioned,
        [
            "/health",
            "/health/ready",
            "/health/workers",
        ],
        (
            "Only the process probes may sit outside "
            "/api/v1.\n"
            "A business resource on an unversioned path "
            "cannot be changed without breaking every client "
            "at once, which is the entire reason the prefix "
            "exists.\n"
            "Probes are deliberately outside it: they are "
            "infrastructure, and an orchestrator's "
            "livenessProbe should not have to know the API "
            "version."
        ),
    )

    ok(
        "the only unversioned documented paths are "
        + ", ".join(
            unversioned
        )
    )


    # ------------------------------------------------------
    # THE HTML PAGES STAY OUT OF THE API DOCUMENT
    # ------------------------------------------------------

    for page in (
        "/dashboard",
        "/documents",
        "/review",
        "/upload",
        "/review/{document_id}",
    ):

        assert_true(
            page not in spec["paths"],
            (
                f"{page} serves an HTML page and must not "
                f"appear in the API specification. A client "
                f"generated from this document would treat it "
                f"as an endpoint."
            ),
        )

    ok(
        "5 HTML page routes are excluded from the API "
        "specification"
    )


    # ------------------------------------------------------
    # EVERY OPERATION IS TAGGED AND DESCRIBED
    # ------------------------------------------------------

    untagged = []

    for path, operations in spec[
        "paths"
    ].items():

        for method, operation in operations.items():

            if method.lower() not in (
                "get",
                "post",
                "put",
                "patch",
                "delete",
            ):
                continue

            if not operation.get(
                "tags"
            ):
                untagged.append(
                    f"{method.upper()} {path}"
                )

    assert_equal(
        untagged,
        [],
        (
            f"These operations carry no tag: {untagged}.\n"
            "An untagged operation lands in a default bucket "
            "in the generated documentation, which is where "
            "endpoints go to be overlooked."
        ),
    )

    tags = sorted(
        {
            tag
            for operations in spec[
                "paths"
            ].values()
            for operation in operations.values()
            if isinstance(
                operation,
                dict,
            )
            for tag in operation.get(
                "tags",
                [],
            )
        }
    )

    ok(
        f"every operation is tagged; tags in use: "
        f"{', '.join(tags)}"
    )


# ==========================================================
# TEST 3 - NOTHING IS SHADOWED
# ==========================================================

def test_no_shadowed_routes():

    section(
        "TEST 3 - NO LITERAL PATH IS SWALLOWED BY A "
        "PARAMETER ROUTE"
    )

    # A literal segment registered AFTER a {parameter} route
    # on the same prefix is unreachable: the parameter route
    # matches first and the literal one never runs.
    #
    # /api/v1/documents/analyze and
    # /api/v1/documents/{document_id} are exactly that shape,
    # so this is not hypothetical.
    #
    # Registration order is what decides it, so this reads
    # app.routes -- the specification does not carry order.

    code = """
import json

from backend.app.main import app


ordered = []

for route in app.routes:

    path = getattr(route, "path", None)

    if not path:
        continue

    ordered.append(
        {
            "path": path,
            "methods": sorted(
                getattr(route, "methods", set()) or set()
            ),
        }
    )

print(json.dumps(ordered))
"""

    environment = dict(
        os.environ
    )

    environment["PYTHONPATH"] = str(
        PROJECT_ROOT
    )

    environment["VIGILOX_API_EAGER_PIPELINE"] = "false"

    with tempfile.TemporaryDirectory() as directory:

        script = (
            Path(
                directory
            )
            / "order.py"
        )

        script.write_text(
            code,
            encoding="utf-8",
        )

        completed = subprocess.run(
            [
                sys.executable,
                str(
                    script
                ),
            ],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(
                PROJECT_ROOT
            ),
            env=environment,
        )

    assert_equal(
        completed.returncode,
        0,
        (
            "The route order must be readable.\n"
            f"{completed.stderr[-2000:]}"
        ),
    )

    ordered = json.loads(
        [
            line
            for line in completed.stdout.splitlines()
            if line.strip().startswith(
                "["
            )
        ][-1]
    )

    assert_true(
        ordered,
        "The route order probe found no routes.",
    )


    # ------------------------------------------------------
    # SHADOWING, DETECTED
    # ------------------------------------------------------

    def segments(
        path: str,
    ) -> list[str]:

        return [
            part
            for part in path.split(
                "/"
            )
            if part
        ]

    shadowed = []

    for index, later in enumerate(
        ordered
    ):

        later_parts = segments(
            later["path"]
        )

        # A literal path: no {parameter} anywhere in it.
        if any(
            part.startswith(
                "{"
            )
            for part in later_parts
        ):
            continue

        for earlier in ordered[:index]:

            earlier_parts = segments(
                earlier["path"]
            )

            if len(
                earlier_parts
            ) != len(
                later_parts
            ):
                continue

            if not set(
                earlier["methods"]
            ) & set(
                later["methods"]
            ):
                continue

            matches = all(
                expected.startswith(
                    "{"
                )
                or expected == actual
                for expected, actual in zip(
                    earlier_parts,
                    later_parts,
                )
            )

            has_parameter = any(
                part.startswith(
                    "{"
                )
                for part in earlier_parts
            )

            if matches and has_parameter:
                shadowed.append(
                    f"{later['path']} is unreachable: "
                    f"{earlier['path']} is registered first "
                    f"and matches it"
                )

    # SELF-CHECK. The detector must be able to see a real
    # case, or an empty result means nothing.
    probe = [
        {
            "path": "/api/v1/documents/{document_id}",
            "methods": [
                "GET",
            ],
        },
        {
            "path": "/api/v1/documents/analyze",
            "methods": [
                "GET",
            ],
        },
    ]

    detected = []

    for index, later in enumerate(
        probe
    ):

        later_parts = segments(
            later["path"]
        )

        if any(
            part.startswith(
                "{"
            )
            for part in later_parts
        ):
            continue

        for earlier in probe[:index]:

            earlier_parts = segments(
                earlier["path"]
            )

            if len(
                earlier_parts
            ) != len(
                later_parts
            ):
                continue

            if not set(
                earlier["methods"]
            ) & set(
                later["methods"]
            ):
                continue

            if all(
                expected.startswith(
                    "{"
                )
                or expected == actual
                for expected, actual in zip(
                    earlier_parts,
                    later_parts,
                )
            ):
                detected.append(
                    later["path"]
                )

    assert_true(
        detected,
        (
            "The shadowing detector cannot see a constructed "
            "case where /documents/{document_id} precedes "
            "/documents/analyze. It is broken, and the "
            "assertion below would pass for the wrong "
            "reason."
        ),
    )

    assert_equal(
        shadowed,
        [],
        (
            "A route is unreachable:\n"
            + "\n".join(
                shadowed
            )
            + "\nNothing in the source makes this visible. "
            "The literal path simply never runs."
        ),
    )

    ok(
        f"{len(ordered)} registered routes, none shadowed "
        f"(detector self-checked against a constructed case)"
    )


# ==========================================================
# TEST 4 - THE CLAIMABLE STATUSES ARE THE DOMAIN'S
# ==========================================================

def test_claimable_statuses_come_from_the_domain():

    section(
        "TEST 4 - THE CLAIM QUERY CLAIMS EXACTLY THE "
        "STATUSES THE DOMAIN CALLS CLAIMABLE"
    )

    from backend.app.domain.job_states import (
        CLAIMABLE_STATUSES,
        COMPLETED,
        FAILED,
        PROCESSING,
        QUEUED,
        RETRY_WAIT,
    )

    from database.database import SessionLocal

    from database.job_repositories import (
        DocumentJobRepository,
    )

    from database.models import DocumentJobModel

    from sqlalchemy.orm import Session


    # ------------------------------------------------------
    # A JOB IN EVERY STATUS
    # ------------------------------------------------------
    # Behavioural rather than textual. Grepping the query for
    # the constant would prove it is mentioned; putting a job
    # in each status and seeing which come back proves what
    # the query does.
    # ------------------------------------------------------

    marker = uuid.uuid4().hex[:10]

    every_status = (
        QUEUED,
        PROCESSING,
        RETRY_WAIT,
        COMPLETED,
        FAILED,
    )

    created: dict[str, str] = {}

    past = datetime.now(
        timezone.utc
    ) - timedelta(
        hours=1
    )

    with Session(
        SessionLocal.kw["bind"]
    ) as session:

        for status in every_status:

            identifier = (
                f"claimtest-{marker}-{status}"
            )

            session.add(
                DocumentJobModel(
                    id=identifier,
                    status=status,
                    original_filename=(
                        f"{identifier}.jpg"
                    ),
                    content_type="image/jpeg",
                    source_name=(
                        f"{identifier}.jpg"
                    ),

                    # Backoff already elapsed, so RETRY_WAIT
                    # is genuinely eligible. Leaving it in the
                    # future would make RETRY_WAIT look
                    # unclaimable for the wrong reason.
                    next_attempt_at=past,

                    # No fingerprint: the partial unique index
                    # would otherwise refuse the second active
                    # job, and this test is about status, not
                    # duplicates.
                    source_sha256=None,
                )
            )

            created[status] = identifier

        session.commit()

    try:

        claimed_statuses = set()

        with SessionLocal() as session:

            repository = DocumentJobRepository(
                session
            )

            # Confined to the jobs this test created, so a
            # real queued upload cannot be claimed by a test.
            remaining = set(
                created.values()
            )

            while remaining:

                claimed = repository.claim_next(
                    worker_id=(
                        f"claimtest-{marker}"
                    ),
                    lease_seconds=30,
                    only_job_ids=remaining,
                )

                if claimed is None:
                    break

                # claim_next returns the ORM row, not a
                # payload dict. The worker builds the payload;
                # the repository hands back the model.
                claimed_id = claimed.id

                claimed_statuses.add(
                    next(
                        status
                        for status, identifier
                        in created.items()
                        if identifier == claimed_id
                    )
                )

                remaining.discard(
                    claimed_id
                )

            session.commit()

        assert_equal(
            sorted(
                claimed_statuses
            ),
            sorted(
                CLAIMABLE_STATUSES
            ),
            (
                "The claim query claims a different set of "
                "statuses than CLAIMABLE_STATUSES names.\n"
                "The constant used to be decorative: the "
                "query spelled out 'QUEUED' and 'RETRY_WAIT' "
                "as literals, so the constant read as a "
                "single definition of claimable and was not "
                "one.\n"
                "That is the same shape of duplication that "
                "hid a critical-field error in Phase 10.5."
            ),
        )

        ok(
            f"a job in each of {len(every_status)} statuses: "
            f"exactly {sorted(claimed_statuses)} were "
            f"claimed, matching CLAIMABLE_STATUSES"
        )


        # --------------------------------------------------
        # AND BACKOFF STILL GATES RETRY_WAIT
        # --------------------------------------------------
        # Deriving membership from the constant must not have
        # dropped the backoff condition -- that comparison is
        # the whole retry mechanism.
        # --------------------------------------------------

        future_id = (
            f"claimtest-{marker}-future"
        )

        with Session(
            SessionLocal.kw["bind"]
        ) as session:

            session.add(
                DocumentJobModel(
                    id=future_id,
                    status=RETRY_WAIT,
                    original_filename=(
                        f"{future_id}.jpg"
                    ),
                    content_type="image/jpeg",
                    source_name=(
                        f"{future_id}.jpg"
                    ),
                    next_attempt_at=(
                        datetime.now(
                            timezone.utc
                        )
                        + timedelta(
                            hours=1
                        )
                    ),
                    source_sha256=None,
                )
            )

            session.commit()

        created["future"] = future_id

        with SessionLocal() as session:

            claimed = DocumentJobRepository(
                session
            ).claim_next(
                worker_id=(
                    f"claimtest-{marker}-b"
                ),
                lease_seconds=30,
                only_job_ids={
                    future_id,
                },
            )

            session.commit()

        assert_equal(
            claimed,
            None,
            (
                "A RETRY_WAIT job whose backoff has NOT "
                "elapsed was claimed.\n"
                "The next_attempt_at comparison is the entire "
                "retry backoff mechanism. Deriving the status "
                "set from the domain constant must not have "
                "removed it."
            ),
        )

        ok(
            "a RETRY_WAIT job with backoff still pending is "
            "not claimed, so the backoff gate survived"
        )

    finally:

        with Session(
            SessionLocal.kw["bind"]
        ) as session:

            for identifier in created.values():

                row = session.get(
                    DocumentJobModel,
                    identifier,
                )

                if row is not None:
                    session.delete(
                        row
                    )

            session.commit()


# ==========================================================
# TEST 5 - THE RESPONSE-MODEL POSITION IS DELIBERATE
# ==========================================================

def test_response_model_position():

    section(
        "TEST 5 - RESPONSE MODELS COVER THE FIXED-SHAPE "
        "RESPONSES AND NOT THE DERIVED ONES"
    )

    spec = openapi_document()

    def has_schema(
        path: str,
        method: str = "get",
    ) -> bool:

        operation = spec[
            "paths"
        ][path][method]

        content = (
            operation.get(
                "responses",
                {},
            )
            .get(
                "200",
                {},
            )
            .get(
                "content",
                {},
            )
            .get(
                "application/json",
                {},
            )
            .get(
                "schema",
                {},
            )
        )

        return bool(
            content.get(
                "$ref"
            )
        )


    # ------------------------------------------------------
    # THE THREE THAT SHOULD HAVE ONE
    # ------------------------------------------------------
    # Fixed shapes, and the ones a client is most likely to
    # generate code against.
    # ------------------------------------------------------

    for path in (
        "/api/v1/documents",
        "/api/v1/reviews/queue",
        "/api/v1/dashboard/summary",
    ):

        assert_true(
            has_schema(
                path
            ),
            (
                f"{path} returns a fixed shape and must "
                f"declare a response model, so a generated "
                f"client has a contract."
            ),
        )

    ok(
        "the 3 list and summary endpoints declare a response "
        "model"
    )


    # ------------------------------------------------------
    # AND THE ONE THAT MUST NOT
    # ------------------------------------------------------
    # This is the part worth writing down.
    #
    # GET /api/v1/documents/{document_id} returns an
    # open-ended derived payload: analysis, classification,
    # duplicate, findings, final_record. Three of those five
    # were added in Phase 10 alone.
    #
    # A Pydantic response_model does not just document a
    # response, it FILTERS it. Any key the model does not
    # declare is silently dropped. Attaching one here would
    # have removed the entire normalized findings block from
    # the response the day Phase 10.6 shipped, with no error
    # anywhere -- the endpoint would have kept returning 200
    # and the workspace would have quietly fallen back to its
    # legacy rendering path.
    #
    # So it is deliberately absent, and this test is what
    # stops someone adding one for tidiness.
    # ------------------------------------------------------

    assert_true(
        not has_schema(
            "/api/v1/documents/{document_id}"
        ),
        (
            "GET /api/v1/documents/{document_id} must NOT "
            "declare a response model.\n"
            "response_model FILTERS the response: every key "
            "the model does not declare is silently dropped. "
            "This endpoint returns analysis, classification, "
            "duplicate, findings and final_record, and three "
            "of those were added during Phase 10.\n"
            "A model attached for tidiness would have deleted "
            "the normalized findings block from the API the "
            "day it shipped, with a 200 and no error."
        ),
    )

    ok(
        "the document detail endpoint declares no response "
        "model, so a derived block added later is not "
        "silently filtered out"
    )


    # ------------------------------------------------------
    # AND THE FIELDS ADDED IN PHASE 10 ACTUALLY ARRIVE
    # ------------------------------------------------------
    # The assertion above is about a mechanism. This one
    # checks the consequence directly.
    # ------------------------------------------------------

    code = """
import json

from fastapi.testclient import TestClient

from backend.app.main import app


with TestClient(app) as client:

    listed = client.get(
        "/api/v1/documents",
        params={"limit": 1},
    ).json()

    items = listed.get("items") or []

    if not items:
        print(json.dumps({"skipped": "no documents"}))

    else:
        detail = client.get(
            "/api/v1/documents/"
            + items[0]["document_id"]
        ).json()

        print(
            json.dumps(
                {
                    "keys": sorted(detail.keys()),
                }
            )
        )
"""

    environment = dict(
        os.environ
    )

    environment["PYTHONPATH"] = str(
        PROJECT_ROOT
    )

    environment["VIGILOX_API_EAGER_PIPELINE"] = "false"

    with tempfile.TemporaryDirectory() as directory:

        script = (
            Path(
                directory
            )
            / "detail.py"
        )

        script.write_text(
            code,
            encoding="utf-8",
        )

        completed = subprocess.run(
            [
                sys.executable,
                str(
                    script
                ),
            ],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(
                PROJECT_ROOT
            ),
            env=environment,
        )

    assert_equal(
        completed.returncode,
        0,
        (
            "The detail probe must run.\n"
            f"{completed.stderr[-2000:]}"
        ),
    )

    observed = json.loads(
        [
            line
            for line in completed.stdout.splitlines()
            if line.strip().startswith(
                "{"
            )
        ][-1]
    )

    if "skipped" in observed:

        print(
            "       (no documents in the database to check "
            "the detail payload against)"
        )

    else:

        for key in (
            "analysis",
            "classification",
            "duplicate",
            "findings",
            "final_record",
            "human_review",
        ):

            assert_true(
                key in observed["keys"],
                (
                    f"The detail response is missing "
                    f"'{key}'. If a response model were "
                    f"attached to this route, this is exactly "
                    f"how the loss would present: a 200, and "
                    f"a key simply gone."
                ),
            )

        ok(
            f"the live detail response carries all "
            f"{len(observed['keys'])} top-level keys "
            f"including classification, duplicate and "
            f"findings"
        )


# ==========================================================
# MAIN
# ==========================================================

# ==========================================================
# TEST 6 - THE HIDDEN ROUTE SURFACE
# ==========================================================

def test_hidden_route_surface():

    section(
        "TEST 6 - EVERY ROUTE HIDDEN FROM THE DOCUMENT IS "
        "STILL DECLARED"
    )

    table = registered_routes()

    hidden = {
        row["path"]: set(
            row["methods"]
        )
        for row in table["routes"]
        if not row["in_schema"]
    }

    assert_equal(
        sorted(
            hidden
        ),
        sorted(
            EXPECTED_HIDDEN_PATHS
        ),
        (
            "The set of routes served but absent from the "
            "OpenAPI document changed.\n"
            "include_in_schema=False hides a route from TEST "
            "1 without hiding it from the internet. That is "
            "how /metrics and /favicon.ico were added in "
            "11.11 and 11.16 without either being reviewed "
            "against the route surface."
        ),
    )

    for path, methods in EXPECTED_HIDDEN_PATHS.items():

        assert_equal(
            hidden[path],
            methods,
            f"{path} must expose exactly {sorted(methods)}.",
        )

    ok(
        f"{len(hidden)} hidden routes, all declared: "
        + ", ".join(
            sorted(
                hidden
            )
        )
    )

    assert_equal(
        set(
            table["mounts"]
        ),
        EXPECTED_MOUNTS,
        (
            "The set of mounted static directories changed. "
            "A mount serves whatever is under it, so an "
            "unreviewed one is a directory nobody chose to "
            "publish."
        ),
    )

    ok(
        "the only static mount is "
        + ", ".join(
            sorted(
                EXPECTED_MOUNTS
            )
        )
    )

    # ------------------------------------------------------
    # AND THE TWO VIEWS TOGETHER COVER EVERYTHING
    # ------------------------------------------------------
    #
    # The point of running both: neither the document nor the
    # route table sees the whole application, so a path
    # present in one and unlisted in the other would still
    # slip through if this were not checked.

    documented = {
        row["path"]
        for row in table["routes"]
        if row["in_schema"]
    }

    unlisted = sorted(
        documented
        - set(
            EXPECTED_API_PATHS
        )
    )

    assert_equal(
        unlisted,
        [],
        (
            "A route the table reports as documented is not "
            "in EXPECTED_API_PATHS. If TEST 1 passed, the "
            "OpenAPI document did not contain it -- which "
            "means the document and the table disagree, and "
            "the surface is larger than either test proved."
        ),
    )

    ok(
        f"{len(documented)} documented routes visible in the "
        "route table are all declared in TEST 1"
    )

    # ------------------------------------------------------
    # THE FRAMEWORK'S OWN DOCUMENTATION ROUTES
    # ------------------------------------------------------
    #
    # /docs, /redoc and /openapi.json are on by default and
    # serve the complete route surface, every schema and every
    # field name to anyone who can reach them. That is not a
    # credential leak; it is a map, handed out, with a form
    # for trying each route.
    #
    # They stay on in the application, because they are how
    # the API is read during development and because turning
    # them off there would be the wrong trade. This asserts
    # the production answer is written down rather than
    # assumed: the proxy is the only ingress, and it refuses
    # them.

    locations = (
        PROJECT_ROOT
        / "docker"
        / "nginx"
        / "vigilox-locations.conf"
    ).read_text(
        encoding="utf-8",
    )

    for path in (
        "/docs",
        "/redoc",
        "/openapi.json",
    ):

        block = f"location = {path}"

        assert_true(
            block in locations,
            (
                "The proxy must have an explicit "
                f"'{block}' block. Left to the catch-all, "
                f"{path} is published to the internet: it is "
                "the entire route surface plus a form for "
                "calling each route."
            ),
        )

    documentation_section = locations[
        locations.index(
            "location = /docs"
        ):
    ]

    normalised = " ".join(
        documentation_section.split()
    )

    assert_true(
        "deny all;" in normalised,
        (
            "The documentation routes must be denied, not "
            "merely mentioned."
        ),
    )

    ok(
        "/docs, /redoc and /openapi.json are served by the "
        "app and refused by the proxy"
    )


def main() -> int:

    print(
        "=" * 74
    )
    print(
        "PHASE 11.4 - ROUTE STRUCTURE AND DOMAIN CONTRACTS"
    )
    print(
        "=" * 74
    )

    test_route_surface()
    test_versioning_is_consistent()
    test_no_shadowed_routes()
    test_claimable_statuses_come_from_the_domain()
    test_response_model_position()
    test_hidden_route_surface()

    print()
    print(
        "=" * 74
    )
    print(
        "[PASS] PHASE 11.4 ROUTE AND DOMAIN CONTRACT TEST "
        "PASSED"
    )
    print(
        "=" * 74
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
