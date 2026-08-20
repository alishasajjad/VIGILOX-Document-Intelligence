import io
import json
import logging

from pathlib import Path
from tempfile import (
    TemporaryDirectory,
)

from fastapi.testclient import (
    TestClient,
)

from backend.app.main import (
    app,
)

from backend.app.api.request_context import (
    REQUEST_ID_HEADER,
)

from backend.app.core.logging import (
    LOGGER_ROOT_NAME,
    StructuredJSONFormatter,
)

from backend.app.services.readiness_service import (
    REASON_DATABASE_UNAVAILABLE,
    REASON_SERVICE_NOT_INITIALIZED,
    REASON_STORAGE_ROOT_MISSING,
    REASON_STORAGE_ROOT_NOT_WRITABLE,
    REASON_STORAGE_ROOT_UNSAFE,
    ReadinessCheckFailed,
    ReadinessService,
    check_application_services,
    check_storage,
    ok_result,
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
# STRUCTURED LOG CAPTURE
# ==========================================================

class StructuredLogCapture:

    def __init__(
        self,
    ):

        self.stream = (
            io.StringIO()
        )


        self.handler = (
            logging.StreamHandler(
                self.stream
            )
        )


        self.handler.setFormatter(
            StructuredJSONFormatter()
        )


        self.root_logger = (
            logging.getLogger(
                LOGGER_ROOT_NAME
            )
        )


        self.previous_level = (
            self.root_logger.level
        )


    def __enter__(
        self,
    ):

        self.root_logger.addHandler(
            self.handler
        )


        self.root_logger.setLevel(
            logging.DEBUG
        )


        return self


    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ):

        self.root_logger.removeHandler(
            self.handler
        )


        self.root_logger.setLevel(
            self.previous_level
        )


        return False


    def records(
        self,
    ) -> list[dict]:

        parsed = []


        for line in (
            self.stream
            .getvalue()
            .splitlines()
        ):

            stripped = (
                line.strip()
            )


            if stripped:

                parsed.append(
                    json.loads(
                        stripped
                    )
                )


        return parsed


    def find_event(
        self,
        event: str,
    ) -> dict | None:

        for record in (
            self.records()
        ):

            if (
                record.get(
                    "event"
                )
                == event
            ):

                return record


        return None


# ==========================================================
# TEST DOUBLES
# ==========================================================

PRIVATE_DATABASE_SECRET = (
    "postgresql://vigilox:"
    "SUPER_SECRET_PASSWORD@"
    "db.internal:5432/vigilox"
)


class FakeDatabaseError(
    RuntimeError
):
    pass


def failing_database_check(
    app_state=None,
):
    """
    Emulates a real SQLAlchemy connectivity failure.

    SQLAlchemy operational errors routinely embed the full
    database URL, including the password, in their message.

    This double reproduces that hazard so the test can prove
    the readiness response never exposes it.
    """

    raise ReadinessCheckFailed(
        reason=(
            REASON_DATABASE_UNAVAILABLE
        ),

        exc=(
            FakeDatabaseError(
                "could not connect to "
                f"{PRIVATE_DATABASE_SECRET}"
            )
        ),
    )


def passing_database_check(
    app_state=None,
):

    return ok_result()


class InferenceForbiddenPipeline:
    """
    Stands in for the OCR + LLM pipeline.

    Any attempt to run inference during a readiness check is
    an immediate failure.
    """

    def __init__(
        self,
    ):

        self.inference_calls = []


    def process(
        self,
        *args,
        **kwargs,
    ):

        self.inference_calls.append(
            "process"
        )


        raise AssertionError(
            "Readiness must never run the "
            "OCR / LLM pipeline."
        )


    def run_ocr(
        self,
        *args,
        **kwargs,
    ):

        self.inference_calls.append(
            "run_ocr"
        )


        raise AssertionError(
            "Readiness must never run OCR "
            "inference."
        )


    def extract(
        self,
        *args,
        **kwargs,
    ):

        self.inference_calls.append(
            "extract"
        )


        raise AssertionError(
            "Readiness must never run LLM "
            "extraction."
        )


