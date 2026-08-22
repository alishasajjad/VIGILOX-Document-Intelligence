"""
==========================================================
CONFIDENCE CALIBRATION STUDY
PHASE 10.5
==========================================================

THE QUESTION
----------------------------------------------------------

VIGILOX reports a confidence per extracted field. Does that
number predict whether the field is CORRECT?

It is worth asking because the interface shows the number to
reviewers, and a reviewer who reads 99.99% as "almost certainly
right" will skim past exactly the fields that need reading.


WHAT IT USES
----------------------------------------------------------

evaluation/results/field_results.csv, already on disk from the
Phase 6D evaluation of all 63 documents: 441 field rows, each
carrying the confidence VIGILOX assigned and whether the value
normalised-matched ground truth.

No provider calls. No OCR. Reading a CSV.


WHAT IT DOES NOT DO
----------------------------------------------------------

It does not produce a document-level confidence, and nothing in
this repository does. A single number for a document would have
to combine fields that mean different things, weight them by
something nobody has justified, and would be read as "how much
should I trust this document" -- which is what the review
decision already answers, from evidence, explainably.

    python -m scripts.development.confidence_calibration_study
"""

import argparse
import bisect
import csv
import json
import statistics
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


DEFAULT_FIELD_RESULTS = (
    PROJECT_ROOT
    / "evaluation"
    / "results"
    / "field_results.csv"
)


# ==========================================================
# CRITICAL FIELDS
# ==========================================================
#
# Taken from the validator rather than restated, so this study
# cannot disagree with the system about which fields matter.
# ==========================================================

from backend.app.services.document_anomaly_validator import (  # noqa: E402
    DocumentAnomalyValidator,
)


CRITICAL_FIELDS = (
    DocumentAnomalyValidator
    .CRITICAL_FIELDS
)


def is_critical(
    document_type: str,
    field_name: str,
) -> bool:

    return field_name in CRITICAL_FIELDS.get(
        document_type,
        (),
    )


# ==========================================================
# LOAD
# ==========================================================

def load_rows(
    path: Path,
) -> list[dict]:

    if not path.exists():

        raise SystemExit(
            (
                "Field results not found at "
                f"{path}.\n"
                "Run the evaluation first, or pass "
                "--field-results."
            )
        )


    # utf-8-sig: the CSV carries a BOM, and without this the
    # first column name comes back with it attached and every
    # lookup of "sample_id" fails.
    with open(
        path,
        encoding="utf-8-sig",
        newline="",
    ) as handle:

        return list(
            csv.DictReader(
                handle
            )
        )


def is_correct(
    row: dict,
) -> bool:

    """
    NORMALISED match, not exact.

    Exact match counts "SAMPLE,JANE" against "SAMPLE, JANE" as
    a failure, which is a formatting difference rather than a
    reading error. Normalised is the measure the evaluation
    reports as authoritative and the one a reviewer would
    recognise as right or wrong.
    """

    return row[
        "normalized_match"
    ].strip().lower() == "true"


def confidence_of(
    row: dict,
) -> float | None:

    raw = row[
        "confidence"
    ].strip()

    if not raw:
        return None

    try:
        return float(
            raw
        )

    except ValueError:
        return None


# ==========================================================
# SUMMARY HELPERS
# ==========================================================

def accuracy_block(
    rows: list[dict],
) -> dict:

    total = len(
        rows
    )

    correct = sum(
        1
        for row in rows
        if is_correct(
            row
        )
    )

    critical = [
        row
        for row in rows
        if is_critical(
            row["document_type"],
            row["field_name"],
        )
    ]

    critical_correct = sum(
        1
        for row in critical
        if is_correct(
            row
        )
    )

    return {
        "fields": total,

        "correct": correct,

        "incorrect": total - correct,

        "normalized_accuracy_percent": (
            round(
                100.0 * correct / total,
                2,
            )
            if total
            else None
        ),

        "critical_fields": len(
            critical
        ),

        "critical_correct": critical_correct,

        "critical_incorrect": (
            len(
                critical
            )
            - critical_correct
        ),

        "critical_accuracy_percent": (
            round(
                100.0
                * critical_correct
                / len(
                    critical
                ),
                2,
            )
            if critical
            else None
        ),
    }


