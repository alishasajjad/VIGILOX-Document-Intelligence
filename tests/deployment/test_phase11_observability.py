"""
==========================================================
PHASE 11.10 / 11.11 / 11.14
LOGGING, METRICS, WORKER HEALTH
==========================================================

WHAT THIS SUITE IS PROTECTING

  1. NOTHING SENSITIVE IS LOGGED.
     The application handles identity documents. A log line
     carrying OCR text, an extracted licence number or a
     reviewer's correction turns a log aggregator into a copy
     of the documents, held for the retention period, readable
     by anyone with log access.

  2. NO METRIC LABEL CARRIES AN IDENTIFIER.
     A Prometheus label value creates a time series, held by
     the scraper forever. document_id would be one series per
     document; filename would be one series per upload AND
     user-controlled text in a monitoring system.

     This is asserted against RENDERED output, not against the
     source, because the question is what actually gets
     emitted.

  3. THE WORKER HEARTBEAT IS REAL.
     Written from inside the loop, so it cannot be produced by
     a wedged process. And the four states an operator has to
     distinguish -- HEALTHY, DRAINING, STALE, NO_WORKER -- are
     actually distinguished.

  4. WORKER HEALTH IS SEPARATE FROM READINESS.
     The API serves uploads, reads and reviews perfectly with
     no worker running; the uploads queue. Failing readiness
     would take the API out of the load balancer and turn a
     worker problem into an API outage.

  5. /metrics IS NOT PUBLIC IN PRODUCTION.


NO REAL DOCUMENT IS PROCESSED
----------------------------------------------------------
The heartbeat tests drive the real WorkerRunner with a fake
worker factory that claims nothing. Running a real worker
here would process whatever is genuinely queued -- which is
somebody's uploaded document and somebody's Groq quota.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
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
# TEST 1 - THE LOGGING SURFACE
# ==========================================================

def test_logging_never_carries_document_content():

    section(
        "TEST 1 - THE LOG CANNOT CARRY DOCUMENT CONTENT OR A "
        "SECRET"
    )

    from backend.app.core.logging import (
        build_log_extra,
        log_event,
    )

    import inspect


    # ------------------------------------------------------
    # THE FIELD SET IS CLOSED
    # ------------------------------------------------------
    # log_event takes named keyword arguments rather than
    # **kwargs, and that is the control. With **kwargs, any
    # call site could add a field -- and the convenient field
    # to add while debugging is the extracted value that is
    # not matching.
    # ------------------------------------------------------

    signature = inspect.signature(
        log_event
    )

    has_var_keyword = any(
        parameter.kind
        == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )

    assert_true(
        not has_var_keyword,
        (
            "log_event accepts **kwargs, so any call site can "
            "invent a log field.\n"
            "The field set must be closed: the convenient "
            "thing to log while debugging an extraction is "
            "the extracted value, and that is a licence "
            "number."
        ),
    )

    allowed = sorted(
        name
        for name, parameter in (
            signature.parameters.items()
        )
        if parameter.kind
        != inspect.Parameter.VAR_POSITIONAL
        and name != "logger"
    )

    forbidden_fields = (
        "ocr_text",
        "text",
        "extraction",
        "extracted",
        "values",
        "value",
        "full_name",
        "licence_number",
        "id_number",
        "date_of_birth",
        "corrections",
        "notes",
        "api_key",
        "password",
        "filename",
    )

    present = [
        name
        for name in allowed
        if name in forbidden_fields
    ]

    assert_equal(
        present,
        [],
        (
            f"log_event exposes fields that would carry "
            f"document content or a secret: {present}"
        ),
    )

    ok(
        f"log_event accepts a closed set of "
        f"{len(allowed)} fields ({', '.join(allowed)}) and "
        f"none of them is document content"
    )


    # ------------------------------------------------------
    # AND WHAT IS ACTUALLY LOGGED, IN PRACTICE
    # ------------------------------------------------------
    # A real request, with hostile content in the places a
    # careless log line would pick it up.
    # ------------------------------------------------------

    probe = """
import io
import json
import logging

from fastapi.testclient import TestClient

from backend.app.main import app


records = []


from backend.app.core.logging import (
    StructuredJSONFormatter,
)


class Capture(logging.Handler):

    def emit(self, record):
        records.append(self.format(record))


handler = Capture()

# The APPLICATION's formatter, not logging's default. Reading
# the default would capture bare messages and prove nothing
# about what is actually written to stdout in production --
# and it is the structured fields, not the message, that could
# carry document content.
handler.setFormatter(StructuredJSONFormatter())

