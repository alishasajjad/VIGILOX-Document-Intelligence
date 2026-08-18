from dotenv import load_dotenv


# ==========================================================
# ENVIRONMENT
# ==========================================================

load_dotenv()


from fastapi.testclient import TestClient
from sqlalchemy import (
    func,
    select,
)

from src.api.main import app

from src.db.database import (
    SessionLocal,
)

from src.db.models import (
    AuditEventModel,
    DocumentAnalysisModel,
    DocumentModel,
    HumanReviewModel,
)


print()
print("=" * 70)
print(
    "PHASE 6C — FULL END-TO-END "
    "API + POSTGRESQL TEST"
)
print("=" * 70)


document_id = None


try:

    # ======================================================
    # START FASTAPI TEST CLIENT
    # ======================================================

    with TestClient(
        app
    ) as client:

        # ==================================================
        # TEST 1 — HEALTH CHECK
        # ==================================================

        response = client.get(
            "/health"
        )


        assert (
            response.status_code
            == 200
        )


        health = (
            response.json()
        )


        assert (
            health[
                "status"
            ]
            == "ok"
        )


        print(
            "Health check:",
            "OK"
        )


        # ==================================================
        # TEST 2 — ANALYZE REAL DOCUMENT
        # ==================================================

        print()
        print(
            "Running real document "
            "analysis..."
        )


        with open(
            "samples/guard_license.jpg",
            "rb",
        ) as image_file:

            response = client.post(
                "/api/v1/documents/analyze",

                files={
                    "file": (
                        "guard_license.jpg",
                        image_file,
                        "image/jpeg",
                    )
                },
            )


        assert (
            response.status_code
            == 200
        )


        analyze_result = (
            response.json()
        )


        assert (
            analyze_result[
                "status"
            ]
            == "success"
        )


        document_id = (
            analyze_result[
                "document_id"
            ]
        )


        analysis_id = (
            analyze_result[
                "analysis_id"
            ]
        )


        machine_audit_id = (
            analyze_result[
                "machine_audit_id"
            ]
        )


        assert document_id
        assert analysis_id
        assert machine_audit_id


        assert (
            analyze_result[
                "processing_status"
            ]
            == "PROCESSED"
        )


        assert (
            analyze_result[
                "analysis"
            ][
                "extraction"
            ][
                "document_type"
            ]
            == "guard_license"
        )


        assert (
            analyze_result[
                "analysis"
            ][
                "review_decision"
            ][
                "decision"
            ]
            == "REVIEW_REQUIRED"
        )


        assert (
            analyze_result[
                "analysis"
            ][
                "review_decision"
            ][
                "priority"
            ]
            == "MEDIUM"
        )


        print(
            "Document analysis:",
            "OK"
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
            "Machine Audit ID:",
            machine_audit_id,
        )


        # ==================================================
        # TEST 3 — RETRIEVE STORED DOCUMENT
        # ==================================================

        response = client.get(
            (
                "/api/v1/documents/"
                f"{document_id}"
            )
        )


        assert (
            response.status_code
            == 200
        )


        stored_result = (
            response.json()
        )


        assert (
            stored_result[
                "document"
            ][
                "document_id"
            ]
            == document_id
        )


        assert (
            stored_result[
                "document"
            ][
                "document_type"
            ]
            == "guard_license"
        )


        assert (
            stored_result[
                "analysis"
            ][
                "analysis_id"
            ]
            == analysis_id
        )


        assert (
            stored_result[
                "analysis"
            ][
                "extraction"
            ][
                "expiry_date"
            ][
                "value"
            ]
            == "2026-01-01"
        )


        print(
            "Stored document retrieval:",
            "OK"
        )


        # ==================================================
        # TEST 4 — SUBMIT HUMAN CORRECTION
        # ==================================================

        response = client.post(
            (
                "/api/v1/documents/"
                f"{document_id}"
                "/reviews"
            ),

            json={
                "reviewer_id":
                    "phase6c-reviewer",

                "action":
                    "CORRECT",

                "notes":
                    (
                        "Expiry date corrected "
                        "during Phase 6C "
                        "end-to-end verification."
                    ),

                "corrections": {
                    "expiry_date":
                        "2027-01-01"
                },
            },
        )


        assert (
            response.status_code
            == 200
        )


        review_result = (
            response.json()
        )


        review_id = (
            review_result[
                "review_id"
            ]
        )


        human_audit_id = (
            review_result[
                "audit_event_id"
            ]
        )


        assert review_id
        assert human_audit_id


        assert (
            review_result[
                "human_action"
            ]
            == "CORRECT"
        )


        assert (
            review_result[
                "review"
            ][
                "machine_decision"
            ]
            == "REVIEW_REQUIRED"
        )


        assert (
            review_result[
                "review"
            ][
                "machine_priority"
            ]
            == "MEDIUM"
        )


        assert (
            review_result[
                "review"
            ][
                "corrections"
            ][
                "expiry_date"
            ]
            == "2027-01-01"
        )


        print(
            "Human correction:",
            "OK"
        )

        print(
            "Review ID:",
            review_id,
        )

        print(
            "Human Audit ID:",
            human_audit_id,
        )


        # ==================================================
        # TEST 5 — AUDIT HISTORY
        # ==================================================

        response = client.get(
            (
                "/api/v1/documents/"
                f"{document_id}"
                "/history"
            )
        )


        assert (
            response.status_code
            == 200
        )


        history = (
            response.json()
        )


        assert (
            history[
                "event_count"
            ]
            == 2
        )


        events = (
            history[
                "events"
            ]
        )


        assert (
            events[
                0
            ][
                "event_type"
            ]
            == "MACHINE_REVIEW_DECISION"
        )


        assert (
            events[
                1
            ][
                "event_type"
            ]
            == "HUMAN_REVIEW"
        )


        assert (
            events[
                1
            ][
                "actor_id"
            ]
            == "phase6c-reviewer"
        )


        assert (
            events[
                1
            ][
                "details"
            ][
                "human_action"
            ]
            == "CORRECT"
        )


        assert (
            events[
                1
            ][
                "details"
            ][
                "corrections"
            ][
                "expiry_date"
            ]
            == "2027-01-01"
        )


        print(
            "Audit history:",
            "OK"
        )


        # ==================================================
        # TEST 6 — MISSING DOCUMENT
        # ==================================================

        response = client.get(
            (
                "/api/v1/documents/"
                "missing-document-id"
            )
        )


        assert (
            response.status_code
            == 404
        )


        response = client.get(
            (
                "/api/v1/documents/"
                "missing-document-id"
                "/history"
            )
        )


        assert (
            response.status_code
            == 404
        )


        print(
            "Missing document handling:",
            "OK"
        )


    # ======================================================
    # TEST 7 — DIRECT POSTGRESQL VERIFICATION
    # ======================================================

    print()
    print(
        "Verifying PostgreSQL "
        "directly..."
    )


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


        analysis = (
            session.scalar(
                select(
                    DocumentAnalysisModel
                )
                .where(
                    DocumentAnalysisModel
                    .document_id
                    == document_id
                )
            )
        )


        human_review = (
            session.scalar(
                select(
                    HumanReviewModel
                )
                .where(
                    HumanReviewModel
                    .document_id
                    == document_id
                )
            )
        )


        assert document_count == 1
        assert analysis_count == 1
        assert review_count == 1
        assert audit_count == 2


        # ==================================================
        # ORIGINAL MACHINE EXTRACTION MUST REMAIN UNCHANGED
        # ==================================================

        assert (
            analysis
            .extraction[
                "expiry_date"
            ][
                "value"
            ]
            == "2026-01-01"
        )


        # ==================================================
        # HUMAN CORRECTION STORED SEPARATELY
        # ==================================================

        assert (
            human_review
            .corrections[
                "expiry_date"
            ]
            == "2027-01-01"
        )


    print(
        "Document rows:",
        document_count,
    )

    print(
        "Analysis rows:",
        analysis_count,
    )

    print(
        "Review rows:",
        review_count,
    )

    print(
        "Audit rows:",
        audit_count,
    )

    print(
        "Original machine result preserved:",
        "OK"
    )

    print(
        "Human correction provenance:",
        "OK"
    )


    # ======================================================
    # SUCCESS
    # ======================================================

    print()
    print("=" * 70)
    print(
        "[PASS] Phase 6C full "
        "end-to-end integration passed."
    )
    print("=" * 70)


finally:

    # ======================================================
    # TEST DATA CLEANUP
    # ======================================================

    if document_id:

        with SessionLocal.begin() as session:

            document = session.get(
                DocumentModel,
                document_id,
            )


            if document is not None:

                session.delete(
                    document
                )


        # ==================================================
        # VERIFY CASCADE CLEANUP
        # ==================================================

        with SessionLocal() as session:

            remaining_documents = (
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


            remaining_analyses = (
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


            remaining_reviews = (
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


            remaining_audits = (
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


        assert remaining_documents == 0
        assert remaining_analyses == 0
        assert remaining_reviews == 0
        assert remaining_audits == 0


        print()
        print(
            "End-to-end test cleanup:",
            "OK"
        )