import csv
import json
import re
import statistics
import unicodedata

from collections import Counter
from datetime import datetime
from pathlib import Path


# ==========================================================
# CONFIGURATION
# ==========================================================

GROUND_TRUTH_PATH = Path(
    "evaluation/ground_truth/labels.jsonl"
)

PREDICTIONS_PATH = Path(
    "evaluation/results/predictions.jsonl"
)

FIELD_RESULTS_PATH = Path(
    "evaluation/results/field_results.csv"
)

DOCUMENT_RESULTS_PATH = Path(
    "evaluation/results/document_results.csv"
)

SUMMARY_PATH = Path(
    "evaluation/reports/summary.json"
)

ERROR_CASES_PATH = Path(
    "evaluation/reports/error_cases.csv"
)


FIELDS = [
    "full_name",
    "licence_number",
    "id_number",
    "expiry_date",
    "date_of_birth",
    "issue_date",
    "issuer",
]


DATE_FIELDS = {
    "expiry_date",
    "date_of_birth",
    "issue_date",
}


IDENTIFIER_FIELDS = {
    "licence_number",
    "id_number",
}


CRITICAL_FIELDS = {

    "guard_license": [
        "full_name",
        "licence_number",
        "expiry_date",
    ],

    "sia_badge": [
        "full_name",
        "licence_number",
        "expiry_date",
    ],

    "id_card": [
        "full_name",
        "id_number",
    ],
}


# ==========================================================
# HELPERS
# ==========================================================

def percentage(
    numerator: int,
    denominator: int,
) -> float | None:

    if denominator == 0:
        return None

    return round(
        (
            numerator
            / denominator
        )
        * 100,
        2,
    )


def load_jsonl(
    path: Path,
) -> list[dict]:

    records = []


    if not path.exists():

        raise FileNotFoundError(
            f"File not found: {path}"
        )


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


# ==========================================================
# CANONICAL PREDICTIONS
# ==========================================================

def build_canonical_predictions(
    prediction_records: list[dict],
) -> dict[str, dict]:

    attempts_by_sample = {}


    for record in prediction_records:

        sample_id = record.get(
            "sample_id"
        )


        if not sample_id:
            continue


        attempts_by_sample.setdefault(
            sample_id,
            [],
        ).append(
            record
        )


    canonical = {}


    for (
        sample_id,
        attempts,
    ) in attempts_by_sample.items():

        successful_attempts = [

            attempt

            for attempt
            in attempts

            if (
                attempt.get("status")
                == "success"
                and attempt.get(
                    "prediction"
                )
                is not None
            )
        ]


        if successful_attempts:

            canonical[
                sample_id
            ] = successful_attempts[-1]

        else:

            canonical[
                sample_id
            ] = attempts[-1]


    return canonical


# ==========================================================
# NORMALIZATION
# ==========================================================

def normalize_text(
    value,
):

    if value is None:
        return None


    value = str(
        value
    ).strip()


    if not value:
        return ""


    value = unicodedata.normalize(
        "NFKC",
        value,
    )


    value = value.upper()


    # Convert punctuation to spaces.
    value = re.sub(
        r"[^A-Z0-9]+",
        " ",
        value,
    )


    value = re.sub(
        r"\s+",
        " ",
        value,
    ).strip()


    return value


def normalize_identifier(
    value,
):

    if value is None:
        return None


    value = unicodedata.normalize(
        "NFKC",
        str(
            value
        ),
    ).upper()


    return re.sub(
        r"[^A-Z0-9]",
        "",
        value,
    )


def normalize_date(
    value,
):

    if value is None:
        return None


    text = str(
        value
    ).strip()


    formats = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d %b %Y",
        "%d %B %Y",
    ]


    for date_format in formats:

        try:

            parsed = datetime.strptime(
                text,
                date_format,
            )

            return parsed.strftime(
                "%Y-%m-%d"
            )

        except ValueError:
            pass


    return normalize_text(
        text
    )


