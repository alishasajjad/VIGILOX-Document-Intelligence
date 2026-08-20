import tempfile

from pathlib import Path
from uuid import uuid4

from database.database import (
    SessionLocal,
)

from database.models import (
    DocumentModel,
)

from backend.app.services.persistence_service import (
    PersistenceService,
)

from backend.app.services.document_storage_service import (
    DocumentStorageService,
)

from backend.app.services.storage_integrity_service import (
    StorageIntegrityService,
)

from backend.app.services.storage_reconciliation_service import (
    StorageReconciliationService,
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
# PIPELINE RESULT
# ==========================================================

def build_pipeline_result() -> dict:

    return {
        "extraction": {
            "document_type":
                "guard_license",

            "full_name": {
                "value":
                    "PHASE 7C6E USER",

                "source_line_ids": [
                    "L0"
                ],
            },

            "licence_number": {
                "value":
                    "P7C6E001",

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
                    "2027-01-01",

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

            "expiry":
                {},

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
                False,

            "error_count":
                0,

            "warning_count":
                0,

            "issues":
                [],
        },

        "review_decision": {
            "decision":
                "AUTO_ACCEPT",

            "review_required":
                False,

            "priority":
                None,

            "reason_codes":
                [],

            "issues":
                [],
        },
    }


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("=" * 76)
    print(
        "PHASE 7C.6e — STORAGE "
        "RECONCILIATION / SAFE CLEANUP TEST"
    )
    print("=" * 76)


    cleanup_ids = set()


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


        source = (
            temp_root
            / "source.jpg"
        )


        source.write_bytes(
            b"VIGILOX-PHASE-7C-6E"
        )


        try:

            # ==================================================
            # 1. HEALTHY DOCUMENT
            # ==================================================

            healthy = (
                persistence_service
                .save_processed_document(
                    original_filename=(
                        "healthy.jpg"
                    ),

                    content_type=(
                        "image/jpeg"
                    ),

                    pipeline_result=(
                        build_pipeline_result()
                    ),

                    source_path=(
                        source
                    ),
                )
            )


            healthy_id = (
                healthy[
                    "document_id"
                ]
            )


            cleanup_ids.add(
                healthy_id
            )


            healthy_directory = (
                storage_service
                .get_document_directory(
                    healthy_id
                )
            )


            # ==================================================
            # 2. DB DOCUMENT WITH MISSING STORAGE
            # ==================================================

            missing = (
                persistence_service
                .save_processed_document(
                    original_filename=(
                        "missing.jpg"
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


            missing_id = (
                missing[
                    "document_id"
                ]
            )


            cleanup_ids.add(
                missing_id
            )


            # ==================================================
            # 3. ORPHAN STORAGE
            # ==================================================

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
                        source
                    ),

                    content_type=(
                        "image/jpeg"
                    ),
                )
            )


            orphan_directory = (
                storage_service
                .get_document_directory(
                    orphan_id
                )
            )


            # ==================================================
            # 4. UNMANAGED FILE
            # ==================================================

            unmanaged_file = (
                storage_service.storage_root
                / "unexpected.txt"
            )


            unmanaged_file.write_text(
                "do not delete",
                encoding="utf-8",
            )


            # ==================================================
            # 5. INVALID DIRECTORY
            # ==================================================

            invalid_directory = (
                storage_service.storage_root
                / "invalid document id"
            )


            invalid_directory.mkdir()


            # ==================================================
            # 6. DRY RUN
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 1 — DRY RUN"
            )
            print("-" * 76)


            dry_run = (
                reconciliation_service
                .reconcile_orphans(
                    dry_run=True
                )
            )


            assert_equal(
                dry_run[
                    "mode"
                ],
                "DRY_RUN",
                (
                    "Unexpected reconciliation "
                    "mode."
                ),
            )


            assert_true(
                dry_run[
                    "candidate_count"
                ]
                >= 1,
                (
                    "Orphan candidate was "
                    "not detected."
                ),
            )


            assert_true(
                dry_run[
                    "would_delete_count"
                ]
                >= 1,
                (
                    "Dry run did not report "
                    "orphan cleanup candidate."
                ),
            )


            assert_true(
                orphan_path.exists(),
                (
                    "Dry run deleted "
                    "orphan storage."
                ),
            )


            assert_true(
                healthy_directory.exists(),
                (
                    "Dry run modified "
                    "healthy storage."
                ),
            )


            assert_true(
                unmanaged_file.exists(),
                (
                    "Dry run modified "
                    "unmanaged file."
                ),
            )


            assert_true(
                invalid_directory.exists(),
                (
                    "Dry run modified invalid "
                    "directory."
                ),
            )


            print(
                "[PASS] Dry run detected "
                "orphan candidate"
            )

            print(
                "[PASS] Dry run deleted nothing"
            )


            # ==================================================
            # 7. EXECUTE SAFE RECONCILIATION
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 2 — EXECUTE SAFE "
                "ORPHAN CLEANUP"
            )
            print("-" * 76)


            executed = (
                reconciliation_service
                .reconcile_orphans(
                    dry_run=False
                )
            )


            assert_equal(
                executed[
                    "mode"
                ],
                "EXECUTE",
                (
                    "Unexpected execute mode."
                ),
            )


            assert_true(
                executed[
                    "deleted_count"
                ]
                >= 1,
                (
                    "Orphan storage was "
                    "not deleted."
                ),
            )


            assert_false(
                orphan_directory.exists(),
                (
                    "Orphan directory still "
                    "exists after reconciliation."
                ),
            )


            print(
                "[PASS] Orphan storage "
                "deleted safely"
            )


            # ==================================================
            # 8. HEALTHY STORAGE PRESERVED
            # ==================================================

            assert_true(
                healthy_directory.exists(),
                (
                    "Healthy storage must "
                    "not be deleted."
                ),
            )


            assert_true(
                storage_service.original_exists(
                    document_id=(
                        healthy_id
                    ),

                    content_type=(
                        "image/jpeg"
                    ),
                ),
                (
                    "Healthy original source "
                    "must remain available."
                ),
            )


            print(
                "[PASS] Healthy document "
                "storage preserved"
            )


            # ==================================================
            # 9. MISSING-STORAGE DB RECORD PRESERVED
            # ==================================================

            with SessionLocal() as session:

                missing_document = (
                    session.get(
                        DocumentModel,
                        missing_id,
                    )
                )


                assert_true(
                    missing_document
                    is not None,
                    (
                        "Reconciliation must "
                        "not delete DB records "
                        "with missing storage."
                    ),
                )


            print(
                "[PASS] Missing-storage DB "
                "record preserved"
            )


            # ==================================================
            # 10. UNMANAGED DATA PRESERVED
            # ==================================================

            assert_true(
                unmanaged_file.exists(),
                (
                    "Unmanaged root file "
                    "must not be deleted."
                ),
            )


            assert_true(
                invalid_directory.exists(),
                (
                    "Invalid storage directory "
                    "must not be deleted."
                ),
            )


            print(
                "[PASS] Unmanaged root "
                "file preserved"
            )

            print(
                "[PASS] Invalid directory "
                "preserved"
            )


            # ==================================================
            # 11. SECOND RECONCILIATION IS IDEMPOTENT
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 3 — IDEMPOTENT "
                "SECOND RECONCILIATION"
            )
            print("-" * 76)


            second_run = (
                reconciliation_service
                .reconcile_orphans(
                    dry_run=False
                )
            )


            assert_equal(
                second_run[
                    "deleted_count"
                ],
                0,
                (
                    "Second reconciliation "
                    "should have no orphan "
                    "left to delete."
                ),
            )


            print(
                "[PASS] Reconciliation is "
                "idempotent"
            )


            # ==================================================
            # 12. FINAL INTEGRITY REPORT
            # ==================================================

            final_report = (
                integrity_service.scan()
            )


            orphan_ids = {
                item[
                    "document_id"
                ]
                for item
                in final_report[
                    "orphan_storage"
                ]
            }


            assert_true(
                orphan_id
                not in orphan_ids,
                (
                    "Deleted orphan still "
                    "appears in integrity scan."
                ),
            )


            missing_ids = {
                item[
                    "document_id"
                ]
                for item
                in final_report[
                    "missing_storage"
                ]
            }


            assert_true(
                missing_id
                in missing_ids,
                (
                    "Missing-storage DB record "
                    "should still be reported."
                ),
            )


            print(
                "[PASS] Final integrity scan "
                "shows orphan removed"
            )

            print(
                "[PASS] Missing-storage issue "
                "remains visible for manual action"
            )


            print()
            print("=" * 76)
            print(
                "[PASS] PHASE 7C.6e STORAGE "
                "RECONCILIATION TEST PASSED"
            )
            print("=" * 76)


            # ==================================================
            # TEST FILESYSTEM CLEANUP
            # ==================================================

            unmanaged_file.unlink()


            invalid_directory.rmdir()


        finally:

            # ==================================================
            # DATABASE CLEANUP
            # ==================================================

            if cleanup_ids:

                with SessionLocal.begin() as session:

                    for document_id in (
                        cleanup_ids
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


            # ==================================================
            # STORAGE CLEANUP
            # ==================================================

            for document_id in (
                cleanup_ids
            ):

                try:

                    storage_service.delete_document(
                        document_id
                    )

                except Exception:

                    pass


            try:

                storage_service.delete_document(
                    orphan_id
                )

            except Exception:

                pass


            print()
            print(
                "[CLEANUP] Phase 7C.6e "
                "temporary database and "
                "storage data removed."
            )


if __name__ == "__main__":

    main()