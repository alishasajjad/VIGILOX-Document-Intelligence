from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_FILE = PROJECT_ROOT / "evaluation" / "results" / "field_results.csv"
OUTPUT_FILE = PROJECT_ROOT / "evaluation" / "reports" / "precision_recall_report.md"


def is_present(value: str | None) -> bool:
    return value is not None and bool(str(value).strip())


def as_bool(value: str | None) -> bool:
    return str(value).strip().lower() == "true"


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def calculate_metrics(
    rows: list[dict[str, str]],
    normalized: bool = True,
) -> dict[str, float | int]:

    gt_col = "normalized_ground_truth" if normalized else "ground_truth"
    pred_col = "normalized_prediction" if normalized else "prediction"
    match_col = "normalized_match" if normalized else "exact_match"

    tp = fp = fn = tn = correct = 0

    for row in rows:
        gt_present = is_present(row.get(gt_col))
        pred_present = is_present(row.get(pred_col))
        match = as_bool(row.get(match_col))

        if match:
            correct += 1

        if not gt_present and not pred_present:
            tn += 1

        elif not gt_present and pred_present:
            fp += 1

        elif gt_present and not pred_present:
            fn += 1

        elif match:
            tp += 1

        else:
            fp += 1
            fn += 1

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0

    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )

    accuracy = correct / len(rows) if rows else 0.0

    return {
        "rows": len(rows),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "accuracy": accuracy,
    }


def group_by(
    rows: list[dict[str, str]],
    column: str,
) -> dict[str, list[dict[str, str]]]:

    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)

    for row in rows:
        grouped[row.get(column) or "unknown"].append(row)

    return dict(grouped)


def metrics_table(
    metrics: dict[str, float | int],
) -> list[str]:

    return [
        "| Metric | Value |",
        "|---|---:|",
        f"| True Positives | {metrics['tp']} |",
        f"| False Positives | {metrics['fp']} |",
        f"| False Negatives | {metrics['fn']} |",
        f"| Correct Nulls / TN | {metrics['tn']} |",
        f"| Precision | **{pct(float(metrics['precision']))}** |",
        f"| Recall | **{pct(float(metrics['recall']))}** |",
        f"| F1 Score | **{pct(float(metrics['f1']))}** |",
        f"| Field Accuracy | {pct(float(metrics['accuracy']))} |",
    ]


