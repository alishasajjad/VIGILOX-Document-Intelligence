from backend.app.services.review_decision_service import ReviewDecisionService


service = ReviewDecisionService()


def build_anomaly_result(
    issues=None,
    valid=True,
):
    issues = issues or []

    error_count = sum(
        1
        for issue in issues
        if issue["severity"] == "ERROR"
    )

    warning_count = sum(
        1
        for issue in issues
        if issue["severity"] == "WARNING"
    )

    return {
        "document_type": "guard_license",
        "valid": valid,
        "has_anomalies": bool(issues),
        "error_count": error_count,
        "warning_count": warning_count,
        "issues": issues,
    }


def warning(code):
    return {
        "code": code,
        "severity": "WARNING",
        "field": None,
        "message": code,
    }


def error(code):
    return {
        "code": code,
        "severity": "ERROR",
        "field": None,
        "message": code,
    }


def run_test(
    name,
    anomaly_result,
    expected_decision,
    expected_priority,
    expected_review_required,
):

    result = service.decide(
        anomaly_result
    )

    print()
    print("=" * 70)
    print(name)
    print("=" * 70)

    print(
        "Decision:",
        result["decision"],
    )

    print(
        "Review Required:",
        result["review_required"],
    )

    print(
        "Priority:",
        result["priority"],
    )

    print(
        "Reason Codes:",
        result["reason_codes"],
    )

    assert (
        result["decision"]
        == expected_decision
    )

    assert (
        result["priority"]
        == expected_priority
    )

    assert (
        result["review_required"]
        == expected_review_required
    )

    print("[PASS]")


# ==========================================================
# TEST 1 — CLEAN DOCUMENT
# ==========================================================

run_test(
    name="TEST 1 — CLEAN DOCUMENT",
    anomaly_result=build_anomaly_result(),
    expected_decision="AUTO_ACCEPT",
    expected_priority="NONE",
    expected_review_required=False,
)


# ==========================================================
# TEST 2 — EXPIRING SOON
# ==========================================================

run_test(
    name="TEST 2 — EXPIRING SOON",
    anomaly_result=build_anomaly_result(
        issues=[
            warning(
                "DOCUMENT_EXPIRING_SOON"
            )
        ]
    ),
    expected_decision="REVIEW_REQUIRED",
    expected_priority="LOW",
    expected_review_required=True,
)


# ==========================================================
# TEST 3 — EXPIRED DOCUMENT
# ==========================================================

run_test(
    name="TEST 3 — EXPIRED DOCUMENT",
    anomaly_result=build_anomaly_result(
        issues=[
            warning(
                "DOCUMENT_EXPIRED"
            )
        ]
    ),
    expected_decision="REVIEW_REQUIRED",
    expected_priority="MEDIUM",
    expected_review_required=True,
)


# ==========================================================
# TEST 4 — INVALID OPTIONAL FIELD
# ==========================================================

run_test(
    name="TEST 4 — INVALID OPTIONAL FIELD",
    anomaly_result=build_anomaly_result(
        issues=[
            warning(
                "EXTRACTED_FIELD_INVALID_EVIDENCE"
            )
        ]
    ),
    expected_decision="REVIEW_REQUIRED",
    expected_priority="MEDIUM",
    expected_review_required=True,
)


# ==========================================================
# TEST 5 — LOW CRITICAL FIELD CONFIDENCE
# ==========================================================

run_test(
    name="TEST 5 — LOW CRITICAL FIELD CONFIDENCE",
    anomaly_result=build_anomaly_result(
        issues=[
            warning(
                "LOW_CRITICAL_FIELD_CONFIDENCE"
            )
        ]
    ),
    expected_decision="REVIEW_REQUIRED",
    expected_priority="MEDIUM",
    expected_review_required=True,
)


# ==========================================================
# TEST 6 — MISSING CRITICAL FIELD
# ==========================================================

run_test(
    name="TEST 6 — MISSING CRITICAL FIELD",
    anomaly_result=build_anomaly_result(
        issues=[
            error(
                "MISSING_CRITICAL_FIELD"
            )
        ],
        valid=False,
    ),
    expected_decision="REVIEW_REQUIRED",
    expected_priority="HIGH",
    expected_review_required=True,
)


# ==========================================================
# TEST 7 — UNKNOWN DOCUMENT TYPE
# ==========================================================

run_test(
    name="TEST 7 — UNKNOWN DOCUMENT TYPE",
    anomaly_result=build_anomaly_result(
        issues=[
            error(
                "UNKNOWN_DOCUMENT_TYPE"
            )
        ],
        valid=False,
    ),
    expected_decision="REVIEW_REQUIRED",
    expected_priority="HIGH",
    expected_review_required=True,
)


# ==========================================================
# TEST 8 — WARNING + ERROR
# ==========================================================

run_test(
    name="TEST 8 — WARNING AND ERROR",
    anomaly_result=build_anomaly_result(
        issues=[
            warning(
                "DOCUMENT_EXPIRED"
            ),
            error(
                "CRITICAL_FIELD_NOT_TRUSTED"
            ),
        ],
        valid=False,
    ),
    expected_decision="REVIEW_REQUIRED",
    expected_priority="HIGH",
    expected_review_required=True,
)


# ==========================================================
# TEST 9 — MULTIPLE LOW WARNINGS
# ==========================================================

run_test(
    name="TEST 9 — LOW PRIORITY WARNING ONLY",
    anomaly_result=build_anomaly_result(
        issues=[
            warning(
                "DOCUMENT_EXPIRING_SOON"
            )
        ]
    ),
    expected_decision="REVIEW_REQUIRED",
    expected_priority="LOW",
    expected_review_required=True,
)


print()
print("=" * 70)
print(
    "ALL REVIEW DECISION TESTS PASSED"
)
print("=" * 70)