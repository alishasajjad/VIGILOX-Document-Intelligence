"""
==========================================================
PHASE 11.5 / 11.6 / 11.7
IDENTITY BOUNDARY, SECURITY HEADERS, RATE LIMIT
==========================================================

The application shipped with NO middleware: no security
headers, no framing protection, no content policy, no origin
policy, no rate limit. And one real hole.


THE HOLE
----------------------------------------------------------
In trusted_headers mode the reviewer identity came from

    X-VIGILOX-REVIEWER-ID
    X-VIGILOX-REVIEWER-ROLE

and nothing checked where the request came from. Any client
able to reach the port could send those two headers with
role=ADMIN, submit a review, and have it written into the
audit trail under a name of their choosing.

The documented mitigation was that the reverse proxy strips
client-supplied copies. That is necessary and not sufficient:
it assumes the proxy is the only route to the port. A
published container port, a permissive security group, or
anything already inside the network reaches the application
directly and the proxy never sees it.

Phase 11.5 honours those headers only from an address in
VIGILOX_TRUSTED_PROXIES, and refuses to start a production
deployment that has not configured one.


WHAT THIS SUITE IS PROTECTING

  1. A FORGED IDENTITY HEADER IS REFUSED, AND A REAL ONE IS
     NOT. Both directions. Asserting only the refusal would
     pass just as well for a boundary that refuses
     everything, which would be a broken service rather than
     a secure one.

  2. A PRODUCTION DEPLOYMENT REFUSES TO START MISCONFIGURED.
     A service that comes up and attributes every review to
     one configured identity is worse than one that does not
     come up: the first is discovered by auditing decisions
     after they were made.

  3. THE SECURITY HEADERS ARE ON EVERY RESPONSE, including
     the errors -- a 404 and a 401 render content too.

  4. THE CONTENT SECURITY POLICY MATCHES WHAT THE PAGES
     ACTUALLY LOAD. A policy copied from a template either
     breaks the interface or permits things the interface
     never needed.

  5. THERE IS NO CORS UNLESS ASKED FOR, AND NEVER "*".

  6. THE RATE LIMIT IS DESCRIBED HONESTLY.
     It is a dictionary in one process. N replicas allow N
     times the limit. This suite asserts the code says so,
     because the failure mode of a rate limit is not that it
     stops working -- it is that somebody believes it bounds
     total load when it bounds one process.
"""

import io
import json
import os
import re
import subprocess
import sys
import tempfile

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
# PROBES
# ==========================================================
#
# Each configuration case runs in its own process: the
# middleware reads its configuration when it is constructed,
# and the app is constructed at import.
# ==========================================================

def probe(
    code: str,
    environment: dict | None = None,
    expect_failure: bool = False,
) -> subprocess.CompletedProcess:

    child = dict(
        os.environ
    )

    child["PYTHONPATH"] = str(
        PROJECT_ROOT
    )

    # Nothing here runs OCR.
    child["VIGILOX_API_EAGER_PIPELINE"] = "false"

    for name in (
        "VIGILOX_ENVIRONMENT",
        "VIGILOX_TRUSTED_PROXIES",
        "VIGILOX_CORS_ORIGINS",
        "VIGILOX_HSTS_ENABLED",
        "VIGILOX_RATE_LIMIT_ENABLED",
        "VIGILOX_UPLOAD_RATE_LIMIT",
        "VIGILOX_UPLOAD_RATE_WINDOW_SECONDS",
    ):
        child.pop(
            name,
            None,
        )

    child.update(
        environment
        or {}
    )

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
            env=child,
        )

    if not expect_failure:

        assert_equal(
            completed.returncode,
            0,
            (
                "The probe must run.\n"
                f"{completed.stdout[-2500:]}\n"
                f"{completed.stderr[-2500:]}"
            ),
        )

    return completed


def result_of(
    completed: subprocess.CompletedProcess,
) -> dict:

    lines = [
        line
        for line in completed.stdout.splitlines()
        if line.strip().startswith(
            "{"
        )
    ]

    assert_true(
        lines,
        (
            "The probe printed no JSON.\n"
            f"{completed.stdout[-2000:]}\n"
            f"{completed.stderr[-2000:]}"
        ),
    )

    return json.loads(
        lines[-1]
    )


# ==========================================================
# TEST 1 - THE IDENTITY BOUNDARY
# ==========================================================

IDENTITY_PROBE = """
import json

from fastapi.testclient import TestClient

from backend.app.main import app


FORGED = {
    "X-VIGILOX-REVIEWER-ID": "attacker",
    "X-VIGILOX-REVIEWER-ROLE": "ADMIN",
}

out = {}

for label, peer in (
    ("from_proxy", ("10.0.0.5", 4444)),
    ("from_elsewhere", ("203.0.113.9", 4444)),
):

    with TestClient(app, client=peer) as client:

        response = client.get(
            "/api/v1/reviewer/me",
            headers=FORGED,
        )

        body = response.json()

        out[label] = {
            "status": response.status_code,
            "reviewer": body.get("reviewer"),
            "code": (
                body.get("error", {}).get("code")
                if response.status_code >= 400
                else None
            ),
        }

print(json.dumps(out))
"""


