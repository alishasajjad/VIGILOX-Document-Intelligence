import tempfile

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import (
    TestClient,
)

from sqlalchemy import (
    func,
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
    DocumentAnalysisModel,
    DocumentModel,
    HumanReviewModel,
)

from backend.app.services.persistence_service import (
    PersistenceService,
)

from backend.app.services.query_service import (
    DocumentQueryService,
)

from backend.app.services.document_deletion_service import (
    DocumentDeletionService,
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

from backend.app.services.storage_integrity_service import (
    StorageIntegrityService,
)

from backend.app.services.storage_reconciliation_service import (
    StorageReconciliationService,
)


# ==========================================================
# TEST CONSTANTS
# ==========================================================

TEST_BYTES = (
    b"VIGILOX-PHASE-7C-6G-"
    b"FINAL-STORAGE-LIFECYCLE-E2E"
)


REVIEWER_ID = (
    "phase7c6g-reviewer"
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


def assert_false(
    condition: bool,
    message: str,
):

    if condition:

        raise AssertionError(
            message
        )


# ==========================================================
# REVIEWER HEADERS
# ==========================================================

def reviewer_headers() -> dict[str, str]:

    return {
        "X-VIGILOX-REVIEWER-ID":
            REVIEWER_ID,

        "X-VIGILOX-REVIEWER-ROLE":
            "REVIEWER",
    }


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
                        "PHASE 7C6G USER",

                    "source_line_ids": [
                        "L0"
                    ],
                },

                "licence_number": {
                    "value":
                        "P7C6G001",

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
                        "2025-01-01",

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
                        "VIGILOX TEST AUTHORITY",

                    "source_line_ids": [
                        "L3"
                    ],
                },
            },
        },

        "ocr_lines": [
            {
                "line_id":
                    "L0",

                "text":
                    "PHASE 7C6G USER",

                "confidence":
                    0.999,

                "bbox":
                    [10, 10, 200, 30],
            },

            {
                "line_id":
                    "L1",

                "text":
                    "P7C6G001",

                "confidence":
                    0.999,

                "bbox":
                    [10, 40, 150, 60],
            },

            {
                "line_id":
                    "L2",

                "text":
                    "01/01/2025",

                "confidence":
                    0.999,

                "bbox":
                    [10, 70, 150, 90],
            },

            {
                "line_id":
                    "L3",

                "text":
                    "VIGILOX TEST AUTHORITY",

                "confidence":
                    0.999,

                "bbox":
                    [10, 100, 250, 120],
            },
        ],

        "evidence_flags":
            [],

        "field_confidence": {
            "full_name":
                0.999,

            "licence_number":
                0.999,

            "id_number":
                None,

            "expiry_date":
                0.999,

            "date_of_birth":
                None,

            "issue_date":
                None,

            "issuer":
                0.999,
        },

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
# FAKE PIPELINE
# ==========================================================
#
# The final 7C.6 test is testing the complete storage
# lifecycle, not OCR model quality.
#
# Real OCR + Groq is already covered by the existing real
# provenance regression test.
#
# This fake pipeline lets us verify temporary upload cleanup
# and all downstream storage behavior deterministically.
# ==========================================================

class TrackingFakePipeline:

    def __init__(
        self,
    ):

        self.received_temp_path = None


    def process(
        self,
        image_path: str,
    ) -> dict:

        self.received_temp_path = (
            image_path
        )


        path = Path(
            image_path
        )


        assert_true(
            path.exists(),
            (
                "Temporary upload must exist "
                "while pipeline is processing."
            ),
        )


        assert_equal(
            path.read_bytes(),
            TEST_BYTES,
            (
                "Pipeline temporary upload "
                "bytes do not match request."
            ),
        )


        return (
            build_pipeline_result()
        )


# ==========================================================
# DATABASE COUNTS
# ==========================================================

def count_documents(
    document_id: str,
) -> int:

    with SessionLocal() as session:

        statement = (
            select(
                func.count(
                    DocumentModel.id
                )
            )
            .where(
                DocumentModel.id
                == document_id
            )
        )


        return (
            session.scalar(
                statement
            )
            or 0
        )


def count_analyses(
    document_id: str,
) -> int:

    with SessionLocal() as session:

        statement = (
            select(
                func.count(
                    DocumentAnalysisModel.id
                )
            )
            .where(
                DocumentAnalysisModel.document_id
                == document_id
            )
        )


        return (
            session.scalar(
                statement
            )
            or 0
        )


