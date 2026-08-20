import tempfile

from pathlib import Path

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
    DocumentModel,
)

from backend.app.services.persistence_service import (
    PersistenceService,
)

from database.repositories import (
    AuditEventRepository,
    DocumentAnalysisRepository,
)

from backend.app.services.document_storage_service import (
    DocumentStorageService,
)


# ==========================================================
# TEST CONSTANTS
# ==========================================================

TEST_BYTES = (
    b"VIGILOX-PHASE-7C-6C-"
    b"FAILED-PROCESSING-CLEANUP"
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
                    "PHASE 7C6C USER",

                "source_line_ids": [
                    "L0"
                ],
            },

            "licence_number": {
                "value":
                    "P7C6C001",

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
                    "PHASE 7C6C USER",

                "confidence":
                    0.999,

                "bbox":
                    [10, 10, 200, 30],
            },

            {
                "line_id":
                    "L1",

                "text":
                    "P7C6C001",

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
# DATABASE HELPER
# ==========================================================

def count_documents_by_filename(
    filename: str,
) -> int:

    with SessionLocal() as session:

        statement = (
            select(
                func.count(
                    DocumentModel.id
                )
            )
            .where(
                DocumentModel.original_filename
                == filename
            )
        )


        return (
            session.scalar(
                statement
            )
            or 0
        )


# ==========================================================
# TRACKING STORAGE SERVICE
# ==========================================================

class TrackingStorageService(
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


        self.last_document_id = None


    def save_original(
        self,
        *,
        document_id: str,
        source_path: str | Path,
        content_type: str,
    ) -> Path:

        self.last_document_id = (
            document_id
        )


        return (
            super()
            .save_original(
                document_id=(
                    document_id
                ),

                source_path=(
                    source_path
                ),

                content_type=(
                    content_type
                ),
            )
        )


# ==========================================================
# FAIL AFTER PHYSICAL SAVE
# ==========================================================

class FailAfterSaveStorageService(
    TrackingStorageService
):

    def save_original(
        self,
        *,
        document_id: str,
        source_path: str | Path,
        content_type: str,
    ) -> Path:

        stored_path = (
            super()
            .save_original(
                document_id=(
                    document_id
                ),

                source_path=(
                    source_path
                ),

                content_type=(
                    content_type
                ),
            )
        )


        assert_true(
            stored_path.exists(),
            (
                "Test setup expected "
                "physical source to exist."
            ),
        )


        raise RuntimeError(
            "Forced failure after "
            "physical source storage."
        )


# ==========================================================
# FAILING PIPELINE
# ==========================================================

class FailingPipeline:

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
                "Temporary upload should exist "
                "while pipeline is running."
            ),
        )


        assert_equal(
            path.read_bytes(),
            TEST_BYTES,
            (
                "Pipeline received incorrect "
                "temporary upload bytes."
            ),
        )


        raise RuntimeError(
            "Forced pipeline failure."
        )


# ==========================================================
# FAILING PERSISTENCE FOR API TEMP TEST
# ==========================================================

class FailingPersistence:

    def __init__(
        self,
    ):

        self.received_temp_path = None


    def save_processed_document(
        self,
        *,
        original_filename: str,
        content_type: str,
        pipeline_result: dict,
        source_path: str | Path | None = None,
    ):

        self.received_temp_path = (
            source_path
        )


        assert_true(
            source_path is not None,
            (
                "Persistence should receive "
                "temporary source path."
            ),
        )


        assert_true(
            Path(
                source_path
            ).exists(),
            (
                "Temporary upload should exist "
                "while persistence runs."
            ),
        )


        raise RuntimeError(
            "Forced persistence failure."
        )


# ==========================================================
# SUCCESS PIPELINE FOR API PERSISTENCE FAILURE
# ==========================================================