def test_identity_boundary():

    section(
        "TEST 1 - A REVIEWER IDENTITY HEADER IS HONOURED "
        "ONLY FROM A TRUSTED PROXY"
    )


    # ------------------------------------------------------
    # WITH A PROXY CONFIGURED
    # ------------------------------------------------------

    configured = result_of(
        probe(
            IDENTITY_PROBE,
            {
                "VIGILOX_REVIEW_IDENTITY_MODE": (
                    "trusted_headers"
                ),
                "VIGILOX_TRUSTED_PROXIES": "10.0.0.0/8",
            },
        )
    )

    assert_equal(
        configured["from_proxy"]["status"],
        200,
        (
            "A request from the configured proxy must be "
            "accepted.\n"
            "Asserting only the refusal below would pass for "
            "a boundary that refuses everything, which is a "
            "broken service rather than a secure one."
        ),
    )

    assert_equal(
        configured["from_proxy"]["reviewer"][
            "reviewer_id"
        ],
        "attacker",
        (
            "From the proxy, the forwarded identity is the "
            "identity. That is the design: the proxy has "
            "already authenticated the user and strips any "
            "client-supplied copy."
        ),
    )

    assert_equal(
        configured["from_proxy"]["reviewer"][
            "source"
        ],
        "TRUSTED_HEADER",
        "And it is recorded as coming from the header.",
    )

    assert_equal(
        configured["from_elsewhere"]["status"],
        401,
        (
            "THE SAME HEADERS from an address that is not "
            "the proxy must be refused.\n"
            "Before Phase 11.5 this returned 200 with "
            "role=ADMIN. Any client able to reach the port "
            "could name itself as any reviewer and have its "
            "decisions written into the audit trail under "
            "that name."
        ),
    )

    assert_equal(
        configured["from_elsewhere"]["code"],
        "REVIEWER_AUTHENTICATION_REQUIRED",
        (
            "Deliberately the same error as a missing "
            "identity. A distinct 'your address is not "
            "trusted' would confirm both that the mechanism "
            "exists and which header names to try from "
            "somewhere else."
        ),
    )

    ok(
        "identical forged headers: 200 as 'attacker' from "
        "10.0.0.5, 401 from 203.0.113.9"
    )


    # ------------------------------------------------------
    # WITH NO PROXY CONFIGURED, NOTHING IS TRUSTED
    # ------------------------------------------------------

    unconfigured = result_of(
        probe(
            IDENTITY_PROBE,
            {
                "VIGILOX_REVIEW_IDENTITY_MODE": (
                    "trusted_headers"
                ),
            },
        )
    )

    for label in (
        "from_proxy",
        "from_elsewhere",
    ):

        assert_equal(
            unconfigured[label]["status"],
            401,
            (
                "With VIGILOX_TRUSTED_PROXIES unset, no "
                "address is trusted.\n"
                "That is the safe direction: a deployment "
                "that forgot to configure the list refuses "
                "identity rather than accepting it from "
                "anywhere."
            ),
        )

    ok(
        "with no proxies configured, the headers are refused "
        "from every address including 10.0.0.5"
    )


# ==========================================================
# TEST 2 - PRODUCTION REFUSES TO START MISCONFIGURED
# ==========================================================

STARTUP_PROBE = """
import json

from fastapi.testclient import TestClient

from backend.app.main import app


with TestClient(app) as client:

    print(json.dumps({"started": True}))
"""


