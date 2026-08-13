from src.schemas import (
    DocumentExtraction,
)

from src.evidence_validator import (
    EvidenceValidator,
)


# ==========================================================
# MOCK OCR OUTPUT
# ==========================================================

ocr_lines = [

    {
        "text":
            "1099 4265 1706 9065",

        "confidence":
            0.9862,

        "bbox":
            [],
    },

    {
        "text":
            "LICENCE",

        "confidence":
            0.9999,

        "bbox":
            [],
    },

    {
        "text":
            "EITY",

        "confidence":
            0.8427,

        "bbox":
            [],
    },

    {
        "text":
            "Security Industry Authority",

        "confidence":
            0.9998,

        "bbox":
            [],
    },

    {
        "text":
            "EXPIRES",

        "confidence":
            0.9984,

        "bbox":
            [],
    },

    {
        "text":
            "24 MAR 2021",

        "confidence":
            0.9999,

        "bbox":
            [],
    },

    {
        "text":
            "M.GREEN",

        "confidence":
            0.9643,

        "bbox":
            [],
    },

    {
        "text":
            "24/03/21",

        "confidence":
            0.9996,

        "bbox":
            [],
    },
]


# ==========================================================
# MOCK STRUCTURED EXTRACTION
# ==========================================================

extraction = (
    DocumentExtraction.model_validate(
        {

            "document_type":
                "sia_badge",

            "full_name": {
                "value":
                    "M.GREEN",

                "source_line_ids":
                    ["L6"],
            },

            "licence_number": {
                "value":
                    "1099 4265 1706 9065",

                "source_line_ids":
                    ["L0"],
            },

            "id_number": {
                "value":
                    None,

                "source_line_ids":
                    [],
            },

            "expiry_date": {
                "value":
                    "2021-03-24",

                "source_line_ids":
                    [
                        "L4",
                        "L5",
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
                    "Security Industry Authority",

                "source_line_ids":
                    ["L3"],
            },
        }
    )
)


# ==========================================================
# RUN VALIDATION
# ==========================================================

validator = EvidenceValidator()


flags = validator.validate(
    extraction,
    ocr_lines,
)


print(
    "\n========== V2 TEST ==========\n"
)


if flags:

    for flag in flags:

        print(
            f"[REVIEW] {flag}"
        )

else:

    print(
        "All semantic evidence is valid."
    )