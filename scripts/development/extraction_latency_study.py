"""
==========================================================
EXTRACTION LATENCY STUDY
PHASE 10.4
==========================================================

WHY THIS EXISTS
----------------------------------------------------------

Phase 10.4 has to bound how long extraction can take, because
the worker holds a lease while it runs and the lease is
finite. Bounding it means choosing a request timeout and a
retry count.

Choosing those from intuition is exactly the mistake Phase
10.1 made and the threshold study caught. So they are measured
instead.

WHAT IT MEASURES
----------------------------------------------------------

The extraction call ONLY -- one Groq completion per document,
timed individually. OCR runs first because extraction needs
real OCR lines to be a realistic request, but OCR is local and
free and its time is reported separately so it cannot be
confused with provider latency.

COST
----------------------------------------------------------

One Groq completion per document. Deliberately small: this is
a targeted measurement, not the 63-document benchmark, which
stays reserved for the end of Phase 12.

    python -m scripts.development.extraction_latency_study
    python -m scripts.development.extraction_latency_study --documents 6
"""

import argparse
import json
import statistics
import sys
import time

from pathlib import Path


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


from dotenv import load_dotenv          # noqa: E402

load_dotenv()


EVALUATION_IMAGES = (
    PROJECT_ROOT
    / "evaluation"
    / "images"
)


DOCUMENT_TYPES = (
    "guard_license",
    "id_card",
    "sia_badge",
)


def select_documents(
    per_type: int,
) -> list[Path]:

    """
    An even spread across the three supported types.

    Even rather than random, because OCR line count drives the
    prompt size and the three types do not produce the same
    amount of text. Sampling one type would measure that type.
    """

    selected: list[Path] = []

    for document_type in DOCUMENT_TYPES:

        directory = (
            EVALUATION_IMAGES
            / document_type
        )

        images = sorted(
            directory.glob(
                "*.jpg"
            )
        )[:per_type]

        selected.extend(
            images
        )

    return selected


def summarise(
    label: str,
    values: list[float],
) -> dict:

    if not values:
        return {
            "label": label,
            "count": 0,
        }

    ordered = sorted(
        values
    )

    def percentile(
        fraction: float,
    ) -> float:

        # Nearest-rank. With a sample this small an
        # interpolated percentile would imply a precision the
        # sample does not support.
        index = min(
            len(
                ordered
            ) - 1,
            int(
                round(
                    fraction
                    * (
                        len(
                            ordered
                        ) - 1
                    )
                )
            ),
        )

        return ordered[index]


    return {
        "label": label,
        "count": len(
            ordered
        ),
        "min": ordered[0],
        "median": statistics.median(
            ordered
        ),
        "p95": percentile(
            0.95
        ),
        "max": ordered[-1],
    }


def print_summary(
    summary: dict,
) -> None:

    if not summary["count"]:
        print(
            f"  {summary['label']:<22} no samples"
        )
        return


    print(
        f"  {summary['label']:<22}"
        f"n={summary['count']:<4}"
        f"min={summary['min']:7.2f}s  "
        f"median={summary['median']:7.2f}s  "
        f"p95={summary['p95']:7.2f}s  "
        f"max={summary['max']:7.2f}s"
    )


