import importlib
import os
import threading
import time


# ==========================================================
# PHASE 9.5
# PERFORMANCE CONTRACT
# ==========================================================
#
# The measurements themselves live in
# scripts/development/async_performance.py, because a number
# measured on one laptop is not something to assert in a test
# suite -- it would fail on a slower machine for no reason.
#
# What IS asserted here is the shape the measurement depends
# on, so the optimisation cannot be quietly reverted:
#
#   1. The OCR model is built at most once per process, even
#      under concurrent first requests.
#
#   2. The API can defer building it, and the switch defaults
#      to the behaviour this process always had.
#
#   3. Deferring actually defers -- the measured 2.9s to 3ms
#      startup is only real if nothing else touches the
#      pipeline during startup.
#
#   4. A test that injects a fake pipeline straight onto
#      app.state still works, because ten suites do exactly
#      that and none of them should have to know about a
#      holder.
#
#   5. Reading job or batch status does not issue a query per
#      document. That is the N+1 check, and it is asserted as
#      a relationship (12 documents cost the same as 3) rather
#      than as a number.
# ==========================================================

PASSES: list[str] = []


def ok(
    message: str,
) -> None:

    PASSES.append(
        message
    )

    print(
        f"[PASS] {message}"
    )


def fail(
    message: str,
) -> None:

    raise AssertionError(
        message
    )


# ==========================================================
# 1. THE MODEL IS BUILT ONCE
# ==========================================================

def test_model_built_once_under_concurrency() -> None:

    from backend.app.services.lazy_pipeline import (
        LazyPipeline,
    )

    builds: list[int] = []

    lock = (
        threading.Lock()
    )

    def slow_factory():

        # Long enough that every thread is inside get() at the
        # same time. Without the lock they would all build.
        time.sleep(0.05)

        with lock:
            builds.append(1)

        return object()


    holder = (
        LazyPipeline(
            factory=slow_factory,
        )
    )

    if holder.is_loaded:
        fail(
            "A fresh holder reports its model as loaded."
        )


    threads = [
        threading.Thread(
            target=holder.get,
        )
        for _ in range(16)
    ]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join(
            timeout=20
        )


    if len(builds) != 1:
        fail(
            f"{len(builds)} pipelines were constructed "
            "by 16 concurrent first requests. Each one "
            "is a separate PaddleOCR instance and a few "
            "hundred megabytes."
        )


    if not holder.is_loaded:
        fail(
            "The holder does not report its model as "
            "loaded after building it."
        )


    first = holder.get()

    if any(
        holder.get() is not first
        for _ in range(5)
    ):
        fail(
            "The holder returns a different instance on "
            "repeat calls."
        )


    ok(
        "16 concurrent first requests build exactly one "
        "pipeline, and it is reused"
    )


# ==========================================================
# 2. THE SWITCH
# ==========================================================

def test_eager_is_the_default() -> None:

    from backend.app.services.lazy_pipeline import (
        eager_pipeline_enabled,
    )

    previous = (
        os.environ.pop(
            "VIGILOX_API_EAGER_PIPELINE",
            None,
        )
    )


    try:

        if not eager_pipeline_enabled():
            fail(
                "Deferring the model load is the "
                "default. It changes when readiness "
                "means what it says and makes the first "
                "analyze call slow, so it has to be "
                "opted into."
            )


        for value in (
            "false",
            "FALSE",
            "0",
            "no",
            "off",
            " off ",
        ):

            os.environ[
                "VIGILOX_API_EAGER_PIPELINE"
            ] = value

            if eager_pipeline_enabled():
                fail(
                    f"{value!r} did not disable eager "
                    "construction."
                )


        # A typo must not silently defer the load and turn
        # somebody's first analyze request into a twenty
        # second one.
        for value in (
            "flase",
            "",
            "true",
            "yes",
            "1",
        ):

            os.environ[
                "VIGILOX_API_EAGER_PIPELINE"
            ] = value

            if not eager_pipeline_enabled():
                fail(
                    f"{value!r} disabled eager "
                    "construction. Only an explicit "
                    "false-ish value may."
                )


    finally:

        os.environ.pop(
            "VIGILOX_API_EAGER_PIPELINE",
            None,
        )

        if previous is not None:
            os.environ[
                "VIGILOX_API_EAGER_PIPELINE"
            ] = previous


    ok(
        "eager construction is the default and only an "
        "explicit false-ish value defers it"
    )


def test_injected_pipeline_still_works() -> None:

    """
    Ten suites assign a fake pipeline onto app.state to
    control what analyze does. None of them should have to
    know the API defers a model load.
    """

    from backend.app.services.lazy_pipeline import (
        LazyPipeline,
    )

    class FakePipeline:

        def process(
            self,
            *args,
            **kwargs,
        ):
            return {}


    fake = (
        FakePipeline()
    )

    if LazyPipeline.resolve(
        fake
    ) is not fake:
        fail(
            "An injected pipeline is not passed "
            "through, so every test that assigns one "
            "would break."
        )


    built = (
        FakePipeline()
    )

    holder = (
        LazyPipeline(
            factory=lambda: built,
        )
    )

    if LazyPipeline.resolve(
        holder
    ) is not built:
        fail(
            "A holder does not resolve to its service."
        )


    # Resolving twice must not try to resolve the service.
    if LazyPipeline.resolve(
        LazyPipeline.resolve(
            holder
        )
    ) is not built:
        fail(
            "resolve() is not idempotent."
        )


    ok(
        "an injected pipeline passes through and a holder "
        "resolves, so both call styles work"
    )


# ==========================================================
# 3. DEFERRING ACTUALLY DEFERS
# ==========================================================

