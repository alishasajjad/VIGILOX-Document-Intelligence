# VIGILOX Precision, Recall and F1 Evaluation Report

## Overview

This report evaluates structured field extraction performance using the existing labeled evaluation artifacts.
The calculation is fully offline and does not call OCR or LLM providers.

## Evaluation Dataset

| Item | Count |
|---|---:|
| Labeled Documents | **63** |
| Document Types | **3** |
| Total Field Comparisons | **441** |

Document categories:

- `guard_license`
- `id_card`
- `sia_badge`

## Metric Definition

- **True Positive (TP):** a non-null expected field was extracted correctly.
- **False Positive (FP):** a value was predicted where none was expected, or an incorrect non-null value was predicted.
- **False Negative (FN):** an expected value was missing, or the correct value was missed because a wrong non-null value was predicted.
- **Correct Null / TN:** both ground truth and prediction were null.

For an incorrect non-null value, the evaluation counts one FP and one FN.
Correct-null cases contribute to field accuracy but not to precision or recall.

## Primary Result: Normalized Field Extraction

| Metric | Value |
|---|---:|
| True Positives | 327 |
| False Positives | 5 |
| False Negatives | 5 |
| Correct Nulls / TN | 108 |
| Precision | **98.49%** |
| Recall | **98.49%** |
| F1 Score | **98.49%** |
| Field Accuracy | 98.64% |

Normalized matching removes benign formatting differences such as capitalization, punctuation and spacing while preserving semantic field-value correctness.

## Exact String Extraction

| Metric | Value |
|---|---:|
| True Positives | 315 |
| False Positives | 17 |
| False Negatives | 17 |
| Correct Nulls / TN | 108 |
| Precision | **94.88%** |
| Recall | **94.88%** |
| F1 Score | **94.88%** |
| Field Accuracy | 95.92% |

## Normalized Precision / Recall by Field

| Group | TP | FP | FN | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| `date_of_birth` | 40 | 2 | 1 | 95.24% | 97.56% | 96.39% |
| `expiry_date` | 61 | 1 | 1 | 98.39% | 98.39% | 98.39% |
| `full_name` | 63 | 0 | 0 | 100.00% | 100.00% | 100.00% |
| `id_number` | 21 | 0 | 0 | 100.00% | 100.00% | 100.00% |
| `issue_date` | 40 | 1 | 1 | 97.56% | 97.56% | 97.56% |
| `issuer` | 60 | 1 | 2 | 98.36% | 96.77% | 97.56% |
| `licence_number` | 42 | 0 | 0 | 100.00% | 100.00% | 100.00% |

## Normalized Precision / Recall by Document Type

| Group | TP | FP | FN | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| `guard_license` | 122 | 4 | 4 | 96.83% | 96.83% | 96.83% |
| `id_card` | 121 | 1 | 1 | 99.18% | 99.18% | 99.18% |
| `sia_badge` | 84 | 0 | 0 | 100.00% | 100.00% | 100.00% |

## Normalized Error Analysis

A total of **6 field rows** did not match after normalization.

| Sample | Type | Field | Ground Truth | Prediction | Outcome |
|---|---|---|---|---|---|
| `id_001` | `id_card` | `date_of_birth` | NULL | 2006-08-23 | `HALLUCINATION` |
| `guard_004` | `guard_license` | `expiry_date` | 2025-06-10 | 2025-10-06 | `VALUE_PRESENT` |
| `guard_004` | `guard_license` | `date_of_birth` | 1973-11-04 | 1973-04-11 | `VALUE_PRESENT` |
| `guard_004` | `guard_license` | `issue_date` | 2024-06-10 | 2024-10-06 | `VALUE_PRESENT` |
| `guard_020` | `guard_license` | `issuer` | TX DPS | ISSUED BY TX DPS | `VALUE_PRESENT` |
| `id_019` | `id_card` | `issuer` | National Population Registry | NULL | `MISSED_KNOWN_FIELD` |

## Final Evaluation Summary

| Metric | Score |
|---|---:|
| Labeled Documents | 63 |
| Exact Field Accuracy | 95.92% |
| Normalized Field Accuracy | 98.64% |
| Exact Precision | 94.88% |
| Exact Recall | 94.88% |
| Exact F1 | 94.88% |
| **Normalized Precision** | **98.49%** |
| **Normalized Recall** | **98.49%** |
| **Normalized F1** | **98.49%** |

## Reproducibility

Source data:

`evaluation/results/field_results.csv`

Generate this report with:

`python .\scripts\evaluation\compute_precision_recall.py`

**Evaluation basis:** 63 labeled security-document samples covering guard_license, id_card, sia_badge.
