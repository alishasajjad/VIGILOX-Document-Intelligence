import argparse
import os
import signal
import time
import sys

from pathlib import Path


# ==========================================================
# VIGILOX DOCUMENT WORKER ENTRYPOINT
# PHASE 9.3
# ==========================================================
#
# The second process. The API accepts uploads and answers
# questions; this one does the eighteen seconds of work.
#
# Run it:
#
#     python -m backend.worker
#
# Both processes are the same image and the same code, started
# with different commands. That is deliberate -- one
# dependency set, one build, one thing to keep in step.
#
#
# GRACEFUL SHUTDOWN
# ----------------------------------------------------------
#
# SIGTERM is what a container runtime sends before SIGKILL, and
# what happens in between decides whether a deploy costs
# anything.
#
# Ignoring it means every rolling restart kills a worker
# mid-document: that document's OCR pass is thrown away, its
# job sits in PROCESSING until the lease expires -- three
# minutes by default -- and only then goes back to the queue.
#
# So SIGTERM asks the loop to stop, the current job finishes,
# and the process exits with its jobs properly recorded.
# Nothing is lost and nothing waits on a lease.
#
# A second SIGTERM exits immediately, because a worker that
# refuses to die is worse than one that drops a job.
# ==========================================================


PROJECT_ROOT = (
    Path(
        __file__
    )
    .resolve()
    .parents[1]
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


from dotenv import load_dotenv                     # noqa: E402

from backend.app.core.logging import (             # noqa: E402
    configure_operational_logging,
    get_operational_logger,
)


def build_parser() -> argparse.ArgumentParser:

    parser = (
        argparse.ArgumentParser(
            prog="python -m backend.worker",
            description=(
                "Process queued VIGILOX document jobs."
            ),
        )
    )

    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help=(
            "How many jobs to process at once. Defaults "
            "to VIGILOX_WORKER_CONCURRENCY, or 1. "
            "Raise it only with a measurement: OCR is "
            "CPU-bound and already multi-threaded, so "
            "parallel passes on one machine contend for "
            "the same cores."
        ),
    )

    parser.add_argument(
        "--no-warm",
        dest="warm",
        action="store_false",
        default=None,
        help=(
            "Do not load the OCR model before the run "
            "loop starts. Defaults to loading it, or to "
            "VIGILOX_WORKER_EAGER_PIPELINE."
        ),
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help=(
            "Process at most one job and exit. For "
            "diagnostics and for tests."
        ),
    )

    parser.add_argument(
        "--drain",
        action="store_true",
        help=(
            "Process until the queue is empty, then "
            "exit. Does not wait for jobs in "
            "RETRY_WAIT."
        ),
    )

    parser.add_argument(
        "--reclaim-only",
        action="store_true",
        help=(
            "Return jobs with expired leases to the "
            "queue, then exit. Use after an unclean "
            "shutdown when no worker is running."
        ),
    )

    return parser


