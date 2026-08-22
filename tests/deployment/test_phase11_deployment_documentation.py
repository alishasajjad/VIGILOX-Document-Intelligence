import pathlib
import re
import subprocess
import sys

from pathlib import Path


# ==========================================================
# PHASE 11.15 - DEPLOYMENT DOCUMENTATION AND VALIDATION
# ==========================================================
#
# Documentation tests are usually worthless: they assert a
# heading exists and pass forever while the text underneath
# goes stale.
#
# So these assert the things that can actually be WRONG, by
# checking the documents against the artifacts they describe:
#
#   every file path a document names must exist
#   every environment variable it names must be one the code
#     reads and .env.example documents
#   every measured number it quotes must match the number the
#     code or the tests actually use
#   the validator must probe a running service, not read a
#     config file
#   nothing may claim a component is deployed when it is not
#
# A document that says stop_grace_period is 400s while the
# compose file says 60s is worse than no document, because it
# will be believed.
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


OPERATIONS = (
    PROJECT_ROOT
    / "docs"
    / "operations"
)

VALIDATOR = (
    PROJECT_ROOT
    / "scripts"
    / "verification"
    / "validate_deployment.py"
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


DEPLOYMENT_DOCS = (
    PROJECT_ROOT
    / "docs"
    / "deployment"
)


# The document set spans two directories, and the links
# between them cross that boundary. Both are read together so
# a link from one to the other is still checked, and each
# document remembers which directory it lives in so relative
# links resolve from the right place.

def operations_documents() -> dict:

    documents = {}

    for directory in (
        OPERATIONS,
        DEPLOYMENT_DOCS,
    ):

        for path in sorted(
            directory.glob(
                "*.md"
            )
        ):

            documents[path.name] = path.read_text(
                encoding="utf-8",
            )

    return documents


def document_directory(
    name: str,
) -> pathlib.Path:

    for directory in (
        OPERATIONS,
        DEPLOYMENT_DOCS,
    ):

        if (
            directory
            / name
        ).is_file():
            return directory

    raise AssertionError(
        f"{name} is in neither documentation directory."
    )


# ==========================================================
# TEST 1 - THE DOCUMENTS EXIST AND CROSS-REFERENCE
# ==========================================================

def test_the_set_is_complete() -> None:

    section(
        "TEST 1 - THE OPERATIONS DOCUMENTS EXIST AND LINK TO "
        "EACH OTHER"
    )

    documents = operations_documents()

    expected = {
        # docs/deployment/
        "deployment.md",

        # docs/operations/
        "monitoring.md",
        "backup-restore.md",
        "shutdown.md",
        "production-runbook.md",
    }

    missing = sorted(
        expected - set(
            documents
        )
    )

    assert_equal(
        missing,
        [],
        (
            "The operations set is incomplete. Each of these "
            "answers a question somebody has at 3am."
        ),
    )

    ok(
        f"{len(expected)} operations documents present: "
        + ", ".join(
            sorted(
                expected
            )
        )
    )

    # ------------------------------------------------------
    # EVERY RELATIVE LINK RESOLVES
    # ------------------------------------------------------
    #
    # A broken link in a runbook is followed at the worst
    # possible moment.

    broken = []

    for name, text in documents.items():

        for target in re.findall(
            r"\]\((?!https?://)([^)#]+)",
            text,
        ):

            resolved = (
                document_directory(
                    name
                )
                / target
            ).resolve()

            if not resolved.exists():

                broken.append(
                    f"{name} -> {target}"
                )

    assert_equal(
        broken,
        [],
        "Every relative link must resolve.",
    )

    ok(
        "every relative link in the operations documents "
        "resolves to a real file"
    )


# ==========================================================
# TEST 2 - EVERY PATH AND SCRIPT NAMED IS REAL
# ==========================================================

def test_named_artifacts_exist() -> None:

    section(
        "TEST 2 - EVERY FILE AND SCRIPT THE DOCUMENTS NAME "
        "ACTUALLY EXISTS"
    )

    documents = operations_documents()

    missing = []

    checked = 0

    for name, text in documents.items():

        # Repository paths appear either in code spans or as
        # bare paths in command examples. Both are worth
        # checking; a command that names a script that does
        # not exist is a command that fails when it is needed.
        for candidate in set(
            re.findall(
                r"(?:scripts|docs|docker|tests|backend|"
                r"database|frontend|migrations)"
                r"/[A-Za-z0-9_./-]+",
                text,
            )
        ):

            target = candidate.rstrip(
                ".,)"
            )

            # A trailing directory reference is fine.
            if target.endswith(
                "/"
            ):
                target = target[:-1]

            checked += 1

            if not (
                PROJECT_ROOT
                / target
            ).exists():

                missing.append(
                    f"{name} names {target}"
                )

    assert_equal(
        missing,
        [],
        (
            "The documents name files that do not exist. A "
            "runbook is followed literally."
        ),
    )

    ok(
        f"all {checked} repository paths named across the "
        "operations documents exist"
    )


# ==========================================================
# TEST 2b - EVERY FLAG THE DOCUMENTS PASS ACTUALLY EXISTS
# ==========================================================

def test_documented_flags_exist() -> None:

    section(
        "TEST 2b - EVERY COMMAND-LINE FLAG THE DOCUMENTS USE "
        "IS ONE THE SCRIPT ACCEPTS"
    )

    # ------------------------------------------------------
    # TEST 2 checks that every PATH named exists. That is not
    # enough, and this test exists because of a real miss:
    # the runbook and the README both told an operator to run
    #
    #     reconcile_storage.py --report
    #
    # and the script has no such flag. Its dry run is the
    # default. TEST 2 was happy because the script existed.
    #
    # An invented flag is worse than an invented path: the
    # path fails immediately and obviously, while a plausible
    # flag makes an operator doubt their own typing during an
    # incident.
    #
    # The flags a script accepts are read from its own
    # argparse definitions, not from a list here -- a list
    # here would be a second place to keep in step.
    # ------------------------------------------------------

    documents = operations_documents()

    scripts = {}

    for path in sorted(
        (
            PROJECT_ROOT
            / "scripts"
        ).rglob(
            "*.py"
        )
    ):

        source = path.read_text(
            encoding="utf-8",
        )

        if "add_argument" not in source:
            continue

        flags = set(
            re.findall(
                r'add_argument\(\s*"(--[a-z0-9-]+)"',
                source,
            )
        )

        if flags:

            # argparse always provides these.
            flags |= {
                "--help",
            }

            scripts[
                path.name
            ] = flags

    assert_true(
        scripts,
        (
            "The flag detector found no argparse scripts. It "
            "is looking in the wrong place, and a check that "
            "cannot see the code it guards passes for the "
            "wrong reason."
        ),
    )

    invented = []

    checked = 0

    for name, text in documents.items():

        for line in text.splitlines():

            for script, flags in scripts.items():

                if script not in line:
                    continue

                for flag in re.findall(
                    r"(--[a-z0-9-]+)",
                    line,
                ):

                    checked += 1

                    if flag not in flags:

                        invented.append(
                            f"{name} passes {flag} to "
                            f"{script}, which accepts only "
                            + " ".join(
                                sorted(
                                    flags
                                )
                            )
                        )

    assert_equal(
        sorted(
            set(
                invented
            )
        ),
        [],
        (
            "The documents pass flags that do not exist."
        ),
    )

    ok(
        f"all {checked} flag use(s) across "
        f"{len(scripts)} documented script(s) are flags the "
        "script actually accepts"
    )

    # ------------------------------------------------------
    # AND THE DETECTOR IS CHECKED AGAINST A PLANTED CASE
    # ------------------------------------------------------

    planted_line = (
        "python scripts/maintenance/reconcile_storage.py "
        "--definitely-not-a-flag"
    )

    caught = [
        flag
        for flag in re.findall(
            r"(--[a-z0-9-]+)",
            planted_line,
        )
        if flag not in scripts["reconcile_storage.py"]
    ]

    assert_equal(
        caught,
        [
            "--definitely-not-a-flag",
        ],
        (
            "The detector must flag an invented option. If "
            "it does not, its verdict above proves nothing."
        ),
    )

    ok(
        "the detector catches a planted invented flag, so its "
        "verdict on the real documents means something"
    )


# ==========================================================
# TEST 3 - EVERY ENVIRONMENT VARIABLE NAMED IS REAL
# ==========================================================

def test_named_variables_are_real() -> None:

    section(
        "TEST 3 - EVERY VIGILOX VARIABLE THE DOCUMENTS NAME "
        "IS ONE THE CODE READS"
    )

    documents = operations_documents()

    # What the code actually reads.
    read_by_code = set()

    for path in PROJECT_ROOT.rglob(
        "*.py"
    ):

        if any(
            part in (
                ".venv",
                "__pycache__",
                "node_modules",
            )
            for part in path.parts
        ):
            continue

        read_by_code.update(
            re.findall(
                r"[\"'](VIGILOX_[A-Z_]+)[\"']",
                path.read_text(
                    encoding="utf-8",
                    errors="replace",
                ),
            )
        )

    # And what the deployment sets, which is also legitimate:
    # the compose file and the entrypoint pass some through.
    for path in (
        PROJECT_ROOT
        / "docker-compose.yml",
        PROJECT_ROOT
        / "docker"
        / "entrypoint.sh",
        PROJECT_ROOT
        / "Dockerfile",
        PROJECT_ROOT
        / ".env.example",
    ):

        if path.exists():

            read_by_code.update(
                re.findall(
                    r"(VIGILOX_[A-Z_]+)",
                    path.read_text(
                        encoding="utf-8",
                    ),
                )
            )

    invented = []

    named = set()

    for name, text in documents.items():

        for variable in re.findall(
            r"(VIGILOX_[A-Z_]+)",
            text,
        ):

            named.add(
                variable
            )

            if variable not in read_by_code:

                invented.append(
                    f"{name} names {variable}"
                )

    assert_equal(
        sorted(
            set(
                invented
            )
        ),
        [],
        (
            "The documents name environment variables "
            "nothing reads. An operator would set them and "
            "believe something changed."
        ),
    )

    ok(
        f"all {len(named)} VIGILOX_* variables named in the "
        "operations documents are read by the code or set by "
        "the deployment"
    )


# ==========================================================
# TEST 4 - THE QUOTED NUMBERS MATCH REALITY
# ==========================================================

def test_quoted_numbers_are_current() -> None:

    section(
        "TEST 4 - THE MEASURED NUMBERS IN THE DOCUMENTS "
        "MATCH THE CODE"
    )

    documents = operations_documents()

    combined = "\n".join(
        documents.values()
    )

    # ------------------------------------------------------
    # THE LEASE
    # ------------------------------------------------------

    from backend.app.services.document_worker import (
        DEFAULT_LEASE_SECONDS,
    )

    assert_true(
        str(
            DEFAULT_LEASE_SECONDS
        ) in combined,
        (
            f"The documents must quote the real lease "
            f"({DEFAULT_LEASE_SECONDS}s). An operator sizing "
            "a grace period or a quiesce window from a stale "
            "number reintroduces the Phase 10.4 defect."
        ),
    )

    # And the superseded value must not appear as a lease.
    for stale in re.findall(
        r"(\d+)\s*(?:s|seconds?)?\s*lease",
        combined,
    ):

        assert_equal(
            int(
                stale
            ),
            DEFAULT_LEASE_SECONDS,
            (
                "A document quotes a lease that is not the "
                "real one."
            ),
        )

    ok(
        f"the lease is quoted as {DEFAULT_LEASE_SECONDS}s "
        "everywhere it appears, matching "
        "DEFAULT_LEASE_SECONDS"
    )

    # ------------------------------------------------------
    # THE GRACE PERIODS
    # ------------------------------------------------------

    compose = (
        PROJECT_ROOT
        / "docker-compose.yml"
    ).read_text(
        encoding="utf-8",
    )

    worker_grace = int(
        [
            line.split(
                ":"
            )[1].strip().rstrip(
                "s"
            )
            for line in compose[
                compose.index(
                    "worker:"
                ):
            ].splitlines()
            if "stop_grace_period" in line
        ][0]
    )

    assert_true(
        f"{worker_grace}" in documents["shutdown.md"],
        (
            f"shutdown.md must quote the real worker grace "
            f"period ({worker_grace}s). It is the number an "
            "operator uses to decide how long a deploy will "
            "take."
        ),
    )

    assert_true(
        f"{worker_grace}" in documents["deployment.md"],
        (
            "deployment.md must quote it too: it is why step "
            "4 of a rolling deploy is slow."
        ),
    )

    ok(
        f"the worker grace period is quoted as "
        f"{worker_grace}s in both shutdown.md and "
        "deployment.md, matching docker-compose.yml"
    )

    # ------------------------------------------------------
    # THE OCR STARTUP MEASUREMENTS
    # ------------------------------------------------------
    #
    # 2929 ms eager against 3 ms lazy. These justify the API
    # and the worker being configured in opposite directions,
    # and the pair only makes sense together.

    for value in (
        "2929",
        "3 ms",
    ):

        assert_true(
            value in documents["deployment.md"],
            (
                f"deployment.md must quote {value}. The "
                "opposite settings for the API and the "
                "worker look arbitrary without the "
                "measurement behind them."
            ),
        )

    ok(
        "the eager/lazy OCR startup measurements are both "
        "quoted where the opposite settings are explained"
    )


# ==========================================================
# TEST 5 - NOTHING CLAIMS TO BE DEPLOYED THAT IS NOT
# ==========================================================

def test_no_false_claims() -> None:

    section(
        "TEST 5 - NOTHING IS CLAIMED TO BE RUNNING THAT IS "
        "NOT IN THE STACK"
    )

    documents = operations_documents()

    compose = (
        PROJECT_ROOT
        / "docker-compose.yml"
    ).read_text(
        encoding="utf-8",
    ).lower()

    # ------------------------------------------------------
    # The user's rule, and it is the right one: do not claim
    # Grafana, Prometheus or Alertmanager is deployed if it
    # is not. Same for Redis, which is absent on purpose.
    # ------------------------------------------------------

    for component in (
        "prometheus",
        "grafana",
        "alertmanager",
        "redis",
    ):

        if component in compose:
            continue

        for name, text in documents.items():

            for line in text.splitlines():

                if component not in line.lower():
                    continue

                # Mentioning it is fine, and necessary --
                # the whole point is saying it is NOT here.
                # What must not appear is a claim that it is.
                lowered = line.lower()

                claiming = any(
                    phrase in lowered
                    for phrase in (
                        f"{component} is deployed",
                        f"{component} is running",
                        f"{component} is included",
                        f"we run {component}",
                        f"{component} ships",
                    )
                )

                assert_true(
                    not claiming,
                    (
                        f"{name} claims {component} is "
                        f"deployed, and it is not in "
                        f"docker-compose.yml:\n  {line}"
                    ),
                )

    ok(
        "no document claims prometheus, grafana, "
        "alertmanager or redis is deployed"
    )

    # ------------------------------------------------------
    # AND THE ABSENCES ARE STATED, NOT LEFT IMPLICIT
    # ------------------------------------------------------

    assert_true(
        "no monitoring stack is deployed"
        in documents["monitoring.md"].lower(),
        (
            "monitoring.md must state plainly that no "
            "monitoring stack ships with the application. "
            "An /metrics endpoint reads as observability "
            "until somebody looks for the dashboard."
        ),
    )

    assert_true(
        "no redis" in documents["deployment.md"].lower()
        or "there is no redis"
        in documents["deployment.md"].lower(),
        (
            "deployment.md must say Redis is absent and why. "
            "Its absence in a queue-based system looks like "
            "an oversight otherwise."
        ),
    )

    assert_true(
        "process-local" in documents[
            "deployment.md"
        ].lower(),
        (
            "deployment.md must describe the application's "
            "rate limiter as process-local. Presenting it as "
            "a deployment-wide limit is a false security "
            "claim: with N replicas the effective limit is N "
            "times the configured value."
        ),
    )

    assert_true(
        "no certificate is committed"
        in documents["deployment.md"].lower()
        or "no tls certificate"
        in documents["deployment.md"].lower(),
        (
            "deployment.md must say no TLS certificate "
            "ships."
        ),
    )

    ok(
        "the absences are stated explicitly: no monitoring "
        "stack, no Redis, no TLS certificate, and a rate "
        "limiter described as process-local"
    )

    # ------------------------------------------------------
    # THE LAZY-API CONSEQUENCE
    # ------------------------------------------------------
    #
    # The user was specific: do not claim readiness proves
    # OCR models are loaded when the API runs lazily.

    deployment = documents["deployment.md"].lower()

    assert_true(
        "does not mean ocr models are loaded" in deployment
        or "does not mean the ocr models are loaded"
        in deployment,
        (
            "deployment.md must state that with the API "
            "lazy, /health/ready passing does NOT mean the "
            "OCR models are loaded in that process. "
            "Readiness that seems to cover the model is "
            "exactly the assumption a lazy API breaks."
        ),
    )

    ok(
        "deployment.md states that readiness does not prove "
        "the OCR models are loaded when the API is lazy"
    )


# ==========================================================
# TEST 5b - THE RUNBOOK COVERS THE OPERATIONAL TASKS
# ==========================================================

def test_runbook_covers_the_tasks() -> None:

    section(
        "TEST 5b - THE PRODUCTION RUNBOOK COVERS EVERY "
        "OPERATIONAL TASK"
    )

    runbook = operations_documents()[
        "production-runbook.md"
    ].lower()

    # ------------------------------------------------------
    # Each of these is something somebody has to do at some
    # point, usually under pressure. A runbook missing one is
    # a runbook that gets abandoned mid-incident in favour of
    # guessing.
    # ------------------------------------------------------

    tasks = {
        "start the stack": "docker compose up",
        "stop the stack": "docker compose stop",
        "restart the api": "docker compose restart api",
        "restart the worker": (
            "docker compose restart worker"
        ),
        "run migrations": "migrate",
        "view logs": "docker compose logs",
        "health check": "/health",
        "readiness check": "/health/ready",
        "worker heartbeat": "/health/workers",
        "queue inspection": "document_jobs group by status",
        "job investigation": "safe_error_code",
        "stale worker handling": "stale",
        "provider 429 handling": "rate_limited",
        "backup": "backup.py",
        "restore": "restore.py",
        "storage problem": "reconcile_storage",
        "database problem": "too many clients",
        "rollback": "rollback",
        "deployment smoke": "validate_deployment.py",
    }

    missing = sorted(
        task
        for task, needle in tasks.items()
        if needle.lower() not in runbook
    )

    assert_equal(
        missing,
        [],
        (
            "The runbook must cover every operational task."
        ),
    )

    ok(
        f"the runbook covers all {len(tasks)} operational "
        "tasks with real commands"
    )

    # ------------------------------------------------------
    # AND IT MUST NOT GIVE DANGEROUS ADVICE
    # ------------------------------------------------------
    #
    # Two specific things, both of which destroy data and
    # both of which look like reasonable first moves.

    assert_true(
        "do not downgrade the schema reflexively" in runbook,
        (
            "The rollback section must warn against a reflex "
            "schema downgrade. Migrations here are additive, "
            "so the previous application version runs "
            "against the newer schema -- downgrading "
            "destroys the columns the newer version wrote."
        ),
    )

    assert_true(
        "only the process that did the work" in runbook,
        (
            "The stale-worker section must warn against "
            "hand-marking a PROCESSING job COMPLETED. It is "
            "permanent and indistinguishable from success."
        ),
    )

    assert_true(
        "not a smoke test" in runbook
        or "do not run the 63-document" in runbook,
        (
            "The runbook must say not to run the 63-document "
            "benchmark as a post-deploy check. It is an "
            "expensive provider window."
        ),
    )

    ok(
        "the runbook warns against the three moves that "
        "destroy data or quota: reflex schema downgrade, "
        "hand-completing an abandoned job, and re-running the "
        "benchmark as a smoke test"
    )


# ==========================================================
# TEST 6 - THE VALIDATOR PROBES, IT DOES NOT READ CONFIG
# ==========================================================

def test_validator_probes_a_running_service() -> None:

    section(
        "TEST 6 - THE VALIDATOR ASKS A RUNNING SERVICE, AND "
        "REFUSES TO GUESS"
    )

    assert_true(
        VALIDATOR.is_file(),
        (
            "scripts/verification/validate_deployment.py "
            "must exist."
        ),
    )

    source = VALIDATOR.read_text(
        encoding="utf-8",
    )

    # ------------------------------------------------------
    # IT MUST MAKE REAL REQUESTS
    # ------------------------------------------------------

    assert_true(
        "urlopen" in source,
        (
            "The validator must make real HTTP requests. A "
            "validator that reads docker-compose.yml checks "
            "the same thing the test suite already checks, "
            "and misses every case where the configuration "
            "was not applied."
        ),
    )

    # ------------------------------------------------------
    # AND IT MUST CHECK THE THINGS THAT MATTER
    # ------------------------------------------------------

    for probe, needle in (
        (
            "liveness",
            "/health",
        ),
        (
            "readiness",
            "/health/ready",
        ),
        (
            "worker health",
            "/health/workers",
        ),
        (
            "identity spoofing",
            "X-VIGILOX-REVIEWER-ID",
        ),
        (
            "metrics exposure",
            "/metrics",
        ),
        (
            "documentation exposure",
            "/openapi.json",
        ),
        (
            "security headers",
            "content-security-policy",
        ),
        (
            "the favicon",
            "/favicon.ico",
        ),
        (
            "the schema revision",
            "alembic_version",
        ),
        (
            "storage separation",
            "pending_root",
        ),
    ):

        assert_true(
            needle in source,
            (
                f"The validator must check {probe} "
                f"(looked for {needle!r})."
            ),
        )

    ok(
        "the validator probes all 10 deployment properties "
        "over HTTP or against the live database"
    )

    # ------------------------------------------------------
    # THE IDENTITY PROBE MUST NOT WRITE
    # ------------------------------------------------------
    #
    # It sends a spoofed ADMIN identity. If it also POSTed a
    # review, then a validator run against a working
    # deployment would write an audit entry -- and against a
    # BROKEN one would write a forged approval.

    assert_true(
        'method="GET"' in source,
        "The validator's requests must be GETs.",
    )

    posts = [
        line.strip()
        for line in source.splitlines()
        if '"POST"' in line
        and not line.strip().startswith(
            "#"
        )
    ]

    assert_equal(
        posts,
        [],
        (
            "The validator must not POST anything. It sends "
            "a spoofed ADMIN identity on purpose; combined "
            "with a write, a run against a broken deployment "
            "would forge an approval while checking whether "
            "it could."
        ),
    )

    ok(
        "every request the validator makes is a GET, so the "
        "spoofing probe cannot itself forge an approval"
    )

    # ------------------------------------------------------
    # A SKIP IS NOT A PASS
    # ------------------------------------------------------

    assert_true(
        "A skipped check is" in source,
        (
            "The validator must say plainly that a skipped "
            "check is not a passing one. Restricted "
            "endpoints legitimately skip when probed from "
            "outside, and a summary that reads as all-clear "
            "is how a deployment goes live unvalidated."
        ),
    )

    ok(
        "the validator states that a skipped check is not a "
        "passing one"
    )

    # ------------------------------------------------------
    # AND IT RUNS
    # ------------------------------------------------------
    #
    # Against an address nothing is listening on. The
    # assertion is that it reports the service as
    # unreachable and exits non-zero, rather than crashing
    # with a traceback -- the state it will most often be run
    # in is one where something is wrong.

    completed = subprocess.run(
        [
            sys.executable,
            str(
                VALIDATOR
            ),
            "--base-url",
            "http://127.0.0.1:1",
        ],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(
            PROJECT_ROOT
        ),
    )

    assert_equal(
        completed.returncode,
        1,
        (
            "An unreachable service must exit 1.\n"
            f"{completed.stdout[-2000:]}\n"
            f"{completed.stderr[-2000:]}"
        ),
    )

    assert_true(
        "Traceback" not in completed.stderr,
        (
            "The validator must report an unreachable "
            "service, not crash on it.\n"
            f"{completed.stderr[-2000:]}"
        ),
    )

    assert_true(
        "not answering" in completed.stdout,
        (
            "The output must say what was wrong.\n"
            f"{completed.stdout[-2000:]}"
        ),
    )

    ok(
        "run against a closed port it reports the service as "
        "not answering and exits 1, with no traceback"
    )


# ==========================================================
# MAIN
# ==========================================================

def main() -> int:

    print(
        "=" * 74
    )
    print(
        "PHASE 11.15 - DEPLOYMENT DOCUMENTATION AND RUNTIME "
        "VALIDATION"
    )
    print(
        "=" * 74
    )

    test_the_set_is_complete()
    test_named_artifacts_exist()
    test_documented_flags_exist()
    test_named_variables_are_real()
    test_quoted_numbers_are_current()
    test_no_false_claims()
    test_runbook_covers_the_tasks()
    test_validator_probes_a_running_service()

    print()
    print(
        "=" * 74
    )
    print(
        "[PASS] PHASE 11.15 DEPLOYMENT DOCUMENTATION TEST "
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