class FakeStorageService:

    def __init__(
        self,
        storage_root,
    ):

        self.storage_root = (
            storage_root
        )


class FakePersistenceService:

    def __init__(
        self,
        storage_root,
    ):

        self.storage_service = (
            FakeStorageService(
                storage_root
            )
        )


# ==========================================================
# APPLICATION STATE SNAPSHOT
# ==========================================================

MANAGED_STATE_ATTRIBUTES = (
    "readiness",
    "persistence",
    "pipeline",
    "document_query",
    "human_review",
    "reviewer_identity",
)


def snapshot_app_state() -> dict:

    return {
        attribute_name:
            getattr(
                app.state,
                attribute_name,
                None,
            )
        for attribute_name in (
            MANAGED_STATE_ATTRIBUTES
        )
    }


def restore_app_state(
    snapshot: dict,
) -> None:

    for (
        attribute_name,
        original_value,
    ) in snapshot.items():

        if original_value is not None:

            setattr(
                app.state,
                attribute_name,
                original_value,
            )


        elif hasattr(
            app.state,
            attribute_name,
        ):

            delattr(
                app.state,
                attribute_name,
            )


# ==========================================================
# READINESS RESPONSE HELPERS
# ==========================================================

def assert_no_secret_leak(
    response,
    context: str,
):

    serialized = (
        json.dumps(
            response.json()
        )
    )


    for forbidden in (
        PRIVATE_DATABASE_SECRET,
        "SUPER_SECRET_PASSWORD",
        "Traceback",
        "postgresql://",
    ):

        assert_true(
            forbidden
            not in serialized,
            (
                f"{context} "
                "leaked private information "
                f"into the response: "
                f"{forbidden}"
            ),
        )


def assert_not_ready(
    response,
    *,
    failing_check: str,
    expected_reason: str,
):

    assert_equal(
        response.status_code,
        503,
        (
            "A failing dependency must "
            "return HTTP 503."
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
            "Readiness failure should use "
            "the central error contract."
        ),
    )


    error = (
        body[
            "error"
        ]
    )


    assert_equal(
        error[
            "code"
        ],
        "SERVICE_NOT_READY",
        (
            "Readiness failure should use "
            "the stable SERVICE_NOT_READY "
            "code."
        ),
    )


    checks = (
        error[
            "details"
        ][
            "checks"
        ]
    )


    assert_equal(
        checks[
            failing_check
        ][
            "status"
        ],
        "error",
        (
            "The failing dependency should "
            f"be reported: {failing_check}"
        ),
    )


    assert_equal(
        checks[
            failing_check
        ][
            "reason"
        ],
        expected_reason,
        (
            "Readiness failure should expose "
            "a stable reason code."
        ),
    )


# ==========================================================
# TEST 0 — REAL DEPENDENCY READINESS
# ==========================================================

def test_real_dependency_readiness(
    client,
):

    print()
    print("-" * 76)
    print(
        "TEST 0 - REAL DEPENDENCY "
        "READINESS"
    )
    print("-" * 76)


    # ======================================================
    # No test doubles are installed here.
    #
    # This exercises the real readiness service against:
    #
    #     real PostgreSQL connectivity
    #     the real managed storage root
    #     the real initialized application services
    #
    # A failure here means either a genuine code regression
    # or an external dependency being unavailable. The
    # reported reason code distinguishes the two.
    # ======================================================

    response = (
        client.get(
            "/health/ready"
        )
    )


    if (
        response.status_code
        != 200
    ):

        raise AssertionError(
            "Real dependency readiness "
            "failed.\n"
            "Inspect the reason codes below "
            "to distinguish a code "
            "regression from an external "
            "dependency outage.\n"
            f"Status: {response.status_code}\n"
            f"Checks: "
            f"{response.json().get('error', {}).get('details')}"
        )


    body = (
        response.json()
    )


    assert_equal(
        body[
            "status"
        ],
        "ready",
        (
            "Real readiness should report "
            "status=ready."
        ),
    )


    for check_name in (
        "database",
        "storage",
        "services",
    ):

        assert_equal(
            body[
                "checks"
            ][
                check_name
            ][
                "status"
            ],
            "ok",
            (
                "Real dependency check should "
                f"report ok: {check_name}"
            ),
        )


    print(
        "[PASS] Real PostgreSQL readiness "
        "check succeeds"
    )

    print(
        "[PASS] Real managed storage "
        "readiness check succeeds"
    )

    print(
        "[PASS] Real application services "
        "readiness check succeeds"
    )


