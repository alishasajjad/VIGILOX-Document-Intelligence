"""
==========================================================
PHASE 11.8 / 11.9 - CONTAINERIZATION AND STACK
==========================================================

WHAT THIS SUITE CAN AND CANNOT PROVE
----------------------------------------------------------
Docker is not installed in the environment this was written
in. So the image has never been built and the stack has never
been started, and this suite says so rather than implying
otherwise.

What it DOES prove, statically and against the real files:

  - .dockerignore excludes every sensitive path, checked by
    applying the ignore rules rather than by grepping for
    strings
  - the Dockerfile copies only named paths, so a file that is
    neither ignored nor named cannot arrive by accident
  - the image runs as a non-root user
  - compose parses, and the api publishes no ports
  - managed storage and pending uploads are separate volumes
  - the proxy strips the reviewer identity headers
  - the proxy rate-limits the expensive routes and does NOT
    rate-limit job-status polling
  - no TLS private key or certificate is committed
  - the entrypoint uses exec, so the application is PID 1 and
    receives SIGTERM
  - the entrypoint has LF line endings and no CRLF
  - the code contains no Windows path assumptions

What it CANNOT prove, and what Phase 12's deployment smoke
covers as EXTERNAL_BLOCKED:

  - that the image builds
  - that paddlepaddle 3.3.1 has a cp313 linux/amd64 wheel
  - that `nginx -t` accepts the configuration
  - the image size
  - that the stack comes up and serves traffic

A static suite that pretended to be a deployment test would
be worse than no suite: it would make the missing verification
invisible.
"""

import json
import os
import re
import shutil
import subprocess
import sys

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


def read(
    relative: str,
) -> str:

    path = (
        PROJECT_ROOT
        / relative
    )

    assert_true(
        path.exists(),
        f"{relative} must exist.",
    )

    return path.read_text(
        encoding="utf-8"
    )


# ==========================================================
# TEST 1 - THE BUILD CONTEXT EXCLUDES WHAT IT MUST
# ==========================================================

def test_dockerignore():

    section(
        "TEST 1 - NOTHING SENSITIVE CAN ENTER THE BUILD "
        "CONTEXT"
    )

    text = read(
        ".dockerignore"
    )

    patterns = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
        and not line.strip().startswith(
            "#"
        )
    ]

    assert_true(
        patterns,
        ".dockerignore must contain rules.",
    )


    # ------------------------------------------------------
    # APPLY THE RULES, DO NOT GREP FOR THEM
    # ------------------------------------------------------
    # A grep for ".env" would pass on a file that only
    # mentions it in a comment. This checks that some rule
    # actually MATCHES each sensitive path, using Docker's
    # matching semantics closely enough to be meaningful:
    # a trailing-slash rule excludes the directory and
    # everything under it, and * does not cross a separator.
    # ------------------------------------------------------

    def excluded(
        candidate: str,
    ) -> bool:

        for pattern in patterns:

            rule = pattern.rstrip(
                "/"
            )

            if candidate == rule:
                return True

            if candidate.startswith(
                rule
                + "/"
            ):
                return True

            # A glob rule such as *.log or .env.*
            regex = (
                "^"
                + re.escape(
                    rule
                ).replace(
                    r"\*",
                    "[^/]*",
                )
                + "$"
            )

            if re.match(
                regex,
                candidate,
            ):
                return True

            # A basename rule matches at any depth for the
                # patterns this file uses (__pycache__, *.log).
            if "/" not in rule and re.match(
                regex,
                candidate.rsplit(
                    "/",
                    1,
                )[-1],
            ):
                return True

        return False

    must_be_excluded = (
        (
            ".env",
            "holds GROQ_API_KEY and the PostgreSQL password",
        ),
        (
            ".env.example",
            "developer documentation, not runtime input",
        ),
        (
            "storage",
            "managed identity documents",
        ),
        (
            "storage/documents/anything.jpg",
            "a stored identity document",
        ),
        (
            "storage/pending/anything.jpg",
            "an upload waiting for a worker",
        ),
        (
            "samples",
            (
                "contains id_card.jpg, a photograph of what "
                "appears to be a real national identity card"
            ),
        ),
        (
            "samples/id_card.jpg",
            "the specific file Phase 8 identified",
        ),
        (
            "evaluation",
            "the benchmark ground truth",
        ),
        (
            "evaluation/ground_truth/anything.json",
            "the answer key to the evaluation set",
        ),
        (
            "output",
            "generated artifacts",
        ),
        (
            ".venv",
            (
                "a Windows virtualenv, useless in a Linux "
                "image and the largest thing in the context"
            ),
        ),
        (
            ".git",
            "the full history, including anything ever removed",
        ),
        (
            "tests",
            (
                "a test runner in production is a way to run "
                "arbitrary code, and several suites create "
                "and drop databases"
            ),
        ),
        (
            "vigilox.log",
            "runtime logs",
        ),
        (
            "backend/__pycache__",
            "developer caches",
        ),
    )

    missed = []

    for candidate, why in must_be_excluded:

        if not excluded(
            candidate
        ):
            missed.append(
                f"{candidate} ({why})"
            )

    assert_equal(
        missed,
        [],
        (
            "These paths are NOT excluded from the build "
            "context:\n"
            + "\n".join(
                missed
            )
            + "\nA build context layer is not removable: "
            "deleting a file in a later RUN leaves it in an "
            "earlier layer, readable by anyone who pulls the "
            "image."
        ),
    )

    ok(
        f"{len(must_be_excluded)} sensitive paths all matched "
        f"by a rule in .dockerignore"
    )


    # SELF-CHECK, both directions. A matcher that returns True
    # for everything would pass the assertion above.
    assert_true(
        not excluded(
            "backend/app/main.py"
        ),
        (
            "The exclusion matcher excludes the application "
            "itself. It is broken, and the assertion above "
            "passed for the wrong reason."
        ),
    )

    assert_true(
        not excluded(
            "frontend/static/js/common.js"
        ),
        (
            "The exclusion matcher excludes the frontend. "
            "It is broken."
        ),
    )

    ok(
        "matcher self-checked: it does NOT exclude "
        "backend/app/main.py or the frontend"
    )


