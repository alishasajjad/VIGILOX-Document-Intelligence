from dotenv import load_dotenv


# ==========================================================
# ENVIRONMENT
# ==========================================================

load_dotenv()


from database.database import (
    SessionLocal,
)

from backend.app.services.persistence_service import (
    PersistenceService,
)

from database.repositories import (
    DocumentAnalysisRepository,
    DocumentRepository,
)

from backend.app.services.pipeline_service import (
    DocumentPipelineService,
)


print()
print("=" * 70)
print(
    "PHASE 6B — REAL PIPELINE PERSISTENCE TEST"
)
print("=" * 70)


# ==========================================================
# TEST DOCUMENT
# ==========================================================

image_path = (
    "samples/guard_license.jpg"
)

filename = (
    "guard_license.jpg"
)

content_type = (
    "image/jpeg"
)


# ==========================================================
# 1. RUN REAL DOCUMENT PIPELINE
# ==========================================================

print()
print(
    "Running document pipeline..."
)

pipeline = (
    DocumentPipelineService()
)

pipeline_result = (
    pipeline.process(
        image_path
    )
)


document_type = (
    pipeline_result[
        "extraction"
    ][
        "document_type"
    ]
)

review_decision = (
    pipeline_result[
        "review_decision"
    ][
        "decision"
    ]
)

priority = (
    pipeline_result[
        "review_decision"
    ][
        "priority"
    ]
)


print(
    "Document Type:",
    document_type,
)

print(
    "Review Decision:",
    review_decision,
)

print(
    "Priority:",
    priority,
)


assert (
    document_type
    == "guard_license"
)


# ==========================================================
# 2. PERSIST REAL PIPELINE RESULT
# ==========================================================

print()
print(
    "Saving pipeline result "
    "to PostgreSQL..."
)


persistence_service = (
    PersistenceService()
)


saved = (
    persistence_service
    .save_processed_document(
        original_filename=filename,
        content_type=content_type,
        pipeline_result=pipeline_result,
    )
)


document_id = (
    saved[
        "document_id"
    ]
)

analysis_id = (
    saved[
        "analysis_id"
    ]
)


print(
    "Document ID:",
    document_id,
)

print(
    "Analysis ID:",
    analysis_id,
)


assert document_id
assert analysis_id


# ==========================================================
# 3. READ FROM A NEW DATABASE SESSION
# ==========================================================

print()
print(
    "Reading persisted result "
    "from PostgreSQL..."
)


with SessionLocal() as session:

    document_repository = (
        DocumentRepository(
            session
        )
    )

    analysis_repository = (
        DocumentAnalysisRepository(
            session
        )
    )


    stored_document = (
        document_repository
        .get_document(
            document_id
        )
    )

    stored_analysis = (
        analysis_repository
        .get_by_document_id(
            document_id
        )
    )


    # ======================================================
    # VERIFY DOCUMENT
    # ======================================================

    assert (
        stored_document
        is not None
    )

    assert (
        stored_document
        .original_filename
        == filename
    )

    assert (
        stored_document
        .content_type
        == content_type
    )

    assert (
        stored_document
        .document_type
        == "guard_license"
    )

    assert (
        stored_document
        .processing_status
        == "PROCESSED"
    )


    # ======================================================
    # VERIFY ANALYSIS
    # ======================================================

    assert (
        stored_analysis
        is not None
    )

    assert (
        stored_analysis.id
        == analysis_id
    )


    assert (
        stored_analysis
        .extraction[
            "document_type"
        ]
        == "guard_license"
    )


    assert (
        stored_analysis
        .extraction[
            "licence_number"
        ][
            "value"
        ]
        == "12345678"
    )


    assert (
        stored_analysis
        .anomaly_validation[
            "has_anomalies"
        ]
        is True
    )


    assert (
        stored_analysis
        .review_decision[
            "decision"
        ]
        == "REVIEW_REQUIRED"
    )


    assert (
        stored_analysis
        .review_decision[
            "priority"
        ]
        == "MEDIUM"
    )


    stored_ocr_count = len(
        stored_analysis
        .ocr_lines
    )


print(
    "Stored OCR Lines:",
    stored_ocr_count,
)

print(
    "Persistent read:",
    "OK"
)


# ==========================================================
# SUCCESS
# ==========================================================

print()
print(
    "[PASS] Real document pipeline "
    "result persisted successfully."
)

print()
print(
    "Persisted Document ID:",
    document_id,
)