class SuccessfulFakePipeline:

    def process(
        self,
        image_path: str,
    ) -> dict:

        assert_true(
            Path(
                image_path
            ).exists(),
            (
                "Pipeline temporary file "
                "should exist."
            ),
        )


        return (
            build_pipeline_result()
        )


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("=" * 76)
    print(
        "PHASE 7C.6c — FAILED ANALYSIS / "
        "PARTIAL STORAGE CLEANUP TEST"
    )
    print("=" * 76)


    original_create_analysis = (
        DocumentAnalysisRepository
        .create_analysis
    )


    original_create_event = (
        AuditEventRepository
        .create_event
    )


    client = None


    with tempfile.TemporaryDirectory() as temp_dir:

        temp_root = Path(
            temp_dir
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
            # TEST 1 — PIPELINE FAILURE CLEANS API TEMP FILE
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 1 — PIPELINE FAILURE "
                "CLEANS TEMP UPLOAD"
            )
            print("-" * 76)


            failing_pipeline = (
                FailingPipeline()
            )


            storage_service = (
                DocumentStorageService(
                    storage_root=(
                        temp_root
                        / "api-pipeline-storage"
                    )
                )
            )


            app.state.pipeline = (
                failing_pipeline
            )


            app.state.persistence = (
                PersistenceService(
                    storage_service=(
                        storage_service
                    )
                )
            )


            client = TestClient(
                app
            )


            pipeline_filename = (
                "phase7c6c_pipeline_failure.jpg"
            )


            response = client.post(
                "/api/v1/documents/analyze",

                files={
                    "file": (
                        pipeline_filename,
                        TEST_BYTES,
                        "image/jpeg",
                    )
                },
            )


            assert_equal(
                response.status_code,
                500,
                (
                    "Pipeline failure should "
                    "return HTTP 500."
                ),
            )


            assert_true(
                failing_pipeline
                .received_temp_path
                is not None,
                (
                    "Pipeline did not receive "
                    "temporary path."
                ),
            )


            assert_false(
                Path(
                    failing_pipeline
                    .received_temp_path
                ).exists(),
                (
                    "Pipeline failure left "
                    "temporary upload behind."
                ),
            )


            assert_equal(
                count_documents_by_filename(
                    pipeline_filename
                ),
                0,
                (
                    "Pipeline failure should "
                    "not create DB document."
                ),
            )


            print(
                "[PASS] Pipeline failure "
                "returned HTTP 500"
            )

            print(
                "[PASS] Pipeline temporary "
                "upload cleaned"
            )

            print(
                "[PASS] Pipeline failure "
                "created no DB document"
            )


            client.close()
            client = None


            # ==================================================
            # TEST 2 — API PERSISTENCE FAILURE CLEANS TEMP
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 2 — PERSISTENCE FAILURE "
                "CLEANS TEMP UPLOAD"
            )
            print("-" * 76)


            failing_persistence = (
                FailingPersistence()
            )


            app.state.pipeline = (
                SuccessfulFakePipeline()
            )


            app.state.persistence = (
                failing_persistence
            )


            client = TestClient(
                app
            )


            response = client.post(
                "/api/v1/documents/analyze",

                files={
                    "file": (
                        "phase7c6c_api_persist_fail.jpg",
                        TEST_BYTES,
                        "image/jpeg",
                    )
                },
            )


            assert_equal(
                response.status_code,
                500,
                (
                    "Persistence failure should "
                    "return HTTP 500."
                ),
            )


            assert_true(
                failing_persistence
                .received_temp_path
                is not None,
                (
                    "Persistence did not "
                    "receive temp source."
                ),
            )


            assert_false(
                Path(
                    failing_persistence
                    .received_temp_path
                ).exists(),
                (
                    "Persistence failure left "
                    "temporary upload behind."
                ),
            )


            print(
                "[PASS] Persistence failure "
                "returned HTTP 500"
            )

            print(
                "[PASS] Persistence failure "
                "temporary upload cleaned"
            )


            client.close()
            client = None


            # ==================================================
            # TEST 3 — SAVE FAILS AFTER PHYSICAL STORAGE
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 3 — FAILURE AFTER "
                "PHYSICAL SOURCE STORAGE"
            )
            print("-" * 76)


            fail_after_save_storage = (
                FailAfterSaveStorageService(
                    storage_root=(
                        temp_root
                        / "fail-after-save"
                    )
                )
            )


            persistence_service = (
                PersistenceService(
                    storage_service=(
                        fail_after_save_storage
                    )
                )
            )


            filename = (
                "phase7c6c_after_save_fail.jpg"
            )


            assert_raises(
                RuntimeError,

                lambda:
                    persistence_service
                    .save_processed_document(
                        original_filename=(
                            filename
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
                    ),

                (
                    "Failure after physical "
                    "save should propagate."
                ),
            )


            document_id = (
                fail_after_save_storage
                .last_document_id
            )


            assert_true(
                document_id is not None,
                (
                    "Storage service did not "
                    "capture document ID."
                ),
            )


            assert_false(
                fail_after_save_storage
                .get_document_directory(
                    document_id
                )
                .exists(),
                (
                    "Failure after physical "
                    "save left orphan storage."
                ),
            )


            assert_equal(
                count_documents_by_filename(
                    filename
                ),
                0,
                (
                    "Failed storage transaction "
                    "should rollback DB document."
                ),
            )


            print(
                "[PASS] Physical-save failure "
                "propagated"
            )

            print(
                "[PASS] Partial permanent "
                "storage compensated"
            )

            print(
                "[PASS] Database transaction "
                "rolled back"
            )


            # ==================================================
            # TEST 4 — ANALYSIS INSERT FAILURE
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 4 — ANALYSIS DB "
                "INSERT FAILURE"
            )
            print("-" * 76)


            tracking_storage = (
                TrackingStorageService(
                    storage_root=(
                        temp_root
                        / "analysis-failure"
                    )
                )
            )


            persistence_service = (
                PersistenceService(
                    storage_service=(
                        tracking_storage
                    )
                )
            )


            def forced_analysis_failure(
                self,
                *,
                document_id: str,
                pipeline_result: dict,
            ):

                raise RuntimeError(
                    "Forced analysis "
                    "database failure."
                )


            DocumentAnalysisRepository.create_analysis = (
                forced_analysis_failure
            )


            analysis_filename = (
                "phase7c6c_analysis_fail.jpg"
            )


            try:

                assert_raises(
                    RuntimeError,

                    lambda:
                        persistence_service
                        .save_processed_document(
                            original_filename=(
                                analysis_filename
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
                        ),

                    (
                        "Analysis DB failure "
                        "should propagate."
                    ),
                )


            finally:

                DocumentAnalysisRepository.create_analysis = (
                    original_create_analysis
                )


            analysis_document_id = (
                tracking_storage
                .last_document_id
            )


            assert_true(
                analysis_document_id
                is not None,
                (
                    "Analysis-failure test "
                    "did not capture ID."
                ),
            )


            assert_false(
                tracking_storage
                .get_document_directory(
                    analysis_document_id
                )
                .exists(),
                (
                    "Analysis DB failure left "
                    "stored source behind."
                ),
            )


            assert_equal(
                count_documents_by_filename(
                    analysis_filename
                ),
                0,
                (
                    "Analysis DB failure "
                    "should rollback document."
                ),
            )


            print(
                "[PASS] Analysis DB failure "
                "rolled back"
            )

            print(
                "[PASS] Stored source "
                "compensated after analysis failure"
            )


            # ==================================================
            # TEST 5 — MACHINE AUDIT INSERT FAILURE
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 5 — MACHINE AUDIT "
                "DB INSERT FAILURE"
            )
            print("-" * 76)


            audit_storage = (
                TrackingStorageService(
                    storage_root=(
                        temp_root
                        / "audit-failure"
                    )
                )
            )


            persistence_service = (
                PersistenceService(
                    storage_service=(
                        audit_storage
                    )
                )
            )


            def forced_audit_failure(
                self,
                *,
                document_id: str,
                event_type: str,
                actor_type: str,
                actor_id: str | None,
                details: dict,
            ):

                raise RuntimeError(
                    "Forced machine audit "
                    "database failure."
                )


            AuditEventRepository.create_event = (
                forced_audit_failure
            )


            audit_filename = (
                "phase7c6c_audit_fail.jpg"
            )


            try:

                assert_raises(
                    RuntimeError,

                    lambda:
                        persistence_service
                        .save_processed_document(
                            original_filename=(
                                audit_filename
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
                        ),

                    (
                        "Audit DB failure "
                        "should propagate."
                    ),
                )


            finally:

                AuditEventRepository.create_event = (
                    original_create_event
                )


            audit_document_id = (
                audit_storage
                .last_document_id
            )


            assert_true(
                audit_document_id
                is not None,
                (
                    "Audit-failure test "
                    "did not capture ID."
                ),
            )


            assert_false(
                audit_storage
                .get_document_directory(
                    audit_document_id
                )
                .exists(),
                (
                    "Audit DB failure left "
                    "stored source behind."
                ),
            )


            assert_equal(
                count_documents_by_filename(
                    audit_filename
                ),
                0,
                (
                    "Audit DB failure should "
                    "rollback document."
                ),
            )


            print(
                "[PASS] Machine audit DB "
                "failure rolled back"
            )

            print(
                "[PASS] Stored source "
                "compensated after audit failure"
            )


            # ==================================================
            # TEST 6 — SUCCESSFUL PERSISTENCE STILL WORKS
            # ==================================================

            print()
            print("-" * 76)
            print(
                "TEST 6 — SUCCESSFUL "
                "PERSISTENCE CONTROL"
            )
            print("-" * 76)


            success_storage = (
                TrackingStorageService(
                    storage_root=(
                        temp_root
                        / "success"
                    )
                )
            )


            success_persistence = (
                PersistenceService(
                    storage_service=(
                        success_storage
                    )
                )
            )


            success_filename = (
                "phase7c6c_success.jpg"
            )


            stored = (
                success_persistence
                .save_processed_document(
                    original_filename=(
                        success_filename
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


            success_document_id = (
                stored[
                    "document_id"
                ]
            )


            assert_equal(
                stored[
                    "original_document_stored"
                ],
                True,
                (
                    "Successful persistence "
                    "should report stored source."
                ),
            )


            assert_true(
                success_storage
                .get_document_directory(
                    success_document_id
                )
                .exists(),
                (
                    "Successful persistence "
                    "should retain storage."
                ),
            )


            assert_equal(
                count_documents_by_filename(
                    success_filename
                ),
                1,
                (
                    "Successful document "
                    "was not persisted."
                ),
            )


            print(
                "[PASS] Successful DB "
                "persistence retained"
            )

            print(
                "[PASS] Successful permanent "
                "storage retained"
            )


            # ==================================================
            # SUCCESS CONTROL CLEANUP
            # ==================================================

            with SessionLocal.begin() as session:

                document = (
                    session.get(
                        DocumentModel,
                        success_document_id,
                    )
                )


                if document is not None:

                    session.delete(
                        document
                    )


            success_storage.delete_document(
                success_document_id
            )


            # ==================================================
            # FINAL
            # ==================================================

            print()
            print("=" * 76)
            print(
                "[PASS] PHASE 7C.6c FAILED "
                "PROCESSING / PARTIAL STORAGE "
                "CLEANUP TEST PASSED"
            )
            print("=" * 76)


        finally:

            # ==================================================
            # RESTORE MONKEYPATCHES
            # ==================================================

            DocumentAnalysisRepository.create_analysis = (
                original_create_analysis
            )


            AuditEventRepository.create_event = (
                original_create_event
            )


            # ==================================================
            # CLIENT CLEANUP
            # ==================================================

            if client is not None:

                client.close()


            # ==================================================
            # APP STATE CLEANUP
            # ==================================================

            for state_name in (
                "pipeline",
                "persistence",
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
                "[CLEANUP] Phase 7C.6c "
                "temporary test state removed."
            )


if __name__ == "__main__":

    main()