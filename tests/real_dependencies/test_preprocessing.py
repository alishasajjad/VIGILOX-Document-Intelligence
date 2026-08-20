from pathlib import Path

import cv2
import numpy as np



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
# SAMPLE DOCUMENTS
# ==========================================================

SAMPLE_IMAGES = {
    "sia_badge": "evaluation/images/sia_badge/sia_001.jpg",
    "id_card": "evaluation/images/id_card/id_001.jpg",
    "guard_license": "evaluation/images/guard_license/guard_001.jpg",
}


# ==========================================================
# OUTPUT DIRECTORY
# ==========================================================

OUTPUT_ROOT = Path(
    "output/preprocessing"
)


# ==========================================================
# ESTIMATE DOCUMENT SKEW ANGLE
# ==========================================================

def estimate_skew_angle(
    image: np.ndarray,
) -> float:
    """
    Estimate small document rotation/skew using Hough lines.

    Returns:
        Estimated angle in degrees.

    Example:
        1.2   -> document is slightly rotated
        0.0   -> no useful skew detected
    """

    # Convert image to grayscale
    gray = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2GRAY,
    )


    # Detect edges
    edges = cv2.Canny(
        gray,
        50,
        150,
        apertureSize=3,
    )


    # Detect straight lines
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
        # OpenCV versions can return different array shapes:
        #
        # [[x1, y1, x2, y2]]
        #
        # or
        #
        # [x1, y1, x2, y2]
        #
        # reshape(-1) safely handles both.
        # --------------------------------------------------

        coordinates = np.asarray(
            line
        ).reshape(-1)


        # Safety check
        if len(coordinates) < 4:
            continue


        x1, y1, x2, y2 = (
            coordinates[:4]
        )


        dx = x2 - x1
        dy = y2 - y1


        # Vertical line - not useful for horizontal skew
        if dx == 0:
            continue


        angle = np.degrees(
            np.arctan2(
                dy,
                dx,
            )
        )


        # --------------------------------------------------
        # Only use small angles.
        #
        # We want document skew,
        # not vertical text or object edges.
        # --------------------------------------------------

        if abs(angle) <= 15:

            angles.append(
                float(angle)
            )


    # No useful horizontal lines found
    if not angles:
        return 0.0


    # Median is more stable than average
    return float(
        np.median(
            angles
        )
    )


# ==========================================================
# ROTATE / DESKEW IMAGE
# ==========================================================

def rotate_image(
    image: np.ndarray,
    angle: float,
) -> np.ndarray:
    """
    Rotate image around its center.

    Border pixels are replicated so we do not introduce
    large black areas around the document.
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
    Create the four preprocessing variants used
    in our Phase 1 experiments:

    1. Original
    2. Grayscale
    3. Otsu threshold
    4. Deskew
    """

    # ------------------------------------------------------
    # 1. ORIGINAL
    # ------------------------------------------------------

    original = image.copy()


    # ------------------------------------------------------
    # 2. GRAYSCALE
    # ------------------------------------------------------

    grayscale = cv2.cvtColor(
        original,
        cv2.COLOR_BGR2GRAY,
    )


    # ------------------------------------------------------
    # 3. OTSU THRESHOLD
    # ------------------------------------------------------

    _, threshold = cv2.threshold(
        grayscale,
        0,
        255,
        cv2.THRESH_BINARY
        + cv2.THRESH_OTSU,
    )


    # ------------------------------------------------------
    # 4. DESKEW
    # ------------------------------------------------------

    skew_angle = estimate_skew_angle(
        original
    )


    # To correct +1 degree skew,
    # rotate by -1 degree.
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
    Save an image and raise an error if OpenCV
    fails to write it.
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
# MAIN
# ==========================================================

def main() -> None:

    print(
        "\n========== PREPROCESSING TEST ==========\n"
    )


    # Create root output folder
    OUTPUT_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )


    for document_name, image_path in (
        SAMPLE_IMAGES.items()
    ):

        print(
            "=" * 65
        )

        print(
            f"DOCUMENT: {document_name}"
        )

        print(
            f"INPUT:    {image_path}"
        )

        print(
            "=" * 65
        )


        # --------------------------------------------------
        # CHECK INPUT FILE
        # --------------------------------------------------

        input_path = Path(
            image_path
        )


        if not input_path.exists():

            print(
                f"[ERROR] Image not found: "
                f"{image_path}"
            )

            print()

            continue


        # --------------------------------------------------
        # READ IMAGE
        # --------------------------------------------------

        image = cv2.imread(
            str(input_path)
        )


        if image is None:

            print(
                f"[ERROR] OpenCV could not read: "
                f"{image_path}"
            )

            print()

            continue


        print(
            f"Image size: "
            f"{image.shape[1]}x"
            f"{image.shape[0]}"
        )


        # --------------------------------------------------
        # CREATE PREPROCESSING VARIANTS
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
        # CREATE DOCUMENT OUTPUT FOLDER
        # --------------------------------------------------

        document_output = (
            OUTPUT_ROOT
            / document_name
        )


        document_output.mkdir(
            parents=True,
            exist_ok=True,
        )


        # --------------------------------------------------
        # SAVE ALL VARIANTS
        # --------------------------------------------------

        for variant_name, variant in (
            variants.items()
        ):

            output_path = (
                document_output
                / f"{variant_name}.jpg"
            )


            save_image(
                variant,
                output_path,
            )


            print(
                f"[SAVED] "
                f"{variant_name:<10} "
                f"-> {output_path}"
            )


        print()


    # ======================================================
    # FINISHED
    # ======================================================

    print(
        "=" * 65
    )

    print(
        "PREPROCESSING COMPLETE"
    )

    print(
        "=" * 65
    )


    print(
        "\nFiles saved to:"
    )

    print(
        OUTPUT_ROOT.resolve()
    )


# ==========================================================
# ENTRY POINT
# ==========================================================

if __name__ == "__main__":

    main()