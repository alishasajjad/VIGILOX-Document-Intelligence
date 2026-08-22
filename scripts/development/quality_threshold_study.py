import argparse
import json
import statistics
import sys

from datetime import (
    datetime,
    timezone,
)
from pathlib import Path

import cv2
import numpy as np


# ==========================================================
# IMAGE QUALITY THRESHOLD STUDY
# PHASE 10.1
# ==========================================================
#
# WHY THIS EXISTS
# ----------------------------------------------------------
#
# A quality threshold picked from intuition is a threshold
# that fires on real documents. "Blurry means Laplacian
# variance under 100" sounds reasonable and would reject a
# fifth of this project's own benchmark set.
#
# So every threshold in document_quality_service.py comes from
# this script, and this script is the justification for it.
#
#
# THE PROBLEM WITH THE AVAILABLE DATA
# ----------------------------------------------------------
#
# All 63 benchmark documents are labelled quality: "clean".
# There are no blurry, dark or rotated fixtures. That bounds
# what can be honestly claimed:
#
#   FALSE POSITIVES can be measured properly. A threshold that
#   fires on any of the 63 known-good documents is wrong, and
#   that is checkable.
#
#   FALSE NEGATIVES cannot be measured against real degraded
#   documents, because none exist.
#
# Rather than leave the second half unmeasured, degradations
# are generated deterministically from the clean originals:
# known blur radii, known brightness scales, known contrast
# reductions, known downscales, known rotations. The magnitude
# is known because we applied it, so "does the metric notice"
# becomes answerable.
#
# This is weaker than labelled real degraded documents and the
# report says so. It is considerably stronger than choosing a
# number because it looks round.
#
#
# NO PROVIDER CALLS
# ----------------------------------------------------------
#
# Pixel arithmetic only. No OCR, no Groq. Free to run, so
# there is no excuse for changing a threshold without it.
# ==========================================================

PROJECT_ROOT = (
    Path(
        __file__
    )
    .resolve()
    .parents[2]
)


if str(
    PROJECT_ROOT
) not in sys.path:

    sys.path.insert(
        0,
        str(
            PROJECT_ROOT
        ),
    )


from backend.app.services.document_quality_service import (   # noqa: E402
    BLUR_VARIANCE_FLOOR,
    BLUR_VARIANCE_UNREADABLE,
    CONTRAST_FLOOR_STUDY_ONLY,
    DARKNESS_FLOOR,
    MIN_SHORTER_SIDE_PX,
    OVEREXPOSURE_CEILING,
    ROTATION_CONCERN_DEGREES,
    DocumentQualityService,
)


IMAGES_ROOT = (
    PROJECT_ROOT
    / "evaluation"
    / "images"
)

OUTPUT_ROOT = (
    PROJECT_ROOT
    / "output"
    / "quality"
)


# ==========================================================
# DEGRADATIONS
# ==========================================================
#
# Each one is a named, deterministic transform with a known
# magnitude. Applied to every clean document, so each
# degradation gets a distribution rather than one example.
# ==========================================================

def degrade_blur(
    image: np.ndarray,
    sigma: float,
) -> np.ndarray:

    # Kernel sized from sigma, forced odd, as OpenCV requires.
    radius = max(
        1,
        int(
            round(
                sigma * 3
            )
        ),
    )

    size = radius * 2 + 1

    return cv2.GaussianBlur(
        image,
        (size, size),
        sigma,
    )


def degrade_brightness(
    image: np.ndarray,
    scale: float,
) -> np.ndarray:

    return cv2.convertScaleAbs(
        image,
        alpha=scale,
        beta=0,
    )


def degrade_contrast(
    image: np.ndarray,
    scale: float,
) -> np.ndarray:

    # Pull every pixel towards mid-grey by the given factor.
    # Keeps the mean roughly where it was, so this isolates
    # contrast from exposure.
    mid = 127.5

    result = (
        (
            image.astype(
                np.float32
            )
            - mid
        )
        * scale
        + mid
    )

    return np.clip(
        result,
        0,
        255,
    ).astype(
        np.uint8
    )


