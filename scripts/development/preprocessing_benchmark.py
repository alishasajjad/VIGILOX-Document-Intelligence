# ==========================================================
# PROJECT ROOT BOOTSTRAP
# PHASE 8.2
# ==========================================================
#
# This block exists so the script can be run directly:
#
#     python scripts\<area>\<script>.py
#
# Direct execution sets sys.path[0] to the script's OWN
# directory, so the backend and database packages would not
# be importable and the script would fail with:
#
#     ModuleNotFoundError: No module named 'backend'
#
# The canonical invocation is module form, which resolves the
# project root itself and needs no bootstrap:
#
#     python -m scripts.<area>.<script>
#
# Both forms are supported. This is the single sanctioned
# bootstrap pattern for scripts/ and it is documented in
# scripts/README.md. It is deliberately absent from
# backend/, database/ and tests/, which must never manipulate
# sys.path.
# ==========================================================

import sys

from pathlib import Path

PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[2]
)

if str(PROJECT_ROOT) not in sys.path:

    sys.path.insert(
        0,
        str(
            PROJECT_ROOT
        ),
    )


import csv
from pathlib import Path

import cv2
import numpy as np

from backend.app.services.ocr_service import OCRService  # noqa: E402



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

# ==========================================================
# DOCUMENT CONFIGURATION
# ==========================================================

DOCUMENTS = {

    "sia_badge": {
        "path": "evaluation/images/sia_badge/sia_001.jpg",

        "critical_fields": [
            "1099 4265 1706 9065",
            "24 MAR 2021",
            "M.GREEN",
        ],
    },

    "id_card": {
        "path": "evaluation/images/id_card/id_001.jpg",

        "critical_fields": [
            "026205000366",
            "PHAN VAN MANH",
            "23/08/2006",
        ],
    },

    "guard_license": {
        "path": "evaluation/images/guard_license/guard_001.jpg",

        "critical_fields": [
            "12345678",
            "01/01/2026",
            "SAMPLE,JANE",
        ],
    },
}


# ==========================================================
# OUTPUT DIRECTORY
# ==========================================================

OUTPUT_ROOT = Path(
    "output/preprocessing_benchmark"
)


# ==========================================================
# NORMALIZE TEXT
# ==========================================================

def normalize_text(
    text: str,
) -> str:
    """
    Normalize OCR and ground-truth text before comparison.

    Examples:

    M.GREEN
    M GREEN
    m.green

    all become:

    MGREEN
    """

    return "".join(
        character
        for character in text.upper()
        if character.isalnum()
    )


# ==========================================================
# ESTIMATE DOCUMENT SKEW
# ==========================================================

def estimate_skew_angle(
    image: np.ndarray,
) -> float:
    """
    Estimate small document skew using Hough lines.

    Handles different OpenCV HoughLinesP output shapes.

    Returns:
        Estimated angle in degrees.

    Example:
        1.2  -> slightly rotated
        0.0  -> no useful skew detected
    """

    # ------------------------------------------------------
    # Convert to grayscale
    # ------------------------------------------------------

    gray = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2GRAY,
    )


    # ------------------------------------------------------
    # Edge detection
    # ------------------------------------------------------

    edges = cv2.Canny(
        gray,
        50,
        150,
        apertureSize=3,
    )


    # ------------------------------------------------------
    # Detect straight lines
    # ------------------------------------------------------

    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=80,
        minLineLength=30,
        maxLineGap=10,
    )


    # No lines detected
    if lines is None:
        return 0.0


    angles: list[float] = []


    for line in lines:

        # --------------------------------------------------
        # OpenCV may return either:
        #
        # [[x1, y1, x2, y2]]
        #
        # or:
        #
        # [x1, y1, x2, y2]
        #
        # Flattening makes both formats safe.
        # --------------------------------------------------

        coordinates = np.asarray(
            line
        ).reshape(-1)


        if len(coordinates) < 4:
            continue


        x1, y1, x2, y2 = (
            coordinates[:4]
        )


        dx = x2 - x1
        dy = y2 - y1


        # Ignore vertical lines
        if dx == 0:
            continue


        angle = np.degrees(
            np.arctan2(
                dy,
                dx,
            )
        )


        # --------------------------------------------------
        # We only want small document rotation.
        #
        # Vertical edges and heavily angled objects should
        # not influence deskew calculation.
        # --------------------------------------------------

        if abs(angle) <= 15:

            angles.append(
                float(angle)
            )


    if not angles:
        return 0.0


    # Median reduces the effect of outlier lines
    return float(
        np.median(
            angles
        )
    )


# ==========================================================
# ROTATE IMAGE
# ==========================================================

