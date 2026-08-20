from math import (
    isclose,
)

from sqlalchemy import (
    select,
)

from backend.app.services.confidence_service import (
    ConfidenceService,
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

from backend.app.services.evidence_validator import (
    EvidenceValidator,
)

from backend.app.services.extraction_service import (
    ExtractionService,
)

from backend.app.domain.schemas import (
    DocumentExtraction,
)


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


def assert_float_equal(
    actual,
    expected,
    message: str,
):

    if actual is None:

        raise AssertionError(
            f"{message}\n"
            f"Expected: {expected}\n"
            "Actual:   None"
        )


    if not isclose(
        float(actual),
        float(expected),
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):

        raise AssertionError(
            f"{message}\n"
            f"Expected: {expected}\n"
            f"Actual:   {actual}"
        )


# ==========================================================
# EXPLICIT OCR LINES
# ==========================================================
#
# IMPORTANT:
#
# These lines are intentionally NOT stored in L0, L1, L2
# positional order.
#
# Example:
#
# array index 0 contains line_id L15
# array index 1 contains line_id L4
#
# If any downstream component still assumes:
#
#     L15 -> ocr_lines[15]
#
# this test will fail.
#
# ==========================================================

def build_explicit_ocr_lines() -> list[dict]:

    return [

        {
            "line_id":
                "L15",

            "text":
                "ISSUED BY TX DPS",

            "confidence":
                0.91,

            "bbox":
                [10, 10, 200, 30],
        },

        {
            "line_id":
                "L4",

            "text":
                "PRINTDATE 01/01/2025",

            "confidence":
                0.93,

            "bbox":
                [10, 40, 220, 60],
        },

        {
            "line_id":
                "L14",

            "text":
                "SAMPLE,JANE",

            "confidence":
                0.98,

            "bbox":
                [10, 70, 180, 90],
        },

        {
            "line_id":
                "L8",

            "text":
                "EXPIRES",

            "confidence":
                0.97,

            "bbox":
                [10, 100, 100, 120],
        },

        {
            "line_id":
                "L9",

            "text":
                "01/01/2026",

            "confidence":
                0.89,

            "bbox":
                [110, 100, 210, 120],
        },

        {
            "line_id":
                "L5",

            "text":
                "LICENSE",

            "confidence":
                0.99,

            "bbox":
                [10, 130, 100, 150],
        },

        {
            "line_id":
                "L6",

            "text":
                "12345678",

            "confidence":
                0.95,

            "bbox":
                [110, 130, 210, 150],
        },

        {
            "line_id":
                "L11",

            "text":
                "DOB",

            "confidence":
                0.96,

            "bbox":
                [10, 160, 60, 180],
        },

        {
            "line_id":
                "L12",

            "text":
                "01/01/1990",

            "confidence":
                0.94,

            "bbox":
                [70, 160, 180, 180],
        },
    ]


# ==========================================================
# STRUCTURED EXTRACTION
# ==========================================================

def build_extraction() -> DocumentExtraction:

    return (
        DocumentExtraction
        .model_validate(
            {
                "document_type":
                    "guard_license",

                "full_name": {
                    "value":
                        "SAMPLE,JANE",

                    "source_line_ids": [
                        "L14"
                    ],
                },

                "licence_number": {
                    "value":
                        "12345678",

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
                        "2026-01-01",

                    "source_line_ids": [
                        "L8",
                        "L9",
                    ],
                },

                "date_of_birth": {
                    "value":
                        "1990-01-01",

                    "source_line_ids": [
                        "L11",
                        "L12",
                    ],
                },

                "issue_date": {
                    "value":
                        "2025-01-01",

                    "source_line_ids": [
                        "L4"
                    ],
                },

                "issuer": {
                    "value":
                        "TX DPS",

                    "source_line_ids": [
                        "L15"
                    ],
                },
            }
        )
    )


# ==========================================================
# LEGACY OCR FIXTURE
# ==========================================================

def build_legacy_ocr_lines() -> list[dict]:

    return [
        {
            "text":
                "EXPIRES",

            "confidence":
                0.80,

            "bbox":
                [],
        },

        {
            "text":
                "01/01/2026",

            "confidence":
                0.70,

            "bbox":
                [],
        },
    ]


def build_legacy_extraction() -> DocumentExtraction:

    return (
        DocumentExtraction
        .model_validate(
            {
                "document_type":
                    "guard_license",

                "full_name": {
                    "value":
                        None,

                    "source_line_ids":
                        [],
                },

                "licence_number": {
                    "value":
                        None,

                    "source_line_ids":
                        [],
                },

                "id_number": {
                    "value":
                        None,

                    "source_line_ids":
                        [],
                },

                "expiry_date": {
                    "value":
                        "2026-01-01",

                    "source_line_ids": [
                        "L0",
                        "L1",
                    ],
                },

                "date_of_birth": {
                    "value":
                        None,

                    "source_line_ids":
                        [],
                },

                "issue_date": {
                    "value":
                        None,

                    "source_line_ids":
                        [],
                },

                "issuer": {
                    "value":
                        None,

                    "source_line_ids":
                        [],
                },
            }
        )
    )


# ==========================================================
# PIPELINE RESULT FOR JSONB PERSISTENCE
# ==========================================================

def build_pipeline_result(
    extraction: DocumentExtraction,
    ocr_lines: list[dict],
    evidence_flags: list[str],
    field_confidence: dict,
) -> dict:

    return {
        "extraction":
            extraction.model_dump(),

        "ocr_lines":
            ocr_lines,

        "evidence_flags":
            evidence_flags,

        "field_confidence":
            field_confidence,

        "date_validation": {
            "reference_date":
                "2026-08-19",

            "date_fields":
                {},

            "expiry": {
                "value":
                    "2026-01-01",

                "status":
                    "EXPIRED",

                "days_until_expiry":
                    -230,
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
                True,

            "error_count":
                0,

            "warning_count":
                1,

            "issues": [
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
            ],
        },

        "review_decision": {
            "decision":
                "REVIEW_REQUIRED",

            "review_required":
                True,

            "priority":
                "MEDIUM",

            "reason_codes": [
                "DOCUMENT_EXPIRED"
            ],
        },
    }


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("=" * 76)
    print(
        "PHASE 7C.2 — EXPLICIT OCR "
        "EVIDENCE LINE ID TEST"
    )
    print("=" * 76)


    validator = (
        EvidenceValidator()
    )


    confidence_service = (
        ConfidenceService()
    )


    explicit_ocr_lines = (
        build_explicit_ocr_lines()
    )


    extraction = (
        build_extraction()
    )


    persisted_document_id = None


    try:

        # ==================================================
        # TEST 1
        # EXTRACTION SERVICE PRESERVES EXPLICIT IDS
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 1 — EXTRACTION SERVICE ID PRESERVATION"
        )
        print("-" * 76)


        # Avoid creating a Groq client because this helper
        # does not require an API call.
        extraction_service = (
            ExtractionService.__new__(
                ExtractionService
            )
        )


        llm_input = (
            extraction_service
            ._prepare_llm_input(
                explicit_ocr_lines
            )
        )


        actual_ids = [
            line[
                "line_id"
            ]
            for line
            in llm_input
        ]


        expected_ids = [
            "L15",
            "L4",
            "L14",
            "L8",
            "L9",
            "L5",
            "L6",
            "L11",
            "L12",
        ]


        assert_equal(
            actual_ids,
            expected_ids,
            (
                "ExtractionService changed "
                "explicit OCR line IDs."
            ),
        )


        for line in llm_input:

            if (
                "confidence"
                in line
            ):

                raise AssertionError(
                    (
                        "OCR confidence must "
                        "not be sent to the LLM."
                    )
                )


        print(
            "[PASS] ExtractionService preserves "
            "explicit OCR line IDs"
        )

        print(
            "[PASS] OCR confidence remains "
            "excluded from LLM evidence"
        )


        # ==================================================
        # TEST 2
        # EVIDENCE VALIDATOR USES EXPLICIT IDS
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 2 — EXPLICIT EVIDENCE LOOKUP"
        )
        print("-" * 76)


        evidence_flags = (
            validator.validate(
                extraction,
                explicit_ocr_lines,
            )
        )


        assert_equal(
            evidence_flags,
            [],
            (
                "Explicit-ID evidence "
                "validation failed."
            ),
        )


        print(
            "[PASS] EvidenceValidator resolved "
            "out-of-order lines by explicit ID"
        )


        # ==================================================
        # TEST 3
        # CONFIDENCE USES EXPLICIT IDS
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 3 — EXPLICIT CONFIDENCE LOOKUP"
        )
        print("-" * 76)


        confidence_results = (
            confidence_service
            .calculate(
                extraction,
                explicit_ocr_lines,
                evidence_flags,
            )
        )


        assert_float_equal(
            confidence_results[
                "full_name"
            ][
                "confidence"
            ],
            0.98,
            (
                "Incorrect full_name "
                "confidence."
            ),
        )


        assert_float_equal(
            confidence_results[
                "licence_number"
            ][
                "confidence"
            ],
            0.95,
            (
                "Incorrect licence_number "
                "confidence."
            ),
        )


        assert_float_equal(
            confidence_results[
                "expiry_date"
            ][
                "confidence"
            ],
            0.89,
            (
                "Incorrect expiry_date "
                "confidence."
            ),
        )


        assert_float_equal(
            confidence_results[
                "date_of_birth"
            ][
                "confidence"
            ],
            0.94,
            (
                "Incorrect date_of_birth "
                "confidence."
            ),
        )


        assert_float_equal(
            confidence_results[
                "issue_date"
            ][
                "confidence"
            ],
            0.93,
            (
                "Incorrect issue_date "
                "confidence."
            ),
        )


        assert_float_equal(
            confidence_results[
                "issuer"
            ][
                "confidence"
            ],
            0.91,
            (
                "Incorrect issuer "
                "confidence."
            ),
        )


        assert_equal(
            confidence_results[
                "id_number"
            ][
                "status"
            ],
            "NOT_EXTRACTED",
            (
                "Null ID number should "
                "remain NOT_EXTRACTED."
            ),
        )


        print(
            "[PASS] ConfidenceService resolved "
            "confidence by explicit line ID"
        )

        print(
            "[PASS] Conservative minimum-confidence "
            "policy preserved"
        )


        # ==================================================
        # TEST 4
        # LEGACY BACKWARD COMPATIBILITY
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 4 — LEGACY OCR COMPATIBILITY"
        )
        print("-" * 76)


        legacy_ocr_lines = (
            build_legacy_ocr_lines()
        )


        legacy_extraction = (
            build_legacy_extraction()
        )


        legacy_flags = (
            validator.validate(
                legacy_extraction,
                legacy_ocr_lines,
            )
        )


        assert_equal(
            legacy_flags,
            [],
            (
                "Legacy OCR records without "
                "line_id should remain valid."
            ),
        )


        legacy_confidence = (
            confidence_service
            .calculate(
                legacy_extraction,
                legacy_ocr_lines,
                legacy_flags,
            )
        )


        assert_float_equal(
            legacy_confidence[
                "expiry_date"
            ][
                "confidence"
            ],
            0.70,
            (
                "Legacy positional confidence "
                "fallback failed."
            ),
        )


        print(
            "[PASS] Legacy OCR without line_id "
            "still validates"
        )

        print(
            "[PASS] Legacy confidence fallback "
            "still works"
        )


        # ==================================================
        # TEST 5
        # DUPLICATE EXPLICIT IDS ARE REJECTED
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 5 — DUPLICATE LINE ID PROTECTION"
        )
        print("-" * 76)


        duplicate_lines = [
            {
                "line_id":
                    "L7",

                "text":
                    "FIRST",

                "confidence":
                    0.90,

                "bbox":
                    [],
            },

            {
                "line_id":
                    "L7",

                "text":
                    "SECOND",

                "confidence":
                    0.91,

                "bbox":
                    [],
            },
        ]


        try:

            (
                extraction_service
                ._prepare_llm_input(
                    duplicate_lines
                )
            )

        except ValueError:

            pass

        else:

            raise AssertionError(
                (
                    "ExtractionService accepted "
                    "duplicate OCR line IDs."
                )
            )


        try:

            validator._build_ocr_lookup(
                duplicate_lines
            )

        except ValueError:

            pass

        else:

            raise AssertionError(
                (
                    "EvidenceValidator accepted "
                    "duplicate OCR line IDs."
                )
            )


        try:

            (
                confidence_service
                ._build_ocr_lookup(
                    duplicate_lines
                )
            )

        except ValueError:

            pass

        else:

            raise AssertionError(
                (
                    "ConfidenceService accepted "
                    "duplicate OCR line IDs."
                )
            )


        print(
            "[PASS] Duplicate explicit OCR "
            "line IDs are rejected"
        )


        # ==================================================
        # TEST 6
        # POSTGRESQL JSONB PERSISTENCE
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 6 — POSTGRESQL JSONB PERSISTENCE"
        )
        print("-" * 76)


        persistence_service = (
            PersistenceService()
        )


        pipeline_result = (
            build_pipeline_result(
                extraction,
                explicit_ocr_lines,
                evidence_flags,
                confidence_results,
            )
        )


        stored = (
            persistence_service
            .save_processed_document(
                original_filename=(
                    "phase7c_explicit_ids.jpg"
                ),

                content_type=(
                    "image/jpeg"
                ),

                pipeline_result=(
                    pipeline_result
                ),
            )
        )


        persisted_document_id = (
            stored[
                "document_id"
            ]
        )


        with SessionLocal() as session:

            statement = (
                select(
                    DocumentAnalysisModel
                )
                .where(
                    DocumentAnalysisModel.document_id
                    == persisted_document_id
                )
            )


            analysis = (
                session
                .scalars(
                    statement
                )
                .one()
            )


            persisted_ocr_lines = (
                analysis.ocr_lines
            )


            persisted_ids = [
                line.get(
                    "line_id"
                )
                for line
                in persisted_ocr_lines
            ]


            assert_equal(
                persisted_ids,
                expected_ids,
                (
                    "PostgreSQL JSONB did not "
                    "preserve explicit line IDs."
                ),
            )


            persisted_extraction = (
                analysis.extraction
            )


            assert_equal(
                persisted_extraction[
                    "issuer"
                ][
                    "source_line_ids"
                ],
                [
                    "L15"
                ],
                (
                    "Persisted extraction lost "
                    "issuer evidence provenance."
                ),
            )


            assert_equal(
                persisted_extraction[
                    "expiry_date"
                ][
                    "source_line_ids"
                ],
                [
                    "L8",
                    "L9",
                ],
                (
                    "Persisted extraction lost "
                    "expiry evidence provenance."
                ),
            )


        print(
            "[PASS] PostgreSQL JSONB preserved "
            "explicit OCR line IDs"
        )

        print(
            "[PASS] Persisted extraction retained "
            "matching source_line_ids"
        )


        # ==================================================
        # FINAL
        # ==================================================

        print()
        print("=" * 76)
        print(
            "[PASS] PHASE 7C.2 EXPLICIT "
            "EVIDENCE ID TEST PASSED"
        )
        print("=" * 76)


    finally:

        # ==================================================
        # CLEANUP TEST DATABASE RECORD
        # ==================================================

        if (
            persisted_document_id
            is not None
        ):

            with SessionLocal() as session:

                document = (
                    session.get(
                        DocumentModel,
                        persisted_document_id,
                    )
                )


                if document is not None:

                    session.delete(
                        document
                    )


                    session.commit()


            print()
            print(
                "[CLEANUP] Phase 7C.2 temporary "
                "database record removed."
            )


if __name__ == "__main__":

    main()