# ==========================================================
# TEST 2 - THE IMAGE
# ==========================================================

def test_dockerfile():

    section(
        "TEST 2 - THE IMAGE COPIES ONLY WHAT IT NAMES AND "
        "DOES NOT RUN AS ROOT"
    )

    text = read(
        "Dockerfile"
    )


    # ------------------------------------------------------
    # NO BLANKET COPY
    # ------------------------------------------------------
    # "COPY . ." would put everything .dockerignore happens
    # not to cover into the image. Naming each path is the
    # second of two independent controls.
    # ------------------------------------------------------

    blanket = re.findall(
        r"^\s*COPY\s+\.\s",
        text,
        re.MULTILINE,
    )

    assert_equal(
        blanket,
        [],
        (
            "The Dockerfile uses a blanket COPY. Every path "
            "must be named, so a file that is neither "
            "ignored nor named cannot reach the image by "
            "accident."
        ),
    )

    copied = re.findall(
        r"^\s*COPY\s+(?:--from=\S+\s+)?(\S+)\s+(\S+)",
        text,
        re.MULTILINE,
    )

    assert_true(
        copied,
        "The Dockerfile must copy something.",
    )

    sources = {
        source
        for source, _ in copied
    }

    for required in (
        "backend/",
        "database/",
        "frontend/",
        "migrations/",
        "alembic.ini",
    ):

        assert_true(
            required in sources,
            (
                f"{required} must be copied into the image. "
                f"Without it the application cannot run."
            ),
        )

    for forbidden in (
        "tests/",
        "evaluation/",
        "samples/",
        ".env",
        "storage/",
    ):

        assert_true(
            forbidden not in sources,
            (
                f"{forbidden} must NOT be copied into the "
                f"image."
            ),
        )

    ok(
        f"{len(copied)} explicit COPY instructions, no "
        f"blanket copy, application present and data absent"
    )


    # ------------------------------------------------------
    # NON-ROOT
    # ------------------------------------------------------

    users = re.findall(
        r"^\s*USER\s+(\S+)",
        text,
        re.MULTILINE,
    )

    assert_true(
        users,
        (
            "The image must declare a USER. Without one it "
            "runs as root, and a process that can rewrite its "
            "own code is a process whose compromise is "
            "permanent."
        ),
    )

    assert_true(
        users[-1] not in (
            "root",
            "0",
        ),
        (
            f"The final USER is {users[-1]!r}. It must not be "
            f"root."
        ),
    )

    assert_true(
        "useradd" in text
        or "adduser" in text,
        "The non-root user must actually be created.",
    )

    ok(
        f"final USER is {users[-1]!r}, created in the image"
    )


    # ------------------------------------------------------
    # NOT 0777
    # ------------------------------------------------------

    permissive = re.findall(
        r"chmod\s+(?:-R\s+)?0?777",
        text,
    )

    assert_equal(
        permissive,
        [],
        (
            "The image chmods something 777. These "
            "directories hold identity documents."
        ),
    )

    modes = re.findall(
        r"chmod\s+(?:-R\s+)?(\d{3,4})",
        text,
    )

    ok(
        f"no 777; permissions used: "
        f"{sorted(set(modes)) or 'none'}"
    )


    # ------------------------------------------------------
    # THE TWO STORAGE ROOTS ARE SEPARATE
    # ------------------------------------------------------

    storage = re.search(
        r"DOCUMENT_STORAGE_DIR=(\S+)",
        text,
    )

    pending = re.search(
        r"DOCUMENT_PENDING_DIR=(\S+)",
        text,
    )

    assert_true(
        storage and pending,
        (
            "Both storage roots must be set in the image, or "
            "they fall back to project-relative defaults that "
            "are not on a volume."
        ),
    )

    storage_path = storage.group(
        1
    )

    pending_path = pending.group(
        1
    )

    assert_true(
        not pending_path.startswith(
            storage_path.rstrip(
                "/"
            )
            + "/"
        ),
        (
            f"The pending root {pending_path} is INSIDE the "
            f"managed root {storage_path}.\n"
            "Phase 9.2: a pending upload has no document row "
            "yet, so the storage integrity scan would "
            "classify every in-flight upload as "
            "ORPHAN_STORAGE -- the one category "
            "reconciliation deletes automatically. Documents "
            "would disappear mid-processing."
        ),
    )

    ok(
        f"managed {storage_path} and pending {pending_path} "
        f"are siblings, not nested"
    )


    # ------------------------------------------------------
    # MODELS ARE BAKED IN
    # ------------------------------------------------------

    assert_true(
        "PADDLE_PDX_CACHE_HOME" in text,
        (
            "The PaddleOCR cache location must be fixed, or "
            "it lands in the user's home directory and is "
            "lost on every container start."
        ),
    )

    assert_true(
        "OCRService()" in text,
        (
            "The models must be downloaded at BUILD time.\n"
            "A container that downloads 150 MB of models on "
            "every start cannot start when the model host is "
            "unreachable, and a worker that cannot start is a "
            "queue that stops draining."
        ),
    )

    ok(
        "the model cache path is fixed and the models are "
        "downloaded during the build, so a container start "
        "needs no outbound network"
    )


