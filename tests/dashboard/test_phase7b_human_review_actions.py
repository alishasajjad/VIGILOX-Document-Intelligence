from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.main import app

from database.database import SessionLocal

from database.models import (
    AuditEventModel,
    DocumentModel,
    HumanReviewModel,
)

from backend.app.services.persistence_service import (
    PersistenceService,
)

from backend.app.services.query_service import (
    DocumentQueryService,
)

from backend.app.services.human_review_service import (
    HumanReviewService,
)

from backend.app.services.reviewer_identity_service import (
    ReviewerIdentityService,
)


# ==========================================================
# PIPELINE RESULT
# ==========================================================

def build_pipeline_result() -> dict:

    issue = {
        "code":
            "DOCUMENT_EXPIRED",

        "severity":
            "WARNING",

        "field":
            "expiry_date",

        "message":
            "The document has passed "
            "its validated expiry date.",
    }


    return {
        "extraction": {
            "document_type":
                "guard_license",

            "full_name": {
                "value":
                    "PHASE 7B TEST USER",

                "source_line_ids": [
                    "L1"
                ],
            },

            "licence_number": {
                "value":
                    "P7B123456",

                "source_line_ids": [
                    "L2"
                ],
            },

            "id_number": {
                "value":
                    None,

                "source_line_ids":
                    [],
            },

            "expiry_date": {
                "value":
                    "2026-01-01",

                "source_line_ids": [
                    "L3"
                ],
            },

            "date_of_birth": {
                "value":
                    "1990-01-01",

                "source_line_ids": [
                    "L4"
                ],
            },

            "issue_date": {
                "value":
                    "2025-01-01",

                "source_line_ids": [
                    "L5"
                ],
            },

            "issuer": {
                "value":
                    "TX DPS",

                "source_line_ids": [
                    "L6"
                ],
            },
        },

        "ocr_lines": [
            {
                "text":
                    "PHASE 7B TEST USER",

                "confidence":
                    0.99,

                "bbox":
                    [0, 0, 10, 10],
            },

            {
                "text":
                    "P7B123456",

                "confidence":
                    0.99,

                "bbox":
                    [0, 0, 10, 10],
            },

            {
                "text":
                    "01/01/2026",

                "confidence":
                    0.99,

                "bbox":
                    [0, 0, 10, 10],
            },

            {
                "text":
                    "01/01/1990",

                "confidence":
                    0.99,

                "bbox":
                    [0, 0, 10, 10],
            },

            {
                "text":
                    "01/01/2025",

                "confidence":
                    0.99,

                "bbox":
                    [0, 0, 10, 10],
            },

            {
                "text":
                    "ISSUED BY TX DPS",

                "confidence":
                    0.99,

                "bbox":
                    [0, 0, 10, 10],
            },
        ],

        "evidence_flags":
            [],

        "field_confidence": {
            "full_name":
                0.99,

            "licence_number":
                0.99,

            "id_number":
                None,

            "expiry_date":
                0.99,

            "date_of_birth":
                0.99,

            "issue_date":
                0.99,

            "issuer":
                0.99,
        },

        "date_validation": {
            "reference_date":
                "2026-08-19",

            "date_fields":
                {},

            "expiry": {
                "value":
                    "2026-01-01",

                "status":
                    "EXPIRED",

                "days_until_expiry":
                    -230,
            },

            "logical_issues":
                [],

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
                issue
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
                issue
            ],
        },
    }


# ==========================================================
# ASSERT HELPER
# ==========================================================

def assert_equal(
    actual,
    expected,
    message: str,
):

    if actual != expected:

        raise AssertionError(
            f"{message}\n"
            f"Expected: {expected}\n"
            f"Actual:   {actual}"
        )


# ==========================================================
# REVIEWER AUTH HEADERS
# PHASE 7C.5
# ==========================================================

def reviewer_headers(
    reviewer_id: str,
    role: str = "REVIEWER",
) -> dict[str, str]:

    return {
        "X-VIGILOX-REVIEWER-ID":
            reviewer_id,

        "X-VIGILOX-REVIEWER-ROLE":
            role,
    }


# ==========================================================
# CREATE TEMP REVIEW DOCUMENT
# ==========================================================

