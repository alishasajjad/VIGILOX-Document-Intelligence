from backend.app.services.review_decision_service import (
    ReviewDecisionService,
)

from backend.app.services.document_anomaly_validator import (
    DocumentAnomalyValidator,
)

from backend.app.services.date_logical_validator import DateLogicalValidator

from backend.app.services.confidence_service import ConfidenceService

from pathlib import Path

from dotenv import load_dotenv

from backend.app.services.ocr_service import (
    OCRService,
)

from backend.app.services.extraction_service import (
    ExtractionService,
)

from backend.app.services.evidence_validator import (

# ==========================================================
# SAFE SYNTHETIC FIXTURES
# PHASE 8.1
# ==========================================================
#
# These point at tracked, generated documents under
# evaluation/images/ rather than the untracked samples/
# directory.
#
# A Phase 8 content inspection found samples/id_card.jpg to be
# a photograph of an apparently REAL national identity card
# carrying personal data. samples/ is therefore gitignored in
# full, and nothing here depends on it any more.
#
# evaluation/images/ is versioned and produced by
# scripts/evaluation/generate_synthetic_documents.py, so a
# fresh clone can run this file unchanged.
# ==========================================================

    EvidenceValidator,
)


# ==========================================================
# LOAD ENVIRONMENT VARIABLES
# ==========================================================

load_dotenv()


# ==========================================================
# INITIALIZE SERVICES
# ==========================================================

ocr_service = OCRService()

extraction_service = (
    ExtractionService()
)

evidence_validator = (
    EvidenceValidator()
)

confidence_service = ConfidenceService()

date_logical_validator = DateLogicalValidator()

document_anomaly_validator = (
    DocumentAnomalyValidator(
        low_confidence_threshold=0.90
    )
)

review_decision_service = (
    ReviewDecisionService()
)

# ==========================================================
# DOCUMENT
# ==========================================================

image_path = (
    "evaluation/images/id_card/id_001.jpg"
)


if not Path(
    image_path
).exists():

    raise FileNotFoundError(
        f"Image not found: "
        f"{image_path}"
    )


# ==========================================================
# STEP 1 — OCR
# ==========================================================

ocr_lines = (
    ocr_service.extract(
        image_path
    )
)


print(
    "\n========== RAW OCR ==========\n"
)


for index, line in enumerate(
    ocr_lines
):

    print(
        f"[L{index}] "
        f"{line['text']:<35}"
        f"{line['confidence']:.2%}"
    )


# ==========================================================
# STEP 2 — STRUCTURED EXTRACTION
# ==========================================================

structured = (
    extraction_service.extract(
        ocr_lines
    )
)


print(
    "\n========== STRUCTURED EXTRACTION ==========\n"
)


print(
    structured.model_dump_json(
        indent=2
    )
)


# ==========================================================
# STEP 3 — EVIDENCE VALIDATION V1 + V2
# ==========================================================

flags = (
    evidence_validator.validate(
        structured,
        ocr_lines,
    )
)


print(
    "\n========== EVIDENCE VALIDATION ==========\n"
)


if flags:

    for flag in flags:

        print(
            f"[REVIEW] {flag}"
        )

else:

    print(
        "All evidence references are valid."
    )

confidence_results = confidence_service.calculate(
    structured,
    ocr_lines,
    flags,
)

print(
    "\n========== FIELD CONFIDENCE ==========\n"
)


for field_name, result in confidence_results.items():

    confidence = result["confidence"]


    if confidence is None:

        confidence_text = "N/A"

    else:

        confidence_text = (
            f"{confidence:.2%}"
        )


    print(
        f"{field_name:<20}"
        f"{str(result['value']):<35}"
        f"{confidence_text:<10}"
        f"{result['status']}"
    )

date_validation = (
    date_logical_validator.validate(
        structured,
        confidence_results,
    )
)


print(
    "\n========== DATE & LOGICAL VALIDATION ==========\n"
)


print(
    f"Reference Date: "
    f"{date_validation['reference_date']}"
)


print(
    "\nDate Fields:"
)


for field_name, result in (
    date_validation["date_fields"].items()
):

    print(
        f"{field_name:<20}"
        f"{str(result['value']):<15}"
        f"{result['status']}"
    )


print(
    "\nExpiry Status:"
)


expiry = date_validation["expiry"]


print(
    f"Value: "
    f"{expiry['value']}"
)

print(
    f"Status: "
    f"{expiry['status']}"
)

print(
    f"Days Until Expiry: "
    f"{expiry['days_until_expiry']}"
)


print(
    "\nLogical Issues:"
)


if date_validation["logical_issues"]:

    for issue in (
        date_validation[
            "logical_issues"
        ]
    ):

        print(
            f"[REVIEW] "
            f"{issue['code']} - "
            f"{issue['message']}"
        )

else:

    print(
        "No logical date issues found."
    )

anomaly_result = (
    document_anomaly_validator.validate(
        structured,
        confidence_results,
        date_validation,
    )
)

print(
    "\n========== DOCUMENT ANOMALY VALIDATION ==========\n"
)


print(
    f"Document Type: "
    f"{anomaly_result['document_type']}"
)

print(
    f"Valid: "
    f"{anomaly_result['valid']}"
)

print(
    f"Has Anomalies: "
    f"{anomaly_result['has_anomalies']}"
)

print(
    f"Errors: "
    f"{anomaly_result['error_count']}"
)

print(
    f"Warnings: "
    f"{anomaly_result['warning_count']}"
)


print(
    "\nIssues:"
)


if anomaly_result["issues"]:

    for issue in anomaly_result["issues"]:

        print(
            f"[{issue['severity']}] "
            f"{issue['code']} "
            f"- {issue['message']}"
        )

else:

    print(
        "No document anomalies detected."
    )

review_result = (
    review_decision_service.decide(
        anomaly_result
    )
)


print(
    "\n========== HUMAN REVIEW DECISION ==========\n"
)


print(
    f"Decision: "
    f"{review_result['decision']}"
)

print(
    f"Review Required: "
    f"{review_result['review_required']}"
)

print(
    f"Priority: "
    f"{review_result['priority']}"
)


print(
    "\nReasons:"
)


if review_result["reason_codes"]:

    for code in (
        review_result["reason_codes"]
    ):

        print(
            f"- {code}"
        )

else:

    print(
        "No review reasons."
    )