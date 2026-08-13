from pathlib import Path

from dotenv import load_dotenv

from src.ocr_service import (
    OCRService,
)

from src.extraction_service import (
    ExtractionService,
)

from src.evidence_validator import (
    EvidenceValidator,
)


# ==========================================================
# LOAD ENVIRONMENT VARIABLES
# ==========================================================

load_dotenv()


# ==========================================================
# INITIALIZE SERVICES
# ==========================================================

ocr_service = OCRService()

extraction_service = (
    ExtractionService()
)

evidence_validator = (
    EvidenceValidator()
)


# ==========================================================
# DOCUMENT
# ==========================================================

image_path = (
    "samples/sia_badge.jpg"
)


if not Path(
    image_path
).exists():

    raise FileNotFoundError(
        f"Image not found: "
        f"{image_path}"
    )


# ==========================================================
# STEP 1 — OCR
# ==========================================================

ocr_lines = (
    ocr_service.extract(
        image_path
    )
)


print(
    "\n========== RAW OCR ==========\n"
)


for index, line in enumerate(
    ocr_lines
):

    print(
        f"[L{index}] "
        f"{line['text']:<35}"
        f"{line['confidence']:.2%}"
    )


# ==========================================================
# STEP 2 — STRUCTURED EXTRACTION
# ==========================================================

structured = (
    extraction_service.extract(
        ocr_lines
    )
)


print(
    "\n========== STRUCTURED EXTRACTION ==========\n"
)


print(
    structured.model_dump_json(
        indent=2
    )
)


# ==========================================================
# STEP 3 — EVIDENCE VALIDATION V1 + V2
# ==========================================================

flags = (
    evidence_validator.validate(
        structured,
        ocr_lines,
    )
)


print(
    "\n========== EVIDENCE VALIDATION ==========\n"
)


if flags:

    for flag in flags:

        print(
            f"[REVIEW] {flag}"
        )

else:

    print(
        "All evidence references are valid."
    )