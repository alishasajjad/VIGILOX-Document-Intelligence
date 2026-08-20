import tempfile

from pathlib import Path

from fastapi.testclient import (
    TestClient,
)

from sqlalchemy import (
    select,
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

from backend.app.services.document_storage_service import (
    DocumentStorageService,
)

from backend.app.services.human_review_service import (
    HumanReviewService,
)

from backend.app.services.reviewer_identity_service import (
    ReviewerIdentityService,
)


# ==========================================================
# TEST CONSTANTS
# ==========================================================

ORIGINAL_FILENAME = (
    "phase7c_identity_dashboard_guard.jpg"
)


ORIGINAL_BYTES = (
    b"VIGILOX-PHASE-7C-5-"
    b"IDENTITY-DASHBOARD-E2E"
)


AUTHENTICATED_REVIEWER_ID = (
    "local-reviewer-001"
)


AUTHENTICATED_REVIEWER_ROLE = (
    "REVIEWER"
)


CORRECTIONS = {
    "expiry_date":
        "2027-01-01",

    "issuer":
        "TX DPS SECURITY",
}


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
                "Temporary uploaded image "
                "bytes do not match source."
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
            # EXTRACTION
            # ==============================================

            "extraction": {

                "document_type":
                    "guard_license",

                "full_name": {
                    "value":
                        "PHASE 7C IDENTITY USER",

                    "source_line_ids": [
                        "L0"
                    ],
                },

                "licence_number": {
                    "value":
                        "P7C500001",

                    "source_line_ids": [
                        "L1",
                        "L2",
                    ],
                },

                "id_number": {
                    "value":
                        None,

                    "source_line_ids":
                        [],
                },

                "issue_date": {
                    "value":
                        "2025-01-01",

                    "source_line_ids": [
                        "L3"
                    ],
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

                "issuer": {
                    "value":
                        "TX DPS",

                    "source_line_ids": [
                        "L8"
                    ],
                },
            },


            # ==============================================
            # OCR WITH EXPLICIT LINE IDS
            # ==============================================

            "ocr_lines": [

                {
                    "line_id":
                        "L0",

                    "text":
                        "PHASE 7C IDENTITY USER",

                    "confidence":
                        0.998,

                    "bbox":
                        [10, 10, 250, 35],
                },

                {
                    "line_id":
                        "L1",

                    "text":
                        "LICENSE",

                    "confidence":
                        0.999,

                    "bbox":
                        [10, 40, 100, 60],
                },

                {
                    "line_id":
                        "L2",

                    "text":
                        "P7C500001",

                    "confidence":
                        0.999,

                    "bbox":
                        [110, 40, 220, 60],
                },

                {
                    "line_id":
                        "L3",

                    "text":
                        "PRINTDATE 01/01/2025",

                    "confidence":
                        0.997,

                    "bbox":
                        [10, 70, 240, 90],
                },

                {
                    "line_id":
                        "L4",

                    "text":
                        "EXPIRES",

                    "confidence":
                        0.999,

                    "bbox":
                        [10, 100, 100, 120],
                },

                {
                    "line_id":
                        "L5",

                    "text":
                        "01/01/2026",

                    "confidence":
                        0.999,

                    "bbox":
                        [110, 100, 220, 120],
                },

                {
                    "line_id":
                        "L6",

                    "text":
                        "DOB",

                    "confidence":
                        0.999,

                    "bbox":
                        [10, 130, 60, 150],
                },

                {
                    "line_id":
                        "L7",

                    "text":
                        "01/01/1990",

                    "confidence":
                        0.999,

                    "bbox":
                        [70, 130, 180, 150],
                },

                {
                    "line_id":
                        "L8",

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

                "issue_date":
                    0.997,

                "expiry_date":
                    0.999,

                "date_of_birth":
                    0.999,

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
            # REVIEW DECISION
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
# ASSERTION HELPERS
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


def assert_false(
    condition: bool,
    message: str,
):

    if condition:

        raise AssertionError(
            message
        )


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("=" * 76)
    print(
        "PHASE 7C.5e — REVIEWER IDENTITY "
        "DASHBOARD FINAL END-TO-END TEST"
    )
    print("=" * 76)


    document_id = None

    client = None


    with tempfile.TemporaryDirectory() as temp_dir:

        temp_root = Path(
            temp_dir
        )


        # ==================================================
        # ISOLATED ORIGINAL DOCUMENT STORAGE
        # ==================================================

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
            # 1. APPLICATION SERVICES
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


            app.state.reviewer_identity = (
                ReviewerIdentityService(
                    mode=(
                        "local_env"
                    ),

                    local_reviewer_id=(
                        AUTHENTICATED_REVIEWER_ID
                    ),

                    local_reviewer_role=(
                        AUTHENTICATED_REVIEWER_ROLE
                    ),
                )
            )


            client = (
                TestClient(
                    app
                )
            )


            print(
                "[OK] Phase 7C.5e application "
                "services initialized"
            )


            # ==================================================
            # 2. DASHBOARD HTML TRUST-BOUNDARY CONTRACT
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 1 — DASHBOARD HTML "
                "AUTHENTICATED REVIEWER UI"
            )
            print("-" * 76)


            response = client.get(
                "/review/test-document-id"
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


            # --------------------------------------------------
            # Authenticated reviewer UI must exist.
            # --------------------------------------------------

            required_html = [
                'id="authenticated-reviewer-section"',
                'id="authenticated-reviewer-card"',
                'id="authenticated-reviewer-name"',
                'id="authenticated-reviewer-role"',
                'id="authenticated-reviewer-source"',
                'id="authenticated-reviewer-access"',
                'id="human-review-form"',
            ]


            for marker in required_html:

                assert_true(
                    marker
                    in detail_html,
                    (
                        "Dashboard HTML missing "
                        f"Phase 7C.5 marker: {marker}"
                    ),
                )


            # --------------------------------------------------
            # Old editable reviewer field must be removed.
            # --------------------------------------------------

            assert_false(
                'id="reviewer-id"'
                in detail_html,
                (
                    "Dashboard still contains "
                    "editable reviewer-id input."
                ),
            )


            assert_false(
                'for="reviewer-id"'
                in detail_html,
                (
                    "Dashboard still contains "
                    "old reviewer-id label."
                ),
            )


            print(
                "[PASS] Authenticated reviewer "
                "card exists in dashboard"
            )

            print(
                "[PASS] Editable reviewer ID "
                "input removed from HTML"
            )


            # ==================================================
            # 3. DASHBOARD JAVASCRIPT TRUST BOUNDARY
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 2 — DASHBOARD JAVASCRIPT "
                "TRUST BOUNDARY"
            )
            print("-" * 76)


            response = client.get(
                "/review/static/review_detail.js"
            )


            assert_equal(
                response.status_code,
                200,
                (
                    "review_detail.js should "
                    "return HTTP 200."
                ),
            )


            detail_js = (
                response.text
            )


            required_js_features = [
                '"/api/v1/reviewer/me"',
                "loadReviewerIdentity",
                "renderReviewerIdentity",
                "loadedReviewerIdentity",
                "can_review",
                "authenticatedReviewerName",
                "authenticatedReviewerRole",
                "authenticatedReviewerSource",
                "authenticatedReviewerAccess",
            ]


            for feature in required_js_features:

                assert_true(
                    feature
                    in detail_js,
                    (
                        "Dashboard JavaScript "
                        f"missing feature: {feature}"
                    ),
                )


            # --------------------------------------------------
            # Old reviewer form mechanisms must be gone.
            # --------------------------------------------------

            assert_false(
                "getReviewerId("
                in detail_js,
                (
                    "Dashboard JavaScript still "
                    "contains getReviewerId()."
                ),
            )


            assert_false(
                "reviewerIdInput"
                in detail_js,
                (
                    "Dashboard JavaScript still "
                    "references reviewerIdInput."
                ),
            )


            # --------------------------------------------------
            # Inspect the actual human-review payload object.
            # --------------------------------------------------

            payload_start = (
                detail_js.find(
                    "const payload = {"
                )
            )


            assert_true(
                payload_start
                != -1,
                (
                    "Human review payload "
                    "construction not found."
                ),
            )


            payload_end = (
                detail_js.find(
                    "};",
                    payload_start,
                )
            )


            assert_true(
                payload_end
                != -1,
                (
                    "Human review payload "
                    "closing marker not found."
                ),
            )


            payload_block = (
                detail_js[
                    payload_start:
                    payload_end
                ]
            )


            assert_false(
                "reviewer_id"
                in payload_block,
                (
                    "Dashboard review payload "
                    "still sends reviewer_id."
                ),
            )


            assert_true(
                "action:"
                in payload_block,
                (
                    "Dashboard review payload "
                    "is missing action."
                ),
            )


            assert_true(
                "notes:"
                in payload_block,
                (
                    "Dashboard review payload "
                    "is missing notes."
                ),
            )


            print(
                "[PASS] Dashboard loads identity "
                "from /api/v1/reviewer/me"
            )

            print(
                "[PASS] Dashboard no longer "
                "uses getReviewerId()"
            )

            print(
                "[PASS] Review POST payload "
                "does not contain reviewer_id"
            )


            # ==================================================
            # 4. CURRENT AUTHENTICATED REVIEWER
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 3 — CURRENT REVIEWER ENDPOINT"
            )
            print("-" * 76)


            response = client.get(
                "/api/v1/reviewer/me"
            )


            assert_equal(
                response.status_code,
                200,
                (
                    "Current reviewer endpoint "
                    "should return HTTP 200."
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
                AUTHENTICATED_REVIEWER_ID,
                (
                    "Unexpected authenticated "
                    "reviewer ID."
                ),
            )


            assert_equal(
                reviewer[
                    "role"
                ],
                AUTHENTICATED_REVIEWER_ROLE,
                (
                    "Unexpected reviewer role."
                ),
            )


            assert_equal(
                reviewer[
                    "source"
                ],
                "LOCAL_ENV",
                (
                    "Unexpected reviewer "
                    "identity source."
                ),
            )


            assert_equal(
                reviewer[
                    "can_review"
                ],
                True,
                (
                    "Local REVIEWER should "
                    "have review access."
                ),
            )


            print(
                "[PASS] Reviewer identity "
                "resolved server-side"
            )

            print(
                "[PASS] Local reviewer has "
                "review write access"
            )


            # ==================================================
            # 5. UPLOAD + MACHINE ANALYSIS
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 4 — DOCUMENT ANALYSIS "
                "AND PENDING REVIEW"
            )
            print("-" * 76)


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
                    "Analyze API should "
                    "return HTTP 200."
                ),
            )


            analyze_body = (
                response.json()
            )


            document_id = (
                analyze_body[
                    "document_id"
                ]
            )


            assert_true(
                bool(
                    document_id
                ),
                (
                    "Analyze response missing "
                    "document_id."
                ),
            )


            assert_equal(
                analyze_body[
                    "original_document_stored"
                ],
                True,
                (
                    "Original document should "
                    "be permanently stored."
                ),
            )


            print(
                "[PASS] Test document analyzed "
                "and persisted"
            )

            print(
                "[PASS] Original source document "
                "stored successfully"
            )


            # ==================================================
            # 6. VERIFY INITIAL PENDING STATE
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
                    "Document detail should "
                    "return HTTP 200."
                ),
            )


            pending = (
                response.json()
            )


            assert_equal(
                pending[
                    "human_review"
                ],
                None,
                (
                    "New document should not "
                    "have a human review."
                ),
            )


            pending_final = (
                pending[
                    "final_record"
                ]
            )


            assert_equal(
                pending_final[
                    "final_status"
                ],
                "PENDING_REVIEW",
                (
                    "Initial final status "
                    "should be PENDING_REVIEW."
                ),
            )


            assert_equal(
                pending_final[
                    "is_final"
                ],
                False,
                (
                    "Pending record should "
                    "not be final."
                ),
            )


            assert_equal(
                pending_final[
                    "is_usable"
                ],
                False,
                (
                    "Pending record should "
                    "not be usable."
                ),
            )


            assert_equal(
                pending_final[
                    "effective_values"
                ],
                None,
                (
                    "Pending document should "
                    "not expose effective values."
                ),
            )


            print(
                "[PASS] Initial status is "
                "PENDING_REVIEW"
            )

            print(
                "[PASS] Pending effective "
                "values withheld"
            )


            # ==================================================
            # 7. PENDING QUEUE
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


            queue_ids = {
                item[
                    "document_id"
                ]

                for item
                in response.json()[
                    "documents"
                ]
            }


            assert_true(
                document_id
                in queue_ids,
                (
                    "Pending review document "
                    "is missing from queue."
                ),
            )


            print(
                "[PASS] Document appears in "
                "pending review queue"
            )


            # ==================================================
            # 8. SUBMIT REVIEW WITHOUT REVIEWER_ID
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 5 — REVIEW SUBMISSION "
                "WITHOUT CLIENT REVIEWER_ID"
            )
            print("-" * 76)


            review_payload = {

                # ==========================================
                # IMPORTANT:
                # reviewer_id is intentionally absent.
                # ==========================================

                "action":
                    "CORRECT",

                "notes":
                    (
                        "Phase 7C.5 final "
                        "identity dashboard E2E."
                    ),

                "corrections":
                    CORRECTIONS,
            }


            assert_false(
                "reviewer_id"
                in review_payload,
                (
                    "Test review payload "
                    "must not contain reviewer_id."
                ),
            )


            response = client.post(
                (
                    "/api/v1/documents/"
                    f"{document_id}"
                    "/reviews"
                ),

                json=(
                    review_payload
                ),
            )


            assert_equal(
                response.status_code,
                200,
                (
                    "Authenticated review "
                    "without client reviewer_id "
                    "should return HTTP 200."
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


            assert_equal(
                review_response[
                    "authenticated_reviewer"
                ][
                    "reviewer_id"
                ],
                AUTHENTICATED_REVIEWER_ID,
                (
                    "API did not use "
                    "server-side reviewer ID."
                ),
            )


            assert_equal(
                review_response[
                    "authenticated_reviewer"
                ][
                    "role"
                ],
                AUTHENTICATED_REVIEWER_ROLE,
                (
                    "API returned incorrect "
                    "authenticated reviewer role."
                ),
            )


            assert_equal(
                review_response[
                    "authenticated_reviewer"
                ][
                    "source"
                ],
                "LOCAL_ENV",
                (
                    "API returned incorrect "
                    "identity source."
                ),
            )


            assert_equal(
                review_response[
                    "review"
                ][
                    "reviewer_id"
                ],
                AUTHENTICATED_REVIEWER_ID,
                (
                    "Human review result did "
                    "not use authenticated identity."
                ),
            )


            print(
                "[PASS] Review accepted without "
                "client reviewer_id"
            )

            print(
                "[PASS] API attached server-side "
                "authenticated reviewer"
            )


            # ==================================================
            # 9. POSTGRESQL HUMAN REVIEW IDENTITY
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 6 — POSTGRESQL "
                "REVIEWER IDENTITY"
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


                stored_review = (
                    session
                    .scalars(
                        statement
                    )
                    .one()
                )


                assert_equal(
                    stored_review.reviewer_id,
                    AUTHENTICATED_REVIEWER_ID,
                    (
                        "PostgreSQL human review "
                        "contains wrong reviewer ID."
                    ),
                )


                assert_equal(
                    stored_review.human_action,
                    "CORRECT",
                    (
                        "PostgreSQL human action "
                        "should be CORRECT."
                    ),
                )


                assert_equal(
                    stored_review.corrections,
                    CORRECTIONS,
                    (
                        "PostgreSQL corrections "
                        "are incorrect."
                    ),
                )


            print(
                "[PASS] PostgreSQL reviewer_id "
                "comes from authenticated identity"
            )

            print(
                "[PASS] Human corrections "
                "persisted"
            )


            # ==================================================
            # 10. AUDIT ACTOR IDENTITY
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 7 — AUDIT ACTOR IDENTITY"
            )
            print("-" * 76)


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


                machine_events = [
                    event
                    for event
                    in audit_events
                    if (
                        event.event_type
                        == "MACHINE_REVIEW_DECISION"
                    )
                ]


                human_events = [
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
                        machine_events
                    ),
                    1,
                    (
                        "Expected exactly one "
                        "machine review audit."
                    ),
                )


                assert_equal(
                    len(
                        human_events
                    ),
                    1,
                    (
                        "Expected exactly one "
                        "human review audit."
                    ),
                )


                human_audit = (
                    human_events[
                        0
                    ]
                )


                assert_equal(
                    human_audit.actor_id,
                    AUTHENTICATED_REVIEWER_ID,
                    (
                        "Human audit actor_id "
                        "does not match "
                        "authenticated reviewer."
                    ),
                )


                human_details = (
                    human_audit.details
                    or {}
                )


                assert_equal(
                    human_details.get(
                        "human_action"
                    ),
                    "CORRECT",
                    (
                        "Human audit action "
                        "is incorrect."
                    ),
                )


                assert_equal(
                    human_details.get(
                        "corrections"
                    ),
                    CORRECTIONS,
                    (
                        "Human audit corrections "
                        "are incorrect."
                    ),
                )


            print(
                "[PASS] Human audit actor_id "
                "uses authenticated identity"
            )

            print(
                "[PASS] Audit corrections and "
                "action preserved"
            )


            # ==================================================
            # 11. REVIEW HISTORY API
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 8 — REVIEW HISTORY API"
            )
            print("-" * 76)


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


            events = (
                response.json()
                .get(
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


            assert_true(
                "MACHINE_REVIEW_DECISION"
                in event_types,
                (
                    "Machine review event "
                    "missing from history."
                ),
            )


            assert_true(
                "HUMAN_REVIEW"
                in event_types,
                (
                    "Human review event "
                    "missing from history."
                ),
            )


            human_history = [
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
                    human_history
                ),
                1,
                (
                    "Expected one human "
                    "history event."
                ),
            )


            assert_equal(
                human_history[
                    0
                ][
                    "actor_id"
                ],
                AUTHENTICATED_REVIEWER_ID,
                (
                    "History API actor_id "
                    "is incorrect."
                ),
            )


            print(
                "[PASS] Review history exposes "
                "authenticated reviewer actor"
            )


            # ==================================================
            # 12. FINAL REVIEWED RECORD
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 9 — FINAL CORRECTED RECORD"
            )
            print("-" * 76)


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


            reviewed = (
                response.json()
            )


            human_review_api = (
                reviewed[
                    "human_review"
                ]
            )


            final_record = (
                reviewed[
                    "final_record"
                ]
            )


            assert_equal(
                human_review_api[
                    "reviewer_id"
                ],
                AUTHENTICATED_REVIEWER_ID,
                (
                    "Document detail API "
                    "contains wrong reviewer ID."
                ),
            )


            assert_equal(
                human_review_api[
                    "human_action"
                ],
                "CORRECT",
                (
                    "Document detail API "
                    "contains wrong action."
                ),
            )


            assert_equal(
                final_record[
                    "final_status"
                ],
                "CORRECTED",
                (
                    "Final status should "
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
                    "Corrected expiry not "
                    "applied to effective values."
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
                    "Corrected issuer not "
                    "applied to effective values."
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
                    "Expiry correction source "
                    "should be HUMAN_CORRECTION."
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
                    "Issuer correction source "
                    "should be HUMAN_CORRECTION."
                ),
            )


            print(
                "[PASS] Final record changed "
                "to CORRECTED"
            )

            print(
                "[PASS] Human corrections appear "
                "in effective values"
            )

            print(
                "[PASS] Correction provenance "
                "is HUMAN_CORRECTION"
            )


            # ==================================================
            # 13. MACHINE EXTRACTION IMMUTABLE
            # ==================================================

            machine_extraction = (
                reviewed[
                    "analysis"
                ][
                    "extraction"
                ]
            )


            assert_equal(
                machine_extraction[
                    "expiry_date"
                ][
                    "value"
                ],
                "2026-01-01",
                (
                    "Machine expiry was "
                    "incorrectly overwritten."
                ),
            )


            assert_equal(
                machine_extraction[
                    "issuer"
                ][
                    "value"
                ],
                "TX DPS",
                (
                    "Machine issuer was "
                    "incorrectly overwritten."
                ),
            )


            print(
                "[PASS] Original machine "
                "extraction remains immutable"
            )


            # ==================================================
            # 14. REVIEWED DOCUMENT REMOVED FROM QUEUE
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 10 — QUEUE REMOVAL"
            )
            print("-" * 76)


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


            assert_false(
                document_id
                in remaining_ids,
                (
                    "Reviewed document still "
                    "appears in pending queue."
                ),
            )


            print(
                "[PASS] Reviewed document "
                "removed from queue"
            )


            # ==================================================
            # 15. DUPLICATE REVIEW STILL BLOCKED
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 11 — DUPLICATE REVIEW PROTECTION"
            )
            print("-" * 76)


            response = client.post(
                (
                    "/api/v1/documents/"
                    f"{document_id}"
                    "/reviews"
                ),

                json={
                    # --------------------------------------
                    # Again no reviewer_id.
                    # --------------------------------------

                    "action":
                        "APPROVE",

                    "notes":
                        (
                            "Duplicate review "
                            "attempt."
                        ),
                },
            )


            assert_equal(
                response.status_code,
                409,
                (
                    "Duplicate review should "
                    "return HTTP 409."
                ),
            )


            print(
                "[PASS] Duplicate review "
                "protection remains active"
            )


            # ==================================================
            # 16. FIRST REVIEW REMAINS AUTHORITATIVE
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
                    "Document should remain "
                    "retrievable after duplicate "
                    "review attempt."
                ),
            )


            after_duplicate = (
                response.json()
            )


            assert_equal(
                after_duplicate[
                    "human_review"
                ][
                    "reviewer_id"
                ],
                AUTHENTICATED_REVIEWER_ID,
                (
                    "Duplicate review changed "
                    "authoritative reviewer."
                ),
            )


            assert_equal(
                after_duplicate[
                    "final_record"
                ][
                    "final_status"
                ],
                "CORRECTED",
                (
                    "Duplicate review changed "
                    "final status."
                ),
            )


            assert_equal(
                after_duplicate[
                    "final_record"
                ][
                    "effective_values"
                ][
                    "expiry_date"
                ],
                "2027-01-01",
                (
                    "Duplicate review altered "
                    "effective values."
                ),
            )


            print(
                "[PASS] First review remains "
                "authoritative after duplicate attempt"
            )


            # ==================================================
            # 17. EXACT REVIEW / AUDIT COUNTS
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 12 — FINAL DATABASE COUNTS"
            )
            print("-" * 76)


            with SessionLocal() as session:

                review_statement = (
                    select(
                        HumanReviewModel
                    )
                    .where(
                        HumanReviewModel.document_id
                        == document_id
                    )
                )


                reviews = (
                    session
                    .scalars(
                        review_statement
                    )
                    .all()
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


                human_audits = (
                    session
                    .scalars(
                        human_audit_statement
                    )
                    .all()
                )


                assert_equal(
                    len(
                        reviews
                    ),
                    1,
                    (
                        "Exactly one human "
                        "review should exist."
                    ),
                )


                assert_equal(
                    len(
                        human_audits
                    ),
                    1,
                    (
                        "Exactly one human "
                        "review audit should exist."
                    ),
                )


                assert_equal(
                    reviews[
                        0
                    ].reviewer_id,
                    AUTHENTICATED_REVIEWER_ID,
                    (
                        "Final stored reviewer "
                        "identity is incorrect."
                    ),
                )


                assert_equal(
                    human_audits[
                        0
                    ].actor_id,
                    AUTHENTICATED_REVIEWER_ID,
                    (
                        "Final audit actor "
                        "identity is incorrect."
                    ),
                )


            print(
                "[PASS] Exactly one human "
                "review persisted"
            )

            print(
                "[PASS] Exactly one human "
                "audit persisted"
            )

            print(
                "[PASS] Final reviewer and "
                "audit actor identities match"
            )


            # ==================================================
            # FINAL SUCCESS
            # ==================================================

            print()
            print("=" * 76)
            print(
                "[PASS] PHASE 7C.5e REVIEWER "
                "IDENTITY DASHBOARD FINAL "
                "END-TO-END TEST PASSED"
            )
            print("=" * 76)


        finally:

            # ==================================================
            # CLOSE CLIENT
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
            # DOCUMENT STORAGE CLEANUP
            # ==================================================

            if document_id is not None:

                storage_service.delete_document(
                    document_id
                )


            # ==================================================
            # APPLICATION STATE CLEANUP
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
                "[CLEANUP] Phase 7C.5e "
                "temporary database and "
                "storage data removed."
            )


if __name__ == "__main__":

    main()