# The APPLICATION's loggers only.
#
# The root logger was captured at first, and it produced a
# false positive worth recording: httpx -- the TEST CLIENT's
# own HTTP library -- logs every request URL, so the digit run
# from a request path appeared in the capture. That is the test
# harness talking, not the application.
#
# The equivalent production concern is real and is handled
# elsewhere: uvicorn's access log writes full paths, which
# contain document ids, so docker/entrypoint.sh runs it with
# --no-access-log. test_uvicorn_does_not_log_paths below
# asserts that.
for name in ("vigilox", "vigilox.api", "vigilox.worker"):
    logger = logging.getLogger(name)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)


SECRET_FILENAME = "LICENCE-1234567890-SECRETNAME.jpg"

with TestClient(app) as client:

    client.get("/api/v1/documents", params={"limit": 1})

    client.post(
        "/api/v1/document-jobs",
        files={
            "file": (
                SECRET_FILENAME,
                io.BytesIO(b"not-an-image-at-all"),
                "text/plain",
            )
        },
    )

    client.get("/api/v1/documents/1234567890-not-a-real-id")

    client.post(
        "/api/v1/documents/abc/reviews",
        json={
            "human_action": "APPROVED",
            "notes": "REVIEWER-NOTE-SHOULD-NOT-BE-LOGGED",
        },
    )

print(json.dumps({"records": records}))
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
            / "logprobe.py"
        )

        script.write_text(
            probe,
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
            "The logging probe must run.\n"
            f"{completed.stdout[-2000:]}\n"
            f"{completed.stderr[-2000:]}"
        ),
    )

    payload = json.loads(
        [
            line
            for line in completed.stdout.splitlines()
            if line.strip().startswith(
                "{"
            )
        ][-1]
    )

    combined = "\n".join(
        payload["records"]
    )

    assert_true(
        payload["records"],
        (
            "The probe captured no log records at all, so it "
            "proves nothing. The handler is not attached."
        ),
    )

    leaked = []

    for needle, description in (
        (
            "REVIEWER-NOTE-SHOULD-NOT-BE-LOGGED",
            "a reviewer's free-text note",
        ),
        (
            "SECRETNAME",
            "part of an uploaded filename",
        ),
        (
            "1234567890",
            (
                "a digit run that could be a licence or id "
                "number"
            ),
        ),
        (
            "not-an-image-at-all",
            "uploaded file content",
        ),
    ):

        if needle in combined:
            leaked.append(
                f"{needle!r} ({description})"
            )

    live_key = os.environ.get(
        "GROQ_API_KEY",
        "",
    )

    if live_key and live_key in combined:
        leaked.append(
            "the live GROQ_API_KEY"
        )

    live_url = os.environ.get(
        "DATABASE_URL",
        "",
    )

    if live_url:

        # The password specifically.
        if "@" in live_url and "//" in live_url:

            authority = live_url.split(
                "//",
                1,
            )[1].split(
                "@",
                1,
            )[0]

            if ":" in authority:

                secret = authority.split(
                    ":",
                    1,
                )[1]

                if secret and secret in combined:
                    leaked.append(
                        "the database password"
                    )

    assert_equal(
        leaked,
        [],
        (
            "The log contains content it must never carry:\n"
            + "\n".join(
                leaked
            )
            + f"\n\nCaptured {len(payload['records'])} "
            "records."
        ),
    )

    ok(
        f"{len(payload['records'])} log records captured "
        f"across 4 requests including a hostile filename and "
        f"a reviewer note: no document content, no filename "
        f"fragment, no secret"
    )


    # ------------------------------------------------------
    # AND THEY ARE MACHINE READABLE
    # ------------------------------------------------------

    parsed = 0

    for record in payload["records"]:

        try:
            body = json.loads(
                record
            )

        except json.JSONDecodeError:
            continue

        if isinstance(
            body,
            dict,
        ):
            parsed += 1

    assert_true(
        parsed > 0,
        (
            "No log record parsed as JSON. Production logs "
            "should be machine readable, or correlating a "
            "request across services means grepping."
        ),
    )

    sample = json.loads(
        next(
            record
            for record in payload["records"]
            if record.strip().startswith(
                "{"
            )
        )
    )

    for field in (
        "timestamp",
        "level",
        "logger",
    ):

        assert_true(
            field in sample,
            (
                f"A structured log record must carry "
                f"{field!r}."
            ),
        )

    ok(
        f"{parsed} of {len(payload['records'])} records are "
        f"JSON objects carrying timestamp, level and logger"
    )


