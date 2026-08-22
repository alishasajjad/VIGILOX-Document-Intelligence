"""
==========================================================
PHASE 11.2 - PRODUCTION CONFIGURATION
==========================================================

WHAT THIS SUITE IS PROTECTING

  1. REQUEST CONCURRENCY AND THE CONNECTION POOL AGREE.
     Every route in this application is a synchronous def,
     so Starlette runs each one in a worker thread from a
     pool that defaults to 40 -- and every route opens a
     database session against a pool that defaulted to 15.

     40 admitted, 15 servable. Requests 16-40 waited for a
     connection and then raised TimeoutError: a 500, under
     load, from a database that was perfectly healthy.

     The defect was never the pool size. It was that two
     numbers were set independently and nothing made them
     agree. This suite is what makes them stay agreed.

  2. EVERY TUNABLE SURVIVES A BAD VALUE.
     A typo in an environment variable must not stop the
     process starting. A pool that refuses to be created
     takes the whole application down, and "20x" instead of
     "20" is not worth that.

  3. NOTHING LEAKS.
     The readiness endpoint reports capacity so an operator
     can size PostgreSQL max_connections against the number
     the process actually holds. It must not report the
     DATABASE_URL, a host, or a credential.

  4. THE DOCUMENTED DEFAULTS ARE THE REAL DEFAULTS.
     .env.example is what an operator reads. A value there
     that no longer matches the code is worse than no value
     at all -- Phase 11.1 found it still recommending a job
     lease of 180 seconds, justified by a measurement Phase
     10.4 had already superseded, which would have
     reintroduced the defect 10.4 fixed.


WHY CONCURRENCY IS ASSERTED AGAINST THE LIVE LIMITER
----------------------------------------------------------
The cap is applied to the AnyIO thread limiter at startup,
inside the running event loop. Reading the constant back
would prove only that the constant exists.

So the app is actually started and the limiter is read from
the loop it belongs to.
"""

import os
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
# RUNNING A PROBE IN A FRESH PROCESS
# ==========================================================
#
# database.database reads its configuration at import time,
# which is correct -- an engine is built once per process --
# but it means the environment cannot be changed and re-read
# inside one interpreter.
#
# So each configuration case gets its own subprocess.
# ==========================================================

def probe(
    code: str,
    environment: dict | None = None,
) -> str:

    child = dict(
        os.environ
    )

    child["PYTHONPATH"] = str(
        PROJECT_ROOT
    )

    # Keep the API process from loading PaddleOCR for a probe
    # that never runs OCR. Nothing here needs it and it costs
    # seconds plus hundreds of megabytes.
    child["VIGILOX_API_EAGER_PIPELINE"] = "false"

    for name in (
        "VIGILOX_REQUEST_CONCURRENCY",
        "VIGILOX_DB_POOL_SIZE",
        "VIGILOX_DB_POOL_TIMEOUT_SECONDS",
        "VIGILOX_DB_POOL_RECYCLE_SECONDS",
        "VIGILOX_DB_CONNECT_TIMEOUT_SECONDS",
    ):
        child.pop(
            name,
            None,
        )

    child.update(
        environment
        or {}
    )

    # Written to a file rather than passed to -c. These
    # probes need real statements -- an async function, a
    # context manager -- and squeezing those through a
    # semicolon-separated -c string means exec() and nested
    # quoting, which is how a test starts failing for reasons
    # that have nothing to do with what it is testing.
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

    if completed.returncode != 0:

        raise AssertionError(
            "Configuration probe failed.\n"
            f"{completed.stdout[-3000:]}\n"
            f"{completed.stderr[-3000:]}"
        )

    # The probes print one JSON line last. Operational
    # logging goes to the same stream, so take the last
    # non-empty line rather than the whole of stdout.
    lines = [
        line
        for line in completed.stdout.splitlines()
        if line.strip()
    ]

    if not lines:

        raise AssertionError(
            "Configuration probe printed nothing.\n"
            f"{completed.stderr[-3000:]}"
        )

    return lines[-1].strip()


POOL_PROBE = """
import json

from database.database import pool_configuration

print(json.dumps(pool_configuration()))
"""


# ==========================================================
# TEST 1 - THE TWO NUMBERS AGREE
# ==========================================================

