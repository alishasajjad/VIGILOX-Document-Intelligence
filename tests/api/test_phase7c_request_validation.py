from pathlib import Path

from fastapi.testclient import (
    TestClient,
)

from backend.app import (
    main as api_main,
)

from backend.app.main import (
    app,
)

from backend.app.api.request_validation import (
    normalize_upload_filename,
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
# ERROR CONTRACT
# ==========================================================

def assert_error(
    response,
    *,
    status_code: int,
    code: str,
):

    assert_equal(
        response.status_code,
        status_code,
        (
            "Unexpected HTTP status."
        ),
    )


    body = (
        response.json()
    )


    assert_equal(
        body[
            "status"
        ],
        "error",
        (
            "Response should use central "
            "error contract."
        ),
    )


    assert_equal(
        body[
            "error"
        ][
            "code"
        ],
        code,
        (
            "Unexpected structured "
            "error code."
        ),
    )


# ==========================================================
# FAKE PIPELINE
# ==========================================================

class TrackingPipeline:

    def __init__(
        self,
    ):

        self.calls = 0

        self.received_path = None

        self.received_bytes = None


    def process(
        self,
        image_path: str,
    ) -> dict:

        self.calls += 1


        self.received_path = (
            image_path
        )


        path = Path(
            image_path
        )


        if not path.exists():

            raise AssertionError(
                "Pipeline received a missing "
                "temporary upload path."
            )


        self.received_bytes = (
            path.read_bytes()
        )


        return {
            "test":
                "pipeline-result"
        }


# ==========================================================
# FAKE PERSISTENCE
# ==========================================================

class RecordingPersistence:

    def __init__(
        self,
    ):

        self.calls = 0

        self.original_filename = None

        self.content_type = None

        self.source_path = None


    def save_processed_document(
        self,
        *,
        original_filename: str,
        content_type: str,
        pipeline_result: dict,
        source_path,
    ) -> dict:

        self.calls += 1


        self.original_filename = (
            original_filename
        )


        self.content_type = (
            content_type
        )


        self.source_path = (
            source_path
        )


        if not Path(
            source_path
        ).exists():

            raise AssertionError(
                "Persistence should receive "
                "an existing temp file."
            )


        return {
            "document_id":
                "phase7c7b-document",

            "analysis_id":
                "phase7c7b-analysis",

            "machine_audit_id":
                "phase7c7b-audit",

            "processing_status":
                "PROCESSED",

            "original_document_stored":
                True,
        }


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("=" * 76)
    print(
        "PHASE 7C.7b — REQUEST / "
        "VALIDATION HARDENING TEST"
    )
    print("=" * 76)


    client = None


    original_pipeline = (
        getattr(
            app.state,
            "pipeline",
            None,
        )
    )


    original_persistence = (
        getattr(
            app.state,
            "persistence",
            None,
        )
    )


    original_max_upload_bytes = (
        api_main.MAX_UPLOAD_BYTES
    )


    try:

        pipeline = (
            TrackingPipeline()
        )


        persistence = (
            RecordingPersistence()
        )


        app.state.pipeline = (
            pipeline
        )


        app.state.persistence = (
            persistence
        )


        client = TestClient(
            app,
            raise_server_exceptions=False,
        )


        # ==================================================
        # TEST 1 — UNSUPPORTED CONTENT TYPE
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 1 — UNSUPPORTED "
            "CONTENT TYPE"
        )
        print("-" * 76)


        response = (
            client.post(
                "/api/v1/documents/analyze",

                files={
                    "file": (
                        "document.txt",
                        b"not-an-image",
                        "text/plain",
                    )
                },
            )
        )


        assert_error(
            response,

            status_code=400,

            code=(
                "UNSUPPORTED_FILE_TYPE"
            ),
        )


        assert_equal(
            pipeline.calls,
            0,
            (
                "Unsupported upload must "
                "not reach pipeline."
            ),
        )


        print(
            "[PASS] Unsupported content "
            "type rejected before pipeline"
        )


        # ==================================================
        # TEST 2 — EMPTY UPLOAD
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 2 — EMPTY UPLOAD"
        )
        print("-" * 76)


        response = (
            client.post(
                "/api/v1/documents/analyze",

                files={
                    "file": (
                        "empty.jpg",
                        b"",
                        "image/jpeg",
                    )
                },
            )
        )


        assert_error(
            response,

            status_code=400,

            code=(
                "EMPTY_UPLOAD"
            ),
        )


        assert_equal(
            pipeline.calls,
            0,
            (
                "Empty upload must not "
                "reach pipeline."
            ),
        )


        print(
            "[PASS] Empty upload rejected"
        )


        # ==================================================
        # TEST 3 — OVERSIZED UPLOAD
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 3 — OVERSIZED UPLOAD"
        )
        print("-" * 76)


        api_main.MAX_UPLOAD_BYTES = (
            8
        )


        response = (
            client.post(
                "/api/v1/documents/analyze",

                files={
                    "file": (
                        "large.jpg",
                        b"123456789",
                        "image/jpeg",
                    )
                },
            )
        )


        assert_error(
            response,

            status_code=413,

            code=(
                "UPLOAD_TOO_LARGE"
            ),
        )


        assert_equal(
            response.json()[
                "error"
            ][
                "details"
            ][
                "maximum_bytes"
            ],
            8,
            (
                "Upload size limit should "
                "be exposed safely."
            ),
        )


        assert_equal(
            pipeline.calls,
            0,
            (
                "Oversized upload must not "
                "reach pipeline."
            ),
        )


        print(
            "[PASS] Actual upload bytes "
            "enforced against hard limit"
        )


        # Restore normal test size.

        api_main.MAX_UPLOAD_BYTES = (
            original_max_upload_bytes
        )


        # ==================================================
        # TEST 4 — OVERLONG FILENAME
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 4 — OVERLONG FILENAME"
        )
        print("-" * 76)


        long_filename = (
            ("a" * 252)
            + ".jpg"
        )


        assert_true(
            len(
                long_filename
            )
            > 255,
            (
                "Test filename should exceed "
                "database length."
            ),
        )


        response = (
            client.post(
                "/api/v1/documents/analyze",

                files={
                    "file": (
                        long_filename,
                        b"image-data",
                        "image/jpeg",
                    )
                },
            )
        )


        assert_error(
            response,

            status_code=400,

            code=(
                "UPLOAD_FILENAME_TOO_LONG"
            ),
        )


        print(
            "[PASS] Overlong filename "
            "blocked before persistence"
        )


        # ==================================================
        # TEST 5 — CLIENT PATH NORMALIZATION
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 5 — CLIENT FILENAME "
            "PATH NORMALIZATION"
        )
        print("-" * 76)


        assert_equal(
            normalize_upload_filename(
                (
                    r"C:\fakepath"
                    r"\guard_badge.jpg"
                )
            ),
            "guard_badge.jpg",
            (
                "Windows client path should "
                "be reduced to basename."
            ),
        )


        assert_equal(
            normalize_upload_filename(
                "/tmp/guard_badge.jpg"
            ),
            "guard_badge.jpg",
            (
                "POSIX client path should "
                "be reduced to basename."
            ),
        )


        print(
            "[PASS] Client path components "
            "removed from filename metadata"
        )


        # ==================================================
        # TEST 6 — VALID UPLOAD STILL WORKS
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 6 — VALID UPLOAD "
            "CONTROL"
        )
        print("-" * 76)


        valid_bytes = (
            b"VIGILOX-VALID-UPLOAD"
        )


        response = (
            client.post(
                "/api/v1/documents/analyze",

                files={
                    "file": (
                        "guard_badge.jpg",
                        valid_bytes,
                        "image/jpeg",
                    )
                },
            )
        )


        assert_equal(
            response.status_code,
            200,
            (
                "Valid upload should "
                "still return HTTP 200."
            ),
        )


        assert_equal(
            pipeline.calls,
            1,
            (
                "Valid upload should reach "
                "pipeline exactly once."
            ),
        )


        assert_equal(
            pipeline.received_bytes,
            valid_bytes,
            (
                "Pipeline received different "
                "upload bytes."
            ),
        )


        assert_equal(
            persistence.calls,
            1,
            (
                "Valid upload should reach "
                "persistence exactly once."
            ),
        )


        assert_equal(
            persistence.original_filename,
            "guard_badge.jpg",
            (
                "Persistence received "
                "incorrect filename."
            ),
        )


        assert_equal(
            persistence.content_type,
            "image/jpeg",
            (
                "Persistence received "
                "incorrect content type."
            ),
        )


        assert_true(
            pipeline.received_path
            is not None,
            (
                "Pipeline temp path missing."
            ),
        )


        assert_false(
            Path(
                pipeline.received_path
            ).exists(),
            (
                "Temporary upload should "
                "be removed after request."
            ),
        )


        assert_equal(
            response.json()[
                "filename"
            ],
            "guard_badge.jpg",
            (
                "API response should expose "
                "normalized filename."
            ),
        )


        print(
            "[PASS] Valid upload still "
            "reaches pipeline and persistence"
        )

        print(
            "[PASS] Temporary upload cleaned "
            "after successful request"
        )


        # ==================================================
        # TEST 7 — MISSING MULTIPART FILE
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 7 — MISSING FILE "
            "VALIDATION"
        )
        print("-" * 76)


        response = (
            client.post(
                "/api/v1/documents/analyze"
            )
        )


        assert_error(
            response,

            status_code=422,

            code=(
                "REQUEST_VALIDATION_ERROR"
            ),
        )


        print(
            "[PASS] Missing multipart file "
            "uses central validation contract"
        )


        # ==================================================
        # FINAL
        # ==================================================

        print()
        print("=" * 76)
        print(
            "[PASS] PHASE 7C.7b REQUEST / "
            "VALIDATION HARDENING TEST PASSED"
        )
        print("=" * 76)


    finally:

        api_main.MAX_UPLOAD_BYTES = (
            original_max_upload_bytes
        )


        if client is not None:

            client.close()


        if original_pipeline is not None:

            app.state.pipeline = (
                original_pipeline
            )

        elif hasattr(
            app.state,
            "pipeline",
        ):

            delattr(
                app.state,
                "pipeline",
            )


        if original_persistence is not None:

            app.state.persistence = (
                original_persistence
            )

        elif hasattr(
            app.state,
            "persistence",
        ):

            delattr(
                app.state,
                "persistence",
            )


        print()
        print(
            "[CLEANUP] Phase 7C.7b "
            "temporary API state removed."
        )


if __name__ == "__main__":

    main()