def main(
    argv: list[str] | None = None,
) -> int:

    arguments = (
        build_parser()
        .parse_args(
            argv
        )
    )

    load_dotenv(
        PROJECT_ROOT / ".env"
    )

    configure_operational_logging()

    logger = (
        get_operational_logger(
            "worker"
        )
    )

    # Imported after the environment is loaded: the services
    # underneath read configuration at construction.
    from backend.app.services.document_worker import (
        DocumentWorker,
        WorkerRunner,
    )


    # ------------------------------------------------------
    # RECLAIM ONLY
    # ------------------------------------------------------

    if arguments.reclaim_only:

        recovered = (
            DocumentWorker()
            .reclaim_expired()
        )

        logger.info(
            "Lease recovery finished.",
            extra={
                "event":
                    "worker.reclaim_only",

                "reclaimed":
                    recovered,
            },
        )

        print(
            f"Returned {recovered} job(s) to the queue."
        )

        return 0


    # ------------------------------------------------------
    # ONE JOB, OR DRAIN
    # ------------------------------------------------------
    #
    # Both are single-threaded and bounded, so they skip the
    # runner entirely. Nothing here is a long-lived process,
    # so nothing here needs signal handling.
    # ------------------------------------------------------

    if arguments.once or arguments.drain:

        worker = (
            DocumentWorker()
        )

        worker.reclaim_expired()

        handled = 0


        while True:

            if not worker.process_one():
                break


            handled += 1


            if arguments.once:
                break


        print(
            f"Processed {handled} job(s): "
            f"{worker.completed} completed, "
            f"{worker.failed} failed, "
            f"{worker.retried} awaiting retry."
        )

        return 0


    # ------------------------------------------------------
    # THE LONG-RUNNING WORKER
    # ------------------------------------------------------

    runner = (
        WorkerRunner(
            concurrency=(
                arguments.concurrency
            ),
        )
    )

    stopping = {
        "requested": False,
    }


    def handle_signal(
        signal_number,
        frame,
    ):

        if stopping["requested"]:

            # Asked twice. Somebody wants this process gone.
            logger.warning(
                "Second shutdown signal; exiting now.",
                extra={
                    "event":
                        "worker.force_exit",
                },
            )

            raise SystemExit(
                1
            )


        stopping["requested"] = True

        logger.info(
            "Shutdown requested; finishing the current "
            "job.",
            extra={
                "event":
                    "worker.shutdown_requested",
            },
        )

        # PHASE 11.14. Recorded before the wait begins.
        #
        # Without it, a rolling deploy looks like a worker
        # failure for the length of the SIGTERM grace period --
        # up to 400 seconds in the compose stack -- and an
        # alert that fires on every deploy is an alert that
        # gets muted.
        try:
            if runner.heartbeat:
                runner.heartbeat.draining()

        except Exception:
            # Never let a monitoring write stop a shutdown.
            pass

        runner.request_stop()


    for name in (
        "SIGTERM",
        "SIGINT",

        # PHASE 11.13. Windows only, and it earns its place.
        #
        # CTRL_BREAK_EVENT -- what a parent process sends to
        # stop a child in its own process group, and what
        # Ctrl+Break sends in a console -- arrives as
        # SIGBREAK, not SIGINT. Without it registered, the
        # default Windows handler terminates the process with
        # STATUS_CONTROL_C_EXIT: no draining heartbeat, no
        # finishing the current document, exit code
        # 3221225786.
        #
        # That was found by the 11.13 test, which measured
        # exactly that code. It does not affect the Linux
        # containers, where SIGTERM is what arrives -- but a
        # developer stopping a local worker should get the
        # same behaviour production gets, not an abrupt kill
        # that abandons a document mid-pipeline.
        #
        # uvicorn registers SIGBREAK on Windows for the same
        # reason.
        "SIGBREAK",
    ):

        # Not every name exists on every platform. SIGBREAK is
        # Windows-only and SIGTERM is absent from some
        # environments; getattr keeps the list declarative
        # rather than branching on sys.platform.
        received = getattr(
            signal,
            name,
            None,
        )

        if received is not None:

            signal.signal(
                received,
                handle_signal,
            )


    # ------------------------------------------------------
    # LOAD THE MODEL BEFORE CLAIMING ANYTHING
    # PHASE 11.8
    # ------------------------------------------------------
    # DocumentWorker builds its pipeline lazily, on the first
    # document. For a long-running worker that is the wrong
    # moment, for two reasons:
    #
    #   1. FAIL FAST. A model that cannot load -- a missing
    #      cache, a broken install, not enough memory --
    #      should make the container fail to START. Lazily, it
    #      instead makes the FIRST CLAIMED JOB fail: an
    #      attempt is consumed, the document is delayed by a
    #      retry backoff, and the container looks healthy the
    #      whole time.
    #
    #   2. NOT UNDER A LEASE. Loading takes about 2.9 seconds
    #      measured. Lazily, that happens while the worker
    #      already holds a lease on a real job, so it is
    #      2.9 seconds of the lease spent on startup work.
    #
    # This is the opposite of the API's policy on purpose. The
    # API is lazy because it never runs OCR except through the
    # legacy synchronous route, and paying a few hundred
    # megabytes per replica for a route that may never be
    # called is waste. For the worker, the model IS the job.
    #
    # Measured, both directions:
    #
    #     eager   about 2929 ms of startup
    #     lazy    about 3 ms of startup
    #
    # --no-warm exists for a diagnostic run that should not
    # pay it.
    # ------------------------------------------------------

    warm = arguments.warm

    if warm is None:

        warm = os.getenv(
            "VIGILOX_WORKER_EAGER_PIPELINE",
            "true",
        ).strip().lower() not in (
            "0",
            "false",
            "no",
            "off",
        )


    if warm:

        started = time.monotonic()

        try:
            # Touching the property is what builds it.
            runner.warm()

        except Exception as exc:

            # Deliberately fatal. A worker that cannot build
            # its pipeline cannot do the one thing it exists
            # for, and a container that exits is visible in a
            # way that a container claiming and failing jobs
            # is not.
            logger.error(
                "OCR pipeline failed to load; refusing to "
                "start.",
                extra={
                    "event":
                        "worker.warmup_failed",

                    "error_type":
                        type(
                            exc
                        ).__name__,
                },
            )

            return 1

        logger.info(
            "OCR pipeline loaded.",
            extra={
                "event":
                    "worker.warmup_complete",

                "duration_ms":
                    round(
                        (
                            time.monotonic()
                            - started
                        )
                        * 1000,
                        1,
                    ),
            },
        )


    runner.run()

    # PHASE 11.14. A clean exit is recorded rather than the
    # row being deleted.
    #
    # "A worker stopped cleanly two minutes ago" is useful,
    # and an absent row would be indistinguishable from a
    # worker that was never started -- which is exactly the
    # distinction the health service exists to make.
    try:
        if runner.heartbeat:
            runner.heartbeat.stopped()

    except Exception:
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
