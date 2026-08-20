from datetime import (
    date,
)

from math import (
    isclose,
)

from pathlib import (
    Path,
)

from dotenv import (
    load_dotenv,
)

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

from backend.app.services.pipeline_service import (
    DocumentPipelineService,
)


# ==========================================================
# ENVIRONMENT
# ==========================================================

load_dotenv()


# ==========================================================
# CONFIGURATION
# ==========================================================

# ==========================================================
# TRACKED SYNTHETIC FIXTURE
# PHASE 8.2
# ==========================================================
#
# This test used to read samples/guard_license.jpg.
#
# samples/ is gitignored in full because
# samples/id_card.jpg is a photograph of an apparently REAL
# national identity card. That made this test unrunnable
# from a clean clone.
#
# It now reads the tracked seed fixture:
#
#     evaluation/images/guard_license/guard_001.jpg
#
# which is BYTE-IDENTICAL to the old samples/ file, so every
# OCR line ID and every expectation below is unchanged.
#
# The fixture is stable by design:
# scripts/evaluation/generate_synthetic_documents.py
# generates from index 2 upward and never regenerates the
# *_001 seed documents.
# ==========================================================

SAMPLE_PATH = (
    Path("evaluation")
    / "images"
    / "guard_license"
    / "guard_001.jpg"
)


REFERENCE_DATE = date(
    2026,
    8,
    19,
)


# ==========================================================
# EXPECTED REPRESENTATIVE EXTRACTION
# ==========================================================