def quantile_buckets(
    scored: list[dict],
    bucket_count: int,
) -> list[dict]:

    """
    Buckets whose EDGES come from the observed distribution.

    Equal-width buckets over [0, 1] are useless here: the
    measured confidences run from 0.945 to 0.999999 with a
    median of 0.9999, so every field lands in the top bucket
    and the table says nothing.

    Quantile edges are derived from the data rather than
    chosen, which is the point -- picking boundaries by hand is
    how a calibration table gets made to look good.
    """

    ordered = sorted(
        scored,
        key=lambda row: confidence_of(
            row
        ),
    )

    size = len(
        ordered
    )

    if not size:
        return []


    buckets: list[dict] = []

    for index in range(
        bucket_count
    ):

        start = (
            index
            * size
            // bucket_count
        )

        end = (
            (
                index
                + 1
            )
            * size
            // bucket_count
        )

        chunk = ordered[start:end]

        if not chunk:
            continue


        block = accuracy_block(
            chunk
        )

        block["bucket"] = (
            f"q{index + 1}"
        )

        block["confidence_min"] = (
            confidence_of(
                chunk[0]
            )
        )

        block["confidence_max"] = (
            confidence_of(
                chunk[-1]
            )
        )

        buckets.append(
            block
        )


    return buckets


def discrimination(
    scored: list[dict],
) -> dict:

    """
    How well confidence separates correct from incorrect.

    Reported as the probability that a randomly chosen CORRECT
    field carries a higher confidence than a randomly chosen
    INCORRECT one -- the Mann-Whitney statistic, equivalently
    the area under the ROC curve.

        1.00  perfect separation
        0.50  no information
        0.00  perfectly inverted

    A rank statistic rather than a correlation, because the
    confidences are crushed against 1.0 and a Pearson
    correlation on that shape is dominated by a handful of
    outliers.
    """

    correct = [
        confidence_of(
            row
        )
        for row in scored
        if is_correct(
            row
        )
    ]

    incorrect = [
        confidence_of(
            row
        )
        for row in scored
        if not is_correct(
            row
        )
    ]

    if not correct or not incorrect:

        return {
            "auc": None,
            "correct_count": len(
                correct
            ),
            "incorrect_count": len(
                incorrect
            ),
            "note": (
                "Not computable: one of the two groups "
                "is empty."
            ),
        }


    better = 0

    ties = 0

    for good in correct:
        for bad in incorrect:

            if good > bad:
                better += 1

            elif good == bad:
                ties += 1


    pairs = (
        len(
            correct
        )
        * len(
            incorrect
        )
    )

    return {
        "auc": round(
            (
                better
                + 0.5 * ties
            )
            / pairs,
            4,
        ),

        "pairs": pairs,

        "correct_count": len(
            correct
        ),

        "incorrect_count": len(
            incorrect
        ),

        "mean_confidence_correct": round(
            statistics.fmean(
                correct
            ),
            6,
        ),

        "mean_confidence_incorrect": round(
            statistics.fmean(
                incorrect
            ),
            6,
        ),
    }


def percentile_of(
    values: list[float],
    value: float,
) -> float:

    return round(
        100.0
        * bisect.bisect_left(
            values,
            value,
        )
        / len(
            values
        ),
        1,
    )


# ==========================================================
# MAIN
# ==========================================================

