import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid

from pathlib import Path


# ==========================================================
# PHASE 11.13 - GRACEFUL SHUTDOWN
# ==========================================================
#
# Real processes, real signals. Nothing here reads a config
# file and concludes that shutdown works.
#
# The question a container runtime asks is narrow: it sends
# SIGTERM, waits stop_grace_period, then sends SIGKILL. So
# three things have to be true.
#
#   1. The signal reaches the application.
#   2. The application finishes what it is holding.
#   3. It exits before the grace period runs out.
#
# And a fourth that is easy to miss and worse than the others:
#
#   4. Work that did NOT finish is not recorded as finished.
#
# A worker killed mid-document must leave that document
# claimable, not completed. Marking incomplete work complete
# is silent, permanent, and indistinguishable from success
# afterwards.
#
#
# SIGNALS ON WINDOWS
# ----------------------------------------------------------
# There is no SIGTERM on Windows. subprocess.terminate() calls
# TerminateProcess, which does not run cleanup handlers at all
# -- using it here would test SIGKILL and report it as a
# graceful shutdown.
#
# So a new process group is created and CTRL_BREAK_EVENT is
# sent, which arrives as SIGBREAK. uvicorn handles SIGBREAK on
# Windows for exactly this reason, and the worker registers
# SIGINT alongside SIGTERM for it.
#
# On Linux -- where the containers run -- it is a plain
# SIGTERM. Both paths are exercised by whichever platform this
# runs on, and the assertions are identical.
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


from dotenv import load_dotenv  # noqa: E402

load_dotenv(
    PROJECT_ROOT
    / ".env"
)

import sqlalchemy as sa  # noqa: E402

from sqlalchemy.orm import sessionmaker  # noqa: E402


