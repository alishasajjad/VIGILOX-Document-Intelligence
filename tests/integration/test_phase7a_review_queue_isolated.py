from datetime import (
    datetime,
    timedelta,
    timezone,
)
from uuid import uuid4

from database.database import (
    SessionLocal,
)

from database.models import (
    DocumentModel,
)

from backend.app.services.query_service import (
    DocumentQueryService,
)

from database.repositories import (
    DocumentAnalysisRepository,
    DocumentRepository,
    HumanReviewRepository,
)


# ==========================================================
# TEST PIPELINE RESULT
# ==========================================================

def build_pipeline_result(
    *,
    document_type: str,
    decision: str,
    priority: str,
    reason_codes: list[str] | None = None,
) -> dict:

    reason_codes = reason_codes or []

    issues = [
        {
            "code": code,
            "severity": (
                "ERROR"
                if priority == "HIGH"
                else "WARNING"
            ),
            "field": None,
            "message": f"Phase 7A test issue: {code}",
        }
        for code in reason_codes
    ]

    return {
        "extraction": {
            "document_type": document_type,
        },

        "ocr_lines": [],

        "evidence_flags": [],

        "field_confidence": {},

        "date_validation": {
            "reference_date": "2026-08-19",
            "date_fields": {},
            "expiry": {
                "value": None,
                "status": "NOT_AVAILABLE",
                "days_until_expiry": None,
            },
            "logical_issues": [],
            "valid": True,
        },

        "anomaly_validation": {
            "document_type": document_type,
            "valid": True,
            "has_anomalies": bool(reason_codes),
            "error_count": (
                len(reason_codes)
                if priority == "HIGH"
                else 0
            ),
            "warning_count": (
                len(reason_codes)
                if priority != "HIGH"
                else 0
            ),
            "issues": issues,
        },

        "review_decision": {
            "decision": decision,
            "review_required": (
                decision == "REVIEW_REQUIRED"
            ),
            "priority": priority,
            "reason_codes": reason_codes,
            "issues": issues,
        },
    }


# ==========================================================
# ASSERTION HELPERS
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


def get_test_items(
    queue: dict,
    document_ids: set[str],
) -> list[dict]:

    return [
        item
        for item in queue["documents"]
        if item["document_id"] in document_ids
    ]


