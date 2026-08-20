import tempfile

from pathlib import Path
from uuid import uuid4

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

from backend.app.services.query_service import (
    DocumentQueryService,
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

    return {
        "extraction": {
            "document_type":
                document_type,

            "fields":
                {},
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
                    None,

                "status":
                    "NOT_AVAILABLE",

                "days_until_expiry":
                    None,
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
                "NONE",

            "reason_codes":
                [],

            "issues":
                [],
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
        "PHASE 7B.4 — ORIGINAL DOCUMENT "
        "IMAGE RETRIEVAL API TEST"
    )
    print("=" * 72)


    created_document_ids: list[str] = []

    client = None


    with tempfile.TemporaryDirectory() as temp_dir:

        temp_root = Path(
            temp_dir
        )


        # ==================================================
        # 1. ISOLATED DOCUMENT STORAGE
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


        try:

            # ==================================================
            # 2. INJECT SERVICES INTO FASTAPI
            # ==================================================

            app.state.persistence = (
                persistence_service
            )


            app.state.document_query = (
                DocumentQueryService()
            )


            client = TestClient(
                app
            )


            print(
                "[OK] Test services initialized"
            )


            # ==================================================
            # 3. CREATE JPG SOURCE
            # ==================================================

            jpg_source = (
                temp_root
                / "source.jpg"
            )


            jpg_bytes = (
                b"PHASE-7B-JPEG-"
                b"ORIGINAL-BYTES"
            )


            jpg_source.write_bytes(
                jpg_bytes
            )


            jpg_stored = (
                persistence_service
                .save_processed_document(
                    original_filename=(
                        "phase7b_guard.jpg"
                    ),

                    content_type=(
                        "image/jpeg"
                    ),

                    pipeline_result=(
                        build_pipeline_result(
                            document_type=(
                                "guard_license"
                            )
                        )
                    ),

                    source_path=(
                        jpg_source
                    ),
                )
            )


            jpg_document_id = (
                jpg_stored[
                    "document_id"
                ]
            )


            created_document_ids.append(
                jpg_document_id
            )


            # ==================================================
            # TEST 1 — JPG RETRIEVAL
            # ==================================================

            response = (
                client.get(
                    (
                        f"/api/v1/documents/"
                        f"{jpg_document_id}/image"
                    )
                )
            )


            assert_equal(
                response.status_code,
                200,
                (
                    "Stored JPG should return "
                    "HTTP 200."
                ),
            )


            assert_equal(
                response.content,
                jpg_bytes,
                (
                    "Returned JPG bytes do not "
                    "match stored original."
                ),
            )


            assert_equal(
                response.headers[
                    "content-type"
                ],
                "image/jpeg",
                (
                    "JPG response has incorrect "
                    "Content-Type."
                ),
            )


            print(
                "[PASS] Stored JPG returned "
                "with HTTP 200"
            )

            print(
                "[PASS] JPG response bytes "
                "match original"
            )

            print(
                "[PASS] JPG Content-Type "
                "is image/jpeg"
            )


            # ==================================================
            # INLINE CONTENT DISPOSITION
            # ==================================================

            content_disposition = (
                response.headers.get(
                    "content-disposition",
                    "",
                )
            )


            if not content_disposition.lower().startswith(
                "inline"
            ):

                raise AssertionError(
                    "Original document should "
                    "be served inline."
                )


            print(
                "[PASS] Image served inline "
                "for reviewer display"
            )


            # ==================================================
            # 4. CREATE PNG SOURCE
            # ==================================================

            png_source = (
                temp_root
                / "source.png"
            )


            png_bytes = (
                b"PHASE-7B-PNG-"
                b"ORIGINAL-BYTES"
            )


            png_source.write_bytes(
                png_bytes
            )


            png_stored = (
                persistence_service
                .save_processed_document(
                    original_filename=(
                        "phase7b_id_card.png"
                    ),

                    content_type=(
                        "image/png"
                    ),

                    pipeline_result=(
                        build_pipeline_result(
                            document_type=(
                                "id_card"
                            )
                        )
                    ),

                    source_path=(
                        png_source
                    ),
                )
            )


            png_document_id = (
                png_stored[
                    "document_id"
                ]
            )


            created_document_ids.append(
                png_document_id
            )


            # ==================================================
            # TEST 2 — PNG RETRIEVAL
            # ==================================================

            response = (
                client.get(
                    (
                        f"/api/v1/documents/"
                        f"{png_document_id}/image"
                    )
                )
            )


            assert_equal(
                response.status_code,
                200,
                (
                    "Stored PNG should return "
                    "HTTP 200."
                ),
            )


            assert_equal(
                response.content,
                png_bytes,
                (
                    "Returned PNG bytes do not "
                    "match stored original."
                ),
            )


            assert_equal(
                response.headers[
                    "content-type"
                ],
                "image/png",
                (
                    "PNG response has incorrect "
                    "Content-Type."
                ),
            )


            print(
                "[PASS] PNG retrieval"
            )

            print(
                "[PASS] PNG Content-Type"
            )


            # ==================================================
            # 5. CREATE WEBP SOURCE
            # ==================================================

            webp_source = (
                temp_root
                / "source.webp"
            )


            webp_bytes = (
                b"PHASE-7B-WEBP-"
                b"ORIGINAL-BYTES"
            )


            webp_source.write_bytes(
                webp_bytes
            )


            webp_stored = (
                persistence_service
                .save_processed_document(
                    original_filename=(
                        "phase7b_sia.webp"
                    ),

                    content_type=(
                        "image/webp"
                    ),

                    pipeline_result=(
                        build_pipeline_result(
                            document_type=(
                                "sia_badge"
                            )
                        )
                    ),

                    source_path=(
                        webp_source
                    ),
                )
            )


            webp_document_id = (
                webp_stored[
                    "document_id"
                ]
            )


            created_document_ids.append(
                webp_document_id
            )


            # ==================================================
            # TEST 3 — WEBP RETRIEVAL
            # ==================================================

            response = (
                client.get(
                    (
                        f"/api/v1/documents/"
                        f"{webp_document_id}/image"
                    )
                )
            )


            assert_equal(
                response.status_code,
                200,
                (
                    "Stored WEBP should return "
                    "HTTP 200."
                ),
            )


            assert_equal(
                response.content,
                webp_bytes,
                (
                    "Returned WEBP bytes do not "
                    "match stored original."
                ),
            )


            assert_equal(
                response.headers[
                    "content-type"
                ],
                "image/webp",
                (
                    "WEBP response has incorrect "
                    "Content-Type."
                ),
            )


            print(
                "[PASS] WEBP retrieval"
            )

            print(
                "[PASS] WEBP Content-Type"
            )


            # ==================================================
            # 6. LEGACY DOCUMENT WITHOUT STORED ORIGINAL
            # ==================================================

            legacy_stored = (
                persistence_service
                .save_processed_document(
                    original_filename=(
                        "phase7b_legacy.jpg"
                    ),

                    content_type=(
                        "image/jpeg"
                    ),

                    pipeline_result=(
                        build_pipeline_result(
                            document_type=(
                                "guard_license"
                            )
                        )
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


            response = (
                client.get(
                    (
                        f"/api/v1/documents/"
                        f"{legacy_document_id}/image"
                    )
                )
            )


            assert_equal(
                response.status_code,
                404,
                (
                    "Legacy document without "
                    "stored original should "
                    "return HTTP 404."
                ),
            )


            assert_equal(
                response.json()[
                    "detail"
                ],
                (
                    "Original document image "
                    "is not available."
                ),
                (
                    "Unexpected missing-image "
                    "error message."
                ),
            )


            print(
                "[PASS] Legacy document "
                "without image returns HTTP 404"
            )


            # ==================================================
            # 7. UNKNOWN DOCUMENT
            # ==================================================

            unknown_document_id = str(
                uuid4()
            )


            response = (
                client.get(
                    (
                        f"/api/v1/documents/"
                        f"{unknown_document_id}/image"
                    )
                )
            )


            assert_equal(
                response.status_code,
                404,
                (
                    "Unknown document should "
                    "return HTTP 404."
                ),
            )


            assert_equal(
                response.json()[
                    "detail"
                ],
                "Document not found.",
                (
                    "Unexpected unknown-document "
                    "error message."
                ),
            )


            print(
                "[PASS] Unknown document "
                "returns HTTP 404"
            )


            # ==================================================
            # 8. VERIFY DETERMINISTIC STORAGE LOOKUP
            # ==================================================

            loaded_jpg = (
                storage_service
                .load_original(
                    document_id=(
                        jpg_document_id
                    ),

                    content_type=(
                        "image/jpeg"
                    ),
                )
            )


            if loaded_jpg is None:

                raise AssertionError(
                    "Stored JPG is unexpectedly "
                    "missing."
                )


            expected_jpg_path = (
                storage_root.resolve()
                / jpg_document_id
                / "original.jpg"
            )


            assert_equal(
                loaded_jpg,
                expected_jpg_path,
                (
                    "Image endpoint storage "
                    "path is not deterministic."
                ),
            )


            print(
                "[PASS] document_id-based "
                "storage lookup verified"
            )


            # ==================================================
            # FINAL SUCCESS
            # ==================================================

            print()
            print("=" * 72)
            print(
                "[PASS] PHASE 7B.4 ORIGINAL "
                "DOCUMENT IMAGE API TEST PASSED"
            )
            print("=" * 72)


        finally:

            # ==================================================
            # CLOSE TEST CLIENT
            # ==================================================

            if client is not None:

                client.close()


            # ==================================================
            # DATABASE CLEANUP
            # ==================================================

            if created_document_ids:

                with SessionLocal() as session:

                    for document_id in (
                        created_document_ids
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


                    session.commit()


            # ==================================================
            # FILE STORAGE CLEANUP
            # ==================================================

            for document_id in (
                created_document_ids
            ):

                storage_service.delete_document(
                    document_id
                )


            # ==================================================
            # APPLICATION STATE CLEANUP
            # ==================================================

            for state_name in (
                "persistence",
                "document_query",
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
                "[CLEANUP] Phase 7B.4 "
                "database and storage "
                "test data removed."
            )


if __name__ == "__main__":

    main()