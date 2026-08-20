from sqlalchemy import (
    select,
)

from fastapi.testclient import (
    TestClient,
)

from backend.app.main import (
    app,
)

from database.database import (
    SessionLocal,
)

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
# ASSERT HELPERS
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


def assert_true(
    condition: bool,
    message: str,
):

    if not condition:

        raise AssertionError(
            message
        )


# ==========================================================
# TEST PIPELINE RESULT
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
            "Document is expired.",
    }


    return {
        "extraction": {
            "document_type":
                "guard_license",

            "full_name": {
                "value":
                    "IDENTITY TEST USER",

                "source_line_ids": [
                    "L0"
                ],
            },

            "licence_number": {
                "value":
                    "AUTH12345",

                "source_line_ids": [
                    "L1"
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
                    "L2"
                ],
            },

            "date_of_birth": {
                "value":
                    None,

                "source_line_ids":
                    [],
            },

            "issue_date": {
                "value":
                    None,

                "source_line_ids":
                    [],
            },

            "issuer": {
                "value":
                    "TEST AUTHORITY",

                "source_line_ids": [
                    "L3"
                ],
            },
        },

        "ocr_lines": [
            {
                "line_id":
                    "L0",

                "text":
                    "IDENTITY TEST USER",

                "confidence":
                    0.99,

                "bbox":
                    [],
            },

            {
                "line_id":
                    "L1",

                "text":
                    "AUTH12345",

                "confidence":
                    0.99,

                "bbox":
                    [],
            },

            {
                "line_id":
                    "L2",

                "text":
                    "01/01/2026",

                "confidence":
                    0.99,

                "bbox":
                    [],
            },

            {
                "line_id":
                    "L3",

                "text":
                    "TEST AUTHORITY",

                "confidence":
                    0.99,

                "bbox":
                    [],
            },
        ],

        "evidence_flags":
            [],

        "field_confidence":
            {},

        "date_validation":
            {},

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
# MAIN
# ==========================================================

def main():

    print()
    print("=" * 76)
    print(
        "PHASE 7C.5b — REVIEWER "
        "IDENTITY API TRUST BOUNDARY TEST"
    )
    print("=" * 76)


    document_id = None
    client = None


    persistence_service = (
        PersistenceService()
    )


    try:

        # ==================================================
        # APPLICATION STATE
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

        app.state.reviewer_identity = (
            ReviewerIdentityService(
                mode=(
                    "trusted_headers"
                )
            )
        )


        client = TestClient(
            app
        )


        print(
            "[OK] Trusted-header API test "
            "services initialized"
        )


        # ==================================================
        # CREATE REVIEW-REQUIRED DOCUMENT
        # ==================================================

        stored = (
            persistence_service
            .save_processed_document(
                original_filename=(
                    "phase7c_identity_api.jpg"
                ),

                content_type=(
                    "image/jpeg"
                ),

                pipeline_result=(
                    build_pipeline_result()
                ),
            )
        )


        document_id = (
            stored[
                "document_id"
            ]
        )


        # ==================================================
        # TEST 1 — MISSING IDENTITY → 401
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 1 — MISSING IDENTITY"
        )
        print("-" * 76)


        response = client.post(
            (
                "/api/v1/documents/"
                f"{document_id}"
                "/reviews"
            ),

            json={
                "reviewer_id":
                    "spoofed-client-user",

                "action":
                    "APPROVE",
            },
        )


        assert_equal(
            response.status_code,
            401,
            (
                "Missing trusted identity "
                "should return HTTP 401."
            ),
        )


        print(
            "[PASS] Missing authenticated "
            "identity rejected with HTTP 401"
        )


        # ==================================================
        # TEST 2 — VIEWER → 403
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 2 — VIEWER AUTHORIZATION"
        )
        print("-" * 76)


        response = client.post(
            (
                "/api/v1/documents/"
                f"{document_id}"
                "/reviews"
            ),

            headers={
                "X-VIGILOX-REVIEWER-ID":
                    "trusted-viewer",

                "X-VIGILOX-REVIEWER-ROLE":
                    "VIEWER",
            },

            json={
                "reviewer_id":
                    "spoofed-admin",

                "action":
                    "APPROVE",
            },
        )


        assert_equal(
            response.status_code,
            403,
            (
                "VIEWER should receive "
                "HTTP 403."
            ),
        )


        print(
            "[PASS] VIEWER blocked from "
            "review write access"
        )


        # ==================================================
        # TEST 3 — /reviewer/me
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 3 — CURRENT REVIEWER IDENTITY"
        )
        print("-" * 76)


        trusted_headers = {
            "X-VIGILOX-REVIEWER-ID":
                "trusted-reviewer-001",

            "X-VIGILOX-REVIEWER-ROLE":
                "REVIEWER",
        }


        response = client.get(
            "/api/v1/reviewer/me",
            headers=(
                trusted_headers
            ),
        )


        assert_equal(
            response.status_code,
            200,
            (
                "Authenticated reviewer "
                "identity endpoint failed."
            ),
        )


        reviewer = (
            response.json()[
                "reviewer"
            ]
        )


        assert_equal(
            reviewer[
                "reviewer_id"
            ],
            "trusted-reviewer-001",
            (
                "Identity endpoint returned "
                "wrong reviewer ID."
            ),
        )


        assert_equal(
            reviewer[
                "role"
            ],
            "REVIEWER",
            (
                "Identity endpoint returned "
                "wrong reviewer role."
            ),
        )


        assert_equal(
            reviewer[
                "can_review"
            ],
            True,
            (
                "REVIEWER should have "
                "review permission."
            ),
        )


        print(
            "[PASS] Current reviewer identity "
            "resolved server-side"
        )


        # ==================================================
        # TEST 4 — CLIENT SPOOF ATTEMPT
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 4 — CLIENT REVIEWER-ID SPOOF ATTEMPT"
        )
        print("-" * 76)


        response = client.post(
            (
                "/api/v1/documents/"
                f"{document_id}"
                "/reviews"
            ),

            headers=(
                trusted_headers
            ),

            json={
                # ==========================================
                # Deliberately different from trusted header.
                # Backend MUST ignore this identity.
                # ==========================================

                "reviewer_id":
                    "fake-client-admin",

                "action":
                    "CORRECT",

                "notes":
                    (
                        "Reviewer identity trust "
                        "boundary verification."
                    ),

                "corrections": {
                    "issuer":
                        "CORRECTED AUTHORITY",
                },
            },
        )


        assert_equal(
            response.status_code,
            200,
            (
                "Trusted REVIEWER should "
                "successfully submit review."
            ),
        )


        body = (
            response.json()
        )


        assert_equal(
            body[
                "authenticated_reviewer"
            ][
                "reviewer_id"
            ],
            "trusted-reviewer-001",
            (
                "API should report trusted "
                "reviewer identity."
            ),
        )


        assert_equal(
            body[
                "review"
            ][
                "reviewer_id"
            ],
            "trusted-reviewer-001",
            (
                "Review result should use "
                "trusted reviewer identity."
            ),
        )


        print(
            "[PASS] Client-supplied reviewer_id "
            "is not authoritative"
        )


        # ==================================================
        # TEST 5 — DATABASE TRUSTED IDENTITY
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 5 — DATABASE IDENTITY"
        )
        print("-" * 76)


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


            review = (
                session
                .scalars(
                    statement
                )
                .one()
            )


            assert_equal(
                review.reviewer_id,
                "trusted-reviewer-001",
                (
                    "PostgreSQL persisted "
                    "client-spoofed identity."
                ),
            )


            human_audit_statement = (
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
                    human_audit_statement
                )
                .one()
            )


            assert_equal(
                audit.actor_id,
                "trusted-reviewer-001",
                (
                    "Human audit actor must "
                    "use trusted identity."
                ),
            )


        print(
            "[PASS] PostgreSQL reviewer_id "
            "uses trusted identity"
        )

        print(
            "[PASS] Audit actor_id uses "
            "trusted identity"
        )


        # ==================================================
        # TEST 6 — DUPLICATE STILL 409
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 6 — DUPLICATE REVIEW PROTECTION"
        )
        print("-" * 76)


        response = client.post(
            (
                "/api/v1/documents/"
                f"{document_id}"
                "/reviews"
            ),

            headers={
                "X-VIGILOX-REVIEWER-ID":
                    "trusted-admin-001",

                "X-VIGILOX-REVIEWER-ROLE":
                    "ADMIN",
            },

            json={
                "reviewer_id":
                    "another-spoof",

                "action":
                    "APPROVE",
            },
        )


        assert_equal(
            response.status_code,
            409,
            (
                "Duplicate human review "
                "must remain HTTP 409."
            ),
        )


        print(
            "[PASS] Existing duplicate-review "
            "protection remains intact"
        )


        # ==================================================
        # FINAL
        # ==================================================

        print()
        print("=" * 76)
        print(
            "[PASS] PHASE 7C.5b REVIEWER "
            "IDENTITY API TRUST BOUNDARY "
            "TEST PASSED"
        )
        print("=" * 76)


    finally:

        if client is not None:

            client.close()


        if document_id is not None:

            with SessionLocal() as session:

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
            "[CLEANUP] Phase 7C.5b temporary "
            "database records removed."
        )


if __name__ == "__main__":

    main()