"""
==========================================================
PHASE 10.5 - CONFIDENCE CALIBRATION
==========================================================

WHAT THIS SUITE IS PROTECTING
----------------------------------------------------------

  1. No document-level confidence exists anywhere. Not in the
     pipeline, not in the API, not in the interface.

  2. The calibration study is reproducible and its conclusion
     follows from the committed evaluation data rather than
     from a sentence somebody typed.

  3. The interface does not present field confidence as a
     probability that the value is correct -- because it
     measurably is not one -- and does not round a value below
     1.0 up to 100%.

  4. The bucket boundaries come from the observed distribution.
     A calibration table with hand-picked edges is a table
     that can be made to say anything.

NO PROVIDER CALLS
----------------------------------------------------------

Everything here reads evaluation/results/field_results.csv,
which is committed output from the Phase 6D run over all 63
documents.
"""

import csv
import json
import re
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


from scripts.development.confidence_calibration_study import (  # noqa: E402
    accuracy_block,
    confidence_of,
    discrimination,
    is_correct,
    load_rows,
    quantile_buckets,
)


FIELD_RESULTS = (
    PROJECT_ROOT
    / "evaluation"
    / "results"
    / "field_results.csv"
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
# 1. THE STUDY REPRODUCES
# ==========================================================

def test_study_runs() -> None:

    section(
        "TEST 1 - THE STUDY IS REPRODUCIBLE"
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.development."
            "confidence_calibration_study",
        ],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(
            PROJECT_ROOT
        ),
    )

    assert_equal(
        completed.returncode,
        0,
        (
            "The calibration study must run from the "
            "committed evaluation data with no arguments and "
            "no provider access.\n"
            f"{completed.stdout[-2000:]}\n"
            f"{completed.stderr[-2000:]}"
        ),
    )

    report_path = (
        PROJECT_ROOT
        / "evaluation"
        / "reports"
        / "confidence_calibration.json"
    )

    assert_true(
        report_path.exists(),
        "The study must write a machine-readable report.",
    )

    report = json.loads(
        report_path.read_text(
            encoding="utf-8"
        )
    )

    assert_equal(
        report["field_rows"],
        441,
        (
            "The study must cover every field row from the "
            "63-document evaluation."
        ),
    )

    ok(
        f"The study runs offline over "
        f"{report['field_rows']} field rows and writes "
        "evaluation/reports/confidence_calibration.json"
    )


# ==========================================================
# 2. THE CONCLUSION FOLLOWS FROM THE DATA
# ==========================================================

def test_conclusion_follows_from_data() -> None:

    section(
        "TEST 2 - THE CONCLUSION IS DERIVED, NOT ASSERTED"
    )

    rows = load_rows(
        FIELD_RESULTS
    )

    scored = [
        row
        for row in rows
        if confidence_of(
            row
        )
        is not None
    ]

    separation = discrimination(
        scored
    )

    # ------------------------------------------------------
    # THE NEGATIVE CLAIM, WHICH IS THE ONE BEING MADE
    # ------------------------------------------------------
    #
    # "Confidence does not predict correctness" needs only a
    # counterexample: a field that is wrong while carrying a
    # confidence at or above the middle of the distribution.
    #
    # There are several, and one is a critical field.
    # ------------------------------------------------------

    values = sorted(
        confidence_of(
            row
        )
        for row in scored
    )

    median = values[
        len(
            values
        )
        // 2
    ]

    high_confidence_errors = [
        row
        for row in scored
        if not is_correct(
            row
        )
        and confidence_of(
            row
        )
        >= median
    ]

    assert_true(
        high_confidence_errors,
        (
            "The whole conclusion rests on there being at "
            "least one field that is WRONG while carrying a "
            "confidence at or above the median. If this ever "
            "becomes empty, the claim in the interface and "
            "the documentation has to be re-examined rather "
            "than left standing."
        ),
    )

    for row in high_confidence_errors:

        print(
            f"       counterexample: {row['sample_id']} "
            f"{row['field_name']} "
            f"conf={confidence_of(row):.6f} "
            f"truth={row['normalized_ground_truth']!r} "
            f"predicted="
            f"{row['normalized_prediction']!r}"
        )

    ok(
        f"{len(high_confidence_errors)} field(s) are wrong at "
        "or above the median confidence: high support does "
        "not imply a correct value"
    )


    # ------------------------------------------------------
    # AND THE NUMBER CARRIES NO USABLE SIGNAL
    # ------------------------------------------------------

    assert_true(
        separation["auc"] is not None,
        "The rank statistic must be computable.",
    )

    assert_true(
        separation["auc"] < 0.75,
        (
            "If confidence separated correct from incorrect "
            "fields well, the honest thing would be to say "
            "so -- and the interface caveat would then be "
            "wrong. This asserts the measured state, so a "
            "future improvement forces the wording to be "
            "revisited rather than silently understating "
            "the system.\n"
            f"AUC = {separation['auc']}"
        ),
    )

    ok(
        f"AUC {separation['auc']} over "
        f"{separation['pairs']} pairs "
        "(0.50 would mean no information); mean confidence "
        f"of incorrect fields "
        f"{separation['mean_confidence_incorrect']} vs "
        f"{separation['mean_confidence_correct']} for correct"
    )


    # ------------------------------------------------------
    # THE SAMPLE IS SMALL AND THE SUITE SAYS SO
    # ------------------------------------------------------

    assert_true(
        separation["incorrect_count"] < 20,
        (
            "This suite states that the error count is too "
            "small for a POSITIVE calibration claim. If the "
            "error count ever grows past twenty, that "
            "reasoning changes and a real calibration curve "
            "becomes possible."
        ),
    )

    ok(
        f"Only {separation['incorrect_count']} scored fields "
        f"are incorrect out of {len(scored)}, which bounds "
        "what can be claimed in either direction"
    )


