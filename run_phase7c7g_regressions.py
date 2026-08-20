import os
import subprocess
import sys
import time

from pathlib import Path


# ==========================================================
# SUBPROCESS ENVIRONMENT
# ==========================================================
#
# Several existing test files print Unicode characters such
# as the arrow U+2192 in their section headers.
#
# When stdout is a captured pipe on Windows, Python defaults
# to the cp1252 console encoding and those prints raise
# UnicodeEncodeError. That is a limitation of this runner's
# output capture, not a defect in the tests or in production
# code.
#
# Forcing UTF-8 for child interpreters makes the captured
# runs behave exactly like an interactive UTF-8 terminal.
# ==========================================================

def build_subprocess_environment() -> dict:

    environment = (
        dict(
            os.environ
        )
    )


    environment[
        "PYTHONIOENCODING"
    ] = "utf-8"


    return environment


# ==========================================================
# PHASE 7C.7g
# OPERATIONAL REGRESSION RUNNER
# ==========================================================
#
# Runs each standalone test file in its own interpreter so
# one module's application-state mutation can never leak
# into another module's assertions.
# ==========================================================

PROJECT_ROOT = (
    Path(
        __file__
    )
    .resolve()
    .parent
)


PYTHON = (
    sys.executable
)


# ==========================================================
# CHANGED PRODUCTION FILES
# ==========================================================

CHANGED_PRODUCTION_FILES = (
    "src/operational_logging.py",
    "src/api/request_context.py",
    "src/readiness_service.py",
    "src/api/main.py",
    "src/api/error_handlers.py",
    "src/api/request_validation.py",
    "src/db/persistence_service.py",
    "src/extraction_service.py",
)


# ==========================================================
# FINAL PRODUCTION-READINESS GATE
# PHASE 7C.8
# ==========================================================

FINAL_PRODUCTION_GATE = (
    (
        "test_phase7c_final_production"
        "_readiness_e2e.py"
    ),
)


# ==========================================================
# TEST GROUPS
# ==========================================================

FOCUSED_PHASE_7C7_TESTS = (
    "test_phase7c_api_error_contract.py",
    "test_phase7c_request_validation.py",
    "test_phase7c_domain_error_mapping.py",
    "test_phase7c_structured_logging.py",
    "test_phase7c_request_id.py",
    "test_phase7c_readiness.py",
)


REVIEW_AND_SECURITY_REGRESSIONS = (
    "test_phase7c_duplicate_review_protection.py",
    "test_phase7c_explicit_evidence_ids.py",
    "test_phase7c_final_record.py",
    "test_phase7c_reviewer_identity_service.py",
    "test_phase7c_reviewer_identity_api.py",
    "test_review_audit_persistence.py",
)


STORAGE_REGRESSIONS = (
    "test_phase7c_storage_path_safety.py",
    "test_phase7c_safe_document_deletion.py",
    "test_phase7c_failed_processing_cleanup.py",
    "test_phase7c_storage_integrity_detection.py",
    "test_phase7c_storage_reconciliation.py",
    "test_phase7b_document_storage.py",
    "test_phase7b_persistence_storage_integration.py",
)


API_AND_DASHBOARD_REGRESSIONS = (
    "test_phase7b_analyze_storage_api.py",
    "test_phase7b_document_image_api.py",
    "test_phase7b_human_review_actions.py",
    "test_phase7b_final_dashboard_e2e.py",
    "test_phase7c_final_status_dashboard_e2e.py",
    "test_phase7c_reviewer_identity_dashboard_e2e.py",
)


END_TO_END_REGRESSIONS = (
    "test_phase7a_final_e2e.py",
    "test_phase7c_storage_lifecycle_e2e.py",
)


REAL_DEPENDENCY_TESTS = (
    "test_real_pipeline_persistence.py",
    "test_phase7c_real_provenance_e2e.py",
)


TEST_GROUPS = (
    (
        "FINAL PRODUCTION-READINESS GATE",
        FINAL_PRODUCTION_GATE,
    ),

    (
        "FOCUSED PHASE 7C.7 TESTS",
        FOCUSED_PHASE_7C7_TESTS,
    ),

    (
        "REVIEW / SECURITY REGRESSIONS",
        REVIEW_AND_SECURITY_REGRESSIONS,
    ),

    (
        "STORAGE REGRESSIONS",
        STORAGE_REGRESSIONS,
    ),

    (
        "API / DASHBOARD REGRESSIONS",
        API_AND_DASHBOARD_REGRESSIONS,
    ),

    (
        "END-TO-END REGRESSIONS",
        END_TO_END_REGRESSIONS,
    ),

    (
        "REAL DEPENDENCY TESTS",
        REAL_DEPENDENCY_TESTS,
    ),
)


# ==========================================================
# COMPILE CHANGED PRODUCTION FILES
# ==========================================================