# ==========================================================
# TEST 1 — LIVENESS STAYS LIGHTWEIGHT
# ==========================================================

def test_health_remains_lightweight(
    client,
):

    print()
    print("-" * 76)
    print(
        "TEST 1 - LIVENESS REMAINS "
        "LIGHTWEIGHT"
    )
    print("-" * 76)


    response = (
        client.get(
            "/health"
        )
    )


    assert_equal(
        response.status_code,
        200,
        (
            "Liveness should return HTTP 200."
        ),
    )


    assert_equal(
        response.json(),
        {
            "status":
                "ok",

            "service":
                "vigilox-document-intelligence",

            "version":
                "0.1.0",
        },
        (
            "Existing lightweight liveness "
            "payload must not change."
        ),
    )


    print(
        "[PASS] /health unchanged and "
        "HTTP 200"
    )


    # ======================================================
    # LIVENESS MUST NOT DEPEND ON READINESS
    # ======================================================

    snapshot = (
        snapshot_app_state()
    )


    try:

        # Break every dependency the readiness endpoint
        # cares about.

        app.state.readiness = (
            ReadinessService(
                database_check=(
                    failing_database_check
                )
            )
        )


        if hasattr(
            app.state,
            "persistence",
        ):

            delattr(
                app.state,
                "persistence",
            )


        response = (
            client.get(
                "/health"
            )
        )


        assert_equal(
            response.status_code,
            200,
            (
                "Liveness must stay HTTP 200 "
                "even when dependencies are "
                "unavailable."
            ),
        )


        print(
            "[PASS] /health stays 200 while "
            "dependencies are broken"
        )


    finally:

        restore_app_state(
            snapshot
        )


# ==========================================================
# TEST 2 — READY
# ==========================================================

def test_readiness_ready(
    client,
):

    print()
    print("-" * 76)
    print(
        "TEST 2 - READINESS WITH HEALTHY "
        "DEPENDENCIES"
    )
    print("-" * 76)


    snapshot = (
        snapshot_app_state()
    )


    with TemporaryDirectory() as temporary_root:

        try:

            storage_root = (
                Path(
                    temporary_root
                )
            )


            app.state.persistence = (
                FakePersistenceService(
                    storage_root
                )
            )


            # ==========================================
            # REAL STORAGE AND SERVICE CHECKS
            # ==========================================
            #
            # Only the database check is substituted, so
            # this test stays deterministic without a live
            # PostgreSQL instance while still exercising
            # the real storage and service checks.
            # ==========================================

            app.state.readiness = (
                ReadinessService(
                    database_check=(
                        passing_database_check
                    )
                )
            )


            response = (
                client.get(
                    "/health/ready"
                )
            )


            assert_equal(
                response.status_code,
                200,
                (
                    "Healthy dependencies "
                    "should return HTTP 200."
                ),
            )


            body = (
                response.json()
            )


            assert_equal(
                body[
                    "status"
                ],
                "ready",
                (
                    "Readiness payload should "
                    "report status=ready."
                ),
            )


            assert_equal(
                body[
                    "service"
                ],
                "vigilox-document-intelligence",
                (
                    "Readiness payload should "
                    "identify the service."
                ),
            )


            for check_name in (
                "database",
                "storage",
                "services",
            ):

                assert_equal(
                    body[
                        "checks"
                    ][
                        check_name
                    ][
                        "status"
                    ],
                    "ok",
                    (
                        "Healthy check should "
                        "report ok: "
                        f"{check_name}"
                    ),
                )


            print(
                "[PASS] Readiness returns 200 "
                "with healthy dependencies"
            )


            # ==========================================
            # REQUEST ID PRESENT
            # ==========================================

            assert_true(
                response.headers.get(
                    REQUEST_ID_HEADER
                )
                is not None,
                (
                    "Readiness response should "
                    "carry a correlation ID "
                    "header."
                ),
            )


            print(
                "[PASS] Readiness response "
                "carries a request ID"
            )


        finally:

            restore_app_state(
                snapshot
            )


