import tempfile

from pathlib import Path

from fastapi.testclient import (
    TestClient,
)

from sqlalchemy import (
    select,
)

from src.api.main import (
    app,
)

from src.db.database import (
    SessionLocal,
)

from src.db.models import (
    AuditEventModel,
    DocumentModel,
    HumanReviewModel,
)

from src.db.persistence_service import (
    PersistenceService,
)

from src.db.query_service import (
    DocumentQueryService,
)

from src.document_storage_service import (
    DocumentStorageService,
)

from src.human_review_service import (
    HumanReviewService,
)

from src.reviewer_identity_service import (
    ReviewerIdentityService,
)


# ==========================================================
# TEST CONSTANTS
# ==========================================================

ORIGINAL_FILENAME = (
    "phase7b_final_guard.jpg"
)


ORIGINAL_BYTES = (
    b"VIGILOX-PHASE-7B-FINAL-"
    b"ORIGINAL-DOCUMENT"
)


REVIEWER_ID = (
    "phase7b-final-reviewer"
)


REVIEWER_ROLE = (
    "REVIEWER"
)


# ==========================================================
# FAKE MACHINE PIPELINE
# ==========================================================

class FakePipeline:

    def process(
        self,
        image_path: str,
    ) -> dict:

        path = Path(
            image_path
        )


        if not path.exists():

            raise AssertionError(
                "Temporary uploaded image "
                "does not exist."
            )


        if (
            path.read_bytes()
            != ORIGINAL_BYTES
        ):

            raise AssertionError(
                "Temporary uploaded bytes "
                "do not match source."
            )


        issue = {
            "code":
                "DOCUMENT_EXPIRED",

            "severity":
                "WARNING",

            "field":
                "expiry_date",

            "message":
                (
                    "The document has passed "
                    "its validated expiry date."
                ),
        }


        return {

            # ==============================================
            # MACHINE EXTRACTION
            # ==============================================

            "extraction": {

                "document_type":
                    "guard_license",

                "full_name": {
                    "value":
                        "PHASE 7B FINAL USER",

                    "source_line_ids": [
                        "L0"
                    ],
                },

                "licence_number": {
                    "value":
                        "P7B999999",

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
                        "L4",
                        "L5",
                    ],
                },

                "date_of_birth": {
                    "value":
                        "1990-01-01",

                    "source_line_ids": [
                        "L6",
                        "L7",
                    ],
                },

                "issue_date": {
                    "value":
                        "2025-01-01",

                    "source_line_ids": [
                        "L3"
                    ],
                },

                "issuer": {
                    "value":
                        "TX DPS",

                    "source_line_ids": [
                        "L8"
                    ],
                },
            },


            # ==============================================
            # OCR LINES
            # ==============================================

            "ocr_lines": [

                {
                    "text":
                        "PHASE 7B FINAL USER",

                    "confidence":
                        0.998,

                    "bbox":
                        [10, 10, 200, 35],
                },

                {
                    "text":
                        "LICENSE",

                    "confidence":
                        0.999,

                    "bbox":
                        [10, 40, 100, 60],
                },

                {
                    "text":
                        "P7B999999",

                    "confidence":
                        0.999,

                    "bbox":
                        [110, 40, 220, 60],
                },

                {
                    "text":
                        "PRINTDATE 01/01/2025",

                    "confidence":
                        0.997,

                    "bbox":
                        [10, 70, 240, 90],
                },

                {
                    "text":
                        "EXPIRES",

                    "confidence":
                        0.999,

                    "bbox":
                        [10, 100, 100, 120],
                },

                {
                    "text":
                        "01/01/2026",

                    "confidence":
                        0.999,

                    "bbox":
                        [110, 100, 220, 120],
                },

                {
                    "text":
                        "DOB",

                    "confidence":
                        0.999,

                    "bbox":
                        [10, 130, 60, 150],
                },

                {
                    "text":
                        "01/01/1990",

                    "confidence":
                        0.999,

                    "bbox":
                        [70, 130, 180, 150],
                },

                {
                    "text":
                        "ISSUED BY TX DPS",

                    "confidence":
                        0.988,

                    "bbox":
                        [10, 160, 220, 180],
                },
            ],


            # ==============================================
            # EVIDENCE FLAGS
            # ==============================================

            "evidence_flags":
                [],


            # ==============================================
            # FIELD CONFIDENCE
            # ==============================================

            "field_confidence": {

                "full_name":
                    0.998,

                "licence_number":
                    0.999,

                "id_number":
                    None,

                "expiry_date":
                    0.999,

                "date_of_birth":
                    0.999,

                "issue_date":
                    0.997,

                "issuer":
                    0.988,
            },


            # ==============================================
            # DATE VALIDATION
            # ==============================================

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


            # ==============================================
            # ANOMALY VALIDATION
            # ==============================================

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


            # ==============================================
            # MACHINE REVIEW DECISION
            # ==============================================

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
# MAIN
# ==========================================================