def compile_changed_files() -> bool:

    print()
    print("=" * 76)
    print(
        "STEP 1 - SYNTAX COMPILATION OF "
        "CHANGED PRODUCTION FILES"
    )
    print("=" * 76)


    existing = [
        relative_path
        for relative_path in (
            CHANGED_PRODUCTION_FILES
        )
        if (
            PROJECT_ROOT
            / relative_path
        ).exists()
    ]


    completed = (
        subprocess.run(
            [
                PYTHON,
                "-m",
                "py_compile",
                *existing,
            ],

            cwd=(
                PROJECT_ROOT
            ),

            capture_output=True,
            text=True,
        )
    )


    if completed.returncode != 0:

        print(
            "[FAIL] Compilation failed"
        )


        print(
            completed.stdout
        )

        print(
            completed.stderr
        )


        return False


    for relative_path in existing:

        print(
            f"[OK]   {relative_path}"
        )


    print()
    print(
        "[PASS] All changed production "
        "files compile"
    )


    return True


# ==========================================================
# RUN A SINGLE TEST FILE
# ==========================================================

def run_test_file(
    test_file: str,
) -> tuple[str, float, str]:

    path = (
        PROJECT_ROOT
        / test_file
    )


    if not path.exists():

        return (
            "MISSING",
            0.0,
            "",
        )


    started = (
        time.monotonic()
    )


    completed = (
        subprocess.run(
            [
                PYTHON,
                test_file,
            ],

            cwd=(
                PROJECT_ROOT
            ),

            capture_output=True,
            text=True,

            encoding="utf-8",
            errors="replace",

            env=(
                build_subprocess_environment()
            ),

            timeout=1800,
        )
    )


    duration = (
        time.monotonic()
        - started
    )


    if completed.returncode == 0:

        return (
            "PASS",
            duration,
            "",
        )


    # ======================================================
    # CAPTURE THE TAIL OF THE FAILURE
    # ======================================================

    combined = (
        (
            completed.stdout
            or ""
        )
        + "\n"
        + (
            completed.stderr
            or ""
        )
    )


    tail = (
        "\n".join(
            combined
            .strip()
            .splitlines()[
                -25:
            ]
        )
    )


    return (
        "FAIL",
        duration,
        tail,
    )


# ==========================================================
# MAIN
# ==========================================================

def main() -> int:

    print()
    print("=" * 76)
    print(
        "PHASE 7C.7g - OPERATIONAL "
        "REGRESSION SUITE"
    )
    print("=" * 76)


    if not compile_changed_files():

        return 1


    results = []


    failures = []


    for (
        group_name,
        test_files,
    ) in TEST_GROUPS:

        print()
        print("=" * 76)
        print(
            f"GROUP - {group_name}"
        )
        print("=" * 76)


        for test_file in test_files:

            (
                status,
                duration,
                tail,
            ) = (
                run_test_file(
                    test_file
                )
            )


            results.append(
                (
                    group_name,
                    test_file,
                    status,
                    duration,
                )
            )


            print(
                f"[{status:<7}] "
                f"{duration:7.1f}s  "
                f"{test_file}"
            )


            if status == "FAIL":

                failures.append(
                    (
                        test_file,
                        tail,
                    )
                )


    # ======================================================
    # FAILURE DETAIL
    # ======================================================

    if failures:

        print()
        print("=" * 76)
        print(
            "FAILURE DETAIL"
        )
        print("=" * 76)


        for (
            test_file,
            tail,
        ) in failures:

            print()
            print("-" * 76)
            print(
                test_file
            )
            print("-" * 76)
            print(
                tail
            )


    # ======================================================
    # SUMMARY
    # ======================================================

    passed = (
        sum(
            1
            for entry in results
            if entry[2] == "PASS"
        )
    )


    failed = (
        sum(
            1
            for entry in results
            if entry[2] == "FAIL"
        )
    )


    missing = (
        sum(
            1
            for entry in results
            if entry[2] == "MISSING"
        )
    )


    print()
    print("=" * 76)
    print(
        "PHASE 7C.7g SUMMARY"
    )
    print("=" * 76)

    print(
        f"PASSED  : {passed}"
    )

    print(
        f"FAILED  : {failed}"
    )

    print(
        f"MISSING : {missing}"
    )


    if missing:

        print()
        print(
            "Missing test files "
            "(not present in repository):"
        )


        for entry in results:

            if entry[2] == "MISSING":

                print(
                    f"  - {entry[1]}"
                )


    print()


    if failed:

        print(
            "[FAIL] PHASE 7C.7g OPERATIONAL "
            "REGRESSION SUITE FAILED"
        )


        return 1


    print(
        "[PASS] PHASE 7C.7g OPERATIONAL "
        "REGRESSION SUITE PASSED"
    )


    return 0


if __name__ == "__main__":

    raise SystemExit(
        main()
    )
