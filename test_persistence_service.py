from sqlalchemy import delete

from src.db.database import (
    SessionLocal,
)

from src.db.models import (
    DocumentAnalysisModel,
    DocumentModel,
)

from src.db.persistence_service import (
    PersistenceService,
)

from src.db.repositories import (
    DocumentAnalysisRepository,
    DocumentRepository,
)


print()
print("=" * 70)
print(
    "PHASE 6B — PERSISTENCE SERVICE TEST"
)
print("=" * 70)


# ==========================================================
# DETERMINISTIC PIPELINE RESULT
# ==========================================================

pipeline_result = {

    "extraction": {
        "document_type":
            "guard_license",

        "full_name": {
            "value":
                "SAMPLE,JANE",

            "source_line_ids": [
                "L14"
            ],
        },

        "licence_number": {
            "value":
                "12345678",

            "source_line_ids": [
                "L5",
                "L6",
            ],
        },

        "id_number": {
            "value": None,
            "source_line_ids": [],
        },

        "expiry_date": {
            "value":
                "2026-01-01",

            "source_line_ids": [
                "L8",
                "L9",
            ],
        },

        "date_of_birth": {
            "value":
                "1990-01-01",

            "source_line_ids": [
                "L11",
                "L12",
            ],
        },

        "issue_date": {
            "value":
                "2025-01-01",

            "source_line_ids": [
                "L4"
            ],
        },

        "issuer": {
            "value":
                "TX DPS",

            "source_line_ids": [
                "L15"
            ],
        },
    },


    "ocr_lines": [
        {
            "text":
                "LICENSE",

            "confidence":
                0.9997,

            "bbox": [
                349,
                101,
                393,
                115,
            ],
        },
        {
            "text":
                "12345678",

            "confidence":
                0.9999,

            "bbox": [
                397,
                97,
                475,
                114,
            ],
        },
    ],


    "evidence_flags": [],


    "field_confidence": {
        "licence_number": {
            "value":
                "12345678",

            "confidence":
                0.9997,

            "status":
                "VALID",
        }
    },


    "date_validation": {
        "reference_date":
            "2026-08-17",

        "expiry": {
            "value":
                "2026-01-01",

            "status":
                "EXPIRED",

            "days_until_expiry":
                -228,
        },

        "logical_issues": [],

        "valid":
            True,
    },


    "anomaly_validation": {
        "document_type":
            "guard_license",

        "valid":
            True,

        "has_anomalies":
            True,

        "error_count":
            0,

        "warning_count":
            1,

        "issues": [
            {
                "code":
                    "DOCUMENT_EXPIRED",

                "severity":
                    "WARNING",

                "field":
                    "expiry_date",

                "message":
                    (
                        "The document has "
                        "passed its validated "
                        "expiry date."
                    ),
            }
        ],
    },


    "review_decision": {
        "decision":
            "REVIEW_REQUIRED",

        "review_required":
            True,

        "priority":
            "MEDIUM",

        "reason_codes": [
            "DOCUMENT_EXPIRED"
        ],

        "issues": [
            {
                "code":
                    "DOCUMENT_EXPIRED",

                "severity":
                    "WARNING",

                "field":
                    "expiry_date",
            }
        ],
    },
}


# ==========================================================
# TEST 1 — SAVE DOCUMENT + ANALYSIS
# ==========================================================

service = PersistenceService()


saved = (
    service
    .save_processed_document(
        original_filename=(
            "guard_license_test.jpg"
        ),
        content_type=(
            "image/jpeg"
        ),
        pipeline_result=(
            pipeline_result
        ),
    )
)


document_id = (
    saved["document_id"]
)

analysis_id = (
    saved["analysis_id"]
)


print(
    "Document ID:",
    document_id,
)

print(
    "Analysis ID:",
    analysis_id,
)

print(
    "Document Type:",
    saved["document_type"],
)

print(
    "Processing Status:",
    saved["processing_status"],
)


assert document_id
assert analysis_id

assert (
    saved["document_type"]
    == "guard_license"
)

assert (
    saved["processing_status"]
    == "PROCESSED"
)


# ==========================================================
# TEST 2 — READ FROM NEW DATABASE SESSION
# ==========================================================

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


    assert (
        stored_document
        is not None
    )

    assert (
        stored_analysis
        is not None
    )


    assert (
        stored_document
        .original_filename
        == "guard_license_test.jpg"
    )


    assert (
        stored_document
        .document_type
        == "guard_license"
    )


    assert (
        stored_analysis
        .id
        == analysis_id
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


print(
    "Persistent read:",
    "OK"
)


# ==========================================================
# TEST 3 — CLEAN UP TEST DATA
# ==========================================================

with SessionLocal.begin() as session:

    session.execute(
        delete(
            DocumentAnalysisModel
        )
        .where(
            DocumentAnalysisModel
            .document_id
            == document_id
        )
    )

    session.execute(
        delete(
            DocumentModel
        )
        .where(
            DocumentModel.id
            == document_id
        )
    )


print(
    "Test cleanup:",
    "OK"
)


# ==========================================================
# SUCCESS
# ==========================================================

print()
print(
    "[PASS] Document and analysis "
    "persistence is working."
)