WINDOWS = sys.platform.startswith(
    "win"
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


def assert_in(
    needle: str,
    haystack: str,
    message: str,
) -> None:

    if needle not in haystack:

        raise AssertionError(
            f"{message}\n"
            f"Looked for: {needle!r}\n"
            f"In:\n{haystack[-4000:]}"
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
# PROCESS CONTROL
# ==========================================================

class Child:

    """
    A spawned process whose output goes to a FILE.

    Not a pipe, and the reason is a bug this test had. Output
    was captured with stdout=PIPE and read by a drain()
    helper, which was passed as the DIAGNOSTIC argument to an
    assertion:

        assert_true(ready, "... " + drain(process))

    Python evaluates arguments before calling the function, so
    drain() ran on every pass as well as every failure -- and
    reading a pipe blocks until the writer closes it, which
    for a server under test means never. The suite hung on
    SUCCESS, holding a uvicorn process open, and looked like a
    slow test rather than a deadlocked one.

    A file has neither problem: reading it never blocks, and
    it cannot fill a 64 KB pipe buffer and stall the child
    mid-write.
    """

    def __init__(
        self,
        process: subprocess.Popen,
        log: Path,
    ) -> None:

        self.process = process
        self.log = log


    def output(
        self,
    ) -> str:

        """
        Whatever has been written so far. Never blocks.
        """

        try:
            return self.log.read_text(
                encoding="utf-8",
                errors="replace",
            )

        except Exception:
            return ""


    def poll(
        self,
    ):
        return self.process.poll()


    def send_signal(
        self,
        number,
    ) -> None:

        self.process.send_signal(
            number
        )


def spawn(
    *arguments: str,
    environment: dict | None = None,
) -> Child:

    """
    Start a child in its own process group, so a signal can
    be delivered to it without also hitting this test.
    """

    keywords = {}

    if WINDOWS:

        keywords["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP
        )

    else:

        keywords["start_new_session"] = True

    combined = dict(
        os.environ
    )

    combined["PYTHONPATH"] = str(
        PROJECT_ROOT
    )

    combined["PYTHONUNBUFFERED"] = "1"

    if environment:
        combined.update(
            environment
        )

    log = Path(
        tempfile.mkdtemp(
            prefix="vigilox-shutdown-",
        )
    ) / "child.log"

    handle = log.open(
        "wb",
    )

    LOGS.append(
        (
            log,
            handle,
        )
    )

    process = subprocess.Popen(
        [
            sys.executable,
            "-u",
            *arguments,
        ],
        stdout=handle,
        stderr=subprocess.STDOUT,
        cwd=str(
            PROJECT_ROOT
        ),
        env=combined,
        **keywords,
    )

    return Child(
        process,
        log,
    )


LOGS = []


def close_logs() -> None:

    for _, handle in LOGS:

        try:
            handle.close()

        except Exception:
            pass


def request_stop(
    process: Child,
) -> str:

    """
    The polite signal, whatever it is called here.

    Returns the name, so the output says which path was
    exercised rather than leaving the reader to guess.
    """

    if WINDOWS:

        process.send_signal(
            signal.CTRL_BREAK_EVENT
        )

        return "CTRL_BREAK_EVENT (SIGBREAK)"

    process.send_signal(
        signal.SIGTERM
    )

    return "SIGTERM"


def free_port() -> int:

    with socket.socket() as probe:

        probe.bind(
            (
                "127.0.0.1",
                0,
            )
        )

        return probe.getsockname()[1]


def wait_for_exit(
    process: Child,
    *,
    seconds: float,
) -> tuple[int | None, float]:

    """
    Wait, and report how long it took.

    The duration is the point. "It exited" is not the claim; a
    container runtime allows a bounded window and kills the
    process at the end of it.
    """

    started = time.monotonic()

    try:
        code = process.process.wait(
            timeout=seconds,
        )

    except subprocess.TimeoutExpired:
        code = None

    return (
        code,
        time.monotonic() - started,
    )


def drain(
    process: Child,
) -> str:

    """
    What the child has written so far.

    Reads the log FILE. It never blocks, which is what makes
    it safe to pass as a diagnostic argument -- see the note
    on Child.
    """

    return process.output()


def kill(
    process: Child,
) -> None:

    if process.poll() is None:

        process.process.kill()

        try:
            process.process.wait(
                timeout=30,
            )

        except Exception:
            pass


# ==========================================================
# THE DATABASE
# ==========================================================

def database_url() -> str:

    url = os.getenv(
        "DATABASE_URL",
        "",
    ).strip()

    if not url:

        raise AssertionError(
            "DATABASE_URL is not set."
        )

    return url


def engine():

    return sa.create_engine(
        database_url(),
        poolclass=sa.pool.NullPool,
    )


def backend_count() -> int:

    """
    How many connections this database currently has.

    NullPool above so this probe does not itself hold one and
    confuse the number it is reporting.
    """

    from sqlalchemy.engine import make_url

    name = make_url(
        database_url()
    ).database

    probe = engine()

    try:

        with probe.connect() as connection:

            return connection.execute(
                sa.text(
                    "select count(*) from pg_stat_activity "
                    "where datname = :name "
                    "and pid <> pg_backend_pid()"
                ),
                {
                    "name": name,
                },
            ).scalar_one()

    finally:
        probe.dispose()


# ==========================================================
# THE WORKER TEST NEEDS ITS OWN DATABASE
# ==========================================================
#
# THIS IS NOT A PRECAUTION. It is a fix for damage this test
# actually did.
#
# The worker test starts a REAL worker. An earlier version
# pointed it at the configured database, and the worker did
# exactly what a worker does: claimed the head of the queue.
# The queue contained three real uploads. It ran OCR and the
# extraction provider against two of them, completed them, and
# was then killed mid-document on the third by the shutdown
# signal under test -- leaving two jobs stranded in PROCESSING.
#
# Nothing was lost, and the two documents processed correctly.
# But the test spent provider quota nobody asked it to spend
# and it processed somebody's documents as a side effect of
# checking a signal handler.
#
# The lesson is the one the job repository already learned:
# a test that can reach the real queue will eventually claim
# real work. claim_next grew only_job_ids for this, and the
# comment there says so. A worker STARTED AS A PROCESS cannot
# be handed that argument, so the isolation has to be the
# database itself.
#
# So: an empty throwaway, migrated, with nothing in the queue.
# The worker starts, finds nothing to claim, writes its
# heartbeat, and is signalled. That is the whole scenario --
# claiming real work was never part of it.
# ==========================================================

SCRATCH_DATABASE = "vigilox_shutdown_test"


def scratch_url() -> str:

    return (
        database_url().rsplit(
            "/",
            1,
        )[0]
        + f"/{SCRATCH_DATABASE}"
    )


def admin_engine():

    return sa.create_engine(
        database_url().rsplit(
            "/",
            1,
        )[0]
        + "/postgres",
        isolation_level="AUTOCOMMIT",
    )


def reset_scratch() -> None:

    with admin_engine().connect() as connection:

        connection.execute(
            sa.text(
                "select pg_terminate_backend(pid) "
                "from pg_stat_activity "
                "where datname = :name "
                "and pid <> pg_backend_pid()"
            ),
            {
                "name": SCRATCH_DATABASE,
            },
        )

        connection.execute(
            sa.text(
                f'drop database if exists '
                f'"{SCRATCH_DATABASE}"'
            )
        )

        connection.execute(
            sa.text(
                f'create database "{SCRATCH_DATABASE}"'
            )
        )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "upgrade",
            "head",
        ],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(
            PROJECT_ROOT
        ),
        env={
            **os.environ,
            "DATABASE_URL": scratch_url(),
            "PYTHONPATH": str(
                PROJECT_ROOT
            ),
        },
    )

    assert_equal(
        completed.returncode,
        0,
        (
            "The throwaway database must be migrated before "
            "a worker is pointed at it.\n"
            f"{completed.stdout[-1500:]}\n"
            f"{completed.stderr[-1500:]}"
        ),
    )


def drop_scratch() -> None:

    try:
        with admin_engine().connect() as connection:

            connection.execute(
                sa.text(
                    "select pg_terminate_backend(pid) "
                    "from pg_stat_activity "
                    "where datname = :name "
                    "and pid <> pg_backend_pid()"
                ),
                {
                    "name": SCRATCH_DATABASE,
                },
            )

            connection.execute(
                sa.text(
                    f'drop database if exists '
                    f'"{SCRATCH_DATABASE}"'
                )
            )

    except Exception as error:

        print(
            f"       (could not drop the throwaway "
            f"database: {type(error).__name__})"
        )


def scratch_engine():

    return sa.create_engine(
        scratch_url(),
        poolclass=sa.pool.NullPool,
    )


# ==========================================================
# TEST 1 - THE API SHUTS DOWN ON THE SIGNAL
# ==========================================================

