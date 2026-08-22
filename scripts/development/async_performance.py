import argparse
import json
import statistics
import sys
import time
import uuid

from datetime import (
    datetime,
    timezone,
)
from pathlib import Path


# ==========================================================
# ASYNC PERFORMANCE MEASUREMENT
# PHASE 9.5
# ==========================================================
#
# The re-measurement that Phase 9.1's baseline exists to be
# compared against.
#
#
# THE DISTINCTION THAT MATTERS
# ----------------------------------------------------------
#
# Async processing did not make OCR faster. It cannot: the
# same PaddleOCR pass runs on the same CPU over the same
# image. Anyone reporting "18.4s -> 90ms" from this work would
# be comparing a completed document against an accepted
# upload, which are not the same event.
#
# So two numbers are reported, separately and labelled:
#
#   USER-PERCEIVED RESPONSIVENESS
#       how long POST /api/v1/document-jobs takes to answer.
#       This is what changed.
#
#   DOCUMENT PROCESSING DURATION
#       how long a worker takes to finish a document. This is
#       essentially unchanged, and is expected to be.
#
# What async bought is that the second number no longer
# happens inside an HTTP request. That is the honest claim.
#
#
# METHODOLOGY
# ----------------------------------------------------------
#
# Deliberately the same as Phase 9.1: the same StageTimer, the
# same document set chosen the same round-robin way, the same
# summarize() and the same p95 rule. Changing methodology
# between a before and an after produces a number that means
# nothing.
#
# The API measurements use enough samples that a p95 is real.
# The worker measurements do not, and say so, because each one
# costs an OCR pass.
#
#
# COLD VERSUS WARM
# ----------------------------------------------------------
#
# Reported separately, never averaged together. The first job
# in a worker process pays for the OCR model load; every job
# after it does not. Folding that into one mean would hide the
# cost of a restart and overstate steady-state throughput.
#
#
# COST
# ----------------------------------------------------------
#
# No Groq calls. The extraction step is stubbed exactly as in
# the Phase 9.1 local baseline, so this can be run freely and
# the OCR figure stays real.
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


from dotenv import load_dotenv               # noqa: E402

load_dotenv(
    PROJECT_ROOT / ".env"
)


from sqlalchemy import event                 # noqa: E402

from backend.app.core.timing import (        # noqa: E402
    StageTimer,
)


IMAGES_ROOT = (
    PROJECT_ROOT
    / "evaluation"
    / "images"
)

OUTPUT_ROOT = (
    PROJECT_ROOT
    / "output"
    / "performance"
)


# Same rule as Phase 9.1. A p95 from six samples is the
# largest number wearing a hat.
MINIMUM_FOR_P95 = 20


RUN_MARKER = (
    "phase95-"
    + uuid.uuid4().hex[:10]
)


# ==========================================================
# STATISTICS
# ==========================================================

def summarize(
    samples: list[float],
) -> dict:

    if not samples:
        return {"count": 0}


    ordered = sorted(
        samples
    )

    result = {
        "count":
            len(ordered),

        "min_ms":
            round(
                ordered[0],
                2,
            ),

        "median_ms":
            round(
                statistics.median(
                    ordered
                ),
                2,
            ),

        "max_ms":
            round(
                ordered[-1],
                2,
            ),

        "mean_ms":
            round(
                statistics.fmean(
                    ordered
                ),
                2,
            ),
    }


    if len(ordered) >= MINIMUM_FOR_P95:

        result["p95_ms"] = (
            round(
                statistics.quantiles(
                    ordered,
                    n=20,
                )[18],
                2,
            )
        )

    else:

        result["p95_ms"] = None

        result["p95_note"] = (
            f"sample of {len(ordered)} is below "
            f"{MINIMUM_FOR_P95}; a p95 from this many "
            "runs would not mean anything"
        )


    return result


# ==========================================================
# QUERY COUNTING
# ==========================================================

