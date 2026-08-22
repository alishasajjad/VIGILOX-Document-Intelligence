# ==========================================================
# PROJECT ROOT BOOTSTRAP
# PHASE 8.2
# ==========================================================
#
# This block exists so the script can be run directly:
#
#     python scripts\<area>\<script>.py
#
# Direct execution sets sys.path[0] to the script's OWN
# directory, so the backend and database packages would not
# be importable and the script would fail with:
#
#     ModuleNotFoundError: No module named 'backend'
#
# The canonical invocation is module form, which resolves the
# project root itself and needs no bootstrap:
#
#     python -m scripts.<area>.<script>
#
# Both forms are supported. This is the single sanctioned
# bootstrap pattern for scripts/ and it is documented in
# scripts/README.md. It is deliberately absent from
# backend/, database/ and tests/, which must never manipulate
# sys.path.
# ==========================================================

import sys

from pathlib import Path

PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[2]
)

if str(PROJECT_ROOT) not in sys.path:

    sys.path.insert(
        0,
        str(
            PROJECT_ROOT
        ),
    )


import argparse
import json
import time

from datetime import date
from pathlib import Path

import groq

from dotenv import load_dotenv

from backend.app.services.pipeline_service import (  # noqa: E402
    DocumentPipelineService,
)


# ==========================================================
# ENVIRONMENT
# ==========================================================

load_dotenv()


# ==========================================================
# CONFIGURATION
# ==========================================================

GROUND_TRUTH_PATH = Path(
    "evaluation/ground_truth/labels.jsonl"
)

RESULTS_DIR = Path(
    "evaluation/results"
)

PREDICTIONS_PATH = (
    RESULTS_DIR
    / "predictions.jsonl"
)


# Fixed reference date for reproducible
# expiry/date evaluation.

EVALUATION_REFERENCE_DATE = date(
    2026,
    8,
    18,
)


DEFAULT_DELAY_SECONDS = 10

RATE_LIMIT_WAIT_SECONDS = 65

MAX_ATTEMPTS_PER_SAMPLE = 3


# ==========================================================
# JSONL HELPERS
# ==========================================================

def load_jsonl(
    path: Path,
) -> list[dict]:

    records = []


    if not path.exists():

        return records


    with path.open(
        "r",
        encoding="utf-8",
    ) as file:

        for line_number, line in enumerate(
            file,
            start=1,
        ):

            line = line.strip()


            if not line:

                continue


            try:

                records.append(
                    json.loads(
                        line
                    )
                )

            except json.JSONDecodeError as exc:

                raise ValueError(
                    f"Invalid JSON in "
                    f"{path} at line "
                    f"{line_number}."
                ) from exc


    return records


def append_jsonl(
    path: Path,
    record: dict,
):

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


    with path.open(
        "a",
        encoding="utf-8",
    ) as file:

        file.write(
            json.dumps(
                record,
                ensure_ascii=False,
            )
            + "\n"
        )

        file.flush()


# ==========================================================
# COMPLETED SAMPLE IDS
# ==========================================================

def get_completed_sample_ids(
    predictions: list[dict],
) -> set[str]:

    completed = set()


    for prediction in predictions:

        if (
            prediction.get("status")
            == "success"
        ):

            sample_id = (
                prediction.get(
                    "sample_id"
                )
            )


            if sample_id:

                completed.add(
                    sample_id
                )


    return completed


# ==========================================================
# SAMPLE SELECTION
# ==========================================================

def select_ground_truth_records(
    ground_truth_records: list[dict],
    requested_sample_ids: list[str] | None,
) -> list[dict]:

    # Normal mode:
    # use the complete dataset.

    if not requested_sample_ids:

        return ground_truth_records


    records_by_id = {

        record["sample_id"]:
            record

        for record
        in ground_truth_records
    }


    unknown_sample_ids = [

        sample_id

        for sample_id
        in requested_sample_ids

        if sample_id
        not in records_by_id
    ]


    if unknown_sample_ids:

        raise ValueError(
            "Unknown sample ID(s): "
            + ", ".join(
                unknown_sample_ids
            )
        )


    # Preserve the exact order supplied
    # on the command line.

    selected_records = [

        records_by_id[
            sample_id
        ]

        for sample_id
        in requested_sample_ids
    ]


    return selected_records


