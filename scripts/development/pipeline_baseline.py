import argparse
import json
import statistics
import sys
import time

from datetime import (
    datetime,
    timezone,
)
from pathlib import Path


# ==========================================================
# PIPELINE PERFORMANCE BASELINE
# PHASE 9.1
# ==========================================================
#
# WHY THIS EXISTS
# ----------------------------------------------------------
#
# Phase 9 replaces a synchronous analyze endpoint with a
# durable job queue and a worker process. That is a real
# amount of new machinery -- a table, a claim protocol, a
# lease, a retry policy, a second process to deploy and
# monitor -- and it is only worth building if the thing it
# is hiding from the user is genuinely slow.
#
# So this measures first. Not to justify a decision already
# made, but because "OCR is probably the slow part" and "OCR
# is 78% of a 4.1 second median" are different kinds of
# statement, and only the second one tells you whether
# concurrency should be bounded by OCR or by the provider.
#
# It also gives Phase 9.5 something to compare against. A
# claim that async processing made anything faster is not
# checkable without a before.
#
#
# WHAT IT MEASURES
# ----------------------------------------------------------
#
#     read          reading the source file off disk
#     ocr           PaddleOCR, including preprocessing
#     extraction    the Groq call
#     evidence      evidence validation
#     confidence    field confidence
#     dates         date and expiry validation
#     anomalies     document anomaly validation
#     review        the machine review decision
#     persistence   the database write and the managed
#                   storage copy, together, because
#                   save_processed_document does both
#
#
# HONESTY ABOUT PERCENTILES
# ----------------------------------------------------------
#
# p95 from five samples is not a p95, it is the largest
# number with a statistical hat on. This script reports
# minimum, median and maximum always, and reports p95 only
# when the sample is at least 20 -- otherwise it says so
# explicitly rather than printing a figure that invites
# being quoted.
#
#
# COST
# ----------------------------------------------------------
#
# Every document costs one real Groq call. The default sample
# is deliberately small. --no-llm skips extraction entirely
# and measures the local pipeline for free, which is the right
# mode for iterating on OCR or on the validators.
#
#
# RESIDUE
# ----------------------------------------------------------
#
# --persist writes real rows and real stored documents, then
# deletes them through the ordinary deletion service so the
# measurement leaves nothing behind. Without --persist nothing
# touches the database.
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

from backend.app.core.timing import (       # noqa: E402
    StageTimer,
)


# ExtractionService requires GROQ_API_KEY at construction,
# even when --no-llm will replace its network call, so the
# environment is loaded before the pipeline is built.
load_dotenv(
    PROJECT_ROOT / ".env"
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


# Reporting a p95 below this sample size would be theatre.
MINIMUM_FOR_P95 = 20


STAGE_ORDER = (
    "read",
    "ocr",
    "extraction",
    "evidence",
    "confidence",
    "dates",
    "anomalies",
    "review_decision",
    "persistence",
)


# ==========================================================
# SAMPLE SELECTION
# ==========================================================

def collect_documents(
    limit: int,
) -> list[Path]:

    if not IMAGES_ROOT.exists():

        raise SystemExit(
            (
                "No evaluation images at "
                f"{IMAGES_ROOT}. This script measures "
                "the pipeline against the benchmark "
                "set."
            )
        )


    found: list[Path] = []


    # Round-robin across document types rather than taking
    # the first N, which would measure guard licences only
    # and then be quoted as a pipeline figure.
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
            "No images found."
        )


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
# STATISTICS
# ==========================================================

def summarize(
    samples: list[float],
) -> dict:

    if not samples:

        return {
            "count": 0,
        }


    ordered = sorted(
        samples
    )

    result = {
        "count":
            len(ordered),

        "min_ms":
            round(
                ordered[0],
                1,
            ),

        "median_ms":
            round(
                statistics.median(
                    ordered
                ),
                1,
            ),

        "max_ms":
            round(
                ordered[-1],
                1,
            ),

        "mean_ms":
            round(
                statistics.fmean(
                    ordered
                ),
                1,
            ),
    }


    if len(ordered) >= MINIMUM_FOR_P95:

        result["p95_ms"] = (
            round(
                statistics.quantiles(
                    ordered,
                    n=20,
                )[18],
                1,
            )
        )

    else:

        result["p95_ms"] = None

        result["p95_note"] = (
            "sample of "
            f"{len(ordered)} is below "
            f"{MINIMUM_FOR_P95}; a p95 from this "
            "many runs would not mean anything"
        )


    return result


# ==========================================================
# MEASUREMENT
# ==========================================================