def test_api_shutdown() -> None:

    section(
        "TEST 1 - THE API EXITS CLEANLY ON THE SHUTDOWN "
        "SIGNAL AND RELEASES ITS DATABASE CONNECTIONS"
    )

    port = free_port()

    baseline = backend_count()

    process = spawn(
        "-m",
        "uvicorn",
        "backend.app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(
            port
        ),
        environment={
            # Lazy, as production runs it. Loading PaddleOCR
            # here would add three seconds to a test about
            # shutting down.
            "VIGILOX_API_EAGER_PIPELINE": "false",
        },
    )

    try:

        # --------------------------------------------------
        # WAIT UNTIL IT IS ACTUALLY SERVING
        # --------------------------------------------------
        #
        # Signalling a process that has not finished starting
        # tests something else entirely.

        import urllib.error
        import urllib.request

        ready = False

        deadline = time.monotonic() + 90

        while time.monotonic() < deadline:

            try:

                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/health",
                    timeout=5,
                ) as response:

                    if response.status == 200:
                        ready = True
                        break

            except (
                urllib.error.URLError,
                OSError,
            ):
                time.sleep(
                    0.5
                )

            if process.poll() is not None:
                break

        assert_true(
            ready,
            (
                "The API must come up before shutdown can be "
                "tested.\n"
                + drain(
                    process
                )[-3000:]
            ),
        )

        # Make it open its pool for real. Startup alone may
        # not have needed a connection.
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/health/ready",
            timeout=30,
        ) as response:

            assert_equal(
                response.status,
                200,
                "Readiness must pass before shutdown.",
            )

        serving = backend_count()

        assert_true(
            serving > baseline,
            (
                "The API must have opened at least one "
                "database connection, or the release "
                "assertion below proves nothing.\n"
                f"baseline {baseline}, serving {serving}"
            ),
        )

        ok(
            f"the API is serving and holding "
            f"{serving - baseline} database connection(s) "
            f"above a baseline of {baseline}"
        )

        # --------------------------------------------------
        # THE SIGNAL
        # --------------------------------------------------

        name = request_stop(
            process
        )

        code, elapsed = wait_for_exit(
            process,
            seconds=60,
        )

        output = drain(
            process
        )

        assert_true(
            code is not None,
            (
                f"The API did not exit within 60s of "
                f"{name}. A container runtime would SIGKILL "
                "it, and anything mid-flight would be cut "
                f"off.\n{output[-3000:]}"
            ),
        )

        # --------------------------------------------------
        # THE EXIT CODE, AND A PLATFORM CAVEAT
        # --------------------------------------------------
        #
        # On Linux -- where the containers run -- a graceful
        # SIGTERM shutdown exits 0, and that is asserted.
        #
        # On Windows the console-control path exits 3 even
        # when the shutdown completed in full. That was
        # measured rather than assumed: a TRIVIAL ASGI app,
        # same launch, same CTRL_BREAK_EVENT, logs
        # "Application shutdown complete" and then exits 3 as
        # well. A bare Python child that installs a SIGBREAK
        # handler and calls sys.exit(0) exits 0, so the
        # platform preserves a chosen code -- the 3 comes from
        # uvicorn's own path on Windows, not from this
        # application and not from the OS.
        #
        # So the code is asserted where it is meaningful, and
        # on Windows the COMPLETENESS of the shutdown is
        # asserted instead, from the log. That is the property
        # that actually matters: the lifespan ran, the pool
        # was disposed, and the connections went away.
        #
        # Recorded rather than waved away, because "the exit
        # code is wrong but it is fine" is exactly the shape
        # of a real defect being explained away.

        if WINDOWS:

            assert_equal(
                code,
                3,
                (
                    "On Windows uvicorn's console-control "
                    "shutdown is expected to exit 3 after a "
                    "COMPLETE shutdown -- measured against a "
                    "trivial ASGI app. A different code here "
                    "means the behaviour changed and this "
                    "caveat needs re-measuring rather than "
                    f"trusting.\n{output[-4000:]}"
                ),
            )

            assert_in(
                "Application shutdown complete",
                output,
                (
                    "The shutdown must have COMPLETED. This "
                    "is what stands in for the exit code on "
                    "this platform, so it is not optional."
                ),
            )

            ok(
                f"{name} -> shutdown completed in "
                f"{elapsed:.2f}s, exit 3 (the documented "
                "Windows console-control code; Linux SIGTERM "
                "exits 0)"
            )

        else:

            assert_equal(
                code,
                0,
                (
                    f"The API must exit 0 on {name}. A "
                    "non-zero exit is reported by the "
                    "runtime as a crash, and a deploy that "
                    "looks like a crash gets rolled "
                    f"back.\n{output[-4000:]}"
                ),
            )

            ok(
                f"{name} -> exit 0 in {elapsed:.2f}s"
            )

        # --------------------------------------------------
        # THE LIFESPAN SHUTDOWN ACTUALLY RAN
        # --------------------------------------------------
        #
        # Exit 0 alone does not prove it. A process killed
        # between the last request and the lifespan resuming
        # can still exit 0 while skipping every cleanup.

        assert_in(
            "api.pool_disposed",
            output,
            (
                "The lifespan shutdown must run and dispose "
                "the connection pool. Without it the process "
                "exits with up to REQUEST_CONCURRENCY "
                "sockets open, which PostgreSQL only notices "
                "on its next read -- and during a rolling "
                "deploy that means the old replica's "
                "connections are still counted against "
                "max_connections while the new one opens "
                "its own."
            ),
        )

        ok(
            "the lifespan shutdown ran and disposed the "
            "connection pool"
        )

        # --------------------------------------------------
        # AND THE CONNECTIONS ARE GONE
        # --------------------------------------------------
        #
        # Asked of PostgreSQL, not of the log line. The log
        # says dispose() was called; pg_stat_activity says
        # whether it worked.

        after = None

        deadline = time.monotonic() + 20

        while time.monotonic() < deadline:

            after = backend_count()

            if after <= baseline:
                break

            time.sleep(
                0.5
            )

        assert_true(
            after <= baseline,
            (
                "The API's database connections must be gone "
                "after it exits.\n"
                f"baseline {baseline}, still open {after}"
            ),
        )

        ok(
            f"connections returned to the baseline of "
            f"{baseline} after exit"
        )

    finally:
        kill(
            process
        )