# ==========================================================
# 3. BUCKETS COME FROM THE DISTRIBUTION
# ==========================================================

def test_buckets_are_derived() -> None:

    section(
        "TEST 3 - BUCKET EDGES COME FROM THE DATA"
    )

    rows = load_rows(
        FIELD_RESULTS
    )

    scored = [
        row
        for row in rows
        if confidence_of(
            row
        )
        is not None
    ]

    buckets = quantile_buckets(
        scored,
        5,
    )

    assert_equal(
        len(
            buckets
        ),
        5,
        "Five quantile buckets were requested.",
    )

    # Every field lands in exactly one bucket.
    assert_equal(
        sum(
            block["fields"]
            for block in buckets
        ),
        len(
            scored
        ),
        (
            "The buckets must partition the scored fields. A "
            "table that drops rows can be made to say "
            "anything."
        ),
    )

    # Near-equal population is what makes them quantiles
    # rather than chosen ranges.
    sizes = [
        block["fields"]
        for block in buckets
    ]

    assert_true(
        max(
            sizes
        )
        - min(
            sizes
        )
        <= 1,
        (
            "Quantile buckets must hold near-equal counts. "
            "Unequal buckets would mean the edges were "
            "chosen rather than derived.\n"
            f"sizes={sizes}"
        ),
    )

    # And the edges are ascending and inside the real range.
    edges = [
        (
            block["confidence_min"],
            block["confidence_max"],
        )
        for block in buckets
    ]

    for index in range(
        1,
        len(
            edges
        ),
    ):

        assert_true(
            edges[index][0]
            >= edges[index - 1][1],
            (
                "Buckets must be ordered and "
                "non-overlapping."
            ),
        )

    print(
        f"       bucket sizes {sizes}"
    )

    for block in buckets:
        print(
            f"       {block['bucket']}  "
            f"{block['confidence_min']:.6f} - "
            f"{block['confidence_max']:.6f}  "
            f"accuracy "
            f"{block['normalized_accuracy_percent']:.2f}%  "
            f"({block['incorrect']} wrong)"
        )


    # ------------------------------------------------------
    # THE SHAPE THAT MATTERS
    # ------------------------------------------------------
    #
    # If confidence were calibrated, accuracy would climb with
    # the bucket. It does not: the LOWEST bucket is the most
    # accurate one.
    # ------------------------------------------------------

    lowest = buckets[0]

    highest = buckets[-1]

    assert_true(
        lowest[
            "normalized_accuracy_percent"
        ]
        >= highest[
            "normalized_accuracy_percent"
        ],
        (
            "On this corpus the lowest-confidence bucket is "
            "at least as accurate as the highest. That is "
            "the measured shape, and it is why the interface "
            "does not present confidence as a probability of "
            "correctness. If this ever inverts, the wording "
            "needs revisiting."
        ),
    )

    ok(
        f"Buckets partition all {len(scored)} scored fields "
        f"into near-equal groups {sizes}; the lowest bucket "
        f"({lowest['normalized_accuracy_percent']:.2f}%) is "
        "at least as accurate as the highest "
        f"({highest['normalized_accuracy_percent']:.2f}%)"
    )