# ==========================================================
# TEST 1b - THE SERVER DOES NOT LOG REQUEST PATHS
# ==========================================================

def test_uvicorn_does_not_log_paths():

    section(
        "TEST 1b - THE ASGI SERVER'S ACCESS LOG IS OFF, "
        "BECAUSE PATHS CONTAIN DOCUMENT IDS"
    )

    entrypoint = (
        PROJECT_ROOT
        / "docker"
        / "entrypoint.sh"
    ).read_text(
        encoding="utf-8"
    )

    launches = [
        line.strip()
        for line in entrypoint.splitlines()
        if "uvicorn" in line
        and not line.strip().startswith(
            "#"
        )
    ]

    assert_true(
        launches,
        "The entrypoint must launch uvicorn.",
    )

    assert_true(
        "--no-access-log" in entrypoint,
        (
            "uvicorn must run with --no-access-log.\n"
            "Its access log writes the full request PATH, and "
            "this application's paths carry document ids:\n"
            "    GET /api/v1/documents/<uuid>/image\n"
            "    GET /review/<uuid>\n"
            "Every document a reviewer opened would land in a "
            "plain-text log with no structure and no retention "
            "policy of its own."
        ),
    )

    # Executable lines only. The comment in the entrypoint
    # explains why --log-config /dev/null is wrong, and a
    # plain substring check flagged that explanation -- the
    # rule punishing the documentation that exists to record
    # it. Third time this shape of mistake has come up, after
    # the error.detail prefix rule and the "for " loop rule.
    executable = [
        line
        for line in entrypoint.splitlines()
        if line.strip()
        and not line.strip().startswith(
            "#"
        )
    ]

    bad_config = [
        line.strip()
        for line in executable
        if "--log-config" in line
    ]

    assert_equal(
        bad_config,
        [],
        (
            "--log-config expects a real dictConfig file. "
            "/dev/null does not disable logging, it fails to "
            "parse -- so this would stop the container "
            "starting rather than quieten it.\n"
            f"Found: {bad_config}"
        ),
    )

    ok(
        "uvicorn runs with --no-access-log, so request paths "
        "containing document ids are not written to a third "
        "log"
    )


# ==========================================================
# TEST 2 - METRIC CARDINALITY
# ==========================================================

