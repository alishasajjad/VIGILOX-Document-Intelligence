import tempfile

from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from database.database import (
    SessionLocal,
)

from database.models import (
    AuditEventModel,
    DocumentAnalysisModel,
    DocumentModel,
)

from backend.app.services.persistence_service import (
    PersistenceService,
)

from backend.app.services.document_storage_service import (
    DocumentStorageService,
)


# ==========================================================
# PIPELINE RESULT BUILDER
# ==========================================================

def build_pipeline_result(
    *,
    document_type: str = "guard_license",
) -> dict:

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
                document_type,

            "fields": {
                "full_name": {
                    "value":
                        "PHASE 7B TEST USER",

                    "source_line_ids":
                        [],
                },

                "licence_number": {
                    "value":
                        "P7B123456",

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
                        "PHASE 7B TEST AUTHORITY",

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
                document_type,

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
# MAIN TEST
# ==========================================================

def main():

    print()
    print("=" * 72)
    print(
        "PHASE 7B.2 — PERSISTENCE + "
        "DOCUMENT STORAGE INTEGRATION TEST"
    )
    print("=" * 72)


    created_document_ids: list[str] = []


    with tempfile.TemporaryDirectory() as temp_dir:

        temp_root = Path(
            temp_dir
        )


        # ==================================================
        # 1. ISOLATED STORAGE ROOT
        # ==================================================

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


        # ==================================================
        # 2. CREATE SOURCE DOCUMENT
        # ==================================================

        source_path = (
            temp_root
            / "phase7b_source.jpg"
        )


        original_bytes = (
            b"VIGILOX-PHASE-7B-"
            b"ORIGINAL-DOCUMENT"
        )


        source_path.write_bytes(
            original_bytes
        )


        try:

            # ==================================================
            # TEST 1 — DB + ORIGINAL DOCUMENT STORAGE
            # ==================================================

            unique_filename = (
                "phase7b_storage_"
                f"{uuid4()}.jpg"
            )


            stored = (
                persistence_service
                .save_processed_document(
                    original_filename=(
                        unique_filename
                    ),

                    content_type=(
                        "image/jpeg"
                    ),

                    pipeline_result=(
                        build_pipeline_result()
                    ),

                    source_path=(
                        source_path
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


            created_document_ids.append(
                document_id
            )


            assert_equal(
                stored[
                    "original_document_stored"
                ],
                True,
                (
                    "Persistence result should "
                    "confirm original storage."
                ),
            )


            print(
                "[PASS] Persistence reports "
                "original document stored"
            )


            # ==================================================
            # 3. VERIFY DETERMINISTIC STORAGE PATH
            # ==================================================

            stored_path = (
                storage_service
                .get_original_path(
                    document_id=(
                        document_id
                    ),

                    content_type=(
                        "image/jpeg"
                    ),
                )
            )


            expected_path = (
                storage_root.resolve()
                / document_id
                / "original.jpg"
            )


            assert_equal(
                stored_path,
                expected_path,
                (
                    "Stored document path "
                    "is incorrect."
                ),
            )


            if not stored_path.exists():

                raise AssertionError(
                    "Original document was "
                    "not created on disk."
                )


            print(
                "[PASS] Deterministic "
                "document storage path"
            )


            # ==================================================
            # 4. VERIFY FILE BYTES
            # ==================================================

            assert_equal(
                stored_path.read_bytes(),
                original_bytes,
                (
                    "Stored document bytes "
                    "do not match source."
                ),
            )


            print(
                "[PASS] Original document "
                "bytes preserved"
            )


            # ==================================================
            # 5. VERIFY POSTGRESQL RECORDS
            # ==================================================

            with SessionLocal() as session:

                document = (
                    session.get(
                        DocumentModel,
                        document_id,
                    )
                )


                analysis = (
                    session.get(
                        DocumentAnalysisModel,
                        analysis_id,
                    )
                )


                machine_audit = (
                    session.get(
                        AuditEventModel,
                        machine_audit_id,
                    )
                )


                if document is None:

                    raise AssertionError(
                        "Document record was "
                        "not persisted."
                    )


                if analysis is None:

                    raise AssertionError(
                        "Analysis record was "
                        "not persisted."
                    )


                if machine_audit is None:

                    raise AssertionError(
                        "Machine audit record "
                        "was not persisted."
                    )


                assert_equal(
                    document.original_filename,
                    unique_filename,
                    (
                        "Original filename "
                        "was not persisted."
                    ),
                )


                assert_equal(
                    document.content_type,
                    "image/jpeg",
                    (
                        "Content type was "
                        "not persisted."
                    ),
                )


                assert_equal(
                    document.document_type,
                    "guard_license",
                    (
                        "Document type was "
                        "not persisted."
                    ),
                )


                assert_equal(
                    machine_audit.event_type,
                    "MACHINE_REVIEW_DECISION",
                    (
                        "Unexpected machine "
                        "audit event type."
                    ),
                )


            print(
                "[PASS] PostgreSQL document "
                "record persisted"
            )

            print(
                "[PASS] PostgreSQL analysis "
                "record persisted"
            )

            print(
                "[PASS] PostgreSQL machine "
                "audit persisted"
            )


            # ==================================================
            # TEST 2 — STORAGE SERVICE CAN RETRIEVE ORIGINAL
            # ==================================================

            loaded_path = (
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


            assert_equal(
                loaded_path,
                stored_path,
                (
                    "Stored original could "
                    "not be retrieved."
                ),
            )


            print(
                "[PASS] Persisted original "
                "document retrievable"
            )


            # ==================================================
            # TEST 3 — LEGACY CALL WITHOUT SOURCE PATH
            # ==================================================

            legacy_filename = (
                "phase7b_legacy_"
                f"{uuid4()}.jpg"
            )


            legacy_stored = (
                persistence_service
                .save_processed_document(
                    original_filename=(
                        legacy_filename
                    ),

                    content_type=(
                        "image/jpeg"
                    ),

                    pipeline_result=(
                        build_pipeline_result()
                    ),
                )
            )


            legacy_document_id = (
                legacy_stored[
                    "document_id"
                ]
            )


            created_document_ids.append(
                legacy_document_id
            )


            assert_equal(
                legacy_stored[
                    "original_document_stored"
                ],
                False,
                (
                    "Legacy call without "
                    "source_path should not "
                    "report stored original."
                ),
            )


            legacy_exists = (
                storage_service
                .original_exists(
                    document_id=(
                        legacy_document_id
                    ),

                    content_type=(
                        "image/jpeg"
                    ),
                )
            )


            assert_equal(
                legacy_exists,
                False,
                (
                    "Legacy call should not "
                    "create an original file."
                ),
            )


            with SessionLocal() as session:

                legacy_document = (
                    session.get(
                        DocumentModel,
                        legacy_document_id,
                    )
                )


                if legacy_document is None:

                    raise AssertionError(
                        "Legacy persistence "
                        "call should still "
                        "create DB records."
                    )


            print(
                "[PASS] Backward-compatible "
                "persistence without source_path"
            )


            # ==================================================
            # TEST 4 — STORAGE FAILURE → DATABASE ROLLBACK
            # ==================================================

            rollback_filename = (
                "phase7b_rollback_"
                f"{uuid4()}.jpg"
            )


            missing_source = (
                temp_root
                / "does_not_exist.jpg"
            )


            try:
                (
                    persistence_service
                    .save_processed_document(
                        original_filename=(
                            rollback_filename
                            ),

            content_type=(
                "image/jpeg"
                ),

            pipeline_result=(
                build_pipeline_result()
            ),

            source_path=(
                missing_source
            ),
        )
    )
            except FileNotFoundError:
                pass


            else:

                raise AssertionError(
                    "Missing source document "
                    "should make persistence "
                    "fail."
                )


            # Verify the document transaction rolled back.

            with SessionLocal() as session:

                statement = (
                    select(
                        DocumentModel
                    )
                    .where(
                        DocumentModel
                        .original_filename
                        == rollback_filename
                    )
                )


                rolled_back_document = (
                    session
                    .scalars(
                        statement
                    )
                    .one_or_none()
                )


            assert_equal(
                rolled_back_document,
                None,
                (
                    "Database document should "
                    "not exist after storage "
                    "failure."
                ),
            )


            print(
                "[PASS] Storage failure "
                "triggers PostgreSQL rollback"
            )


            # ==================================================
            # FINAL SUCCESS
            # ==================================================

            print()
            print("=" * 72)
            print(
                "[PASS] PHASE 7B.2 "
                "PERSISTENCE + STORAGE "
                "INTEGRATION TEST PASSED"
            )
            print("=" * 72)


        finally:

            # ==================================================
            # DATABASE CLEANUP
            # ==================================================

            if created_document_ids:

                with SessionLocal() as session:

                    for created_id in (
                        created_document_ids
                    ):

                        document = (
                            session.get(
                                DocumentModel,
                                created_id,
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

            for created_id in (
                created_document_ids
            ):

                storage_service.delete_document(
                    created_id
                )


            print()
            print(
                "[CLEANUP] Phase 7B.2 "
                "database and storage "
                "test data removed."
            )


if __name__ == "__main__":

    main()