class QueryCounter:

    """
    Counts SQL statements issued while it is active.

    This is how "avoid N+1 status loading" becomes checkable
    rather than asserted. A batch status read whose query count
    grows with the number of documents in the batch is an N+1,
    and the only way to know is to count.
    """

    def __init__(
        self,
    ) -> None:

        from database.database import (
            engine,
        )

        self.engine = engine

        self.statements: list[str] = []

        self._active = False


    def _record(
        self,
        conn,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ) -> None:

        if self._active:
            self.statements.append(
                " ".join(
                    statement.split()
                )[:160]
            )


    def __enter__(
        self,
    ) -> "QueryCounter":

        event.listen(
            self.engine,
            "before_cursor_execute",
            self._record,
        )

        self.statements = []

        self._active = True

        return self


    def __exit__(
        self,
        exc_type,
        exc,
        traceback,
    ) -> bool:

        self._active = False

        event.remove(
            self.engine,
            "before_cursor_execute",
            self._record,
        )

        return False


    @property
    def count(
        self,
    ) -> int:

        return len(
            self.statements
        )


# ==========================================================
# SAMPLE SELECTION
# ==========================================================

def collect_documents(
    limit: int,
) -> list[Path]:

    by_type: dict[str, list[Path]] = {}


    for path in sorted(
        IMAGES_ROOT.rglob(
            "*"
        )
    ):

        if not path.is_file():
            continue

        if path.suffix.lower() not in (
            ".jpg",
            ".jpeg",
            ".png",
        ):
            continue

        by_type.setdefault(
            path.parent.name,
            [],
        ).append(
            path
        )


    if not by_type:
        raise SystemExit(
            f"No images under {IMAGES_ROOT}."
        )


    # Round-robin across document types, exactly as Phase 9.1
    # did, so the sample is comparable.
    found: list[Path] = []
    types = sorted(
        by_type
    )
    index = 0

    while len(found) < limit:

        added = False

        for document_type in types:

            bucket = by_type[
                document_type
            ]

            if index < len(bucket):
                found.append(
                    bucket[index]
                )
                added = True

                if len(found) >= limit:
                    break

        if not added:
            break

        index += 1


    return found


# ==========================================================
# PART 1: USER-PERCEIVED API RESPONSIVENESS
# ==========================================================

def measure_api(
    samples: int,
) -> dict:

    """
    How long the async endpoints take to answer.

    No OCR runs here, and that is the point: the whole reason
    the job endpoint exists is that it does not wait for the
    pipeline.
    """

    from fastapi.testclient import (
        TestClient,
    )

    from backend.app.main import (
        app,
    )

    print(
        "Measuring API responsiveness "
        f"({samples} samples)..."
    )

    image_bytes = (
        b"\xff\xd8\xff\xe0" + b"J" * 60000
    )

    create_ms: list[float] = []
    status_ms: list[float] = []
    batch_create_ms: list[float] = []
    batch_status_ms: list[float] = []

    job_ids: list[str] = []
    batch_ids: list[str] = []

    query_counts = {}


    with TestClient(
        app,
        raise_server_exceptions=False,
    ) as client:

        # ------------------------------------------------
        # POST /document-jobs
        # ------------------------------------------------

        for index in range(
            samples
        ):

            started = (
                time.perf_counter()
            )

            response = (
                client.post(
                    "/api/v1/document-jobs",
                    files={
                        "file": (
                            f"{RUN_MARKER}-{index}.jpg",
                            image_bytes,
                            "image/jpeg",
                        ),
                    },
                )
            )

            elapsed = (
                (
                    time.perf_counter()
                    - started
                )
                * 1000.0
            )

            if response.status_code != 202:
                raise SystemExit(
                    "Job creation returned "
                    f"{response.status_code}: "
                    f"{response.text[:200]}"
                )

            create_ms.append(
                elapsed
            )

            job_ids.append(
                response.json()["job_id"]
            )


        # ------------------------------------------------
        # GET /document-jobs/{id}
        # ------------------------------------------------

        for job_id in job_ids:

            started = (
                time.perf_counter()
            )

            response = (
                client.get(
                    f"/api/v1/document-jobs/{job_id}"
                )
            )

            status_ms.append(
                (
                    time.perf_counter()
                    - started
                )
                * 1000.0
            )

            if response.status_code != 200:
                raise SystemExit(
                    "Job status returned "
                    f"{response.status_code}"
                )


        # ------------------------------------------------
        # BATCHES, AND THE N+1 QUESTION
        # ------------------------------------------------
        #
        # Two batch sizes, so the query count can be
        # compared. If reading a 12-document batch costs
        # more queries than reading a 3-document batch,
        # that is an N+1 and it will get worse.
        # ------------------------------------------------

        for size in (
            3,
            12,
        ):

            files = [
                (
                    "files",
                    (
                        f"{RUN_MARKER}-b{size}-{n}.jpg",
                        image_bytes,
                        "image/jpeg",
                    ),
                )
                for n in range(
                    size
                )
            ]

            started = (
                time.perf_counter()
            )

            response = (
                client.post(
                    "/api/v1/document-batches",
                    files=files,
                )
            )

            batch_create_ms.append(
                (
                    time.perf_counter()
                    - started
                )
                * 1000.0
            )

            if response.status_code != 202:
                raise SystemExit(
                    "Batch creation returned "
                    f"{response.status_code}: "
                    f"{response.text[:200]}"
                )

            batch_id = (
                response.json()["batch_id"]
            )

            batch_ids.append(
                batch_id
            )

            # Warm the path once, then count.
            client.get(
                f"/api/v1/document-batches/{batch_id}"
            )

            with QueryCounter() as counter:

                started = (
                    time.perf_counter()
                )

                client.get(
                    f"/api/v1/document-batches/{batch_id}"
                )

                batch_status_ms.append(
                    (
                        time.perf_counter()
                        - started
                    )
                    * 1000.0
                )

            query_counts[
                f"batch_status_{size}_documents"
            ] = counter.count


        # ------------------------------------------------
        # QUERY COUNT FOR A SINGLE JOB READ
        # ------------------------------------------------

        with QueryCounter() as counter:

            client.get(
                f"/api/v1/document-jobs/{job_ids[0]}"
            )

        query_counts[
            "job_status"
        ] = counter.count


        with QueryCounter() as counter:

            client.post(
                "/api/v1/document-jobs",
                files={
                    "file": (
                        f"{RUN_MARKER}-q.jpg",
                        image_bytes,
                        "image/jpeg",
                    ),
                },
            )

        query_counts[
            "job_create"
        ] = counter.count


    return {
        "create_job":
            summarize(
                create_ms
            ),

        "job_status":
            summarize(
                status_ms
            ),

        "create_batch":
            summarize(
                batch_create_ms
            ),

        "batch_status":
            summarize(
                batch_status_ms
            ),

        "query_counts":
            query_counts,

        "batch_sizes_measured":
            [3, 12],
    }