def test_metric_labels_carry_no_identifiers():

    section(
        "TEST 2 - NO METRIC LABEL CARRIES AN IDENTIFIER"
    )

    from backend.app.services import metrics_service


    # ------------------------------------------------------
    # THE ROUTE TEMPLATE COLLAPSES IDENTIFIERS
    # ------------------------------------------------------
    # The single most important function for cardinality.
    # ------------------------------------------------------

    document_id = str(
        uuid.uuid4()
    )

    cases = (
        (
            f"/api/v1/documents/{document_id}",
            "/api/v1/documents/{id}",
        ),
        (
            f"/api/v1/documents/{document_id}/image",
            "/api/v1/documents/{id}/image",
        ),
        (
            f"/api/v1/documents/{document_id}/reviews",
            "/api/v1/documents/{id}/reviews",
        ),
        (
            f"/api/v1/documents/{document_id}/history",
            "/api/v1/documents/{id}/history",
        ),
        (
            f"/api/v1/document-jobs/{document_id}",
            "/api/v1/document-jobs/{id}",
        ),
        (
            f"/api/v1/document-batches/{document_id}",
            "/api/v1/document-batches/{id}",
        ),
        (
            "/api/v1/documents",
            "/api/v1/documents",
        ),
        (
            f"/review/{document_id}",
            "page",
        ),
        (
            "/review/static/js/common.js",
            "static",
        ),
        (
            "/some/path/nobody/registered",
            "other",
        ),
    )

    for path, expected in cases:

        actual = metrics_service.route_template(
            path
        )

        assert_equal(
            actual,
            expected,
            (
                f"{path} must collapse to {expected!r}.\n"
                "Anything that lets an identifier through "
                "creates one Prometheus time series per "
                "document, held by the scraper forever."
            ),
        )

        assert_true(
            document_id not in actual,
            (
                f"The template {actual!r} still contains the "
                f"document id."
            ),
        )

    ok(
        f"{len(cases)} paths all collapse to a template; no "
        f"identifier survives"
    )


    # ------------------------------------------------------
    # AND THE RENDERED OUTPUT CONFIRMS IT
    # ------------------------------------------------------
    # Against real emitted text, not against the source. The
    # question is what actually gets scraped.
    # ------------------------------------------------------

    probe = """
import json
import uuid

from fastapi.testclient import TestClient

from backend.app.main import app


MARKER = uuid.uuid4().hex

with TestClient(app) as client:

    client.get("/api/v1/documents", params={"limit": 1})
    client.get("/api/v1/documents/" + MARKER)
    client.get("/api/v1/documents/" + MARKER + "/image")
    client.get("/review/" + MARKER)
    client.get("/api/v1/document-jobs/" + MARKER)
    client.get("/nothing/here/" + MARKER)

    body = client.get("/metrics").text

print(json.dumps({"marker": MARKER, "body": body}))
"""

    environment = dict(
        os.environ
    )

    environment["PYTHONPATH"] = str(
        PROJECT_ROOT
    )

    environment["VIGILOX_API_EAGER_PIPELINE"] = "false"

    environment["VIGILOX_METRICS_ENABLED"] = "true"

    with tempfile.TemporaryDirectory() as directory:

        script = (
            Path(
                directory
            )
            / "metricsprobe.py"
        )

        script.write_text(
            probe,
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
            "The metrics probe must run.\n"
            f"{completed.stderr[-2000:]}"
        ),
    )

    payload = json.loads(
        [
            line
            for line in completed.stdout.splitlines()
            if line.strip().startswith(
                "{"
            )
        ][-1]
    )

    body = payload["body"]

    marker = payload["marker"]

    assert_true(
        body.strip(),
        "The metrics endpoint returned nothing.",
    )

    assert_true(
        marker not in body,
        (
            "The rendered metrics contain the identifier that "
            "was used in the request paths.\n"
            "That is one time series per document, held by "
            "the scraper forever."
        ),
    )


    # Every label VALUE in the output must come from a fixed
    # set. This is the general check, not a list of things
    # that happen to be wrong.
    label_values = set(
        re.findall(
            r'[a-z_]+="([^"]*)"',
            body,
        )
    )

    allowed = (
        set(
            metrics_service.HTTP_METHODS
        )
        | set(
            metrics_service.STATUS_CLASSES
        )
        | set(
            metrics_service.ROUTE_TEMPLATES
        )
        | set(
            metrics_service.PIPELINE_STAGES
        )
        | set(
            metrics_service.PROVIDER_OUTCOMES
        )
        | set(
            metrics_service.JOB_OUTCOMES
        )
        | {
            "running",
            "draining",
            "stale",
            "QUEUED",
            "PROCESSING",
            "RETRY_WAIT",
            "COMPLETED",
            "FAILED",
            "CANCELLED",
        }
    )

    # Histogram bucket edges are label values too.
    numeric = re.compile(
        r"^\+Inf$|^[0-9.]+$"
    )

    unexpected = sorted(
        value
        for value in label_values
        if value not in allowed
        and not numeric.match(
            value
        )
    )

    assert_equal(
        unexpected,
        [],
        (
            f"The metrics output contains label values "
            f"outside the declared sets: {unexpected}\n"
            "Every label value must come from a fixed, small "
            "set defined in code. An unbounded label is how a "
            "monitoring system is taken down."
        ),
    )

    ok(
        f"{len(label_values)} distinct label values in the "
        f"rendered output, all from declared sets; the "
        f"request identifier appears nowhere"
    )


    # ------------------------------------------------------
    # THE USEFUL SERIES ARE ACTUALLY THERE
    # ------------------------------------------------------

    for metric in (
        "vigilox_http_requests_total",
        "vigilox_http_request_duration_seconds",
        "vigilox_job_queue_depth",
        "vigilox_workers",
        "vigilox_queue_waiting_with_no_worker",
    ):

        assert_true(
            metric in body,
            (
                f"{metric} must be exposed. A cardinality "
                f"rule that produced an empty endpoint would "
                f"pass every assertion above."
            ),
        )

    ok(
        "the five core metric families are present, so the "
        "cardinality checks are not passing on an empty "
        "endpoint"
    )


# ==========================================================
# TEST 3 - THE METRICS ENDPOINT IS NOT PUBLIC
# ==========================================================

