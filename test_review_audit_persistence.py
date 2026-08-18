from sqlalchemy import delete

from src.db.database import (
    SessionLocal,
)

from src.db.models import (
    DocumentModel,
)

from src.db.persistence_service import (
    PersistenceService,
)

from src.db.repositories import (
    AuditEventRepository,
    DocumentAnalysisRepository,
    HumanReviewRepository,
)

from src.human_review_service import (
    HumanReviewService,
)


print()
print("=" * 70)
print(
    "PHASE 6B — HUMAN REVIEW + AUDIT "
    "PERSISTENCE TEST"
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


    "ocr_lines": [],


    "evidence_flags": [],


    "field_confidence": {},


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
# TEST 1 — SAVE MACHINE ANALYSIS
# ==========================================================

saved_document = (
    persistence_service
    .save_processed_document(
        original_filename=(
            "review_test.jpg"
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

print(
    "Machine Audit ID:",
    saved_document[
        "machine_audit_id"
    ],
)


# ==========================================================
# TEST 2 — CREATE HUMAN CORRECTION
# ==========================================================

review_result = (
    human_review_service
    .submit_review(
        document_id=(
            document_id
        ),

        reviewer_id=(
            "reviewer-001"
        ),

        review_result=(
            pipeline_result[
                "review_decision"
            ]
        ),

        action=(
            "CORRECT"
        ),

        notes=(
            "Expiry date corrected "
            "after manual verification."
        ),

        corrections={
            "expiry_date":
                "2027-01-01"
        },
    )
)


assert (
    review_result[
        "human_action"
    ]
    == "CORRECT"
)


# ==========================================================
# TEST 3 — PERSIST REVIEW + AUDIT
# ==========================================================

saved_review = (
    persistence_service
    .save_human_review(
        review_result=(
            review_result
        )
    )
)


review_id = (
    saved_review[
        "review_id"
    ]
)


print(
    "Review ID:",
    review_id,
)

print(
    "Human Audit ID:",
    saved_review[
        "audit_event_id"
    ],
)


# ==========================================================
# TEST 4 — READ FROM NEW SESSION
# ==========================================================

with SessionLocal() as session:

    review_repository = (
        HumanReviewRepository(
            session
        )
    )

    audit_repository = (
        AuditEventRepository(
            session
        )
    )

    analysis_repository = (
        DocumentAnalysisRepository(
            session
        )
    )


    stored_review = (
        review_repository
        .get_review(
            review_id
        )
    )


    audit_events = (
        audit_repository
        .get_by_document_id(
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
    # HUMAN REVIEW ASSERTIONS
    # ======================================================

    assert (
        stored_review
        is not None
    )

    assert (
        stored_review
        .reviewer_id
        == "reviewer-001"
    )

    assert (
        stored_review
        .human_action
        == "CORRECT"
    )

    assert (
        stored_review
        .corrections[
            "expiry_date"
        ]
        == "2027-01-01"
    )


    # ======================================================
    # ORIGINAL MACHINE ANALYSIS MUST REMAIN UNCHANGED
    # ======================================================

    assert (
        stored_analysis
        .extraction[
            "expiry_date"
        ][
            "value"
        ]
        == "2026-01-01"
    )


    # ======================================================
    # AUDIT ASSERTIONS
    # ======================================================

    assert len(
        audit_events
    ) == 2


    event_types = {
        event.event_type
        for event
        in audit_events
    }


    assert (
        "MACHINE_REVIEW_DECISION"
        in event_types
    )

    assert (
        "HUMAN_REVIEW"
        in event_types
    )


    human_event = next(
        event
        for event
        in audit_events
        if event.event_type
        == "HUMAN_REVIEW"
    )


    assert (
        human_event
        .actor_type
        == "HUMAN"
    )

    assert (
        human_event
        .actor_id
        == "reviewer-001"
    )

    assert (
        human_event
        .details[
            "human_action"
        ]
        == "CORRECT"
    )

    assert (
        human_event
        .details[
            "corrections"
        ][
            "expiry_date"
        ]
        == "2027-01-01"
    )


print(
    "Human review persistence:",
    "OK"
)

print(
    "Audit history:",
    "2 events"
)

print(
    "Original extraction preserved:",
    "OK"
)


# ==========================================================
# TEST 5 — CLEAN UP
# ==========================================================

with SessionLocal.begin() as session:

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
    "Cascade cleanup:",
    "OK"
)


# ==========================================================
# SUCCESS
# ==========================================================

print()
print(
    "[PASS] Human review and audit "
    "persistence is working."
)