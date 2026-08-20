import tempfile

from datetime import (
    datetime,
    timezone,
)

from pathlib import Path

from uuid import (
    uuid4,
)

from sqlalchemy import (
    func,
    select,
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

from database.repositories import (
    DocumentRepository,
)

from backend.app.services.document_deletion_service import (
    DocumentDeletionService,
    DocumentStorageCleanupError,
)

from backend.app.services.document_storage_service import (
    DocumentStorageSecurityError,
    DocumentStorageService,
)


# ==========================================================
# TEST STORAGE SERVICE
# ==========================================================

class FailingDeleteStorageService(
    DocumentStorageService
):

    def __init__(
        self,
        *,
        storage_root: str | Path,
    ):

        super().__init__(
            storage_root=(
                storage_root
            )
        )


        self.fail_document_id = None


    def delete_document(
        self,
        document_id: str,
    ) -> bool:

        if (
            document_id
            == self.fail_document_id
        ):

            raise OSError(
                "Forced filesystem "
                "cleanup failure."
            )


        return (
            super()
            .delete_document(
                document_id
            )
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
            (
                "The document has passed "
                "its validated expiry date."
            ),
    }


    return {
        "extraction": {
            "document_type":
                "guard_license",

            "full_name": {
                "value":
                    "PHASE 7C6 DELETE USER",

                "source_line_ids": [
                    "L0"
                ],
            },

            "licence_number": {
                "value":
                    "P7C600001",

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

            "issue_date": {
                "value":
                    "2025-01-01",

                "source_line_ids": [
                    "L2"
                ],
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

            "issuer": {
                "value":
                    "TX DPS",

                "source_line_ids": [
                    "L5"
                ],
            },
        },

        "ocr_lines": [
            {
                "line_id":
                    "L0",

                "text":
                    "PHASE 7C6 DELETE USER",

                "confidence":
                    0.999,

                "bbox":
                    [10, 10, 200, 30],
            },

            {
                "line_id":
                    "L1",

                "text":
                    "P7C600001",

                "confidence":
                    0.999,

                "bbox":
                    [10, 40, 160, 60],
            },

            {
                "line_id":
                    "L2",

                "text":
                    "01/01/2025",

                "confidence":
                    0.999,

                "bbox":
                    [10, 70, 160, 90],
            },

            {
                "line_id":
                    "L3",

                "text":
                    "01/01/2026",

                "confidence":
                    0.999,

                "bbox":
                    [10, 100, 160, 120],
            },

            {
                "line_id":
                    "L4",

                "text":
                    "01/01/1990",

                "confidence":
                    0.999,

                "bbox":
                    [10, 130, 160, 150],
            },

            {
                "line_id":
                    "L5",

                "text":
                    "ISSUED BY TX DPS",

                "confidence":
                    0.999,

                "bbox":
                    [10, 160, 200, 180],
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

            "issue_date":
                0.999,

            "expiry_date":
                0.999,

            "date_of_birth":
                0.999,

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


def assert_raises(
    expected_exception,
    callback,
    message: str,
):

    try:

        callback()

    except expected_exception as exc:

        return exc


    except Exception as exc:

        raise AssertionError(
            f"{message}\n"
            "Unexpected exception: "
            f"{type(exc).__name__}: {exc}"
        ) from exc


    raise AssertionError(
        message
    )


# ==========================================================
# DATABASE COUNT HELPERS
# ==========================================================

def count_document(
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


def count_analysis(
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
# CREATE PROCESSED DOCUMENT
# ==========================================================

def create_document(
    *,
    persistence_service: PersistenceService,
    source_path: Path,
    with_storage: bool = True,
) -> str:

    stored = (
        persistence_service
        .save_processed_document(
            original_filename=(
                source_path.name
            ),

            content_type=(
                "image/jpeg"
            ),

            pipeline_result=(
                build_pipeline_result()
            ),

            source_path=(
                source_path
                if with_storage
                else None
            ),
        )
    )


    return stored[
        "document_id"
    ]


# ==========================================================
# ADD HUMAN REVIEW
# ==========================================================

def add_human_review(
    *,
    persistence_service: PersistenceService,
    document_id: str,
):

    persistence_service.save_human_review(
        review_result={
            "review_id":
                str(
                    uuid4()
                ),

            "document_id":
                document_id,

            "reviewer_id":
                "phase7c6-reviewer",

            "machine_decision":
                "REVIEW_REQUIRED",

            "machine_priority":
                "MEDIUM",

            "machine_reason_codes": [
                "DOCUMENT_EXPIRED"
            ],

            "human_action":
                "APPROVE",

            "corrections":
                {},

            "notes":
                (
                    "Phase 7C.6 cascade "
                    "deletion test."
                ),

            "reviewed_at":
                (
                    datetime.now(
                        timezone.utc
                    )
                    .isoformat()
                ),
        }
    )


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("=" * 76)
    print(
        "PHASE 7C.6b — SAFE DOCUMENT "
        "DELETE SERVICE TEST"
    )
    print("=" * 76)


    cleanup_document_ids: set[str] = (
        set()
    )


    original_repository_delete = (
        DocumentRepository
        .delete_document
    )


    with tempfile.TemporaryDirectory() as temp_dir:

        temp_root = Path(
            temp_dir
        )


        storage_root = (
            temp_root
            / "documents"
        )


        source_path = (
            temp_root
            / "source.jpg"
        )


        source_path.write_bytes(
            (
                b"VIGILOX-PHASE-7C-6B-"
                b"SAFE-DOCUMENT-DELETE"
            )
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


        deletion_service = (
            DocumentDeletionService(
                storage_service=(
                    storage_service
                )
            )
        )


        try:

            # ==================================================
            # TEST 1 — COMPLETE DB + STORAGE DELETE
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 1 — COMPLETE DOCUMENT DELETE"
            )
            print("-" * 76)


            document_id = (
                create_document(
                    persistence_service=(
                        persistence_service
                    ),

                    source_path=(
                        source_path
                    ),
                )
            )


            cleanup_document_ids.add(
                document_id
            )


            add_human_review(
                persistence_service=(
                    persistence_service
                ),

                document_id=(
                    document_id
                ),
            )


            document_directory = (
                storage_service
                .get_document_directory(
                    document_id
                )
            )


            assert_true(
                document_directory.exists(),
                (
                    "Document storage should "
                    "exist before delete."
                ),
            )


            assert_equal(
                count_document(
                    document_id
                ),
                1,
                (
                    "Expected one document "
                    "before deletion."
                ),
            )


            assert_equal(
                count_analysis(
                    document_id
                ),
                1,
                (
                    "Expected one analysis "
                    "before deletion."
                ),
            )


            assert_equal(
                count_reviews(
                    document_id
                ),
                1,
                (
                    "Expected one review "
                    "before deletion."
                ),
            )


            assert_equal(
                count_audits(
                    document_id
                ),
                2,
                (
                    "Expected machine + human "
                    "audit before deletion."
                ),
            )


            result = (
                deletion_service
                .delete_document(
                    document_id
                )
            )


            assert_equal(
                result[
                    "status"
                ],
                "DELETED",
                (
                    "Unexpected deletion "
                    "status."
                ),
            )


            assert_equal(
                result[
                    "database_deleted"
                ],
                True,
                (
                    "Database deletion "
                    "should be True."
                ),
            )


            assert_equal(
                result[
                    "storage_deleted"
                ],
                True,
                (
                    "Storage deletion "
                    "should be True."
                ),
            )


            assert_equal(
                result[
                    "storage_status"
                ],
                "DELETED",
                (
                    "Unexpected storage "
                    "deletion status."
                ),
            )


            assert_equal(
                count_document(
                    document_id
                ),
                0,
                (
                    "Document row was "
                    "not deleted."
                ),
            )


            assert_equal(
                count_analysis(
                    document_id
                ),
                0,
                (
                    "Analysis row did not "
                    "cascade delete."
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
                    "Audit events did not "
                    "cascade delete."
                ),
            )


            assert_false(
                document_directory.exists(),
                (
                    "Document storage still "
                    "exists after delete."
                ),
            )


            cleanup_document_ids.discard(
                document_id
            )


            print(
                "[PASS] Document database "
                "record deleted"
            )

            print(
                "[PASS] Analysis / review / "
                "audit rows cascade deleted"
            )

            print(
                "[PASS] Managed source storage "
                "deleted"
            )


            # ==================================================
            # TEST 2 — DB EXISTS, STORAGE MISSING
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 2 — MISSING STORAGE"
            )
            print("-" * 76)


            missing_storage_id = (
                create_document(
                    persistence_service=(
                        persistence_service
                    ),

                    source_path=(
                        source_path
                    ),

                    with_storage=False,
                )
            )


            cleanup_document_ids.add(
                missing_storage_id
            )


            result = (
                deletion_service
                .delete_document(
                    missing_storage_id
                )
            )


            assert_equal(
                result[
                    "status"
                ],
                "DELETED",
                (
                    "Database document should "
                    "still delete when source "
                    "storage is missing."
                ),
            )


            assert_equal(
                result[
                    "storage_deleted"
                ],
                False,
                (
                    "Missing storage should "
                    "not report deleted."
                ),
            )


            assert_equal(
                result[
                    "storage_status"
                ],
                "MISSING",
                (
                    "Missing storage should "
                    "be explicitly reported."
                ),
            )


            assert_equal(
                count_document(
                    missing_storage_id
                ),
                0,
                (
                    "Database record should "
                    "be deleted even when "
                    "storage is missing."
                ),
            )


            cleanup_document_ids.discard(
                missing_storage_id
            )


            print(
                "[PASS] Missing source storage "
                "handled explicitly"
            )

            print(
                "[PASS] Database lifecycle "
                "remains authoritative"
            )


            # ==================================================
            # TEST 3 — DB MISSING, ORPHAN STORAGE EXISTS
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 3 — ORPHAN STORAGE NOT "
                "DELETED BY BUSINESS DELETE"
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
                    "Orphan test source "
                    "was not created."
                ),
            )


            result = (
                deletion_service
                .delete_document(
                    orphan_id
                )
            )


            assert_equal(
                result[
                    "status"
                ],
                "NOT_FOUND",
                (
                    "DB-missing document "
                    "should return NOT_FOUND."
                ),
            )


            assert_equal(
                result[
                    "storage_status"
                ],
                "NOT_CHECKED",
                (
                    "Business deletion must "
                    "not silently delete orphan "
                    "filesystem data."
                ),
            )


            assert_true(
                orphan_path.exists(),
                (
                    "Orphan storage should be "
                    "left for reconciliation."
                ),
            )


            print(
                "[PASS] DB-missing request "
                "returns NOT_FOUND"
            )

            print(
                "[PASS] Orphan storage left "
                "for reconciliation phase"
            )


            # Manual test cleanup.

            storage_service.delete_document(
                orphan_id
            )


            # ==================================================
            # TEST 4 — UNSAFE DOCUMENT ID
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 4 — UNSAFE DELETE ID"
            )
            print("-" * 76)


            outside_directory = (
                temp_root
                / "outside"
            )


            outside_directory.mkdir(
                parents=True,
                exist_ok=True,
            )


            sentinel = (
                outside_directory
                / "DO_NOT_DELETE.txt"
            )


            sentinel.write_text(
                "safe",
                encoding="utf-8",
            )


            assert_raises(
                DocumentStorageSecurityError,

                lambda:
                    deletion_service
                    .delete_document(
                        "../outside"
                    ),

                (
                    "Unsafe delete ID "
                    "should be rejected."
                ),
            )


            assert_true(
                sentinel.exists(),
                (
                    "Unsafe deletion modified "
                    "outside storage."
                ),
            )


            print(
                "[PASS] Unsafe document ID "
                "blocked before deletion"
            )

            print(
                "[PASS] Outside sentinel "
                "preserved"
            )


            # ==================================================
            # TEST 5 — FILESYSTEM CLEANUP FAILURE
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 5 — FILESYSTEM CLEANUP FAILURE"
            )
            print("-" * 76)


            failing_storage = (
                FailingDeleteStorageService(
                    storage_root=(
                        storage_root
                    )
                )
            )


            failing_persistence = (
                PersistenceService(
                    storage_service=(
                        failing_storage
                    )
                )
            )


            failing_deletion = (
                DocumentDeletionService(
                    storage_service=(
                        failing_storage
                    )
                )
            )


            failure_document_id = (
                create_document(
                    persistence_service=(
                        failing_persistence
                    ),

                    source_path=(
                        source_path
                    ),
                )
            )


            cleanup_document_ids.add(
                failure_document_id
            )


            failure_directory = (
                failing_storage
                .get_document_directory(
                    failure_document_id
                )
            )


            failing_storage.fail_document_id = (
                failure_document_id
            )


            cleanup_error = (
                assert_raises(
                    DocumentStorageCleanupError,

                    lambda:
                        failing_deletion
                        .delete_document(
                            failure_document_id
                        ),

                    (
                        "Filesystem cleanup "
                        "failure should be "
                        "surfaced."
                    ),
                )
            )


            assert_equal(
                cleanup_error.database_deleted,
                True,
                (
                    "Cleanup error should "
                    "report committed DB delete."
                ),
            )


            assert_equal(
                count_document(
                    failure_document_id
                ),
                0,
                (
                    "Database deletion should "
                    "already be committed."
                ),
            )


            assert_true(
                failure_directory.exists(),
                (
                    "Forced filesystem failure "
                    "should leave recoverable "
                    "orphan storage."
                ),
            )


            cleanup_document_ids.discard(
                failure_document_id
            )


            print(
                "[PASS] Filesystem failure "
                "was not silently ignored"
            )

            print(
                "[PASS] DB deletion remained "
                "committed"
            )

            print(
                "[PASS] Recoverable orphan "
                "storage remained"
            )


            # Manual storage cleanup after test.

            failing_storage.fail_document_id = (
                None
            )


            failing_storage.delete_document(
                failure_document_id
            )


            # ==================================================
            # TEST 6 — DATABASE DELETE FAILURE
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 6 — DATABASE FAILURE "
                "PRESERVES STORAGE"
            )
            print("-" * 76)


            db_failure_document_id = (
                create_document(
                    persistence_service=(
                        persistence_service
                    ),

                    source_path=(
                        source_path
                    ),
                )
            )


            cleanup_document_ids.add(
                db_failure_document_id
            )


            db_failure_directory = (
                storage_service
                .get_document_directory(
                    db_failure_document_id
                )
            )


            def forced_database_failure(
                self,
                document,
            ):

                raise RuntimeError(
                    "Forced PostgreSQL "
                    "delete failure."
                )


            DocumentRepository.delete_document = (
                forced_database_failure
            )


            try:

                assert_raises(
                    RuntimeError,

                    lambda:
                        deletion_service
                        .delete_document(
                            db_failure_document_id
                        ),

                    (
                        "Forced DB failure "
                        "should propagate."
                    ),
                )


            finally:

                DocumentRepository.delete_document = (
                    original_repository_delete
                )


            assert_equal(
                count_document(
                    db_failure_document_id
                ),
                1,
                (
                    "DB document should remain "
                    "after failed transaction."
                ),
            )


            assert_equal(
                count_analysis(
                    db_failure_document_id
                ),
                1,
                (
                    "Analysis should remain "
                    "after failed transaction."
                ),
            )


            assert_true(
                db_failure_directory.exists(),
                (
                    "Filesystem must remain "
                    "untouched when database "
                    "deletion fails."
                ),
            )


            print(
                "[PASS] Database failure "
                "rolled back"
            )

            print(
                "[PASS] Source storage "
                "preserved after DB failure"
            )


            # ==================================================
            # FINAL
            # ==================================================

            print()
            print("=" * 76)
            print(
                "[PASS] PHASE 7C.6b SAFE "
                "DOCUMENT DELETE SERVICE TEST PASSED"
            )
            print("=" * 76)


        finally:

            # ==================================================
            # RESTORE REPOSITORY METHOD
            # ==================================================

            DocumentRepository.delete_document = (
                original_repository_delete
            )


            # ==================================================
            # DATABASE CLEANUP
            # ==================================================

            if cleanup_document_ids:

                with SessionLocal.begin() as session:

                    for document_id in (
                        cleanup_document_ids
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


            print()
            print(
                "[CLEANUP] Phase 7C.6b "
                "temporary database and "
                "storage data removed."
            )


if __name__ == "__main__":

    main()