def test_metrics_gated_in_production():

    section(
        "TEST 3 - /metrics IS OFF BY DEFAULT IN PRODUCTION"
    )

    probe = """
import json

from fastapi.testclient import TestClient

from backend.app.main import app


with TestClient(app) as client:

    response = client.get("/metrics")

    print(
        json.dumps(
            {
                "status": response.status_code,
                "length": len(response.text),
            }
        )
    )
"""

    def run(
        overrides,
    ):

        environment = dict(
            os.environ
        )

        environment["PYTHONPATH"] = str(
            PROJECT_ROOT
        )

        environment[
            "VIGILOX_API_EAGER_PIPELINE"
        ] = "false"

        for name in (
            "VIGILOX_METRICS_ENABLED",
            "VIGILOX_ENVIRONMENT",
            "VIGILOX_TRUSTED_PROXIES",
        ):
            environment.pop(
                name,
                None,
            )

        environment.update(
            overrides
        )

        with tempfile.TemporaryDirectory() as directory:

            script = (
                Path(
                    directory
                )
                / "gate.py"
            )

            script.write_text(
                probe,
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
                "The probe must run.\n"
                f"{completed.stderr[-1500:]}"
            ),
        )

        return json.loads(
            [
                line
                for line in (
                    completed.stdout.splitlines()
                )
                if line.strip().startswith(
                    "{"
                )
            ][-1]
        )

    development = run(
        {}
    )

    assert_equal(
        development["status"],
        200,
        (
            "In development /metrics must answer. A metric "
            "nobody can see is a metric nobody uses."
        ),
    )

    # A production posture has to be a VALID one. Setting
    # VIGILOX_ENVIRONMENT=production alone makes the Phase
    # 11.5 startup check refuse to start -- local_env identity
    # is rejected in production -- which is that check working
    # correctly, and would make this test fail for a reason
    # that has nothing to do with metrics.
    PRODUCTION = {
        "VIGILOX_ENVIRONMENT": "production",
        "VIGILOX_REVIEW_IDENTITY_MODE": "trusted_headers",
        "VIGILOX_TRUSTED_PROXIES": "10.0.0.0/8",
    }

    production = run(
        dict(
            PRODUCTION
        )
    )

    assert_equal(
        production["status"],
        404,
        (
            "In production /metrics must be OFF unless "
            "explicitly enabled.\n"
            "Queue depth, failure rates and provider "
            "behaviour say how loaded the service is, when it "
            "is struggling, and whether anyone is watching. "
            "The proxy restricts the path; this is the second "
            "control, for a deployment without that proxy in "
            "front."
        ),
    )

    enabled = run(
        dict(
            PRODUCTION,
            VIGILOX_METRICS_ENABLED="true",
        )
    )

    assert_equal(
        enabled["status"],
        200,
        (
            "And it must be available when a production "
            "deployment turns it on deliberately."
        ),
    )

    ok(
        "development 200, production 404, production with "
        "VIGILOX_METRICS_ENABLED 200"
    )


# ==========================================================
# TEST 4 - THE HEARTBEAT IS WRITTEN BY THE LOOP
# ==========================================================