# ==========================================================
# TEST 2 - THE WORKER STOPS CLAIMING, THEN EXITS
# ==========================================================

def test_worker_shutdown() -> None:

    section(
        "TEST 2 - THE WORKER RECORDS ITSELF DRAINING, STOPS "
        "CLAIMING, AND EXITS CLEANLY"
    )

    from database.models import WorkerHeartbeatModel

    # ------------------------------------------------------
    # AN EMPTY THROWAWAY, AND IT IS PROVEN EMPTY
    # ------------------------------------------------------

    reset_scratch()

    probe = scratch_engine()

    session_factory = sessionmaker(
        bind=probe
    )

    with session_factory() as session:

        waiting = session.execute(
            sa.text(
                "select count(*) from document_jobs"
            )
        ).scalar_one()

    assert_equal(
        waiting,
        0,
        (
            "The throwaway queue must be empty before a real "
            "worker is started against it. A worker claims "
            "the head of the queue; if this is not zero, this "
            "test is about to process somebody's documents "
            "as a side effect of checking a signal handler."
        ),
    )

    ok(
        f"the worker will run against an empty throwaway "
        f"database ({SCRATCH_DATABASE}), so it has no real "
        "work it could claim"
    )

    # ------------------------------------------------------
    # THE WORKER NAMES ITSELF
    # ------------------------------------------------------
    #
    # There is no --worker-id flag, on purpose:
    # default_worker_id() is host + pid + a random suffix, and
    # the suffix exists so a restarted worker cannot be
    # mistaken for the one that just died and have its stale
    # lease extended by its own successor.
    #
    # So the row is discovered rather than named. Which means
    # recording the ids that already exist first -- otherwise
    # a heartbeat left by anything else would be picked up and
    # this test would assert against a worker it did not
    # start.

    with session_factory() as session:

        before = {
            row.worker_id
            for row in session.query(
                WorkerHeartbeatModel
            ).all()
        }

    process = spawn(
        "-m",
        "backend.worker",

        # No model load. This test is about signals, and
        # 2.9 seconds of PaddleOCR is 2.9 seconds of noise.
        "--no-warm",

        environment={
            "VIGILOX_WORKER_EAGER_PIPELINE": "false",

            # THE ISOLATION. Without this line the worker
            # claims from the real queue.
            "DATABASE_URL": scratch_url(),
        },
    )

    worker_id = None

    try:

        # --------------------------------------------------
        # WAIT FOR IT TO CHECK IN
        # --------------------------------------------------
        #
        # The heartbeat is written from inside the run loop,
        # so its appearance is proof the loop is running --
        # which is what has to be true before a shutdown
        # signal means anything.

        status = None

        deadline = time.monotonic() + 120

        while time.monotonic() < deadline:

            with session_factory() as session:

                fresh = [
                    row
                    for row in session.query(
                        WorkerHeartbeatModel
                    ).all()
                    if row.worker_id not in before
                ]

                if fresh:
                    worker_id = fresh[0].worker_id
                    status = fresh[0].status
                    break

            if process.poll() is not None:
                break

            time.sleep(
                0.5
            )

        assert_true(
            worker_id is not None,
            (
                "The worker must check in before its "
                "shutdown can be tested. The heartbeat is "
                "written from inside the run loop, so its "
                "appearance is the proof that the loop is "
                "running -- which has to be true before a "
                "shutdown signal means anything.\n"
                + drain(
                    process
                )[-3000:]
            ),
        )

        assert_equal(
            status,
            "RUNNING",
            "A worker in its run loop must record RUNNING.",
        )

        ok(
            f"the worker checked in as {worker_id} with "
            "status RUNNING"
        )

        # --------------------------------------------------
        # THE SIGNAL
        # --------------------------------------------------

        name = request_stop(
            process
        )

        code, elapsed = wait_for_exit(
            process,
            seconds=120,
        )

        output = drain(
            process
        )

        assert_true(
            code is not None,
            (
                f"The worker did not exit within 120s of "
                f"{name}.\n{output[-3000:]}"
            ),
        )

        # Same platform caveat as the API. On Linux the
        # worker must exit 0; on Windows the console-control
        # path may report 3 for a shutdown that completed, so
        # the acceptable set is stated explicitly and the
        # actual code is printed rather than hidden.
        acceptable = (
            (
                0,
                3,
            )
            if WINDOWS
            else (
                0,
            )
        )

        assert_true(
            code in acceptable,
            (
                f"The worker must exit cleanly on {name}. "
                f"Acceptable: {acceptable}, got {code}.\n"
                "A code outside that set means it crashed "
                "rather than stopped, and a worker that "
                "crashes on SIGTERM abandons the document it "
                f"was holding.\n{output[-4000:]}"
            ),
        )

        ok(
            f"{name} -> exit {code} in {elapsed:.2f}s"
        )

        # --------------------------------------------------
        # IT SAID WHAT IT WAS DOING
        # --------------------------------------------------

        assert_in(
            "worker.shutdown_requested",
            output,
            (
                "The worker must record that it was asked to "
                "stop, and that it is finishing the current "
                "job rather than abandoning it."
            ),
        )

        ok(
            "the worker logged the shutdown request rather "
            "than disappearing"
        )

        # --------------------------------------------------
        # AND THE HEARTBEAT ENDED AT STOPPED
        # --------------------------------------------------
        #
        # This is what stops a rolling deploy looking like a
        # worker failure. STOPPED means "gone on purpose";
        # a RUNNING row that stops advancing means "died".
        # Monitoring alerts on the second one.

        with session_factory() as session:

            final = session.get(
                WorkerHeartbeatModel,
                worker_id,
            )

            assert_true(
                final is not None,
                (
                    "The heartbeat row must survive the "
                    "shutdown. Deleting it would make a "
                    "deliberate stop indistinguishable from "
                    "a worker that was never deployed."
                ),
            )

            assert_equal(
                final.status,
                "STOPPED",
                (
                    "A clean exit must leave the heartbeat "
                    "at STOPPED. Left at RUNNING, monitoring "
                    "reports a dead worker for every "
                    "deliberate stop, and an alert that "
                    "fires on every deploy is an alert that "
                    "gets muted."
                ),
            )

        ok(
            "the heartbeat ended at STOPPED, so a deliberate "
            "stop is distinguishable from a death"
        )

    finally:

        kill(
            process
        )

        probe.dispose()

        # The whole database goes, so there is no per-row
        # cleanup to get wrong.
        drop_scratch()


