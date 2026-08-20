import tempfile

from pathlib import Path

from fastapi.testclient import (
    TestClient,
)

from backend.app.main import app

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


# ==========================================================
# FAKE PIPELINE
# ==========================================================

class FakePipeline:

    def process(
        self,
        image_path: str,
    ) -> dict:

        # Verify that FastAPI actually created
        # the temporary upload file.

        path = Path(
            image_path
        )

        if not path.exists():

            raise AssertionError(
                "Temporary upload file "
                "does not exist."
            )


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

                "fields": {},
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
# MAIN
# ==========================================================

def main():

    print()
    print("=" * 72)
    print(
        "PHASE 7B.3 — ANALYZE API + "
        "ORIGINAL STORAGE TEST"
    )
    print("=" * 72)


    document_id = None

    client = None


    with tempfile.TemporaryDirectory() as temp_dir:

        storage_root = (
            Path(temp_dir)
            / "documents"
        )


        storage_service = (
            DocumentStorageService(
                storage_root=(
                    storage_root
                )
            )
        )


        try:

            # ==============================================
            # INJECT TEST SERVICES
            # ==============================================

            app.state.pipeline = (
                FakePipeline()
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


            # ==============================================
            # TEST UPLOAD BYTES
            # ==============================================

            original_bytes = (
                b"PHASE-7B-API-"
                b"ORIGINAL-DOCUMENT-BYTES"
            )


            # ==============================================
            # CALL ANALYZE ENDPOINT
            # ==============================================

            response = (
                client.post(
                    "/api/v1/documents/analyze",

                    files={
                        "file": (
                            "phase7b_api_guard.jpg",
                            original_bytes,
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


            body = (
                response.json()
            )


            print(
                "[PASS] Analyze endpoint "
                "returned HTTP 200"
            )


            # ==============================================
            # VERIFY API RESPONSE
            # ==============================================

            assert_equal(
                body[
                    "status"
                ],
                "success",
                (
                    "Analyze response status "
                    "should be success."
                ),
            )


            assert_equal(
                body[
                    "original_document_stored"
                ],
                True,
                (
                    "API should confirm that "
                    "original document was stored."
                ),
            )


            document_id = (
                body[
                    "document_id"
                ]
            )


            if not document_id:

                raise AssertionError(
                    "API response missing "
                    "document_id."
                )


            print(
                "[PASS] API confirms "
                "original document storage"
            )


            # ==============================================
            # VERIFY PERMANENT FILE
            # ==============================================

            stored_path = (
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


            if stored_path is None:

                raise AssertionError(
                    "Permanent original "
                    "document was not found."
                )


            assert_equal(
                stored_path.read_bytes(),
                original_bytes,
                (
                    "Permanent original bytes "
                    "do not match upload."
                ),
            )


            print(
                "[PASS] Uploaded document "
                "permanently stored"
            )

            print(
                "[PASS] Permanent file bytes "
                "match uploaded bytes"
            )


            # ==============================================
            # VERIFY PATH
            # ==============================================

            expected_path = (
                storage_root.resolve()
                / document_id
                / "original.jpg"
            )


            assert_equal(
                stored_path,
                expected_path,
                (
                    "Permanent document path "
                    "is incorrect."
                ),
            )


            print(
                "[PASS] Permanent storage "
                "path uses document_id"
            )


            # ==============================================
            # VERIFY POSTGRESQL
            # ==============================================

            with SessionLocal() as session:

                document = (
                    session.get(
                        DocumentModel,
                        document_id,
                    )
                )


                if document is None:

                    raise AssertionError(
                        "Document was not "
                        "persisted in PostgreSQL."
                    )


                assert_equal(
                    document.original_filename,
                    "phase7b_api_guard.jpg",
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


            print(
                "[PASS] PostgreSQL document "
                "record verified"
            )


            # ==============================================
            # VERIFY INVALID FILE TYPE STILL REJECTED
            # ==============================================

            invalid_response = (
                client.post(
                    "/api/v1/documents/analyze",

                    files={
                        "file": (
                            "invalid.txt",
                            b"invalid-data",
                            "text/plain",
                        )
                    },
                )
            )


            assert_equal(
                invalid_response.status_code,
                400,
                (
                    "Unsupported upload should "
                    "return HTTP 400."
                ),
            )


            print(
                "[PASS] Unsupported file "
                "type still rejected"
            )


            # ==============================================
            # FINAL SUCCESS
            # ==============================================

            print()
            print("=" * 72)
            print(
                "[PASS] PHASE 7B.3 ANALYZE "
                "API STORAGE TEST PASSED"
            )
            print("=" * 72)


        finally:

            # ==============================================
            # CLOSE CLIENT
            # ==============================================

            if client is not None:

                client.close()


            # ==============================================
            # DATABASE CLEANUP
            # ==============================================

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


                # ==========================================
                # STORAGE CLEANUP
                # ==========================================

                storage_service.delete_document(
                    document_id
                )


            # ==============================================
            # APPLICATION STATE CLEANUP
            # ==============================================

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
                "[CLEANUP] Phase 7B.3 "
                "database and storage "
                "test data removed."
            )


if __name__ == "__main__":

    main()