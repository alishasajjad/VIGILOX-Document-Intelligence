from src.api.main import app

from fastapi.testclient import (
    TestClient,
)

from src.db.database import (
    SessionLocal,
)

from src.db.models import (
    DocumentModel,
)

from src.db.persistence_service import (
    PersistenceService,
)

from src.db.query_service import (
    DocumentQueryService,
)

from src.human_review_service import (
    HumanReviewService,
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

            "fields": {
                "full_name": {
                    "value":
                        "PHASE7A TEST USER",

                    "source_line_ids":
                        [],
                },

                "licence_number": {
                    "value":
                        "P7A123456",

                    "source_line_ids":
                        [],
                },

                "id_number": {
                    "value":
                        None,

                    "source_line_ids":
                        [],
                },

                "expiry_date": {
                    "value":
                        "2025-01-01",

                    "source_line_ids":
                        [],
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
                        "PHASE 7A TEST AUTHORITY",

                    "source_line_ids":
                        [],
                },
            },
        },

        "ocr_lines":
            [],

        "evidence_flags":
            [],

        "field_confidence":
            {},

        "date_validation": {
            "reference_date":
                "2026-08-19",

            "date_fields":
                {},

            "expiry": {
                "value":
                    "2025-01-01",

                "status":
                    "EXPIRED",

                "days_until_expiry":
                    -595,
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
# ASSERTION HELPER
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
# FIND DOCUMENT IN QUEUE
# ==========================================================

def find_queue_document(
    response_body: dict,
    document_id: str,
) -> dict | None:

    for item in (
        response_body[
            "documents"
        ]
    ):

        if (
            item[
                "document_id"
            ]
            == document_id
        ):

            return item


    return None


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()

    print(
        "=" * 72
    )

    print(
        "PHASE 7A — FINAL OPERATIONAL "
        "END-TO-END TEST"
    )

    print(
        "=" * 72
    )


    document_id = None

    client = None


    try:

        # ==================================================
        # 1. INITIALIZE APPLICATION SERVICES
        # ==================================================
        #
        # We intentionally initialize only the services
        # required by this review workflow.
        #
        # OCR / LLM initialization is not required because
        # Phase 7A is testing the operational review queue,
        # not document extraction.
        # ==================================================

        app.state.document_query = (
            DocumentQueryService()
        )

        app.state.persistence = (
            PersistenceService()
        )

        app.state.human_review = (
            HumanReviewService()
        )


        client = TestClient(
            app
        )


        print(
            "[OK] Review workflow services "
            "initialized"
        )


        # ==================================================
        # 2. PERSIST MACHINE-PROCESSED DOCUMENT
        # ==================================================

        pipeline_result = (
            build_pipeline_result()
        )


        persistence_service = (
            app.state.persistence
        )


        stored = (
            persistence_service
            .save_processed_document(
                original_filename=(
                    "phase7a_final_guard.jpg"
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
            stored[
                "document_id"
            ]
        )


        analysis_id = (
            stored[
                "analysis_id"
            ]
        )


        machine_audit_id = (
            stored[
                "machine_audit_id"
            ]
        )


        if not document_id:

            raise AssertionError(
                "Document ID was not created."
            )


        if not analysis_id:

            raise AssertionError(
                "Analysis ID was not created."
            )


        if not machine_audit_id:

            raise AssertionError(
                "Machine audit ID was not created."
            )


        print(
            "[PASS] Machine-processed "
            "document persisted"
        )

        print(
            "[PASS] Machine analysis "
            "persisted"
        )

        print(
            "[PASS] Machine audit event "
            "persisted"
        )


        # ==================================================
        # 3. VERIFY DOCUMENT APPEARS IN REVIEW QUEUE
        # ==================================================

        response = (
            client.get(
                "/api/v1/reviews/queue"
            )
        )


        assert_equal(
            response.status_code,
            200,
            (
                "Review queue should return "
                "HTTP 200."
            ),
        )


        queue_before = (
            response.json()
        )


        queue_item = (
            find_queue_document(
                queue_before,
                document_id,
            )
        )


        if queue_item is None:

            raise AssertionError(
                "New REVIEW_REQUIRED document "
                "did not appear in queue."
            )


        assert_equal(
            queue_item[
                "review_decision"
            ],
            "REVIEW_REQUIRED",
            (
                "Queue document has incorrect "
                "machine decision."
            ),
        )


        assert_equal(
            queue_item[
                "review_priority"
            ],
            "MEDIUM",
            (
                "Queue document has incorrect "
                "priority."
            ),
        )


        assert_equal(
            queue_item[
                "reason_codes"
            ],
            [
                "DOCUMENT_EXPIRED"
            ],
            (
                "Queue document has incorrect "
                "reason codes."
            ),
        )


        print(
            "[PASS] Pending document "
            "appears in review queue"
        )

        print(
            "[PASS] Queue exposes trusted "
            "machine decision"
        )


        # ==================================================
        # 4. SUBMIT HUMAN APPROVAL THROUGH API
        # ==================================================

        review_response = (
            client.post(
                (
                    f"/api/v1/documents/"
                    f"{document_id}/reviews"
                ),

                json={
                    "reviewer_id":
                        "phase7a-final-reviewer",

                    "action":
                        "APPROVE",

                    "notes":
                        (
                            "Phase 7A final "
                            "end-to-end approval."
                        ),

                    "corrections":
                        None,
                },
            )
        )


        assert_equal(
            review_response.status_code,
            200,
            (
                "Human review submission "
                "should return HTTP 200."
            ),
        )


        review_body = (
            review_response.json()
        )


        assert_equal(
            review_body[
                "document_id"
            ],
            document_id,
            (
                "Review response document ID "
                "does not match."
            ),
        )


        assert_equal(
            review_body[
                "human_action"
            ],
            "APPROVE",
            (
                "Human action should be "
                "APPROVE."
            ),
        )


        review_id = (
            review_body[
                "review_id"
            ]
        )


        human_audit_id = (
            review_body[
                "audit_event_id"
            ]
        )


        if not review_id:

            raise AssertionError(
                "Human review ID missing."
            )


        if not human_audit_id:

            raise AssertionError(
                "Human audit event ID missing."
            )


        print(
            "[PASS] Human APPROVE action "
            "submitted through API"
        )

        print(
            "[PASS] Human review persisted"
        )

        print(
            "[PASS] Human audit event "
            "persisted"
        )


        # ==================================================
        # 5. VERIFY DOCUMENT DISAPPEARS FROM QUEUE
        # ==================================================

        response = (
            client.get(
                "/api/v1/reviews/queue"
            )
        )


        assert_equal(
            response.status_code,
            200,
            (
                "Review queue after human "
                "review should return HTTP 200."
            ),
        )


        queue_after = (
            response.json()
        )


        queue_item_after = (
            find_queue_document(
                queue_after,
                document_id,
            )
        )


        assert_equal(
            queue_item_after,
            None,
            (
                "Human-reviewed document "
                "should disappear from "
                "pending queue."
            ),
        )


        print(
            "[PASS] Human-reviewed document "
            "removed from pending queue"
        )


        # ==================================================
        # 6. VERIFY STORED DOCUMENT STILL EXISTS
        # ==================================================

        response = (
            client.get(
                (
                    f"/api/v1/documents/"
                    f"{document_id}"
                )
            )
        )


        assert_equal(
            response.status_code,
            200,
            (
                "Stored document should still "
                "exist after human review."
            ),
        )


        stored_document = (
            response.json()
        )


        assert_equal(
            stored_document[
                "analysis"
            ][
                "review_decision"
            ][
                "decision"
            ],
            "REVIEW_REQUIRED",
            (
                "Original machine decision "
                "must remain unchanged."
            ),
        )


        print(
            "[PASS] Stored document remains "
            "available"
        )

        print(
            "[PASS] Original machine "
            "decision preserved"
        )


        # ==================================================
        # 7. VERIFY AUDIT HISTORY
        # ==================================================

        response = (
            client.get(
                (
                    f"/api/v1/documents/"
                    f"{document_id}/history"
                )
            )
        )


        assert_equal(
            response.status_code,
            200,
            (
                "Audit-history endpoint "
                "should return HTTP 200."
            ),
        )


        history = (
            response.json()
        )


        events = (
            history[
                "events"
            ]
        )


        event_types = [
            event[
                "event_type"
            ]
            for event
            in events
        ]


        if (
            "MACHINE_REVIEW_DECISION"
            not in event_types
        ):

            raise AssertionError(
                "Machine review audit event "
                "missing from history."
            )


        if (
            "HUMAN_REVIEW"
            not in event_types
        ):

            raise AssertionError(
                "Human review audit event "
                "missing from history."
            )


        print(
            "[PASS] Machine audit present "
            "in history"
        )

        print(
            "[PASS] Human review audit "
            "present in history"
        )


        # ==================================================
        # 8. DIRECT POSTGRESQL VERIFICATION
        # ==================================================

        with SessionLocal() as session:

            document = (
                session.get(
                    DocumentModel,
                    document_id,
                )
            )


            if document is None:

                raise AssertionError(
                    "Document missing from "
                    "PostgreSQL."
                )


        print(
            "[PASS] PostgreSQL document "
            "record verified"
        )


        # ==================================================
        # FINAL SUCCESS
        # ==================================================

        print()

        print(
            "=" * 72
        )

        print(
            "[PASS] PHASE 7A FINAL "
            "END-TO-END TEST PASSED"
        )

        print(
            "=" * 72
        )


    finally:

        # ==================================================
        # CLOSE CLIENT
        # ==================================================

        if client is not None:

            client.close()


        # ==================================================
        # CLEANUP TEST DOCUMENT
        # ==================================================

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


            print()

            print(
                "[CLEANUP] Phase 7A final "
                "test document removed."
            )


        # ==================================================
        # CLEAN APPLICATION STATE
        # ==================================================

        for state_name in (
            "document_query",
            "persistence",
            "human_review",
        ):

            if hasattr(
                app.state,
                state_name,
            ):

                delattr(
                    app.state,
                    state_name,
                )


if __name__ == "__main__":

    main()