def test_worker_heartbeat():

    section(
        "TEST 4 - THE HEARTBEAT IS PRODUCED BY THE RUNNING "
        "LOOP"
    )

    from backend.app.services.document_worker import (
        WorkerRunner,
    )

    from backend.app.services.worker_health_service import (
        HEALTHY,
        NO_WORKER,
        STALE,
        WorkerHealthService,
        WorkerHeartbeatWriter,
    )

    from database.database import SessionLocal

    from database.models import WorkerHeartbeatModel

    marker = uuid.uuid4().hex[:8]


    # ------------------------------------------------------
    # A FAKE WORKER THAT CLAIMS NOTHING
    # ------------------------------------------------------
    # The real runner, the real heartbeat write, and a worker
    # that does no work. Running a real worker here would
    # process whatever is genuinely queued -- somebody's
    # uploaded document and somebody's Groq quota.
    # ------------------------------------------------------

    class IdleWorker:

        def __init__(
            self,
        ) -> None:

            self.worker_id = (
                f"observability-{marker}"
            )

            self.completed = 0

            self.failed = 0

            self.retried = 0

            self.current_job_id = None

        def reclaim_expired(
            self,
        ) -> int:
            return 0

        def process_one(
            self,
        ) -> bool:
            return False

        @property
        def pipeline(
            self,
        ):
            # Never touched: warm() is not called here, and
            # this test is about the heartbeat, not OCR.
            raise AssertionError(
                "The idle worker must not build a pipeline."
            )

    runner = WorkerRunner(
        concurrency=1,
        poll_seconds=0.05,
        idle_poll_seconds=0.05,
        worker_factory=IdleWorker,
    )

    created = []

    try:

        thread = threading.Thread(
            target=runner.run,
            daemon=True,
        )

        thread.start()

        # Long enough for the loop to come round several
        # times at a 0.05s poll.
        deadline = time.monotonic() + 15

        row = None

        while time.monotonic() < deadline:

            with SessionLocal() as session:

                row = session.get(
                    WorkerHeartbeatModel,
                    f"observability-{marker}",
                )

                if row is not None:
                    created.append(
                        row.worker_id
                    )
                    break

            time.sleep(
                0.25
            )

        assert_true(
            row is not None,
            (
                "The running loop wrote no heartbeat within "
                "15 seconds.\n"
                "A heartbeat has to be produced by the loop "
                "actually turning -- that is what makes it "
                "distinguishable from 'a container is "
                "running'."
            ),
        )

        assert_equal(
            row.status,
            "RUNNING",
            "A turning loop reports RUNNING.",
        )

        assert_equal(
            row.concurrency,
            1,
            (
                "The configured concurrency is recorded, so "
                "an operator can see whether the deployment "
                "is set up the way they think."
            ),
        )

        ok(
            f"the loop wrote a heartbeat for "
            f"{row.worker_id!r} with status RUNNING"
        )


        # --------------------------------------------------
        # THE HEARTBEAT ADVANCES
        # --------------------------------------------------
        # One row proves it was written once. A row whose
        # timestamp moves proves the loop is still turning,
        # which is the actual signal.
        # --------------------------------------------------

        first_seen = row.last_seen_at

        advanced = False

        deadline = time.monotonic() + 15

        while time.monotonic() < deadline:

            with SessionLocal() as session:

                current = session.get(
                    WorkerHeartbeatModel,
                    f"observability-{marker}",
                )

                if (
                    current is not None
                    and current.last_seen_at
                    > first_seen
                ):
                    advanced = True
                    break

            time.sleep(
                0.25
            )

        assert_true(
            advanced,
            (
                "The heartbeat timestamp never advanced. A "
                "single write could come from process "
                "startup; a moving timestamp is what "
                "distinguishes a live loop from a wedged "
                "one."
            ),
        )

        ok(
            "the heartbeat timestamp advances while the loop "
            "runs"
        )


        # --------------------------------------------------
        # HEALTHY, AND VISIBLE
        # --------------------------------------------------

        health = (
            WorkerHealthService()
            .evaluate()
        )

        assert_equal(
            health["state"],
            HEALTHY,
            (
                "With a live worker the state must be "
                f"HEALTHY, got {health['state']}."
            ),
        )

        assert_true(
            health["running_count"] >= 1,
            "The live worker must be counted.",
        )

        ok(
            f"worker health reports HEALTHY with "
            f"{health['running_count']} running"
        )

    finally:

        # ==================================================
        # JOIN THE THREAD. DO NOT SLEEP AND HOPE.
        # ==================================================
        # This used to be
        #
        #     runner.request_stop()
        #     time.sleep(0.5)
        #     ... delete the row
        #
        # and that is a race, not a wait. request_stop() only
        # sets a flag; the loop notices it on its next
        # iteration and beats once more on the way out. Half a
        # second is enough while the machine is quiet and is
        # not enough under gate load -- so the final beat
        # landed AFTER the delete, re-creating a live RUNNING
        # row, and the STALE assertion below then read the
        # whole deployment as HEALTHY.
        #
        # It failed in the full gate and passed standalone,
        # which is the signature of exactly this bug and the
        # second time this class of defect has appeared in
        # this suite family.
        #
        # Joining is deterministic: when the thread has
        # returned, no further beat is possible, so the delete
        # cannot be undone.
        runner.request_stop()

        thread.join(
            timeout=30
        )

        if thread.is_alive():
            raise AssertionError(
                "The worker loop did not stop within 30s of "
                "request_stop(). Deleting its heartbeat now "
                "would race a beat that is still coming, and "
                "the stale assertion below would fail for a "
                "reason that has nothing to do with "
                "staleness."
            )

        # Removed HERE, not in the final cleanup, because the
        # STALE case below evaluates worker health with a
        # 60-second threshold -- and this row is seconds old.
        # Leaving it would make the whole deployment read
        # HEALTHY.
        with SessionLocal.begin() as session:

            for identifier in created:

                row = session.get(
                    WorkerHeartbeatModel,
                    identifier,
                )

                if row is not None:
                    session.delete(
                        row
                    )

        created.clear()

        # ==================================================
        # AND THE AGGREGATE MUST BE OWNABLE
        # ==================================================
        # state is computed over EVERY heartbeat row in the
        # database, so the assertion below is only meaningful
        # if nothing else is live. On a shared development
        # database that is not guaranteed: a real worker may
        # be running right now.
        #
        # Rather than delete somebody else's rows -- which
        # would be this test corrupting the deployment it is
        # inspecting -- foreign live workers are DETECTED and
        # named, and the aggregate assertion is skipped
        # loudly rather than failing for the wrong reason.
        #
        # The per-worker `stale` assertion is unaffected: it
        # reads only the row this test planted, and it is the
        # assertion that actually proves the classification.
        foreign_live = []

        with SessionLocal() as session:

            for row in session.query(
                WorkerHeartbeatModel
            ).all():

                if row.status == "STOPPED":
                    continue

                age = (
                    datetime.now(
                        timezone.utc
                    )
                    - (
                        row.last_seen_at.replace(
                            tzinfo=timezone.utc
                        )
                        if row.last_seen_at.tzinfo is None
                        else row.last_seen_at
                    )
                ).total_seconds()

                if age < 60:
                    foreign_live.append(
                        f"{row.worker_id} "
                        f"({row.status}, {age:.0f}s ago)"
                    )


    # ------------------------------------------------------
    # STALE IS DISTINGUISHED FROM NO_WORKER
    # ------------------------------------------------------
    # The distinction that matters most: a worker that DIED
    # versus a deployment where one was never started. Both
    # look like "no recent heartbeat" and they need different
    # responses.
    # ------------------------------------------------------

    stale_id = f"stale-{marker}"

    writer = WorkerHeartbeatWriter(
        worker_id=stale_id,
        concurrency=1,
    )

    writer.beat()

    with SessionLocal.begin() as session:

        row = session.get(
            WorkerHeartbeatModel,
            stale_id,
        )

        # Aged past any plausible threshold.
        row.last_seen_at = datetime.now(
            timezone.utc
        ) - timedelta(
            hours=6,
        )

    try:

        service = WorkerHealthService(
            stale_seconds=60,
        )

        observed = service.evaluate()

        recorded = [
            worker
            for worker in observed["workers"]
            if worker["worker_id"] == stale_id
        ]

        assert_true(
            recorded,
            "The aged worker must still be listed.",
        )

        assert_equal(
            recorded[0]["stale"],
            True,
            (
                "A heartbeat six hours old must read as "
                "stale."
            ),
        )

        # Never NO_WORKER. This holds whatever else is in the
        # database -- a row exists, so "one was never
        # started" is false -- and it is the distinction the
        # comment above is about.
        assert_true(
            observed["state"] != NO_WORKER,
            (
                "An aged heartbeat must never read as "
                "NO_WORKER. NO_WORKER means one was never "
                "started: a missing compose service, a typo "
                "in a command. Different cause, different "
                "fix, and they look identical if all you "
                f"have is 'no recent heartbeat'. Got "
                f"{observed['state']}."
            ),
        )

        if foreign_live:

            print(
                "       (aggregate state assertion skipped: "
                + str(
                    len(
                        foreign_live
                    )
                )
                + " other live worker(s) in this database -- "
                + ", ".join(
                    foreign_live
                )
                + ". Their rows are not this test's to "
                "delete. The per-worker staleness assertion "
                "above is unaffected.)"
            )

        else:

            assert_equal(
                observed["state"],
                STALE,
                (
                    "With only an aged heartbeat the state "
                    "must be STALE -- a worker that DIED.\n"
                    f"Got {observed['state']}."
                ),
        )

        assert_true(
            observed[
                "queue_waiting_with_no_worker"
            ]
            is (
                observed["queue"]["ACTIVE_TOTAL"] > 0
            ),
            (
                "The paging signal must be true exactly when "
                "there is work waiting and nothing healthy to "
                "do it."
            ),
        )

        ok(
            f"an aged heartbeat reports STALE (not "
            f"NO_WORKER), with "
            f"queue_waiting_with_no_worker="
            f"{observed['queue_waiting_with_no_worker']}"
        )

    finally:

        with SessionLocal.begin() as session:

            for identifier in (
                created
                + [
                    stale_id,
                ]
            ):

                row = session.get(
                    WorkerHeartbeatModel,
                    identifier,
                )

                if row is not None:
                    session.delete(
                        row
                    )


