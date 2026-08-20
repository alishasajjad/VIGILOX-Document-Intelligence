import os

from pathlib import Path

from sqlalchemy import text

from database.database import (
    engine,
)


# ==========================================================
# READINESS SERVICE
# PHASE 7C.7f
# ==========================================================
#
# LIVENESS vs READINESS
# ----------------------------------------------------------
#
# GET /health
#
#     Process liveness only.
#
#     Deliberately dependency-free so an orchestrator never
#     restarts a healthy process just because PostgreSQL is
#     briefly unreachable.
#
#
# GET /health/ready
#
#     Dependency-aware readiness.
#
#     Answers a different question:
#
#         "can this process actually serve the document
#          workflows right now?"
#
#
# COST BOUNDARY
# ----------------------------------------------------------
#
# Readiness must be fast and deterministic.
#
# It therefore NEVER runs:
#
#     PaddleOCR inference
#     Groq / LLM inference
#
# External OCR and LLM availability is represented through
# application-service initialization, because the pipeline
# service constructs its OCR and extraction clients during
# application startup.
#
#
# INFORMATION BOUNDARY
# ----------------------------------------------------------
#
# A failed check reports only:
#
#     a stable reason code
#     the exception class name
#
# It never reports str(exception).
#
# SQLAlchemy connection errors routinely embed the full
# database URL, including the password, in their message.
# Those must never reach an HTTP response or a log field.
# ==========================================================

CHECK_OK = (
    "ok"
)


CHECK_ERROR = (
    "error"
)


# ==========================================================
# STABLE READINESS REASON CODES
# ==========================================================

REASON_DATABASE_UNAVAILABLE = (
    "DATABASE_UNAVAILABLE"
)


REASON_STORAGE_ROOT_MISSING = (
    "STORAGE_ROOT_MISSING"
)


REASON_STORAGE_ROOT_NOT_DIRECTORY = (
    "STORAGE_ROOT_NOT_DIRECTORY"
)


REASON_STORAGE_ROOT_UNSAFE = (
    "STORAGE_ROOT_UNSAFE"
)


REASON_STORAGE_ROOT_NOT_WRITABLE = (
    "STORAGE_ROOT_NOT_WRITABLE"
)


REASON_STORAGE_ROOT_UNRESOLVED = (
    "STORAGE_ROOT_UNRESOLVED"
)


REASON_SERVICE_NOT_INITIALIZED = (
    "SERVICE_NOT_INITIALIZED"
)


REASON_CHECK_FAILED = (
    "CHECK_FAILED"
)


# ==========================================================
# REQUIRED APPLICATION SERVICES
# ==========================================================
#
# These are populated by the FastAPI lifespan handler.
#
# "pipeline" transitively represents OCR and LLM client
# initialization without performing any inference.
# ==========================================================

REQUIRED_APPLICATION_SERVICES = (
    "pipeline",
    "persistence",
    "document_query",
    "human_review",
    "reviewer_identity",
)


# ==========================================================
# CHECK RESULT HELPERS
# ==========================================================

def ok_result() -> dict:

    return {
        "status":
            CHECK_OK,
    }


def error_result(
    *,
    reason: str,
    error_type: str | None = None,
) -> dict:

    result = {
        "status":
            CHECK_ERROR,

        "reason":
            reason,
    }


    if error_type:

        result[
            "error_type"
        ] = error_type


    return result


# ==========================================================
# DATABASE CHECK
# ==========================================================

def check_database(
    app_state=None,
) -> dict:

    # ======================================================
    # The engine is configured with pool_pre_ping=True, so
    # a single trivial round trip is enough to prove real
    # PostgreSQL connectivity.
    # ======================================================

    try:

        with engine.connect() as connection:

            connection.execute(
                text(
                    "SELECT 1"
                )
            )


        return ok_result()


    except Exception as exc:

        # ==================================================
        # SECURITY RULE
        # ==================================================
        #
        # str(exc) may contain the database URL and
        # password. Only the exception class name is safe
        # to surface.
        # ==================================================

        raise ReadinessCheckFailed(
            reason=(
                REASON_DATABASE_UNAVAILABLE
            ),

            exc=exc,
        ) from exc


# ==========================================================
# STORAGE CHECK
# ==========================================================

def check_storage(
    app_state=None,
) -> dict:

    storage_root = (
        resolve_storage_root(
            app_state
        )
    )


    if storage_root is None:

        raise ReadinessCheckFailed(
            reason=(
                REASON_STORAGE_ROOT_UNRESOLVED
            ),
        )


    # ======================================================
    # SYMLINK SAFETY
    # ======================================================
    #
    # Phase 7C.6a established that a symlinked managed
    # storage root is never acceptable.
    #
    # Readiness reuses that invariant instead of relaxing
    # it.
    # ======================================================

    if storage_root.is_symlink():

        raise ReadinessCheckFailed(
            reason=(
                REASON_STORAGE_ROOT_UNSAFE
            ),
        )


    if not storage_root.exists():

        raise ReadinessCheckFailed(
            reason=(
                REASON_STORAGE_ROOT_MISSING
            ),
        )


    if not storage_root.is_dir():

        raise ReadinessCheckFailed(
            reason=(
                REASON_STORAGE_ROOT_NOT_DIRECTORY
            ),
        )


    # ======================================================
    # NON-MUTATING WRITABILITY CHECK
    # ======================================================
    #
    # Readiness deliberately does NOT create probe files
    # inside managed document storage.
    #
    # A readiness endpoint must never mutate production
    # storage state.
    # ======================================================

    if not os.access(
        storage_root,
        os.W_OK,
    ):

        raise ReadinessCheckFailed(
            reason=(
                REASON_STORAGE_ROOT_NOT_WRITABLE
            ),
        )


    return ok_result()