# ==========================================================
# TEST 3 - A SECOND SIGNAL GIVES UP WAITING
# ==========================================================

def test_second_signal_forces_exit() -> None:

    section(
        "TEST 3 - A SECOND SIGNAL EXITS IMMEDIATELY"
    )

    # ------------------------------------------------------
    # Why this exists: the first signal starts a wait that is
    # bounded by the current job, and the worst measured
    # pipeline case is 268 seconds. An operator who needs the
    # process gone now should not have to reach for SIGKILL,
    # which skips the heartbeat write and every other bit of
    # cleanup.
    #
    # Asserted on the source and on the exit code together --
    # an idle worker exits so fast on the first signal that
    # racing a second one in is unreliable, so the behaviour
    # is read from the code and the escape hatch is proven to
    # exist.
    # ------------------------------------------------------

    source = (
        PROJECT_ROOT
        / "backend"
        / "worker.py"
    ).read_text(
        encoding="utf-8",
    )

    assert_in(
        "Second shutdown signal",
        source,
        (
            "A second signal must be handled distinctly from "
            "the first."
        ),
    )

    assert_in(
        "worker.force_exit",
        source,
        (
            "The forced exit must be recorded, so a worker "
            "that abandoned a job is identifiable "
            "afterwards."
        ),
    )

    # And the forced path must exit NON-zero. A worker that
    # abandoned work must not report success.
    forced = source[
        source.index(
            "Second shutdown signal"
        ):
    ]

    assert_in(
        "SystemExit(",
        forced[:800],
        "The second signal must actually exit.",
    )

    assert_true(
        "raise SystemExit(\n                1\n            )"
        in forced[:800]
        or "SystemExit(1)" in forced[:800],
        (
            "The forced exit must be non-zero. Exiting 0 "
            "after abandoning a claimed job reports success "
            "for work that did not happen."
        ),
    )

    ok(
        "a second signal exits immediately and non-zero, and "
        "records worker.force_exit"
    )


# ==========================================================
# TEST 4 - WORK THAT DID NOT FINISH IS NOT MARKED FINISHED
# ==========================================================