def create_test_document(
    persistence_service: PersistenceService,
    suffix: str,
) -> str:

    filename = (
        f"phase7b8_{suffix}_"
        f"{uuid4()}.jpg"
    )


    stored = (
        persistence_service
        .save_processed_document(
            original_filename=(
                filename
            ),

            content_type=(
                "image/jpeg"
            ),

            pipeline_result=(
                build_pipeline_result()
            ),
        )
    )


    return stored[
        "document_id"
    ]


# ==========================================================
# VERIFY DOCUMENT IN QUEUE
# ==========================================================

def assert_in_queue(
    client: TestClient,
    document_id: str,
):

    response = client.get(
        "/api/v1/reviews/queue"
    )


    assert_equal(
        response.status_code,
        200,
        "Queue request failed.",
    )


    document_ids = {
        item["document_id"]
        for item
        in response.json()["documents"]
    }


    if document_id not in document_ids:

        raise AssertionError(
            "Expected temporary document "
            "to appear in review queue."
        )


# ==========================================================
# VERIFY DOCUMENT REMOVED FROM QUEUE
# ==========================================================

def assert_not_in_queue(
    client: TestClient,
    document_id: str,
):

    response = client.get(
        "/api/v1/reviews/queue"
    )


    assert_equal(
        response.status_code,
        200,
        "Queue request failed.",
    )


    document_ids = {
        item["document_id"]
        for item
        in response.json()["documents"]
    }


    if document_id in document_ids:

        raise AssertionError(
            "Reviewed document should not "
            "remain in pending queue."
        )


# ==========================================================
# VERIFY DB REVIEW
# ==========================================================

def get_human_review(
    document_id: str,
):

    with SessionLocal() as session:

        statement = (
            select(
                HumanReviewModel
            )
            .where(
                HumanReviewModel.document_id
                == document_id
            )
        )


        return (
            session
            .scalars(
                statement
            )
            .one()
        )


# ==========================================================
# VERIFY HUMAN AUDIT
# ==========================================================

