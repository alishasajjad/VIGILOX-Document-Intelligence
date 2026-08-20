from dotenv import load_dotenv

from backend.app.services.pipeline_service import (

# ==========================================================
# TRACKED SYNTHETIC FIXTURE
# PHASE 8.2
# ==========================================================
#
# This test used to read samples/guard_license.jpg.
#
# samples/ is gitignored in full because
# samples/id_card.jpg is a photograph of an apparently REAL
# national identity card. That made this test unrunnable
# from a clean clone.
#
# It now reads the tracked seed fixture:
#
#     evaluation/images/guard_license/guard_001.jpg
#
# which is BYTE-IDENTICAL to the old samples/ file, so every
# OCR line ID and every expectation below is unchanged.
#
# The fixture is stable by design:
# scripts/evaluation/generate_synthetic_documents.py
# generates from index 2 upward and never regenerates the
# *_001 seed documents.
# ==========================================================

    DocumentPipelineService,
)


load_dotenv()


pipeline = DocumentPipelineService()


image_path = (
    "evaluation/images/guard_license/guard_001.jpg"
)


print()
print("=" * 70)
print("DOCUMENT PIPELINE TEST")
print("=" * 70)


result = pipeline.process(
    image_path
)


print(
    "Document Type:",
    result["extraction"][
        "document_type"
    ],
)

print(
    "Evidence Flags:",
    result["evidence_flags"],
)

print(
    "Anomaly Valid:",
    result[
        "anomaly_validation"
    ]["valid"],
)

print(
    "Review Decision:",
    result[
        "review_decision"
    ]["decision"],
)

print(
    "Priority:",
    result[
        "review_decision"
    ]["priority"],
)


assert (
    result["extraction"][
        "document_type"
    ]
    == "guard_license"
)


assert (
    result[
        "review_decision"
    ]["decision"]
    == "REVIEW_REQUIRED"
)


print()
print(
    "[PASS] Complete pipeline "
    "executed successfully."
)