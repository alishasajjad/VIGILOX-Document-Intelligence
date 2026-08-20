from backend.app.domain.schemas import DocumentExtraction
from backend.app.services.document_anomaly_validator import (
    DocumentAnomalyValidator,
)


validator = DocumentAnomalyValidator(
    low_confidence_threshold=0.90
)


# ==========================================================
# HELPER — CREATE DOCUMENT
# ==========================================================

def create_extraction(
    document_type="guard_license",
    full_name="TEST USER",
    licence_number="12345678",
    id_number=None,
    expiry_date="2027-01-01",
    date_of_birth="1990-01-01",
    issue_date="2025-01-01",
    issuer="TEST AUTHORITY",
):

    def field(value, line_id):

        return {
            "value": value,
            "source_line_ids": (
                [line_id]
                if value is not None
                else []
            ),
        }

    return DocumentExtraction.model_validate(
        {
            "document_type": document_type,

            "full_name":
                field(full_name, "L0"),

            "licence_number":
                field(licence_number, "L1"),

            "id_number":
                field(id_number, "L2"),

            "expiry_date":
                field(expiry_date, "L3"),

            "date_of_birth":
                field(date_of_birth, "L4"),

            "issue_date":
                field(issue_date, "L5"),

            "issuer":
                field(issuer, "L6"),
        }
    )


# ==========================================================
# HELPER — CREATE CONFIDENCE RESULTS
# ==========================================================

def create_confidence_results(
    extraction,
    overrides=None,
):

    overrides = overrides or {}

    results = {}

    fields = (
        "full_name",
        "licence_number",
        "id_number",
        "expiry_date",
        "date_of_birth",
        "issue_date",
        "issuer",
    )

    for field_name in fields:

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

    for field_name, changes in (
        overrides.items()
    ):

        results[field_name].update(
            changes
        )

    return results


# ==========================================================
# HELPER — DATE VALIDATION RESULT
# ==========================================================

def create_date_validation(
    expiry_status="ACTIVE",
    days_until_expiry=140,
    logical_issues=None,
):

    return {
        "logical_issues":
            logical_issues or [],

        "expiry": {
            "value": "2027-01-01",
            "status": expiry_status,
            "days_until_expiry":
                days_until_expiry,
        },
    }


# ==========================================================
# HELPER — RUN TEST
# ==========================================================

def run_test(
    name,
    extraction,
    confidence_results,
    date_validation,
    expected_codes,
    expected_valid,
):

    result = validator.validate(
        extraction,
        confidence_results,
        date_validation,
    )

    actual_codes = [
        issue["code"]
        for issue in result["issues"]
    ]

    print()
    print("=" * 72)
    print(name)
    print("=" * 72)

    print(
        "Valid:",
        result["valid"],
    )

    print(
        "Errors:",
        result["error_count"],
    )

    print(
        "Warnings:",
        result["warning_count"],
    )

    if result["issues"]:

        for issue in result["issues"]:

            print(
                f"[{issue['severity']}] "
                f"{issue['code']}"
            )

    else:

        print(
            "No anomalies detected."
        )

    assert (
        result["valid"]
        == expected_valid
    )

    for expected_code in expected_codes:

        assert (
            expected_code
            in actual_codes
        ), (
            f"Expected anomaly "
            f"{expected_code} "
            f"was not detected."
        )

    print("[PASS]")


# ==========================================================
# TEST 1 — CLEAN ACTIVE GUARD LICENCE
# ==========================================================

extraction = create_extraction()

confidence = (
    create_confidence_results(
        extraction
    )
)

dates = create_date_validation()

run_test(
    name="TEST 1 — CLEAN ACTIVE DOCUMENT",
    extraction=extraction,
    confidence_results=confidence,
    date_validation=dates,
    expected_codes=[],
    expected_valid=True,
)


# ==========================================================
# TEST 2 — MISSING CRITICAL FIELD
# ==========================================================

extraction = create_extraction(
    licence_number=None
)

confidence = (
    create_confidence_results(
        extraction
    )
)

dates = create_date_validation()

run_test(
    name="TEST 2 — MISSING CRITICAL FIELD",
    extraction=extraction,
    confidence_results=confidence,
    date_validation=dates,
    expected_codes=[
        "MISSING_CRITICAL_FIELD"
    ],
    expected_valid=False,
)


# ==========================================================
# TEST 3 — LOW CRITICAL FIELD CONFIDENCE
# ==========================================================

extraction = create_extraction()

confidence = (
    create_confidence_results(
        extraction,
        overrides={
            "full_name": {
                "confidence": 0.72
            }
        },
    )
)

dates = create_date_validation()

run_test(
    name="TEST 3 — LOW CRITICAL FIELD CONFIDENCE",
    extraction=extraction,
    confidence_results=confidence,
    date_validation=dates,
    expected_codes=[
        "LOW_CRITICAL_FIELD_CONFIDENCE"
    ],
    expected_valid=True,
)