def test_production_posture():

    section(
        "TEST 2 - A MISCONFIGURED PRODUCTION DEPLOYMENT "
        "REFUSES TO START"
    )

    cases = (
        (
            "local_env identity in production",
            {
                "VIGILOX_ENVIRONMENT": "production",
                "VIGILOX_REVIEW_IDENTITY_MODE": "local_env",
            },
            "local_env",
        ),
        (
            "trusted_headers with no proxy configured",
            {
                "VIGILOX_ENVIRONMENT": "production",
                "VIGILOX_REVIEW_IDENTITY_MODE": (
                    "trusted_headers"
                ),
            },
            "VIGILOX_TRUSTED_PROXIES",
        ),
    )

    for description, environment, expected in cases:

        completed = probe(
            STARTUP_PROBE,
            environment,
            expect_failure=True,
        )

        assert_true(
            completed.returncode != 0,
            (
                f"Production with {description} must refuse "
                f"to start.\n"
                "A service that comes up and attributes every "
                "review decision to one configured identity "
                "is worse than one that does not come up: the "
                "first is discovered by auditing decisions "
                "after they were made."
            ),
        )

        assert_true(
            expected in completed.stderr,
            (
                f"The refusal must say what is wrong. "
                f"Expected {expected!r} in the message.\n"
                f"{completed.stderr[-1500:]}"
            ),
        )

    ok(
        f"{len(cases)} misconfigured production postures each "
        f"refuse to start and name the variable at fault"
    )


    # ------------------------------------------------------
    # AND A CORRECT ONE STARTS
    # ------------------------------------------------------

    started = result_of(
        probe(
            STARTUP_PROBE,
            {
                "VIGILOX_ENVIRONMENT": "production",
                "VIGILOX_REVIEW_IDENTITY_MODE": (
                    "trusted_headers"
                ),
                "VIGILOX_TRUSTED_PROXIES": "10.0.0.0/8",
            },
        )
    )

    assert_equal(
        started["started"],
        True,
        (
            "A correctly configured production deployment "
            "must start. A check that refuses everything is "
            "not a check."
        ),
    )

    ok(
        "production with trusted_headers and a configured "
        "proxy starts normally"
    )


    # ------------------------------------------------------
    # DEVELOPMENT IS UNTOUCHED
    # ------------------------------------------------------

    development = result_of(
        probe(
            STARTUP_PROBE,
            {
                "VIGILOX_REVIEW_IDENTITY_MODE": "local_env",
            },
        )
    )

    assert_equal(
        development["started"],
        True,
        (
            "local_env must keep working outside production. "
            "The whole point of the mode is that a developer "
            "does not need an identity provider."
        ),
    )

    ok(
        "local_env still starts when VIGILOX_ENVIRONMENT is "
        "not production"
    )


# ==========================================================
# TEST 3 - SECURITY HEADERS ON EVERY RESPONSE
# ==========================================================

HEADERS_PROBE = """
import json

from fastapi.testclient import TestClient

from backend.app.main import app


out = {}

with TestClient(app) as client:

    checks = (
        ("ok", "get", "/api/v1/documents", {}),
        ("page", "get", "/upload", {}),
        ("not_found", "get", "/api/v1/nope", {}),
        (
            "bad_request",
            "get",
            "/api/v1/documents",
            {"params": {"page_size": "-4"}},
        ),
        (
            "missing_document",
            "get",
            "/api/v1/documents/does-not-exist",
            {},
        ),
    )

    for label, method, path, extra in checks:

        response = getattr(client, method)(path, **extra)

        out[label] = {
            "status": response.status_code,
            "headers": {
                key.lower(): value
                for key, value in response.headers.items()
            },
        }

print(json.dumps(out))
"""


REQUIRED_HEADERS = (
    "x-content-type-options",
    "x-frame-options",
    "referrer-policy",
    "permissions-policy",
    "cross-origin-opener-policy",
    "content-security-policy",
)


def test_security_headers():

    section(
        "TEST 3 - THE SECURITY HEADERS ARE ON EVERY "
        "RESPONSE, INCLUDING ERRORS"
    )

    observed = result_of(
        probe(
            HEADERS_PROBE
        )
    )

    for label, response in observed.items():

        for header in REQUIRED_HEADERS:

            assert_true(
                header in response["headers"],
                (
                    f"The {label} response (HTTP "
                    f"{response['status']}) is missing "
                    f"{header}.\n"
                    "An error response renders content too. A "
                    "404 body without nosniff is still a "
                    "body a browser may decide to interpret "
                    "as HTML."
                ),
            )

    ok(
        f"all {len(REQUIRED_HEADERS)} headers present on "
        f"{len(observed)} response kinds: "
        + ", ".join(
            f"{label} ({response['status']})"
            for label, response in sorted(
                observed.items()
            )
        )
    )


    # ------------------------------------------------------
    # THE VALUES
    # ------------------------------------------------------

    headers = observed["ok"]["headers"]

    assert_equal(
        headers["x-content-type-options"],
        "nosniff",
        "Content sniffing must be off.",
    )

    assert_equal(
        headers["x-frame-options"],
        "DENY",
        (
            "Framing must be denied. A reviewer's session "
            "inside somebody else's iframe is a clickjacking "
            "target, and the approve button is one click."
        ),
    )

    assert_equal(
        headers["referrer-policy"],
        "no-referrer",
        (
            "A document URL contains a document id. It must "
            "not travel to wherever the user goes next."
        ),
    )

    ok(
        "nosniff, DENY, no-referrer, "
        f"{headers['cross-origin-opener-policy']}, "
        f"{headers['permissions-policy']}"
    )


    # ------------------------------------------------------
    # HSTS IS OFF UNLESS ASKED FOR
    # ------------------------------------------------------

    assert_true(
        "strict-transport-security" not in headers,
        (
            "HSTS must NOT be sent by default.\n"
            "It tells a browser to refuse plain HTTP to this "
            "host for a year, and the browser remembers. Sent "
            "from a deployment that is not actually behind "
            "TLS, it locks users out of their own service and "
            "cannot be withdrawn quickly.\n"
            "TLS terminates at the proxy, so this process "
            "cannot know. It sends HSTS only when a "
            "deployment that does know says so."
        ),
    )

    enabled = result_of(
        probe(
            HEADERS_PROBE,
            {
                "VIGILOX_HSTS_ENABLED": "true",
            },
        )
    )

    assert_true(
        "strict-transport-security"
        in enabled["ok"]["headers"],
        "And it must be sent when enabled.",
    )

    ok(
        "HSTS absent by default, present when "
        "VIGILOX_HSTS_ENABLED is set"
    )