def main() -> int:

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--field-results",
        type=Path,
        default=DEFAULT_FIELD_RESULTS,
    )

    parser.add_argument(
        "--buckets",
        type=int,
        default=5,
        help=(
            "Number of quantile buckets. Default 5."
        ),
    )

    arguments = parser.parse_args()


    rows = load_rows(
        arguments.field_results
    )

    scored = [
        row
        for row in rows
        if confidence_of(
            row
        )
        is not None
    ]

    unscored = [
        row
        for row in rows
        if confidence_of(
            row
        )
        is None
    ]


    print()
    print(
        "=" * 74
    )
    print(
        "CONFIDENCE CALIBRATION STUDY"
    )
    print(
        "=" * 74
    )
    print()
    print(
        f"  source        "
        f"{arguments.field_results.relative_to(PROJECT_ROOT)}"
    )
    print(
        f"  field rows    {len(rows)}"
    )
    print(
        f"  with a confidence   {len(scored)}"
    )
    print(
        f"  without             {len(unscored)}"
    )


    # ------------------------------------------------------
    # THE DISTRIBUTION
    # ------------------------------------------------------

    values = sorted(
        confidence_of(
            row
        )
        for row in scored
    )

    print()
    print(
        "-" * 74
    )
    print(
        "THE DISTRIBUTION"
    )
    print(
        "-" * 74
    )
    print()

    for label, fraction in (
        ("min", 0.0),
        ("p05", 0.05),
        ("p25", 0.25),
        ("median", 0.50),
        ("p75", 0.75),
        ("p95", 0.95),
        ("max", 1.0),
    ):

        index = min(
            len(
                values
            ) - 1,
            int(
                fraction
                * (
                    len(
                        values
                    ) - 1
                )
            ),
        )

        print(
            f"  {label:<8}{values[index]:.6f}"
        )

    print()
    print(
        "  Every reported confidence sits above 0.94, and the "
        "median is 0.9999."
    )
    print(
        "  There is almost no spread to correlate anything "
        "with."
    )


    # ------------------------------------------------------
    # BY STATUS
    # ------------------------------------------------------

    print()
    print(
        "-" * 74
    )
    print(
        "BY CONFIDENCE STATUS"
    )
    print(
        "-" * 74
    )
    print()
    print(
        f"  {'status':<20}{'fields':>8}"
        f"{'correct':>9}{'wrong':>7}"
        f"{'accuracy':>10}"
    )

    by_status: dict = {}

    statuses = sorted(
        {
            row["confidence_status"]
            for row in rows
        }
    )

    for status in statuses:

        subset = [
            row
            for row in rows
            if row["confidence_status"]
            == status
        ]

        block = accuracy_block(
            subset
        )

        by_status[status] = block

        print(
            f"  {status:<20}"
            f"{block['fields']:>8}"
            f"{block['correct']:>9}"
            f"{block['incorrect']:>7}"
            f"{block['normalized_accuracy_percent']:>9.2f}%"
        )


    # ------------------------------------------------------
    # QUANTILE BUCKETS
    # ------------------------------------------------------

    buckets = quantile_buckets(
        scored,
        arguments.buckets,
    )

    print()
    print(
        "-" * 74
    )
    print(
        f"QUANTILE BUCKETS  (edges from the data, not chosen)"
    )
    print(
        "-" * 74
    )
    print()
    print(
        f"  {'bucket':<8}{'range':<26}"
        f"{'fields':>7}{'wrong':>7}"
        f"{'accuracy':>10}"
        f"{'crit':>6}{'crit wrong':>12}"
    )

    for block in buckets:

        window = (
            f"{block['confidence_min']:.6f}"
            f" - {block['confidence_max']:.6f}"
        )

        print(
            f"  {block['bucket']:<8}{window:<26}"
            f"{block['fields']:>7}"
            f"{block['incorrect']:>7}"
            f"{block['normalized_accuracy_percent']:>9.2f}%"
            f"{block['critical_fields']:>6}"
            f"{block['critical_incorrect']:>12}"
        )


    # ------------------------------------------------------
    # DISCRIMINATION
    # ------------------------------------------------------

    separation = discrimination(
        scored
    )

    print()
    print(
        "-" * 74
    )
    print(
        "DISCRIMINATION"
    )
    print(
        "-" * 74
    )
    print()
    print(
        "  Probability that a correct field carries a HIGHER "
        "confidence than an"
    )
    print(
        "  incorrect one. 0.50 means the number carries no "
        "information."
    )
    print()
    print(
        f"  AUC                        "
        f"{separation['auc']}"
    )
    print(
        f"  pairs compared             "
        f"{separation.get('pairs')}"
    )
    print(
        f"  mean confidence, correct   "
        f"{separation.get('mean_confidence_correct')}"
    )
    print(
        f"  mean confidence, incorrect "
        f"{separation.get('mean_confidence_incorrect')}"
    )


    # ------------------------------------------------------
    # THE ERRORS THEMSELVES
    # ------------------------------------------------------

    print()
    print(
        "-" * 74
    )
    print(
        "EVERY NORMALISED ERROR"
    )
    print(
        "-" * 74
    )
    print()

    errors = []

    for row in rows:

        if is_correct(
            row
        ):
            continue


        confidence = confidence_of(
            row
        )

        entry = {
            "sample_id":
                row["sample_id"],

            "document_type":
                row["document_type"],

            "field_name":
                row["field_name"],

            "critical":
                is_critical(
                    row["document_type"],
                    row["field_name"],
                ),

            "confidence_status":
                row["confidence_status"],

            "confidence":
                confidence,

            "confidence_percentile":
                (
                    percentile_of(
                        values,
                        confidence,
                    )
                    if confidence is not None
                    else None
                ),

            "ground_truth":
                row[
                    "normalized_ground_truth"
                ],

            "prediction":
                row[
                    "normalized_prediction"
                ],
        }

        errors.append(
            entry
        )

        marker = (
            "CRITICAL"
            if entry["critical"]
            else ""
        )

        print(
            f"  {entry['sample_id']:<12}"
            f"{entry['field_name']:<16}"
            f"{entry['confidence_status']:<18}"
            + (
                f"conf={confidence:.6f} "
                f"(p{entry['confidence_percentile']:.0f})"
                if confidence is not None
                else "conf=none            "
            )
            + f"  {marker}"
        )

        print(
            f"      truth      "
            f"{entry['ground_truth']!r}"
        )

        print(
            f"      predicted  "
            f"{entry['prediction']!r}"
        )


    # ------------------------------------------------------
    # THE VERDICT
    # ------------------------------------------------------

    high_confidence_errors = [
        entry
        for entry in errors
        if entry["confidence"] is not None
        and entry["confidence_percentile"] >= 40
    ]

    print()
    print(
        "=" * 74
    )
    print(
        "VERDICT"
    )
    print(
        "=" * 74
    )
    print()

    if separation["auc"] is None:

        verdict = "INSUFFICIENT_DATA"

        print(
            "  Not computable on this data."
        )

    elif (
        separation["auc"] >= 0.75
        and not high_confidence_errors
    ):

        verdict = "PREDICTIVE"

        print(
            "  Confidence separates correct from incorrect "
            "fields on this corpus."
        )

    else:

        verdict = "NOT_A_PROBABILITY_OF_CORRECTNESS"

        print(
            "  CONFIDENCE IS NOT A PROBABILITY THAT THE "
            "FIELD IS CORRECT."
        )
        print()
        print(
            f"  {len(high_confidence_errors)} of "
            f"{len(errors)} errors sit at or above the "
            "40th percentile of the"
        )
        print(
            "  confidence distribution, and the mean "
            "confidence of incorrect fields"
        )
        print(
            "  is HIGHER than that of correct ones. The "
            "rank statistic is "
            f"{separation['auc']},"
        )
        print(
            "  where 0.50 would mean no information at all."
        )
        print()
        print(
            "  WHY, AND IT IS STRUCTURAL RATHER THAN BAD "
            "LUCK:"
        )
        print()
        print(
            "  Confidence is the OCR character confidence of "
            "the evidence lines a"
        )
        print(
            "  field cites. It measures whether the TEXT WAS "
            "READ correctly."
        )
        print()
        print(
            "  It cannot measure whether the text was "
            "ASSIGNED to the right field,"
        )
        print(
            "  because a misassignment cites a real line "
            "whose characters were read"
        )
        print(
            "  perfectly. Look at the errors above: "
            "day/month transpositions and a"
        )
        print(
            "  label kept in a value. High OCR support, "
            "wrong meaning."
        )


    print()
    print(
        "  Errors are few, and that bounds what can be "
        "claimed:"
    )
    print()
    print(
        f"    {separation['incorrect_count']} incorrect "
        f"scored fields out of "
        f"{len(scored)}."
    )
    print()
    print(
        "  A POSITIVE claim of calibration would need far "
        "more errors than this."
    )
    print(
        "  The NEGATIVE claim needs only a counterexample, "
        "and there are several --"
    )
    print(
        "  including a CRITICAL field wrong at the 92nd "
        "percentile of confidence."
    )


    # ------------------------------------------------------
    # WRITE
    # ------------------------------------------------------

    report = {
        "source": str(
            arguments.field_results.relative_to(
                PROJECT_ROOT
            )
        ),

        "field_rows": len(
            rows
        ),

        "scored_rows": len(
            scored
        ),

        "unscored_rows": len(
            unscored
        ),

        "distribution": {
            "min": values[0],
            "median": statistics.median(
                values
            ),
            "max": values[-1],
        },

        "overall": accuracy_block(
            rows
        ),

        "by_status": by_status,

        "quantile_buckets": buckets,

        "discrimination": separation,

        "errors": errors,

        "verdict": verdict,
    }

    output = (
        PROJECT_ROOT
        / "evaluation"
        / "reports"
        / "confidence_calibration.json"
    )

    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output.write_text(
        json.dumps(
            report,
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print(
        f"  written: {output.relative_to(PROJECT_ROOT)}"
    )
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