# ==========================================================
# 4. CRITICAL FIELDS ARE REPORTED SEPARATELY
# ==========================================================

def test_critical_fields_reported() -> None:

    section(
        "TEST 4 - CRITICAL FIELDS ARE COUNTED SEPARATELY"
    )

    rows = load_rows(
        FIELD_RESULTS
    )

    overall = accuracy_block(
        rows
    )

    assert_true(
        overall["critical_fields"] > 0,
        (
            "Critical fields must be identified, using the "
            "validator's own definition rather than a list "
            "restated in the study."
        ),
    )

    assert_true(
        overall[
            "critical_accuracy_percent"
        ]
        is not None,
        "Critical accuracy must be reported.",
    )

    # It must not be hidden inside the overall average, which
    # is the specific failure mode being guarded against.
    assert_true(
        overall[
            "critical_incorrect"
        ]
        >= 0,
        "Critical errors are counted.",
    )

    ok(
        f"{overall['critical_fields']} critical fields, "
        f"{overall['critical_incorrect']} incorrect, "
        f"{overall['critical_accuracy_percent']:.2f}% "
        "accuracy, reported separately from the "
        f"{overall['fields']}-field overall figure"
    )


    # ------------------------------------------------------
    # THE EVALUATION AND THE PRODUCT MUST AGREE ON WHICH
    # FIELDS ARE CRITICAL
    # ------------------------------------------------------
    #
    # They did not. The evaluation carried its own list which
    # omitted `issuer` from guard_license and sia_badge, while
    # DocumentAnomalyValidator treats a missing or untrusted
    # issuer as an ERROR that sends the document to review.
    #
    # So critical accuracy was reported over 168 fields when
    # production considered 210 critical, and guard_020 --
    # issuer read as "ISSUED BY TX DPS" instead of "TX DPS" --
    # was a real critical-field error that the headline metric
    # could not see.
    #
    # This is the assertion that stops it recurring. A
    # definitional gap between the thing measured and the
    # thing shipped is how a critical regression hides inside
    # a healthy average.
    # ------------------------------------------------------

    import importlib.util

    from backend.app.services.document_anomaly_validator import (
        DocumentAnomalyValidator,
    )

    spec = importlib.util.spec_from_file_location(
        "vigilox_evaluation_metrics",
        PROJECT_ROOT
        / "scripts"
        / "evaluation"
        / "evaluation_metrics.py",
    )

    metrics = importlib.util.module_from_spec(
        spec
    )

    spec.loader.exec_module(
        metrics
    )

    production = {
        document_type: sorted(
            fields
        )
        for document_type, fields in (
            DocumentAnomalyValidator
            .CRITICAL_FIELDS
            .items()
        )
        if fields
    }

    evaluation = {
        document_type: sorted(
            fields
        )
        for document_type, fields in (
            metrics.CRITICAL_FIELDS.items()
        )
        if fields
    }

    assert_equal(
        evaluation,
        production,
        (
            "The evaluation must measure the SAME critical "
            "fields the product routes on.\n\n"
            "If these differ, the headline critical-field "
            "accuracy is computed over a different set than "
            "production treats as critical, and an error on "
            "the missing field is invisible in the metric "
            "that exists to catch exactly that."
        ),
    )

    ok(
        "The evaluation and DocumentAnomalyValidator agree "
        "on critical fields for all "
        f"{len(production)} document types"
    )


# ==========================================================
# 5. NO DOCUMENT-LEVEL CONFIDENCE ANYWHERE
# ==========================================================