# ==========================================================
# TEST 4 - THE CSP MATCHES WHAT THE PAGES LOAD
# ==========================================================

def test_csp_matches_the_pages():

    section(
        "TEST 4 - THE CONTENT SECURITY POLICY IS AS STRICT "
        "AS THE PAGES ALLOW"
    )

    from backend.app.api.security_headers import (
        CONTENT_SECURITY_POLICY,
    )

    directives = dict(
        (
            part.strip().split(
                " ",
                1,
            )[0],
            part.strip(),
        )
        for part in CONTENT_SECURITY_POLICY.split(
            ";"
        )
        if part.strip()
    )


    # ------------------------------------------------------
    # NO UNSAFE ANYTHING
    # ------------------------------------------------------

    for directive in (
        "script-src",
        "style-src",
    ):

        value = directives[directive]

        assert_true(
            "unsafe-inline" not in value,
            (
                f"{directive} must not allow "
                f"'unsafe-inline'. It is the directive doing "
                f"the work: with it, the policy stops "
                f"preventing injected script or style at all."
            ),
        )

        assert_true(
            "unsafe-eval" not in value,
            f"{directive} must not allow 'unsafe-eval'.",
        )

    assert_equal(
        directives["frame-ancestors"],
        "frame-ancestors 'none'",
        "Nothing may frame this application.",
    )

    assert_equal(
        directives["object-src"],
        "object-src 'none'",
        "No plugins.",
    )

    ok(
        "script-src and style-src are 'self' with no unsafe "
        "directive; frame-ancestors and object-src are 'none'"
    )


    # ------------------------------------------------------
    # AND THE PAGES CAN ACTUALLY LIVE WITH IT
    # ------------------------------------------------------
    # A strict policy that breaks the interface is worse than
    # a loose one, because it is discovered by a user rather
    # than by a test. So the pages are read.
    # ------------------------------------------------------

    pages = sorted(
        (
            PROJECT_ROOT
            / "frontend"
            / "pages"
        ).glob(
            "*.html"
        )
    )

    assert_true(
        pages,
        "No pages found to check the policy against.",
    )

    violations = []

    for page in pages:

        html = page.read_text(
            encoding="utf-8"
        )

        name = page.name

        # An inline style attribute needs style-src
        # 'unsafe-inline'. The five in upload.html were
        # removed in Phase 11.6 for exactly this reason.
        for match in re.finditer(
            r'style="[^"]*"',
            html,
        ):
            violations.append(
                f"{name}: inline style {match.group(0)[:40]}"
            )

        # An inline <script> block, as opposed to
        # <script src="...">.
        for match in re.finditer(
            r"<script(?![^>]*\bsrc=)[^>]*>",
            html,
        ):
            violations.append(
                f"{name}: inline script {match.group(0)[:40]}"
            )

        # An inline event handler is inline script.
        for attribute in (
            "onclick",
            "onload",
            "onsubmit",
            "onchange",
            "onerror",
        ):

            if f"{attribute}=" in html:
                violations.append(
                    f"{name}: inline handler {attribute}"
                )

        if "javascript:" in html:
            violations.append(
                f"{name}: javascript: URL"
            )

        # An external host would need to be named in the
        # policy.
        for match in re.finditer(
            r'(?:src|href)="(https?:)?//[^"]+"',
            html,
        ):
            violations.append(
                f"{name}: external resource "
                f"{match.group(0)[:50]}"
            )

    assert_equal(
        violations,
        [],
        (
            "A page contains something the policy forbids, "
            "so the interface would break in a browser:\n"
            + "\n".join(
                violations
            )
        ),
    )

    ok(
        f"{len(pages)} pages contain no inline style, no "
        f"inline script, no inline handler and no external "
        f"resource"
    )


    # SELF-CHECK. The detector has to be able to see one.
    probe_html = '<div style="margin: 0"></div><script>x()</script>'

    found = bool(
        re.search(
            r'style="[^"]*"',
            probe_html,
        )
    ) and bool(
        re.search(
            r"<script(?![^>]*\bsrc=)[^>]*>",
            probe_html,
        )
    )

    assert_true(
        found,
        (
            "The inline-content detector cannot see a "
            "constructed inline style and script. It is "
            "broken, and the assertion above would pass for "
            "the wrong reason."
        ),
    )

    ok(
        "detector self-checked against a constructed inline "
        "style and inline script"
    )