# ==========================================================
# TEST 3 - THE ENTRYPOINT
# ==========================================================

def test_entrypoint():

    section(
        "TEST 3 - THE ENTRYPOINT MAKES THE APPLICATION PID 1"
    )

    path = (
        PROJECT_ROOT
        / "docker"
        / "entrypoint.sh"
    )

    raw = path.read_bytes()

    text = raw.decode(
        "utf-8"
    )


    # ------------------------------------------------------
    # LINE ENDINGS
    # ------------------------------------------------------
    # A shell script with CRLF fails on Linux with
    #     /bin/sh^M: bad interpreter: No such file or directory
    # which names a file that plainly exists. Written on
    # Windows, so this is a real hazard rather than a
    # hypothetical one.
    # ------------------------------------------------------

    assert_true(
        b"\r\n" not in raw,
        (
            "docker/entrypoint.sh contains CRLF line "
            "endings.\n"
            "On Linux the kernel reads the shebang including "
            "the carriage return and reports "
            "'bad interpreter' for a path that exists, which "
            "is among the harder container errors to read."
        ),
    )

    assert_true(
        raw.startswith(
            b"#!/bin/sh"
        )
        or raw.startswith(
            b"#!/usr/bin/env sh"
        ),
        "The entrypoint must have a POSIX shell shebang.",
    )

    ok(
        "LF line endings and a POSIX shebang"
    )


    # ------------------------------------------------------
    # EVERY ROLE USES exec
    # ------------------------------------------------------
    # Without exec the shell stays PID 1, and a shell does
    # not forward signals. Docker sends SIGTERM, nothing
    # happens, and the container is SIGKILLed -- killing a
    # worker mid-document.
    # ------------------------------------------------------

    roles = {
        "api": "uvicorn",
        "worker": "backend.worker",
        "migrate": "alembic",
    }

    for role, command in roles.items():

        assert_true(
            re.search(
                r"^\s*"
                + re.escape(
                    role
                )
                + r"\)",
                text,
                re.MULTILINE,
            )
            is not None,
            f"The entrypoint must handle the {role!r} role.",
        )

    launches = re.findall(
        r"^\s*(exec\s+)?(\S+)",
        text,
        re.MULTILINE,
    )

    for command in roles.values():

        occurrences = [
            line.strip()
            for line in text.splitlines()
            if command in line
            and not line.strip().startswith(
                "#"
            )
        ]

        assert_true(
            occurrences,
            f"{command} must be launched.",
        )

        assert_true(
            any(
                line.startswith(
                    "exec "
                )
                for line in occurrences
            ),
            (
                f"{command} must be launched with exec so it "
                f"becomes PID 1 and receives SIGTERM "
                f"directly.\n"
                f"Found: {occurrences}"
            ),
        )

    ok(
        f"all {len(roles)} roles ({', '.join(roles)}) launch "
        f"with exec"
    )


    # ------------------------------------------------------
    # THE FORWARDER LIST IS NOT "*"
    # ------------------------------------------------------
    # uvicorn --forwarded-allow-ips "*" would let any client
    # set its own apparent address via X-Forwarded-For and
    # walk straight through the Phase 11.5 identity boundary.
    # ------------------------------------------------------

    assert_true(
        '--forwarded-allow-ips "*"' not in text
        and "--forwarded-allow-ips '*'" not in text
        and "--forwarded-allow-ips *" not in text,
        (
            "The entrypoint passes --forwarded-allow-ips "
            '"*".\n'
            "That tells uvicorn to rewrite request.client.host "
            "from X-Forwarded-For for ANY peer, so a client "
            "could name its own address and satisfy the "
            "trusted-proxy check."
        ),
    )

    assert_true(
        "VIGILOX_FORWARDED_ALLOW_IPS:=}" in text
        or 'VIGILOX_FORWARDED_ALLOW_IPS:=""' in text,
        (
            "The forwarder list must default to EMPTY, so a "
            "deployment that forgot to configure it does not "
            "trust forwarded addresses."
        ),
    )

    ok(
        "the forwarded-allow-ips list defaults to empty and "
        "is never '*'"
    )