def assert_human_audit_exists(
    document_id: str,
):

    with SessionLocal() as session:

        statement = (
            select(
                AuditEventModel
            )
            .where(
                AuditEventModel.document_id
                == document_id
            )
            .where(
                AuditEventModel.event_type
                == "HUMAN_REVIEW"
            )
        )


        audit = (
            session
            .scalars(
                statement
            )
            .one_or_none()
        )


        if audit is None:

            raise AssertionError(
                "HUMAN_REVIEW audit event "
                "was not persisted."
            )


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("=" * 72)
    print(
        "PHASE 7B.8 — HUMAN REVIEW "
        "ACTIONS OPERATIONAL TEST"
    )
    print("=" * 72)


    created_document_ids: list[str] = []

    client = None


    persistence_service = (
        PersistenceService()
    )


    try:

        # ==================================================
        # INITIALIZE TEST SERVICES
        # ==================================================

        app.state.persistence = (
            persistence_service
        )


        app.state.document_query = (
            DocumentQueryService()
        )


        app.state.human_review = (
            HumanReviewService()
        )


        # ==================================================
        # PHASE 7C.5
        # TRUSTED REVIEWER IDENTITY
        # ==================================================

        app.state.reviewer_identity = (
            ReviewerIdentityService(
                mode="trusted_headers",
                trusted_proxies=(
                    # PHASE 11.5. TestClient reports its
                    # peer as the literal "testclient".
                    # Naming it here is this test saying
                    # it stands in for the reverse proxy;
                    # the network boundary itself is
                    # tested in
                    # tests/deployment/test_phase11_security_boundary.py.
                    "testclient",
                ),
            )
        )


        client = TestClient(
            app
        )


        print(
            "[OK] Human review services initialized"
        )


        # ==================================================
        # TEST 1 — APPROVE
        # ==================================================

        approve_document_id = (
            create_test_document(
                persistence_service,
                "approve",
            )
        )


        created_document_ids.append(
            approve_document_id
        )


        assert_in_queue(
            client,
            approve_document_id,
        )


        print(
            "[PASS] APPROVE test document "
            "appears in review queue"
        )


        response = client.post(
            (
                "/api/v1/documents/"
                f"{approve_document_id}"
                "/reviews"
            ),

            headers=reviewer_headers(
                "phase7b-reviewer"
            ),

            json={
                "action":
                    "APPROVE",

                "notes":
                    "Phase 7B approve test.",
            },
        )


        assert_equal(
            response.status_code,
            200,
            "APPROVE should return HTTP 200.",
        )


        assert_equal(
            response.json()[
                "human_action"
            ],
            "APPROVE",
            "Unexpected APPROVE action.",
        )


        review = (
            get_human_review(
                approve_document_id
            )
        )


        assert_equal(
            review.reviewer_id,
            "phase7b-reviewer",
            (
                "Authenticated reviewer "
                "was not persisted."
            ),
        )


        assert_equal(
            review.human_action,
            "APPROVE",
            "APPROVE was not persisted.",
        )


        assert_equal(
            review.corrections,
            {},
            (
                "APPROVE should not "
                "persist corrections."
            ),
        )


        assert_human_audit_exists(
            approve_document_id
        )


        assert_not_in_queue(
            client,
            approve_document_id,
        )


        print(
            "[PASS] APPROVE persisted"
        )

        print(
            "[PASS] APPROVE human audit persisted"
        )

        print(
            "[PASS] APPROVE document removed "
            "from pending queue"
        )


        # ==================================================
        # TEST 2 — REJECT
        # ==================================================

        reject_document_id = (
            create_test_document(
                persistence_service,
                "reject",
            )
        )


        created_document_ids.append(
            reject_document_id
        )


        assert_in_queue(
            client,
            reject_document_id,
        )


        response = client.post(
            (
                "/api/v1/documents/"
                f"{reject_document_id}"
                "/reviews"
            ),

            headers=reviewer_headers(
                "phase7b-reviewer"
            ),

            json={
                "action":
                    "REJECT",

                "notes":
                    (
                        "Document rejected during "
                        "Phase 7B test."
                    ),
            },
        )


        assert_equal(
            response.status_code,
            200,
            "REJECT should return HTTP 200.",
        )


        assert_equal(
            response.json()[
                "human_action"
            ],
            "REJECT",
            "Unexpected REJECT action.",
        )


        review = (
            get_human_review(
                reject_document_id
            )
        )


        assert_equal(
            review.reviewer_id,
            "phase7b-reviewer",
            (
                "Authenticated reviewer "
                "was not persisted."
            ),
        )


        assert_equal(
            review.human_action,
            "REJECT",
            "REJECT was not persisted.",
        )


        assert_equal(
            review.corrections,
            {},
            (
                "REJECT should not "
                "persist corrections."
            ),
        )


        assert_human_audit_exists(
            reject_document_id
        )


        assert_not_in_queue(
            client,
            reject_document_id,
        )


        print(
            "[PASS] REJECT persisted"
        )

        print(
            "[PASS] REJECT human audit persisted"
        )

        print(
            "[PASS] REJECT document removed "
            "from pending queue"
        )


        # ==================================================
        # TEST 3 — CORRECT
        # ==================================================

        correct_document_id = (
            create_test_document(
                persistence_service,
                "correct",
            )
        )


        created_document_ids.append(
            correct_document_id
        )


        assert_in_queue(
            client,
            correct_document_id,
        )


        corrections = {
            "expiry_date":
                "2027-01-01",

            "issuer":
                "TX DPS SECURITY",
        }


        response = client.post(
            (
                "/api/v1/documents/"
                f"{correct_document_id}"
                "/reviews"
            ),

            headers=reviewer_headers(
                "phase7b-reviewer"
            ),

            json={
                "action":
                    "CORRECT",

                "notes":
                    (
                        "Corrected expiry date "
                        "and issuer."
                    ),

                "corrections":
                    corrections,
            },
        )


        assert_equal(
            response.status_code,
            200,
            "CORRECT should return HTTP 200.",
        )


        assert_equal(
            response.json()[
                "human_action"
            ],
            "CORRECT",
            "Unexpected CORRECT action.",
        )


        review = (
            get_human_review(
                correct_document_id
            )
        )


        assert_equal(
            review.reviewer_id,
            "phase7b-reviewer",
            (
                "Authenticated reviewer "
                "was not persisted."
            ),
        )


        assert_equal(
            review.human_action,
            "CORRECT",
            "CORRECT was not persisted.",
        )


        assert_equal(
            review.corrections,
            corrections,
            (
                "Correction values were "
                "not persisted correctly."
            ),
        )


        assert_human_audit_exists(
            correct_document_id
        )


        assert_not_in_queue(
            client,
            correct_document_id,
        )


        print(
            "[PASS] CORRECT persisted"
        )

        print(
            "[PASS] Correction values persisted"
        )

        print(
            "[PASS] CORRECT human audit persisted"
        )

        print(
            "[PASS] CORRECT document removed "
            "from pending queue"
        )


        # ==================================================
        # VERIFY MACHINE EXTRACTION NOT OVERWRITTEN
        # ==================================================

        response = client.get(
            (
                "/api/v1/documents/"
                f"{correct_document_id}"
            )
        )


        assert_equal(
            response.status_code,
            200,
            (
                "Corrected document should "
                "remain retrievable."
            ),
        )


        stored_analysis = (
            response.json()[
                "analysis"
            ]
        )


        assert_equal(
            stored_analysis[
                "extraction"
            ][
                "expiry_date"
            ][
                "value"
            ],
            "2026-01-01",
            (
                "Original machine expiry "
                "must never be overwritten."
            ),
        )


        assert_equal(
            stored_analysis[
                "extraction"
            ][
                "issuer"
            ][
                "value"
            ],
            "TX DPS",
            (
                "Original machine issuer "
                "must never be overwritten."
            ),
        )


        print(
            "[PASS] Original machine extraction "
            "preserved after CORRECT"
        )


        # ==================================================
        # INVALID CORRECT WITHOUT CORRECTIONS
        # ==================================================

        invalid_document_id = (
            create_test_document(
                persistence_service,
                "invalid_correct",
            )
        )


        created_document_ids.append(
            invalid_document_id
        )


        response = client.post(
            (
                "/api/v1/documents/"
                f"{invalid_document_id}"
                "/reviews"
            ),

            headers=reviewer_headers(
                "phase7b-reviewer"
            ),

            json={
                "action":
                    "CORRECT",

                "notes":
                    "No corrections provided.",
            },
        )


        assert_equal(
            response.status_code,
            400,
            (
                "CORRECT without corrections "
                "should return HTTP 400."
            ),
        )


        assert_in_queue(
            client,
            invalid_document_id,
        )


        print(
            "[PASS] CORRECT without corrections "
            "rejected with HTTP 400"
        )

        print(
            "[PASS] Failed review remains "
            "in pending queue"
        )


        # ==================================================
        # FINAL
        # ==================================================

        print()
        print("=" * 72)
        print(
            "[PASS] PHASE 7B.8 HUMAN REVIEW "
            "ACTIONS TEST PASSED"
        )
        print("=" * 72)


    finally:

        # ==================================================
        # CLIENT
        # ==================================================

        if client is not None:

            client.close()


        # ==================================================
        # DATABASE CLEANUP
        # ==================================================

        if created_document_ids:

            with SessionLocal() as session:

                for document_id in (
                    created_document_ids
                ):

                    document = (
                        session.get(
                            DocumentModel,
                            document_id,
                        )
                    )


                    if document is not None:

                        session.delete(
                            document
                        )


                session.commit()


        # ==================================================
        # STORAGE CLEANUP
        # ==================================================

        for document_id in (
            created_document_ids
        ):

            (
                persistence_service
                .storage_service
                .delete_document(
                    document_id
                )
            )


        # ==================================================
        # APP STATE CLEANUP
        # ==================================================

        for state_name in (
            "persistence",
            "document_query",
            "human_review",
            "reviewer_identity",
        ):

            if hasattr(
                app.state,
                state_name,
            ):

                delattr(
                    app.state,
                    state_name,
                )


        print()
        print(
            "[CLEANUP] Phase 7B.8 temporary "
            "documents and review records removed."
        )


if __name__ == "__main__":

    main()