from sqlalchemy import (
    select,
)

from database.database import (
    SessionLocal,
)

from database.models import (
    DocumentAnalysisModel,
    DocumentModel,
)

from backend.app.services.persistence_service import (
    PersistenceService,
)

from backend.app.services.query_service import (
    DocumentQueryService,
)

from backend.app.services.human_review_service import (
    HumanReviewService,
)


# ==========================================================
# BASE MACHINE EXTRACTION
# ==========================================================

MACHINE_VALUES = {
    "document_type":
        "guard_license",

    "full_name":
        "SAMPLE,JANE",

    "licence_number":
        "12345678",

    "id_number":
        None,

    "expiry_date":
        "2026-01-01",

    "date_of_birth":
        "1990-01-01",

    "issue_date":
        "2025-01-01",

    "issuer":
        "TX DPS",
}


# ==========================================================
# ASSERT HELPERS
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


def assert_true(
    condition: bool,
    message: str,
):

    if not condition:

        raise AssertionError(
            message
        )


# ==========================================================
# BUILD EXTRACTION
# ==========================================================

def build_extraction() -> dict:

    return {
        "document_type":
            MACHINE_VALUES[
                "document_type"
            ],

        "full_name": {
            "value":
                MACHINE_VALUES[
                    "full_name"
                ],

            "source_line_ids": [
                "L14"
            ],
        },

        "licence_number": {
            "value":
                MACHINE_VALUES[
                    "licence_number"
                ],

            "source_line_ids": [
                "L5",
                "L6",
            ],
        },

        "id_number": {
            "value":
                None,

            "source_line_ids":
                [],
        },

        "expiry_date": {
            "value":
                MACHINE_VALUES[
                    "expiry_date"
                ],

            "source_line_ids": [
                "L8",
                "L9",
            ],
        },

        "date_of_birth": {
            "value":
                MACHINE_VALUES[
                    "date_of_birth"
                ],

            "source_line_ids": [
                "L11",
                "L12",
            ],
        },

        "issue_date": {
            "value":
                MACHINE_VALUES[
                    "issue_date"
                ],

            "source_line_ids": [
                "L4"
            ],
        },

        "issuer": {
            "value":
                MACHINE_VALUES[
                    "issuer"
                ],

            "source_line_ids": [
                "L15"
            ],
        },
    }


# ==========================================================
# BUILD OCR LINES
# ==========================================================

def build_ocr_lines() -> list[dict]:

    return [
        {
            "line_id":
                "L4",

            "text":
                "PRINTDATE 01/01/2025",

            "confidence":
                0.99,

            "bbox":
                [],
        },

        {
            "line_id":
                "L5",

            "text":
                "LICENSE",

            "confidence":
                0.99,

            "bbox":
                [],
        },

        {
            "line_id":
                "L6",

            "text":
                "12345678",

            "confidence":
                0.98,

            "bbox":
                [],
        },

        {
            "line_id":
                "L8",

            "text":
                "EXPIRES",

            "confidence":
                0.99,

            "bbox":
                [],
        },

        {
            "line_id":
                "L9",

            "text":
                "01/01/2026",

            "confidence":
                0.97,

            "bbox":
                [],
        },

        {
            "line_id":
                "L11",

            "text":
                "DOB",

            "confidence":
                0.99,

            "bbox":
                [],
        },

        {
            "line_id":
                "L12",

            "text":
                "01/01/1990",

            "confidence":
                0.98,

            "bbox":
                [],
        },

        {
            "line_id":
                "L14",

            "text":
                "SAMPLE,JANE",

            "confidence":
                0.99,

            "bbox":
                [],
        },

        {
            "line_id":
                "L15",

            "text":
                "ISSUED BY TX DPS",

            "confidence":
                0.99,

            "bbox":
                [],
        },
    ]


# ==========================================================
# BUILD PIPELINE RESULT
# ==========================================================