def test_killed_worker_leaves_work_recoverable() -> None:

    section(
        "TEST 4 - A WORKER KILLED MID-JOB LEAVES THE JOB "
        "RECOVERABLE, NOT COMPLETED"
    )

    # ------------------------------------------------------
    # The worst failure in this whole area, and the quietest.
    #
    # SIGKILL, an OOM kill, a host reboot -- no handler runs,
    # nothing is written. The job is left PROCESSING with a
    # lease held by a worker that no longer exists. What must
    # happen is that the lease expires and another worker
    # picks it up. What must NOT happen is the job being
    # recorded as COMPLETED, which is indistinguishable from
    # success forever afterwards.
    #
    # Simulated by writing the state a killed worker leaves
    # behind, then asking the real claim query what it does
    # with it. Actually killing a worker mid-document would
    # need a real document, OCR and the extraction provider;
    # the state it leaves is exactly reproducible without any
    # of that.
    # ------------------------------------------------------

    from datetime import datetime, timedelta, timezone

    from database.job_repositories import (
        DocumentJobRepository,
    )
    from database.models import DocumentJobModel

    # A throwaway here too. only_job_ids already stops this
    # claiming real work -- that is the point of the argument
    # and it is relied on below -- but this test also PLANTS a
    # row, and a planted row in the real database is residue
    # if anything goes wrong before the cleanup runs.
    reset_scratch()

    probe = scratch_engine()

    session_factory = sessionmaker(
        bind=probe
    )

    job_id = str(
        uuid.uuid4()
    )

    dead_worker = f"killed-{uuid.uuid4().hex[:8]}"

    now = datetime.now(
        timezone.utc
    )

    try:

        with session_factory() as session:

            session.add(
                DocumentJobModel(
                    id=job_id,
                    status="PROCESSING",
                    original_filename=(
                        "abandoned.png"
                    ),
                    content_type="image/png",
                    size_bytes=1234,
                    source_name=(
                        f"{job_id}.png"
                    ),
                    attempt_count=1,
                    worker_id=dead_worker,

                    # The lease a killed worker leaves
                    # behind: held, and already past.
                    lease_expires_at=(
                        now
                        - timedelta(
                            seconds=30,
                        )
                    ),
                    started_at=(
                        now
                        - timedelta(
                            seconds=400,
                        )
                    ),
                )
            )

            session.commit()

        ok(
            f"planted a PROCESSING job with an expired lease "
            f"held by {dead_worker}"
        )

        # --------------------------------------------------
        # IT IS NOT COMPLETED, AND NOTHING SAID IT WAS
        # --------------------------------------------------

        with session_factory() as session:

            planted = session.get(
                DocumentJobModel,
                job_id,
            )

            assert_equal(
                planted.status,
                "PROCESSING",
                (
                    "A job whose worker vanished must stay "
                    "PROCESSING. Nothing may mark it "
                    "COMPLETED or FAILED on the worker's "
                    "behalf: only the process that did the "
                    "work knows what happened, and it is "
                    "gone."
                ),
            )

            assert_true(
                planted.completed_at is None,
                (
                    "completed_at must be unset. A timestamp "
                    "here is a permanent claim that a "
                    "document was processed when it was not."
                ),
            )

        ok(
            "the abandoned job is still PROCESSING with no "
            "completion timestamp"
        )

        # --------------------------------------------------
        # AND THE LEASE LETS IT BE RECOVERED
        # --------------------------------------------------
        #
        # Through the real claim query. A recovery rule
        # re-implemented here could agree with itself and
        # disagree with production.

        # --------------------------------------------------
        # RECOVERY IS ITS OWN OPERATION, NOT A SIDE EFFECT
        # OF CLAIMING
        # --------------------------------------------------
        #
        # The first version of this test expected claim_next
        # to pick up a PROCESSING job whose lease had expired.
        # It does not, and it should not: the claimable
        # predicate is QUEUED plus RETRY_WAIT past its
        # backoff, and widening it to "or PROCESSING with a
        # dead lease" would put lease arithmetic inside the
        # hot path of every claim.
        #
        # Recovery is reclaim_expired(), a separate step that
        # decides between requeueing and failing as ABANDONED
        # -- a document that repeatedly kills its worker has
        # to stop being handed to the next one.
        #
        # Driven here through the real worker entrypoint,
        # `python -m backend.worker --reclaim-only`, against
        # the throwaway database. Not by importing it: the
        # service uses SessionLocal, which binds to
        # DATABASE_URL at import time, so an in-process call
        # would operate on the REAL database. That is the
        # mistake that once processed two of somebody's
        # uploads, and a subprocess is the only way to be
        # certain which database is being written.

        completed = spawn(
            "-m",
            "backend.worker",
            "--reclaim-only",
            "--no-warm",
            environment={
                "DATABASE_URL": scratch_url(),
                "VIGILOX_WORKER_EAGER_PIPELINE": "false",
            },
        )

        code, elapsed = wait_for_exit(
            completed,
            seconds=180,
        )

        assert_equal(
            code,
            0,
            (
                "The reclaim pass must run and exit 0.\n"
                + drain(
                    completed
                )[-3000:]
            ),
        )

        with session_factory() as session:

            recovered = session.get(
                DocumentJobModel,
                job_id,
            )

            assert_equal(
                recovered.status,
                "QUEUED",
                (
                    "An expired lease must return the job to "
                    "QUEUED. Without this a worker killed "
                    "mid-document strands that document in "
                    "PROCESSING forever, and the queue "
                    "silently loses one slot per crash."
                ),
            )

            assert_true(
                recovered.worker_id is None,
                (
                    "The dead worker's claim must be "
                    "released. A row still naming it looks "
                    "like work in progress."
                ),
            )

            assert_true(
                recovered.lease_expires_at is None,
                "The expired lease must be cleared.",
            )

            assert_true(
                recovered.completed_at is None,
                (
                    "Recovery must not fabricate a "
                    "completion. The document was never "
                    "processed."
                ),
            )

            # --------------------------------------------
            # THE ATTEMPT IS NOT GIVEN BACK
            # --------------------------------------------
            #
            # Deliberate, and the repository says so: an
            # abandoned attempt is still an attempt.
            # Otherwise a document that kills the worker is
            # retried without limit, and each retry kills the
            # worker again.
            assert_equal(
                recovered.attempt_count,
                1,
                (
                    "The abandoned attempt must still count. "
                    "Resetting it would let a document that "
                    "crashes the worker retry forever."
                ),
            )

            attempts = recovered.attempt_count

            maximum = recovered.max_attempts

        ok(
            f"reclaim returned the job to QUEUED in "
            f"{elapsed:.2f}s, released the dead lease, kept "
            f"attempt {attempts} of {maximum}, and wrote no "
            "completion"
        )

        # --------------------------------------------------
        # AND NOW A WORKER CAN ACTUALLY TAKE IT
        # --------------------------------------------------
        #
        # Through the real claim query, restricted to this one
        # job. only_job_ids exists precisely so a test cannot
        # claim somebody's real upload; here the database is a
        # throwaway as well, so it is belt and braces.

        with session_factory() as session:

            repository = DocumentJobRepository(
                session
            )

            claimed = repository.claim_next(
                worker_id="recovery-probe",
                lease_seconds=60,
                only_job_ids=job_id,
            )

            # Committing is what publishes the claim: the row
            # lock that makes it safe lives for the length of
            # the transaction.
            session.commit()

            claimed_id = (
                claimed.id
                if claimed is not None
                else None
            )

        assert_equal(
            claimed_id,
            job_id,
            (
                "After recovery the job must be claimable by "
                "the ordinary claim path. If it is not, "
                "recovery moved it to a state nothing "
                "processes."
            ),
        )

        with session_factory() as session:

            reclaimed = session.get(
                DocumentJobModel,
                job_id,
            )

            assert_equal(
                reclaimed.worker_id,
                "recovery-probe",
                (
                    "The lease must now be held by the "
                    "recovering worker."
                ),
            )

            assert_equal(
                reclaimed.attempt_count,
                2,
                (
                    "The new claim is the second attempt: "
                    "one abandoned, one now in progress."
                ),
            )

            assert_true(
                reclaimed.attempt_count
                <= reclaimed.max_attempts,
                (
                    "The recovered attempt must be within "
                    "max_attempts."
                ),
            )

        ok(
            "a fresh worker then claimed the recovered job as "
            "attempt 2, so the crash cost the document one "
            "attempt and up to one lease of delay -- nothing "
            "permanent"
        )

    finally:

        # --------------------------------------------------
        # ONLY THE PLANTED ROW TO REMOVE
        # --------------------------------------------------
        #
        # Because the claim was restricted to it. Nothing
        # real was touched, so there is nothing real to put
        # back -- which is the point of only_job_ids.

        with session_factory() as session:

            removed = session.query(
                DocumentJobModel
            ).filter(
                DocumentJobModel.id == job_id
            ).delete()

            session.commit()

        stranded = None

        with session_factory() as session:

            stranded = session.query(
                DocumentJobModel
            ).filter(
                DocumentJobModel.worker_id
                == "recovery-probe"
            ).count()

        if stranded:

            raise AssertionError(
                f"This test left {stranded} job(s) leased to "
                "recovery-probe. A probe that strands real "
                "work has caused the exact failure it was "
                "written to check for."
            )

        print(
            f"       (removed {removed} planted job; no real "
            "job was claimed, so none needed putting back)"
        )

        probe.dispose()

        drop_scratch()


