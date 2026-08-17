from pathlib import Path

from src.review_decision_service import (
    ReviewDecisionService,
)

from src.human_review_service import (
    HumanReviewService,
)

from src.audit_service import (
    AuditService,
)


# ==========================================================
# TEST AUDIT FILE
# ==========================================================

TEST_LOG_PATH = (
    "output/audit/"
    "test_phase5_end_to_end.jsonl"
)


test_log = Path(
    TEST_LOG_PATH
)


if test_log.exists():
    test_log.unlink()


# ==========================================================
# SERVICES
# ==========================================================

review_decision_service = (
    ReviewDecisionService()
)

human_review_service = (
    HumanReviewService()
)

audit_service = AuditService(
    log_path=TEST_LOG_PATH
)


# ==========================================================
# HELPERS
# ==========================================================

def warning(
    code: str,
) -> dict:

    return {
        "code": code,
        "severity": "WARNING",
        "field": None,
        "message": code,
    }


def error(
    code: str,
) -> dict:

    return {
        "code": code,
        "severity": "ERROR",
        "field": None,
        "message": code,
    }


def build_anomaly_result(
    issues=None,
    valid=True,
) -> dict:

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
        "document_type":
            "guard_license",

        "valid":
            valid,

        "has_anomalies":
            bool(issues),

        "error_count":
            error_count,

        "warning_count":
            warning_count,

        "issues":
            issues,
    }


# ==========================================================
# TEST 1 — CLEAN DOCUMENT → AUTO ACCEPT
# ==========================================================

print()
print("=" * 72)
print(
    "TEST 1 — CLEAN DOCUMENT → AUTO ACCEPT"
)
print("=" * 72)


document_id = "DOC-E2E-001"


anomaly_result = (
    build_anomaly_result()
)


review_result = (
    review_decision_service
    .decide(
        anomaly_result
    )
)


assert (
    review_result["decision"]
    == "AUTO_ACCEPT"
)

assert (
    review_result["review_required"]
    is False
)


audit_service.log_machine_decision(
    document_id=document_id,
    review_result=review_result,
)


history = (
    audit_service
    .get_document_history(
        document_id
    )
)


print(
    "Decision:",
    review_result["decision"],
)

print(
    "Review Required:",
    review_result[
        "review_required"
    ],
)

print(
    "Audit Events:",
    len(history),
)


assert len(history) == 1

assert (
    history[0]["event_type"]
    == "MACHINE_REVIEW_DECISION"
)


print("[PASS]")


# ==========================================================
# TEST 2 — EXPIRED → HUMAN APPROVES
# ==========================================================

print()
print("=" * 72)
print(
    "TEST 2 — EXPIRED DOCUMENT → HUMAN APPROVES"
)
print("=" * 72)


document_id = "DOC-E2E-002"


anomaly_result = (
    build_anomaly_result(
        issues=[
            warning(
                "DOCUMENT_EXPIRED"
            )
        ]
    )
)


review_result = (
    review_decision_service
    .decide(
        anomaly_result
    )
)


assert (
    review_result["decision"]
    == "REVIEW_REQUIRED"
)

assert (
    review_result["priority"]
    == "MEDIUM"
)


audit_service.log_machine_decision(
    document_id=document_id,
    review_result=review_result,
)


human_review = (
    human_review_service
    .submit_review(
        document_id=document_id,
        reviewer_id="REVIEWER-001",
        review_result=review_result,
        action="APPROVE",
        notes=(
            "Expired document manually "
            "reviewed and accepted."
        ),
    )
)


audit_service.log_human_review(
    human_review
)


history = (
    audit_service
    .get_document_history(
        document_id
    )
)


print(
    "Machine Decision:",
    review_result["decision"],
)

print(
    "Priority:",
    review_result["priority"],
)

print(
    "Human Action:",
    human_review["human_action"],
)

