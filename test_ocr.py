from pathlib import Path

from src.ocr_service import OCRService


ocr_service = OCRService()


samples = [
    "samples/sia_badge.jpg",
    "samples/id_card.jpg",
    "samples/guard_license.jpg",
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