def normalize_field(
    field_name: str,
    value,
):

    if value is None:
        return None


    if field_name in DATE_FIELDS:

        return normalize_date(
            value
        )


    if field_name in IDENTIFIER_FIELDS:

        return normalize_identifier(
            value
        )


    return normalize_text(
        value
    )


# ==========================================================
# FIELD COMPARISON
# ==========================================================

def compare_field(
    field_name: str,
    ground_truth_value,
    predicted_value,
):

    exact_match = (
        ground_truth_value
        == predicted_value
    )


    normalized_ground_truth = (
        normalize_field(
            field_name,
            ground_truth_value,
        )
    )


    normalized_prediction = (
        normalize_field(
            field_name,
            predicted_value,
        )
    )


    normalized_match = (
        normalized_ground_truth
        == normalized_prediction
    )


    if (
        ground_truth_value is None
        and predicted_value is None
    ):

        null_outcome = (
            "CORRECT_NULL"
        )


    elif (
        ground_truth_value is None
        and predicted_value is not None
    ):

        null_outcome = (
            "HALLUCINATION"
        )


    elif (
        ground_truth_value is not None
        and predicted_value is None
    ):

        null_outcome = (
            "MISSED_KNOWN_FIELD"
        )


    else:

        null_outcome = (
            "VALUE_PRESENT"
        )


    return {
        "exact_match":
            exact_match,

        "normalized_match":
            normalized_match,

        "normalized_ground_truth":
            normalized_ground_truth,

        "normalized_prediction":
            normalized_prediction,

        "null_outcome":
            null_outcome,
    }


# ==========================================================
# CSV WRITER
# ==========================================================

def write_csv(
    path: Path,
    rows: list[dict],
):

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


    if not rows:

        return


    fieldnames = list(
        rows[0].keys()
    )


    with path.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )


        writer.writeheader()

        writer.writerows(
            rows
        )


# ==========================================================
# MAIN METRICS
# ==========================================================

