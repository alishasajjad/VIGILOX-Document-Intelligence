from datetime import date

from src.schemas import DocumentExtraction
from src.date_logical_validator import DateLogicalValidator


REFERENCE_DATE = date(
    2026,
    8,
    14,
)


validator = DateLogicalValidator(
    expiring_soon_days=30
)


# ==========================================================
# HELPER — CREATE EXTRACTION
# ==========================================================

def create_extraction(
    dob=None,
    issue=None,
    expiry=None,
):

    return DocumentExtraction.model_validate(
        {
            "document_type": "guard_license",

            "full_name": {
                "value": "TEST USER",
                "source_line_ids": ["L0"],
            },

            "licence_number": {
                "value": "12345678",
                "source_line_ids": ["L1"],
            },

            "id_number": {
                "value": None,
                "source_line_ids": [],
            },

            "expiry_date": {
                "value": expiry,
                "source_line_ids": (
                    ["L2"]
                    if expiry
                    else []
                ),
            },

            "date_of_birth": {
                "value": dob,
                "source_line_ids": (
                    ["L3"]
                    if dob
                    else []
                ),
            },

            "issue_date": {
                "value": issue,
                "source_line_ids": (
                    ["L4"]
                    if issue
                    else []
                ),
            },

            "issuer": {
                "value": "TEST AUTHORITY",
                "source_line_ids": ["L5"],
            },
        }
    )


# ==========================================================
# HELPER — FAKE PHASE 4A RESULTS
# ==========================================================

def create_confidence_results(
    extraction,
):

    results = {}

    for field_name in (
        "full_name",
        "licence_number",
        "id_number",
        "expiry_date",
        "date_of_birth",
        "issue_date",
        "issuer",
    ):

        field = getattr(
            extraction,
            field_name,
        )

        if field.value is None:

            results[field_name] = {
                "value": None,
                "confidence": None,
                "status": "NOT_EXTRACTED",
            }

        else:

            results[field_name] = {
                "value": field.value,
                "confidence": 0.99,
                "status": "VALID",
            }

    return results


# ==========================================================
# HELPER — RUN TEST
# ==========================================================

def run_test(
    name,
    dob=None,
    issue=None,
    expiry=None,
):

    extraction = create_extraction(
        dob=dob,
        issue=issue,
        expiry=expiry,
    )

    confidence_results = (
        create_confidence_results(
            extraction
        )
    )

    result = validator.validate(
        extraction,
        confidence_results,
        reference_date=REFERENCE_DATE,
    )

    print()
    print("=" * 70)
    print(name)
    print("=" * 70)

    print(
        "Expiry Status:",
        result["expiry"]["status"],
    )

    print(
        "Days Until Expiry:",
        result["expiry"][
            "days_until_expiry"
        ],
    )

    if result["logical_issues"]:

        for issue in (
            result["logical_issues"]
        ):

            print(
                "[DETECTED]",
                issue["code"],
            )

    else:

        print(
            "No logical issues detected."
        )


# ==========================================================
# TEST 1 — VALID ACTIVE DOCUMENT
# ==========================================================

run_test(
    "TEST 1 — ACTIVE DOCUMENT",
    dob="1990-01-01",
    issue="2026-01-01",
    expiry="2027-01-01",
)


# ==========================================================
# TEST 2 — EXPIRING SOON
# ==========================================================

run_test(
    "TEST 2 — EXPIRING SOON",
    dob="1990-01-01",
    issue="2025-01-01",
    expiry="2026-08-30",
)


# ==========================================================
# TEST 3 — EXPIRES TODAY
# ==========================================================

run_test(
    "TEST 3 — EXPIRES TODAY",
    dob="1990-01-01",
    issue="2025-01-01",
    expiry="2026-08-14",
)


# ==========================================================
# TEST 4 — EXPIRED
# ==========================================================

run_test(
    "TEST 4 — EXPIRED",
    dob="1990-01-01",
    issue="2025-01-01",
    expiry="2026-01-01",
)


# ==========================================================
# TEST 5 — FUTURE DOB
# ==========================================================

run_test(
    "TEST 5 — FUTURE DOB",
    dob="2030-01-01",
    issue=None,
    expiry=None,
)


# ==========================================================
# TEST 6 — FUTURE ISSUE DATE
# ==========================================================

run_test(
    "TEST 6 — FUTURE ISSUE DATE",
    dob="1990-01-01",
    issue="2027-01-01",
    expiry="2028-01-01",
)


# ==========================================================
# TEST 7 — EXPIRY BEFORE ISSUE
# ==========================================================

run_test(
    "TEST 7 — EXPIRY BEFORE ISSUE DATE",
    dob="1990-01-01",
    issue="2025-01-01",
    expiry="2024-01-01",
)


# ==========================================================
# TEST 8 — DOB AFTER ISSUE DATE
# ==========================================================

run_test(
    "TEST 8 — DOB AFTER ISSUE DATE",
    dob="2025-01-01",
    issue="2020-01-01",
    expiry="2030-01-01",
)


# ==========================================================
# TEST 9 — DOB AFTER EXPIRY DATE
# ==========================================================

run_test(
    "TEST 9 — DOB AFTER EXPIRY DATE",
    dob="2025-01-01",
    issue=None,
    expiry="2020-01-01",
)