# ==========================================================
# TEST 5 - WORKER HEALTH IS NOT READINESS
# ==========================================================

def test_worker_health_is_separate_from_readiness():

    section(
        "TEST 5 - A MISSING WORKER DOES NOT FAIL API "
        "READINESS"
    )

    probe = """
import json

from fastapi.testclient import TestClient

from backend.app.main import app


with TestClient(app) as client:

    ready = client.get("/health/ready")

    workers = client.get("/health/workers")

    print(
        json.dumps(
            {
                "ready_status": ready.status_code,
                "workers_status": workers.status_code,
                "worker_state": workers.json().get("status"),
                "ready_body_keys": sorted(ready.json().keys()),
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
            / "readyprobe.py"
        )

        script.write_text(
            probe,
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
            "The probe must run.\n"
            f"{completed.stderr[-1500:]}"
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

    assert_equal(
        observed["ready_status"],
        200,
        (
            "Readiness must pass with no worker running.\n"
            "The API serves uploads, reads and reviews "
            "perfectly well: the uploads simply queue. "
            "Failing readiness would take the API out of the "
            "load balancer and turn a worker problem into an "
            "API outage."
        ),
    )

    assert_equal(
        observed["workers_status"],
        200,
        (
            "The worker health endpoint answers regardless of "
            "worker state -- it REPORTS the state rather than "
            "failing on it, so monitoring can distinguish the "
            "cases."
        ),
    )

    assert_true(
        observed["worker_state"]
        in (
            "HEALTHY",
            "DRAINING",
            "STALE",
            "NO_WORKER",
        ),
        (
            f"The worker state must be one of the four "
            f"documented values, got "
            f"{observed['worker_state']!r}."
        ),
    )

    ok(
        f"readiness 200 while worker state is "
        f"{observed['worker_state']}; the two are reported "
        f"separately"
    )


# ==========================================================
# TEST 6 - THE ALERTS ARE DOCUMENTED
# ==========================================================

def test_alerts_are_documented():

    section(
        "TEST 6 - THE RECOMMENDED ALERTS ARE WRITTEN DOWN, "
        "AND NOTHING IS CLAIMED TO BE DEPLOYED"
    )

    path = (
        PROJECT_ROOT
        / "docs"
        / "operations"
        / "monitoring.md"
    )

    assert_true(
        path.exists(),
        (
            "docs/operations/monitoring.md must exist. "
            "Metrics with no documented alerts are metrics "
            "nobody watches."
        ),
    )

    text = path.read_text(
        encoding="utf-8"
    )

    lowered = text.lower()

    for topic in (
        "readiness",
        "database",
        "storage",
        "heartbeat",
        "queue",
        "failed",
        "rate limit",
        "disk",
    ):

        assert_true(
            topic in lowered,
            (
                f"The monitoring document must cover "
                f"{topic!r}."
            ),
        )


    # ------------------------------------------------------
    # AND IT MUST NOT CLAIM A STACK THAT IS NOT DEPLOYED
    # ------------------------------------------------------

    for claim in (
        "prometheus is deployed",
        "grafana is deployed",
        "alertmanager is deployed",
        "grafana dashboard is available",
    ):

        assert_true(
            claim not in lowered,
            (
                f"The document claims {claim!r}. Nothing of "
                f"the sort is deployed: the application "
                f"exposes an endpoint, and that is all."
            ),
        )

    assert_true(
        "not deployed" in lowered
        or "is not included" in lowered
        or "no monitoring stack" in lowered,
        (
            "The document must state plainly that no "
            "monitoring stack ships with this application. "
            "Otherwise a reader assumes the alerts below are "
            "live."
        ),
    )

    ok(
        "8 alert topics documented, with no claim that a "
        "monitoring stack is deployed"
    )


# ==========================================================
# MAIN
# ==========================================================

def main() -> int:

    print(
        "=" * 74
    )
    print(
        "PHASE 11.10 / 11.11 / 11.14 - OBSERVABILITY"
    )
    print(
        "=" * 74
    )

    test_logging_never_carries_document_content()
    test_uvicorn_does_not_log_paths()
    test_metric_labels_carry_no_identifiers()
    test_metrics_gated_in_production()
    test_worker_heartbeat()
    test_worker_health_is_separate_from_readiness()
    test_alerts_are_documented()

    print()
    print(
        "=" * 74
    )
    print(
        "[PASS] PHASE 11.10/11.11/11.14 OBSERVABILITY TEST "
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
