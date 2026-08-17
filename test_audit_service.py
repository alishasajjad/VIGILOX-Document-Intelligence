from pathlib import Path

from src.audit_service import (
    AuditService,
)

from src.human_review_service import (
    HumanReviewService,
)


TEST_LOG = (
    "output/audit/"
    "test_audit_log.jsonl"
)


# ==========================================================
# CLEAN PREVIOUS TEST FILE
# ==========================================================

test_path = Path(
    TEST_LOG
)

if test_path.exists():
    test_path.unlink()


audit_service = AuditService(
    log_path=TEST_LOG
)

human_review_service = (
    HumanReviewService()
)


DOCUMENT_ID = "DOC-001"


MACHINE_RESULT = {
    "decision":
        "REVIEW_REQUIRED",

    "review_required":
        True,

    "priority":
        "MEDIUM",

    "reason_codes": [
        "DOCUMENT_EXPIRED"
    ],
}


# ==========================================================
# TEST 1 — MACHINE DECISION AUDIT
# ==========================================================

print()
print("=" * 70)
print(
    "TEST 1 — MACHINE DECISION AUDIT"
)
print("=" * 70)


machine_event = (
    audit_service
    .log_machine_decision(
        document_id=DOCUMENT_ID,
        review_result=MACHINE_RESULT,
    )
)


print(
    "Event Type:",
    machine_event["event_type"],
)

print(
    "Actor Type:",
    machine_event["actor_type"],
)


assert (
    machine_event["event_type"]
    == "MACHINE_REVIEW_DECISION"
)

assert (
    machine_event["actor_type"]
    == "SYSTEM"
)

print("[PASS]")


# ==========================================================
# TEST 2 — HUMAN APPROVE AUDIT
# ==========================================================

print()
print("=" * 70)
print(
    "TEST 2 — HUMAN REVIEW AUDIT"
)
print("=" * 70)


human_review = (
    human_review_service
    .submit_review(
        document_id=DOCUMENT_ID,
        reviewer_id="USER-001",
        review_result=MACHINE_RESULT,
        action="APPROVE",
        notes=(
            "Document manually "
            "reviewed."
        ),
    )
)


human_event = (
    audit_service
    .log_human_review(
        human_review
    )
)


print(
    "Human Action:",
    human_event[
        "details"
    ]["human_action"],
)

print(
    "Reviewer:",
    human_event["actor_id"],
)


assert (
    human_event[
        "details"
    ]["human_action"]
    == "APPROVE"
)

assert (
    human_event["actor_id"]
    == "USER-001"
)

print("[PASS]")


# ==========================================================
# TEST 3 — HISTORY RETRIEVAL
# ==========================================================

print()
print("=" * 70)
print(
    "TEST 3 — DOCUMENT HISTORY"
)
print("=" * 70)


history = (
    audit_service
    .get_document_history(
        DOCUMENT_ID
    )
)


print(
    "Number of Events:",
    len(history),
)


for event in history:

    print(
        "-",
        event["event_type"],
    )


assert len(history) == 2

assert (
    history[0]["event_type"]
    == "MACHINE_REVIEW_DECISION"
)

assert (
    history[1]["event_type"]
    == "HUMAN_REVIEW"
)

print("[PASS]")


# ==========================================================
# TEST 4 — HUMAN CORRECTION AUDIT
# ==========================================================

print()
print("=" * 70)
print(
    "TEST 4 — CORRECTION AUDIT"
)
print("=" * 70)


correction_review = (
    human_review_service
    .submit_review(
        document_id="DOC-002",
        reviewer_id="USER-002",
        review_result=MACHINE_RESULT,
        action="CORRECT",
        corrections={
            "full_name":
                "JOHN SMITH",

            "expiry_date":
                "2027-01-01",
        },
        notes=(
            "Values corrected after "
            "manual inspection."
        ),
    )
)


correction_event = (
    audit_service
    .log_human_review(
        correction_review
    )
)


corrections = (
    correction_event[
        "details"
    ]["corrections"]
)


print(
    "Corrections:",
    corrections,
)


assert (
    corrections["full_name"]
    == "JOHN SMITH"
)

assert (
    corrections["expiry_date"]
    == "2027-01-01"
)

print("[PASS]")


# ==========================================================
# TEST 5 — APPEND-ONLY BEHAVIOR
# ==========================================================

print()
print("=" * 70)
print(
    "TEST 5 — APPEND-ONLY AUDIT"
)
print("=" * 70)


doc_1_history = (
    audit_service
    .get_document_history(
        "DOC-001"
    )
)

doc_2_history = (
    audit_service
    .get_document_history(
        "DOC-002"
    )
)


assert len(doc_1_history) == 2
assert len(doc_2_history) == 1


print(
    "DOC-001 Events:",
    len(doc_1_history),
)

print(
    "DOC-002 Events:",
    len(doc_2_history),
)

print("[PASS]")


print()
print("=" * 70)
print(
    "ALL AUDIT TRAIL TESTS PASSED"
)
print("=" * 70)