def rotate_image(
    image: np.ndarray,
    angle: float,
) -> np.ndarray:
    """
    Rotate image around its center.

    Border replication prevents large black borders.
    """

    height, width = image.shape[:2]


    center = (
        width / 2,
        height / 2,
    )


    rotation_matrix = (
        cv2.getRotationMatrix2D(
            center,
            angle,
            1.0,
        )
    )


    rotated = cv2.warpAffine(
        image,
        rotation_matrix,
        (
            width,
            height,
        ),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )


    return rotated


# ==========================================================
# CREATE PREPROCESSING VARIANTS
# ==========================================================

def create_variants(
    image: np.ndarray,
) -> tuple[
    dict[str, np.ndarray],
    float,
]:
    """
    Create preprocessing variants used in Phase 1.

    Variants:

    1. Original
    2. Grayscale
    3. Otsu Threshold
    4. Deskew
    """

    # ------------------------------------------------------
    # ORIGINAL
    # ------------------------------------------------------

    original = image.copy()


    # ------------------------------------------------------
    # GRAYSCALE
    # ------------------------------------------------------

    grayscale = cv2.cvtColor(
        original,
        cv2.COLOR_BGR2GRAY,
    )


    # ------------------------------------------------------
    # OTSU THRESHOLD
    # ------------------------------------------------------

    _, threshold = cv2.threshold(
        grayscale,
        0,
        255,
        cv2.THRESH_BINARY
        + cv2.THRESH_OTSU,
    )


    # ------------------------------------------------------
    # DESKEW
    # ------------------------------------------------------

    skew_angle = estimate_skew_angle(
        original
    )


    # If document skew is +1 degree,
    # rotate by -1 degree to correct it.
    deskew = rotate_image(
        original,
        -skew_angle,
    )


    variants = {
        "original": original,
        "grayscale": grayscale,
        "threshold": threshold,
        "deskew": deskew,
    }


    return variants, skew_angle


# ==========================================================
# SAVE IMAGE
# ==========================================================

def save_image(
    image: np.ndarray,
    output_path: Path,
) -> None:
    """
    Save preprocessing variant safely.
    """

    success = cv2.imwrite(
        str(output_path),
        image,
    )


    if not success:

        raise RuntimeError(
            f"Could not save image: "
            f"{output_path}"
        )


# ==========================================================
# CRITICAL FIELD ACCURACY
# ==========================================================

def calculate_critical_accuracy(
    expected_values: list[str],
    ocr_lines: list[dict],
) -> float:
    """
    Calculate exact-match accuracy for important document
    fields after normalization.

    Example:

    expected:
        M.GREEN

    OCR:
        M.GREEN

    -> correct

    expected:
        23/08/2006

    OCR:
        23/05/2005

    -> incorrect
    """

    normalized_ocr_lines = [

        normalize_text(
            line["text"]
        )

        for line in ocr_lines
    ]


    correct = 0


    for expected in expected_values:

        normalized_expected = (
            normalize_text(
                expected
            )
        )


        # --------------------------------------------------
        # Search expected value inside OCR lines
        # --------------------------------------------------

        found = any(

            normalized_expected
            == normalized_ocr

            or

            normalized_expected
            in normalized_ocr

            for normalized_ocr
            in normalized_ocr_lines
        )


        if found:
            correct += 1


    if not expected_values:
        return 0.0


    return (
        correct
        / len(expected_values)
    )


# ==========================================================
# AVERAGE OCR CONFIDENCE
# ==========================================================

def calculate_average_confidence(
    ocr_lines: list[dict],
) -> float:
    """
    Calculate average PaddleOCR confidence
    across all detected OCR lines.
    """

    if not ocr_lines:
        return 0.0


    total_confidence = sum(

        line["confidence"]

        for line in ocr_lines
    )


    return (
        total_confidence
        / len(ocr_lines)
    )


# ==========================================================
# PRINT OCR RESULT
# ==========================================================

def print_ocr_result(
    ocr_lines: list[dict],
) -> None:
    """
    Print OCR lines for debugging and comparison.
    """

    for index, line in enumerate(
        ocr_lines
    ):

        print(
            f"    [{index}] "
            f"{line['text']:<35} "
            f"{line['confidence']:.2%}"
        )


# ==========================================================
# MAIN BENCHMARK
# ==========================================================