# ==========================================================
# RESOLVE MANAGED STORAGE ROOT
# ==========================================================

def resolve_storage_root(
    app_state,
) -> Path | None:

    persistence_service = (
        getattr(
            app_state,
            "persistence",
            None,
        )
    )


    if persistence_service is None:

        return None


    storage_service = (
        getattr(
            persistence_service,
            "storage_service",
            None,
        )
    )


    if storage_service is None:

        return None


    storage_root = (
        getattr(
            storage_service,
            "storage_root",
            None,
        )
    )


    if storage_root is None:

        return None


    return Path(
        storage_root
    )


# ==========================================================
# APPLICATION SERVICES CHECK
# ==========================================================

def check_application_services(
    app_state=None,
) -> dict:

    # ======================================================
    # No OCR or LLM inference is performed here.
    #
    # Presence of the initialized service objects is the
    # readiness signal.
    # ======================================================

    for service_name in (
        REQUIRED_APPLICATION_SERVICES
    ):

        service = (
            getattr(
                app_state,
                service_name,
                None,
            )
        )


        if service is None:

            raise ReadinessCheckFailed(
                reason=(
                    REASON_SERVICE_NOT_INITIALIZED
                ),
            )


    return ok_result()


# ==========================================================
# READINESS CHECK FAILURE
# ==========================================================

class ReadinessCheckFailed(
    RuntimeError
):
    """
    Internal readiness failure signal.

    Carries only safe, structured information:

        a stable reason code
        the originating exception (server-side only)
    """

    def __init__(
        self,
        *,
        reason: str,
        exc: Exception | None = None,
    ):

        self.reason = (
            reason
        )


        self.original_exception = (
            exc
        )


        super().__init__(
            reason
        )


# ==========================================================
# READINESS SERVICE
# ==========================================================

class ReadinessService:
    """
    Evaluates dependency readiness.

    Each check is injectable so failure paths can be
    exercised deterministically in tests without breaking
    the real PostgreSQL or storage integration.
    """

    def __init__(
        self,
        *,
        database_check=None,
        storage_check=None,
        services_check=None,
    ):

        self.database_check = (
            database_check
            or check_database
        )


        self.storage_check = (
            storage_check
            or check_storage
        )


        self.services_check = (
            services_check
            or check_application_services
        )


    # ======================================================
    # RUN A SINGLE CHECK
    # ======================================================

    def run_check(
        self,
        check,
        *,
        app_state,
    ) -> tuple[dict, Exception | None]:

        try:

            result = (
                check(
                    app_state
                )
            )


            # A check may return its own detail payload.

            if not isinstance(
                result,
                dict,
            ):

                return (
                    ok_result(),
                    None,
                )


            return (
                result,
                None,
            )


        # ==================================================
        # STRUCTURED READINESS FAILURE
        # ==================================================

        except ReadinessCheckFailed as exc:

            original = (
                exc.original_exception
            )


            error_type = (
                type(
                    original
                ).__name__
                if original is not None
                else None
            )


            return (
                error_result(
                    reason=(
                        exc.reason
                    ),

                    error_type=(
                        error_type
                    ),
                ),

                original
                or exc,
            )


        # ==================================================
        # UNEXPECTED CHECK FAILURE
        # ==================================================

        except Exception as exc:

            return (
                error_result(
                    reason=(
                        REASON_CHECK_FAILED
                    ),

                    error_type=(
                        type(
                            exc
                        ).__name__
                    ),
                ),

                exc,
            )


    # ======================================================
    # EVALUATE READINESS
    # ======================================================

    def evaluate(
        self,
        *,
        app_state,
    ) -> dict:

        checks: dict[str, dict] = {}


        failures: dict[str, Exception] = {}


        for (
            check_name,
            check,
        ) in (
            (
                "database",
                self.database_check,
            ),

            (
                "storage",
                self.storage_check,
            ),

            (
                "services",
                self.services_check,
            ),
        ):

            (
                result,
                failure,
            ) = (
                self.run_check(
                    check,
                    app_state=(
                        app_state
                    ),
                )
            )


            checks[
                check_name
            ] = result


            if failure is not None:

                failures[
                    check_name
                ] = failure


        ready = (
            all(
                result[
                    "status"
                ]
                == CHECK_OK
                for result in checks.values()
            )
        )


        return {
            "ready":
                ready,

            "checks":
                checks,

            "failures":
                failures,
        }