def degrade_scale(
    image: np.ndarray,
    factor: float,
) -> np.ndarray:

    height, width = image.shape[:2]

    return cv2.resize(
        image,
        (
            max(
                1,
                int(
                    width * factor
                ),
            ),
            max(
                1,
                int(
                    height * factor
                ),
            ),
        ),
        interpolation=cv2.INTER_AREA,
    )


def degrade_rotation(
    image: np.ndarray,
    degrees: float,
) -> np.ndarray:

    height, width = image.shape[:2]

    matrix = (
        cv2.getRotationMatrix2D(
            (
                width / 2.0,
                height / 2.0,
            ),
            degrees,
            1.0,
        )
    )

    return cv2.warpAffine(
        image,
        matrix,
        (width, height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )


DEGRADATIONS = (
    ("blur_sigma_1", lambda i: degrade_blur(i, 1.0)),
    ("blur_sigma_2", lambda i: degrade_blur(i, 2.0)),
    ("blur_sigma_4", lambda i: degrade_blur(i, 4.0)),
    ("dark_0.50x", lambda i: degrade_brightness(i, 0.50)),
    ("dark_0.35x", lambda i: degrade_brightness(i, 0.35)),
    ("dark_0.20x", lambda i: degrade_brightness(i, 0.20)),
    ("bright_1.3x", lambda i: degrade_brightness(i, 1.3)),
    ("bright_1.6x", lambda i: degrade_brightness(i, 1.6)),
    ("contrast_0.50x", lambda i: degrade_contrast(i, 0.50)),
    ("contrast_0.25x", lambda i: degrade_contrast(i, 0.25)),
    ("scale_0.60x", lambda i: degrade_scale(i, 0.60)),
    ("scale_0.40x", lambda i: degrade_scale(i, 0.40)),
    ("rotate_3deg", lambda i: degrade_rotation(i, 3.0)),
    ("rotate_10deg", lambda i: degrade_rotation(i, 10.0)),
)


METRICS = (
    "shorter_side_px",
    "laplacian_variance",
    "mean_luminance",
    "contrast_spread",
    "estimated_skew_degrees",
)


# ==========================================================
# MEASUREMENT
# ==========================================================

def clean_documents() -> list:

    found = []

    for path in sorted(
        IMAGES_ROOT.rglob(
            "*"
        )
    ):

        if path.is_file() and path.suffix.lower() in (
            ".jpg",
            ".jpeg",
            ".png",
        ):
            found.append(
                path
            )

    if not found:
        raise SystemExit(
            f"No images under {IMAGES_ROOT}."
        )

    return found


def distribution(
    values: list,
) -> dict:

    """
    Summarise a metric, separating unmeasurable results.

    estimated_skew_degrees returns None when no near-horizontal
    line was found, and that count is the whole question for
    that metric: a signal that is unmeasurable on good
    documents has no measurable false-positive rate.
    """

    numeric = [
        value
        for value in values
        if value is not None
    ]

    unmeasurable = (
        len(values)
        - len(numeric)
    )

    if not numeric:

        return {
            "count": 0,
            "unmeasurable": unmeasurable,
            "min": None,
            "p05": None,
            "median": None,
            "p95": None,
            "max": None,
        }

    ordered = sorted(
        numeric
    )

    return {
        "unmeasurable":
            unmeasurable,

        "count":
            len(ordered),

        "min":
            round(
                ordered[0],
                2,
            ),

        "p05":
            round(
                float(
                    np.percentile(
                        ordered,
                        5,
                    )
                ),
                2,
            ),

        "median":
            round(
                statistics.median(
                    ordered
                ),
                2,
            ),

        "p95":
            round(
                float(
                    np.percentile(
                        ordered,
                        95,
                    )
                ),
                2,
            ),

        "max":
            round(
                ordered[-1],
                2,
            ),
    }


def measure_variant(
    service: DocumentQualityService,
    image: np.ndarray,
    scratch: Path,
) -> dict:

    """
    Measure one image array.

    Written to a scratch file because the service's entry
    point takes a path -- which is the real production entry
    point, so the study exercises exactly what ships rather
    than a private helper.
    """

    cv2.imwrite(
        str(
            scratch
        ),
        image,
    )

    assessment = (
        service.assess(
            scratch
        )
    )

    return {
        "metrics":
            assessment.metrics,

        "codes":
            assessment.codes(),
    }


def run(
    limit: int | None,
) -> dict:

    service = (
        DocumentQualityService()
    )

    documents = (
        clean_documents()
    )

    if limit:
        documents = documents[:limit]


    scratch_dir = (
        OUTPUT_ROOT
        / "scratch"
    )

    scratch_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    scratch = (
        scratch_dir
        / "variant.png"
    )


    # metric -> variant -> [values]
    samples: dict = {
        metric: {
            "clean": [],
        }
        for metric in METRICS
    }

    # variant -> code -> count
    fired: dict = {
        "clean": {},
    }

    for name, _ in DEGRADATIONS:
        fired[name] = {}
        for metric in METRICS:
            samples[metric][name] = []


    print(
        f"Measuring {len(documents)} clean documents "
        f"and {len(DEGRADATIONS)} degradations each "
        f"({len(documents) * (len(DEGRADATIONS) + 1)} "
        "measurements)..."
    )


    for position, path in enumerate(
        documents,
        start=1,
    ):

        if position % 10 == 0 or position == 1:
            print(
                f"  [{position}/{len(documents)}]"
            )


        original = (
            cv2.imdecode(
                np.fromfile(
                    str(
                        path
                    ),
                    dtype=np.uint8,
                ),
                cv2.IMREAD_COLOR,
            )
        )

        if original is None:
            continue


        # ---- clean, measured through the real entry point
        assessment = (
            service.assess(
                path
            )
        )

        for metric in METRICS:
            samples[metric]["clean"].append(
                assessment.metrics[metric]
            )

        for code in assessment.codes():
            fired["clean"][code] = (
                fired["clean"].get(
                    code,
                    0,
                )
                + 1
            )


        # ---- degradations
        for name, transform in DEGRADATIONS:

            result = (
                measure_variant(
                    service,
                    transform(
                        original
                    ),
                    scratch,
                )
            )

            for metric in METRICS:
                samples[metric][name].append(
                    result["metrics"][metric]
                )

            for code in result["codes"]:
                fired[name][code] = (
                    fired[name].get(
                        code,
                        0,
                    )
                    + 1
                )


    scratch.unlink(
        missing_ok=True,
    )

    try:
        scratch_dir.rmdir()
    except OSError:
        pass


    return {
        "measured_at":
            datetime.now(
                timezone.utc
            ).isoformat(
                timespec="seconds"
            ),

        "documents":
            len(documents),

        "thresholds_in_force": {
            "MIN_SHORTER_SIDE_PX":
                MIN_SHORTER_SIDE_PX,

            "BLUR_VARIANCE_FLOOR":
                BLUR_VARIANCE_FLOOR,

            "BLUR_VARIANCE_UNREADABLE":
                BLUR_VARIANCE_UNREADABLE,

            "DARKNESS_FLOOR":
                DARKNESS_FLOOR,

            "OVEREXPOSURE_CEILING":
                OVEREXPOSURE_CEILING,

            "CONTRAST_FLOOR_STUDY_ONLY":
                CONTRAST_FLOOR_STUDY_ONLY,

            "ROTATION_CONCERN_DEGREES":
                ROTATION_CONCERN_DEGREES,
        },

        "distributions": {
            metric: {
                variant: distribution(
                    values
                )
                for variant, values in variants.items()
                if values
            }
            for metric, variants in samples.items()
        },

        "findings_fired":
            fired,
    }


# ==========================================================
# REPORT
# ==========================================================

def render(
    report: dict,
) -> None:

    documents = report[
        "documents"
    ]

    print()
    print("=" * 78)
    print(
        "PHASE 10.1 - IMAGE QUALITY THRESHOLD STUDY"
    )
    print("=" * 78)
    print()
    print(
        f"  {documents} clean benchmark documents, "
        f"{len(DEGRADATIONS)} deterministic degradations "
        "each."
    )
    print(
        "  All benchmark fixtures are labelled clean, so "
        "false positives are measured"
    )
    print(
        "  against real data and false negatives against "
        "generated degradations."
    )


    for metric in METRICS:

        print()
        print(
            f"  {metric}"
        )
        print(
            "  " + "-" * 74
        )
        print(
            f"  {'VARIANT':<18}{'MIN':>11}{'P05':>11}"
            f"{'MEDIAN':>11}{'P95':>11}{'MAX':>11}"
        )

        variants = report["distributions"][metric]

        for variant in [
            "clean"
        ] + [
            name
            for name, _ in DEGRADATIONS
        ]:

            if variant not in variants:
                continue

            stat = variants[variant]

            if stat["min"] is None:

                print(
                    f"  {variant:<18}"
                    f"{'unmeasurable on all':>57}"
                    f"  ({stat['unmeasurable']})"
                )

                continue

            note = (
                f"   {stat['unmeasurable']} unmeasurable"
                if stat.get("unmeasurable")
                else ""
            )

            print(
                f"  {variant:<18}"
                f"{stat['min']:>11.2f}"
                f"{stat['p05']:>11.2f}"
                f"{stat['median']:>11.2f}"
                f"{stat['p95']:>11.2f}"
                f"{stat['max']:>11.2f}"
                f"{note}"
            )


    print()
    print(
        "  FINDINGS FIRED"
    )
    print(
        "  " + "-" * 74
    )
    print(
        "  A finding on 'clean' is a FALSE POSITIVE and "
        "must be zero."
    )
    print()

    fired = report[
        "findings_fired"
    ]

    for variant in [
        "clean"
    ] + [
        name
        for name, _ in DEGRADATIONS
    ]:

        codes = fired.get(
            variant,
            {},
        )

        if not codes:
            summary = "(none)"

        else:
            summary = ", ".join(
                f"{code} x{count}"
                for code, count in sorted(
                    codes.items()
                )
            )

        marker = (
            "  <-- FALSE POSITIVE"
            if variant == "clean" and codes
            else ""
        )

        print(
            f"  {variant:<18}{summary}{marker}"
        )


    print()
    print(
        "  VERDICT"
    )
    print(
        "  " + "-" * 74
    )

    false_positives = (
        fired.get(
            "clean",
            {},
        )
    )

    if false_positives:
        print(
            "  FAIL: thresholds fire on known-good "
            f"documents: {false_positives}"
        )

    else:
        print(
            f"  No finding fires on any of the "
            f"{documents} known-good documents."
        )

    print()


# ==========================================================
# MAIN
# ==========================================================

def main() -> int:

    parser = (
        argparse.ArgumentParser(
            description=(
                "Measure image quality metrics across the "
                "benchmark set and deterministic "
                "degradations of it."
            )
        )
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "Measure only the first N clean documents. "
            "For a quick pass; the reported thresholds "
            "come from the full set."
        ),
    )

    parser.add_argument(
        "--save",
        action="store_true",
        help=(
            "Write the study to output/quality/."
        ),
    )

    arguments = (
        parser.parse_args()
    )

    report = (
        run(
            arguments.limit
        )
    )

    render(
        report
    )


    if arguments.save:

        OUTPUT_ROOT.mkdir(
            parents=True,
            exist_ok=True,
        )

        stamp = (
            report["measured_at"]
            .replace(":", "")
            .replace("-", "")
        )

        destination = (
            OUTPUT_ROOT
            / f"threshold_study_{stamp}.json"
        )

        destination.write_text(
            json.dumps(
                report,
                indent=2,
            ),
            encoding="utf-8",
        )

        print(
            f"  saved to {destination}"
        )
        print()


    # A study that finds a false positive is a failing study.
    return (
        1
        if report["findings_fired"].get(
            "clean"
        )
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