def measure(
    documents: list[Path],
    use_llm: bool,
    persist: bool,
) -> dict:

    from backend.app.services.pipeline_service import (
        DocumentPipelineService,
    )

    print(
        "Constructing the pipeline "
        "(PaddleOCR model load)..."
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

    print(
        "  ready in "
        f"{construction_ms / 1000.0:.1f}s"
    )


    persistence = None
    deletion = None


    if persist:

        from backend.app.services.persistence_service import (
            PersistenceService,
        )
        from backend.app.services.document_deletion_service import (
            DocumentDeletionService,
        )

        persistence = (
            PersistenceService()
        )

        deletion = (
            DocumentDeletionService()
        )


    if not use_llm:

        # Replace only the network call. Everything the
        # extraction feeds -- evidence, confidence, dates,
        # anomalies, the review decision -- still runs on a
        # real object, so those measurements stay real.
        pipeline.extraction_service = (
            _StubExtraction(
                pipeline.extraction_service
            )
        )


    per_stage: dict[str, list[float]] = {
        name: []
        for name in STAGE_ORDER
    }

    totals: list[float] = []

    runs: list[dict] = []

    failures: list[dict] = []


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


        try:

            with timer.stage(
                "read"
            ):
                source_bytes = (
                    path.read_bytes()
                )


            result = (
                pipeline.process(
                    str(
                        path
                    ),
                    timer=timer,
                )
            )


            if persist and persistence is not None:

                with timer.stage(
                    "persistence"
                ):

                    stored = (
                        persistence
                        .save_processed_document(
                            original_filename=(
                                path.name
                            ),

                            content_type=(
                                "image/jpeg"
                            ),

                            pipeline_result=(
                                result
                            ),

                            source_path=(
                                str(
                                    path
                                )
                            ),
                        )
                    )


                # Delete straight away, through the real
                # service, so a performance run never leaves
                # rows or stored documents behind.
                if deletion is not None:

                    deletion.delete_document(
                        stored[
                            "document_id"
                        ]
                    )


            elapsed_ms = (
                (
                    time.perf_counter()
                    - started
                )
                * 1000.0
            )

            durations = (
                timer.durations()
            )


            for name, value in durations.items():

                if name in per_stage:
                    per_stage[name].append(
                        value
                    )


            totals.append(
                elapsed_ms
            )

            runs.append(
                {
                    "document":
                        f"{path.parent.name}/{path.name}",

                    "bytes":
                        len(
                            source_bytes
                        ),

                    "total_ms":
                        round(
                            elapsed_ms,
                            1,
                        ),

                    "stages":
                        durations,
                }
            )

            print(
                f"  {elapsed_ms / 1000.0:.2f}s"
            )


        except Exception as error:      # noqa: BLE001

            # A provider refusal is a fact about the run, not
            # a reason to lose the samples already collected.
            print(
                "  FAILED "
                f"{type(error).__name__}"
            )

            failures.append(
                {
                    "document":
                        f"{path.parent.name}/{path.name}",

                    "error_type":
                        type(
                            error
                        ).__name__,

                    "error":
                        str(
                            error
                        )[:300],
                }
            )


    return {
        "measured_at":
            datetime.now(
                timezone.utc
            ).isoformat(
                timespec="seconds"
            ),

        "mode":
            (
                "full pipeline with real Groq"
                if use_llm
                else "local pipeline, Groq stubbed"
            ),

        "persistence_measured":
            persist,

        "pipeline_construction_ms":
            round(
                construction_ms,
                1,
            ),

        "documents_attempted":
            len(
                documents
            ),

        "documents_measured":
            len(
                totals
            ),

        "failures":
            failures,

        "total":
            summarize(
                totals
            ),

        "stages":
            {
                name: summarize(
                    per_stage[name]
                )
                for name in STAGE_ORDER
                if per_stage[name]
            },

        "runs":
            runs,
    }


class _StubExtraction:

    """
    Stands in for the Groq call so the local pipeline can be
    measured without spending quota.

    It delegates to the real service for everything except
    the network call, and returns a structurally valid
    extraction so that every downstream validator still runs
    against a real object. The extraction figure in a stubbed
    run is therefore meaningless and is reported as stubbed
    rather than as a measurement.
    """

    def __init__(
        self,
        real,
    ) -> None:

        self._real = real


    def extract(
        self,
        ocr_lines,
    ):

        from backend.app.domain.schemas import (
            DocumentExtraction,
        )

        # The smallest extraction the schema accepts: every
        # field present, every value absent. Evidence
        # validation, confidence, date validation, anomaly
        # detection and the review decision all still run
        # their real code against a real object, so those
        # measurements stay honest -- only the network call
        # is gone.
        empty = {
            "value": None,
            "source_line_ids": [],
        }

        return (
            DocumentExtraction
            .model_validate(
                {
                    "document_type":
                        "unknown",

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


# ==========================================================
# REPORT
# ==========================================================

def render(
    report: dict,
) -> None:

    print()
    print("=" * 76)
    print(
        "PIPELINE PERFORMANCE BASELINE - PHASE 9.1"
    )
    print("=" * 76)
    print()
    print(
        f"  mode                  {report['mode']}"
    )
    print(
        "  persistence measured  "
        f"{report['persistence_measured']}"
    )
    print(
        "  pipeline construction "
        f"{report['pipeline_construction_ms'] / 1000.0:.1f}s "
        "(PaddleOCR model load, once per process)"
    )
    print(
        "  documents measured    "
        f"{report['documents_measured']} of "
        f"{report['documents_attempted']}"
    )


    if report["failures"]:

        print()
        print(
            f"  {len(report['failures'])} failure(s):"
        )

        for failure in report["failures"]:
            print(
                f"    {failure['document']}  "
                f"{failure['error_type']}"
            )


    total = report["total"]


    if not total.get(
        "count"
    ):

        print()
        print(
            "  Nothing was measured."
        )
        return


    print()
    print("-" * 76)
    print(
        f"  {'STAGE':<22}"
        f"{'MIN':>10}"
        f"{'MEDIAN':>10}"
        f"{'MAX':>10}"
        f"{'SHARE':>9}"
    )
    print("-" * 76)


    median_total = (
        total["median_ms"]
    )


    for name in STAGE_ORDER:

        stage = report["stages"].get(
            name
        )

        if not stage:
            continue


        share = (
            (
                stage["median_ms"]
                / median_total
                * 100.0
            )
            if median_total
            else 0.0
        )

        print(
            f"  {name:<22}"
            f"{stage['min_ms']:>9.0f}ms"
            f"{stage['median_ms']:>9.0f}ms"
            f"{stage['max_ms']:>9.0f}ms"
            f"{share:>8.1f}%"
        )


    print("-" * 76)
    print(
        f"  {'END TO END':<22}"
        f"{total['min_ms']:>9.0f}ms"
        f"{total['median_ms']:>9.0f}ms"
        f"{total['max_ms']:>9.0f}ms"
        f"{100.0:>8.1f}%"
    )
    print("-" * 76)


    if total.get(
        "p95_ms"
    ) is None:

        print()
        print(
            f"  p95: {total['p95_note']}"
        )

    else:

        print()
        print(
            "  p95 end to end        "
            f"{total['p95_ms']:.0f}ms"
        )


    print()


# ==========================================================
# MAIN
# ==========================================================

def main() -> int:

    parser = (
        argparse.ArgumentParser(
            description=(
                "Measure where time goes in the "
                "VIGILOX document pipeline."
            )
        )
    )

    parser.add_argument(
        "--documents",
        type=int,
        default=6,
        help=(
            "How many documents to measure. Each one "
            "costs a real Groq call unless --no-llm is "
            "given. Default 6."
        ),
    )

    parser.add_argument(
        "--no-llm",
        action="store_true",
        help=(
            "Stub the Groq call. Measures the local "
            "pipeline for free; the extraction figure "
            "is then meaningless and is labelled as "
            "stubbed."
        ),
    )

    parser.add_argument(
        "--persist",
        action="store_true",
        help=(
            "Also measure the database write and the "
            "managed storage copy. Writes real rows and "
            "deletes them again through the ordinary "
            "deletion service."
        ),
    )

    parser.add_argument(
        "--save",
        action="store_true",
        help=(
            "Write the report to "
            "output/performance/."
        ),
    )

    arguments = (
        parser.parse_args()
    )


    documents = (
        collect_documents(
            arguments.documents
        )
    )


    if not documents:

        print(
            "No documents to measure."
        )
        return 1


    report = (
        measure(
            documents=(
                documents
            ),

            use_llm=(
                not arguments.no_llm
            ),

            persist=(
                arguments.persist
            ),
        )
    )

    render(
        report
    )


    if arguments.save:

        OUTPUT_ROOT.mkdir(
            parents=True,
            exist_ok=True,
        )

        stamp = (
            report["measured_at"]
            .replace(
                ":",
                "",
            )
            .replace(
                "-",
                "",
            )
        )

        suffix = (
            "local"
            if arguments.no_llm
            else "full"
        )

        destination = (
            OUTPUT_ROOT
            / f"baseline_{suffix}_{stamp}.json"
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


    # A run where nothing could be measured is a failure.
    return (
        0
        if report["documents_measured"]
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