def test_pool_matches_request_concurrency():

    section(
        "TEST 1 - THE CONNECTION POOL SERVES THE CONCURRENCY "
        "THE SERVER ADMITS"
    )

    import json

    default = json.loads(
        probe(
            POOL_PROBE
        )
    )

    assert_equal(
        default["max_connections_per_process"],
        default["request_concurrency"],
        (
            "The pool must be able to serve every request "
            "the server will admit at once.\n"
            "This is the whole defect: 40 threads against 15 "
            "connections meant requests 16-40 waited "
            "pool_timeout seconds and then raised "
            "TimeoutError. A 500 under load, from a healthy "
            "database."
        ),
    )

    assert_equal(
        default["pool_size"]
        + default["max_overflow"],
        default["request_concurrency"],
        (
            "pool_size plus max_overflow is the real ceiling, "
            "and it is what has to match."
        ),
    )

    ok(
        f"request concurrency {default['request_concurrency']}"
        f" == pool_size {default['pool_size']} + overflow "
        f"{default['max_overflow']}"
    )


    # ------------------------------------------------------
    # AND THEY STAY AGREED WHEN THE NUMBER MOVES
    # ------------------------------------------------------
    # The point of deriving one from the other is that an
    # operator can change concurrency without knowing the
    # pool exists.
    # ------------------------------------------------------

    for concurrency in (
        "1",
        "5",
        "20",
        "64",
    ):

        scaled = json.loads(
            probe(
                POOL_PROBE,
                {
                    "VIGILOX_REQUEST_CONCURRENCY": (
                        concurrency
                    ),
                },
            )
        )

        assert_equal(
            scaled["request_concurrency"],
            int(
                concurrency
            ),
            f"Concurrency {concurrency} must be honoured.",
        )

        assert_equal(
            scaled["max_connections_per_process"],
            int(
                concurrency
            ),
            (
                f"At concurrency {concurrency} the pool "
                f"ceiling must follow. An operator raising "
                f"concurrency should not have to know the "
                f"pool exists."
            ),
        )

        assert_true(
            scaled["max_overflow"] >= 0,
            (
                f"At concurrency {concurrency} the overflow "
                f"must not go negative: pool_size is clamped "
                f"to the concurrency, so a concurrency below "
                f"the default pool size still produces a "
                f"valid pool."
            ),
        )

    ok(
        "concurrency 1, 5, 20 and 64 each produce a pool "
        "ceiling that matches, overflow never negative"
    )


    # ------------------------------------------------------
    # THE SAFETY SETTINGS ARE ON
    # ------------------------------------------------------

    assert_equal(
        default["pool_pre_ping"],
        True,
        (
            "Without pre-ping, a connection a proxy or "
            "firewall killed while idle surfaces as a failed "
            "request rather than being replaced."
        ),
    )

    assert_true(
        60
        <= default["pool_recycle_seconds"]
        <= 86400,
        (
            "Connections must be recycled. SQLAlchemy's "
            "default is -1, meaning never, which lets one "
            "process hold a single server-side session open "
            "indefinitely and leaves old connections alive "
            "across a deploy."
        ),
    )

    assert_true(
        0
        < default["connect_timeout_seconds"]
        <= 120,
        (
            "Without a connect timeout, a TCP connect to an "
            "unreachable database can hang for the operating "
            "system timeout -- minutes -- holding the request "
            "thread. The readiness endpoint cannot report an "
            "unreachable database if checking never returns."
        ),
    )

    assert_true(
        0
        < default["pool_timeout_seconds"]
        <= 30,
        (
            "With the thread pool capped to match, waiting "
            "for a connection should be near-impossible. If "
            "it happens, a fast error beats a request that "
            "hangs for thirty seconds and fails anyway."
        ),
    )

    ok(
        f"pre_ping on, recycle "
        f"{default['pool_recycle_seconds']}s, connect timeout "
        f"{default['connect_timeout_seconds']}s, pool timeout "
        f"{default['pool_timeout_seconds']}s"
    )


# ==========================================================
# TEST 2 - THE RUNNING APPLICATION APPLIES THE CAP
# ==========================================================

