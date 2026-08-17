from src.human_review_service import (
    HumanReviewService,
)


service = HumanReviewService()


MACHINE_REVIEW_RESULT = {
    "decision": "REVIEW_REQUIRED",
    "review_required": True,
    "priority": "MEDIUM",
    "reason_codes": [
        "DOCUMENT_EXPIRED"
    ],
}


# ==========================================================
# TEST 1 — HUMAN APPROVE
# ==========================================================

print()
print("=" * 70)
print("TEST 1 — HUMAN APPROVE")
print("=" * 70)

result = service.submit_review(
    document_id="DOC-001",
    reviewer_id="USER-001",
    review_result=MACHINE_REVIEW_RESULT,
    action="APPROVE",
    notes=(
        "Document manually checked "
        "and accepted."
    ),
)

print(
    "Human Action:",
    result["human_action"],
)

print(
    "Status:",
    result["status"],
)

assert (
    result["human_action"]
    == "APPROVE"
)

assert (
    result["machine_decision"]
    == "REVIEW_REQUIRED"
)

print("[PASS]")


# ==========================================================
# TEST 2 — HUMAN REJECT
# ==========================================================

print()
print("=" * 70)
print("TEST 2 — HUMAN REJECT")
print("=" * 70)

result = service.submit_review(
    document_id="DOC-002",
    reviewer_id="USER-002",
    review_result=MACHINE_REVIEW_RESULT,
    action="REJECT",
    notes=(
        "Expired document cannot "
        "be accepted."
    ),
)

print(
    "Human Action:",
    result["human_action"],
)

assert (
    result["human_action"]
    == "REJECT"
)

print("[PASS]")


# ==========================================================
# TEST 3 — HUMAN CORRECTION
# ==========================================================

print()
print("=" * 70)
print("TEST 3 — HUMAN CORRECTION")
print("=" * 70)

result = service.submit_review(
    document_id="DOC-003",
    reviewer_id="USER-003",
    review_result=MACHINE_REVIEW_RESULT,
    action="CORRECT",
    corrections={
        "full_name":
            "JOHN SMITH",

        "expiry_date":
            "2027-01-01",
    },
    notes=(
        "OCR values corrected after "
        "manual inspection."
    ),
)

print(
    "Human Action:",
    result["human_action"],
)

print(
    "Corrections:",
    result["corrections"],
)

assert (
    result["human_action"]
    == "CORRECT"
)

assert (
    result["corrections"][
        "full_name"
    ]
    == "JOHN SMITH"
)

print("[PASS]")


# ==========================================================
# TEST 4 — CORRECT WITHOUT CORRECTIONS
# ==========================================================

print()
print("=" * 70)
print(
    "TEST 4 — CORRECT WITHOUT CORRECTIONS"
)
print("=" * 70)

try:

    service.submit_review(
        document_id="DOC-004",
        reviewer_id="USER-004",
        review_result=MACHINE_REVIEW_RESULT,
        action="CORRECT",
    )

    raise AssertionError(
        "Expected ValueError."
    )

except ValueError:

    print(
        "[PASS] Invalid correction blocked."
    )


# ==========================================================
# TEST 5 — APPROVE WITH CORRECTIONS
# ==========================================================

print()
print("=" * 70)
print(
    "TEST 5 — APPROVE WITH CORRECTIONS"
)
print("=" * 70)

try:

    service.submit_review(
        document_id="DOC-005",
        reviewer_id="USER-005",
        review_result=MACHINE_REVIEW_RESULT,
        action="APPROVE",
        corrections={
            "full_name":
                "TEST USER"
        },
    )

    raise AssertionError(
        "Expected ValueError."
    )

except ValueError:

    print(
        "[PASS] Invalid action/correction "
        "combination blocked."
    )


# ==========================================================
# TEST 6 — UNSUPPORTED FIELD
# ==========================================================

print()
print("=" * 70)
print("TEST 6 — UNSUPPORTED FIELD")
print("=" * 70)

try:

    service.submit_review(
        document_id="DOC-006",
        reviewer_id="USER-006",
        review_result=MACHINE_REVIEW_RESULT,
        action="CORRECT",
        corrections={
            "fake_field":
                "ABC"
        },
    )

    raise AssertionError(
        "Expected ValueError."
    )

except ValueError:

    print(
        "[PASS] Unsupported field blocked."
    )


print()
print("=" * 70)
print(
    "ALL HUMAN REVIEW TESTS PASSED"
)
print("=" * 70)