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
# PIPELINE RESULT
# ==========================================================

def build_pipeline_result() -> dict:

    return {
        "extraction": {
            "document_type":
                "guard_license",

            "full_name": {
                "value":
                    "PHASE 7C6D USER",

                "source_line_ids": [
                    "L0"
                ],
            },

            "licence_number": {
                "value":
                    "P7C6D001",

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
        "PHASE 7C.6d — ORPHAN + MISSING "
        "STORAGE DETECTION TEST"
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


        source = (
            temp_root
            / "source.jpg"
        )


        source.write_bytes(
            b"VIGILOX-PHASE-7C-6D"
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


            storage_service.save_original(
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


            # ==================================================
            # 4. UNMANAGED ROOT FILE
            # ==================================================

            unmanaged_file = (
                storage_service.storage_root
                / "unexpected.txt"
            )


            unmanaged_file.write_text(
                "unexpected root file",
                encoding="utf-8",
            )


            # ==================================================
            # 5. INVALID DIRECTORY NAME
            # ==================================================

            invalid_directory = (
                storage_service.storage_root
                / "invalid document id"
            )


            invalid_directory.mkdir()


            # ==================================================
            # 6. RUN READ-ONLY SCAN
            # ==================================================

            result = (
                integrity_service.scan()
            )


            assert_equal(
                result[
                    "status"
                ],
                "ISSUES_FOUND",
                (
                    "Integrity scan should "
                    "report issues."
                ),
            )


            summary = (
                result[
                    "summary"
                ]
            )


            assert_true(
                summary[
                    "healthy_documents"
                ]
                >= 1,
                (
                    "Healthy document was "
                    "not detected."
                ),
            )


            assert_true(
                summary[
                    "missing_storage"
                ]
                >= 1,
                (
                    "Missing storage was "
                    "not detected."
                ),
            )


            assert_true(
                summary[
                    "orphan_storage"
                ]
                >= 1,
                (
                    "Orphan storage was "
                    "not detected."
                ),
            )


            assert_true(
                summary[
                    "unmanaged_entries"
                ]
                >= 2,
                (
                    "Unmanaged filesystem "
                    "entries were not detected."
                ),
            )


            # ==================================================
            # HEALTHY DOCUMENT CHECK
            # ==================================================

            healthy_matches = [
                item
                for item
                in result[
                    "healthy_documents"
                ]
                if (
                    item[
                        "document_id"
                    ]
                    == healthy_id
                )
            ]


            assert_equal(
                len(
                    healthy_matches
                ),
                1,
                (
                    "Expected healthy document "
                    "exactly once."
                ),
            )


            print(
                "[PASS] Healthy DB + storage "
                "document detected"
            )


            # ==================================================
            # MISSING STORAGE CHECK
            # ==================================================

            missing_matches = [
                item
                for item
                in result[
                    "missing_storage"
                ]
                if (
                    item[
                        "document_id"
                    ]
                    == missing_id
                )
            ]


            assert_equal(
                len(
                    missing_matches
                ),
                1,
                (
                    "Missing-storage DB "
                    "document not detected."
                ),
            )


            print(
                "[PASS] DB document with "
                "missing source detected"
            )


            # ==================================================
            # ORPHAN CHECK
            # ==================================================

            orphan_matches = [
                item
                for item
                in result[
                    "orphan_storage"
                ]
                if (
                    item[
                        "document_id"
                    ]
                    == orphan_id
                )
            ]


            assert_equal(
                len(
                    orphan_matches
                ),
                1,
                (
                    "Orphan storage directory "
                    "not detected."
                ),
            )


            print(
                "[PASS] Orphan filesystem "
                "document detected"
            )


            # ==================================================
            # UNMANAGED FILE CHECK
            # ==================================================

            unmanaged_names = {
                item[
                    "name"
                ]
                for item
                in result[
                    "unmanaged_entries"
                ]
            }


            assert_true(
                "unexpected.txt"
                in unmanaged_names,
                (
                    "Unexpected root file "
                    "was not detected."
                ),
            )


            assert_true(
                "invalid document id"
                in unmanaged_names,
                (
                    "Invalid directory name "
                    "was not detected."
                ),
            )


            print(
                "[PASS] Unmanaged root file "
                "detected"
            )

            print(
                "[PASS] Invalid storage "
                "directory detected"
            )


            # ==================================================
            # READ-ONLY GUARANTEE
            # ==================================================

            assert_true(
                storage_service
                .get_document_directory(
                    orphan_id
                )
                .exists(),
                (
                    "Integrity scan must not "
                    "delete orphan storage."
                ),
            )


            assert_true(
                unmanaged_file.exists(),
                (
                    "Integrity scan must not "
                    "delete unmanaged files."
                ),
            )


            assert_true(
                invalid_directory.exists(),
                (
                    "Integrity scan must not "
                    "delete invalid directories."
                ),
            )


            print(
                "[PASS] Integrity scan is "
                "strictly read-only"
            )


            print()
            print("=" * 76)
            print(
                "[PASS] PHASE 7C.6d ORPHAN / "
                "MISSING STORAGE DETECTION TEST PASSED"
            )
            print("=" * 76)


            # ==================================================
            # MANUAL FILESYSTEM TEST CLEANUP
            # ==================================================

            storage_service.delete_document(
                orphan_id
            )


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


            print()
            print(
                "[CLEANUP] Phase 7C.6d "
                "temporary database and "
                "storage data removed."
            )


if __name__ == "__main__":

    main()