# ==========================================================
# PART 2: DOCUMENT PROCESSING DURATION
# ==========================================================

class StubExtraction:

    """
    The same stub as the Phase 9.1 local baseline: replaces
    only the network call, so every validator still runs its
    real code and the OCR figure stays real.
    """

    def extract(
        self,
        ocr_lines,
    ):

        from backend.app.domain.schemas import (
            DocumentExtraction,
        )

        empty = {
            "value": None,
            "source_line_ids": [],
        }

        return (
            DocumentExtraction
            .model_validate(
                {
                    "document_type": "unknown",
                    "full_name": dict(empty),
                    "licence_number": dict(empty),
                    "id_number": dict(empty),
                    "expiry_date": dict(empty),
                    "date_of_birth": dict(empty),
                    "issue_date": dict(empty),
                    "issuer": dict(empty),
                }
            )
        )


def measure_worker(
    documents: list[Path],
) -> dict:

    """
    How long a worker takes per document, cold and warm.

    Cold is the first job in the process and includes the OCR
    model load. It is reported on its own, because averaging it
    in would hide the cost of a restart.
    """

    from backend.app.services.pipeline_service import (
        DocumentPipelineService,
    )

    print(
        "Constructing the pipeline "
        "(OCR model load, once)..."
    )

    construction_started = (
        time.perf_counter()
    )

    pipeline = (
        DocumentPipelineService()
    )

    construction_ms = (
        (
            time.perf_counter()
            - construction_started
        )
        * 1000.0
    )

    pipeline.extraction_service = (
        StubExtraction()
    )

    print(
        f"  ready in {construction_ms / 1000.0:.1f}s"
    )


    per_stage: dict[str, list[float]] = {}
    totals: list[float] = []
    runs: list[dict] = []


    for position, path in enumerate(
        documents,
        start=1,
    ):

        print(
            f"  [{position}/{len(documents)}] "
            f"{path.parent.name}/{path.name}",
            end="",
            flush=True,
        )

        timer = (
            StageTimer()
        )

        started = (
            time.perf_counter()
        )

        with timer.stage(
            "read"
        ):
            path.read_bytes()

        pipeline.process(
            str(
                path
            ),
            timer=timer,
        )

        elapsed = (
            (
                time.perf_counter()
                - started
            )
            * 1000.0
        )

        for name, value in timer.durations().items():
            per_stage.setdefault(
                name,
                [],
            ).append(
                value
            )

        totals.append(
            elapsed
        )

        runs.append(
            {
                "document":
                    f"{path.parent.name}/{path.name}",

                "total_ms":
                    round(
                        elapsed,
                        1,
                    ),

                "stages":
                    timer.durations(),
            }
        )

        print(
            f"  {elapsed / 1000.0:.2f}s"
        )


    # The first document in the process is cold only in the
    # sense that caches are unwarmed; the model load is
    # measured separately above and is not inside it.
    cold = (
        totals[0]
        if totals
        else None
    )

    warm = totals[1:]


    return {
        "pipeline_construction_ms":
            round(
                construction_ms,
                1,
            ),

        "cold_first_document_ms":
            round(
                cold,
                1,
            )
            if cold is not None
            else None,

        "cold_including_construction_ms":
            round(
                construction_ms + cold,
                1,
            )
            if cold is not None
            else None,

        "warm":
            summarize(
                warm
            ),

        "all_documents":
            summarize(
                totals
            ),

        "stages":
            {
                name: summarize(
                    values
                )
                for name, values in per_stage.items()
            },

        "runs":
            runs,
    }