def get_ids(
    queue: dict,
) -> set[str]:

    return {
        item["document_id"]
        for item in queue["documents"]
    }


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("=" * 72)
    print(
        "PHASE 7A — ISOLATED REVIEW QUEUE "
        "POSTGRESQL TEST"
    )
    print("=" * 72)

    created_document_ids: list[str] = []

    try:

        # ==================================================
        # CREATE TEMPORARY TEST DATA
        # ==================================================

        with SessionLocal() as session:

            document_repository = (
                DocumentRepository(
                    session
                )
            )

            analysis_repository = (
                DocumentAnalysisRepository(
                    session
                )
            )

            human_review_repository = (
                HumanReviewRepository(
                    session
                )
            )

            base_time = datetime(
                2026,
                8,
                19,
                8,
                0,
                0,
                tzinfo=timezone.utc,
            )

            # ==============================================
            # HIGH PRIORITY
            # ==============================================

            high_document = (
                document_repository
                .create_document(
                    original_filename=(
                        "phase7a_high_guard.jpg"
                    ),
                    content_type="image/jpeg",
                    document_type="guard_license",
                )
            )

            high_document.created_at = (
                base_time
                + timedelta(minutes=5)
            )

            analysis_repository.create_analysis(
                document_id=high_document.id,
                pipeline_result=(
                    build_pipeline_result(
                        document_type="guard_license",
                        decision="REVIEW_REQUIRED",
                        priority="HIGH",
                        reason_codes=[
                            "MISSING_CRITICAL_FIELD"
                        ],
                    )
                ),
            )

            created_document_ids.append(
                high_document.id
            )

            # ==============================================
            # MEDIUM OLD
            # ==============================================

            medium_old_document = (
                document_repository
                .create_document(
                    original_filename=(
                        "phase7a_medium_old.jpg"
                    ),
                    content_type="image/jpeg",
                    document_type="guard_license",
                )
            )

            medium_old_document.created_at = (
                base_time
                + timedelta(minutes=1)
            )

            analysis_repository.create_analysis(
                document_id=medium_old_document.id,
                pipeline_result=(
                    build_pipeline_result(
                        document_type="guard_license",
                        decision="REVIEW_REQUIRED",
                        priority="MEDIUM",
                        reason_codes=[
                            "DOCUMENT_EXPIRED"
                        ],
                    )
                ),
            )

            created_document_ids.append(
                medium_old_document.id
            )

            # ==============================================
            # MEDIUM NEW
            # ==============================================

            medium_new_document = (
                document_repository
                .create_document(
                    original_filename=(
                        "phase7a_medium_new.jpg"
                    ),
                    content_type="image/jpeg",
                    document_type="guard_license",
                )
            )

            medium_new_document.created_at = (
                base_time
                + timedelta(minutes=3)
            )

            analysis_repository.create_analysis(
                document_id=medium_new_document.id,
                pipeline_result=(
                    build_pipeline_result(
                        document_type="guard_license",
                        decision="REVIEW_REQUIRED",
                        priority="MEDIUM",
                        reason_codes=[
                            "INVALID_EVIDENCE"
                        ],
                    )
                ),
            )

            created_document_ids.append(
                medium_new_document.id
            )

            # ==============================================
            # LOW ID CARD
            # ==============================================

            low_document = (
                document_repository
                .create_document(
                    original_filename=(
                        "phase7a_low_id.jpg"
                    ),
                    content_type="image/jpeg",
                    document_type="id_card",
                )
            )

            low_document.created_at = (
                base_time
                + timedelta(minutes=2)
            )

            analysis_repository.create_analysis(
                document_id=low_document.id,
                pipeline_result=(
                    build_pipeline_result(
                        document_type="id_card",
                        decision="REVIEW_REQUIRED",
                        priority="LOW",
                        reason_codes=[
                            "EXPIRING_SOON"
                        ],
                    )
                ),
            )

            created_document_ids.append(
                low_document.id
            )

            # ==============================================
            # AUTO ACCEPT
            # MUST NOT APPEAR
            # ==============================================

            auto_document = (
                document_repository
                .create_document(
                    original_filename=(
                        "phase7a_auto_id.jpg"
                    ),
                    content_type="image/jpeg",
                    document_type="id_card",
                )
            )

            auto_document.created_at = (
                base_time
            )

            analysis_repository.create_analysis(
                document_id=auto_document.id,
                pipeline_result=(
                    build_pipeline_result(
                        document_type="id_card",
                        decision="AUTO_ACCEPT",
                        priority="NONE",
                        reason_codes=[],
                    )
                ),
            )

            created_document_ids.append(
                auto_document.id
            )

            # ==============================================
            # ALREADY HUMAN REVIEWED
            # MUST NOT APPEAR
            # ==============================================

            reviewed_document = (
                document_repository
                .create_document(
                    original_filename=(
                        "phase7a_reviewed_sia.jpg"
                    ),
                    content_type="image/jpeg",
                    document_type="sia_badge",
                )
            )

            reviewed_document.created_at = (
                base_time
            )

            analysis_repository.create_analysis(
                document_id=reviewed_document.id,
                pipeline_result=(
                    build_pipeline_result(
                        document_type="sia_badge",
                        decision="REVIEW_REQUIRED",
                        priority="HIGH",
                        reason_codes=[
                            "INVALID_DOCUMENT"
                        ],
                    )
                ),
            )

            human_review_repository.create_review(
                review_result={
                    "review_id": str(
                        uuid4()
                    ),

                    "document_id":
                        reviewed_document.id,

                    "reviewer_id":
                        "phase7a-reviewer",

                    "machine_decision":
                        "REVIEW_REQUIRED",

                    "machine_priority":
                        "HIGH",

                    "machine_reason_codes": [
                        "INVALID_DOCUMENT"
                    ],

                    "human_action":
                        "APPROVE",

                    "corrections":
                        {},

                    "notes":
                        "Phase 7A test review.",

                    "reviewed_at": (
                        datetime.now(
                            timezone.utc
                        ).isoformat()
                    ),
                }
            )

            created_document_ids.append(
                reviewed_document.id
            )

            session.commit()

        print(
            "[OK] Temporary Phase 7A "
            "test data created"
        )

        # ==================================================
        # IDS USED BY TEST
        # ==================================================

        pending_test_ids = {
            high_document.id,
            medium_old_document.id,
            medium_new_document.id,
            low_document.id,
        }

        all_test_ids = set(
            created_document_ids
        )

        # ==================================================
        # QUERY SERVICE
        # ==================================================

        query_service = (
            DocumentQueryService()
        )

        # ==================================================
        # TEST 1 — DEFAULT QUEUE
        # ==================================================

        queue = (
            query_service
            .get_review_queue()
        )

        queue_ids = get_ids(
            queue
        )

        test_items = get_test_items(
            queue,
            pending_test_ids,
        )

        test_filenames = [
            item["original_filename"]
            for item in test_items
        ]

        expected_filenames = [
            "phase7a_high_guard.jpg",
            "phase7a_medium_old.jpg",
            "phase7a_medium_new.jpg",
            "phase7a_low_id.jpg",
        ]

        assert_equal(
            test_filenames,
            expected_filenames,
            (
                "Phase 7A pending queue "
                "ordering is incorrect."
            ),
        )

        print(
            "[PASS] REVIEW_REQUIRED "
            "test documents returned"
        )

        # ==================================================
        # AUTO ACCEPT EXCLUSION
        # ==================================================

        assert_equal(
            auto_document.id
            in queue_ids,
            False,
            (
                "AUTO_ACCEPT document "
                "must not appear in queue."
            ),
        )

        print(
            "[PASS] AUTO_ACCEPT excluded"
        )

        # ==================================================
        # HUMAN REVIEWED EXCLUSION
        # ==================================================

        assert_equal(
            reviewed_document.id
            in queue_ids,
            False,
            (
                "Already reviewed document "
                "must not appear in queue."
            ),
        )

        print(
            "[PASS] Human-reviewed "
            "document excluded"
        )

        # ==================================================
        # ORDERING
        # ==================================================

        assert_equal(
            test_filenames,
            expected_filenames,
            "Priority ordering failed.",
        )

        print(
            "[PASS] Priority ordering "
            "HIGH → MEDIUM → LOW"
        )

        medium_names = [
            item["original_filename"]
            for item in test_items
            if (
                item["review_priority"]
                == "MEDIUM"
            )
        ]

        assert_equal(
            medium_names,
            [
                "phase7a_medium_old.jpg",
                "phase7a_medium_new.jpg",
            ],
            (
                "Oldest-first ordering "
                "inside MEDIUM failed."
            ),
        )

        print(
            "[PASS] Oldest-first ordering "
            "within same priority"
        )

        # ==================================================
        # TEST 2 — PRIORITY FILTER
        # ==================================================

        high_queue = (
            query_service
            .get_review_queue(
                priority="high"
            )
        )

        high_test_items = (
            get_test_items(
                high_queue,
                all_test_ids,
            )
        )

        assert_equal(
            len(high_test_items),
            1,
            (
                "HIGH filter should return "
                "exactly one Phase 7A "
                "test document."
            ),
        )

        assert_equal(
            high_test_items[0][
                "document_id"
            ],
            high_document.id,
            (
                "Incorrect HIGH priority "
                "test document."
            ),
        )

        assert_equal(
            high_queue[
                "filters"
            ][
                "priority"
            ],
            "HIGH",
            (
                "Priority normalization "
                "failed."
            ),
        )

        print(
            "[PASS] Priority filter"
        )

        # ==================================================
        # TEST 3 — DOCUMENT TYPE FILTER
        # ==================================================

        id_queue = (
            query_service
            .get_review_queue(
                document_type="ID_CARD"
            )
        )

        id_test_items = (
            get_test_items(
                id_queue,
                all_test_ids,
            )
        )

        assert_equal(
            len(id_test_items),
            1,
            (
                "ID_CARD filter should "
                "return exactly one pending "
                "Phase 7A test document."
            ),
        )

        assert_equal(
            id_test_items[0][
                "document_id"
            ],
            low_document.id,
            (
                "Incorrect ID-card test "
                "document returned."
            ),
        )

        assert_equal(
            id_queue[
                "filters"
            ][
                "document_type"
            ],
            "id_card",
            (
                "Document type "
                "normalization failed."
            ),
        )

        print(
            "[PASS] Document-type filter"
        )

        # ==================================================
        # TEST 4 — COMBINED FILTER
        # ==================================================

        combined_queue = (
            query_service
            .get_review_queue(
                priority="medium",
                document_type=(
                    "guard_license"
                ),
            )
        )

        combined_test_items = (
            get_test_items(
                combined_queue,
                all_test_ids,
            )
        )

        combined_names = [
            item["original_filename"]
            for item
            in combined_test_items
        ]

        assert_equal(
            combined_names,
            [
                "phase7a_medium_old.jpg",
                "phase7a_medium_new.jpg",
            ],
            (
                "Combined filter failed."
            ),
        )

        print(
            "[PASS] Combined priority + "
            "document-type filter"
        )

        # ==================================================
        # TEST 5 — EMPTY TEST RESULT
        # ==================================================

        empty_queue = (
            query_service
            .get_review_queue(
                priority="HIGH",
                document_type="id_card",
            )
        )

        empty_test_items = (
            get_test_items(
                empty_queue,
                all_test_ids,
            )
        )

        assert_equal(
            empty_test_items,
            [],
            (
                "No Phase 7A HIGH priority "
                "ID card should exist."
            ),
        )

        print(
            "[PASS] Empty filtered "
            "Phase 7A test result"
        )

        # ==================================================
        # EXISTING DATABASE DATA NOTE
        # ==================================================

        non_test_items = [
            item
            for item in queue[
                "documents"
            ]
            if (
                item["document_id"]
                not in all_test_ids
            )
        ]

        print()
        print(
            "Existing non-test pending "
            f"documents in database: "
            f"{len(non_test_items)}"
        )

        for item in non_test_items:

            print(
                "  - "
                f"{item['original_filename']} "
                f"({item['review_priority']})"
            )

        # ==================================================
        # SUCCESS
        # ==================================================

        print()
        print("=" * 72)
        print(
            "[PASS] PHASE 7A REVIEW QUEUE "
            "DATABASE TEST PASSED"
        )
        print("=" * 72)

    finally:

        # ==================================================
        # CLEANUP
        # ==================================================

        if created_document_ids:

            with SessionLocal() as session:

                for document_id in (
                    created_document_ids
                ):

                    document = (
                        session.get(
                            DocumentModel,
                            document_id,
                        )
                    )

                    if document is not None:

                        session.delete(
                            document
                        )

                session.commit()

            print()
            print(
                "[CLEANUP] Temporary "
                "Phase 7A test documents "
                "removed."
            )


if __name__ == "__main__":

    main()