def build_pipeline_result(
    *,
    machine_decision: str,
) -> dict:

    review_required = (
        machine_decision
        == "REVIEW_REQUIRED"
    )


    priority = (
        "MEDIUM"
        if review_required
        else "NONE"
    )


    reason_codes = (
        [
            "DOCUMENT_EXPIRED"
        ]
        if review_required
        else []
    )


    return {
        "extraction":
            build_extraction(),

        "ocr_lines":
            build_ocr_lines(),

        "evidence_flags":
            [],

        "field_confidence": {
            "full_name": {
                "value":
                    "SAMPLE,JANE",

                "confidence":
                    0.99,

                "status":
                    "VALID",
            },

            "licence_number": {
                "value":
                    "12345678",

                "confidence":
                    0.98,

                "status":
                    "VALID",
            },

            "id_number": {
                "value":
                    None,

                "confidence":
                    None,

                "status":
                    "NOT_EXTRACTED",
            },

            "expiry_date": {
                "value":
                    "2026-01-01",

                "confidence":
                    0.97,

                "status":
                    "VALID",
            },

            "date_of_birth": {
                "value":
                    "1990-01-01",

                "confidence":
                    0.98,

                "status":
                    "VALID",
            },

            "issue_date": {
                "value":
                    "2025-01-01",

                "confidence":
                    0.99,

                "status":
                    "VALID",
            },

            "issuer": {
                "value":
                    "TX DPS",

                "confidence":
                    0.99,

                "status":
                    "VALID",
            },
        },

        "date_validation": {
            "reference_date":
                "2026-08-19",

            "date_fields":
                {},

            "expiry": {
                "value":
                    "2026-01-01",

                "status":
                    (
                        "EXPIRED"
                        if review_required
                        else "VALID"
                    ),
            },

            "logical_issues":
                [],

            "valid":
                True,
        },

        "anomaly_validation": {
            "document_type":
                "guard_license",

            "valid":
                True,

            "has_anomalies":
                review_required,

            "error_count":
                0,

            "warning_count":
                (
                    1
                    if review_required
                    else 0
                ),

            "issues":
                (
                    [
                        {
                            "code":
                                "DOCUMENT_EXPIRED",

                            "severity":
                                "WARNING",

                            "field":
                                "expiry_date",

                            "message":
                                "Document is expired.",
                        }
                    ]
                    if review_required
                    else []
                ),
        },

        "review_decision": {
            "decision":
                machine_decision,

            "review_required":
                review_required,

            "priority":
                priority,

            "reason_codes":
                reason_codes,

            "issues":
                [],
        },
    }


# ==========================================================
# CREATE TEST DOCUMENT
# ==========================================================

def create_document(
    persistence_service: PersistenceService,
    *,
    filename: str,
    machine_decision: str,
) -> str:

    stored = (
        persistence_service
        .save_processed_document(
            original_filename=(
                filename
            ),

            content_type=(
                "image/jpeg"
            ),

            pipeline_result=(
                build_pipeline_result(
                    machine_decision=(
                        machine_decision
                    )
                )
            ),
        )
    )


    return stored[
        "document_id"
    ]


# ==========================================================
# SUBMIT HUMAN REVIEW
# ==========================================================

def submit_review(
    *,
    persistence_service: PersistenceService,
    human_review_service: HumanReviewService,
    document_id: str,
    action: str,
    corrections: dict | None = None,
):

    machine_result = {
        "decision":
            "REVIEW_REQUIRED",

        "priority":
            "MEDIUM",

        "reason_codes": [
            "DOCUMENT_EXPIRED"
        ],
    }


    review_result = (
        human_review_service
        .submit_review(
            document_id=(
                document_id
            ),

            reviewer_id=(
                "phase7c-final-reviewer"
            ),

            review_result=(
                machine_result
            ),

            action=(
                action
            ),

            notes=(
                "Phase 7C.3 final "
                "record verification."
            ),

            corrections=(
                corrections
            ),
        )
    )


    return (
        persistence_service
        .save_human_review(
            review_result=(
                review_result
            )
        )
    )


# ==========================================================
# VERIFY MACHINE VALUES
# ==========================================================

def verify_machine_values(
    final_record: dict,
):

    assert_equal(
        final_record[
            "machine_values"
        ],
        MACHINE_VALUES,
        (
            "Final record machine_values "
            "must preserve the original "
            "machine extraction."
        ),
    )