# ==========================================================
# CLEANUP
# ==========================================================

def cleanup() -> dict:

    """
    Remove the job rows and pending uploads this run created.

    A performance script that leaves a hundred queued jobs
    behind would poison the next measurement and the job
    suite's quiet-queue precondition.
    """

    from sqlalchemy import delete

    from database.database import (
        SessionLocal,
    )

    from database.models import (
        DocumentJobModel,
    )

    from backend.app.services.job_service import (
        JobService,
    )

    service = (
        JobService()
    )

    with SessionLocal.begin() as session:

        rows = (
            session.execute(
                delete(
                    DocumentJobModel
                )
                .where(
                    DocumentJobModel
                    .original_filename
                    .like(
                        f"{RUN_MARKER}%"
                    )
                )
            ).rowcount
        )


    removed_files = 0

    for name in service.orphaned_sources():

        try:
            if service.source_store.delete_pending(
                name
            ):
                removed_files += 1

        except Exception:      # noqa: BLE001
            pass


    return {
        "rows_removed": rows,
        "pending_files_removed": removed_files,
    }


# ==========================================================
# REPORT
# ==========================================================

def render(
    report: dict,
) -> None:

    api = report["api"]
    worker = report.get(
        "worker"
    )

    print()
    print("=" * 76)
    print(
        "PHASE 9.5 - ASYNC PERFORMANCE"
    )
    print("=" * 76)

    print()
    print(
        "USER-PERCEIVED API RESPONSIVENESS"
    )
    print("-" * 76)
    print(
        "  What changed. No OCR runs inside these "
        "requests."
    )
    print()
    print(
        f"  {'ENDPOINT':<34}{'MIN':>9}{'MEDIAN':>10}"
        f"{'P95':>10}{'MAX':>10}"
    )
    print("-" * 76)

    for label, key in (
        ("POST /document-jobs", "create_job"),
        ("GET  /document-jobs/{id}", "job_status"),
        ("POST /document-batches", "create_batch"),
        ("GET  /document-batches/{id}", "batch_status"),
    ):

        stat = api[key]

        if not stat.get(
            "count"
        ):
            continue

        p95 = (
            f"{stat['p95_ms']:.0f}ms"
            if stat.get(
                "p95_ms"
            ) is not None
            else "n/a"
        )

        print(
            f"  {label:<34}"
            f"{stat['min_ms']:>7.0f}ms"
            f"{stat['median_ms']:>8.0f}ms"
            f"{p95:>10}"
            f"{stat['max_ms']:>8.0f}ms"
        )

    print("-" * 76)
    print()
    print(
        "  Query counts (N+1 check):"
    )

    for name, count in sorted(
        api["query_counts"].items()
    ):
        print(
            f"    {name:<34}{count} statement(s)"
        )


    if worker:

        print()
        print(
            "DOCUMENT PROCESSING DURATION"
        )
        print("-" * 76)
        print(
            "  What did NOT change. The same OCR pass on "
            "the same CPU."
        )
        print()
        print(
            "  OCR model load (once per process)   "
            f"{worker['pipeline_construction_ms'] / 1000.0:.1f}s"
        )
        print(
            "  First document after load          "
            f"{worker['cold_first_document_ms'] / 1000.0:.1f}s"
        )
        print(
            "  Cold start total                   "
            f"{worker['cold_including_construction_ms'] / 1000.0:.1f}s"
        )

        warm = worker["warm"]

        if warm.get(
            "count"
        ):
            print(
                "  Warm documents                     "
                f"median {warm['median_ms'] / 1000.0:.1f}s "
                f"over {warm['count']} document(s) "
                f"(min {warm['min_ms'] / 1000.0:.1f}s, "
                f"max {warm['max_ms'] / 1000.0:.1f}s)"
            )

        print()
        print(
            f"  {'STAGE':<22}{'MIN':>10}{'MEDIAN':>10}"
            f"{'MAX':>10}{'SHARE':>9}"
        )
        print("-" * 76)

        median_total = (
            worker["all_documents"]["median_ms"]
        )

        for name, stat in worker["stages"].items():

            share = (
                stat["median_ms"]
                / median_total
                * 100.0
                if median_total
                else 0.0
            )

            print(
                f"  {name:<22}"
                f"{stat['min_ms']:>8.0f}ms"
                f"{stat['median_ms']:>8.0f}ms"
                f"{stat['max_ms']:>8.0f}ms"
                f"{share:>8.1f}%"
            )

        print("-" * 76)

        if warm.get(
            "p95_ms"
        ) is None and warm.get(
            "count"
        ):
            print()
            print(
                f"  p95: {warm['p95_note']}"
            )


    print()
    print(
        "THE HONEST COMPARISON"
    )
    print("-" * 76)
    print(
        "  Before: the browser waited the full "
        "processing duration inside one HTTP request."
    )
    print(
        "  After:  the browser waits "
        f"{api['create_job']['median_ms']:.0f}ms for an "
        "answer, and the processing happens in a worker."
    )
    print(
        "  The processing duration itself is unchanged, "
        "and is expected to be:"
    )
    print(
        "  async moved the work out of the request, it "
        "did not make OCR faster."
    )
    print()