def main():

    print()
    print("=" * 76)
    print(
        "PHASE 7B.9 — FINAL REVIEW DASHBOARD "
        "END-TO-END TEST"
    )
    print("=" * 76)


    document_id = None

    client = None


    with tempfile.TemporaryDirectory() as temp_dir:

        temp_root = Path(
            temp_dir
        )


        storage_service = (
            DocumentStorageService(
                storage_root=(
                    temp_root
                    / "documents"
                )
            )
        )


        persistence_service = (
            PersistenceService(
                storage_service=(
                    storage_service
                )
            )
        )


        try:

            # ==================================================
            # 1. INITIALIZE APPLICATION SERVICES
            # ==================================================

            app.state.pipeline = (
                FakePipeline()
            )


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
                    mode="trusted_headers"
                )
            )


            client = TestClient(
                app
            )


            print(
                "[OK] Final dashboard test "
                "services initialized"
            )


            # ==================================================
            # 2. DASHBOARD ROUTE
            # ==================================================

            response = client.get(
                "/review"
            )


            assert_equal(
                response.status_code,
                200,
                (
                    "Review dashboard should "
                    "return HTTP 200."
                ),
            )


            dashboard_html = (
                response.text
            )


            if (
                "Review Queue"
                not in dashboard_html
            ):

                raise AssertionError(
                    "Review dashboard HTML "
                    "was not returned."
                )


            if (
                "/review/static/dashboard.js"
                not in dashboard_html
            ):

                raise AssertionError(
                    "Dashboard JavaScript "
                    "reference is missing."
                )


            print(
                "[PASS] Review dashboard "
                "HTML route"
            )


            # ==================================================
            # 3. UPLOAD + MACHINE ANALYSIS + STORAGE
            # ==================================================

            response = client.post(
                "/api/v1/documents/analyze",

                files={
                    "file": (
                        ORIGINAL_FILENAME,
                        ORIGINAL_BYTES,
                        "image/jpeg",
                    )
                },
            )


            assert_equal(
                response.status_code,
                200,
                (
                    "Analyze upload should "
                    "return HTTP 200."
                ),
            )


            body = (
                response.json()
            )


            document_id = (
                body[
                    "document_id"
                ]
            )


            if not document_id:

                raise AssertionError(
                    "Analyze response missing "
                    "document_id."
                )


            assert_equal(
                body[
                    "original_document_stored"
                ],
                True,
                (
                    "Original image should "
                    "be permanently stored."
                ),
            )


            print(
                "[PASS] Document uploaded "
                "through analyze API"
            )

            print(
                "[PASS] Machine analysis "
                "persisted"
            )

            print(
                "[PASS] Original document "
                "permanently stored"
            )


            # ==================================================
            # 4. VERIFY POSTGRESQL DOCUMENT
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
                        "Uploaded document "
                        "missing from PostgreSQL."
                    )


                assert_equal(
                    document.original_filename,
                    ORIGINAL_FILENAME,
                    (
                        "Original filename "
                        "was not persisted."
                    ),
                )


                assert_equal(
                    document.document_type,
                    "guard_license",
                    (
                        "Unexpected persisted "
                        "document type."
                    ),
                )


            print(
                "[PASS] PostgreSQL document "
                "record verified"
            )


            # ==================================================
            # 5. REVIEW QUEUE
            # ==================================================

            response = client.get(
                "/api/v1/reviews/queue"
            )


            assert_equal(
                response.status_code,
                200,
                (
                    "Review queue should "
                    "return HTTP 200."
                ),
            )


            queue_documents = (
                response.json()[
                    "documents"
                ]
            )


            matching_queue_items = [
                item
                for item
                in queue_documents
                if (
                    item[
                        "document_id"
                    ]
                    == document_id
                )
            ]


            assert_equal(
                len(
                    matching_queue_items
                ),
                1,
                (
                    "Uploaded review-required "
                    "document should appear "
                    "exactly once in queue."
                ),
            )


            queue_item = (
                matching_queue_items[
                    0
                ]
            )


            assert_equal(
                queue_item[
                    "review_priority"
                ],
                "MEDIUM",
                (
                    "Unexpected queue priority."
                ),
            )


            if (
                "DOCUMENT_EXPIRED"
                not in queue_item[
                    "reason_codes"
                ]
            ):

                raise AssertionError(
                    "Expected DOCUMENT_EXPIRED "
                    "reason code in queue."
                )


            print(
                "[PASS] Document appears in "
                "pending review queue"
            )

            print(
                "[PASS] Queue exposes machine "
                "priority and reason codes"
            )


            # ==================================================
            # 6. REVIEW DETAIL HTML PAGE
            # ==================================================

            response = client.get(
                (
                    "/review/"
                    f"{document_id}"
                )
            )


            assert_equal(
                response.status_code,
                200,
                (
                    "Review detail page should "
                    "return HTTP 200."
                ),
            )


            detail_html = (
                response.text
            )


            if (
                "Human Review"
                not in detail_html
            ):

                raise AssertionError(
                    "Human Review UI is "
                    "missing from detail page."
                )


            if (
                "review_detail.js"
                not in detail_html
            ):

                raise AssertionError(
                    "Review detail JavaScript "
                    "reference is missing."
                )


            if (
                "approve-button"
                not in detail_html
                or
                "reject-button"
                not in detail_html
                or
                "correct-button"
                not in detail_html
            ):

                raise AssertionError(
                    "Reviewer action controls "
                    "are missing."
                )


            # ==================================================
            # PHASE 7C.5 UI CONTRACT
            # ==================================================

            if (
                "authenticated-reviewer-card"
                not in detail_html
            ):

                raise AssertionError(
                    "Authenticated reviewer "
                    "UI is missing."
                )


            if (
                'id="reviewer-id"'
                in detail_html
            ):

                raise AssertionError(
                    "Legacy editable reviewer "
                    "ID input still exists."
                )


            print(
                "[PASS] Document review "
                "detail page available"
            )

            print(
                "[PASS] Approve / Reject / "
                "Correct controls present"
            )

            print(
                "[PASS] Authenticated reviewer "
                "UI present"
            )

            print(
                "[PASS] Legacy editable reviewer "
                "ID removed"
            )


            # ==================================================
            # 7. CURRENT REVIEWER ENDPOINT
            # PHASE 7C.5
            # ==================================================

            response = client.get(
                "/api/v1/reviewer/me",

                headers=reviewer_headers(
                    REVIEWER_ID
                ),
            )


            assert_equal(
                response.status_code,
                200,
                (
                    "Authenticated reviewer "
                    "endpoint should return "
                    "HTTP 200."
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
                REVIEWER_ID,
                (
                    "Current reviewer endpoint "
                    "returned wrong reviewer ID."
                ),
            )


            assert_equal(
                reviewer[
                    "role"
                ],
                REVIEWER_ROLE,
                (
                    "Current reviewer endpoint "
                    "returned wrong role."
                ),
            )


            assert_equal(
                reviewer[
                    "can_review"
                ],
                True,
                (
                    "REVIEWER should have "
                    "review write access."
                ),
            )


            print(
                "[PASS] Authenticated reviewer "
                "resolved through API"
            )


            # ==================================================
            # 8. DOCUMENT DETAIL API
            # ==================================================

            response = client.get(
                (
                    "/api/v1/documents/"
                    f"{document_id}"
                )
            )


            assert_equal(
                response.status_code,
                200,
                (
                    "Stored document API should "
                    "return HTTP 200."
                ),
            )


            stored = (
                response.json()
            )


            analysis = (
                stored[
                    "analysis"
                ]
            )


            assert_equal(
                analysis[
                    "extraction"
                ][
                    "full_name"
                ][
                    "value"
                ],
                "PHASE 7B FINAL USER",
                (
                    "Machine full name "
                    "is incorrect."
                ),
            )


            assert_equal(
                analysis[
                    "extraction"
                ][
                    "issuer"
                ][
                    "value"
                ],
                "TX DPS",
                (
                    "Machine issuer "
                    "is incorrect."
                ),
            )


            assert_equal(
                analysis[
                    "ocr_lines"
                ][
                    8
                ][
                    "text"
                ],
                "ISSUED BY TX DPS",
                (
                    "Raw OCR evidence "
                    "is incorrect."
                ),
            )


            print(
                "[PASS] Detail API exposes "
                "machine extraction"
            )

            print(
                "[PASS] OCR evidence available "
                "for reviewer provenance"
            )


            # ==================================================
            # 9. ORIGINAL IMAGE RETRIEVAL
            # ==================================================

            response = client.get(
                (
                    "/api/v1/documents/"
                    f"{document_id}"
                    "/image"
                )
            )


            assert_equal(
                response.status_code,
                200,
                (
                    "Original image API should "
                    "return HTTP 200."
                ),
            )


            assert_equal(
                response.content,
                ORIGINAL_BYTES,
                (
                    "Returned original image "
                    "bytes do not match upload."
                ),
            )


            assert_equal(
                response.headers[
                    "content-type"
                ],
                "image/jpeg",
                (
                    "Original image has "
                    "incorrect Content-Type."
                ),
            )


            print(
                "[PASS] Original source image "
                "retrievable by reviewer"
            )

            print(
                "[PASS] Original image bytes "
                "preserved exactly"
            )


            # ==================================================
            # 10. SUBMIT HUMAN CORRECTION
            # PHASE 7C.5 TRUSTED IDENTITY
            # ==================================================

            corrections = {
                "expiry_date":
                    "2027-01-01",

                "issuer":
                    "TX DPS SECURITY",
            }


            review_payload = {

                # ==========================================
                # IMPORTANT:
                # reviewer_id intentionally absent.
                # ==========================================

                "action":
                    "CORRECT",

                "notes":
                    (
                        "Final dashboard E2E "
                        "correction test."
                    ),

                "corrections":
                    corrections,
            }


            if (
                "reviewer_id"
                in review_payload
            ):

                raise AssertionError(
                    "Client review payload "
                    "must not contain reviewer_id."
                )


            response = client.post(
                (
                    "/api/v1/documents/"
                    f"{document_id}"
                    "/reviews"
                ),

                headers=reviewer_headers(
                    REVIEWER_ID
                ),

                json=(
                    review_payload
                ),
            )


            assert_equal(
                response.status_code,
                200,
                (
                    "Human CORRECT should "
                    "return HTTP 200."
                ),
            )


            review_response = (
                response.json()
            )


            assert_equal(
                review_response[
                    "human_action"
                ],
                "CORRECT",
                (
                    "Unexpected human "
                    "review action."
                ),
            )


            # ==================================================
            # VERIFY AUTHENTICATED REVIEWER RESPONSE
            # ==================================================

            authenticated_reviewer = (
                review_response[
                    "authenticated_reviewer"
                ]
            )


            assert_equal(
                authenticated_reviewer[
                    "reviewer_id"
                ],
                REVIEWER_ID,
                (
                    "API did not use trusted "
                    "reviewer identity."
                ),
            )


            assert_equal(
                authenticated_reviewer[
                    "role"
                ],
                REVIEWER_ROLE,
                (
                    "Authenticated reviewer "
                    "role is incorrect."
                ),
            )


            assert_equal(
                authenticated_reviewer[
                    "source"
                ],
                "TRUSTED_HEADER",
                (
                    "Authenticated reviewer "
                    "source is incorrect."
                ),
            )


            assert_equal(
                review_response[
                    "review"
                ][
                    "reviewer_id"
                ],
                REVIEWER_ID,
                (
                    "Review result did not use "
                    "trusted reviewer identity."
                ),
            )


            print(
                "[PASS] Human CORRECT action "
                "accepted by API"
            )

            print(
                "[PASS] Client payload contains "
                "no reviewer_id"
            )

            print(
                "[PASS] API attached trusted "
                "authenticated reviewer"
            )


            # ==================================================
            # 11. VERIFY HUMAN REVIEW DATABASE RECORD
            # ==================================================

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


                human_review = (
                    session
                    .scalars(
                        statement
                    )
                    .one()
                )


                assert_equal(
                    human_review.reviewer_id,
                    REVIEWER_ID,
                    (
                        "Trusted reviewer ID "
                        "was not persisted."
                    ),
                )


                assert_equal(
                    human_review.human_action,
                    "CORRECT",
                    (
                        "Human action was not "
                        "persisted."
                    ),
                )


                assert_equal(
                    human_review.corrections,
                    corrections,
                    (
                        "Corrections were not "
                        "persisted correctly."
                    ),
                )


            print(
                "[PASS] Human review persisted "
                "in PostgreSQL"
            )

            print(
                "[PASS] Trusted reviewer identity "
                "persisted"
            )

            print(
                "[PASS] Human corrections "
                "persisted"
            )


            # ==================================================
            # 12. VERIFY AUDIT HISTORY API
            # ==================================================

            response = client.get(
                (
                    "/api/v1/documents/"
                    f"{document_id}"
                    "/history"
                )
            )


            assert_equal(
                response.status_code,
                200,
                (
                    "Document history should "
                    "return HTTP 200."
                ),
            )


            history = (
                response.json()
            )


            events = (
                history.get(
                    "events",
                    []
                )
            )


            event_types = {
                event.get(
                    "event_type"
                )
                for event
                in events
            }


            if (
                "MACHINE_REVIEW_DECISION"
                not in event_types
            ):

                raise AssertionError(
                    "Machine review audit "
                    "event missing."
                )


            if (
                "HUMAN_REVIEW"
                not in event_types
            ):

                raise AssertionError(
                    "Human review audit "
                    "event missing."
                )


            human_history_events = [
                event
                for event
                in events
                if (
                    event.get(
                        "event_type"
                    )
                    == "HUMAN_REVIEW"
                )
            ]


            assert_equal(
                len(
                    human_history_events
                ),
                1,
                (
                    "Expected exactly one "
                    "HUMAN_REVIEW history event."
                ),
            )


            human_history = (
                human_history_events[
                    0
                ]
            )


            assert_equal(
                human_history[
                    "actor_id"
                ],
                REVIEWER_ID,
                (
                    "History API should expose "
                    "trusted reviewer as actor."
                ),
            )


            print(
                "[PASS] Machine review audit "
                "present"
            )

            print(
                "[PASS] Human review audit "
                "present"
            )

            print(
                "[PASS] History actor uses "
                "trusted reviewer identity"
            )


            # ==================================================
            # 13. DIRECT AUDIT DATABASE VERIFICATION
            # ==================================================

            with SessionLocal() as session:

                statement = (
                    select(
                        AuditEventModel
                    )
                    .where(
                        AuditEventModel.document_id
                        == document_id
                    )
                )


                audit_events = (
                    session
                    .scalars(
                        statement
                    )
                    .all()
                )


                machine_audits = [
                    event
                    for event
                    in audit_events
                    if (
                        event.event_type
                        == "MACHINE_REVIEW_DECISION"
                    )
                ]


                human_audits = [
                    event
                    for event
                    in audit_events
                    if (
                        event.event_type
                        == "HUMAN_REVIEW"
                    )
                ]


                assert_equal(
                    len(
                        machine_audits
                    ),
                    1,
                    (
                        "Exactly one machine "
                        "audit should exist."
                    ),
                )


                assert_equal(
                    len(
                        human_audits
                    ),
                    1,
                    (
                        "Exactly one human "
                        "audit should exist."
                    ),
                )


                assert_equal(
                    human_audits[
                        0
                    ].actor_id,
                    REVIEWER_ID,
                    (
                        "PostgreSQL human audit "
                        "actor_id is incorrect."
                    ),
                )


            print(
                "[PASS] PostgreSQL audit "
                "records verified"
            )

            print(
                "[PASS] Human audit actor_id "
                "uses trusted reviewer identity"
            )


            # ==================================================
            # 14. REVIEWED DOCUMENT REMOVED FROM QUEUE
            # ==================================================

            response = client.get(
                "/api/v1/reviews/queue"
            )


            assert_equal(
                response.status_code,
                200,
                (
                    "Review queue should "
                    "return HTTP 200."
                ),
            )


            remaining_ids = {
                item[
                    "document_id"
                ]
                for item
                in response.json()[
                    "documents"
                ]
            }


            if (
                document_id
                in remaining_ids
            ):

                raise AssertionError(
                    "Human-reviewed document "
                    "still appears in queue."
                )


            print(
                "[PASS] Human-reviewed document "
                "removed from pending queue"
            )


            # ==================================================
            # 15. ORIGINAL MACHINE EXTRACTION PRESERVED
            # ==================================================

            response = client.get(
                (
                    "/api/v1/documents/"
                    f"{document_id}"
                )
            )


            assert_equal(
                response.status_code,
                200,
                (
                    "Reviewed document should "
                    "remain retrievable."
                ),
            )


            reviewed_document = (
                response.json()
            )


            stored_after_review = (
                reviewed_document[
                    "analysis"
                ]
            )


            assert_equal(
                stored_after_review[
                    "extraction"
                ][
                    "expiry_date"
                ][
                    "value"
                ],
                "2026-01-01",
                (
                    "Human correction must "
                    "not overwrite machine "
                    "expiry extraction."
                ),
            )


            assert_equal(
                stored_after_review[
                    "extraction"
                ][
                    "issuer"
                ][
                    "value"
                ],
                "TX DPS",
                (
                    "Human correction must "
                    "not overwrite machine "
                    "issuer extraction."
                ),
            )


            print(
                "[PASS] Original machine "
                "extraction preserved"
            )


            # ==================================================
            # 16. VERIFY FINAL RECORD
            # ==================================================

            final_record = (
                reviewed_document[
                    "final_record"
                ]
            )


            assert_equal(
                final_record[
                    "final_status"
                ],
                "CORRECTED",
                (
                    "Final record should "
                    "be CORRECTED."
                ),
            )


            assert_equal(
                final_record[
                    "is_final"
                ],
                True,
                (
                    "CORRECTED record should "
                    "be final."
                ),
            )


            assert_equal(
                final_record[
                    "is_usable"
                ],
                True,
                (
                    "CORRECTED record should "
                    "be downstream usable."
                ),
            )


            assert_equal(
                final_record[
                    "effective_values"
                ][
                    "expiry_date"
                ],
                "2027-01-01",
                (
                    "Human corrected expiry "
                    "missing from final record."
                ),
            )


            assert_equal(
                final_record[
                    "effective_values"
                ][
                    "issuer"
                ],
                "TX DPS SECURITY",
                (
                    "Human corrected issuer "
                    "missing from final record."
                ),
            )


            assert_equal(
                final_record[
                    "value_sources"
                ][
                    "expiry_date"
                ],
                "HUMAN_CORRECTION",
                (
                    "Corrected expiry should "
                    "show HUMAN_CORRECTION."
                ),
            )


            assert_equal(
                final_record[
                    "value_sources"
                ][
                    "issuer"
                ],
                "HUMAN_CORRECTION",
                (
                    "Corrected issuer should "
                    "show HUMAN_CORRECTION."
                ),
            )


            print(
                "[PASS] Final record is "
                "CORRECTED and usable"
            )

            print(
                "[PASS] Effective values contain "
                "human corrections"
            )

            print(
                "[PASS] Correction provenance "
                "preserved"
            )


            # ==================================================
            # FINAL SUCCESS
            # ==================================================

            print()
            print("=" * 76)
            print(
                "[PASS] PHASE 7B.9 FINAL "
                "DASHBOARD END-TO-END TEST PASSED"
            )
            print("=" * 76)


        finally:

            # ==================================================
            # CLOSE TEST CLIENT
            # ==================================================

            if client is not None:

                client.close()


            # ==================================================
            # DATABASE CLEANUP
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


            # ==================================================
            # STORAGE CLEANUP
            # ==================================================

            if document_id is not None:

                storage_service.delete_document(
                    document_id
                )


            # ==================================================
            # APP STATE CLEANUP
            # ==================================================

            for state_name in (
                "pipeline",
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
                "[CLEANUP] Phase 7B.9 "
                "temporary database and "
                "storage data removed."
            )


if __name__ == "__main__":

    main()