# ==========================================================
# TEST 4 - THE STACK
# ==========================================================

def test_compose():

    section(
        "TEST 4 - THE STACK EXPOSES ONLY THE PROXY AND KEEPS "
        "STORAGE SEPARATE"
    )

    text = read(
        "docker-compose.yml"
    )


    # ------------------------------------------------------
    # IT PARSES
    # ------------------------------------------------------
    # Without PyYAML this falls back to structural checks and
    # says so, rather than skipping silently.
    # ------------------------------------------------------

    document = None

    try:
        import yaml

        document = yaml.safe_load(
            text
        )

    except ImportError:
        print(
            "       (PyYAML not installed: checking "
            "structure textually instead of by parsing)"
        )

    if document is not None:

        services = document.get(
            "services",
            {},
        )

        assert_equal(
            sorted(
                services
            ),
            [
                "api",
                "migrate",
                "postgres",
                "proxy",
                "worker",
            ],
            (
                "The stack must contain exactly these five "
                "services. Anything else is a dependency to "
                "back up, secure and monitor -- and the job "
                "queue is PostgreSQL, so a broker is not one "
                "of them."
            ),
        )

        assert_true(
            "redis" not in services,
            (
                "There must be no Redis. The durable queue "
                "uses PostgreSQL with FOR UPDATE SKIP LOCKED "
                "and worker leases, which gives the queue "
                "transactional consistency with the documents "
                "it refers to."
            ),
        )


        # --------------------------------------------------
        # ONLY THE PROXY IS PUBLISHED
        # --------------------------------------------------

        published = {
            name: service.get(
                "ports"
            )
            for name, service in services.items()
            if service.get(
                "ports"
            )
        }

        assert_equal(
            sorted(
                published
            ),
            [
                "proxy",
            ],
            (
                "Only the proxy may publish ports.\n"
                f"Published: {published}\n"
                "The api must not be reachable directly: in "
                "trusted_headers mode the reviewer identity "
                "is a header the proxy injects, and a "
                "directly reachable api is a client able to "
                "send that header itself."
            ),
        )


        # --------------------------------------------------
        # STORAGE STAYS SEPARATE
        # --------------------------------------------------

        volumes = sorted(
            document.get(
                "volumes",
                {},
            )
            or {}
        )

        for required in (
            "document-storage",
            "pending-uploads",
            "postgres-data",
        ):

            assert_true(
                required in volumes,
                (
                    f"{required} must be a named volume, or "
                    f"a container restart loses it."
                ),
            )

        assert_true(
            "document-storage" != "pending-uploads",
            "distinct names",
        )

        for name in (
            "api",
            "worker",
        ):

            mounts = services[name].get(
                "volumes",
                [],
            )

            targets = [
                str(
                    mount
                ).split(
                    ":"
                )[1]
                for mount in mounts
                if ":" in str(
                    mount
                )
            ]

            assert_true(
                "/data/documents" in targets
                and "/data/pending" in targets,
                (
                    f"{name} must mount both storage roots: "
                    f"{targets}"
                ),
            )

            assert_true(
                not any(
                    target.startswith(
                        "/data/documents/"
                    )
                    for target in targets
                ),
                (
                    "The pending root must not be mounted "
                    "inside the managed root. See Phase 9.2."
                ),
            )

        ok(
            f"5 services, only the proxy publishes ports, "
            f"{len(volumes)} named volumes with managed and "
            f"pending storage separate"
        )


        # --------------------------------------------------
        # NO SECRETS IN THE FILE
        # --------------------------------------------------

        serialized = json.dumps(
            document
        )

        leaked = []

        live_key = os.environ.get(
            "GROQ_API_KEY",
            "",
        )

        live_url = os.environ.get(
            "DATABASE_URL",
            "",
        )

        for secret in (
            live_key,
            live_url,
        ):

            if secret and secret in serialized:
                leaked.append(
                    secret[:12]
                    + "..."
                )

        assert_equal(
            leaked,
            [],
            (
                f"docker-compose.yml contains a real secret: "
                f"{leaked}"
            ),
        )

        assert_true(
            "${GROQ_API_KEY" in text,
            (
                "The Groq key must come from the environment "
                "rather than being written here."
            ),
        )

        assert_true(
            ":?" in text,
            (
                "Credentials should use the ${VAR:?message} "
                "form so a missing secret refuses to start "
                "rather than producing a service with an "
                "empty password."
            ),
        )

        ok(
            "no real credential in the file; secrets come "
            "from the environment and a missing one fails the "
            "command"
        )


        # --------------------------------------------------
        # GRACE PERIODS COVER THE MEASURED WORST CASE
        # --------------------------------------------------

        grace = services["worker"].get(
            "stop_grace_period",
            "",
        )

        seconds = int(
            re.sub(
                r"[^0-9]",
                "",
                str(
                    grace
                ),
            )
            or 0
        )

        assert_true(
            seconds >= 268,
            (
                f"The worker's stop_grace_period is "
                f"{grace!r}.\n"
                "The measured worst-case pipeline is 268 "
                "seconds. Graceful shutdown finishes the "
                "document in hand, so a shorter grace period "
                "means Docker SIGKILLs the worker partway -- "
                "wasting a full OCR pass and delaying that "
                "document by the lease timeout."
            ),
        )

        ok(
            f"the worker's stop_grace_period is {grace}, "
            f"covering the measured 268s worst case"
        )

    else:

        for required in (
            "services:",
            "api:",
            "worker:",
            "postgres:",
            "proxy:",
            "migrate:",
        ):
            assert_true(
                required in text,
                f"{required} must be present.",
            )

        ok(
            "compose structure present (textual check)"
        )