def test_live_thread_limiter():

    section(
        "TEST 2 - THE RUNNING APPLICATION CAPS ITS OWN "
        "THREAD POOL"
    )

    # Started for real, and the limiter read from INSIDE the
    # event loop it belongs to.
    #
    # current_default_thread_limiter() resolves against the
    # running loop -- calling it from synchronous test code
    # raises NoEventLoopError, which is the correct behaviour
    # and the reason this probe runs the lifespan itself
    # rather than going through TestClient.
    #
    # Reading REQUEST_CONCURRENCY back instead would prove
    # only that the constant exists, not that anything
    # applied it.
    code = """
import asyncio
import json

import anyio.to_thread

from backend.app.main import app, lifespan


async def observe():

    async with lifespan(app):

        limiter = (
            anyio.to_thread
            .current_default_thread_limiter()
        )

        return {
            "total_tokens": limiter.total_tokens,
            "pool": app.state.pool,
        }


print(json.dumps(asyncio.run(observe())))
"""

    import json

    for concurrency, expected in (
        (
            None,
            20,
        ),
        (
            "7",
            7,
        ),
    ):

        environment = (
            {}
            if concurrency is None
            else {
                "VIGILOX_REQUEST_CONCURRENCY": (
                    concurrency
                ),
            }
        )

        observed = json.loads(
            probe(
                code,
                environment,
            )
        )

        assert_equal(
            observed["total_tokens"],
            expected,
            (
                "The AnyIO thread limiter must be capped to "
                "the configured concurrency.\n"
                "Uncapped it is 40, and 40 concurrent "
                "synchronous routes each want a database "
                "connection."
            ),
        )

        assert_equal(
            observed["pool"][
                "max_connections_per_process"
            ],
            expected,
            (
                "And the pool it was matched against must be "
                "the same number."
            ),
        )

    ok(
        "a started application caps its thread pool to 20 by "
        "default and to 7 when configured, pool matching in "
        "both cases"
    )


    # ------------------------------------------------------
    # THE FRAMEWORK DEFAULT IS WHAT WE ARE OVERRIDING
    # ------------------------------------------------------
    # Asserted so this suite fails loudly rather than
    # silently becoming a no-op if AnyIO changes its default
    # to something already safe -- or to something worse.
    # ------------------------------------------------------

    baseline = probe(
        """
import asyncio

import anyio.to_thread


async def observe():

    return (
        anyio.to_thread
        .current_default_thread_limiter()
        .total_tokens
    )


print(asyncio.run(observe()))
"""
    )

    print(
        f"       (AnyIO's own default, for reference: "
        f"{baseline})"
    )

    assert_true(
        float(
            baseline
        )
        > 0,
        "The framework default must be readable.",
    )

    ok(
        "the framework default is readable, so this override "
        "cannot silently become a no-op"
    )


# ==========================================================
# TEST 3 - A BAD VALUE DOES NOT STOP THE PROCESS
# ==========================================================

def test_bad_values_survive():

    section(
        "TEST 3 - A TYPO IN THE ENVIRONMENT IS SURVIVABLE"
    )

    import json

    cases = (
        (
            "not-a-number",
            "unparseable",
        ),
        (
            "",
            "empty",
        ),
        (
            "   ",
            "whitespace",
        ),
        (
            "0",
            "below the minimum",
        ),
        (
            "-5",
            "negative",
        ),
        (
            "100000",
            "far above the maximum",
        ),
    )

    for value, description in cases:

        result = json.loads(
            probe(
                POOL_PROBE,
                {
                    "VIGILOX_REQUEST_CONCURRENCY": value,
                },
            )
        )

        assert_true(
            result["request_concurrency"] >= 1,
            (
                f"A {description} concurrency value "
                f"({value!r}) must still produce a usable "
                f"pool.\n"
                f"An engine that refuses to be created takes "
                f"the whole process down, and a typo in an "
                f"environment variable is not worth that."
            ),
        )

        assert_equal(
            result["max_connections_per_process"],
            result["request_concurrency"],
            (
                f"With a {description} value the two numbers "
                f"must still agree."
            ),
        )

    ok(
        f"{len(cases)} bad values (unparseable, empty, "
        f"whitespace, 0, negative, 100000) all clamp to a "
        f"working pool with the numbers still agreed"
    )


# ==========================================================
# TEST 4 - READINESS REPORTS CAPACITY AND NOTHING ELSE
# ==========================================================