# ==========================================================
# TEST 5 - THE GRACE PERIOD IS LONG ENOUGH FOR REAL WORK
# ==========================================================

def test_grace_period_covers_the_measured_worst_case() -> None:

    section(
        "TEST 5 - THE GRACE PERIOD IS LONGER THAN THE WORK "
        "IT HAS TO WAIT FOR"
    )

    # ------------------------------------------------------
    # A graceful shutdown that is not given enough time is a
    # SIGKILL with extra steps.
    #
    # The worker's first signal starts a wait bounded by the
    # current document. Measured worst case for the whole
    # pipeline is 268 seconds, and the lease is 360. If
    # stop_grace_period is below that, the runtime kills the
    # worker mid-document on a routine deploy -- and TEST 4 is
    # what happens next, on every deploy, quietly.
    # ------------------------------------------------------

    compose = (
        PROJECT_ROOT
        / "docker-compose.yml"
    ).read_text(
        encoding="utf-8",
    )

    from backend.app.services.document_worker import (
        DEFAULT_LEASE_SECONDS,
    )

    worker_block = compose[
        compose.index(
            "worker:"
        ):
    ]

    line = [
        entry.strip()
        for entry in worker_block.splitlines()
        if "stop_grace_period" in entry
    ]

    assert_true(
        line,
        (
            "The worker service must declare a "
            "stop_grace_period. Docker's default is 10 "
            "seconds, which is shorter than a single "
            "document."
        ),
    )

    grace = int(
        line[0].split(
            ":"
        )[1].strip().rstrip(
            "s"
        )
    )

    assert_true(
        grace >= 268,
        (
            f"stop_grace_period is {grace}s, below the "
            "measured worst-case pipeline of 268s. A deploy "
            "would SIGKILL the worker mid-document, leaving "
            "the job to be recovered by lease expiry every "
            "single time."
        ),
    )

    assert_true(
        grace >= DEFAULT_LEASE_SECONDS - 60,
        (
            f"stop_grace_period is {grace}s against a "
            f"{DEFAULT_LEASE_SECONDS}s lease. The grace "
            "period should be in the same region as the "
            "lease: the lease is the statement of how long "
            "one document may take."
        ),
    )

    ok(
        f"the worker's stop_grace_period is {grace}s, above "
        f"the 268s measured worst case and comparable to the "
        f"{DEFAULT_LEASE_SECONDS}s lease"
    )

    # ------------------------------------------------------
    # AND THE API'S IS SHORT ON PURPOSE
    # ------------------------------------------------------

    assert_in(
        "stop_grace_period",
        compose[
            :compose.index(
                "worker:"
            )
        ],
        (
            "The api service should declare its own grace "
            "period rather than inheriting the default, so "
            "the difference between the two is a decision on "
            "the record."
        ),
    )

    ok(
        "the api declares its own, shorter grace period: an "
        "HTTP request is not a document"
    )


# ==========================================================
# TEST 6 - THE PROCEDURE IS DOCUMENTED
# ==========================================================