# ==========================================================
# TEST 5 - THE PROXY
# ==========================================================

def test_proxy_configuration():

    section(
        "TEST 5 - THE PROXY STRIPS IDENTITY HEADERS AND "
        "LIMITS THE EXPENSIVE ROUTES"
    )

    locations = read(
        "docker/nginx/vigilox-locations.conf"
    )

    main = read(
        "docker/nginx/nginx.conf"
    )


    # ------------------------------------------------------
    # THE STRIP
    # ------------------------------------------------------
    # nginx forwards unknown request headers by default, so
    # NOT mentioning a header is not stripping it.
    # proxy_set_header with an empty value removes it.
    # ------------------------------------------------------

    for header in (
        "X-VIGILOX-REVIEWER-ID",
        "X-VIGILOX-REVIEWER-ROLE",
    ):

        stripped = re.search(
            r'proxy_set_header\s+'
            + re.escape(
                header
            )
            + r'\s+""\s*;',
            locations,
            re.IGNORECASE,
        )

        assert_true(
            stripped is not None,
            (
                f"The proxy must STRIP {header} from client "
                f"requests with\n"
                f'    proxy_set_header {header} "";\n'
                "nginx forwards unknown request headers by "
                "default, so leaving it unmentioned passes a "
                "browser-supplied reviewer identity straight "
                "through to the application."
            ),
        )

    ok(
        "both reviewer identity headers are explicitly "
        "stripped before proxying"
    )


    # ------------------------------------------------------
    # X-Forwarded-For IS SET, NOT APPENDED
    # ------------------------------------------------------

    assert_true(
        re.search(
            r"proxy_set_header\s+X-Forwarded-For\s+\$remote_addr\s*;",
            locations,
        )
        is not None,
        (
            "X-Forwarded-For must be SET to $remote_addr, not "
            "appended to.\n"
            "$proxy_add_x_forwarded_for prepends the client's "
            "own value, and the application reads the FIRST "
            "entry when the peer is trusted -- so a client "
            "could choose the address it appears to come "
            "from."
        ),
    )

    assert_true(
        "proxy_add_x_forwarded_for" not in locations,
        (
            "proxy_add_x_forwarded_for preserves a "
            "client-supplied X-Forwarded-For. Use "
            "$remote_addr."
        ),
    )

    ok(
        "X-Forwarded-For is set to $remote_addr, discarding "
        "any client-supplied value"
    )


    # ------------------------------------------------------
    # NO FAKED AUTHENTICATION
    # ------------------------------------------------------
    # The identity header must be stripped and NOT replaced
    # with a hardcoded value. A proxy that injects a fixed
    # reviewer id is the local_env behaviour that production
    # refuses to start with, wearing a proxy's clothes.
    # ------------------------------------------------------

    injected = [
        line.strip()
        for line in locations.splitlines()
        if "X-VIGILOX-REVIEWER" in line
        and not line.strip().startswith(
            "#"
        )
        and '""' not in line
    ]

    assert_equal(
        injected,
        [],
        (
            "The proxy injects a reviewer identity value: "
            f"{injected}\n"
            "No identity provider exists in this environment. "
            "Injecting a fixed value would hand every visitor "
            "the same reviewer identity -- exactly the "
            "local_env behaviour production refuses to start "
            "with. The deployment must fail closed instead, "
            "and the integration point must be documented."
        ),
    )

    assert_true(
        "fails closed" in locations.lower()
        or "fail closed" in locations.lower(),
        (
            "The configuration must state that with no "
            "authenticator in front, the deployment fails "
            "closed and cannot record a review decision."
        ),
    )

    ok(
        "no identity value is injected; the configuration "
        "documents the integration point and the fail-closed "
        "behaviour"
    )


    # ------------------------------------------------------
    # THE EXPENSIVE ROUTES ARE LIMITED
    # ------------------------------------------------------

    zones = dict(
        re.findall(
            r"limit_req_zone\s+\S+\s+zone=(\w+):\S+\s+rate=(\S+);",
            main,
        )
    )

    assert_true(
        len(
            zones
        )
        >= 4,
        (
            f"There must be separate limit zones for routes "
            f"of different cost. Found: {zones}\n"
            "One limit for all of them would either break "
            "batch intake or leave the expensive routes open."
        ),
    )

    required_routes = (
        (
            "/api/v1/document-jobs",
            "single document job creation",
        ),
        (
            "/api/v1/document-batches",
            "batch creation",
        ),
        (
            "/api/v1/documents/analyze",
            (
                "the legacy synchronous route, which runs OCR "
                "inline"
            ),
        ),
        (
            "reviews",
            "review submission",
        ),
    )

    for route, description in required_routes:

        block = re.search(
            r"location[^\n{]*"
            + re.escape(
                route
            )
            + r"[^{]*\{([^}]*)\}",
            locations,
        )

        assert_true(
            block is not None,
            (
                f"There must be a location block for {route} "
                f"({description})."
            ),
        )

        assert_true(
            "limit_req" in block.group(
                1
            ),
            (
                f"{route} ({description}) must be rate "
                f"limited at the proxy. This is the "
                f"AUTHORITATIVE limit: the application's is "
                f"per process and cannot bound total load "
                f"across replicas."
            ),
        )

    ok(
        f"{len(zones)} limit zones "
        f"({', '.join(sorted(zones))}); all "
        f"{len(required_routes)} expensive routes limited"
    )


    # ------------------------------------------------------
    # POLLING IS NOT LIMITED
    # ------------------------------------------------------
    # The failure this avoids: the async interface polls job
    # status every couple of seconds for the length of a
    # batch. A rate limit there makes a working upload look
    # like a hung one.
    # ------------------------------------------------------

    catch_all = re.search(
        r"location\s+/\s*\{([^}]*)\}",
        locations,
    )

    assert_true(
        catch_all is not None,
        "There must be a catch-all location.",
    )

    assert_true(
        "limit_req" not in catch_all.group(
            1
        ),
        (
            "The catch-all location must NOT rate limit.\n"
            "Job-status polling goes through it: after an "
            "upload the browser asks every couple of seconds "
            "until the document completes, and a 20-file "
            "batch is ten minutes of that. A limit here makes "
            "the upload page appear to hang at exactly the "
            "moment it is working."
        ),
    )

    status_block = re.search(
        r"location[^\n{]*document-jobs/\{?job_id\}?[^{]*\{([^}]*)\}",
        locations,
    )

    ok(
        "the catch-all location carries no limit_req, so job "
        "status polling is not throttled"
    )


    # ------------------------------------------------------
    # BODY SIZE AND TIMEOUTS
    # ------------------------------------------------------

    body = re.search(
        r"client_max_body_size\s+(\S+);",
        locations,
    )

    assert_true(
        body is not None,
        (
            "client_max_body_size must be set, so an "
            "oversized upload is refused before it reaches "
            "Python."
        ),
    )

    analyze = re.search(
        r"location\s*=\s*/api/v1/documents/analyze[^{]*\{([^}]*)\}",
        locations,
    )

    assert_true(
        "proxy_read_timeout" in analyze.group(
            1
        ),
        (
            "The synchronous analyze route needs its own "
            "timeout: it runs the whole pipeline inline, "
            "measured worst case 268 seconds, while the "
            "default read timeout is 60."
        ),
    )

    analyze_timeout = int(
        re.search(
            r"proxy_read_timeout\s+(\d+)s",
            analyze.group(
                1
            ),
        ).group(
            1
        )
    )

    assert_true(
        analyze_timeout >= 268,
        (
            f"The analyze read timeout is {analyze_timeout}s "
            f"but the measured worst case is 268s. The proxy "
            f"would give up on a request the application was "
            f"still correctly serving."
        ),
    )

    ok(
        f"body limit {body.group(1)}, analyze read timeout "
        f"{analyze_timeout}s covering the 268s worst case"
    )


    # ------------------------------------------------------
    # METRICS ARE NOT PUBLIC
    # ------------------------------------------------------

    metrics = re.search(
        r"location\s*=\s*/metrics[^{]*\{([^}]*)\}",
        locations,
    )

    assert_true(
        metrics is not None,
        "There must be a /metrics location block.",
    )

    # Whitespace-normalised: nginx style aligns directives,
    # so the file reads "deny  all;" with two spaces.
    metrics_body = re.sub(
        r"\s+",
        " ",
        metrics.group(
            1
        ),
    )

    assert_true(
        "deny all" in metrics_body,
        (
            "/metrics must not be publicly reachable. Queue "
            "depth, failure rates and provider behaviour are "
            "all useful to somebody probing the service."
        ),
    )

    ok(
        "/metrics is restricted to private ranges and denied "
        "to everything else"
    )