# ==========================================================
# TRANSIENT ERROR DETECTION
# ==========================================================

# ==========================================================
# HOW LONG TO WAIT AFTER A 429
# PHASE 12.17
# ==========================================================
#
# Groq states the answer in the error, and the runner used to
# ignore it.
#
# The flat 65-second wait was sized for a TOKENS PER MINUTE
# limit, where a minute genuinely clears it. The daily limit
# behaves differently: the tokens-per-day window frees at
# whatever rate they were consumed 24 hours earlier, and a
# real refusal reads
#
#     Limit 200000, Used 196625, Requested 4512.
#     Please try again in 8m11.183999999s
#
# Three attempts at 65 seconds covers 195 seconds of an
# eight-minute wait, so every attempt failed and seven
# documents were recorded as failures with plenty of allowance
# about to free up. Measured during the Phase 12 run: the
# window was releasing roughly 240 tokens a minute, so the
# provider's estimate was accurate and the runner's was not.
#
# NOTHING ABOUT EXTRACTION CHANGES HERE. Not the prompt, not
# the model, not the schema, not the field handling, not the
# number of extraction attempts. A 429 is a quota signal, and
# responding to one by touching extraction would corrupt the
# comparison the run exists to make. This changes only how
# long the script waits before asking the same question again.
# ==========================================================

RATE_LIMIT_WAIT_CEILING_SECONDS = 900


def parse_retry_delay(
    exc: Exception,
) -> float | None:

    """
    The delay the provider asked for, in seconds.

    Returns None when the error carries no hint, in which case
    the caller falls back to RATE_LIMIT_WAIT_SECONDS.

    Bounded by RATE_LIMIT_WAIT_CEILING_SECONDS so a
    malformed or hostile value cannot park the run for hours.
    """

    import re

    text = str(
        exc
    )

    match = re.search(
        r"try again in\s+"
        r"(?:(\d+)m)?"
        r"([\d.]+)s",
        text,
        re.IGNORECASE,
    )

    if not match:
        return None

    minutes = int(
        match.group(
            1
        )
        or 0
    )

    seconds = float(
        match.group(
            2
        )
    )

    total = minutes * 60 + seconds

    # A few seconds of margin: waiting exactly the stated time
    # lands on the boundary and is refused again.
    total += 5

    return min(
        total,
        float(
            RATE_LIMIT_WAIT_CEILING_SECONDS
        ),
    )


def is_rate_limit_error(
    exc: Exception,
) -> bool:

    message = str(
        exc
    ).lower()


    rate_limit_markers = [
        "rate_limit",
        "rate limit",
        "tokens per minute",
        "tpm",
        "error code: 429",
        "error code: 413",
    ]


    return any(
        marker in message
        for marker
        in rate_limit_markers
    )


# ==========================================================
# PROCESS SINGLE SAMPLE
# ==========================================================

def process_sample(
    pipeline: DocumentPipelineService,
    ground_truth: dict,
) -> dict:

    sample_id = (
        ground_truth[
            "sample_id"
        ]
    )


    image_path = Path(
        ground_truth[
            "image_path"
        ]
    )


    if not image_path.exists():

        raise FileNotFoundError(
            f"Image does not exist: "
            f"{image_path}"
        )


    started_at = (
        time.perf_counter()
    )


    pipeline_result = (
        pipeline.process(
            str(
                image_path
            ),
            reference_date=(
                EVALUATION_REFERENCE_DATE
            ),
        )
    )


    runtime_seconds = (
        time.perf_counter()
        - started_at
    )


    return {

        "sample_id":
            sample_id,

        "image_path":
            ground_truth[
                "image_path"
            ],

        "quality":
            ground_truth[
                "quality"
            ],

        "ground_truth": {

            "document_type":
                ground_truth[
                    "document_type"
                ],

            "fields":
                ground_truth[
                    "fields"
                ],
        },

        "prediction":
            pipeline_result,

        "runtime_seconds":
            round(
                runtime_seconds,
                4,
            ),

        "reference_date":
            EVALUATION_REFERENCE_DATE
            .isoformat(),

        "status":
            "success",

        "error":
            None,
    }


# ==========================================================
# MAIN EVALUATION
# ==========================================================