# ==========================================================
# TEST 3 — DATABASE FAILURE
# ==========================================================

def test_database_failure(
    client,
):

    print()
    print("-" * 76)
    print(
        "TEST 3 - DATABASE READINESS "
        "FAILURE"
    )
    print("-" * 76)


    snapshot = (
        snapshot_app_state()
    )


    with TemporaryDirectory() as temporary_root:

        try:

            app.state.persistence = (
                FakePersistenceService(
                    Path(
                        temporary_root
                    )
                )
            )


            app.state.readiness = (
                ReadinessService(
                    database_check=(
                        failing_database_check
                    )
                )
            )


            with StructuredLogCapture() as capture:

                response = (
                    client.get(
                        "/health/ready"
                    )
                )


                dependency_log = (
                    capture.find_event(
                        "readiness_dependency"
                        "_failed"
                    )
                )


                summary_log = (
                    capture.find_event(
                        "readiness_check_failed"
                    )
                )


            assert_not_ready(
                response,

                failing_check=(
                    "database"
                ),

                expected_reason=(
                    REASON_DATABASE_UNAVAILABLE
                ),
            )


            print(
                "[PASS] Database failure "
                "returns HTTP 503"
            )


            # ==========================================
            # NO SECRET LEAK
            # ==========================================

            assert_no_secret_leak(
                response,
                "Database readiness failure",
            )


            checks = (
                response.json()[
                    "error"
                ][
                    "details"
                ][
                    "checks"
                ]
            )


            assert_equal(
                checks[
                    "database"
                ][
                    "error_type"
                ],
                "FakeDatabaseError",
                (
                    "Only the exception class "
                    "name should be exposed."
                ),
            )


            print(
                "[PASS] Private exception "
                "details not exposed"
            )


            # ==========================================
            # STRUCTURED LOGGING
            # ==========================================

            assert_true(
                dependency_log is not None,
                (
                    "A failing dependency should "
                    "emit a structured "
                    "readiness_dependency_failed "
                    "event."
                ),
            )


            assert_true(
                summary_log is not None,
                (
                    "A failed readiness check "
                    "should emit a structured "
                    "readiness_check_failed "
                    "event."
                ),
            )


            header_request_id = (
                response.headers.get(
                    REQUEST_ID_HEADER
                )
            )


            assert_true(
                header_request_id is not None,
                (
                    "Readiness failure should "
                    "still return a correlation "
                    "ID header."
                ),
            )


            assert_equal(
                response.json()[
                    "error"
                ][
                    "request_id"
                ],
                header_request_id,
                (
                    "Readiness failure payload "
                    "and header must share the "
                    "request ID."
                ),
            )


            print(
                "[PASS] Readiness failure "
                "exposes a request ID"
            )


            assert_equal(
                dependency_log[
                    "request_id"
                ],
                header_request_id,
                (
                    "Readiness dependency log "
                    "must share the response "
                    "request ID."
                ),
            )


            assert_equal(
                summary_log[
                    "request_id"
                ],
                header_request_id,
                (
                    "Readiness summary log must "
                    "share the response request "
                    "ID."
                ),
            )


            print(
                "[PASS] Readiness failure log "
                "shares the same request ID"
            )


            # ==========================================
            # SERVER-SIDE TRACE IS RETAINED
            # ==========================================

            assert_true(
                PRIVATE_DATABASE_SECRET
                in dependency_log[
                    "exception"
                ],
                (
                    "The server-side log should "
                    "retain the real failure "
                    "detail for operators."
                ),
            )


            print(
                "[PASS] Real failure detail kept "
                "server-side only"
            )


        finally:

            restore_app_state(
                snapshot
            )


