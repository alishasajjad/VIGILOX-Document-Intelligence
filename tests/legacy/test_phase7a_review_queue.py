from datetime import (
    datetime,
    timedelta,
    timezone,
)

from database.database import (
    SessionLocal,
)

from database.models import (
    DocumentModel,
)

from database.repositories import (
    DocumentAnalysisRepository,
    DocumentRepository,
    HumanReviewRepository,
)

from backend.app.services.query_service import (
    DocumentQueryService,
)


# ==========================================================
# PIPELINE RESULT BUILDER
# ==========================================================

def build_pipeline_result(
    *,
    document_type: str,
    decision: str,
    priority: str,
    reason_codes: list[str] | None = None,
) -> dict:

    reason_codes = (
        reason_codes
        or []
    )


    issues = [

        {
            "code":
                code,

            "severity":
                (
                    "ERROR"
                    if priority == "HIGH"
                    else "WARNING"
                ),

            "field":
                None,

            "message":
                f"Test issue: {code}",
        }

        for code
        in reason_codes
    ]


    return {

        "extraction": {
            "document_type":
                document_type,
        },

        "ocr_lines":
            [],

        "evidence_flags":
            [],

        "field_confidence":
            {},

        "date_validation": {
            "reference_date":
                "2026-08-19",

            "date_fields":
                {},

            "expiry": {
                "value":
                    None,

                "status":
                    "NOT_AVAILABLE",

                "days_until_expiry":
                    None,
            },

            "logical_issues":
                [],

            "valid":
                True,
        },

        "anomaly_validation": {

            "document_type":
                document_type,

            "valid":
                True,

            "has_anomalies":
                bool(
                    reason_codes
                ),

            "error_count":
                (
                    len(reason_codes)
                    if priority == "HIGH"
                    else 0
                ),

            "warning_count":
                (
                    len(reason_codes)
                    if priority != "HIGH"
                    else 0
                ),

            "issues":
                issues,
        },

        "review_decision": {

            "decision":
                decision,

            "review_required":
                (
                    decision
                    == "REVIEW_REQUIRED"
                ),

            "priority":
                priority,

            "reason_codes":
                reason_codes,

            "issues":
                issues,
        },
    }


# ==========================================================
# ASSERTION HELPER
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


# ==========================================================
# MAIN TEST
# ==========================================================