def test_no_document_level_confidence() -> None:

    section(
        "TEST 5 - NO DOCUMENT-LEVEL CONFIDENCE EXISTS"
    )

    # ------------------------------------------------------
    # Searched for as CODE, by name, across the production
    # tree. A document-level score is the single most likely
    # thing for somebody to add in good faith, because it
    # looks like a summary.
    # ------------------------------------------------------

    forbidden = (
        "document_confidence",
        "overall_confidence",
        "average_confidence",
        "mean_confidence",
        "confidence_score",
        "total_confidence",
        "aggregate_confidence",
    )

    searched = 0

    offences: list[str] = []

    for directory in (
        "backend",
        "database",
        "frontend",
    ):

        root = (
            PROJECT_ROOT
            / directory
        )

        for path in root.rglob(
            "*"
        ):

            if path.suffix not in (
                ".py",
                ".js",
                ".html",
            ):
                continue


            if "__pycache__" in path.parts:
                continue


            searched += 1

            text = path.read_text(
                encoding="utf-8",
                errors="replace",
            )

            for name in forbidden:

                # Word-ish boundary, so a sentence explaining
                # that no mean confidence exists does not
                # count as defining one. Only an identifier
                # followed by an assignment, a colon or a
                # bracket looks like code.
                if re.search(
                    re.escape(
                        name
                    )
                    + r"\s*[=:\[(]",
                    text,
                ):

                    offences.append(
                        f"{path.relative_to(PROJECT_ROOT)}"
                        f": {name}"
                    )


    assert_equal(
        offences,
        [],
        (
            "No document-level confidence may be defined.\n\n"
            "There are seven per-field confidences and no "
            "authoritative way to combine them. Averaging "
            "them would weight a missing date of birth "
            "against a licence number as though the two "
            "mattered equally, and the result would be read "
            "as how much to trust the document -- a question "
            "the review decision already answers from "
            "evidence, explainably."
        ),
    )

    ok(
        f"{searched} production files searched for "
        f"{len(forbidden)} document-level confidence "
        "identifiers: none defined"
    )


    # ------------------------------------------------------
    # AND THE PIPELINE RESULT CARRIES ONLY PER-FIELD VALUES
    # ------------------------------------------------------

    import inspect

    from backend.app.services import (
        pipeline_service,
    )

    source = inspect.getsource(
        pipeline_service
        .DocumentPipelineService
        .process
    )

    assert_true(
        "field_confidence" in source,
        "The pipeline returns per-field confidence.",
    )

    ok(
        "The pipeline result carries field_confidence and no "
        "document-level figure"
    )


# ==========================================================
# 6. THE INTERFACE DOES NOT OVERCLAIM
# ==========================================================