# ==========================================================
# TEST 4 — STORAGE FAILURE
# ==========================================================

def test_storage_failure(
    client,
):

    print()
    print("-" * 76)
    print(
        "TEST 4 - STORAGE READINESS "
        "FAILURE"
    )
    print("-" * 76)


    snapshot = (
        snapshot_app_state()
    )


    with TemporaryDirectory() as temporary_root:

        try:

            # ==========================================
            # MISSING STORAGE ROOT
            # ==========================================
            #
            # An isolated temporary directory is used so no
            # real document storage is ever touched.
            # ==========================================

            missing_root = (
                Path(
                    temporary_root
                )
                / "does-not-exist"
            )


            app.state.persistence = (
                FakePersistenceService(
                    missing_root
                )
            )


            app.state.readiness = (
                ReadinessService(
                    database_check=(
                        passing_database_check
                    )
                )
            )


            response = (
                client.get(
                    "/health/ready"
                )
            )


            assert_not_ready(
                response,

                failing_check=(
                    "storage"
                ),

                expected_reason=(
                    REASON_STORAGE_ROOT_MISSING
                ),
            )


            print(
                "[PASS] Missing storage root "
                "returns HTTP 503"
            )


            # ==========================================
            # SAFE INFORMATION ONLY
            # ==========================================

            serialized = (
                json.dumps(
                    response.json()
                )
            )


            assert_true(
                str(
                    missing_root
                )
                not in serialized,
                (
                    "Readiness must not expose "
                    "filesystem paths."
                ),
            )


            print(
                "[PASS] Filesystem paths not "
                "exposed"
            )


        finally:

            restore_app_state(
                snapshot
            )


# ==========================================================
# TEST 5 — MISSING APPLICATION SERVICE
# ==========================================================

def test_missing_application_service(
    client,
):

    print()
    print("-" * 76)
    print(
        "TEST 5 - MISSING REQUIRED "
        "APPLICATION SERVICE"
    )
    print("-" * 76)


    snapshot = (
        snapshot_app_state()
    )


    with TemporaryDirectory() as temporary_root:

        try:

            app.state.persistence = (
                FakePersistenceService(
                    Path(
                        temporary_root
                    )
                )
            )


            app.state.readiness = (
                ReadinessService(
                    database_check=(
                        passing_database_check
                    )
                )
            )


            # ==========================================
            # REMOVE A REQUIRED SERVICE
            # ==========================================

            if hasattr(
                app.state,
                "human_review",
            ):

                delattr(
                    app.state,
                    "human_review",
                )


            response = (
                client.get(
                    "/health/ready"
                )
            )


            assert_not_ready(
                response,

                failing_check=(
                    "services"
                ),

                expected_reason=(
                    REASON_SERVICE_NOT_INITIALIZED
                ),
            )


            print(
                "[PASS] Missing required service "
                "returns HTTP 503"
            )


        finally:

            restore_app_state(
                snapshot
            )


# ==========================================================
# TEST 6 — NO OCR / LLM INFERENCE
# ==========================================================

