import json
import logging
import os
import subprocess
import sys

from pathlib import Path


# ==========================================================
# PHASE 7C.7 FINAL VERIFICATION
# ==========================================================

PROJECT_ROOT = (
    Path(
        __file__
    )
    .resolve()
    .parents[2]
)


def section(
    title: str,
):

    print()
    print("-" * 76)
    print(
        title
    )
    print("-" * 76)


# ==========================================================
# 1. API ROUTE CONTRACT
# ==========================================================

def verify_routes():

    section(
        "1 - EXISTING API ROUTES PRESERVED"
    )


    from backend.app.main import (
        app,
    )


    registered = {
        route.path
        for route in app.routes
        if hasattr(
            route,
            "path",
        )
    }


    required = (
        "/health",
        "/api/v1/documents/analyze",
        "/api/v1/documents/{document_id}",
        "/api/v1/documents/{document_id}/image",
        "/api/v1/documents/{document_id}/reviews",
        "/api/v1/documents/{document_id}/history",
        "/api/v1/reviews/queue",
        "/api/v1/reviewer/me",
        "/review",
        "/review/{document_id}",
    )


    missing = [
        path
        for path in required
        if path not in registered
    ]


    if missing:

        raise AssertionError(
            "Existing API routes are "
            f"missing: {missing}"
        )


    for path in required:

        print(
            f"[OK]   {path}"
        )


    # ======================================================
    # NEW READINESS ROUTE
    # ======================================================

    if (
        "/health/ready"
        not in registered
    ):

        raise AssertionError(
            "Readiness route /health/ready "
            "is not registered."
        )


    print(
        "[OK]   /health/ready  (new in "
        "Phase 7C.7f)"
    )


    print()
    print(
        "[PASS] All documented routes "
        "preserved"
    )


# ==========================================================
# 2. LOG LEVEL CONFIGURATION
# ==========================================================

def verify_log_levels():

    section(
        "2 - VIGILOX_LOG_LEVEL "
        "CONFIGURATION"
    )


    from backend.app.core.logging import (
        LOGGER_ROOT_NAME,
        SUPPORTED_LOG_LEVELS,
        resolve_log_level,
    )


    original = (
        os.environ.get(
            "VIGILOX_LOG_LEVEL"
        )
    )


    try:

        for (
            level_name,
            expected_level,
        ) in SUPPORTED_LOG_LEVELS.items():

            os.environ[
                "VIGILOX_LOG_LEVEL"
            ] = level_name


            resolved = (
                resolve_log_level()
            )


            if resolved != expected_level:

                raise AssertionError(
                    "Log level mismatch for "
                    f"{level_name}: "
                    f"{resolved} != "
                    f"{expected_level}"
                )


            print(
                f"[OK]   {level_name} -> "
                f"{resolved}"
            )


        # ==============================================
        # DEFAULT
        # ==============================================

        os.environ.pop(
            "VIGILOX_LOG_LEVEL",
            None,
        )


        if (
            resolve_log_level()
            != logging.INFO
        ):

            raise AssertionError(
                "Default log level should be "
                "INFO."
            )


        print(
            "[OK]   default -> INFO"
        )


        # ==============================================
        # UNKNOWN VALUE FALLS BACK SAFELY
        # ==============================================

        os.environ[
            "VIGILOX_LOG_LEVEL"
        ] = "NOT_A_LEVEL"


        if (
            resolve_log_level()
            != logging.INFO
        ):

            raise AssertionError(
                "Unknown log level should "
                "fall back to INFO."
            )


        print(
            "[OK]   unknown value -> INFO "
            "(safe fallback)"
        )


    finally:

        if original is None:

            os.environ.pop(
                "VIGILOX_LOG_LEVEL",
                None,
            )


        else:

            os.environ[
                "VIGILOX_LOG_LEVEL"
            ] = original


    print()
    print(
        "[PASS] Log level configuration "
        "behaves correctly"
    )


# ==========================================================
# 3. SECRET SAFETY OF STRUCTURED LOGS
# ==========================================================

