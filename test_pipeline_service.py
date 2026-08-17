from dotenv import load_dotenv

from src.pipeline_service import (
    DocumentPipelineService,
)


load_dotenv()


pipeline = DocumentPipelineService()


image_path = (
    "samples/guard_license.jpg"
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