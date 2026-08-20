from pathlib import Path

from backend.app.services.ocr_service import OCRService



# ==========================================================
# SAFE SYNTHETIC FIXTURES
# PHASE 8.1
# ==========================================================
#
# These point at tracked, generated documents under
# evaluation/images/ rather than the untracked samples/
# directory.
#
# A Phase 8 content inspection found samples/id_card.jpg to be
# a photograph of an apparently REAL national identity card
# carrying personal data. samples/ is therefore gitignored in
# full, and nothing here depends on it any more.
#
# evaluation/images/ is versioned and produced by
# scripts/evaluation/generate_synthetic_documents.py, so a
# fresh clone can run this file unchanged.
# ==========================================================

ocr_service = OCRService()


samples = [
    "evaluation/images/sia_badge/sia_001.jpg",
    "evaluation/images/id_card/id_001.jpg",
    "evaluation/images/guard_license/guard_001.jpg",
]


for image_path in samples:

    print("\n")
    print("=" * 70)
    print(f"DOCUMENT: {image_path}")
    print("=" * 70)

    if not Path(image_path).exists():

        print(
            f"[ERROR] File does not exist: "
            f"{image_path}"
        )

        continue


    ocr_lines = ocr_service.extract(
        image_path
    )


    for index, line in enumerate(
        ocr_lines
    ):

        confidence = line["confidence"]

        status = (
            "[OK]"
            if confidence >= 0.90
            else "[REVIEW]"
        )

        print(
            f"[{index}] "
            f"{line['text']:<40} "
            f"{confidence:.2%} "
            f"{status}"
        )