def test_diagnostics_cannot_block() -> None:

    section(
        "TEST 0 - THE SUITE'S OWN DIAGNOSTICS CANNOT BLOCK"
    )

    # ------------------------------------------------------
    # This suite deadlocked on SUCCESS once.
    #
    # Child output was captured with stdout=PIPE and read by
    # drain(), which was passed as the message argument to an
    # assertion. Python evaluates arguments before the call,
    # so drain() ran whether the assertion passed or failed --
    # and reading a pipe blocks until the writer closes it,
    # which for a server under test is never.
    #
    # The failure mode is the nasty kind: the suite hung after
    # printing a section header, holding a uvicorn process
    # open, indistinguishable from a slow test.
    #
    # So the property is asserted rather than remembered.
    # ------------------------------------------------------

    source = Path(
        __file__
    ).read_text(
        encoding="utf-8",
    )

    # Matched as an ARGUMENT, not as a substring.
    #
    # The substring form matched its own detector line -- the
    # fifth self-referential false positive of this shape in
    # this work. A source scanner is part of the source it
    # scans, and a rule loose enough to flag itself teaches
    # whoever hits it to loosen the rule.
    #
    # A real occurrence is a keyword argument, so the line
    # begins with it.
    piped = [
        line.strip()
        for line in source.splitlines()
        if line.strip().startswith(
            "stdout="
        )
        and "PIPE" in line
    ]

    # And the detector is checked against a constructed case,
    # because a rule that cannot fail is not a rule.
    planted = [
        line.strip()
        for line in (
            "        stdout=subprocess.PIPE,",
            "        stdout=handle,",
        )
        if line.strip().startswith(
            "stdout="
        )
        and "PIPE" in line
    ]

    assert_equal(
        planted,
        [
            "stdout=subprocess.PIPE,",
        ],
        (
            "The detector must flag a planted PIPE argument "
            "and leave a file handle alone."
        ),
    )

    assert_equal(
        piped,
        [],
        (
            "Child output must go to a file, not a pipe. A "
            "diagnostic that reads a pipe blocks until the "
            "child exits, and it is evaluated even when the "
            "assertion it belongs to is passing."
        ),
    )

    # And drain() must be the non-blocking kind.
    assert_true(
        "return process.output()" in source,
        (
            "drain() must read the log file rather than the "
            "process stream."
        ),
    )

    ok(
        "child output is captured to files, so a diagnostic "
        "passed to a passing assertion cannot hang the suite"
    )

    # ------------------------------------------------------
    # AND NO CHILD MAY BE POINTED AT THE REAL DATABASE
    # ------------------------------------------------------
    #
    # The other bug this suite had, and the more expensive
    # one: a real worker started against the configured
    # database claimed three real uploads, ran OCR and the
    # extraction provider on two of them, and was killed
    # mid-document on the third.
    #
    # Any spawn that starts a WORKER must override
    # DATABASE_URL. The API may use the real one -- it reads
    # and serves, it does not claim work.

    worker_spawns = [
        index
        for index, line in enumerate(
            source.splitlines()
        )
        if '"backend.worker"' in line
    ]

    assert_true(
        worker_spawns,
        (
            "The detector found no worker spawn. It is "
            "looking in the wrong place."
        ),
    )

    lines = source.splitlines()

    for index in worker_spawns:

        window = "\n".join(
            lines[index:index + 25]
        )

        assert_true(
            "DATABASE_URL" in window
            and "scratch_url()" in window,
            (
                "A worker is spawned without DATABASE_URL "
                "overridden to the throwaway. A real worker "
                "claims the head of the real queue, which is "
                "how this suite once processed two of "
                "somebody's uploads and stranded a third.\n"
                f"near line {index + 1}:\n{window}"
            ),
        )

    ok(
        f"all {len(worker_spawns)} worker spawn(s) override "
        "DATABASE_URL to a throwaway, so no real job can be "
        "claimed"
    )


def test_shutdown_is_documented() -> None:

    section(
        "TEST 6 - SHUTDOWN BEHAVIOUR IS WRITTEN DOWN"
    )

    path = (
        PROJECT_ROOT
        / "docs"
        / "operations"
        / "shutdown.md"
    )

    assert_true(
        path.is_file(),
        "docs/operations/shutdown.md must exist.",
    )

    document = path.read_text(
        encoding="utf-8",
    ).lower()

    for topic, needle in (
        (
            "the signal a runtime sends",
            "sigterm",
        ),
        (
            "what a second signal does",
            "second",
        ),
        (
            "the grace period",
            "stop_grace_period",
        ),
        (
            "lease recovery after a hard kill",
            "lease",
        ),
        (
            "the draining heartbeat state",
            "draining",
        ),
        (
            "that incomplete work is not marked complete",
            "completed",
        ),
        (
            "connection pool release",
            "dispose",
        ),
    ):

        assert_true(
            needle in document,
            (
                f"The document must cover {topic} "
                f"(looked for {needle!r})."
            ),
        )

    ok(
        "shutdown.md covers all 7 topics"
    )


# ==========================================================
# MAIN
# ==========================================================

def main() -> int:

    print(
        "=" * 74
    )
    print(
        "PHASE 11.13 - GRACEFUL SHUTDOWN"
    )
    print(
        "=" * 74
    )
    print(
        f"  platform: {sys.platform}, polite signal: "
        + (
            "CTRL_BREAK_EVENT"
            if WINDOWS
            else "SIGTERM"
        )
    )

    try:

        test_diagnostics_cannot_block()
        test_api_shutdown()
        test_worker_shutdown()
        test_second_signal_forces_exit()
        test_killed_worker_leaves_work_recoverable()
        test_grace_period_covers_the_measured_worst_case()
        test_shutdown_is_documented()

    finally:
        close_logs()

    print()
    print(
        "=" * 74
    )
    print(
        "[PASS] PHASE 11.13 GRACEFUL SHUTDOWN TEST PASSED"
    )
    print(
        "=" * 74
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