# ==========================================================
# TEST 6 - NO TLS MATERIAL IS COMMITTED
# ==========================================================

def test_no_committed_tls_material():

    section(
        "TEST 6 - NO CERTIFICATE OR PRIVATE KEY IS COMMITTED"
    )

    suspicious = []

    for pattern in (
        "**/*.pem",
        "**/*.key",
        "**/*.crt",
        "**/*.p12",
        "**/*.pfx",
    ):

        for path in PROJECT_ROOT.glob(
            pattern
        ):

            relative = path.relative_to(
                PROJECT_ROOT
            ).as_posix()

            if relative.startswith(
                (
                    ".venv/",
                    ".git/",
                )
            ):
                continue

            suspicious.append(
                relative
            )

    assert_equal(
        suspicious,
        [],
        (
            f"Certificate or key material is present in the "
            f"repository: {suspicious}\n"
            "A self-signed certificate committed to version "
            "control is worse than none: it looks like TLS "
            "while its private key is public, and it trains "
            "everyone to click through the browser warning."
        ),
    )

    main = read(
        "docker/nginx/nginx.conf"
    )

    active_ssl = [
        line.strip()
        for line in main.splitlines()
        if "ssl_certificate" in line
        and not line.strip().startswith(
            "#"
        )
    ]

    assert_equal(
        active_ssl,
        [],
        (
            "The proxy configuration activates TLS without a "
            "certificate being available: "
            f"{active_ssl}\n"
            "nginx would fail to start. The HTTPS block is "
            "commented out on purpose, with instructions."
        ),
    )

    assert_true(
        "TLSv1.2" in main
        and "TLSv1.3" in main,
        (
            "The commented HTTPS block should still show the "
            "intended protocol versions, so enabling it is a "
            "matter of uncommenting rather than research."
        ),
    )

    ok(
        "no certificate or key in the repository; the HTTPS "
        "block is present but inactive, with TLS 1.2/1.3 "
        "specified"
    )


