from sqlalchemy import (
    func,
    select,
    text,
)

from database.database import (
    SessionLocal,
)

from database.models import (
    AuditEventModel,
    DocumentAnalysisModel,
    DocumentModel,
    HumanReviewModel,
)

from backend.app.services.persistence_service import (
    PersistenceService,
)

from backend.app.services.human_review_service import (
    HumanReviewService,
)


print()
print("=" * 70)
print(
    "PHASE 6B — FINAL DATABASE "
    "INTEGRITY TEST"
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
            "2026-08-18",

        "expiry": {
            "value":
                "2026-01-01",

            "status":
                "EXPIRED",

            "days_until_expiry":
                -229,
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
                    "Document expired.",
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
# SERVICES
# ==========================================================

persistence_service = (
    PersistenceService()
)

human_review_service = (
    HumanReviewService()
)


# ==========================================================
# TEST 1 — SAVE DOCUMENT + ANALYSIS + MACHINE AUDIT
# ==========================================================

saved_document = (
    persistence_service
    .save_processed_document(
        original_filename=(
            "phase6b_final_test.jpg"
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
    saved_document[
        "document_id"
    ]
)


print(
    "Document ID:",
    document_id,
)


assert (
    saved_document[
        "analysis_id"
    ]
)

assert (
    saved_document[
        "machine_audit_id"
    ]
)


print(
    "Document persistence:",
    "OK"
)


# ==========================================================
# TEST 2 — HUMAN REVIEW
# ==========================================================

review_result = (
    human_review_service
    .submit_review(
        document_id=(
            document_id
        ),

        reviewer_id=(
            "reviewer-final-test"
        ),

        review_result=(
            pipeline_result[
                "review_decision"
            ]
        ),

        action=(
            "APPROVE"
        ),

        notes=(
            "Approved during final "
            "database verification."
        ),
    )
)


saved_review = (
    persistence_service
    .save_human_review(
        review_result=(
            review_result
        )
    )
)


assert (
    saved_review[
        "review_id"
    ]
)

assert (
    saved_review[
        "audit_event_id"
    ]
)


print(
    "Human review persistence:",
    "OK"
)


# ==========================================================
# TEST 3 — VERIFY DATABASE RELATIONSHIPS
# ==========================================================

with SessionLocal() as session:

    document_count = (
        session.scalar(
            select(
                func.count()
            )
            .select_from(
                DocumentModel
            )
            .where(
                DocumentModel.id
                == document_id
            )
        )
    )


    analysis_count = (
        session.scalar(
            select(
                func.count()
            )
            .select_from(
                DocumentAnalysisModel
            )
            .where(
                DocumentAnalysisModel
                .document_id
                == document_id
            )
        )
    )


    review_count = (
        session.scalar(
            select(
                func.count()
            )
            .select_from(
                HumanReviewModel
            )
            .where(
                HumanReviewModel
                .document_id
                == document_id
            )
        )
    )


    audit_count = (
        session.scalar(
            select(
                func.count()
            )
            .select_from(
                AuditEventModel
            )
            .where(
                AuditEventModel
                .document_id
                == document_id
            )
        )
    )


assert document_count == 1
assert analysis_count == 1
assert review_count == 1
assert audit_count == 2


print(
    "Document rows:",
    document_count,
)

print(
    "Analysis rows:",
    analysis_count,
)

print(
    "Human review rows:",
    review_count,
)

print(
    "Audit rows:",
    audit_count,
)


# ==========================================================
# TEST 4 — VERIFY JSONB DIRECTLY IN POSTGRESQL
# ==========================================================

with SessionLocal() as session:

    result = session.execute(
        text(
            """
            SELECT
                extraction ->> 'document_type'
                    AS document_type,

                review_decision ->> 'decision'
                    AS decision,

                review_decision ->> 'priority'
                    AS priority

            FROM document_analyses

            WHERE document_id = :document_id
            """
        ),

        {
            "document_id":
                document_id
        },
    ).one()


assert (
    result.document_type
    == "guard_license"
)

assert (
    result.decision
    == "REVIEW_REQUIRED"
)

assert (
    result.priority
    == "MEDIUM"
)


print(
    "JSONB query:",
    "OK"
)


# ==========================================================
# TEST 5 — INVALID DOCUMENT REVIEW MUST FAIL
# ==========================================================

invalid_review_result = (
    human_review_service
    .submit_review(
        document_id=(
            "missing-document-id"
        ),

        reviewer_id=(
            "reviewer-final-test"
        ),

        review_result=(
            pipeline_result[
                "review_decision"
            ]
        ),

        action=(
            "APPROVE"
        ),
    )
)


try:

    persistence_service.save_human_review(
        review_result=(
            invalid_review_result
        )
    )

    raise AssertionError(
        "Missing document review "
        "should not persist."
    )

except ValueError:

    pass


print(
    "Orphan review prevention:",
    "OK"
)


# ==========================================================
# TEST 6 — VERIFY NO ORPHAN REVIEW WAS CREATED
# ==========================================================

with SessionLocal() as session:

    orphan_reviews = (
        session.scalar(
            select(
                func.count()
            )
            .select_from(
                HumanReviewModel
            )
            .where(
                HumanReviewModel
                .document_id
                == "missing-document-id"
            )
        )
    )


    orphan_audits = (
        session.scalar(
            select(
                func.count()
            )
            .select_from(
                AuditEventModel
            )
            .where(
                AuditEventModel
                .document_id
                == "missing-document-id"
            )
        )
    )


assert orphan_reviews == 0
assert orphan_audits == 0


print(
    "No orphan database records:",
    "OK"
)


# ==========================================================
# TEST 7 — CASCADE DELETE
# ==========================================================

with SessionLocal.begin() as session:

    document = session.get(
        DocumentModel,
        document_id,
    )

    assert (
        document
        is not None
    )

    session.delete(
        document
    )


# ==========================================================
# TEST 8 — VERIFY CHILD RECORDS WERE CASCADED
# ==========================================================

with SessionLocal() as session:

    document_count = (
        session.scalar(
            select(
                func.count()
            )
            .select_from(
                DocumentModel
            )
            .where(
                DocumentModel.id
                == document_id
            )
        )
    )


    analysis_count = (
        session.scalar(
            select(
                func.count()
            )
            .select_from(
                DocumentAnalysisModel
            )
            .where(
                DocumentAnalysisModel
                .document_id
                == document_id
            )
        )
    )


    review_count = (
        session.scalar(
            select(
                func.count()
            )
            .select_from(
                HumanReviewModel
            )
            .where(
                HumanReviewModel
                .document_id
                == document_id
            )
        )
    )


    audit_count = (
        session.scalar(
            select(
                func.count()
            )
            .select_from(
                AuditEventModel
            )
            .where(
                AuditEventModel
                .document_id
                == document_id
            )
        )
    )


assert document_count == 0
assert analysis_count == 0
assert review_count == 0
assert audit_count == 0


print(
    "Cascade delete:",
    "OK"
)


# ==========================================================
# SUCCESS
# ==========================================================

print()
print("=" * 70)
print(
    "[PASS] Phase 6B PostgreSQL "
    "integrity verification passed."
)
print("=" * 70)