def run_evaluation(
    limit: int | None,
    delay_seconds: int,
    reset: bool,
    requested_sample_ids: list[str] | None,
):

    RESULTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )


    # ======================================================
    # RESET PREVIOUS PREDICTIONS
    # ======================================================

    if (
        reset
        and PREDICTIONS_PATH.exists()
    ):

        PREDICTIONS_PATH.unlink()


        print(
            "Previous predictions removed."
        )


    # ======================================================
    # LOAD GROUND TRUTH
    # ======================================================

    ground_truth_records = (
        load_jsonl(
            GROUND_TRUTH_PATH
        )
    )


    if not ground_truth_records:

        raise RuntimeError(
            "Ground truth dataset is empty."
        )


    # ======================================================
    # OPTIONAL SAMPLE-ID SELECTION
    # ======================================================

    selected_records = (
        select_ground_truth_records(
            ground_truth_records,
            requested_sample_ids,
        )
    )


    # ======================================================
    # LOAD EXISTING RESULTS FOR RESUME
    # ======================================================

    existing_predictions = (
        load_jsonl(
            PREDICTIONS_PATH
        )
    )


    completed_sample_ids = (
        get_completed_sample_ids(
            existing_predictions
        )
    )


    pending_records = [

        record

        for record
        in selected_records

        if record[
            "sample_id"
        ]
        not in completed_sample_ids
    ]


    if limit is not None:

        pending_records = (
            pending_records[
                :limit
            ]
        )


    # ======================================================
    # SUMMARY
    # ======================================================

    print()
    print(
        "=" * 70
    )

    print(
        "PHASE 6D — "
        "DOCUMENT EVALUATION RUNNER"
    )

    print(
        "=" * 70
    )


    print(
        "Ground truth documents:",
        len(
            ground_truth_records
        ),
    )


    print(
        "Already completed:",
        len(
            completed_sample_ids
        ),
    )


    if requested_sample_ids:

        print(
            "Requested sample IDs:",
            ", ".join(
                requested_sample_ids
            ),
        )


    print(
        "Selected for this run:",
        len(
            pending_records
        ),
    )


    print(
        "Reference date:",
        EVALUATION_REFERENCE_DATE,
    )


    print(
        "Prediction file:",
        PREDICTIONS_PATH,
    )


    if not pending_records:

        print()
        print(
            "[INFO] No pending "
            "documents to evaluate."
        )

        return


    # ======================================================
    # INITIALIZE PIPELINE ONCE
    # ======================================================

    print()
    print(
        "Initializing document pipeline..."
    )


    pipeline = (
        DocumentPipelineService()
    )


    print(
        "Pipeline initialization: OK"
    )


    successful_count = 0
    failed_count = 0


    # ======================================================
    # PROCESS DOCUMENTS
    # ======================================================

    for index, ground_truth in enumerate(
        pending_records,
        start=1,
    ):

        sample_id = (
            ground_truth[
                "sample_id"
            ]
        )


        print()
        print(
            "-" * 70
        )


        print(
            f"[{index}/"
            f"{len(pending_records)}] "
            f"{sample_id}"
        )


        print(
            ground_truth[
                "image_path"
            ]
        )


        success = False

        final_error = None


        for attempt in range(
            1,
            MAX_ATTEMPTS_PER_SAMPLE
            + 1,
        ):

            try:

                print(
                    f"Attempt "
                    f"{attempt}/"
                    f"{MAX_ATTEMPTS_PER_SAMPLE}"
                )


                prediction_record = (
                    process_sample(
                        pipeline,
                        ground_truth,
                    )
                )


                append_jsonl(
                    PREDICTIONS_PATH,
                    prediction_record,
                )


                prediction = (
                    prediction_record[
                        "prediction"
                    ]
                )


                predicted_type = (
                    prediction[
                        "extraction"
                    ][
                        "document_type"
                    ]
                )


                review = (
                    prediction[
                        "review_decision"
                    ]
                )


                print(
                    "Predicted type:",
                    predicted_type,
                )


                print(
                    "Review decision:",
                    review[
                        "decision"
                    ],
                )


                print(
                    "Priority:",
                    review[
                        "priority"
                    ],
                )


                print(
                    "Runtime:",
                    prediction_record[
                        "runtime_seconds"
                    ],
                    "seconds",
                )


                print(
                    "[OK]",
                    sample_id,
                )


                successful_count += 1

                success = True

                break


            except groq.APIStatusError as exc:

                print(
                    "[GROQ API ERROR]",
                    repr(
                        exc
                    ),
                )


                final_error = exc


                if (
                    is_rate_limit_error(
                        exc
                    )
                    and attempt
                    < MAX_ATTEMPTS_PER_SAMPLE
                ):

                    print(
                        "Rate limit detected."
                    )


                    # The provider's own estimate when it
                    # gives one, because a flat wait sized
                    # for a per-minute limit does not cover a
                    # per-day one.
                    hinted = parse_retry_delay(
                        exc
                    )

                    delay = (
                        hinted
                        if hinted is not None
                        else float(
                            RATE_LIMIT_WAIT_SECONDS
                        )
                    )


                    print(
                        "Waiting",
                        round(
                            delay,
                            1,
                        ),
                        "seconds before retry"
                        + (
                            " (the provider asked for this)"
                            if hinted is not None
                            else " (no hint given)"
                        )
                        + "..."
                    )


                    time.sleep(
                        delay
                    )


                    continue


                break


            except Exception as exc:

                print(
                    "[EVALUATION ERROR]",
                    repr(
                        exc
                    ),
                )


                final_error = exc

                break


        # ==================================================
        # SAVE FAILURE RECORD
        # ==================================================

        if not success:

            failed_count += 1


            failure_record = {

                "sample_id":
                    sample_id,

                "image_path":
                    ground_truth[
                        "image_path"
                    ],

                "quality":
                    ground_truth[
                        "quality"
                    ],

                "ground_truth": {

                    "document_type":
                        ground_truth[
                            "document_type"
                        ],

                    "fields":
                        ground_truth[
                            "fields"
                        ],
                },

                "prediction":
                    None,

                "runtime_seconds":
                    None,

                "reference_date":
                    EVALUATION_REFERENCE_DATE
                    .isoformat(),

                "status":
                    "failed",

                "error":
                    repr(
                        final_error
                    ),
            }


            append_jsonl(
                PREDICTIONS_PATH,
                failure_record,
            )


            print(
                "[FAILED]",
                sample_id,
            )


        # ==================================================
        # INTER-REQUEST DELAY
        # ==================================================

        if (
            index
            < len(
                pending_records
            )
        ):

            print(
                f"Waiting "
                f"{delay_seconds} "
                f"seconds..."
            )


            time.sleep(
                delay_seconds
            )


    # ======================================================
    # FINAL SUMMARY
    # ======================================================

    all_predictions = (
        load_jsonl(
            PREDICTIONS_PATH
        )
    )


    unique_successful_ids = (
        get_completed_sample_ids(
            all_predictions
        )
    )


    print()
    print(
        "=" * 70
    )

    print(
        "EVALUATION RUN SUMMARY"
    )

    print(
        "=" * 70
    )


    print(
        "Successful this run:",
        successful_count,
    )


    print(
        "Failed this run:",
        failed_count,
    )


    print(
        "Total successful samples:",
        len(
            unique_successful_ids
        ),
    )


    print(
        "Target samples:",
        len(
            ground_truth_records
        ),
    )


    print(
        "Results:",
        PREDICTIONS_PATH,
    )


    print(
        "=" * 70
    )


# ==========================================================
# COMMAND-LINE INTERFACE
# ==========================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Run the VIGILOX Phase 6D "
            "evaluation dataset through "
            "the complete document pipeline."
        )
    )


    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "Maximum number of pending "
            "documents to process."
        ),
    )


    parser.add_argument(
        "--delay",
        type=int,
        default=(
            DEFAULT_DELAY_SECONDS
        ),
        help=(
            "Delay in seconds between "
            "documents."
        ),
    )


    parser.add_argument(
        "--reset",
        action="store_true",
        help=(
            "Delete existing predictions "
            "before running."
        ),
    )


    parser.add_argument(
        "--sample-id",
        nargs="+",
        default=None,
        help=(
            "Process only the specified "
            "sample IDs. Example: "
            "--sample-id sia_004 "
            "guard_002 id_002"
        ),
    )


    args = parser.parse_args()


    run_evaluation(
        limit=args.limit,
        delay_seconds=args.delay,
        reset=args.reset,
        requested_sample_ids=(
            args.sample_id
        ),
    )


if __name__ == "__main__":

    main()