def test_deferred_startup_touches_no_model() -> None:

    """
    The measured 2.9s to 3ms startup only holds if nothing
    else in the lifespan reaches for the pipeline.

    A readiness check, a metric or a warm-up that touched it
    would undo the saving silently, and the only symptom would
    be a slow startup nobody attributes to it. So the test
    asks the holder whether it was built.
    """

    from fastapi.testclient import (
        TestClient,
    )

    os.environ[
        "VIGILOX_API_EAGER_PIPELINE"
    ] = "false"


    try:

        import backend.app.main as main_module

        importlib.reload(
            main_module
        )

        started = (
            time.perf_counter()
        )

        with TestClient(
            main_module.app,
            raise_server_exceptions=False,
        ) as client:

            startup_ms = (
                (
                    time.perf_counter()
                    - started
                )
                * 1000.0
            )

            holder = (
                main_module.app.state.pipeline
            )

            if holder.is_loaded:
                fail(
                    "Something built the pipeline during "
                    "startup despite deferral being "
                    "requested. The startup saving is "
                    "gone and nothing would say so."
                )


            response = (
                client.get(
                    "/health/ready"
                )
            )

            if response.status_code != 200:
                fail(
                    "Readiness fails when the model load "
                    "is deferred. An API that has not "
                    "needed a pipeline is ready to do "
                    "everything it is for."
                )


            body = (
                response.json()
            )

            reported = (
                body["checks"]["services"]
                .get(
                    "pipeline_loaded"
                )
            )

            if reported is not False:
                fail(
                    "Readiness does not report "
                    "pipeline_loaded as false while the "
                    "model is unbuilt. An operator "
                    "debugging a slow first analyze call "
                    "needs to see this."
                )


            # Model load is seconds; a deferred startup is
            # milliseconds. This bound is deliberately loose
            # so it holds on a slow machine while still
            # failing if the model is being built.
            if startup_ms > 1500:
                fail(
                    f"Deferred startup took "
                    f"{startup_ms:.0f}ms, which is long "
                    "enough that something is probably "
                    "loading a model."
                )


    finally:

        os.environ.pop(
            "VIGILOX_API_EAGER_PIPELINE",
            None,
        )

        # Leave the module in its default state for whatever
        # runs next.
        import backend.app.main as main_module

        importlib.reload(
            main_module
        )


    ok(
        "with deferral requested, startup builds no model, "
        "readiness passes and reports pipeline_loaded false"
    )


# ==========================================================
# 4. NO N+1 IN STATUS READS
# ==========================================================

def test_status_reads_are_not_n_plus_one() -> None:

    """
    Asserted as a relationship, not a number.

    A batch status read that costs one query per document
    would be fine at three documents and a problem at twenty,
    and a fixed expected count would have to be updated every
    time an unrelated query moved. What matters is that the
    count does not grow with the batch.
    """

    from sqlalchemy import event

    from database.database import (
        engine,
    )

    from backend.app.services.job_service import (
        JobService,
    )

    from tests.jobs.test_phase9_job_worker import (
        Harness,
    )

    harness = (
        Harness()
    )

    counts: dict[int, int] = {}

    statements: list[str] = []

    active = {
        "on": False,
    }


    def record(
        conn,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ) -> None:

        if active["on"]:
            statements.append(
                statement
            )


    try:

        for size in (
            3,
            12,
        ):

            with __import__(
                "database.database",
                fromlist=["SessionLocal"],
            ).SessionLocal.begin() as session:

                from database.job_repositories import (
                    DocumentBatchRepository,
                )

                batch = (
                    DocumentBatchRepository(
                        session
                    ).create_batch(
                        submitted_count=size,
                    )
                )

                batch_id = batch.id


            for _ in range(
                size
            ):
                harness.queue(
                    batch_id=batch_id,
                )


            service = (
                JobService(
                    source_store=(
                        harness.store
                    ),
                )
            )

            # Warm the path, then count.
            service.get_batch(
                batch_id
            )

            event.listen(
                engine,
                "before_cursor_execute",
                record,
            )

            statements.clear()

            active["on"] = True

            service.get_batch(
                batch_id
            )

            active["on"] = False

            event.remove(
                engine,
                "before_cursor_execute",
                record,
            )

            counts[size] = len(
                statements
            )


    finally:

        removed = (
            harness.cleanup()
        )


    if counts[12] > counts[3]:
        fail(
            "Reading a 12-document batch cost "
            f"{counts[12]} queries and a 3-document "
            f"batch cost {counts[3]}. The query count "
            "grows with the batch, which is an N+1 and "
            "will get worse."
        )


    # And it must be a small constant, not merely constant.
    if counts[3] > 6:
        fail(
            f"A batch status read costs {counts[3]} "
            "queries. That is more than reading a batch, "
            "its jobs and their counts should need."
        )


    ok(
        f"a batch status read costs {counts[3]} queries "
        f"for 3 documents and {counts[12]} for 12 -- "
        "constant, not per document"
    )


# ==========================================================
# MAIN
# ==========================================================

def main() -> int:

    print()
    print("=" * 76)
    print(
        "PHASE 9.5 - PERFORMANCE CONTRACT"
    )
    print("=" * 76)
    print()

    test_model_built_once_under_concurrency()

    test_eager_is_the_default()

    test_injected_pipeline_still_works()

    test_deferred_startup_touches_no_model()

    test_status_reads_are_not_n_plus_one()

    print()
    print("=" * 76)
    print(
        f"[PASS] PHASE 9.5 PERFORMANCE CONTRACT PASSED - "
        f"{len(PASSES)} properties asserted"
    )
    print("=" * 76)

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