print(
    "Audit Events:",
    len(history),
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

assert (
    history[1]["details"][
        "human_action"
    ]
    == "APPROVE"
)


print("[PASS]")


# ==========================================================
# TEST 3 — CRITICAL ERROR → HUMAN REJECTS
# ==========================================================

print()
print("=" * 72)
print(
    "TEST 3 — CRITICAL ERROR → HUMAN REJECTS"
)
print("=" * 72)


document_id = "DOC-E2E-003"


anomaly_result = (
    build_anomaly_result(
        issues=[
            error(
                "MISSING_CRITICAL_FIELD"
            )
        ],
        valid=False,
    )
)


review_result = (
    review_decision_service
    .decide(
        anomaly_result
    )
)


assert (
    review_result["decision"]
    == "REVIEW_REQUIRED"
)

assert (
    review_result["priority"]
    == "HIGH"
)


audit_service.log_machine_decision(
    document_id=document_id,
    review_result=review_result,
)


human_review = (
    human_review_service
    .submit_review(
        document_id=document_id,
        reviewer_id="REVIEWER-002",
        review_result=review_result,
        action="REJECT",
        notes=(
            "Required document field "
            "could not be verified."
        ),
    )
)


audit_service.log_human_review(
    human_review
)


history = (
    audit_service
    .get_document_history(
        document_id
    )
)


print(
    "Priority:",
    review_result["priority"],
)

print(
    "Human Action:",
    human_review["human_action"],
)

print(
    "Audit Events:",
    len(history),
)


assert len(history) == 2

assert (
    human_review["human_action"]
    == "REJECT"
)


print("[PASS]")


# ==========================================================
# TEST 4 — INVALID FIELD → HUMAN CORRECTS
# ==========================================================

print()
print("=" * 72)
print(
    "TEST 4 — INVALID FIELD → HUMAN CORRECTS"
)
print("=" * 72)


document_id = "DOC-E2E-004"


anomaly_result = (
    build_anomaly_result(
        issues=[
            warning(
                "EXTRACTED_FIELD_INVALID_EVIDENCE"
            )
        ]
    )
)


review_result = (
    review_decision_service
    .decide(
        anomaly_result
    )
)


assert (
    review_result["priority"]
    == "MEDIUM"
)


audit_service.log_machine_decision(
    document_id=document_id,
    review_result=review_result,
)


human_review = (
    human_review_service
    .submit_review(
        document_id=document_id,
        reviewer_id="REVIEWER-003",
        review_result=review_result,
        action="CORRECT",
        corrections={
            "date_of_birth":
                "2006-08-23"
        },
        notes=(
            "Date of birth manually "
            "verified from document."
        ),
    )
)


audit_service.log_human_review(
    human_review
)


history = (
    audit_service
    .get_document_history(
        document_id
    )
)


print(
    "Human Action:",
    human_review["human_action"],
)

print(
    "Corrections:",
    human_review["corrections"],
)

print(
    "Audit Events:",
    len(history),
)


assert (
    human_review["human_action"]
    == "CORRECT"
)

assert (
    human_review["corrections"][
        "date_of_birth"
    ]
    == "2006-08-23"
)

assert len(history) == 2


audit_corrections = (
    history[1]["details"][
        "corrections"
    ]
)


assert (
    audit_corrections[
        "date_of_birth"
    ]
    == "2006-08-23"
)


print("[PASS]")


# ==========================================================
# TEST 5 — MACHINE REASON PRESERVED AFTER HUMAN REVIEW
# ==========================================================

print()
print("=" * 72)
print(
    "TEST 5 — MACHINE REASON PRESERVED"
)
print("=" * 72)


history = (
    audit_service
    .get_document_history(
        "DOC-E2E-004"
    )
)


machine_event = history[0]

human_event = history[1]


machine_reasons = (
    machine_event[
        "details"
    ]["reason_codes"]
)


human_machine_reasons = (
    human_event[
        "details"
    ]["machine_reason_codes"]
)


print(
    "Original Machine Reasons:",
    machine_reasons,
)

print(
    "Preserved in Human Review:",
    human_machine_reasons,
)


assert (
    machine_reasons
    == human_machine_reasons
)

assert (
    machine_reasons
    == [
        "EXTRACTED_FIELD_INVALID_EVIDENCE"
    ]
)


print("[PASS]")


# ==========================================================
# TEST 6 — DOCUMENT HISTORIES REMAIN ISOLATED
# ==========================================================

print()
print("=" * 72)
print(
    "TEST 6 — DOCUMENT HISTORY ISOLATION"
)
print("=" * 72)


history_1 = (
    audit_service
    .get_document_history(
        "DOC-E2E-001"
    )
)

history_2 = (
    audit_service
    .get_document_history(
        "DOC-E2E-002"
    )
)

history_3 = (
    audit_service
    .get_document_history(
        "DOC-E2E-003"
    )
)

history_4 = (
    audit_service
    .get_document_history(
        "DOC-E2E-004"
    )
)


print(
    "DOC-E2E-001:",
    len(history_1),
)

print(
    "DOC-E2E-002:",
    len(history_2),
)

print(
    "DOC-E2E-003:",
    len(history_3),
)

print(
    "DOC-E2E-004:",
    len(history_4),
)


assert len(history_1) == 1
assert len(history_2) == 2
assert len(history_3) == 2
assert len(history_4) == 2


print("[PASS]")


# ==========================================================
# FINAL
# ==========================================================

print()
print("=" * 72)
print(
    "ALL PHASE 5 END-TO-END TESTS PASSED"
)
print("=" * 72)