EXPECTED_VALUES = {

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
# EXPECTED REAL OCR PROVENANCE
# ==========================================================
#
# These IDs were verified against the actual representative
# guard_license.jpg OCR output.
# ==========================================================

EXPECTED_OCR_TEXT = {

    "L4":
        "PRINTDATE 01/01/2025",

    "L5":
        "LICENSE",

    "L6":
        "12345678",

    "L8":
        "EXPIRES",

    "L9":
        "01/01/2026",

    "L11":
        "DOB",

    "L12":
        "01/01/1990",

    "L14":
        "SAMPLE,JANE",

    "L15":
        "ISSUED BY TX DPS",
}


EXPECTED_FIELD_SOURCE_IDS = {

    "full_name": {
        "L14",
    },

    "licence_number": {
        "L5",
        "L6",
    },

    "expiry_date": {
        "L8",
        "L9",
    },

    "date_of_birth": {
        "L11",
        "L12",
    },

    "issue_date": {
        "L4",
    },

    "issuer": {
        "L15",
    },
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
        rel_tol=1e-7,
        abs_tol=1e-7,
    ):

        raise AssertionError(
            f"{message}\n"
            f"Expected: {expected}\n"
            f"Actual:   {actual}"
        )


# ==========================================================
# BUILD OCR LOOKUP
# ==========================================================

def build_ocr_lookup(
    ocr_lines: list[dict],
) -> dict[str, dict]:

    lookup: dict[str, dict] = {}


    for line in ocr_lines:

        line_id = (
            line.get(
                "line_id"
            )
        )


        if not line_id:

            raise AssertionError(
                (
                    "Real pipeline OCR output "
                    "contains a line without "
                    "explicit line_id."
                )
            )


        if line_id in lookup:

            raise AssertionError(
                (
                    "Duplicate real OCR line_id "
                    f"detected: {line_id}"
                )
            )


        lookup[
            line_id
        ] = line


    return lookup


# ==========================================================
# VERIFY SEQUENTIAL OCR IDS
# ==========================================================

def verify_sequential_line_ids(
    ocr_lines: list[dict],
):

    actual_ids = [
        line[
            "line_id"
        ]
        for line
        in ocr_lines
    ]


    expected_ids = [
        f"L{index}"
        for index
        in range(
            len(
                ocr_lines
            )
        )
    ]


    assert_equal(
        actual_ids,
        expected_ids,
        (
            "OCRService did not produce the "
            "expected explicit zero-based "
            "line ID sequence."
        ),
    )


# ==========================================================
# VERIFY EXPECTED OCR LINES
# ==========================================================

def verify_known_ocr_evidence(
    ocr_lookup: dict[str, dict],
):

    for (
        line_id,
        expected_text,
    ) in EXPECTED_OCR_TEXT.items():

        assert_true(
            line_id
            in ocr_lookup,
            (
                "Expected real OCR evidence "
                f"{line_id} is missing."
            ),
        )


        actual_text = (
            ocr_lookup[
                line_id
            ][
                "text"
            ]
        )


        assert_equal(
            actual_text,
            expected_text,
            (
                "Unexpected OCR text for "
                f"{line_id}."
            ),
        )


# ==========================================================
# VERIFY EXTRACTION VALUES
# ==========================================================

def verify_extraction_values(
    extraction: dict,
):

    assert_equal(
        extraction[
            "document_type"
        ],
        EXPECTED_VALUES[
            "document_type"
        ],
        "Incorrect document type.",
    )


    for field_name in (
        "full_name",
        "licence_number",
        "id_number",
        "expiry_date",
        "date_of_birth",
        "issue_date",
        "issuer",
    ):

        actual_value = (
            extraction[
                field_name
            ][
                "value"
            ]
        )


        assert_equal(
            actual_value,
            EXPECTED_VALUES[
                field_name
            ],
            (
                "Unexpected extracted value "
                f"for {field_name}."
            ),
        )


# ==========================================================
# VERIFY EXPECTED FIELD PROVENANCE
# ==========================================================

def verify_expected_field_sources(
    extraction: dict,
):

    for (
        field_name,
        expected_ids,
    ) in EXPECTED_FIELD_SOURCE_IDS.items():

        actual_ids = set(
            extraction[
                field_name
            ][
                "source_line_ids"
            ]
        )


        assert_equal(
            actual_ids,
            expected_ids,
            (
                "Unexpected source_line_ids "
                f"for {field_name}."
            ),
        )


# ==========================================================
# VERIFY ALL SOURCE IDS RESOLVE
# ==========================================================

def verify_all_sources_resolve(
    extraction: dict,
    ocr_lookup: dict[str, dict],
):

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

        field = (
            extraction[
                field_name
            ]
        )


        value = (
            field[
                "value"
            ]
        )


        source_line_ids = (
            field[
                "source_line_ids"
            ]
        )


        # Null fields must have no evidence.
        if value is None:

            assert_equal(
                source_line_ids,
                [],
                (
                    "Null field unexpectedly "
                    "contains evidence IDs: "
                    f"{field_name}"
                ),
            )


            continue


        # Non-null fields require evidence.
        assert_true(
            len(
                source_line_ids
            )
            > 0,
            (
                "Extracted field has no "
                "source_line_ids: "
                f"{field_name}"
            ),
        )


        for line_id in source_line_ids:

            assert_true(
                line_id
                in ocr_lookup,
                (
                    f"{field_name} references "
                    "an OCR line that does not "
                    f"exist: {line_id}"
                ),
            )


# ==========================================================
# VERIFY FIELD CONFIDENCE PROVENANCE
# ==========================================================

def verify_confidence_provenance(
    extraction: dict,
    field_confidence: dict,
    ocr_lookup: dict[str, dict],
):

    fields = (
        "full_name",
        "licence_number",
        "expiry_date",
        "date_of_birth",
        "issue_date",
        "issuer",
    )


    for field_name in fields:

        field = (
            extraction[
                field_name
            ]
        )


        confidence_result = (
            field_confidence[
                field_name
            ]
        )


        assert_equal(
            confidence_result[
                "status"
            ],
            "VALID",
            (
                "Expected VALID confidence "
                f"for {field_name}."
            ),
        )


        source_confidences = [

            float(
                ocr_lookup[
                    line_id
                ][
                    "confidence"
                ]
            )

            for line_id
            in field[
                "source_line_ids"
            ]
        ]


        expected_confidence = min(
            source_confidences
        )


        assert_float_equal(
            confidence_result[
                "confidence"
            ],
            expected_confidence,
            (
                "Field confidence does not "
                "match the minimum confidence "
                "of its explicit OCR evidence "
                f"for {field_name}."
            ),
        )


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("=" * 76)
    print(
        "PHASE 7C.2 — REAL PIPELINE "
        "PROVENANCE END-TO-END TEST"
    )
    print("=" * 76)


    if not SAMPLE_PATH.exists():

        raise FileNotFoundError(
            (
                "Representative sample not found: "
                f"{SAMPLE_PATH}"
            )
        )


    pipeline = None

    persistence_service = (
        PersistenceService()
    )

    query_service = (
        DocumentQueryService()
    )


    persisted_document_id = None


    try:

        # ==================================================
        # 1. INITIALIZE REAL PIPELINE
        # ==================================================

        print()
        print(
            "[INFO] Initializing PaddleOCR "
            "and Groq extraction services..."
        )


        pipeline = (
            DocumentPipelineService()
        )


        print(
            "[PASS] Real document pipeline initialized"
        )


        # ==================================================
        # 2. RUN REAL OCR + LLM + VALIDATORS
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 1 — REAL OCR + LLM PIPELINE"
        )
        print("-" * 76)


        pipeline_result = (
            pipeline.process(
                str(
                    SAMPLE_PATH
                ),

                reference_date=(
                    REFERENCE_DATE
                ),
            )
        )


        print(
            "[PASS] Real guard licence processed "
            "through complete pipeline"
        )


        # ==================================================
        # 3. EXPLICIT OCR IDS
        # ==================================================

        ocr_lines = (
            pipeline_result[
                "ocr_lines"
            ]
        )


        assert_true(
            len(
                ocr_lines
            )
            > 0,
            "OCR returned no lines.",
        )


        verify_sequential_line_ids(
            ocr_lines
        )


        ocr_lookup = (
            build_ocr_lookup(
                ocr_lines
            )
        )


        print(
            "[PASS] Every real OCR line contains "
            "an explicit unique line_id"
        )


        # ==================================================
        # 4. KNOWN REAL OCR PROVENANCE
        # ==================================================

        verify_known_ocr_evidence(
            ocr_lookup
        )


        print(
            "[PASS] Representative OCR evidence "
            "IDs map to expected source text"
        )


        # ==================================================
        # 5. REAL STRUCTURED EXTRACTION
        # ==================================================

        extraction = (
            pipeline_result[
                "extraction"
            ]
        )


        verify_extraction_values(
            extraction
        )


        print(
            "[PASS] Representative structured "
            "extraction values are correct"
        )


        # ==================================================
        # 6. SOURCE IDS MATCH EXPECTED OCR EVIDENCE
        # ==================================================

        verify_expected_field_sources(
            extraction
        )


        print(
            "[PASS] Extracted fields retain "
            "expected real source_line_ids"
        )


        # ==================================================
        # 7. ALL REFERENCES RESOLVE
        # ==================================================

        verify_all_sources_resolve(
            extraction,
            ocr_lookup,
        )


        print(
            "[PASS] Every extracted source_line_id "
            "resolves to an actual OCR record"
        )


        # ==================================================
        # 8. EVIDENCE VALIDATION
        # ==================================================

        evidence_flags = (
            pipeline_result[
                "evidence_flags"
            ]
        )


        assert_equal(
            evidence_flags,
            [],
            (
                "Representative document "
                "produced unexpected evidence "
                "validation flags."
            ),
        )


        print(
            "[PASS] Real explicit OCR provenance "
            "passes semantic evidence validation"
        )


        # ==================================================
        # 9. CONFIDENCE PROVENANCE
        # ==================================================

        verify_confidence_provenance(
            extraction,
            pipeline_result[
                "field_confidence"
            ],
            ocr_lookup,
        )


        print(
            "[PASS] Field confidence is derived "
            "from the same explicit OCR evidence"
        )


        # ==================================================
        # 10. EXPECTED MACHINE REVIEW DECISION
        # ==================================================

        review_decision = (
            pipeline_result[
                "review_decision"
            ]
        )


        assert_equal(
            review_decision[
                "decision"
            ],
            "REVIEW_REQUIRED",
            (
                "Expired representative "
                "document should require review."
            ),
        )


        assert_true(
            "DOCUMENT_EXPIRED"
            in review_decision.get(
                "reason_codes",
                [],
            ),
            (
                "Expected DOCUMENT_EXPIRED "
                "review reason is missing."
            ),
        )


        print(
            "[PASS] Existing expiry/review behavior "
            "remains intact"
        )


        # ==================================================
        # 11. PERSIST REAL PIPELINE RESULT
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 2 — POSTGRESQL PROVENANCE PERSISTENCE"
        )
        print("-" * 76)


        stored = (
            persistence_service
            .save_processed_document(
                original_filename=(
                    "phase7c_real_provenance_guard.jpg"
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


        print(
            "[PASS] Real pipeline result "
            "persisted to PostgreSQL"
        )


        # ==================================================
        # 12. VERIFY RAW DATABASE JSONB
        # ==================================================

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


            persisted_extraction = (
                analysis.extraction
            )


            persisted_lookup = (
                build_ocr_lookup(
                    persisted_ocr_lines
                )
            )


            # ==============================================
            # ALL EXPLICIT IDS SURVIVED JSONB
            # ==============================================

            original_ids = [
                line[
                    "line_id"
                ]
                for line
                in ocr_lines
            ]


            persisted_ids = [
                line[
                    "line_id"
                ]
                for line
                in persisted_ocr_lines
            ]


            assert_equal(
                persisted_ids,
                original_ids,
                (
                    "PostgreSQL JSONB changed or "
                    "lost explicit OCR line IDs."
                ),
            )


            # ==============================================
            # KNOWN L15 PROVENANCE
            # ==============================================

            assert_equal(
                persisted_lookup[
                    "L15"
                ][
                    "text"
                ],
                "ISSUED BY TX DPS",
                (
                    "Persisted L15 evidence "
                    "does not match source OCR."
                ),
            )


            assert_equal(
                set(
                    persisted_extraction[
                        "issuer"
                    ][
                        "source_line_ids"
                    ]
                ),
                {
                    "L15"
                },
                (
                    "Persisted issuer provenance "
                    "does not reference L15."
                ),
            )


            # ==============================================
            # CHECK ALL PERSISTED SOURCES
            # ==============================================

            verify_all_sources_resolve(
                persisted_extraction,
                persisted_lookup,
            )


        print(
            "[PASS] PostgreSQL JSONB preserved "
            "all explicit OCR line IDs"
        )


        print(
            "[PASS] Persisted L15 still maps to "
            "'ISSUED BY TX DPS'"
        )


        print(
            "[PASS] Persisted extraction evidence "
            "still resolves to persisted OCR records"
        )


        # ==================================================
        # 13. VERIFY QUERY SERVICE READ PATH
        # ==================================================

        print()
        print("-" * 76)
        print(
            "TEST 3 — APPLICATION READ PATH"
        )
        print("-" * 76)


        stored_document = (
            query_service
            .get_document(
                persisted_document_id
            )
        )


        assert_true(
            stored_document
            is not None,
            (
                "Persisted document could "
                "not be reloaded."
            ),
        )


        stored_analysis = (
            stored_document[
                "analysis"
            ]
        )


        assert_true(
            stored_analysis
            is not None,
            (
                "Reloaded document has no "
                "analysis."
            ),
        )


        query_ocr_lines = (
            stored_analysis[
                "ocr_lines"
            ]
        )


        query_lookup = (
            build_ocr_lookup(
                query_ocr_lines
            )
        )


        assert_equal(
            query_lookup[
                "L15"
            ][
                "text"
            ],
            "ISSUED BY TX DPS",
            (
                "Application read path lost "
                "explicit L15 provenance."
            ),
        )


        assert_equal(
            set(
                stored_analysis[
                    "extraction"
                ][
                    "issuer"
                ][
                    "source_line_ids"
                ]
            ),
            {
                "L15"
            },
            (
                "Application read path lost "
                "issuer source_line_ids."
            ),
        )


        print(
            "[PASS] Application read path "
            "preserves explicit provenance"
        )


        # ==================================================
        # FINAL
        # ==================================================

        print()
        print("=" * 76)
        print(
            "[PASS] PHASE 7C.2 REAL PIPELINE "
            "PROVENANCE END-TO-END TEST PASSED"
        )
        print("=" * 76)


    finally:

        # ==================================================
        # CLEANUP DATABASE
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


            # No original document is stored by this test
            # because source_path is intentionally omitted.
            # Keep storage cleanup defensive anyway.

            try:

                persistence_service.storage_service.delete_document(
                    persisted_document_id
                )

            except Exception:

                pass


            print()
            print(
                "[CLEANUP] Phase 7C.2 real "
                "pipeline database record removed."
            )


if __name__ == "__main__":

    main()