def count_reviews(
    document_id: str,
) -> int:

    with SessionLocal() as session:

        statement = (
            select(
                func.count(
                    HumanReviewModel.id
                )
            )
            .where(
                HumanReviewModel.document_id
                == document_id
            )
        )


        return (
            session.scalar(
                statement
            )
            or 0
        )


def count_audits(
    document_id: str,
) -> int:

    with SessionLocal() as session:

        statement = (
            select(
                func.count(
                    AuditEventModel.id
                )
            )
            .where(
                AuditEventModel.document_id
                == document_id
            )
        )


        return (
            session.scalar(
                statement
            )
            or 0
        )


# ==========================================================
# FIND DOCUMENT IN RESULT CATEGORY
# ==========================================================

def contains_document(
    items: list[dict],
    document_id: str,
) -> bool:

    return any(
        item.get(
            "document_id"
        )
        == document_id

        for item
        in items
    )


# ==========================================================
# FIND DOCUMENT IN REVIEW QUEUE
# ==========================================================

def queue_contains_document(
    response_body: dict,
    document_id: str,
) -> bool:

    return any(
        item[
            "document_id"
        ]
        == document_id

        for item
        in response_body[
            "documents"
        ]
    )


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("=" * 76)
    print(
        "PHASE 7C.6g — FINAL STORAGE "
        "LIFECYCLE END-TO-END TEST"
    )
    print("=" * 76)


    client = None

    managed_ids: set[str] = (
        set()
    )


    orphan_id = None


    with tempfile.TemporaryDirectory() as temp_dir:

        temp_root = Path(
            temp_dir
        )


        storage_root = (
            temp_root
            / "documents"
        )


        storage_service = (
            DocumentStorageService(
                storage_root=(
                    storage_root
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


        integrity_service = (
            StorageIntegrityService(
                storage_service=(
                    storage_service
                )
            )
        )


        reconciliation_service = (
            StorageReconciliationService(
                storage_service=(
                    storage_service
                ),

                integrity_service=(
                    integrity_service
                ),
            )
        )


        deletion_service = (
            DocumentDeletionService(
                storage_service=(
                    storage_service
                )
            )
        )


        pipeline = (
            TrackingFakePipeline()
        )


        source_path = (
            temp_root
            / "source.jpg"
        )


        source_path.write_bytes(
            TEST_BYTES
        )


        try:

            # ==================================================
            # APPLICATION SERVICES
            # ==================================================

            app.state.pipeline = (
                pipeline
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
                    mode="trusted_headers"
                )
            )


            client = TestClient(
                app
            )


            print(
                "[OK] Final lifecycle "
                "services initialized"
            )


            # ==================================================
            # TEST 1 — UPLOAD THROUGH API
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 1 — API UPLOAD + "
                "PERMANENT STORAGE"
            )
            print("-" * 76)


            response = (
                client.post(
                    "/api/v1/documents/analyze",

                    files={
                        "file": (
                            "phase7c6g.jpg",
                            TEST_BYTES,
                            "image/jpeg",
                        )
                    },
                )
            )


            assert_equal(
                response.status_code,
                200,
                (
                    "Analyze endpoint should "
                    "return HTTP 200."
                ),
            )


            response_body = (
                response.json()
            )


            document_id = (
                response_body[
                    "document_id"
                ]
            )


            managed_ids.add(
                document_id
            )


            assert_equal(
                response_body[
                    "original_document_stored"
                ],
                True,
                (
                    "Analyze API should report "
                    "permanent source storage."
                ),
            )


            assert_true(
                pipeline.received_temp_path
                is not None,
                (
                    "Pipeline did not receive "
                    "temporary upload path."
                ),
            )


            assert_false(
                Path(
                    pipeline.received_temp_path
                ).exists(),
                (
                    "Temporary API upload "
                    "was not cleaned."
                ),
            )


            print(
                "[PASS] API document "
                "analysis persisted"
            )

            print(
                "[PASS] Temporary upload "
                "cleaned after request"
            )


            # ==================================================
            # TEST 2 — PERMANENT SOURCE + DB
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 2 — PERMANENT SOURCE "
                "+ DATABASE STATE"
            )
            print("-" * 76)


            document_directory = (
                storage_service
                .get_document_directory(
                    document_id
                )
            )


            original_path = (
                storage_service
                .load_original(
                    document_id=(
                        document_id
                    ),

                    content_type=(
                        "image/jpeg"
                    ),
                )
            )


            assert_true(
                original_path is not None,
                (
                    "Permanent original source "
                    "was not found."
                ),
            )


            assert_true(
                original_path.exists(),
                (
                    "Permanent original path "
                    "does not exist."
                ),
            )


            assert_equal(
                original_path.read_bytes(),
                TEST_BYTES,
                (
                    "Permanent original bytes "
                    "were modified."
                ),
            )


            temporary_files = list(
                document_directory.glob(
                    ".upload_*.tmp"
                )
            )


            assert_equal(
                temporary_files,
                [],
                (
                    "Permanent document "
                    "directory contains "
                    "temporary upload files."
                ),
            )


            assert_equal(
                count_documents(
                    document_id
                ),
                1,
                (
                    "Expected one PostgreSQL "
                    "document row."
                ),
            )


            assert_equal(
                count_analyses(
                    document_id
                ),
                1,
                (
                    "Expected one PostgreSQL "
                    "analysis row."
                ),
            )


            assert_equal(
                count_reviews(
                    document_id
                ),
                0,
                (
                    "Document should not yet "
                    "have a human review."
                ),
            )


            assert_equal(
                count_audits(
                    document_id
                ),
                1,
                (
                    "Expected machine audit "
                    "before human review."
                ),
            )


            print(
                "[PASS] Permanent original "
                "bytes preserved"
            )

            print(
                "[PASS] No permanent temp "
                "artifacts remain"
            )

            print(
                "[PASS] PostgreSQL document, "
                "analysis and machine audit verified"
            )


            # ==================================================
            # TEST 3 — ORIGINAL IMAGE API
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 3 — SOURCE IMAGE "
                "RETRIEVAL"
            )
            print("-" * 76)


            image_response = (
                client.get(
                    (
                        f"/api/v1/documents/"
                        f"{document_id}/image"
                    )
                )
            )


            assert_equal(
                image_response.status_code,
                200,
                (
                    "Stored source image "
                    "should return HTTP 200."
                ),
            )


            assert_equal(
                image_response.content,
                TEST_BYTES,
                (
                    "Image endpoint returned "
                    "different bytes."
                ),
            )


            assert_equal(
                image_response.headers[
                    "content-type"
                ],
                "image/jpeg",
                (
                    "Image endpoint returned "
                    "incorrect Content-Type."
                ),
            )


            print(
                "[PASS] Original image "
                "retrievable through API"
            )

            print(
                "[PASS] API image bytes "
                "preserved exactly"
            )


            # ==================================================
            # TEST 4 — HEALTHY INTEGRITY STATE
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 4 — HEALTHY "
                "INTEGRITY STATE"
            )
            print("-" * 76)


            integrity_report = (
                integrity_service.scan()
            )


            assert_true(
                contains_document(
                    integrity_report[
                        "healthy_documents"
                    ],
                    document_id,
                ),
                (
                    "Stored document should be "
                    "classified as HEALTHY."
                ),
            )


            assert_false(
                contains_document(
                    integrity_report[
                        "missing_storage"
                    ],
                    document_id,
                ),
                (
                    "Healthy document was "
                    "incorrectly classified "
                    "as missing storage."
                ),
            )


            print(
                "[PASS] DB + permanent "
                "storage classified HEALTHY"
            )


            # ==================================================
            # TEST 5 — HUMAN REVIEW
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 5 — HUMAN REVIEW "
                "PRESERVES SOURCE"
            )
            print("-" * 76)


            queue_response = (
                client.get(
                    "/api/v1/reviews/queue"
                )
            )


            assert_equal(
                queue_response.status_code,
                200,
                (
                    "Review queue should "
                    "return HTTP 200."
                ),
            )


            assert_true(
                queue_contains_document(
                    queue_response.json(),
                    document_id,
                ),
                (
                    "REVIEW_REQUIRED document "
                    "should appear in queue."
                ),
            )


            review_payload = {
                "action":
                    "APPROVE",

                "notes":
                    (
                        "Phase 7C.6g final "
                        "storage lifecycle review."
                    ),

                "corrections":
                    None,
            }


            assert_false(
                "reviewer_id"
                in review_payload,
                (
                    "Client review payload "
                    "must not contain "
                    "reviewer_id."
                ),
            )


            review_response = (
                client.post(
                    (
                        f"/api/v1/documents/"
                        f"{document_id}/reviews"
                    ),

                    headers=(
                        reviewer_headers()
                    ),

                    json=(
                        review_payload
                    ),
                )
            )


            assert_equal(
                review_response.status_code,
                200,
                (
                    "Human APPROVE should "
                    "return HTTP 200."
                ),
            )


            review_body = (
                review_response.json()
            )


            assert_equal(
                review_body[
                    "authenticated_reviewer"
                ][
                    "reviewer_id"
                ],
                REVIEWER_ID,
                (
                    "Review API did not use "
                    "trusted reviewer identity."
                ),
            )


            assert_equal(
                count_reviews(
                    document_id
                ),
                1,
                (
                    "Expected one human review."
                ),
            )


            assert_equal(
                count_audits(
                    document_id
                ),
                2,
                (
                    "Expected machine + human "
                    "audit events."
                ),
            )


            assert_true(
                storage_service
                .original_exists(
                    document_id=(
                        document_id
                    ),

                    content_type=(
                        "image/jpeg"
                    ),
                ),
                (
                    "Human review must not "
                    "remove original source."
                ),
            )


            image_after_review = (
                client.get(
                    (
                        f"/api/v1/documents/"
                        f"{document_id}/image"
                    )
                )
            )


            assert_equal(
                image_after_review.status_code,
                200,
                (
                    "Original source should "
                    "remain available after "
                    "human review."
                ),
            )


            assert_equal(
                image_after_review.content,
                TEST_BYTES,
                (
                    "Human review modified "
                    "original source bytes."
                ),
            )


            integrity_after_review = (
                integrity_service.scan()
            )


            assert_true(
                contains_document(
                    integrity_after_review[
                        "healthy_documents"
                    ],
                    document_id,
                ),
                (
                    "Reviewed document should "
                    "remain storage healthy."
                ),
            )


            print(
                "[PASS] Trusted human "
                "review persisted"
            )

            print(
                "[PASS] Review did not modify "
                "original source"
            )

            print(
                "[PASS] Reviewed document "
                "remains HEALTHY"
            )


            # ==================================================
            # TEST 6 — SAFE BUSINESS DELETE
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 6 — SAFE BUSINESS "
                "DOCUMENT DELETE"
            )
            print("-" * 76)


            deletion_result = (
                deletion_service
                .delete_document(
                    document_id
                )
            )


            assert_equal(
                deletion_result[
                    "status"
                ],
                "DELETED",
                (
                    "Business deletion did "
                    "not complete."
                ),
            )


            assert_equal(
                deletion_result[
                    "database_deleted"
                ],
                True,
                (
                    "Database document should "
                    "be deleted."
                ),
            )


            assert_equal(
                deletion_result[
                    "storage_status"
                ],
                "DELETED",
                (
                    "Permanent source storage "
                    "should be deleted."
                ),
            )


            assert_equal(
                count_documents(
                    document_id
                ),
                0,
                (
                    "Document DB row remains "
                    "after delete."
                ),
            )


            assert_equal(
                count_analyses(
                    document_id
                ),
                0,
                (
                    "Analysis did not cascade "
                    "delete."
                ),
            )


            assert_equal(
                count_reviews(
                    document_id
                ),
                0,
                (
                    "Human review did not "
                    "cascade delete."
                ),
            )


            assert_equal(
                count_audits(
                    document_id
                ),
                0,
                (
                    "Audit rows did not "
                    "cascade delete."
                ),
            )


            assert_false(
                document_directory.exists(),
                (
                    "Permanent source directory "
                    "remains after delete."
                ),
            )


            managed_ids.discard(
                document_id
            )


            print(
                "[PASS] PostgreSQL document "
                "deleted"
            )

            print(
                "[PASS] Analysis / review / "
                "audit rows cascade deleted"
            )

            print(
                "[PASS] Permanent source "
                "storage deleted"
            )


            # ==================================================
            # TEST 7 — DELETED DOCUMENT API STATE
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 7 — POST-DELETE "
                "APPLICATION STATE"
            )
            print("-" * 76)


            document_response = (
                client.get(
                    (
                        f"/api/v1/documents/"
                        f"{document_id}"
                    )
                )
            )


            assert_equal(
                document_response.status_code,
                404,
                (
                    "Deleted document should "
                    "return HTTP 404."
                ),
            )


            image_response = (
                client.get(
                    (
                        f"/api/v1/documents/"
                        f"{document_id}/image"
                    )
                )
            )


            assert_equal(
                image_response.status_code,
                404,
                (
                    "Deleted source image "
                    "should return HTTP 404."
                ),
            )


            post_delete_report = (
                integrity_service.scan()
            )


            assert_false(
                contains_document(
                    post_delete_report[
                        "healthy_documents"
                    ],
                    document_id,
                ),
                (
                    "Deleted document still "
                    "appears healthy."
                ),
            )


            assert_false(
                contains_document(
                    post_delete_report[
                        "missing_storage"
                    ],
                    document_id,
                ),
                (
                    "Deleted document should "
                    "not become missing-storage."
                ),
            )


            assert_false(
                contains_document(
                    post_delete_report[
                        "orphan_storage"
                    ],
                    document_id,
                ),
                (
                    "Deleted document should "
                    "not leave an orphan."
                ),
            )


            print(
                "[PASS] Deleted document "
                "returns HTTP 404"
            )

            print(
                "[PASS] Deleted document "
                "left no integrity artifact"
            )


            # ==================================================
            # TEST 8 — ORPHAN DETECTION
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 8 — ORPHAN DETECTION "
                "+ DRY RUN"
            )
            print("-" * 76)


            orphan_id = str(
                uuid4()
            )


            orphan_path = (
                storage_service
                .save_original(
                    document_id=(
                        orphan_id
                    ),

                    source_path=(
                        source_path
                    ),

                    content_type=(
                        "image/jpeg"
                    ),
                )
            )


            assert_true(
                orphan_path.exists(),
                (
                    "Orphan setup failed."
                ),
            )


            orphan_report = (
                integrity_service.scan()
            )


            assert_true(
                contains_document(
                    orphan_report[
                        "orphan_storage"
                    ],
                    orphan_id,
                ),
                (
                    "Filesystem orphan was "
                    "not detected."
                ),
            )


            dry_run = (
                reconciliation_service
                .reconcile_orphans(
                    dry_run=True
                )
            )


            orphan_dry_results = [
                item
                for item
                in dry_run[
                    "results"
                ]
                if (
                    item.get(
                        "document_id"
                    )
                    == orphan_id
                )
            ]


            assert_equal(
                len(
                    orphan_dry_results
                ),
                1,
                (
                    "Dry run should contain "
                    "the orphan exactly once."
                ),
            )


            assert_equal(
                orphan_dry_results[
                    0
                ][
                    "status"
                ],
                "WOULD_DELETE",
                (
                    "Dry run should report "
                    "WOULD_DELETE."
                ),
            )


            assert_true(
                orphan_path.exists(),
                (
                    "Dry run must not delete "
                    "orphan storage."
                ),
            )


            print(
                "[PASS] Orphan storage "
                "detected"
            )

            print(
                "[PASS] Dry run proposed "
                "cleanup without deleting"
            )


            # ==================================================
            # TEST 9 — SAFE ORPHAN RECONCILIATION
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 9 — SAFE ORPHAN "
                "RECONCILIATION"
            )
            print("-" * 76)


            execute_result = (
                reconciliation_service
                .reconcile_orphans(
                    dry_run=False
                )
            )


            orphan_execute_results = [
                item
                for item
                in execute_result[
                    "results"
                ]
                if (
                    item.get(
                        "document_id"
                    )
                    == orphan_id
                )
            ]


            assert_equal(
                len(
                    orphan_execute_results
                ),
                1,
                (
                    "Execute result should "
                    "contain orphan once."
                ),
            )


            assert_equal(
                orphan_execute_results[
                    0
                ][
                    "status"
                ],
                "DELETED",
                (
                    "Orphan should be safely "
                    "deleted."
                ),
            )


            assert_false(
                storage_service
                .get_document_directory(
                    orphan_id
                )
                .exists(),
                (
                    "Orphan directory remains "
                    "after reconciliation."
                ),
            )


            final_orphan_report = (
                integrity_service.scan()
            )


            assert_false(
                contains_document(
                    final_orphan_report[
                        "orphan_storage"
                    ],
                    orphan_id,
                ),
                (
                    "Reconciled orphan still "
                    "appears in scan."
                ),
            )


            print(
                "[PASS] Orphan safely "
                "reconciled"
            )

            print(
                "[PASS] Final scan confirms "
                "orphan removed"
            )


            orphan_id = None


            # ==================================================
            # TEST 10 — MISSING STORAGE PROTECTION
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 10 — MISSING STORAGE "
                "DETECTION + PROTECTION"
            )
            print("-" * 76)


            missing_stored = (
                persistence_service
                .save_processed_document(
                    original_filename=(
                        "phase7c6g_missing.jpg"
                    ),

                    content_type=(
                        "image/jpeg"
                    ),

                    pipeline_result=(
                        build_pipeline_result()
                    ),

                    source_path=None,
                )
            )


            missing_document_id = (
                missing_stored[
                    "document_id"
                ]
            )


            managed_ids.add(
                missing_document_id
            )


            missing_report = (
                integrity_service.scan()
            )


            assert_true(
                contains_document(
                    missing_report[
                        "missing_storage"
                    ],
                    missing_document_id,
                ),
                (
                    "DB document without "
                    "source was not detected."
                ),
            )


            reconciliation_result = (
                reconciliation_service
                .reconcile_orphans(
                    dry_run=False
                )
            )


            assert_true(
                reconciliation_result[
                    "protected"
                ][
                    "missing_storage"
                ]
                >= 1,
                (
                    "Reconciliation should "
                    "report protected missing "
                    "storage records."
                ),
            )


            assert_equal(
                count_documents(
                    missing_document_id
                ),
                1,
                (
                    "Reconciliation must not "
                    "delete missing-storage "
                    "DB document."
                ),
            )


            print(
                "[PASS] Missing storage "
                "detected"
            )

            print(
                "[PASS] Reconciliation "
                "protected DB record"
            )


            # ==================================================
            # TEST 11 — CONTROLLED DELETE OF MISSING STORAGE
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 11 — CONTROLLED DELETE "
                "OF MISSING-STORAGE RECORD"
            )
            print("-" * 76)


            missing_delete_result = (
                deletion_service
                .delete_document(
                    missing_document_id
                )
            )


            assert_equal(
                missing_delete_result[
                    "status"
                ],
                "DELETED",
                (
                    "Missing-storage DB "
                    "document should still "
                    "delete cleanly."
                ),
            )


            assert_equal(
                missing_delete_result[
                    "storage_status"
                ],
                "MISSING",
                (
                    "Missing physical storage "
                    "should be explicitly "
                    "reported."
                ),
            )


            assert_equal(
                count_documents(
                    missing_document_id
                ),
                0,
                (
                    "Missing-storage DB "
                    "document still exists."
                ),
            )


            assert_equal(
                count_analyses(
                    missing_document_id
                ),
                0,
                (
                    "Missing-storage analysis "
                    "did not cascade delete."
                ),
            )


            assert_equal(
                count_audits(
                    missing_document_id
                ),
                0,
                (
                    "Missing-storage audit "
                    "did not cascade delete."
                ),
            )


            managed_ids.discard(
                missing_document_id
            )


            print(
                "[PASS] Missing-storage DB "
                "record deleted explicitly"
            )

            print(
                "[PASS] Missing physical "
                "source reported safely"
            )


            # ==================================================
            # TEST 12 — FINAL STORAGE ROOT STATE
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 12 — FINAL MANAGED "
                "STORAGE STATE"
            )
            print("-" * 76)


            root_entries = list(
                storage_root.iterdir()
            )


            assert_equal(
                root_entries,
                [],
                (
                    "Final test storage root "
                    "should contain no managed "
                    "artifacts."
                ),
            )


            print(
                "[PASS] No test storage "
                "artifacts remain"
            )


            # ==================================================
            # FINAL SUCCESS
            # ==================================================

            print()
            print("=" * 76)
            print(
                "[PASS] PHASE 7C.6g FINAL "
                "STORAGE LIFECYCLE E2E TEST PASSED"
            )
            print("=" * 76)


        finally:

            # ==================================================
            # CLOSE CLIENT
            # ==================================================

            if client is not None:

                client.close()


            # ==================================================
            # DATABASE SAFETY CLEANUP
            # ==================================================

            if managed_ids:

                with SessionLocal.begin() as session:

                    for cleanup_id in (
                        managed_ids
                    ):

                        document = (
                            session.get(
                                DocumentModel,
                                cleanup_id,
                            )
                        )


                        if document is not None:

                            session.delete(
                                document
                            )


            # ==================================================
            # STORAGE SAFETY CLEANUP
            # ==================================================

            for cleanup_id in (
                managed_ids
            ):

                try:

                    storage_service.delete_document(
                        cleanup_id
                    )

                except Exception:

                    pass


            if orphan_id is not None:

                try:

                    storage_service.delete_document(
                        orphan_id
                    )

                except Exception:

                    pass


            # ==================================================
            # CLEAN APPLICATION STATE
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
                "[CLEANUP] Phase 7C.6g "
                "temporary database, API "
                "and storage state removed."
            )


if __name__ == "__main__":

    main()