def main() -> int:

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--documents",
        type=int,
        default=9,
        help=(
            "Total documents to measure, spread across "
            "the three types. Default 9."
        ),
    )

    arguments = parser.parse_args()

    per_type = max(
        1,
        arguments.documents // len(
            DOCUMENT_TYPES
        ),
    )

    images = select_documents(
        per_type
    )


    print()
    print(
        "=" * 74
    )
    print(
        "EXTRACTION LATENCY STUDY"
    )
    print(
        "=" * 74
    )
    print()
    print(
        f"Documents: {len(images)} "
        f"({per_type} per type)"
    )
    print(
        "One real Groq completion each. OCR is local."
    )
    print()


    from backend.app.services.ocr_service import (
        OCRService,
    )

    from backend.app.services.extraction_service import (
        ExtractionService,
    )


    ocr = OCRService()

    extraction = ExtractionService()


    ocr_times: list[float] = []

    extraction_times: list[float] = []

    line_counts: list[float] = []

    prompt_characters: list[float] = []

    rows: list[dict] = []

    failures: list[dict] = []


    for image in images:

        started = time.perf_counter()

        try:
            lines = ocr.extract(
                str(
                    image
                )
            )

        except Exception as error:      # noqa: BLE001

            failures.append(
                {
                    "image": image.name,
                    "stage": "ocr",
                    "error": (
                        f"{type(error).__name__}: "
                        f"{error}"
                    ),
                }
            )

            continue


        ocr_seconds = (
            time.perf_counter()
            - started
        )


        # The characters actually sent, which is what drives
        # provider latency far more than the image does.
        characters = sum(
            len(
                str(
                    line.get(
                        "text",
                        "",
                    )
                )
            )
            for line in lines
        )


        started = time.perf_counter()

        try:
            extraction.extract(
                lines
            )

        except Exception as error:      # noqa: BLE001

            failures.append(
                {
                    "image": image.name,
                    "stage": "extraction",
                    "error": (
                        f"{type(error).__name__}: "
                        f"{error}"
                    )[:200],
                }
            )

            print(
                f"  {image.name:<20} "
                f"ocr={ocr_seconds:6.2f}s  "
                f"extraction=FAILED "
                f"({type(error).__name__})"
            )

            continue


        extraction_seconds = (
            time.perf_counter()
            - started
        )


        ocr_times.append(
            ocr_seconds
        )

        extraction_times.append(
            extraction_seconds
        )

        line_counts.append(
            float(
                len(
                    lines
                )
            )
        )

        prompt_characters.append(
            float(
                characters
            )
        )

        rows.append(
            {
                "image": image.name,
                "ocr_seconds": round(
                    ocr_seconds,
                    3,
                ),
                "extraction_seconds": round(
                    extraction_seconds,
                    3,
                ),
                "ocr_lines": len(
                    lines
                ),
                "ocr_characters": characters,
            }
        )

        print(
            f"  {image.name:<20} "
            f"ocr={ocr_seconds:6.2f}s  "
            f"extraction={extraction_seconds:6.2f}s  "
            f"lines={len(lines):3d}  "
            f"chars={characters:5d}"
        )


    print()
    print(
        "-" * 74
    )
    print(
        "DISTRIBUTIONS"
    )
    print(
        "-" * 74
    )

    print_summary(
        summarise(
            "extraction (provider)",
            extraction_times,
        )
    )

    print_summary(
        summarise(
            "ocr (local)",
            ocr_times,
        )
    )

    print_summary(
        summarise(
            "ocr lines",
            line_counts,
        )
    )

    print_summary(
        summarise(
            "ocr characters",
            prompt_characters,
        )
    )


    if failures:

        print()
        print(
            "-" * 74
        )
        print(
            f"FAILURES ({len(failures)})"
        )
        print(
            "-" * 74
        )

        for failure in failures:
            print(
                f"  {failure['image']:<20} "
                f"{failure['stage']:<12} "
                f"{failure['error']}"
            )


    # ------------------------------------------------------
    # WHAT THE NUMBERS IMPLY FOR A TIMEOUT
    # ------------------------------------------------------

    if extraction_times:

        summary = summarise(
            "extraction",
            extraction_times,
        )

        print()
        print(
            "-" * 74
        )
        print(
            "IMPLICATIONS"
        )
        print(
            "-" * 74
        )
        print()
        print(
            "  A read timeout has to be well above the "
            "measured maximum, or normal"
        )
        print(
            "  documents start failing. It also has to be "
            "small enough that the"
        )
        print(
            "  worst-case retry chain still fits inside "
            "the worker lease."
        )
        print()
        print(
            f"  measured max        {summary['max']:.2f}s"
        )
        print(
            f"  measured p95        {summary['p95']:.2f}s"
        )
        print()
        print(
            "  Sample size is small and deliberately so. "
            "These numbers bound a"
        )
        print(
            "  TIMEOUT, which only needs to sit safely "
            "above normal latency -- not"
        )
        print(
            "  a published performance claim."
        )


    output = (
        PROJECT_ROOT
        / "output"
        / "extraction_latency_study.json"
    )

    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output.write_text(
        json.dumps(
            {
                "documents": rows,
                "failures": failures,
                "extraction_seconds": summarise(
                    "extraction",
                    extraction_times,
                ),
                "ocr_seconds": summarise(
                    "ocr",
                    ocr_times,
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print(
        f"  written: {output.relative_to(PROJECT_ROOT)}"
    )
    print()

    return 0 if extraction_times else 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