def test_readiness_runs_no_inference(
    client,
):

    print()
    print("-" * 76)
    print(
        "TEST 6 - READINESS RUNS NO "
        "OCR / LLM INFERENCE"
    )
    print("-" * 76)


    snapshot = (
        snapshot_app_state()
    )


    with TemporaryDirectory() as temporary_root:

        try:

            forbidden_pipeline = (
                InferenceForbiddenPipeline()
            )


            app.state.pipeline = (
                forbidden_pipeline
            )


            app.state.persistence = (
                FakePersistenceService(
                    Path(
                        temporary_root
                    )
                )
            )


            app.state.readiness = (
                ReadinessService(
                    database_check=(
                        passing_database_check
                    )
                )
            )


            response = (
                client.get(
                    "/health/ready"
                )
            )


            assert_equal(
                response.status_code,
                200,
                (
                    "Readiness should succeed "
                    "without running any "
                    "inference."
                ),
            )


            assert_equal(
                forbidden_pipeline
                .inference_calls,
                [],
                (
                    "Readiness invoked OCR / LLM "
                    "inference. It must only "
                    "verify service "
                    "initialization."
                ),
            )


            print(
                "[PASS] Readiness performed no "
                "OCR / LLM inference"
            )


            # ==========================================
            # REPEATED PROBES STAY CHEAP
            # ==========================================

            for _ in range(
                10
            ):

                client.get(
                    "/health/ready"
                )


            assert_equal(
                forbidden_pipeline
                .inference_calls,
                [],
                (
                    "Repeated readiness probes "
                    "must never trigger "
                    "inference."
                ),
            )


            print(
                "[PASS] Repeated probes remain "
                "inference-free"
            )


        finally:

            restore_app_state(
                snapshot
            )


# ==========================================================
# TEST 7 — STORAGE SAFETY INVARIANTS
# ==========================================================