def verify_secret_safety():

    section(
        "3 - SECRET SAFETY OF STRUCTURED "
        "LOGS"
    )


    import io


    from backend.app.core.logging import (
        LOGGER_ROOT_NAME,
        StructuredJSONFormatter,
        get_operational_logger,
    )


    stream = (
        io.StringIO()
    )


    handler = (
        logging.StreamHandler(
            stream
        )
    )


    handler.setFormatter(
        StructuredJSONFormatter()
    )


    root_logger = (
        logging.getLogger(
            LOGGER_ROOT_NAME
        )
    )


    root_logger.addHandler(
        handler
    )


    previous_level = (
        root_logger.level
    )


    root_logger.setLevel(
        logging.DEBUG
    )


    try:

        logger = (
            get_operational_logger(
                "verify.secrets"
            )
        )


        # ==============================================
        # REAL ENVIRONMENT SECRETS
        # ==============================================
        #
        # Actual configured secret VALUES are used as
        # needles only. They are never printed.
        # ==============================================

        secret_values = []


        for variable_name in (
            "GROQ_API_KEY",
            "DATABASE_URL",
        ):

            value = (
                os.environ.get(
                    variable_name
                )
            )


            if value:

                secret_values.append(
                    (
                        variable_name,
                        value,
                    )
                )


        logger.info(
            "Verification probe.",

            extra={
                "event":
                    "secret_safety_probe",

                "document_id":
                    "doc-verify",

                # Hostile / accidental context
                "GROQ_API_KEY":
                    os.environ.get(
                        "GROQ_API_KEY",
                        "unset",
                    ),

                "DATABASE_URL":
                    os.environ.get(
                        "DATABASE_URL",
                        "unset",
                    ),

                "authorization":
                    "Bearer abc123",

                "env":
                    dict(
                        os.environ
                    ),
            },
        )


        serialized = (
            stream.getvalue()
        )


        # ==============================================
        # STRUCTURE
        # ==============================================

        record = (
            json.loads(
                serialized.strip()
            )
        )


        print(
            "[OK]   structured record is "
            "valid JSON"
        )


        for (
            variable_name,
            secret_value,
        ) in secret_values:

            if secret_value in serialized:

                raise AssertionError(
                    "A configured secret value "
                    "leaked into a structured "
                    f"log: {variable_name}"
                )


            print(
                f"[OK]   {variable_name} value "
                "never serialized"
            )


        for forbidden_key in (
            "GROQ_API_KEY",
            "DATABASE_URL",
            "authorization",
            "env",
        ):

            if forbidden_key in record:

                raise AssertionError(
                    "Non-allowlisted key leaked "
                    "into a structured log: "
                    f"{forbidden_key}"
                )


            print(
                f"[OK]   '{forbidden_key}' key "
                "not serialized"
            )


        if (
            record.get(
                "document_id"
            )
            != "doc-verify"
        ):

            raise AssertionError(
                "Allowlisted context should "
                "still be serialized."
            )


        print(
            "[OK]   allowlisted context still "
            "serialized"
        )


    finally:

        root_logger.removeHandler(
            handler
        )


        root_logger.setLevel(
            previous_level
        )


    print()
    print(
        "[PASS] Structured logs never carry "
        "secrets or request bodies"
    )


# ==========================================================
# 4. NO .env READS IN LOGGING PATHS
# ==========================================================

def verify_no_env_file_logging():

    section(
        "4 - NO .env CONTENT IN LOGGING "
        "PATHS"
    )


    for relative_path in (
        "backend/app/core/logging.py",
        "backend/app/core/paths.py",
        "backend/app/api/request_context.py",
        "backend/app/services/readiness_service.py",
        "backend/app/api/error_handlers.py",
    ):

        source = (
            (
                PROJECT_ROOT
                / relative_path
            )
            .read_text(
                encoding="utf-8"
            )
        )


        for forbidden in (
            ".env",
            "environ.items",
            "dict(os.environ)",
            "load_dotenv",
        ):

            if forbidden in source:

                raise AssertionError(
                    f"{relative_path} references "
                    f"'{forbidden}', which risks "
                    "logging environment "
                    "content."
                )


        print(
            f"[OK]   {relative_path}"
        )


    print()
    print(
        "[PASS] Logging / readiness modules "
        "never touch .env content"
    )


# ==========================================================
# 5. PRODUCTION PRINT SCAN
# ==========================================================

def verify_print_scan():

    section(
        "5 - PRODUCTION SOURCE PRINT SCAN"
    )


    offending = []


    source_roots = (
        PROJECT_ROOT
        / "backend",

        PROJECT_ROOT
        / "database",
    )


    for python_file in sorted(
        python_file
        for source_root in source_roots
        for python_file in source_root.rglob(
            "*.py"
        )
    ):

        for (
            line_number,
            line,
        ) in enumerate(
            python_file
            .read_text(
                encoding="utf-8"
            )
            .splitlines(),
            start=1,
        ):

            if (
                line
                .strip()
                .startswith(
                    "print("
                )
            ):

                offending.append(
                    f"{python_file}:"
                    f"{line_number}"
                )


    if offending:

        raise AssertionError(
            "print() calls remain in "
            f"production source: {offending}"
        )


    print(
        "[OK]   zero print() calls in "
        "backend/ and database/"
    )


    print()
    print(
        "[PASS] All operational output uses "
        "structured logging"
    )


# ==========================================================
# MAIN
# ==========================================================

def main() -> int:

    print()
    print("=" * 76)
    print(
        "PHASE 7C.7 FINAL VERIFICATION"
    )
    print("=" * 76)


    verify_routes()

    verify_log_levels()

    verify_secret_safety()

    verify_no_env_file_logging()

    verify_print_scan()


    print()
    print("=" * 76)
    print(
        "[PASS] PHASE 7C.7 FINAL "
        "VERIFICATION PASSED"
    )
    print("=" * 76)


    return 0


if __name__ == "__main__":

    raise SystemExit(
        main()
    )