# ==========================================================
# TEST 5 - CORS
# ==========================================================

CORS_PROBE = """
import json

from fastapi.testclient import TestClient

from backend.app.main import app


out = {}

with TestClient(app) as client:

    for label, origin in (
        ("no_origin", None),
        ("allowed", "https://reviews.example.com"),
        ("other", "https://evil.example.com"),
    ):

        headers = (
            {"Origin": origin}
            if origin
            else {}
        )

        response = client.get(
            "/api/v1/documents",
            headers=headers,
        )

        out[label] = {
            "status": response.status_code,
            "allow_origin": response.headers.get(
                "access-control-allow-origin"
            ),
            "vary": response.headers.get("vary"),
        }

print(json.dumps(out))
"""


def test_cors():

    section(
        "TEST 5 - NO CORS BY DEFAULT, AN ALLOWLIST WHEN "
        "ASKED, NEVER '*'"
    )


    # ------------------------------------------------------
    # NONE, BY DEFAULT
    # ------------------------------------------------------
    # The frontend is served by this same application from
    # the same origin, so a browser never makes a
    # cross-origin request and no header is needed.
    # ------------------------------------------------------

    default = result_of(
        probe(
            CORS_PROBE
        )
    )

    for label, response in default.items():

        assert_equal(
            response["allow_origin"],
            None,
            (
                f"No Access-Control-Allow-Origin may be sent "
                f"by default ({label}).\n"
                "The interface is same-origin. A permissive "
                "header here would be the difference between "
                "an API only these pages can call and one any "
                "page on the internet can call on behalf of a "
                "signed-in reviewer."
            ),
        )

    ok(
        "no Access-Control-Allow-Origin on any of the 3 "
        "requests by default"
    )


    # ------------------------------------------------------
    # AN ALLOWLIST, ECHOED SPECIFICALLY
    # ------------------------------------------------------

    allowlisted = result_of(
        probe(
            CORS_PROBE,
            {
                "VIGILOX_CORS_ORIGINS": (
                    "https://reviews.example.com"
                ),
            },
        )
    )

    assert_equal(
        allowlisted["allowed"]["allow_origin"],
        "https://reviews.example.com",
        (
            "An allowlisted origin must be echoed back "
            "specifically, not as '*'."
        ),
    )

    assert_true(
        "Origin"
        in (
            allowlisted["allowed"]["vary"]
            or ""
        ),
        (
            "Vary: Origin is required when the response "
            "depends on the request origin, or a shared cache "
            "serves one origin's response to another."
        ),
    )

    assert_equal(
        allowlisted["other"]["allow_origin"],
        None,
        (
            "An origin NOT on the allowlist gets no header. "
            "This is the assertion that makes the allowlist "
            "an allowlist."
        ),
    )

    assert_equal(
        allowlisted["no_origin"]["allow_origin"],
        None,
        (
            "A request with no Origin at all gets no header."
        ),
    )

    ok(
        "the allowlisted origin is echoed with Vary: Origin; "
        "another origin gets nothing"
    )


    # ------------------------------------------------------
    # "*" IS REFUSED, NOT HONOURED
    # ------------------------------------------------------

    wildcard = result_of(
        probe(
            CORS_PROBE,
            {
                "VIGILOX_CORS_ORIGINS": "*",
            },
        )
    )

    for label, response in wildcard.items():

        assert_equal(
            response["allow_origin"],
            None,
            (
                "VIGILOX_CORS_ORIGINS='*' must be REFUSED, "
                "not honoured.\n"
                "An allowlist that allows everything is not "
                "an allowlist, and this API is called with a "
                "reviewer identity attached."
            ),
        )

    ok(
        "VIGILOX_CORS_ORIGINS='*' is discarded and no header "
        "is sent"
    )


# ==========================================================
# TEST 6 - THE RATE LIMIT
# ==========================================================