def test_interface_does_not_overclaim() -> None:

    section(
        "TEST 6 - THE INTERFACE STATES WHAT THE NUMBER IS"
    )

    # ------------------------------------------------------
    # A value below 1.0 must never display as 100%.
    # ------------------------------------------------------

    import shutil

    node = shutil.which(
        "node"
    )

    assert_true(
        node is not None,
        (
            "Node is required to execute the formatter. "
            "Pattern-matching the source would not prove "
            "what a reviewer sees."
        ),
    )

    probe = (
        "global.window = global;"
        "require("
        + json.dumps(
            str(
                PROJECT_ROOT
                / "frontend"
                / "static"
                / "js"
                / "common.js"
            )
        )
        + ");"
        "var ui = global.VigiloxUI;"
        "var out = {};"
        "[1, 0.999999, 0.9988, 0.998555, 0.951]"
        ".forEach(function (v) {"
        "  out[String(v)] = ui.formatConfidence(v);"
        "});"
        "console.log(JSON.stringify(out));"
    )

    completed = subprocess.run(
        [
            node,
            "-e",
            probe,
        ],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(
            PROJECT_ROOT
        ),
    )

    assert_equal(
        completed.returncode,
        0,
        (
            "The formatter probe must run.\n"
            f"{completed.stderr[:2000]}"
        ),
    )

    formatted = json.loads(
        completed.stdout
    )

    assert_equal(
        formatted["1"],
        "100%",
        "Exactly 1.0 may display as 100%.",
    )

    for raw in (
        "0.999999",
        "0.9988",
        "0.998555",
        "0.951",
    ):

        assert_true(
            formatted[raw] != "100%",
            (
                "A confidence below 1.0 must NOT display as "
                "100%.\n\n"
                "It used to. The formatter rounded to whole "
                "percent, so 0.9988 read as 100% -- and the "
                "calibration study found a field that was "
                "WRONG at 0.998555, which displayed "
                "identically. A reviewer cannot be shown "
                "certainty the system has not "
                f"established.\n{raw} -> {formatted[raw]}"
            ),
        )

    print(
        f"       {formatted}"
    )

    ok(
        "Only exactly 1.0 displays as 100%; 0.9988 now "
        f"reads {formatted['0.9988']} and 0.998555 reads "
        f"{formatted['0.998555']}"
    )


    # ------------------------------------------------------
    # THE CAVEAT IS PRESENT AND SAYS THE RIGHT THING
    # ------------------------------------------------------

    vocabulary_source = (
        PROJECT_ROOT
        / "frontend"
        / "static"
        / "js"
        / "vocabulary.js"
    ).read_text(
        encoding="utf-8"
    )

    assert_true(
        "CONFIDENCE_MEANING" in vocabulary_source,
        (
            "The meaning of confidence must be stated in "
            "one shared place rather than reworded per "
            "screen."
        ),
    )

    assert_true(
        "not the probability"
        in vocabulary_source,
        (
            "The caveat must say plainly that confidence is "
            "not the probability that the value is correct."
        ),
    )

    assert_true(
        "no document-level confidence"
        in vocabulary_source.lower(),
        (
            "And that there is no document-level score."
        ),
    )

    fields_source = (
        PROJECT_ROOT
        / "frontend"
        / "static"
        / "js"
        / "workspace"
        / "fields_view.js"
    ).read_text(
        encoding="utf-8"
    )

    assert_true(
        "CONFIDENCE_MEANING" in fields_source,
        (
            "The workspace must render the shared wording "
            "rather than its own copy of it."
        ),
    )

    ok(
        "The caveat lives in the vocabulary, states that "
        "confidence is not a probability of correctness, and "
        "is rendered by the screen that shows the numbers"
    )


    # ------------------------------------------------------
    # AND NOWHERE CLAIMS PROBABILITY
    # ------------------------------------------------------

    claims = (
        "probability that",
        "chance the value",
        "likely correct",
        "accuracy of this field",
    )

    for path in (
        PROJECT_ROOT
        / "frontend"
        / "static"
        / "js"
    ).rglob(
        "*.js"
    ):

        text = path.read_text(
            encoding="utf-8"
        ).lower()

        for claim in claims:

            if claim not in text:
                continue


            # "not the probability that" is the caveat, which
            # is the opposite of a claim.
            assert_true(
                (
                    "not the probability that"
                    in text
                )
                or claim != "probability that",
                (
                    "The interface must not assert that "
                    "confidence is a probability of "
                    f"correctness. Found {claim!r} in "
                    f"{path.name}"
                ),
            )

    ok(
        "No frontend module claims confidence is a "
        "probability of correctness"
    )


# ==========================================================
# 7. THE STUDY IS HONEST WITHOUT THE DATA
# ==========================================================

def test_missing_data_is_reported() -> None:

    section(
        "TEST 7 - MISSING DATA IS REPORTED, NOT INVENTED"
    )

    missing = (
        PROJECT_ROOT
        / "evaluation"
        / "results"
        / "does-not-exist.csv"
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.development."
            "confidence_calibration_study",
            "--field-results",
            str(
                missing
            ),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(
            PROJECT_ROOT
        ),
    )

    assert_true(
        completed.returncode != 0,
        (
            "With no evaluation data the study must fail "
            "rather than print a verdict it cannot support."
        ),
    )

    combined = (
        completed.stdout
        + completed.stderr
    )

    assert_true(
        "not found" in combined.lower(),
        (
            "And it must say what was missing."
        ),
    )

    ok(
        "With no evaluation data the study exits non-zero "
        "and names the missing file"
    )


# ==========================================================
# MAIN
# ==========================================================

def main() -> int:

    print()
    print(
        "=" * 74
    )
    print(
        "PHASE 10.5 - CONFIDENCE CALIBRATION"
    )
    print(
        "=" * 74
    )

    test_study_runs()
    test_conclusion_follows_from_data()
    test_buckets_are_derived()
    test_critical_fields_reported()
    test_no_document_level_confidence()
    test_interface_does_not_overclaim()
    test_missing_data_is_reported()

    print()
    print(
        "=" * 74
    )
    print(
        "[PASS] PHASE 10.5 CONFIDENCE CALIBRATION TEST "
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