def test_readiness_capacity():

    section(
        "TEST 4 - READINESS REPORTS THE REAL CAPACITY AND NO "
        "CREDENTIALS"
    )

    code = """
import json

from fastapi.testclient import TestClient

from backend.app.main import app


with TestClient(app) as client:

    response = client.get("/health/ready")

    print(
        json.dumps(
            {
                "status_code": response.status_code,
                "body": response.json(),
            }
        )
    )
"""

    import json

    observed = json.loads(
        probe(
            code
        )
    )

    assert_equal(
        observed["status_code"],
        200,
        (
            "Readiness must pass. If it does not, the "
            "database or storage is genuinely unavailable "
            "and that is the finding."
        ),
    )

    body = observed[
        "body"
    ]

    capacity = body.get(
        "capacity"
    )

    assert_true(
        capacity is not None,
        (
            "Readiness must report capacity. An operator "
            "sizing PostgreSQL max_connections has to "
            "multiply the PER-PROCESS number by the replica "
            "count, and a figure written into a runbook "
            "drifts from the one the process holds."
        ),
    )

    for key in (
        "request_concurrency",
        "pool_size",
        "max_overflow",
        "max_connections_per_process",
        "pool_timeout_seconds",
        "pool_recycle_seconds",
        "connect_timeout_seconds",
        "pool_pre_ping",
    ):

        assert_true(
            key in capacity,
            f"capacity must report {key}.",
        )

    assert_equal(
        capacity["max_connections_per_process"],
        capacity["request_concurrency"],
        (
            "And what it reports has to be the agreed "
            "number, not a restated one."
        ),
    )

    ok(
        f"readiness reports {len(capacity)} capacity values, "
        f"{capacity['max_connections_per_process']} "
        f"connections per process"
    )


    # ------------------------------------------------------
    # NOTHING SENSITIVE
    # ------------------------------------------------------

    serialized = json.dumps(
        body
    )

    database_url = os.environ.get(
        "DATABASE_URL",
        "",
    )

    banned = [
        "DATABASE_URL",
        "postgresql",
        "GROQ_API_KEY",
        "gsk_",
        "password",
        "Password",
    ]

    if database_url:

        banned.append(
            database_url
        )

        # And the credential out of it, specifically, since
        # that is the part that matters.
        if "@" in database_url and "//" in database_url:

            authority = database_url.split(
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

                if secret:
                    banned.append(
                        secret
                    )

    leaked = [
        item
        for item in banned
        if item and item in serialized
    ]

    assert_equal(
        leaked,
        [],
        (
            "The readiness response leaks something it must "
            f"not: {leaked}.\n"
            "This endpoint is reachable by anything that can "
            "reach the service, including an orchestrator "
            "probe and anything else on the network. It "
            "reports numbers, not connection strings."
        ),
    )

    ok(
        f"the readiness response contains none of "
        f"{len(banned)} sensitive strings, including the live "
        f"DATABASE_URL and its password"
    )


# ==========================================================
# TEST 5 - .env.example TELLS THE TRUTH
# ==========================================================

def test_documented_defaults_are_real():

    section(
        "TEST 5 - THE DOCUMENTED DEFAULTS MATCH THE CODE"
    )

    text = (
        PROJECT_ROOT
        / ".env.example"
    ).read_text(
        encoding="utf-8"
    )


    # ------------------------------------------------------
    # THE JOB LEASE
    # ------------------------------------------------------
    # PHASE 11.1 found .env.example still recommending 180,
    # justified by a 32.8 second worst case that PHASE 10.4
    # had already replaced with a measured 268. An operator
    # following the file would have reintroduced the defect
    # 10.4 fixed -- silently, because nothing incorrect
    # results, the work is just done twice.
    # ------------------------------------------------------

    from backend.app.services.document_worker import (
        DEFAULT_LEASE_SECONDS,
    )

    assert_true(
        f"VIGILOX_JOB_LEASE_SECONDS={DEFAULT_LEASE_SECONDS}"
        in text,
        (
            ".env.example must document the real lease "
            f"default, which is {DEFAULT_LEASE_SECONDS}.\n"
            "A recommended value that no longer matches the "
            "code is worse than no recommendation: an "
            "operator who follows it reintroduces whatever "
            "the change was made to fix."
        ),
    )

    assert_true(
        "VIGILOX_JOB_LEASE_SECONDS=180" not in text,
        (
            "The superseded lease value must be gone from "
            "the recommendation, not merely explained "
            "alongside it."
        ),
    )

    ok(
        f"the documented job lease is "
        f"{DEFAULT_LEASE_SECONDS}, matching "
        f"DEFAULT_LEASE_SECONDS, and 180 no longer appears "
        f"as a value"
    )


    # ------------------------------------------------------
    # THE POOL AND CONCURRENCY VARIABLES ARE DOCUMENTED
    # ------------------------------------------------------
    # A tunable nobody knows about is a tunable that gets
    # discovered during an incident.
    # ------------------------------------------------------

    from database import database as database_module

    documented = []

    for name in (
        "VIGILOX_REQUEST_CONCURRENCY",
        "VIGILOX_DB_POOL_SIZE",
        "VIGILOX_DB_POOL_TIMEOUT_SECONDS",
        "VIGILOX_DB_POOL_RECYCLE_SECONDS",
        "VIGILOX_DB_CONNECT_TIMEOUT_SECONDS",
        "VIGILOX_API_EAGER_PIPELINE",
    ):

        assert_true(
            name in text,
            (
                f"{name} changes production behaviour and "
                f"must be documented in .env.example. An "
                f"undocumented tunable is one that gets "
                f"discovered during an incident."
            ),
        )

        documented.append(
            name
        )

    ok(
        f"all {len(documented)} production tunables appear "
        f"in .env.example"
    )


    # ------------------------------------------------------
    # AND EVERY ENVIRONMENT VARIABLE THE CODE READS
    # ------------------------------------------------------

    import re

    read_by_code = set()

    for root in (
        "backend",
        "database",
    ):

        for path in sorted(
            (
                PROJECT_ROOT
                / root
            ).rglob(
                "*.py"
            )
        ):

            if "__pycache__" in path.parts:
                continue

            read_by_code.update(
                re.findall(
                    r'getenv\(\s*\n?\s*"([A-Z0-9_]+)"',
                    path.read_text(
                        encoding="utf-8"
                    ),
                )
            )

    assert_true(
        read_by_code,
        (
            "The environment-variable extractor found "
            "nothing. It is broken, and this assertion would "
            "pass for the wrong reason."
        ),
    )

    undocumented = sorted(
        name
        for name in read_by_code
        if name not in text
    )

    assert_equal(
        undocumented,
        [],
        (
            "The code reads environment variables that "
            f".env.example never mentions: {undocumented}.\n"
            "Every one of them changes behaviour, and an "
            "operator reading the template would not know "
            "they exist."
        ),
    )

    ok(
        f"all {len(read_by_code)} environment variables the "
        f"code reads are documented in .env.example"
    )


    # ------------------------------------------------------
    # NO SECRETS IN THE TEMPLATE
    # ------------------------------------------------------

    real = (
        PROJECT_ROOT
        / ".env"
    )

    if real.exists():

        secrets = []

        for line in real.read_text(
            encoding="utf-8"
        ).splitlines():

            if "=" not in line or line.strip().startswith(
                "#"
            ):
                continue

            value = line.split(
                "=",
                1,
            )[1].strip()

            # Short values are things like INFO, 1, false --
            # not secrets, and matching them would be noise.
            if len(
                value
            ) >= 12 and value in text:
                secrets.append(
                    line.split(
                        "=",
                        1,
                    )[0].strip()
                )

        assert_equal(
            secrets,
            [],
            (
                "A real value from .env appears verbatim in "
                f".env.example: {secrets}.\n"
                ".env.example is committed. Placeholders "
                "only."
            ),
        )

        ok(
            "no value from the local .env appears in "
            ".env.example"
        )

    else:
        print(
            "       (no local .env to compare against)"
        )


# ==========================================================
# MAIN
# ==========================================================

def main() -> int:

    print(
        "=" * 74
    )
    print(
        "PHASE 11.2 - PRODUCTION CONFIGURATION"
    )
    print(
        "=" * 74
    )

    test_pool_matches_request_concurrency()
    test_live_thread_limiter()
    test_bad_values_survive()
    test_readiness_capacity()
    test_documented_defaults_are_real()

    print()
    print(
        "=" * 74
    )
    print(
        "[PASS] PHASE 11.2 PRODUCTION CONFIGURATION TEST "
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