def main() -> None:

    print(
        "\n========== PREPROCESSING BENCHMARK ==========\n"
    )


    # ------------------------------------------------------
    # Create output folder
    # ------------------------------------------------------

    OUTPUT_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )


    # ------------------------------------------------------
    # Initialize OCR only once
    # ------------------------------------------------------

    ocr_service = OCRService()


    benchmark_rows: list[dict] = []


    # ======================================================
    # PROCESS DOCUMENTS
    # ======================================================

    for document_name, config in (
        DOCUMENTS.items()
    ):

        print()
        print(
            "=" * 70
        )

        print(
            f"DOCUMENT: {document_name}"
        )

        print(
            "=" * 70
        )


        image_path = Path(
            config["path"]
        )


        # --------------------------------------------------
        # Check file exists
        # --------------------------------------------------

        if not image_path.exists():

            print(
                f"[ERROR] File does not exist: "
                f"{image_path}"
            )

            continue


        # --------------------------------------------------
        # Read image
        # --------------------------------------------------

        image = cv2.imread(
            str(image_path)
        )


        if image is None:

            print(
                f"[ERROR] OpenCV could not read: "
                f"{image_path}"
            )

            continue


        print(
            f"Image size: "
            f"{image.shape[1]}x"
            f"{image.shape[0]}"
        )


        # --------------------------------------------------
        # Create preprocessing variants
        # --------------------------------------------------

        variants, skew_angle = (
            create_variants(
                image
            )
        )


        print(
            f"Estimated skew angle: "
            f"{skew_angle:.2f}°"
        )


        # --------------------------------------------------
        # Document-specific output directory
        # --------------------------------------------------

        document_output = (
            OUTPUT_ROOT
            / document_name
        )


        document_output.mkdir(
            parents=True,
            exist_ok=True,
        )


        # ==================================================
        # PROCESS EACH VARIANT
        # ==================================================

        for variant_name, variant_image in (
            variants.items()
        ):

            print()
            print(
                "-" * 70
            )

            print(
                f"VARIANT: {variant_name}"
            )

            print(
                "-" * 70
            )


            # ----------------------------------------------
            # Save preprocessing image
            # ----------------------------------------------

            variant_path = (
                document_output
                / f"{variant_name}.jpg"
            )


            save_image(
                variant_image,
                variant_path,
            )


            print(
                f"Saved: {variant_path}"
            )


            # ----------------------------------------------
            # Run OCR
            # ----------------------------------------------

            try:

                ocr_lines = (
                    ocr_service.extract(
                        str(variant_path)
                    )
                )

            except Exception as error:

                print(
                    f"[ERROR] OCR failed for "
                    f"{document_name} / "
                    f"{variant_name}"
                )

                print(
                    f"Reason: {error}"
                )

                continue


            # ----------------------------------------------
            # Print OCR lines
            # ----------------------------------------------

            print(
                "\nOCR Results:"
            )


            print_ocr_result(
                ocr_lines
            )


            # ----------------------------------------------
            # Critical field accuracy
            # ----------------------------------------------

            critical_accuracy = (
                calculate_critical_accuracy(
                    config[
                        "critical_fields"
                    ],
                    ocr_lines,
                )
            )


            # ----------------------------------------------
            # Average OCR confidence
            # ----------------------------------------------

            average_confidence = (
                calculate_average_confidence(
                    ocr_lines
                )
            )


            print(
                "\nMetrics:"
            )


            print(
                f"Critical Field Accuracy: "
                f"{critical_accuracy:.2%}"
            )


            print(
                f"Average OCR Confidence:  "
                f"{average_confidence:.2%}"
            )


            # ----------------------------------------------
            # Save benchmark row
            # ----------------------------------------------

            benchmark_rows.append(
                {
                    "document":
                        document_name,

                    "variant":
                        variant_name,

                    "critical_field_accuracy":
                        critical_accuracy,

                    "average_ocr_confidence":
                        average_confidence,
                }
            )


    # ======================================================
    # SAVE CSV
    # ======================================================

    csv_path = (
        OUTPUT_ROOT
        / "benchmark_summary.csv"
    )


    with open(
        csv_path,
        "w",
        newline="",
        encoding="utf-8",
    ) as csv_file:

        fieldnames = [
            "document",
            "variant",
            "critical_field_accuracy",
            "average_ocr_confidence",
        ]


        writer = csv.DictWriter(
            csv_file,
            fieldnames=fieldnames,
        )


        writer.writeheader()


        writer.writerows(
            benchmark_rows
        )


    # ======================================================
    # PRINT FINAL SUMMARY
    # ======================================================

    print()
    print()
    print(
        "=" * 70
    )

    print(
        "BENCHMARK SUMMARY"
    )

    print(
        "=" * 70
    )


    for row in benchmark_rows:

        print(
            f"{row['document']:<16} "
            f"{row['variant']:<12} "
            f"accuracy="
            f"{row['critical_field_accuracy']:.2%} "
            f"confidence="
            f"{row['average_ocr_confidence']:.2%}"
        )


    print()
    print(
        "=" * 70
    )

    print(
        "BENCHMARK COMPLETE"
    )

    print(
        "=" * 70
    )


    print(
        "\nCSV saved to:"
    )

    print(
        csv_path.resolve()
    )


    print(
        "\nPreprocessed images saved to:"
    )

    print(
        OUTPUT_ROOT.resolve()
    )


# ==========================================================
# ENTRY POINT
# ==========================================================

if __name__ == "__main__":

    main()