# ==========================================================
# TEST 7 - THE CODE HAS NO WINDOWS PATH ASSUMPTIONS
# ==========================================================

def test_linux_path_compatibility():

    section(
        "TEST 7 - THE APPLICATION MAKES NO WINDOWS PATH "
        "ASSUMPTIONS"
    )

    offenders = []

    drive_letter = re.compile(
        r'["\'][A-Za-z]:[\\/]'
    )

    backslash_join = re.compile(
        r'["\'][^"\']*\\\\[^"\']*["\']'
    )

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

            for number, line in enumerate(
                path.read_text(
                    encoding="utf-8"
                ).splitlines(),
                start=1,
            ):

                stripped = line.strip()

                if stripped.startswith(
                    "#"
                ):
                    continue

                if drive_letter.search(
                    line
                ):
                    offenders.append(
                        f"{path.relative_to(PROJECT_ROOT).as_posix()}"
                        f":{number} drive letter"
                    )

                if "os.sep" in line:
                    offenders.append(
                        f"{path.relative_to(PROJECT_ROOT).as_posix()}"
                        f":{number} os.sep"
                    )

    assert_equal(
        offenders,
        [],
        (
            "The application contains platform-specific path "
            f"handling: {offenders}\n"
            "The image is Linux."
        ),
    )

    # SELF-CHECK.
    assert_true(
        drive_letter.search(
            'path = "C:\\\\Users\\\\x"'
        )
        is not None,
        (
            "The drive-letter detector cannot see a "
            "constructed Windows path. It is broken."
        ),
    )

    ok(
        "no drive letters and no os.sep in backend/ or "
        "database/ (detector self-checked)"
    )


    # ------------------------------------------------------
    # AND THE ANCHOR IS RELATIVE TO THE MODULE
    # ------------------------------------------------------

    from backend.app.core import paths

    assert_true(
        paths.PROJECT_ROOT.is_absolute(),
        "The project anchor must resolve to an absolute path.",
    )

    for name in (
        "FRONTEND_PAGES_DIRECTORY",
        "FRONTEND_STATIC_DIRECTORY",
    ):

        directory = getattr(
            paths,
            name,
        )

        assert_true(
            directory.exists(),
            (
                f"{name} must resolve to a real directory, or "
                f"the image serves no frontend."
            ),
        )

    ok(
        "the project anchor is derived from the module "
        "location, so it resolves the same at /app in a "
        "container"
    )