# ==========================================================
# VERIFY MACHINE EXTRACTION IN DATABASE
# ==========================================================

def verify_raw_machine_extraction(
    document_id: str,
):

    with SessionLocal() as session:

        statement = (
            select(
                DocumentAnalysisModel
            )
            .where(
                DocumentAnalysisModel.document_id
                == document_id
            )
        )


        analysis = (
            session
            .scalars(
                statement
            )
            .one()
        )


        extraction = (
            analysis.extraction
        )


        assert_equal(
            extraction[
                "expiry_date"
            ][
                "value"
            ],
            "2026-01-01",
            (
                "Human review must not overwrite "
                "the stored machine expiry date."
            ),
        )


        assert_equal(
            extraction[
                "issuer"
            ][
                "value"
            ],
            "TX DPS",
            (
                "Human review must not overwrite "
                "the stored machine issuer."
            ),
        )


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("=" * 76)
    print(
        "PHASE 7C.3 — FINAL REVIEWED "
        "RECORD / EFFECTIVE VALUES TEST"
    )
    print("=" * 76)


    persistence_service = (
        PersistenceService()
    )


    query_service = (
        DocumentQueryService()
    )


    human_review_service = (
        HumanReviewService()
    )


    created_document_ids: list[str] = []


    try:

        # ==================================================
        # TEST 1 — AUTO ACCEPTED
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 1 — AUTO_ACCEPT → AUTO_ACCEPTED"
        )
        print("-" * 76)


        document_id = (
            create_document(
                persistence_service,
                filename=(
                    "phase7c_auto_accept.jpg"
                ),
                machine_decision=(
                    "AUTO_ACCEPT"
                ),
            )
        )


        created_document_ids.append(
            document_id
        )


        result = (
            query_service
            .get_document(
                document_id
            )
        )


        final_record = (
            result[
                "final_record"
            ]
        )


        assert_equal(
            result[
                "human_review"
            ],
            None,
            (
                "AUTO_ACCEPT document should "
                "not have a human review."
            ),
        )


        assert_equal(
            final_record[
                "final_status"
            ],
            "AUTO_ACCEPTED",
            (
                "AUTO_ACCEPT machine decision "
                "should become AUTO_ACCEPTED."
            ),
        )


        assert_equal(
            final_record[
                "is_final"
            ],
            True,
            "AUTO_ACCEPTED should be final.",
        )


        assert_equal(
            final_record[
                "is_usable"
            ],
            True,
            "AUTO_ACCEPTED should be usable.",
        )


        assert_equal(
            final_record[
                "effective_values"
            ],
            MACHINE_VALUES,
            (
                "AUTO_ACCEPTED effective values "
                "should equal machine values."
            ),
        )


        verify_machine_values(
            final_record
        )


        print(
            "[PASS] AUTO_ACCEPT produces "
            "final usable machine values"
        )


        # ==================================================
        # TEST 2 — PENDING REVIEW
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 2 — REVIEW_REQUIRED → PENDING_REVIEW"
        )
        print("-" * 76)


        document_id = (
            create_document(
                persistence_service,
                filename=(
                    "phase7c_pending_review.jpg"
                ),
                machine_decision=(
                    "REVIEW_REQUIRED"
                ),
            )
        )


        created_document_ids.append(
            document_id
        )


        result = (
            query_service
            .get_document(
                document_id
            )
        )


        final_record = (
            result[
                "final_record"
            ]
        )


        assert_equal(
            result[
                "human_review"
            ],
            None,
            (
                "Pending document should "
                "not yet have human review."
            ),
        )


        assert_equal(
            final_record[
                "final_status"
            ],
            "PENDING_REVIEW",
            (
                "REVIEW_REQUIRED without "
                "human action should remain "
                "PENDING_REVIEW."
            ),
        )


        assert_equal(
            final_record[
                "is_final"
            ],
            False,
            (
                "Pending review must not "
                "be considered final."
            ),
        )


        assert_equal(
            final_record[
                "is_usable"
            ],
            False,
            (
                "Pending review must not "
                "be considered usable."
            ),
        )


        assert_equal(
            final_record[
                "effective_values"
            ],
            None,
            (
                "Pending review must not "
                "expose final effective values."
            ),
        )


        verify_machine_values(
            final_record
        )


        print(
            "[PASS] REVIEW_REQUIRED remains "
            "non-final and non-usable"
        )


        # ==================================================
        # TEST 3 — APPROVED
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 3 — APPROVE → APPROVED"
        )
        print("-" * 76)


        document_id = (
            create_document(
                persistence_service,
                filename=(
                    "phase7c_approved.jpg"
                ),
                machine_decision=(
                    "REVIEW_REQUIRED"
                ),
            )
        )


        created_document_ids.append(
            document_id
        )


        submit_review(
            persistence_service=(
                persistence_service
            ),
            human_review_service=(
                human_review_service
            ),
            document_id=(
                document_id
            ),
            action=(
                "APPROVE"
            ),
        )


        result = (
            query_service
            .get_document(
                document_id
            )
        )


        human_review = (
            result[
                "human_review"
            ]
        )


        final_record = (
            result[
                "final_record"
            ]
        )


        assert_true(
            human_review
            is not None,
            (
                "APPROVE document should "
                "expose its human review."
            ),
        )


        assert_equal(
            human_review[
                "human_action"
            ],
            "APPROVE",
            (
                "Stored human action should "
                "be APPROVE."
            ),
        )


        assert_equal(
            final_record[
                "final_status"
            ],
            "APPROVED",
            (
                "APPROVE action should create "
                "APPROVED final status."
            ),
        )


        assert_equal(
            final_record[
                "is_final"
            ],
            True,
            "APPROVED should be final.",
        )


        assert_equal(
            final_record[
                "is_usable"
            ],
            True,
            "APPROVED should be usable.",
        )


        assert_equal(
            final_record[
                "effective_values"
            ],
            MACHINE_VALUES,
            (
                "APPROVED effective values "
                "should equal machine values."
            ),
        )


        verify_machine_values(
            final_record
        )


        print(
            "[PASS] APPROVE produces final "
            "usable machine values"
        )


        # ==================================================
        # TEST 4 — CORRECTED
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 4 — CORRECT → CORRECTED"
        )
        print("-" * 76)


        document_id = (
            create_document(
                persistence_service,
                filename=(
                    "phase7c_corrected.jpg"
                ),
                machine_decision=(
                    "REVIEW_REQUIRED"
                ),
            )
        )


        created_document_ids.append(
            document_id
        )


        corrections = {
            "expiry_date":
                "2027-01-01",

            "issuer":
                "Texas Department of Public Safety",

            # Deliberately clear a machine value.
            "id_number":
                None,
        }


        submit_review(
            persistence_service=(
                persistence_service
            ),
            human_review_service=(
                human_review_service
            ),
            document_id=(
                document_id
            ),
            action=(
                "CORRECT"
            ),
            corrections=(
                corrections
            ),
        )


        result = (
            query_service
            .get_document(
                document_id
            )
        )


        human_review = (
            result[
                "human_review"
            ]
        )


        final_record = (
            result[
                "final_record"
            ]
        )


        assert_equal(
            human_review[
                "human_action"
            ],
            "CORRECT",
            (
                "Stored human action should "
                "be CORRECT."
            ),
        )


        assert_equal(
            human_review[
                "corrections"
            ],
            corrections,
            (
                "Stored correction payload "
                "does not match submitted data."
            ),
        )


        assert_equal(
            final_record[
                "final_status"
            ],
            "CORRECTED",
            (
                "CORRECT should produce "
                "CORRECTED final status."
            ),
        )


        assert_equal(
            final_record[
                "is_final"
            ],
            True,
            "CORRECTED should be final.",
        )


        assert_equal(
            final_record[
                "is_usable"
            ],
            True,
            "CORRECTED should be usable.",
        )


        expected_effective_values = dict(
            MACHINE_VALUES
        )


        expected_effective_values.update(
            corrections
        )


        assert_equal(
            final_record[
                "effective_values"
            ],
            expected_effective_values,
            (
                "Human corrections were not "
                "correctly overlaid onto "
                "machine values."
            ),
        )


        assert_equal(
            final_record[
                "value_sources"
            ][
                "expiry_date"
            ],
            "HUMAN_CORRECTION",
            (
                "Corrected expiry_date should "
                "identify HUMAN_CORRECTION "
                "as its source."
            ),
        )


        assert_equal(
            final_record[
                "value_sources"
            ][
                "issuer"
            ],
            "HUMAN_CORRECTION",
            (
                "Corrected issuer should "
                "identify HUMAN_CORRECTION "
                "as its source."
            ),
        )


        assert_equal(
            final_record[
                "value_sources"
            ][
                "full_name"
            ],
            "MACHINE",
            (
                "Unchanged full_name should "
                "remain MACHINE sourced."
            ),
        )


        assert_equal(
            final_record[
                "value_sources"
            ][
                "id_number"
            ],
            "HUMAN_CORRECTION",
            (
                "Explicit correction to None "
                "must still retain "
                "HUMAN_CORRECTION provenance."
            ),
        )


        verify_machine_values(
            final_record
        )


        verify_raw_machine_extraction(
            document_id
        )


        assert_equal(
            result[
                "analysis"
            ][
                "extraction"
            ][
                "expiry_date"
            ][
                "value"
            ],
            "2026-01-01",
            (
                "QueryService analysis should "
                "still expose original machine "
                "expiry date after correction."
            ),
        )


        print(
            "[PASS] CORRECT overlays only "
            "effective values"
        )


        print(
            "[PASS] Human correction provenance "
            "is exposed per field"
        )


        print(
            "[PASS] Original machine extraction "
            "remains immutable"
        )


        # ==================================================
        # TEST 5 — REJECTED
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 5 — REJECT → REJECTED"
        )
        print("-" * 76)


        document_id = (
            create_document(
                persistence_service,
                filename=(
                    "phase7c_rejected.jpg"
                ),
                machine_decision=(
                    "REVIEW_REQUIRED"
                ),
            )
        )


        created_document_ids.append(
            document_id
        )


        submit_review(
            persistence_service=(
                persistence_service
            ),
            human_review_service=(
                human_review_service
            ),
            document_id=(
                document_id
            ),
            action=(
                "REJECT"
            ),
        )


        result = (
            query_service
            .get_document(
                document_id
            )
        )


        final_record = (
            result[
                "final_record"
            ]
        )


        assert_equal(
            result[
                "human_review"
            ][
                "human_action"
            ],
            "REJECT",
            (
                "Stored human action should "
                "be REJECT."
            ),
        )


        assert_equal(
            final_record[
                "final_status"
            ],
            "REJECTED",
            (
                "REJECT should produce "
                "REJECTED final status."
            ),
        )


        assert_equal(
            final_record[
                "is_final"
            ],
            True,
            "REJECTED is a final decision.",
        )


        assert_equal(
            final_record[
                "is_usable"
            ],
            False,
            (
                "REJECTED document must "
                "not be usable downstream."
            ),
        )


        assert_equal(
            final_record[
                "effective_values"
            ],
            None,
            (
                "REJECTED document must not "
                "publish effective values."
            ),
        )


        assert_equal(
            final_record[
                "value_sources"
            ],
            None,
            (
                "REJECTED document should not "
                "publish usable value sources."
            ),
        )


        verify_machine_values(
            final_record
        )


        verify_raw_machine_extraction(
            document_id
        )


        print(
            "[PASS] REJECT produces a final "
            "but non-usable record"
        )


        print(
            "[PASS] Rejected machine extraction "
            "remains available for audit"
        )


        # ==================================================
        # FINAL
        # ==================================================

        print()
        print("=" * 76)
        print(
            "[PASS] PHASE 7C.3 FINAL "
            "RECORD TEST PASSED"
        )
        print("=" * 76)


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


        for document_id in (
            created_document_ids
        ):

            try:

                (
                    persistence_service
                    .storage_service
                    .delete_document(
                        document_id
                    )
                )

            except Exception:

                pass


        print()
        print(
            "[CLEANUP] Phase 7C.3 temporary "
            "documents, reviews and audits removed."
        )


if __name__ == "__main__":

    main()