def main():

    print()
    print(
        "=" * 74
    )

    print(
        "PHASE 6D — EVALUATION METRICS"
    )

    print(
        "=" * 74
    )


    # ======================================================
    # LOAD DATA
    # ======================================================

    ground_truth_records = (
        load_jsonl(
            GROUND_TRUTH_PATH
        )
    )


    prediction_records = (
        load_jsonl(
            PREDICTIONS_PATH
        )
    )


    canonical_predictions = (
        build_canonical_predictions(
            prediction_records
        )
    )


    ground_truth_by_id = {

        record["sample_id"]:
            record

        for record
        in ground_truth_records
    }


    # ======================================================
    # VERIFY DATASET COMPLETENESS
    # ======================================================

    missing_successful_predictions = []


    for sample_id in ground_truth_by_id:

        prediction_record = (
            canonical_predictions.get(
                sample_id
            )
        )


        if (
            prediction_record is None
            or prediction_record.get(
                "status"
            )
            != "success"
        ):

            missing_successful_predictions.append(
                sample_id
            )


    if missing_successful_predictions:

        raise RuntimeError(
            "Missing successful predictions for: "
            + ", ".join(
                missing_successful_predictions
            )
        )


    successful_canonical_count = sum(

        1

        for sample_id
        in ground_truth_by_id

        if (
            canonical_predictions[
                sample_id
            ].get(
                "status"
            )
            == "success"
        )
    )


    failed_attempt_count = sum(

        1

        for record
        in prediction_records

        if record.get(
            "status"
        )
        == "failed"
    )


    print(
        "Ground truth documents:",
        len(
            ground_truth_records
        ),
    )


    print(
        "Raw prediction records:",
        len(
            prediction_records
        ),
    )


    print(
        "Canonical successful predictions:",
        successful_canonical_count,
    )


    print(
        "Infrastructure/API failed attempts:",
        failed_attempt_count,
    )


    # ======================================================
    # RESULT CONTAINERS
    # ======================================================

    field_rows = []

    document_rows = []

    error_rows = []


    review_decisions = Counter()

    review_priorities = Counter()

    confidence_statuses = Counter()

    document_type_counts = Counter()

    document_type_correct_counts = Counter()


    runtimes = []

    runtimes_by_type = {}


    # ======================================================
    # PROCESS EACH DOCUMENT
    # ======================================================

    for ground_truth in ground_truth_records:

        sample_id = (
            ground_truth[
                "sample_id"
            ]
        )


        ground_truth_type = (
            ground_truth[
                "document_type"
            ]
        )


        quality = (
            ground_truth[
                "quality"
            ]
        )


        prediction_record = (
            canonical_predictions[
                sample_id
            ]
        )


        pipeline_prediction = (
            prediction_record[
                "prediction"
            ]
        )


        extraction = (
            pipeline_prediction[
                "extraction"
            ]
        )


        field_confidence = (
            pipeline_prediction.get(
                "field_confidence",
                {},
            )
        )


        review_decision = (
            pipeline_prediction.get(
                "review_decision",
                {},
            )
        )


        anomaly_validation = (
            pipeline_prediction.get(
                "anomaly_validation",
                {},
            )
        )


        predicted_type = (
            extraction.get(
                "document_type"
            )
        )


        document_type_correct = (
            predicted_type
            == ground_truth_type
        )


        document_type_counts[
            ground_truth_type
        ] += 1


        if document_type_correct:

            document_type_correct_counts[
                ground_truth_type
            ] += 1


        # ==================================================
        # DOCUMENT TYPE ERROR
        # ==================================================

        if not document_type_correct:

            error_rows.append({

                "sample_id":
                    sample_id,

                "document_type":
                    ground_truth_type,

                "quality":
                    quality,

                "error_type":
                    "DOCUMENT_TYPE_MISMATCH",

                "field_name":
                    "document_type",

                "ground_truth":
                    ground_truth_type,

                "prediction":
                    predicted_type,

                "confidence_status":
                    "",

                "review_decision":
                    review_decision.get(
                        "decision"
                    ),

                "review_priority":
                    review_decision.get(
                        "priority"
                    ),
            })


        # ==================================================
        # FIELD EVALUATION
        # ==================================================

        exact_matches = []

        normalized_matches = []

        mismatch_fields = []


        critical_fields = (
            CRITICAL_FIELDS.get(
                ground_truth_type,
                [],
            )
        )


        critical_matches = []


        for field_name in FIELDS:

            ground_truth_value = (
                ground_truth[
                    "fields"
                ].get(
                    field_name
                )
            )


            extracted_field = (
                extraction.get(
                    field_name,
                    {},
                )
            )


            if isinstance(
                extracted_field,
                dict,
            ):

                predicted_value = (
                    extracted_field.get(
                        "value"
                    )
                )


                source_line_ids = (
                    extracted_field.get(
                        "source_line_ids",
                        [],
                    )
                )

            else:

                predicted_value = None

                source_line_ids = []


            comparison = (
                compare_field(
                    field_name,
                    ground_truth_value,
                    predicted_value,
                )
            )


            exact_matches.append(
                comparison[
                    "exact_match"
                ]
            )


            normalized_matches.append(
                comparison[
                    "normalized_match"
                ]
            )


            if field_name in critical_fields:

                critical_matches.append(
                    comparison[
                        "normalized_match"
                    ]
                )


            if not comparison[
                "normalized_match"
            ]:

                mismatch_fields.append(
                    field_name
                )


            confidence_info = (
                field_confidence.get(
                    field_name,
                    {},
                )
            )


            confidence_value = (
                confidence_info.get(
                    "confidence"
                )
            )


            confidence_status = (
                confidence_info.get(
                    "status"
                )
            )


            if confidence_status:

                confidence_statuses[
                    confidence_status
                ] += 1


            field_row = {

                "sample_id":
                    sample_id,

                "document_type":
                    ground_truth_type,

                "quality":
                    quality,

                "field_name":
                    field_name,

                "ground_truth":
                    ground_truth_value,

                "prediction":
                    predicted_value,

                "exact_match":
                    comparison[
                        "exact_match"
                    ],

                "normalized_match":
                    comparison[
                        "normalized_match"
                    ],

                "normalized_ground_truth":
                    comparison[
                        "normalized_ground_truth"
                    ],

                "normalized_prediction":
                    comparison[
                        "normalized_prediction"
                    ],

                "null_outcome":
                    comparison[
                        "null_outcome"
                    ],

                "confidence":
                    confidence_value,

                "confidence_status":
                    confidence_status,

                "source_line_ids":
                    "|".join(
                        source_line_ids
                    ),
            }


            field_rows.append(
                field_row
            )


            # ==============================================
            # FIELD ERROR CASE
            # ==============================================

            if not comparison[
                "normalized_match"
            ]:

                if (
                    comparison[
                        "null_outcome"
                    ]
                    == "HALLUCINATION"
                ):

                    error_type = (
                        "HALLUCINATION"
                    )


                elif (
                    comparison[
                        "null_outcome"
                    ]
                    == "MISSED_KNOWN_FIELD"
                ):

                    error_type = (
                        "MISSED_KNOWN_FIELD"
                    )


                else:

                    error_type = (
                        "FIELD_MISMATCH"
                    )


                error_rows.append({

                    "sample_id":
                        sample_id,

                    "document_type":
                        ground_truth_type,

                    "quality":
                        quality,

                    "error_type":
                        error_type,

                    "field_name":
                        field_name,

                    "ground_truth":
                        ground_truth_value,

                    "prediction":
                        predicted_value,

                    "confidence_status":
                        confidence_status,

                    "review_decision":
                        review_decision.get(
                            "decision"
                        ),

                    "review_priority":
                        review_decision.get(
                            "priority"
                        ),
                })


        # ==================================================
        # DOCUMENT-LEVEL CORRECTNESS
        # ==================================================

        all_fields_exact = all(
            exact_matches
        )


        all_fields_normalized = all(
            normalized_matches
        )


        critical_fields_correct = all(
            critical_matches
        ) if critical_matches else True


        document_correct_normalized = (
            document_type_correct
            and all_fields_normalized
        )


        decision = (
            review_decision.get(
                "decision"
            )
        )


        priority = (
            review_decision.get(
                "priority"
            )
        )


        reason_codes = (
            review_decision.get(
                "reason_codes",
                [],
            )
        )


        review_decisions[
            decision or "UNKNOWN"
        ] += 1


        review_priorities[
            priority or "UNKNOWN"
        ] += 1


        false_auto_accept = (
            decision == "AUTO_ACCEPT"
            and not document_correct_normalized
        )


        safe_escalation = (
            decision == "REVIEW_REQUIRED"
            and not document_correct_normalized
        )


        runtime_seconds = (
            prediction_record.get(
                "runtime_seconds"
            )
        )


        if runtime_seconds is not None:

            runtime_seconds = float(
                runtime_seconds
            )


            runtimes.append(
                runtime_seconds
            )


            runtimes_by_type.setdefault(
                ground_truth_type,
                [],
            ).append(
                runtime_seconds
            )


        anomaly_issues = (
            anomaly_validation.get(
                "issues",
                [],
            )
        )


        anomaly_codes = [

            issue.get(
                "code"
            )

            for issue
            in anomaly_issues

            if issue.get(
                "code"
            )
        ]


        document_rows.append({

            "sample_id":
                sample_id,

            "quality":
                quality,

            "ground_truth_type":
                ground_truth_type,

            "predicted_type":
                predicted_type,

            "document_type_correct":
                document_type_correct,

            "all_fields_exact":
                all_fields_exact,

            "all_fields_normalized":
                all_fields_normalized,

            "critical_fields_correct":
                critical_fields_correct,

            "document_correct_normalized":
                document_correct_normalized,

            "mismatch_fields":
                "|".join(
                    mismatch_fields
                ),

            "review_decision":
                decision,

            "review_priority":
                priority,

            "review_reason_codes":
                "|".join(
                    reason_codes
                ),

            "anomaly_codes":
                "|".join(
                    anomaly_codes
                ),

            "false_auto_accept":
                false_auto_accept,

            "safe_escalation":
                safe_escalation,

            "runtime_seconds":
                runtime_seconds,
        })


    # ======================================================
    # FIELD METRICS
    # ======================================================

    total_fields = len(
        field_rows
    )


    exact_field_matches = sum(

        1

        for row
        in field_rows

        if row[
            "exact_match"
        ]
    )


    normalized_field_matches = sum(

        1

        for row
        in field_rows

        if row[
            "normalized_match"
        ]
    )


    known_field_rows = [

        row

        for row
        in field_rows

        if row[
            "ground_truth"
        ]
        is not None
    ]


    known_exact_matches = sum(

        1

        for row
        in known_field_rows

        if row[
            "exact_match"
        ]
    )


    known_normalized_matches = sum(

        1

        for row
        in known_field_rows

        if row[
            "normalized_match"
        ]
    )


    null_field_rows = [

        row

        for row
        in field_rows

        if row[
            "ground_truth"
        ]
        is None
    ]


    correct_null_count = sum(

        1

        for row
        in null_field_rows

        if row[
            "null_outcome"
        ]
        == "CORRECT_NULL"
    )


    hallucination_count = sum(

        1

        for row
        in null_field_rows

        if row[
            "null_outcome"
        ]
        == "HALLUCINATION"
    )


    missed_known_count = sum(

        1

        for row
        in known_field_rows

        if row[
            "null_outcome"
        ]
        == "MISSED_KNOWN_FIELD"
    )


    # ======================================================
    # CRITICAL FIELD METRICS
    # ======================================================

    critical_rows = []


    for row in field_rows:

        document_type = (
            row[
                "document_type"
            ]
        )


        if (
            row[
                "field_name"
            ]
            in CRITICAL_FIELDS.get(
                document_type,
                [],
            )
        ):

            critical_rows.append(
                row
            )


    critical_normalized_matches = sum(

        1

        for row
        in critical_rows

        if row[
            "normalized_match"
        ]
    )


    # ======================================================
    # DOCUMENT METRICS
    # ======================================================

    total_documents = len(
        document_rows
    )


    correct_document_types = sum(

        1

        for row
        in document_rows

        if row[
            "document_type_correct"
        ]
    )


    fully_correct_documents = sum(

        1

        for row
        in document_rows

        if row[
            "document_correct_normalized"
        ]
    )


    incorrect_documents = (
        total_documents
        - fully_correct_documents
    )


    auto_accept_count = sum(

        1

        for row
        in document_rows

        if row[
            "review_decision"
        ]
        == "AUTO_ACCEPT"
    )


    review_required_count = sum(

        1

        for row
        in document_rows

        if row[
            "review_decision"
        ]
        == "REVIEW_REQUIRED"
    )


    false_auto_accept_count = sum(

        1

        for row
        in document_rows

        if row[
            "false_auto_accept"
        ]
    )


    safe_escalation_count = sum(

        1

        for row
        in document_rows

        if row[
            "safe_escalation"
        ]
    )


    # ======================================================
    # PER-TYPE METRICS
    # ======================================================

    per_document_type = {}


    for document_type in sorted(
        document_type_counts.keys()
    ):

        type_documents = [

            row

            for row
            in document_rows

            if row[
                "ground_truth_type"
            ]
            == document_type
        ]


        type_fields = [

            row

            for row
            in field_rows

            if row[
                "document_type"
            ]
            == document_type
        ]


        type_known_fields = [

            row

            for row
            in type_fields

            if row[
                "ground_truth"
            ]
            is not None
        ]


        per_document_type[
            document_type
        ] = {

            "documents":
                len(
                    type_documents
                ),

            "document_type_accuracy_percent":
                percentage(
                    sum(
                        1

                        for row
                        in type_documents

                        if row[
                            "document_type_correct"
                        ]
                    ),
                    len(
                        type_documents
                    ),
                ),

            "all_field_exact_accuracy_percent":
                percentage(
                    sum(
                        1

                        for row
                        in type_fields

                        if row[
                            "exact_match"
                        ]
                    ),
                    len(
                        type_fields
                    ),
                ),

            "all_field_normalized_accuracy_percent":
                percentage(
                    sum(
                        1

                        for row
                        in type_fields

                        if row[
                            "normalized_match"
                        ]
                    ),
                    len(
                        type_fields
                    ),
                ),

            "known_field_normalized_accuracy_percent":
                percentage(
                    sum(
                        1

                        for row
                        in type_known_fields

                        if row[
                            "normalized_match"
                        ]
                    ),
                    len(
                        type_known_fields
                    ),
                ),

            "fully_correct_documents":
                sum(
                    1

                    for row
                    in type_documents

                    if row[
                        "document_correct_normalized"
                    ]
                ),

            "fully_correct_document_rate_percent":
                percentage(
                    sum(
                        1

                        for row
                        in type_documents

                        if row[
                            "document_correct_normalized"
                        ]
                    ),
                    len(
                        type_documents
                    ),
                ),
        }


    # ======================================================
    # PER-FIELD METRICS
    # ======================================================

    per_field = {}


    for field_name in FIELDS:

        rows = [

            row

            for row
            in field_rows

            if row[
                "field_name"
            ]
            == field_name
        ]


        known_rows = [

            row

            for row
            in rows

            if row[
                "ground_truth"
            ]
            is not None
        ]


        null_rows = [

            row

            for row
            in rows

            if row[
                "ground_truth"
            ]
            is None
        ]


        per_field[
            field_name
        ] = {

            "total":
                len(
                    rows
                ),

            "known_ground_truth":
                len(
                    known_rows
                ),

            "null_ground_truth":
                len(
                    null_rows
                ),

            "exact_accuracy_percent":
                percentage(
                    sum(
                        1

                        for row
                        in rows

                        if row[
                            "exact_match"
                        ]
                    ),
                    len(
                        rows
                    ),
                ),

            "normalized_accuracy_percent":
                percentage(
                    sum(
                        1

                        for row
                        in rows

                        if row[
                            "normalized_match"
                        ]
                    ),
                    len(
                        rows
                    ),
                ),

            "known_normalized_accuracy_percent":
                percentage(
                    sum(
                        1

                        for row
                        in known_rows

                        if row[
                            "normalized_match"
                        ]
                    ),
                    len(
                        known_rows
                    ),
                ),

            "hallucinations":
                sum(
                    1

                    for row
                    in rows

                    if row[
                        "null_outcome"
                    ]
                    == "HALLUCINATION"
                ),

            "missed_known_fields":
                sum(
                    1

                    for row
                    in rows

                    if row[
                        "null_outcome"
                    ]
                    == "MISSED_KNOWN_FIELD"
                ),
        }


    # ======================================================
    # RUNTIME STATISTICS
    # ======================================================

    runtime_summary = {}


    if runtimes:

        runtime_summary = {

            "count":
                len(
                    runtimes
                ),

            "mean_seconds":
                round(
                    statistics.mean(
                        runtimes
                    ),
                    4,
                ),

            "median_seconds":
                round(
                    statistics.median(
                        runtimes
                    ),
                    4,
                ),

            "minimum_seconds":
                round(
                    min(
                        runtimes
                    ),
                    4,
                ),

            "maximum_seconds":
                round(
                    max(
                        runtimes
                    ),
                    4,
                ),
        }


    runtime_by_type_summary = {}


    for (
        document_type,
        values,
    ) in runtimes_by_type.items():

        runtime_by_type_summary[
            document_type
        ] = {

            "count":
                len(
                    values
                ),

            "mean_seconds":
                round(
                    statistics.mean(
                        values
                    ),
                    4,
                ),

            "median_seconds":
                round(
                    statistics.median(
                        values
                    ),
                    4,
                ),

            "minimum_seconds":
                round(
                    min(
                        values
                    ),
                    4,
                ),

            "maximum_seconds":
                round(
                    max(
                        values
                    ),
                    4,
                ),
        }


    # ======================================================
    # SUMMARY
    # ======================================================

    summary = {

        "evaluation": {

            "reference_date":
                "2026-08-18",

            "ground_truth_documents":
                len(
                    ground_truth_records
                ),

            "raw_prediction_records":
                len(
                    prediction_records
                ),

            "canonical_successful_predictions":
                successful_canonical_count,

            "infrastructure_failed_attempts":
                failed_attempt_count,
        },


        "document_classification": {

            "correct":
                correct_document_types,

            "total":
                total_documents,

            "accuracy_percent":
                percentage(
                    correct_document_types,
                    total_documents,
                ),
        },


        "field_accuracy": {

            "all_fields": {

                "total":
                    total_fields,

                "exact_matches":
                    exact_field_matches,

                "exact_accuracy_percent":
                    percentage(
                        exact_field_matches,
                        total_fields,
                    ),

                "normalized_matches":
                    normalized_field_matches,

                "normalized_accuracy_percent":
                    percentage(
                        normalized_field_matches,
                        total_fields,
                    ),
            },


            "known_non_null_fields": {

                "total":
                    len(
                        known_field_rows
                    ),

                "exact_matches":
                    known_exact_matches,

                "exact_accuracy_percent":
                    percentage(
                        known_exact_matches,
                        len(
                            known_field_rows
                        ),
                    ),

                "normalized_matches":
                    known_normalized_matches,

                "normalized_accuracy_percent":
                    percentage(
                        known_normalized_matches,
                        len(
                            known_field_rows
                        ),
                    ),
            },


            "critical_fields": {

                "total":
                    len(
                        critical_rows
                    ),

                "normalized_matches":
                    critical_normalized_matches,

                "normalized_accuracy_percent":
                    percentage(
                        critical_normalized_matches,
                        len(
                            critical_rows
                        ),
                    ),
            },
        },


        "null_handling": {

            "ground_truth_null_fields":
                len(
                    null_field_rows
                ),

            "correct_nulls":
                correct_null_count,

            "correct_null_rate_percent":
                percentage(
                    correct_null_count,
                    len(
                        null_field_rows
                    ),
                ),

            "hallucinations":
                hallucination_count,

            "hallucination_rate_percent":
                percentage(
                    hallucination_count,
                    len(
                        null_field_rows
                    ),
                ),

            "ground_truth_known_fields":
                len(
                    known_field_rows
                ),

            "missed_known_fields":
                missed_known_count,

            "missed_known_field_rate_percent":
                percentage(
                    missed_known_count,
                    len(
                        known_field_rows
                    ),
                ),
        },


        "document_level": {

            "fully_correct_documents":
                fully_correct_documents,

            "incorrect_documents":
                incorrect_documents,

            "fully_correct_rate_percent":
                percentage(
                    fully_correct_documents,
                    total_documents,
                ),
        },


        "review_decisions": {

            "distribution":
                dict(
                    review_decisions
                ),

            "priority_distribution":
                dict(
                    review_priorities
                ),

            "auto_accept_count":
                auto_accept_count,

            "review_required_count":
                review_required_count,

            "false_auto_accept_count":
                false_auto_accept_count,

            "false_auto_accept_rate_among_auto_accepts_percent":
                percentage(
                    false_auto_accept_count,
                    auto_accept_count,
                ),

            "false_auto_accept_rate_overall_percent":
                percentage(
                    false_auto_accept_count,
                    total_documents,
                ),

            "safe_escalation_count":
                safe_escalation_count,

            "safe_escalation_rate_among_incorrect_documents_percent":
                percentage(
                    safe_escalation_count,
                    incorrect_documents,
                ),
        },


        "field_confidence_status_distribution":
            dict(
                confidence_statuses
            ),


        "per_document_type":
            per_document_type,


        "per_field":
            per_field,


        "runtime":
            runtime_summary,


        "runtime_by_document_type":
            runtime_by_type_summary,
    }


    # ======================================================
    # SAVE OUTPUTS
    # ======================================================

    write_csv(
        FIELD_RESULTS_PATH,
        field_rows,
    )


    write_csv(
        DOCUMENT_RESULTS_PATH,
        document_rows,
    )


    write_csv(
        ERROR_CASES_PATH,
        error_rows,
    )


    SUMMARY_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


    with SUMMARY_PATH.open(
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            summary,
            file,
            indent=2,
            ensure_ascii=False,
        )


    # ======================================================
    # CONSOLE REPORT
    # ======================================================

    print()
    print(
        "-" * 74
    )


    print(
        "DOCUMENT TYPE ACCURACY"
    )


    print(
        f"{correct_document_types}/"
        f"{total_documents} "
        f"("
        f"{percentage(correct_document_types, total_documents)}%"
        f")"
    )


    print()
    print(
        "FIELD ACCURACY"
    )


    print(
        "Exact:",
        f"{exact_field_matches}/"
        f"{total_fields}",
        f"("
        f"{percentage(exact_field_matches, total_fields)}%"
        f")",
    )


    print(
        "Normalized:",
        f"{normalized_field_matches}/"
        f"{total_fields}",
        f"("
        f"{percentage(normalized_field_matches, total_fields)}%"
        f")",
    )


    print(
        "Known-field normalized:",
        f"{known_normalized_matches}/"
        f"{len(known_field_rows)}",
        f"("
        f"{percentage(known_normalized_matches, len(known_field_rows))}%"
        f")",
    )


    print(
        "Critical-field normalized:",
        f"{critical_normalized_matches}/"
        f"{len(critical_rows)}",
        f"("
        f"{percentage(critical_normalized_matches, len(critical_rows))}%"
        f")",
    )


    print()
    print(
        "NULL HANDLING"
    )


    print(
        "Correct nulls:",
        correct_null_count,
    )


    print(
        "Hallucinations:",
        hallucination_count,
    )


    print(
        "Missed known fields:",
        missed_known_count,
    )


    print()
    print(
        "DOCUMENT-LEVEL ACCURACY"
    )


    print(
        "Fully correct:",
        f"{fully_correct_documents}/"
        f"{total_documents}",
        f"("
        f"{percentage(fully_correct_documents, total_documents)}%"
        f")",
    )


    print()
    print(
        "REVIEW SAFETY"
    )


    print(
        "AUTO_ACCEPT:",
        auto_accept_count,
    )


    print(
        "REVIEW_REQUIRED:",
        review_required_count,
    )


    print(
        "False auto-accepts:",
        false_auto_accept_count,
    )


    print(
        "False auto-accept rate "
        "among AUTO_ACCEPT:",
        f"{percentage(false_auto_accept_count, auto_accept_count)}%",
    )


    print(
        "Safe escalations:",
        safe_escalation_count,
    )


    print(
        "Safe escalation rate "
        "among incorrect documents:",
        f"{percentage(safe_escalation_count, incorrect_documents)}%",
    )


    if runtimes:

        print()
        print(
            "RUNTIME"
        )


        print(
            "Mean:",
            runtime_summary[
                "mean_seconds"
            ],
            "seconds",
        )


        print(
            "Median:",
            runtime_summary[
                "median_seconds"
            ],
            "seconds",
        )


    print()
    print(
        "OUTPUT FILES"
    )


    print(
        FIELD_RESULTS_PATH
    )

    print(
        DOCUMENT_RESULTS_PATH
    )

    print(
        SUMMARY_PATH
    )

    print(
        ERROR_CASES_PATH
    )


    print()
    print(
        "=" * 74
    )

    print(
        "[PASS] Phase 6D metrics generated."
    )

    print(
        "=" * 74
    )


if __name__ == "__main__":

    main()