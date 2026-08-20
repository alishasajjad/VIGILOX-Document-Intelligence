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
    "phase7c_final_status_guard.jpg"
)


ORIGINAL_BYTES = (
    b"VIGILOX-PHASE-7C-4-"
    b"FINAL-STATUS-DASHBOARD"
)


REVIEWER_ID = (
    "phase7c-dashboard-reviewer"
)


REVIEWER_ROLE = (
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
                        "PHASE 7C DASHBOARD USER",

                    "source_line_ids": [
                        "L0"
                    ],
                },

                "licence_number": {
                    "value":
                        "P7C400001",

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
            # EXPLICIT OCR LINE IDS
            # PHASE 7C.2
            # ==============================================

            "ocr_lines": [

                {
                    "line_id":
                        "L0",

                    "text":
                        "PHASE 7C DASHBOARD USER",

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
                        "P7C400001",

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
            # EVIDENCE
            # ==============================================

            "evidence_flags":
                [],


            # ==============================================
            # FIELD CONFIDENCE
            # ==============================================

            "field_confidence": {

                "full_name": {
                    "value":
                        "PHASE 7C DASHBOARD USER",

                    "confidence":
                        0.998,

                    "status":
                        "VALID",
                },

                "licence_number": {
                    "value":
                        "P7C400001",

                    "confidence":
                        0.999,

                    "status":
                        "VALID",
                },

                "id_number": {
                    "value":
                        None,

                    "confidence":
                        None,

                    "status":
                        "NOT_EXTRACTED",
                },

                "issue_date": {
                    "value":
                        "2025-01-01",

                    "confidence":
                        0.997,

                    "status":
                        "VALID",
                },

                "expiry_date": {
                    "value":
                        "2026-01-01",

                    "confidence":
                        0.999,

                    "status":
                        "VALID",
                },

                "date_of_birth": {
                    "value":
                        "1990-01-01",

                    "confidence":
                        0.999,

                    "status":
                        "VALID",
                },

                "issuer": {
                    "value":
                        "TX DPS",

                    "confidence":
                        0.988,

                    "status":
                        "VALID",
                },
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
            # ANOMALIES
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


# ==========================================================
# REVIEWER AUTH HEADERS
# PHASE 7C.5 REGRESSION COMPATIBILITY
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
        "PHASE 7C.4 — FINAL STATUS "
        "DASHBOARD END-TO-END TEST"
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
                "[OK] Phase 7C.4 test "
                "services initialized"
            )


            # ==================================================
            # 2. REVIEW DETAIL HTML CONTRACT
            # ==================================================

            response = client.get(
                "/review/test-document-id"
            )


            assert_equal(
                response.status_code,
                200,
                (
                    "Review detail HTML route "
                    "should return HTTP 200."
                ),
            )


            detail_html = (
                response.text
            )


            required_html_ids = [
                'id="final-status"',
                'id="final-is-final"',
                'id="final-is-usable"',
                'id="effective-values"',
                'id="completed-review-summary"',
                'id="human-review-form"',
                'id="review-locked-message"',
                'id="review-history-list"',
                'id="authenticated-reviewer-card"',
            ]


            for html_id in required_html_ids:

                assert_true(
                    html_id
                    in detail_html,
                    (
                        "Phase 7C.4/7C.5 detail HTML "
                        f"is missing {html_id}."
                    ),
                )


            assert_true(
                'id="reviewer-id"'
                not in detail_html,
                (
                    "Legacy editable reviewer "
                    "ID input must not exist."
                ),
            )


            print(
                "[PASS] Detail HTML exposes "
                "Phase 7C.4 final-state UI"
            )

            print(
                "[PASS] Detail HTML exposes "
                "authenticated reviewer UI"
            )

            print(
                "[PASS] Legacy editable "
                "reviewer ID removed"
            )


            # ==================================================
            # 3. REVIEW DETAIL JAVASCRIPT CONTRACT
            # ==================================================

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
                "renderFinalRecord",
                "renderEffectiveValues",
                "renderHumanReviewState",
                "renderReviewHistory",
                "loadReviewHistory",
                "loadReviewerIdentity",
                "renderReviewerIdentity",
                "/api/v1/reviewer/me",
                "HUMAN_CORRECTION",
                "PENDING_REVIEW",
                "CORRECTED",
                "REJECTED",
                "AUTO_ACCEPTED",
            ]


            for feature in required_js_features:

                assert_true(
                    feature
                    in detail_js,
                    (
                        "Phase 7C.4/7C.5 "
                        "JavaScript is missing "
                        f"{feature}."
                    ),
                )


            assert_true(
                "getReviewerId("
                not in detail_js,
                (
                    "Legacy getReviewerId() "
                    "must not exist."
                ),
            )


            assert_true(
                "reviewerIdInput"
                not in detail_js,
                (
                    "Legacy reviewerIdInput "
                    "must not exist."
                ),
            )


            print(
                "[PASS] Dashboard JavaScript "
                "contains final-status rendering"
            )

            print(
                "[PASS] Dashboard JavaScript "
                "contains review-history rendering"
            )

            print(
                "[PASS] Dashboard JavaScript "
                "contains reviewed-state locking"
            )

            print(
                "[PASS] Dashboard JavaScript "
                "uses authenticated reviewer identity"
            )


            # ==================================================
            # 4. AUTHENTICATED REVIEWER ENDPOINT
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
                    "Reviewer endpoint returned "
                    "wrong reviewer ID."
                ),
            )


            assert_equal(
                reviewer[
                    "role"
                ],
                REVIEWER_ROLE,
                (
                    "Reviewer endpoint returned "
                    "wrong role."
                ),
            )


            assert_equal(
                reviewer[
                    "source"
                ],
                "TRUSTED_HEADER",
                (
                    "Reviewer endpoint returned "
                    "wrong identity source."
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
                "[PASS] Trusted reviewer "
                "identity resolved through API"
            )


            # ==================================================
            # 5. UPLOAD DOCUMENT
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
                "[PASS] Test document uploaded "
                "and machine analysis persisted"
            )


            # ==================================================
            # 6. PENDING FINAL RECORD
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
                    "Pending document detail "
                    "should return HTTP 200."
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
                    "New review-required document "
                    "should not yet have "
                    "human review."
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
                    "Initial final status should "
                    "be PENDING_REVIEW."
                ),
            )


            assert_equal(
                pending_final[
                    "is_final"
                ],
                False,
                (
                    "Pending record must not "
                    "be final."
                ),
            )


            assert_equal(
                pending_final[
                    "is_usable"
                ],
                False,
                (
                    "Pending record must not "
                    "be downstream usable."
                ),
            )


            assert_equal(
                pending_final[
                    "effective_values"
                ],
                None,
                (
                    "Pending review must not "
                    "publish effective values."
                ),
            )


            print(
                "[PASS] Pending detail exposes "
                "PENDING_REVIEW state"
            )

            print(
                "[PASS] Effective values are "
                "withheld before human review"
            )


            # ==================================================
            # 7. EXPLICIT OCR EVIDENCE AVAILABLE
            # ==================================================

            ocr_lines = (
                pending[
                    "analysis"
                ][
                    "ocr_lines"
                ]
            )


            ocr_lookup = {
                line[
                    "line_id"
                ]:
                    line

                for line
                in ocr_lines
            }


            assert_equal(
                ocr_lookup[
                    "L8"
                ][
                    "text"
                ],
                "ISSUED BY TX DPS",
                (
                    "Explicit L8 OCR evidence "
                    "was not preserved."
                ),
            )


            assert_equal(
                pending[
                    "analysis"
                ][
                    "extraction"
                ][
                    "issuer"
                ][
                    "source_line_ids"
                ],
                [
                    "L8"
                ],
                (
                    "Issuer provenance should "
                    "reference explicit L8."
                ),
            )


            print(
                "[PASS] Explicit OCR evidence "
                "available to dashboard"
            )


            # ==================================================
            # 8. DOCUMENT APPEARS IN QUEUE
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


            pending_ids = {
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
                in pending_ids,
                (
                    "Pending test document "
                    "should appear in queue."
                ),
            )


            print(
                "[PASS] Pending document "
                "appears in review queue"
            )


            # ==================================================
            # 9. ORIGINAL IMAGE
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
                    "Original image should "
                    "return HTTP 200."
                ),
            )


            assert_equal(
                response.content,
                ORIGINAL_BYTES,
                (
                    "Stored original image "
                    "bytes changed."
                ),
            )


            print(
                "[PASS] Original source image "
                "available to reviewer"
            )


            # ==================================================
            # 10. SUBMIT HUMAN CORRECTION
            # PHASE 7C.5 TRUSTED IDENTITY
            # ==================================================

            review_payload = {

                # ==========================================
                # reviewer_id intentionally absent.
                # ==========================================

                "action":
                    "CORRECT",

                "notes":
                    (
                        "Phase 7C.4 final "
                        "status dashboard test."
                    ),

                "corrections":
                    CORRECTIONS,
            }


            assert_true(
                "reviewer_id"
                not in review_payload,
                (
                    "Client review payload "
                    "must not contain reviewer_id."
                ),
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
                    "CORRECT review should "
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
                    "Unexpected returned "
                    "human action."
                ),
            )


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
                "accepted"
            )

            print(
                "[PASS] Client payload contains "
                "no reviewer_id"
            )

            print(
                "[PASS] API attached trusted "
                "reviewer identity"
            )


            # ==================================================
            # 11. REVIEW DATABASE RECORD
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
                        "Stored action should "
                        "be CORRECT."
                    ),
                )


                assert_equal(
                    human_review.corrections,
                    CORRECTIONS,
                    (
                        "Stored corrections "
                        "are incorrect."
                    ),
                )


            print(
                "[PASS] Human review and "
                "corrections persisted"
            )

            print(
                "[PASS] PostgreSQL reviewer_id "
                "uses trusted identity"
            )


            # ==================================================
            # 12. FINAL CORRECTED RECORD
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


            assert_true(
                human_review_api
                is not None,
                (
                    "Detail API should expose "
                    "completed human review."
                ),
            )


            assert_equal(
                human_review_api[
                    "human_action"
                ],
                "CORRECT",
                (
                    "Detail API human action "
                    "should be CORRECT."
                ),
            )


            assert_equal(
                human_review_api[
                    "reviewer_id"
                ],
                REVIEWER_ID,
                (
                    "Detail API reviewer ID "
                    "is incorrect."
                ),
            )


            assert_equal(
                human_review_api[
                    "corrections"
                ],
                CORRECTIONS,
                (
                    "Detail API corrections "
                    "are incorrect."
                ),
            )


            assert_equal(
                final_record[
                    "final_status"
                ],
                "CORRECTED",
                (
                    "Final record should become "
                    "CORRECTED."
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


            print(
                "[PASS] Final status changed "
                "to CORRECTED"
            )

            print(
                "[PASS] CORRECTED record is "
                "final and downstream usable"
            )


            # ==================================================
            # 13. EFFECTIVE VALUES OVERLAY
            # ==================================================

            machine_values = (
                final_record[
                    "machine_values"
                ]
            )


            effective = (
                final_record[
                    "effective_values"
                ]
            )


            sources = (
                final_record[
                    "value_sources"
                ]
            )


            assert_equal(
                machine_values[
                    "expiry_date"
                ],
                "2026-01-01",
                (
                    "Original machine expiry "
                    "must remain unchanged."
                ),
            )


            assert_equal(
                machine_values[
                    "issuer"
                ],
                "TX DPS",
                (
                    "Original machine issuer "
                    "must remain unchanged."
                ),
            )


            assert_equal(
                effective[
                    "expiry_date"
                ],
                "2027-01-01",
                (
                    "Corrected expiry was not "
                    "applied to effective values."
                ),
            )


            assert_equal(
                effective[
                    "issuer"
                ],
                "TX DPS SECURITY",
                (
                    "Corrected issuer was not "
                    "applied to effective values."
                ),
            )


            assert_equal(
                effective[
                    "full_name"
                ],
                "PHASE 7C DASHBOARD USER",
                (
                    "Uncorrected machine field "
                    "should remain unchanged."
                ),
            )


            assert_equal(
                sources[
                    "expiry_date"
                ],
                "HUMAN_CORRECTION",
                (
                    "Corrected expiry should "
                    "show HUMAN_CORRECTION."
                ),
            )


            assert_equal(
                sources[
                    "issuer"
                ],
                "HUMAN_CORRECTION",
                (
                    "Corrected issuer should "
                    "show HUMAN_CORRECTION."
                ),
            )


            assert_equal(
                sources[
                    "full_name"
                ],
                "MACHINE",
                (
                    "Unchanged full name should "
                    "remain MACHINE sourced."
                ),
            )


            print(
                "[PASS] Effective values contain "
                "human correction overlay"
            )

            print(
                "[PASS] Per-field correction "
                "provenance exposed"
            )


            # ==================================================
            # 14. MACHINE EXTRACTION STILL IMMUTABLE
            # ==================================================

            analysis_after = (
                reviewed[
                    "analysis"
                ]
            )


            assert_equal(
                analysis_after[
                    "extraction"
                ][
                    "expiry_date"
                ][
                    "value"
                ],
                "2026-01-01",
                (
                    "Human correction must not "
                    "overwrite machine expiry."
                ),
            )


            assert_equal(
                analysis_after[
                    "extraction"
                ][
                    "issuer"
                ][
                    "value"
                ],
                "TX DPS",
                (
                    "Human correction must not "
                    "overwrite machine issuer."
                ),
            )


            print(
                "[PASS] Original machine "
                "extraction remains immutable"
            )


            # ==================================================
            # 15. REVIEW HISTORY API
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
                    "Review history endpoint "
                    "should return HTTP 200."
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


            event_types = [
                event.get(
                    "event_type"
                )

                for event
                in events
            ]


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
                    "Exactly one HUMAN_REVIEW "
                    "history event expected."
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
                    "Human review history "
                    "actor ID is incorrect."
                ),
            )


            human_details = (
                human_history.get(
                    "details"
                )
                or {}
            )


            assert_equal(
                human_details.get(
                    "human_action"
                ),
                "CORRECT",
                (
                    "Human audit details should "
                    "contain CORRECT action."
                ),
            )


            assert_equal(
                human_details.get(
                    "corrections"
                ),
                CORRECTIONS,
                (
                    "Human audit details should "
                    "contain submitted corrections."
                ),
            )


            print(
                "[PASS] Review history contains "
                "machine review event"
            )

            print(
                "[PASS] Review history contains "
                "human correction event"
            )

            print(
                "[PASS] Human history retains "
                "trusted reviewer and "
                "correction details"
            )


            # ==================================================
            # 16. DIRECT DATABASE AUDIT VERIFICATION
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
                        "review audit expected."
                    ),
                )


                assert_equal(
                    len(
                        human_audits
                    ),
                    1,
                    (
                        "Exactly one human "
                        "review audit expected."
                    ),
                )


                assert_equal(
                    human_audits[
                        0
                    ].actor_id,
                    REVIEWER_ID,
                    (
                        "HUMAN_REVIEW audit "
                        "actor_id should use "
                        "trusted reviewer identity."
                    ),
                )


            print(
                "[PASS] PostgreSQL contains "
                "one machine and one human audit"
            )

            print(
                "[PASS] Human audit actor_id "
                "uses trusted reviewer identity"
            )


            # ==================================================
            # 17. REVIEWED DOCUMENT REMOVED FROM QUEUE
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


            assert_true(
                document_id
                not in remaining_ids,
                (
                    "Reviewed document should "
                    "be removed from queue."
                ),
            )


            print(
                "[PASS] Reviewed document "
                "removed from pending queue"
            )


            # ==================================================
            # 18. DUPLICATE REVIEW REMAINS BLOCKED
            # ==================================================

            response = client.post(
                (
                    "/api/v1/documents/"
                    f"{document_id}"
                    "/reviews"
                ),

                headers=reviewer_headers(
                    "second-reviewer"
                ),

                json={
                    # ======================================
                    # reviewer_id intentionally absent.
                    # ======================================

                    "action":
                        "APPROVE",

                    "notes":
                        "Duplicate review attempt.",
                },
            )


            assert_equal(
                response.status_code,
                409,
                (
                    "Second review should be "
                    "rejected with HTTP 409."
                ),
            )


            print(
                "[PASS] Reviewed-state backend "
                "remains protected by HTTP 409"
            )


            # ==================================================
            # 19. FINAL RECORD STILL AUTHORITATIVE
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


            final_after_duplicate = (
                response.json()[
                    "final_record"
                ]
            )


            assert_equal(
                final_after_duplicate[
                    "final_status"
                ],
                "CORRECTED",
                (
                    "Duplicate review attempt "
                    "must not alter final status."
                ),
            )


            assert_equal(
                final_after_duplicate[
                    "effective_values"
                ][
                    "expiry_date"
                ],
                "2027-01-01",
                (
                    "Duplicate review attempt "
                    "must not alter corrected "
                    "effective values."
                ),
            )


            print(
                "[PASS] First completed review "
                "remains authoritative"
            )


            # ==================================================
            # FINAL SUCCESS
            # ==================================================

            print()
            print("=" * 76)
            print(
                "[PASS] PHASE 7C.4 FINAL "
                "STATUS DASHBOARD E2E TEST PASSED"
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
                "[CLEANUP] Phase 7C.4 "
                "temporary database and "
                "storage data removed."
            )


if __name__ == "__main__":

    main()