# ==========================================================
# MAIN
# ==========================================================

def main() -> int:

    parser = (
        argparse.ArgumentParser(
            description=(
                "Measure async API responsiveness and "
                "document processing duration "
                "separately."
            )
        )
    )

    parser.add_argument(
        "--api-samples",
        type=int,
        default=40,
        help=(
            "How many job-creation and status requests "
            "to time. Default 40, which is enough for a "
            "real p95."
        ),
    )

    parser.add_argument(
        "--documents",
        type=int,
        default=6,
        help=(
            "How many documents to process. Matches the "
            "Phase 9.1 sample size by default so the "
            "comparison is like for like. 0 skips the "
            "worker measurement."
        ),
    )

    parser.add_argument(
        "--save",
        action="store_true",
        help=(
            "Write the report to output/performance/."
        ),
    )

    arguments = (
        parser.parse_args()
    )

    report: dict = {
        "measured_at":
            datetime.now(
                timezone.utc
            ).isoformat(
                timespec="seconds"
            ),

        "methodology":
            (
                "Same StageTimer, document selection and "
                "p95 rule as the Phase 9.1 baseline. "
                "Groq stubbed; OCR real."
            ),
    }


    try:

        report["api"] = (
            measure_api(
                arguments.api_samples
            )
        )


        if arguments.documents > 0:

            documents = (
                collect_documents(
                    arguments.documents
                )
            )

            report["worker"] = (
                measure_worker(
                    documents
                )
            )


    finally:

        report["cleanup"] = (
            cleanup()
        )


    render(
        report
    )

    print(
        "  cleanup: removed "
        f"{report['cleanup']['rows_removed']} job row(s) "
        "and "
        f"{report['cleanup']['pending_files_removed']} "
        "pending file(s)"
    )
    print()


    if arguments.save:

        OUTPUT_ROOT.mkdir(
            parents=True,
            exist_ok=True,
        )

        stamp = (
            report["measured_at"]
            .replace(":", "")
            .replace("-", "")
        )

        destination = (
            OUTPUT_ROOT
            / f"phase95_async_{stamp}.json"
        )

        destination.write_text(
            json.dumps(
                report,
                indent=2,
            ),
            encoding="utf-8",
        )

        print(
            f"  saved to {destination}"
        )
        print()


    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