RATE_PROBE = """
import json
import io
import uuid

RUN_MARKER = uuid.uuid4().hex[:12]

from fastapi.testclient import TestClient

from backend.app.main import app


def upload(client, name):

    # Unique bytes per upload AND per run.
    #
    # Per upload, because identical bytes are refused by Phase
    # 10.3 duplicate detection with a 409 -- correct
    # behaviour, and it would hide whether the rate limiter
    # did anything.
    #
    # Per RUN, because a job left QUEUED by an earlier run
    # holds the same fingerprint and refuses this run's upload
    # for the same reason. The first version of this probe
    # reused fixed bytes and every upload came back 409 on the
    # second run.
    #
    # This is the same lesson the Phase 10.2 and 10.3 suites
    # learned: a test against a durable queue has to be
    # independent of what is already in it.
    return client.post(
        "/api/v1/document-jobs",
        files={
            "file": (
                name,
                io.BytesIO(
                    b"not-a-real-image-"
                    + RUN_MARKER.encode()
                    + b"-"
                    + name.encode()
                ),
                "image/jpeg",
            )
        },
    )


out = {"uploads": [], "reads": []}

created_jobs = []

with TestClient(app, client=("198.51.100.7", 9000)) as client:

    for index in range(6):

        response = upload(client, "rate-%d.jpg" % index)

        if response.status_code == 202:

            job_id = response.json().get("job_id")

            if job_id:
                created_jobs.append(job_id)

        out["uploads"].append(
            {
                "status": response.status_code,
                "code": (
                    response.json()
                    .get("error", {})
                    .get("code")
                    if response.headers.get(
                        "content-type", ""
                    ).startswith("application/json")
                    else None
                ),
                "retry_after": response.headers.get(
                    "retry-after"
                ),
                "request_id": response.headers.get(
                    "x-request-id"
                ),
                "csp": bool(
                    response.headers.get(
                        "content-security-policy"
                    )
                ),
            }
        )

    # Reads must not be limited: the dashboard polls them.
    for index in range(6):

        response = client.get("/api/v1/documents")

        out["reads"].append(response.status_code)


# ------------------------------------------------------
# THE JOBS THIS PROBE CREATED MUST NOT OUTLIVE IT
# ------------------------------------------------------
# An accepted upload is a real durable job row plus real
# pending bytes on disk. Phase 11.1 found what happens when a
# test leaves those behind: they sit QUEUED forever, they turn
# up in the operational queue depth, and a worker that does
# start will pick up a file that was never an image.
#
# The queue is durable on purpose, which is exactly why a test
# has to tidy up after itself.
# ------------------------------------------------------

from database.database import SessionLocal
from database.models import DocumentJobModel
from backend.app.services.job_source_store import (
    JobSourceStore,
)

store = JobSourceStore()

with SessionLocal() as session:

    for job_id in created_jobs:

        row = session.get(DocumentJobModel, job_id)

        if row is None:
            continue

        try:
            store.delete_pending(row.source_name)
        except Exception:
            pass

        session.delete(row)

    session.commit()

print(json.dumps(out))
"""


def test_rate_limit():

    section(
        "TEST 6 - THE UPLOAD RATE LIMIT REFUSES CORRECTLY "
        "AND LEAVES READS ALONE"
    )

    observed = result_of(
        probe(
            RATE_PROBE,
            {
                "VIGILOX_UPLOAD_RATE_LIMIT": "3",
                "VIGILOX_UPLOAD_RATE_WINDOW_SECONDS": "60",
            },
        )
    )

    uploads = observed[
        "uploads"
    ]

    limited = [
        entry
        for entry in uploads
        if entry["status"] == 429
    ]

    assert_equal(
        len(
            limited
        ),
        3,
        (
            "With a limit of 3, six uploads must produce "
            "three refusals.\n"
            f"Got: {[entry['status'] for entry in uploads]}"
        ),
    )

    assert_equal(
        [
            entry["status"]
            for entry in uploads[:3]
        ],
        [
            202,
            202,
            202,
        ],
        (
            "The first three must be accepted outright. A "
            "limiter that refuses the first request is not a "
            "limiter, and a 409 here would mean duplicate "
            "detection fired instead and the limit was never "
            "exercised."
        ),
    )

    ok(
        f"limit 3: statuses "
        f"{[entry['status'] for entry in uploads]}"
    )


    # ------------------------------------------------------
    # THE REFUSAL IS A PROPER RESPONSE
    # ------------------------------------------------------
    # It is generated before the router, so no exception
    # handler is in scope. It still has to look like every
    # other refusal, or a client that parses errors breaks on
    # this one alone.
    # ------------------------------------------------------

    refusal = limited[0]

    assert_equal(
        refusal["code"],
        "RATE_LIMITED",
        (
            "The refusal must use the same error envelope as "
            "every other error, with a stable code."
        ),
    )

    assert_true(
        refusal["retry_after"],
        (
            "A 429 must say when to try again. Without "
            "Retry-After a client either gives up or retries "
            "immediately, and the second is worse."
        ),
    )

    assert_true(
        refusal["request_id"],
        (
            "The 429 must carry the correlation ID.\n"
            "This is why the rate limiter is registered "
            "INSIDE the request-context middleware: a refused "
            "upload has to be traceable to the same request "
            "in the logs as any other."
        ),
    )

    assert_equal(
        refusal["csp"],
        True,
        (
            "And the security headers must be on it too, "
            "which is why the security middleware is the "
            "innermost of the three."
        ),
    )

    ok(
        f"the 429 carries code RATE_LIMITED, Retry-After "
        f"{refusal['retry_after']}s, a request ID, and the "
        f"security headers"
    )


    # ------------------------------------------------------
    # READS ARE NOT LIMITED
    # ------------------------------------------------------

    assert_true(
        all(
            status == 200
            for status in observed["reads"]
        ),
        (
            "Reads must not be rate limited.\n"
            f"Got: {observed['reads']}\n"
            "An upload books thirty seconds of a worker. A "
            "GET reads a row, and the dashboard polls it. "
            "Limiting reads adds a failure mode for no "
            "benefit."
        ),
    )

    ok(
        f"{len(observed['reads'])} consecutive reads all 200 "
        f"while uploads were being refused"
    )


    # ------------------------------------------------------
    # IT CAN BE TURNED OFF
    # ------------------------------------------------------

    disabled = result_of(
        probe(
            RATE_PROBE,
            {
                "VIGILOX_RATE_LIMIT_ENABLED": "false",
                "VIGILOX_UPLOAD_RATE_LIMIT": "3",
            },
        )
    )

    assert_true(
        all(
            entry["status"] != 429
            for entry in disabled["uploads"]
        ),
        (
            "With the limiter disabled, nothing may be "
            "refused by it. A deployment behind a gateway "
            "that already limits should be able to turn this "
            "off rather than have two limits interacting."
        ),
    )

    ok(
        "with VIGILOX_RATE_LIMIT_ENABLED=false, none of the "
        "6 uploads is refused"
    )