def test_storage_safety_invariants():

    print()
    print("-" * 76)
    print(
        "TEST 7 - STORAGE SAFETY "
        "INVARIANTS PRESERVED"
    )
    print("-" * 76)


    class StateStub:

        def __init__(
            self,
            storage_root,
        ):

            self.persistence = (
                FakePersistenceService(
                    storage_root
                )
            )


    with TemporaryDirectory() as temporary_root:

        root = (
            Path(
                temporary_root
            )
        )


        # ==============================================
        # HEALTHY ROOT
        # ==============================================

        healthy_root = (
            root
            / "healthy"
        )


        healthy_root.mkdir()


        assert_equal(
            check_storage(
                StateStub(
                    healthy_root
                )
            ),
            ok_result(),
            (
                "A healthy managed storage "
                "root should pass."
            ),
        )


        print(
            "[PASS] Healthy storage root "
            "passes"
        )


        # ==============================================
        # NON-MUTATING
        # ==============================================
        #
        # Readiness must never create probe files inside
        # managed document storage.
        # ==============================================

        contents_before = (
            sorted(
                entry.name
                for entry in (
                    healthy_root.iterdir()
                )
            )
        )


        for _ in range(
            5
        ):

            check_storage(
                StateStub(
                    healthy_root
                )
            )


        contents_after = (
            sorted(
                entry.name
                for entry in (
                    healthy_root.iterdir()
                )
            )
        )


        assert_equal(
            contents_after,
            contents_before,
            (
                "Readiness must not mutate "
                "managed storage state."
            ),
        )


        assert_equal(
            contents_after,
            [],
            (
                "Readiness left files behind "
                "in managed storage."
            ),
        )


        print(
            "[PASS] Readiness does not mutate "
            "storage state"
        )


        # ==============================================
        # FILE INSTEAD OF DIRECTORY
        # ==============================================

        file_root = (
            root
            / "not-a-directory"
        )


        file_root.write_text(
            "x",
            encoding="utf-8",
        )


        try:

            check_storage(
                StateStub(
                    file_root
                )
            )


            raise AssertionError(
                "A non-directory storage root "
                "should fail readiness."
            )


        except ReadinessCheckFailed as exc:

            assert_true(
                exc.reason
                in (
                    "STORAGE_ROOT_NOT_DIRECTORY",
                    REASON_STORAGE_ROOT_NOT_WRITABLE,
                ),
                (
                    "Unexpected reason for a "
                    "non-directory storage root: "
                    f"{exc.reason}"
                ),
            )


        print(
            "[PASS] Non-directory storage root "
            "rejected"
        )


        # ==============================================
        # SYMLINKED ROOT
        # ==============================================

        symlink_root = (
            root
            / "symlinked"
        )


        symlink_created = False


        try:

            symlink_root.symlink_to(
                healthy_root,
                target_is_directory=True,
            )


            symlink_created = True


        except (
            OSError,
            NotImplementedError,
        ):

            # Creating symlinks on Windows requires
            # elevated privileges or developer mode.

            print(
                "[SKIP] Symlink creation not "
                "permitted in this environment"
            )


        if symlink_created:

            try:

                check_storage(
                    StateStub(
                        symlink_root
                    )
                )


                raise AssertionError(
                    "A symlinked managed storage "
                    "root must fail readiness."
                )


            except ReadinessCheckFailed as exc:

                assert_equal(
                    exc.reason,
                    REASON_STORAGE_ROOT_UNSAFE,
                    (
                        "A symlinked storage root "
                        "should be reported as "
                        "unsafe."
                    ),
                )


            print(
                "[PASS] Symlinked storage root "
                "rejected"
            )


        # ==============================================
        # UNRESOLVED STORAGE ROOT
        # ==============================================

        class EmptyState:
            pass


        try:

            check_storage(
                EmptyState()
            )


            raise AssertionError(
                "An unresolvable storage root "
                "should fail readiness."
            )


        except ReadinessCheckFailed as exc:

            assert_equal(
                exc.reason,
                "STORAGE_ROOT_UNRESOLVED",
                (
                    "Unresolvable storage root "
                    "should report a stable "
                    "reason."
                ),
            )


        print(
            "[PASS] Unresolvable storage root "
            "rejected"
        )


        # ==============================================
        # SERVICE CHECK DOES NOT CALL SERVICES
        # ==============================================

        class ServiceState:

            def __init__(
                self,
            ):

                self.pipeline = (
                    InferenceForbiddenPipeline()
                )

                self.persistence = (
                    object()
                )

                self.document_query = (
                    object()
                )

                self.human_review = (
                    object()
                )

                self.reviewer_identity = (
                    object()
                )


        service_state = (
            ServiceState()
        )


        assert_equal(
            check_application_services(
                service_state
            ),
            ok_result(),
            (
                "Initialized services should "
                "pass the service check."
            ),
        )


        assert_equal(
            service_state
            .pipeline
            .inference_calls,
            [],
            (
                "The service check must not "
                "invoke the pipeline."
            ),
        )


        print(
            "[PASS] Service check performs no "
            "inference"
        )


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("=" * 76)
    print(
        "PHASE 7C.7f - HEALTH / READINESS "
        "HARDENING TEST"
    )
    print("=" * 76)


    outer_snapshot = None


    # ======================================================
    # REAL APPLICATION LIFESPAN
    # ======================================================
    #
    # TestClient must be used as a context manager so the
    # FastAPI lifespan actually runs.
    #
    # Without it, app.state is never populated and every
    # readiness probe would trivially fail with
    # SERVICE_NOT_INITIALIZED, which would not test anything
    # meaningful.
    #
    # Running the real lifespan also keeps the real
    # PostgreSQL and real managed-storage integration in the
    # test path.
    # ======================================================

    with TestClient(
        app,
        raise_server_exceptions=False,
    ) as client:

        outer_snapshot = (
            snapshot_app_state()
        )


        test_real_dependency_readiness(
            client
        )

        test_health_remains_lightweight(
            client
        )


        try:

            test_readiness_ready(
                client
            )

            test_database_failure(
                client
            )

            test_storage_failure(
                client
            )

            test_missing_application_service(
                client
            )

            test_readiness_runs_no_inference(
                client
            )

            test_storage_safety_invariants()


            print()
            print("=" * 76)
            print(
                "[PASS] PHASE 7C.7f HEALTH / "
                "READINESS HARDENING TEST "
                "PASSED"
            )
            print("=" * 76)


        finally:

            restore_app_state(
                outer_snapshot
            )


            print()
            print(
                "[CLEANUP] Phase 7C.7f "
                "temporary API state removed."
            )


if __name__ == "__main__":

    main()