def main():

    print()
    print(
        "=" * 72
    )

    print(
        "PHASE 7A — REVIEW QUEUE "
        "POSTGRESQL TEST"
    )

    print(
        "=" * 72
    )


    created_document_ids = []


    try:

        # ==================================================
        # CREATE TEST DATA
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
            # 1. HIGH PRIORITY — SHOULD APPEAR
            # ==============================================

            high_document = (
                document_repository
                .create_document(
                    original_filename=(
                        "phase7a_high_guard.jpg"
                    ),

                    content_type=(
                        "image/jpeg"
                    ),

                    document_type=(
                        "guard_license"
                    ),
                )
            )


            high_document.created_at = (
                base_time
                + timedelta(
                    minutes=5
                )
            )


            analysis_repository.create_analysis(
                document_id=(
                    high_document.id
                ),

                pipeline_result=(
                    build_pipeline_result(
                        document_type=(
                            "guard_license"
                        ),

                        decision=(
                            "REVIEW_REQUIRED"
                        ),

                        priority=(
                            "HIGH"
                        ),

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
            # 2. MEDIUM OLD — SHOULD APPEAR FIRST
            #    AMONG MEDIUM DOCUMENTS
            # ==============================================

            medium_old_document = (
                document_repository
                .create_document(
                    original_filename=(
                        "phase7a_medium_old.jpg"
                    ),

                    content_type=(
                        "image/jpeg"
                    ),

                    document_type=(
                        "guard_license"
                    ),
                )
            )


            medium_old_document.created_at = (
                base_time
                + timedelta(
                    minutes=1
                )
            )


            analysis_repository.create_analysis(
                document_id=(
                    medium_old_document.id
                ),

                pipeline_result=(
                    build_pipeline_result(
                        document_type=(
                            "guard_license"
                        ),

                        decision=(
                            "REVIEW_REQUIRED"
                        ),

                        priority=(
                            "MEDIUM"
                        ),

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
            # 3. MEDIUM NEW — SHOULD APPEAR AFTER
            #    MEDIUM OLD
            # ==============================================

            medium_new_document = (
                document_repository
                .create_document(
                    original_filename=(
                        "phase7a_medium_new.jpg"
                    ),

                    content_type=(
                        "image/jpeg"
                    ),

                    document_type=(
                        "guard_license"
                    ),
                )
            )


            medium_new_document.created_at = (
                base_time
                + timedelta(
                    minutes=3
                )
            )


            analysis_repository.create_analysis(
                document_id=(
                    medium_new_document.id
                ),

                pipeline_result=(
                    build_pipeline_result(
                        document_type=(
                            "guard_license"
                        ),

                        decision=(
                            "REVIEW_REQUIRED"
                        ),

                        priority=(
                            "MEDIUM"
                        ),

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
            # 4. LOW ID CARD — SHOULD APPEAR
            # ==============================================

            low_document = (
                document_repository
                .create_document(
                    original_filename=(
                        "phase7a_low_id.jpg"
                    ),

                    content_type=(
                        "image/jpeg"
                    ),

                    document_type=(
                        "id_card"
                    ),
                )
            )


            low_document.created_at = (
                base_time
                + timedelta(
                    minutes=2
                )
            )


            analysis_repository.create_analysis(
                document_id=(
                    low_document.id
                ),

                pipeline_result=(
                    build_pipeline_result(
                        document_type=(
                            "id_card"
                        ),

                        decision=(
                            "REVIEW_REQUIRED"
                        ),

                        priority=(
                            "LOW"
                        ),

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
            # 5. AUTO ACCEPT — MUST NOT APPEAR
            # ==============================================

            auto_document = (
                document_repository
                .create_document(
                    original_filename=(
                        "phase7a_auto_id.jpg"
                    ),

                    content_type=(
                        "image/jpeg"
                    ),

                    document_type=(
                        "id_card"
                    ),
                )
            )


            auto_document.created_at = (
                base_time
            )


            analysis_repository.create_analysis(
                document_id=(
                    auto_document.id
                ),

                pipeline_result=(
                    build_pipeline_result(
                        document_type=(
                            "id_card"
                        ),

                        decision=(
                            "AUTO_ACCEPT"
                        ),

                        priority=(
                            "NONE"
                        ),

                        reason_codes=[],
                    )
                ),
            )


            created_document_ids.append(
                auto_document.id
            )


            # ==============================================
            # 6. REVIEW_REQUIRED BUT ALREADY HUMAN REVIEWED
            #    MUST NOT APPEAR
            # ==============================================

            reviewed_document = (
                document_repository
                .create_document(
                    original_filename=(
                        "phase7a_reviewed_sia.jpg"
                    ),

                    content_type=(
                        "image/jpeg"
                    ),

                    document_type=(
                        "sia_badge"
                    ),
                )
            )


            reviewed_document.created_at = (
                base_time
            )


            analysis_repository.create_analysis(
                document_id=(
                    reviewed_document.id
                ),

                pipeline_result=(
                    build_pipeline_result(
                        document_type=(
                            "sia_badge"
                        ),

                        decision=(
                            "REVIEW_REQUIRED"
                        ),

                        priority=(
                            "HIGH"
                        ),

                        reason_codes=[
                            "INVALID_DOCUMENT"
                        ],
                    )
                ),
            )


            human_review_repository.create_review(
                review_result={

                    "review_id":
                        (
                            "phase7a-test-review"
                        ),

                    "document_id":
                        reviewed_document.id,

                    "reviewer_id":
                        "phase7a-reviewer",

                    "machine_decision":
                        "REVIEW_REQUIRED",

                    "machine_priority":
                        "HIGH",

                    "machine_reason_codes":
                        [
                            "INVALID_DOCUMENT"
                        ],

                    "human_action":
                        "APPROVE",

                    "corrections":
                        {},

                    "notes":
                        (
                            "Phase 7A test review."
                        ),

                    "reviewed_at":
                        (
                            datetime.now(
                                timezone.utc
                            )
                            .isoformat()
                        ),
                }
            )


            created_document_ids.append(
                reviewed_document.id
            )


            session.commit()


        print(
            "[OK] Test data created"
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


        queue_filenames = [

            item[
                "original_filename"
            ]

            for item
            in queue[
                "documents"
            ]
        ]


        expected_queue = [
            "phase7a_high_guard.jpg",
            "phase7a_medium_old.jpg",
            "phase7a_medium_new.jpg",
            "phase7a_low_id.jpg",
        ]


        assert_equal(
            queue_filenames,
            expected_queue,
            (
                "Default queue ordering "
                "is incorrect."
            ),
        )


        assert_equal(
            queue[
                "total"
            ],
            4,
            (
                "Default queue should "
                "contain 4 pending cases."
            ),
        )


        print(
            "[PASS] REVIEW_REQUIRED "
            "documents returned"
        )


        print(
            "[PASS] AUTO_ACCEPT excluded"
        )


        print(
            "[PASS] Human-reviewed "
            "document excluded"
        )


        print(
            "[PASS] Priority ordering "
            "HIGH → MEDIUM → LOW"
        )


        print(
            "[PASS] Oldest-first ordering "
            "within MEDIUM"
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


        assert_equal(
            high_queue[
                "total"
            ],
            1,
            (
                "HIGH priority filter "
                "should return 1 item."
            ),
        )


        assert_equal(
            high_queue[
                "documents"
            ][0][
                "original_filename"
            ],
            "phase7a_high_guard.jpg",
            (
                "Incorrect HIGH priority "
                "document returned."
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
                "Priority filter was not "
                "normalized correctly."
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
                document_type=(
                    "ID_CARD"
                )
            )
        )


        assert_equal(
            id_queue[
                "total"
            ],
            1,
            (
                "ID-card filter should "
                "return 1 pending item."
            ),
        )


        assert_equal(
            id_queue[
                "documents"
            ][0][
                "original_filename"
            ],
            "phase7a_low_id.jpg",
            (
                "Incorrect ID-card queue "
                "item returned."
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
                "Document-type filter was "
                "not normalized correctly."
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


        combined_names = [

            item[
                "original_filename"
            ]

            for item
            in combined_queue[
                "documents"
            ]
        ]


        assert_equal(
            combined_names,
            [
                "phase7a_medium_old.jpg",
                "phase7a_medium_new.jpg",
            ],
            (
                "Combined priority + "
                "document-type filter "
                "is incorrect."
            ),
        )


        print(
            "[PASS] Combined filters"
        )


        # ==================================================
        # TEST 5 — EMPTY QUEUE RESULT
        # ==================================================

        empty_queue = (
            query_service
            .get_review_queue(
                priority="HIGH",
                document_type="id_card",
            )
        )


        assert_equal(
            empty_queue[
                "total"
            ],
            0,
            (
                "Expected an empty "
                "filtered queue."
            ),
        )


        assert_equal(
            empty_queue[
                "documents"
            ],
            [],
            (
                "Empty queue documents "
                "should be []."
            ),
        )


        print(
            "[PASS] Empty queue response"
        )


        # ==================================================
        # FINAL SUCCESS
        # ==================================================

        print()
        print(
            "=" * 72
        )

        print(
            "[PASS] PHASE 7A REVIEW QUEUE "
            "DATABASE TEST PASSED"
        )

        print(
            "=" * 72
        )


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
                "[CLEANUP] Phase 7A test "
                "documents removed."
            )


if __name__ == "__main__":

    main()