# ==========================================================
# TEST 7 - A FORWARDED ADDRESS IS ONLY TRUSTED FROM A PROXY
# ==========================================================

FORWARDED_PROBE = """
import json
import io
import uuid

RUN_MARKER = uuid.uuid4().hex[:12]

from fastapi.testclient import TestClient

from backend.app.main import app


def upload(client, index, forwarded):

    return client.post(
        "/api/v1/document-jobs",
        files={
            "file": (
                "f-%d.jpg" % index,
                io.BytesIO(
                    b"forwarded-probe-"
                    + RUN_MARKER.encode()
                    + b"-%d" % index
                ),
                "image/jpeg",
            )
        },
        headers={"X-Forwarded-For": forwarded},
    )


out = {}

created_jobs = []

# Untrusted peer, a DIFFERENT forwarded address every time.
# If the forwarded header were honoured, each request would
# look like a new client and the limit would never apply.
with TestClient(app, client=("198.51.100.7", 9000)) as client:

    statuses = []

    for index in range(6):

        response = upload(
            client,
            index,
            "203.0.113.%d" % index,
        )

        statuses.append(response.status_code)

        if response.status_code == 202:

            job_id = response.json().get("job_id")

            if job_id:
                created_jobs.append(job_id)

    out["untrusted"] = statuses


# ------------------------------------------------------
# THE JOBS THIS PROBE CREATED MUST NOT OUTLIVE IT
# ------------------------------------------------------
# An accepted upload is a real durable job row plus real
# pending bytes on disk. Phase 11.1 found what happens when a
# test leaves those behind: they sit QUEUED forever, they turn
# up in the operational queue depth, and a worker that does
# start will pick up a file that was never an image.
#
# The queue is durable on purpose, which is exactly why a test
# has to tidy up after itself.
# ------------------------------------------------------

from database.database import SessionLocal
from database.models import DocumentJobModel
from backend.app.services.job_source_store import (
    JobSourceStore,
)

store = JobSourceStore()

with SessionLocal() as session:

    for job_id in created_jobs:

        row = session.get(DocumentJobModel, job_id)

        if row is None:
            continue

        try:
            store.delete_pending(row.source_name)
        except Exception:
            pass

        session.delete(row)

    session.commit()

print(json.dumps(out))
"""