# ==========================================================
# TEST 4 — INVALID CRITICAL FIELD EVIDENCE
# ==========================================================

extraction = create_extraction()

confidence = (
    create_confidence_results(
        extraction,
        overrides={
            "expiry_date": {
                "confidence": None,
                "status": "INVALID_EVIDENCE",
            }
        },
    )
)

dates = create_date_validation(
    expiry_status="NOT_AVAILABLE",
    days_until_expiry=None,
)

run_test(
    name="TEST 4 — INVALID CRITICAL FIELD EVIDENCE",
    extraction=extraction,
    confidence_results=confidence,
    date_validation=dates,
    expected_codes=[
        "CRITICAL_FIELD_NOT_TRUSTED"
    ],
    expected_valid=False,
)


# ==========================================================
# TEST 5 — DUPLICATE IDENTIFIER MAPPING
# ==========================================================

extraction = create_extraction(
    licence_number="12345678",
    id_number="12345678",
)

confidence = (
    create_confidence_results(
        extraction
    )
)

dates = create_date_validation()

run_test(
    name="TEST 5 — DUPLICATE IDENTIFIER MAPPING",
    extraction=extraction,
    confidence_results=confidence,
    date_validation=dates,
    expected_codes=[
        "DUPLICATE_IDENTIFIER_MAPPING"
    ],
    expected_valid=False,
)


# ==========================================================
# TEST 6 — DATE LOGICAL ISSUE PROPAGATION
# ==========================================================

extraction = create_extraction()

confidence = (
    create_confidence_results(
        extraction
    )
)

dates = create_date_validation(
    logical_issues=[
        {
            "code":
                "EXPIRY_BEFORE_ISSUE_DATE",

            "field":
                "expiry_date",

            "message":
                (
                    "Expiry date occurs before "
                    "the issue date."
                ),
        }
    ]
)

run_test(
    name="TEST 6 — DATE LOGICAL ISSUE",
    extraction=extraction,
    confidence_results=confidence,
    date_validation=dates,
    expected_codes=[
        "EXPIRY_BEFORE_ISSUE_DATE"
    ],
    expected_valid=False,
)


# ==========================================================
# TEST 7 — EXPIRED DOCUMENT
# ==========================================================

extraction = create_extraction(
    expiry_date="2026-01-01"
)

confidence = (
    create_confidence_results(
        extraction
    )
)

dates = create_date_validation(
    expiry_status="EXPIRED",
    days_until_expiry=-225,
)

run_test(
    name="TEST 7 — EXPIRED DOCUMENT",
    extraction=extraction,
    confidence_results=confidence,
    date_validation=dates,
    expected_codes=[
        "DOCUMENT_EXPIRED"
    ],
    expected_valid=True,
)


# ==========================================================
# TEST 8 — EXPIRING SOON
# ==========================================================

extraction = create_extraction()

confidence = (
    create_confidence_results(
        extraction
    )
)

dates = create_date_validation(
    expiry_status="EXPIRING_SOON",
    days_until_expiry=16,
)

run_test(
    name="TEST 8 — EXPIRING SOON",
    extraction=extraction,
    confidence_results=confidence,
    date_validation=dates,
    expected_codes=[
        "DOCUMENT_EXPIRING_SOON"
    ],
    expected_valid=True,
)


# ==========================================================
# TEST 9 — NON-CRITICAL FIELD INVALID EVIDENCE
# ==========================================================

extraction = create_extraction()

confidence = (
    create_confidence_results(
        extraction,
        overrides={
            "date_of_birth": {
                "confidence": None,
                "status":
                    "INVALID_EVIDENCE",
            }
        },
    )
)

dates = create_date_validation()

run_test(
    name=(
        "TEST 9 — NON-CRITICAL FIELD "
        "INVALID EVIDENCE"
    ),
    extraction=extraction,
    confidence_results=confidence,
    date_validation=dates,
    expected_codes=[
        "EXTRACTED_FIELD_INVALID_EVIDENCE"
    ],
    expected_valid=True,
)


# ==========================================================
# TEST 10 — UNKNOWN DOCUMENT TYPE
# ==========================================================

extraction = create_extraction(
    document_type="unknown"
)

confidence = (
    create_confidence_results(
        extraction
    )
)

dates = create_date_validation()

run_test(
    name="TEST 10 — UNKNOWN DOCUMENT TYPE",
    extraction=extraction,
    confidence_results=confidence,
    date_validation=dates,
    expected_codes=[
        "UNKNOWN_DOCUMENT_TYPE"
    ],
    expected_valid=False,
)


print()
print("=" * 72)
print(
    "ALL DOCUMENT ANOMALY TESTS PASSED"
)
print("=" * 72)