def grouped_table(
    groups: dict[str, list[dict[str, str]]],
) -> list[str]:

    lines = [
        "| Group | TP | FP | FN | Precision | Recall | F1 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]

    for name in sorted(groups):
        metrics = calculate_metrics(
            groups[name],
            normalized=True,
        )

        lines.append(
            f"| `{name}` "
            f"| {metrics['tp']} "
            f"| {metrics['fp']} "
            f"| {metrics['fn']} "
            f"| {pct(float(metrics['precision']))} "
            f"| {pct(float(metrics['recall']))} "
            f"| {pct(float(metrics['f1']))} |"
        )

    return lines


def mismatch_table(
    rows: list[dict[str, str]],
) -> list[str]:

    mismatches = [
        row
        for row in rows
        if not as_bool(row.get("normalized_match"))
    ]

    lines = [
        "| Sample | Type | Field | Ground Truth | Prediction | Outcome |",
        "|---|---|---|---|---|---|",
    ]

    for row in mismatches:
        ground_truth = (
            row.get("ground_truth") or "NULL"
        ).replace("|", "\\|")

        prediction = (
            row.get("prediction") or "NULL"
        ).replace("|", "\\|")

        outcome = (
            row.get("null_outcome") or ""
        ).replace("|", "\\|")

        lines.append(
            f"| `{row.get('sample_id', '')}` "
            f"| `{row.get('document_type', '')}` "
            f"| `{row.get('field_name', '')}` "
            f"| {ground_truth} "
            f"| {prediction} "
            f"| `{outcome}` |"
        )

    return lines


def build_report(
    rows: list[dict[str, str]],
) -> str:

    normalized = calculate_metrics(
        rows,
        normalized=True,
    )

    exact = calculate_metrics(
        rows,
        normalized=False,
    )

    sample_ids = sorted({
        row["sample_id"]
        for row in rows
    })

    document_types = sorted({
        row["document_type"]
        for row in rows
    })

    field_groups = group_by(
        rows,
        "field_name",
    )

    document_type_groups = group_by(
        rows,
        "document_type",
    )

    mismatch_count = sum(
        1
        for row in rows
        if not as_bool(
            row.get("normalized_match")
        )
    )

    lines: list[str] = []

    lines.extend([
        "# VIGILOX Precision, Recall and F1 Evaluation Report",
        "",
        "## Overview",
        "",
        (
            "This report evaluates structured field extraction "
            "performance using the existing labeled evaluation artifacts."
        ),
        (
            "The calculation is fully offline and does not call OCR "
            "or LLM providers."
        ),
        "",
        "## Evaluation Dataset",
        "",
        "| Item | Count |",
        "|---|---:|",
        f"| Labeled Documents | **{len(sample_ids)}** |",
        f"| Document Types | **{len(document_types)}** |",
        f"| Total Field Comparisons | **{len(rows)}** |",
        "",
        "Document categories:",
        "",
    ])

    lines.extend(
        f"- `{name}`"
        for name in document_types
    )

    lines.extend([
        "",
        "## Metric Definition",
        "",
        (
            "- **True Positive (TP):** a non-null expected field "
            "was extracted correctly."
        ),
        (
            "- **False Positive (FP):** a value was predicted where "
            "none was expected, or an incorrect non-null value was predicted."
        ),
        (
            "- **False Negative (FN):** an expected value was missing, "
            "or the correct value was missed because a wrong non-null "
            "value was predicted."
        ),
        (
            "- **Correct Null / TN:** both ground truth and "
            "prediction were null."
        ),
        "",
        (
            "For an incorrect non-null value, the evaluation counts "
            "one FP and one FN."
        ),
        (
            "Correct-null cases contribute to field accuracy but not "
            "to precision or recall."
        ),
        "",
        "## Primary Result: Normalized Field Extraction",
        "",
    ])

    lines.extend(
        metrics_table(normalized)
    )

    lines.extend([
        "",
        (
            "Normalized matching removes benign formatting differences "
            "such as capitalization, punctuation and spacing while "
            "preserving semantic field-value correctness."
        ),
        "",
        "## Exact String Extraction",
        "",
    ])

    lines.extend(
        metrics_table(exact)
    )

    lines.extend([
        "",
        "## Normalized Precision / Recall by Field",
        "",
    ])

    lines.extend(
        grouped_table(field_groups)
    )

    lines.extend([
        "",
        "## Normalized Precision / Recall by Document Type",
        "",
    ])

    lines.extend(
        grouped_table(document_type_groups)
    )

    lines.extend([
        "",
        "## Normalized Error Analysis",
        "",
        (
            f"A total of **{mismatch_count} field rows** "
            "did not match after normalization."
        ),
        "",
    ])

    lines.extend(
        mismatch_table(rows)
    )

    lines.extend([
        "",
        "## Final Evaluation Summary",
        "",
        "| Metric | Score |",
        "|---|---:|",
        f"| Labeled Documents | {len(sample_ids)} |",
        (
            f"| Exact Field Accuracy | "
            f"{pct(float(exact['accuracy']))} |"
        ),
        (
            f"| Normalized Field Accuracy | "
            f"{pct(float(normalized['accuracy']))} |"
        ),
        (
            f"| Exact Precision | "
            f"{pct(float(exact['precision']))} |"
        ),
        (
            f"| Exact Recall | "
            f"{pct(float(exact['recall']))} |"
        ),
        (
            f"| Exact F1 | "
            f"{pct(float(exact['f1']))} |"
        ),
        (
            f"| **Normalized Precision** | "
            f"**{pct(float(normalized['precision']))}** |"
        ),
        (
            f"| **Normalized Recall** | "
            f"**{pct(float(normalized['recall']))}** |"
        ),
        (
            f"| **Normalized F1** | "
            f"**{pct(float(normalized['f1']))}** |"
        ),
        "",
        "## Reproducibility",
        "",
        "Source data:",
        "",
        "`evaluation/results/field_results.csv`",
        "",
        "Generate this report with:",
        "",
        "`python .\\scripts\\evaluation\\compute_precision_recall.py`",
        "",
        (
            f"**Evaluation basis:** {len(sample_ids)} labeled "
            "security-document samples covering "
            + ", ".join(document_types)
            + "."
        ),
        "",
    ])

    return "\n".join(lines)


def main() -> None:

    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Evaluation input file not found: {INPUT_FILE}"
        )

    with INPUT_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        rows = list(
            csv.DictReader(file)
        )

    if not rows:
        raise ValueError(
            "field_results.csv contains no rows."
        )

    required_columns = {
        "sample_id",
        "document_type",
        "field_name",
        "ground_truth",
        "prediction",
        "exact_match",
        "normalized_match",
        "normalized_ground_truth",
        "normalized_prediction",
        "null_outcome",
    }

    missing = (
        required_columns
        - set(rows[0].keys())
    )

    if missing:
        raise ValueError(
            "Missing required columns: "
            + ", ".join(
                sorted(missing)
            )
        )

    report = build_report(rows)

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUTPUT_FILE.write_text(
        report,
        encoding="utf-8",
    )

    normalized = calculate_metrics(
        rows,
        normalized=True,
    )

    exact = calculate_metrics(
        rows,
        normalized=False,
    )

    document_count = len({
        row["sample_id"]
        for row in rows
    })

    print("=" * 64)
    print(
        "VIGILOX PRECISION / RECALL EVALUATION"
    )
    print("=" * 64)

    print(
        f"Documents evaluated : {document_count}"
    )

    print(
        f"Field comparisons   : {len(rows)}"
    )

    print()

    print("Normalized")

    print(
        f"  Precision : "
        f"{pct(float(normalized['precision']))}"
    )

    print(
        f"  Recall    : "
        f"{pct(float(normalized['recall']))}"
    )

    print(
        f"  F1        : "
        f"{pct(float(normalized['f1']))}"
    )

    print()

    print("Exact")

    print(
        f"  Precision : "
        f"{pct(float(exact['precision']))}"
    )

    print(
        f"  Recall    : "
        f"{pct(float(exact['recall']))}"
    )

    print(
        f"  F1        : "
        f"{pct(float(exact['f1']))}"
    )

    print()

    print(
        f"Report written to: {OUTPUT_FILE}"
    )

    print("=" * 64)


if __name__ == "__main__":
    main()