def test_forwarded_address_is_not_trusted_blindly():

    section(
        "TEST 7 - X-Forwarded-For FROM AN UNTRUSTED PEER IS "
        "IGNORED BY THE LIMITER"
    )

    observed = result_of(
        probe(
            FORWARDED_PROBE,
            {
                "VIGILOX_UPLOAD_RATE_LIMIT": "3",
                "VIGILOX_UPLOAD_RATE_WINDOW_SECONDS": "60",
            },
        )
    )

    statuses = observed[
        "untrusted"
    ]

    assert_true(
        429 in statuses,
        (
            "Six uploads from one untrusted peer, each "
            "claiming a different X-Forwarded-For, must "
            "still hit the limit.\n"
            f"Got: {statuses}\n"
            "Honouring a forwarded address from an untrusted "
            "peer is the standard way this kind of limiter is "
            "defeated: send a new value every request and the "
            "limit never applies."
        ),
    )

    assert_equal(
        len(
            [
                status
                for status in statuses
                if status == 429
            ]
        ),
        3,
        (
            "And exactly three should be refused, as if the "
            "header were not there at all."
        ),
    )

    ok(
        f"6 uploads with 6 different X-Forwarded-For values "
        f"from one untrusted peer: {statuses}"
    )


# ==========================================================
# TEST 8 - THE LIMIT IS DESCRIBED HONESTLY
# ==========================================================

def test_rate_limit_is_described_honestly():

    section(
        "TEST 8 - THE RATE LIMIT DOES NOT CLAIM TO BE "
        "SOMETHING IT IS NOT"
    )

    source = (
        PROJECT_ROOT
        / "backend"
        / "app"
        / "api"
        / "rate_limit.py"
    ).read_text(
        encoding="utf-8"
    )

    lowered = source.lower()


    # ------------------------------------------------------
    # IT SAYS WHAT IT IS
    # ------------------------------------------------------
    # The failure mode of this limiter is not that it stops
    # working. It is that somebody reads "rate limit" and
    # believes total load is bounded, when what is bounded is
    # one process.
    # ------------------------------------------------------

    for phrase, why in (
        (
            "not a globally reliable",
            (
                "it must state plainly that it is not a "
                "global limit"
            ),
        ),
        (
            "per-process",
            (
                "it must name the scope it actually has"
            ),
        ),
        (
            "n times the configured limit",
            (
                "it must spell out what replicas do to the "
                "effective limit"
            ),
        ),
        (
            "restart forgets",
            (
                "it must say that the state does not survive "
                "a restart"
            ),
        ),
    ):

        assert_true(
            phrase in lowered,
            (
                f"backend/app/api/rate_limit.py must say "
                f"{phrase!r}: {why}."
            ),
        )

    ok(
        "the module states that it is per-process, not "
        "global, multiplied by replicas, and lost on restart"
    )


    # ------------------------------------------------------
    # AND NOTHING OVERSTATES IT
    # ------------------------------------------------------

    overstated = []

    for claim in (
        "globally reliable rate limit",
        "global rate limit prevents",
        "guarantees the total",
        "cluster-wide",
    ):

        if claim in lowered:
            overstated.append(
                claim
            )

    assert_equal(
        overstated,
        [],
        (
            f"The module overstates what it does: "
            f"{overstated}"
        ),
    )

    ok(
        "no claim of a global, cluster-wide or guaranteed "
        "limit anywhere in the module"
    )


    # ------------------------------------------------------
    # AND THE MEMORY IS BOUNDED
    # ------------------------------------------------------
    # A limiter that grows a dictionary per distinct client
    # until the process dies is the denial of service it was
    # added to reduce.
    # ------------------------------------------------------

    from backend.app.api.rate_limit import (
        MAX_TRACKED_CLIENTS,
        SlidingWindowCounter,
    )

    counter = SlidingWindowCounter(
        limit=5,
        window_seconds=60,
        max_clients=50,
    )

    for index in range(
        500
    ):
        counter.check(
            f"client-{index}",
            now=float(
                index
            ),
        )

    tracked = len(
        counter._events
    )

    assert_true(
        tracked <= 50,
        (
            f"After 500 distinct clients with a cap of 50, "
            f"{tracked} are still tracked.\n"
            "An unbounded limiter is a memory exhaustion "
            "primitive: a caller cycling addresses grows the "
            "dictionary until the process dies, which is the "
            "attack the limiter exists to make harder."
        ),
    )

    assert_true(
        MAX_TRACKED_CLIENTS > 0,
        "There must be a cap at all.",
    )

    ok(
        f"500 distinct clients against a cap of 50 leaves "
        f"{tracked} tracked; production cap is "
        f"{MAX_TRACKED_CLIENTS}"
    )


# ==========================================================
# MAIN
# ==========================================================

def main() -> int:

    print(
        "=" * 74
    )
    print(
        "PHASE 11.5 / 11.6 / 11.7 - SECURITY BOUNDARY"
    )
    print(
        "=" * 74
    )

    test_identity_boundary()
    test_production_posture()
    test_security_headers()
    test_csp_matches_the_pages()
    test_cors()
    test_rate_limit()
    test_forwarded_address_is_not_trusted_blindly()
    test_rate_limit_is_described_honestly()

    print()
    print(
        "=" * 74
    )
    print(
        "[PASS] PHASE 11.5-11.7 SECURITY BOUNDARY TEST "
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