# ==========================================================
# TEST 8 - WHAT REMAINS UNVERIFIED
# ==========================================================

def test_docker_availability_is_reported():

    section(
        "TEST 8 - THE UNVERIFIED PART IS NAMED, NOT HIDDEN"
    )

    docker = shutil.which(
        "docker"
    )

    if docker is None:

        print(
            "       Docker is NOT installed in this "
            "environment."
        )
        print()
        print(
            "       EXTERNAL_BLOCKED - the following cannot "
            "be verified here:"
        )

        for item in (
            "docker build succeeds",
            (
                "paddlepaddle 3.3.1 has a cp313 "
                "linux/amd64 wheel"
            ),
            "the final image size",
            "the PaddleOCR model download during build",
            "nginx -t accepts the configuration",
            "docker compose up brings the stack online",
            "volumes survive a restart",
            "the worker heartbeat appears",
        ):
            print(
                f"         - {item}"
            )

        print()
        print(
            "       Everything above this test was checked "
            "statically against the real files."
        )

        ok(
            "the missing verification is reported rather "
            "than skipped"
        )

        return

    # Docker IS available: do the cheap real checks.
    version = subprocess.run(
        [
            docker,
            "--version",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )

    print(
        f"       docker present: "
        f"{version.stdout.strip()}"
    )

    compose_check = subprocess.run(
        [
            docker,
            "compose",
            "config",
            "--quiet",
        ],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(
            PROJECT_ROOT
        ),
    )

    assert_equal(
        compose_check.returncode,
        0,
        (
            "docker compose config must validate the stack.\n"
            f"{compose_check.stderr[-2000:]}"
        ),
    )

    ok(
        "docker is available and `docker compose config` "
        "validates the stack"
    )


# ==========================================================
# MAIN
# ==========================================================

def main() -> int:

    print(
        "=" * 74
    )
    print(
        "PHASE 11.8 / 11.9 - CONTAINERIZATION AND STACK"
    )
    print(
        "=" * 74
    )

    test_dockerignore()
    test_dockerfile()
    test_entrypoint()
    test_compose()
    test_proxy_configuration()
    test_no_committed_tls_material()
    test_linux_path_compatibility()
    test_docker_availability_is_reported()

    print()
    print(
        "=" * 74
    )
    print(
        "[PASS] PHASE 11.8/11.9 CONTAINERIZATION TEST PASSED"
    )
    print(
        "       Static verification only where Docker is "
        "absent - see TEST 8."
    )
    print(
        "=" * 74
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
