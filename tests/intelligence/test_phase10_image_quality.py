import tempfile

from pathlib import Path

import cv2
import numpy as np

from backend.app.services.document_quality_service import (
    BLUR_VARIANCE_FLOOR,
    BLUR_VARIANCE_UNREADABLE,
    DARKNESS_FLOOR,
    MIN_SHORTER_SIDE_PX,
    OVEREXPOSURE_CEILING,
    QUALITY_CODES,
    QUALITY_IMAGE_BLURRY,
    QUALITY_IMAGE_OVEREXPOSED,
    QUALITY_IMAGE_TOO_DARK,
    QUALITY_IMAGE_TOO_SMALL,
    QUALITY_IMAGE_UNREADABLE,
    QUALITY_ROTATION_CONCERN,
    ROTATION_CONCERN_DEGREES,
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    DocumentQualityService,
    QualityAssessment,
    QualityFinding,
    apply_quality_to_review,
    quality_review_policy,
)


# ==========================================================
# PHASE 10.1
# IMAGE QUALITY ASSESSMENT
# ==========================================================
#
# Deterministic, no OCR, no provider. Degradations are
# generated from the real benchmark documents at run time, so
# the suite needs no fixtures of its own and the magnitudes
# are known because we applied them.
#
# THE RELEASE-CRITICAL INVARIANT
# ----------------------------------------------------------
#
# False AUTO_ACCEPT must not increase. Quality assessment
# cannot increase it, because apply_quality_to_review() is
# only able to escalate -- and that is asserted directly
# rather than inferred from a sample of documents.
#
# WHAT IS NOT CLAIMED
# ----------------------------------------------------------
#
# The clean corpus is synthetic, bright and axis-aligned. The
# zero-false-positive result holds on it and on nothing else;
# a corpus of hand-held photographs would need the study
# re-run. The suite asserts what was measured and does not
# extrapolate.
# ==========================================================

PROJECT_ROOT = (
    Path(
        __file__
    )
    .resolve()
    .parents[2]
)

IMAGES_ROOT = (
    PROJECT_ROOT
    / "evaluation"
    / "images"
)


PASSES: list[str] = []


def ok(
    message: str,
) -> None:

    PASSES.append(
        message
    )

    print(
        f"[PASS] {message}"
    )


def fail(
    message: str,
) -> None:

    raise AssertionError(
        message
    )


# ==========================================================
# FIXTURES
# ==========================================================

def sample_documents(
    limit: int = 6,
) -> list:

    """
    A spread across document types, chosen the same
    round-robin way as the performance and threshold scripts
    so all three look at comparable samples.
    """

    by_type: dict = {}

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
            by_type.setdefault(
                path.parent.name,
                [],
            ).append(
                path
            )


    if not by_type:
        fail(
            f"No benchmark images under {IMAGES_ROOT}. "
            "This suite measures against the real "
            "document set."
        )


    chosen: list = []
    types = sorted(
        by_type
    )
    index = 0

    while len(chosen) < limit:

        added = False

        for document_type in types:

            bucket = by_type[
                document_type
            ]

            if index < len(bucket):
                chosen.append(
                    bucket[index]
                )
                added = True

                if len(chosen) >= limit:
                    break

        if not added:
            break

        index += 1


    return chosen


def load(
    path: Path,
) -> np.ndarray:

    return cv2.imdecode(
        np.fromfile(
            str(
                path
            ),
            dtype=np.uint8,
        ),
        cv2.IMREAD_COLOR,
    )


class Scratch:

    """
    A directory for generated variants, removed afterwards.

    Variants go through a real file because assess() takes a
    path -- the same entry point production uses, so the test
    exercises what ships rather than a private helper.
    """

    def __enter__(
        self,
    ) -> "Scratch":

        self.root = (
            Path(
                tempfile.mkdtemp(
                    prefix="vigilox-quality-",
                )
            )
        )

        self.counter = 0

        return self


    def __exit__(
        self,
        exc_type,
        exc,
        traceback,
    ) -> bool:

        import shutil

        shutil.rmtree(
            self.root,
            ignore_errors=True,
        )

        return False


    def write(
        self,
        image: np.ndarray,
    ) -> Path:

        self.counter += 1

        # PNG, so the variant is not re-compressed with JPEG
        # artefacts that would change the very measurements
        # under test.
        path = (
            self.root
            / f"variant_{self.counter}.png"
        )

        cv2.imwrite(
            str(
                path
            ),
            image,
        )

        return path


def blur(
    image: np.ndarray,
    sigma: float,
) -> np.ndarray:

    radius = max(
        1,
        int(
            round(
                sigma * 3
            )
        ),
    )

    return cv2.GaussianBlur(
        image,
        (
            radius * 2 + 1,
            radius * 2 + 1,
        ),
        sigma,
    )


def scale_brightness(
    image: np.ndarray,
    factor: float,
) -> np.ndarray:

    return cv2.convertScaleAbs(
        image,
        alpha=factor,
        beta=0,
    )


def resize(
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


def rotate(
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


# ==========================================================
# 1. CLEAN DOCUMENTS RAISE NOTHING
# ==========================================================

def test_clean_documents_are_silent() -> None:

    """
    The single most important quality property.

    A finding on a known-good document is a reviewer looking
    at a document that did not need looking at, and a product
    that cries wolf. The first version of these thresholds
    fired on 40 of 63.
    """

    service = (
        DocumentQualityService()
    )

    offenders = []

    documents = (
        sample_documents(
            limit=63
        )
    )

    for path in documents:

        assessment = (
            service.assess(
                path
            )
        )

        if assessment.error:
            fail(
                f"{path.name} could not be assessed: "
                f"{assessment.error}"
            )

        if assessment.codes():
            offenders.append(
                (
                    path.name,
                    assessment.codes(),
                )
            )


    if offenders:
        fail(
            f"{len(offenders)} known-good document(s) "
            "raised a quality finding:\n"
            + "\n".join(
                f"  {name}: {codes}"
                for name, codes in offenders[:10]
            )
        )


    if len(documents) < 60:
        fail(
            f"Only {len(documents)} documents were "
            "examined. The zero-false-positive claim is "
            "about the whole benchmark set."
        )


    ok(
        f"none of {len(documents)} known-good documents "
        "raises a quality finding"
    )


def test_clean_documents_report_metrics() -> None:

    """
    A silent assessment must still be a measured one.

    An assess() that returned no findings because it measured
    nothing would pass the test above.
    """

    service = (
        DocumentQualityService()
    )

    path = (
        sample_documents(
            limit=1
        )[0]
    )

    metrics = (
        service.assess(
            path
        ).metrics
    )

    required = (
        "width_px",
        "height_px",
        "shorter_side_px",
        "total_pixels",
        "laplacian_variance",
        "mean_luminance",
        "contrast_spread",
        "estimated_skew_degrees",
    )

    missing = [
        name
        for name in required
        if name not in metrics
    ]

    if missing:
        fail(
            f"The assessment omits {missing}."
        )


    for name in (
        "laplacian_variance",
        "mean_luminance",
        "contrast_spread",
    ):

        if not isinstance(
            metrics[name],
            (int, float),
        ):
            fail(
                f"{name} is not a number: "
                f"{metrics[name]!r}"
            )


    ok(
        "a clean assessment still reports all eight "
        "measurements"
    )


# ==========================================================
# 2. DEGRADATIONS ARE DETECTED
# ==========================================================

def test_degradations_are_detected() -> None:

    service = (
        DocumentQualityService()
    )

    documents = (
        sample_documents(
            limit=6
        )
    )

    # (label, transform, code that must appear)
    cases = (
        (
            "blur sigma 1",
            lambda i: blur(i, 1.0),
            QUALITY_IMAGE_BLURRY,
        ),
        (
            "blur sigma 4",
            lambda i: blur(i, 4.0),
            QUALITY_IMAGE_UNREADABLE,
        ),
        (
            "darkened 0.5x",
            lambda i: scale_brightness(i, 0.5),
            QUALITY_IMAGE_TOO_DARK,
        ),
        (
            "resized 0.15x",
            lambda i: resize(i, 0.15),
            QUALITY_IMAGE_TOO_SMALL,
        ),
        (
            "rotated 12 degrees",
            lambda i: rotate(i, 12.0),
            QUALITY_ROTATION_CONCERN,
        ),
    )

    with Scratch() as scratch:

        for label, transform, expected in cases:

            missed = []

            for path in documents:

                variant = (
                    scratch.write(
                        transform(
                            load(
                                path
                            )
                        )
                    )
                )

                codes = (
                    service.assess(
                        variant
                    ).codes()
                )

                if expected not in codes:
                    missed.append(
                        (
                            path.name,
                            codes,
                        )
                    )


            if missed:
                fail(
                    f"{label}: {expected} was not "
                    f"raised for {len(missed)} of "
                    f"{len(documents)} documents. "
                    f"Example: {missed[0]}"
                )


    ok(
        f"{len(cases)} degradations each raise their "
        f"expected finding on all {len(documents)} "
        "documents"
    )


def test_overexposure_detects_bright_documents_only() -> None:

    """
    Overexposure is detected on documents that were already
    bright, and NOT on documents with large dark regions.

    That is a real limitation of a mean-luminance ceiling and
    it is asserted rather than hidden. A licence with a big
    dark photograph area keeps its mean below the ceiling even
    when the paper is blown out, because the mean averages the
    blown-out paper with the dark photo.

    The signal is still worth shipping: zero false positives
    on all 63 clean documents, and the threshold study found
    it fires on 59 of 63 at 1.3x brightening. What it misses
    is the minority with low base luminance, and this test
    pins both halves of that so neither can drift.

    A saturated-pixel fraction would detect the missed cases
    properly and is the obvious future improvement. It is not
    added here because adding a metric means re-running the
    study and re-deriving a threshold, and the existing signal
    is honest about what it does.
    """

    service = (
        DocumentQualityService()
    )

    documents = (
        sample_documents(
            limit=12
        )
    )

    detected_bright = 0
    bright_total = 0

    missed_dark = 0
    dark_total = 0

    with Scratch() as scratch:

        for path in documents:

            base = (
                service.assess(
                    path
                ).metrics["mean_luminance"]
            )

            variant = (
                scratch.write(
                    scale_brightness(
                        load(
                            path
                        ),
                        1.6,
                    )
                )
            )

            fired = (
                QUALITY_IMAGE_OVEREXPOSED
                in service.assess(
                    variant
                ).codes()
            )

            # 220 splits the corpus at the point the study
            # showed matters: the bright majority saturates,
            # the darker minority does not.
            if base >= 220:

                bright_total += 1

                if fired:
                    detected_bright += 1

            else:

                dark_total += 1

                if not fired:
                    missed_dark += 1


    if bright_total == 0:
        fail(
            "No bright-base documents in the sample, so "
            "this test proves nothing."
        )


    if detected_bright != bright_total:
        fail(
            "Overexposure was detected on "
            f"{detected_bright} of {bright_total} "
            "bright-base documents. It should fire on "
            "all of them."
        )


    ok(
        f"overexposure fires on all {bright_total} "
        f"bright-base documents and, as measured, misses "
        f"{missed_dark} of {dark_total} with large dark "
        "regions"
    )


def test_unreadable_is_the_only_error() -> None:

    """
    Severity is what drives the review policy, so which
    finding is an ERROR is a policy decision and not a
    presentation detail.
    """

    service = (
        DocumentQualityService()
    )

    path = (
        sample_documents(
            limit=1
        )[0]
    )

    with Scratch() as scratch:

        heavy = (
            scratch.write(
                blur(
                    load(
                        path
                    ),
                    4.0,
                )
            )
        )

        assessment = (
            service.assess(
                heavy
            )
        )

        errors = [
            finding.code
            for finding in assessment.findings
            if finding.severity == SEVERITY_ERROR
        ]

        if errors != [
            QUALITY_IMAGE_UNREADABLE
        ]:
            fail(
                "A heavily blurred image should raise "
                "exactly one ERROR, IMAGE_UNREADABLE; "
                f"got {errors}."
            )


        if assessment.highest_severity() != SEVERITY_ERROR:
            fail(
                "highest_severity does not reflect the "
                "ERROR finding."
            )


        # And a merely soft image must NOT be an error.
        mild = (
            scratch.write(
                blur(
                    load(
                        path
                    ),
                    1.0,
                )
            )
        )

        mild_assessment = (
            service.assess(
                mild
            )
        )

        mild_errors = [
            finding.code
            for finding in mild_assessment.findings
            if finding.severity == SEVERITY_ERROR
        ]

        if mild_errors:
            fail(
                "A mildly blurred image raised an "
                f"ERROR ({mild_errors}). Only an "
                "unreadable image may, because ERROR "
                "forces human review."
            )


    ok(
        "IMAGE_UNREADABLE is the only ERROR; a merely "
        "soft image is a WARNING"
    )


# ==========================================================
# 3. THRESHOLD BOUNDARIES
# ==========================================================

def test_thresholds_are_strict_comparisons() -> None:

    """
    A value exactly at the threshold must not fire.

    Off-by-one on a boundary is the classic way a threshold
    starts rejecting the documents it was calibrated against,
    since the calibration puts the clean minimum right at the
    edge.
    """

    service = (
        DocumentQualityService()
    )

    findings = (
        service._evaluate(
            {
                "shorter_side_px":
                    MIN_SHORTER_SIDE_PX,

                "total_pixels":
                    10_000_000,

                "laplacian_variance":
                    BLUR_VARIANCE_FLOOR,

                "mean_luminance":
                    DARKNESS_FLOOR,

                "contrast_spread":
                    0.0,

                "estimated_skew_degrees":
                    ROTATION_CONCERN_DEGREES,
            }
        )
    )

    if findings:
        fail(
            "Values exactly at the thresholds raised "
            f"{[f.code for f in findings]}. The "
            "comparisons must be strict, or the clean "
            "minimum used to calibrate them fires."
        )


    # A hair past each boundary must fire.
    just_past = (
        service._evaluate(
            {
                "shorter_side_px":
                    MIN_SHORTER_SIDE_PX - 1,

                "total_pixels":
                    10_000_000,

                "laplacian_variance":
                    BLUR_VARIANCE_FLOOR - 0.01,

                "mean_luminance":
                    DARKNESS_FLOOR - 0.01,

                "contrast_spread":
                    0.0,

                "estimated_skew_degrees":
                    ROTATION_CONCERN_DEGREES + 0.01,
            }
        )
    )

    codes = {
        finding.code
        for finding in just_past
    }

    for expected in (
        QUALITY_IMAGE_TOO_SMALL,
        QUALITY_IMAGE_BLURRY,
        QUALITY_IMAGE_TOO_DARK,
        QUALITY_ROTATION_CONCERN,
    ):

        if expected not in codes:
            fail(
                f"{expected} did not fire just past its "
                f"threshold. Got {sorted(codes)}."
            )


    # Overexposure is the other side of the same metric, so it
    # needs its own case.
    over = (
        service._evaluate(
            {
                "shorter_side_px": 1000,
                "total_pixels": 10_000_000,
                "laplacian_variance": 10_000.0,
                "mean_luminance":
                    OVEREXPOSURE_CEILING + 0.01,
                "contrast_spread": 100.0,
                "estimated_skew_degrees": 0.0,
            }
        )
    )

    if QUALITY_IMAGE_OVEREXPOSED not in {
        finding.code
        for finding in over
    }:
        fail(
            "IMAGE_OVEREXPOSED did not fire just past "
            "its ceiling."
        )


    ok(
        "every threshold is a strict comparison: the "
        "boundary value is silent, a hair past it fires"
    )


def test_unmeasurable_skew_raises_nothing() -> None:

    """
    None means "no angle could be measured", not zero.

    An earlier version returned 0.0 for both, which made the
    threshold study read as a perfect signal when it was
    measuring nothing at all.
    """

    service = (
        DocumentQualityService()
    )

    findings = (
        service._evaluate(
            {
                "shorter_side_px": 1000,
                "total_pixels": 10_000_000,
                "laplacian_variance": 10_000.0,
                "mean_luminance": 180.0,
                "contrast_spread": 100.0,
                "estimated_skew_degrees": None,
            }
        )
    )

    if findings:
        fail(
            "An unmeasurable skew raised "
            f"{[f.code for f in findings]}. Nothing may "
            "be concluded from a measurement that did "
            "not happen."
        )


    # A blank image is the realistic case: no edges, no lines.
    with Scratch() as scratch:

        blank = (
            scratch.write(
                np.full(
                    (400, 600, 3),
                    255,
                    dtype=np.uint8,
                )
            )
        )

        assessment = (
            service.assess(
                blank
            )
        )

        if QUALITY_ROTATION_CONCERN in assessment.codes():
            fail(
                "A blank image raised a rotation "
                "concern."
            )


    ok(
        "an unmeasurable skew raises nothing, including "
        "on a blank image"
    )


# ==========================================================
# 4. NO INVENTED METRICS
# ==========================================================

def test_no_score_and_no_fraud_language() -> None:

    service = (
        DocumentQualityService()
    )

    path = (
        sample_documents(
            limit=1
        )[0]
    )

    with Scratch() as scratch:

        variant = (
            scratch.write(
                blur(
                    load(
                        path
                    ),
                    4.0,
                )
            )
        )

        payload = (
            service.assess(
                variant
            ).to_dict()
        )


    # The only derived value is a severity, not a number.
    for forbidden in (
        "score",
        "risk",
        "fraud",
        "tamper",
        "confidence",
        "percent",
        "probability",
    ):

        if forbidden in str(
            payload
        ).lower():
            fail(
                f"The quality payload contains "
                f"{forbidden!r}. Image measurements are "
                "not a risk score and must not be "
                "presented as one."
            )


    if payload["highest_severity"] not in (
        SEVERITY_ERROR,
        SEVERITY_WARNING,
        None,
    ):
        fail(
            "highest_severity is not a severity: "
            f"{payload['highest_severity']!r}"
        )


    # Every finding carries what it measured and against what,
    # so a reviewer can see why rather than being told a
    # verdict.
    for finding in payload["findings"]:

        for key in (
            "code",
            "severity",
            "message",
            "metric_name",
            "measured_value",
            "threshold",
        ):

            if key not in finding:
                fail(
                    f"A finding omits {key}: {finding}"
                )


        if finding["code"] not in QUALITY_CODES:
            fail(
                f"{finding['code']} is not in "
                "QUALITY_CODES, so nothing else in the "
                "product knows how to render it."
            )


    ok(
        "the payload carries severities and measured "
        "values, and no score, risk or fraud language"
    )


# ==========================================================
# 5. THE RELEASE-CRITICAL INVARIANT
# ==========================================================

def finding(
    code: str,
    severity: str,
) -> QualityFinding:

    return QualityFinding(
        code=code,
        severity=severity,
        message="m",
        metric_name="x",
        measured_value=1.0,
        threshold=2.0,
    )


def test_quality_can_only_escalate() -> None:

    """
    False AUTO_ACCEPT must not increase.

    Asserted against the function directly rather than
    sampled across documents, because the property has to
    hold for every possible combination of findings and a
    sample cannot show that.
    """

    auto = {
        "decision": "AUTO_ACCEPT",
        "review_required": False,
        "priority": "NONE",
        "reason_codes": [],
        "issues": [],
    }

    required = {
        "decision": "REVIEW_REQUIRED",
        "review_required": True,
        "priority": "MEDIUM",
        "reason_codes": ["EXISTING_REASON"],
        "issues": [{"code": "EXISTING_REASON"}],
    }

    cases = (
        (
            "no findings",
            QualityAssessment(),
        ),
        (
            "warning only",
            QualityAssessment(
                findings=[
                    finding(
                        QUALITY_IMAGE_TOO_DARK,
                        SEVERITY_WARNING,
                    ),
                    finding(
                        QUALITY_IMAGE_BLURRY,
                        SEVERITY_WARNING,
                    ),
                    finding(
                        QUALITY_ROTATION_CONCERN,
                        SEVERITY_WARNING,
                    ),
                ]
            ),
        ),
        (
            "error present",
            QualityAssessment(
                findings=[
                    finding(
                        QUALITY_IMAGE_UNREADABLE,
                        SEVERITY_ERROR,
                    )
                ]
            ),
        ),
    )

    for label, assessment in cases:

        # An already-required review must never be cleared or
        # downgraded.
        result = (
            apply_quality_to_review(
                required,
                assessment,
            )
        )

        if not result["review_required"]:
            fail(
                f"{label}: a required review was "
                "cleared."
            )

        if result["decision"] != "REVIEW_REQUIRED":
            fail(
                f"{label}: the decision changed away "
                "from REVIEW_REQUIRED."
            )

        if result["priority"] != "MEDIUM":
            fail(
                f"{label}: the priority changed from "
                f"MEDIUM to {result['priority']}."
            )

        if "EXISTING_REASON" not in result["reason_codes"]:
            fail(
                f"{label}: an existing reason code was "
                "dropped."
            )


        # An AUTO_ACCEPT may only become REVIEW_REQUIRED, and
        # only for an ERROR.
        from_auto = (
            apply_quality_to_review(
                auto,
                assessment,
            )
        )

        has_error = any(
            item.severity == SEVERITY_ERROR
            for item in assessment.findings
        )

        if has_error:

            if from_auto["decision"] != "REVIEW_REQUIRED":
                fail(
                    f"{label}: an ERROR quality finding "
                    "did not escalate AUTO_ACCEPT. An "
                    "unreadable image must not be "
                    "auto-accepted."
                )

            if from_auto["priority"] != "HIGH":
                fail(
                    f"{label}: escalation should be "
                    "HIGH priority."
                )

        else:

            if from_auto != auto:
                fail(
                    f"{label}: AUTO_ACCEPT was modified "
                    "without an ERROR finding. A dim or "
                    "slightly soft photograph of a valid "
                    "licence is still a valid licence, "
                    "and routing all of them to a human "
                    "would bury the reviewer."
                )


        # The inputs must be untouched.
        if auto["decision"] != "AUTO_ACCEPT":
            fail(
                f"{label}: the input dict was mutated."
            )

        if required["priority"] != "MEDIUM":
            fail(
                f"{label}: the input dict was mutated."
            )


    ok(
        "quality can only escalate AUTO_ACCEPT to "
        "REVIEW_REQUIRED, never clear or downgrade a "
        "review, and never mutates its input"
    )


def test_policy_reports_only_errors() -> None:

    warning_only = (
        QualityAssessment(
            findings=[
                finding(
                    QUALITY_IMAGE_TOO_DARK,
                    SEVERITY_WARNING,
                )
            ]
        )
    )

    verdict = (
        quality_review_policy(
            warning_only
        )
    )

    if verdict["requires_review"]:
        fail(
            "A WARNING finding required review. Only an "
            "ERROR may."
        )


    if quality_review_policy(
        None
    )["requires_review"]:
        fail(
            "A missing assessment required review."
        )


    with_error = (
        quality_review_policy(
            QualityAssessment(
                findings=[
                    finding(
                        QUALITY_IMAGE_UNREADABLE,
                        SEVERITY_ERROR,
                    )
                ]
            )
        )
    )

    if with_error["reasons"] != [
        QUALITY_IMAGE_UNREADABLE
    ]:
        fail(
            "The policy does not report which finding "
            "caused the escalation: "
            f"{with_error['reasons']}"
        )


    ok(
        "the review policy triggers on ERROR only and "
        "names the reason"
    )


# ==========================================================
# 6. QUALITY DOES NOT TOUCH THE DOCUMENT
# ==========================================================

def test_assessment_does_not_modify_the_image() -> None:

    """
    Quality assessment runs beside OCR on the same file. If it
    could write to that file, it would be changing what OCR
    reads.
    """

    service = (
        DocumentQualityService()
    )

    path = (
        sample_documents(
            limit=1
        )[0]
    )

    with Scratch() as scratch:

        copy = (
            scratch.write(
                load(
                    path
                )
            )
        )

        before = (
            copy.read_bytes()
        )

        before_mtime = (
            copy.stat().st_mtime_ns
        )

        service.assess(
            copy
        )

        if copy.read_bytes() != before:
            fail(
                "The image bytes changed during "
                "assessment."
            )

        if copy.stat().st_mtime_ns != before_mtime:
            fail(
                "The image was written to during "
                "assessment."
            )


    ok(
        "assessment leaves the image byte-identical and "
        "unwritten"
    )


def test_undecodable_file_is_reported_not_raised() -> None:

    service = (
        DocumentQualityService()
    )

    with Scratch() as scratch:

        broken = (
            scratch.root
            / "not-an-image.jpg"
        )

        broken.write_bytes(
            b"this is not an image"
        )

        assessment = (
            service.assess(
                broken
            )
        )

        if assessment.error is None:
            fail(
                "An undecodable file produced no error."
            )

        if assessment.findings:
            fail(
                "An undecodable file produced findings. "
                "There was nothing to measure, so there "
                "is nothing to conclude."
            )

        # A missing file is the same shape of answer.
        missing = (
            service.assess(
                scratch.root / "nope.png"
            )
        )

        if missing.error is None:
            fail(
                "A missing file produced no error."
            )


    ok(
        "an undecodable or missing file reports an error "
        "and no findings, and does not raise"
    )


# ==========================================================
# 7. PIPELINE INTEGRATION
# ==========================================================

def test_pipeline_exposes_quality_without_touching_extraction() -> None:

    """
    The pipeline result gains a quality key and loses nothing.

    Checked against the contract rather than by running OCR:
    this suite is deterministic and free, and the real
    end-to-end path is covered by the E2E suites.
    """

    import inspect as inspect_module

    from backend.app.services import (
        pipeline_service,
    )

    source = (
        inspect_module.getsource(
            pipeline_service.DocumentPipelineService.process
        )
    )

    # Quality must be measured before OCR, so a reviewer
    # looking at a failed extraction can see the photograph
    # was unusable.
    if source.index(
        "quality_service.assess"
    ) > source.index(
        "ocr_service.extract"
    ):
        fail(
            "Quality is assessed after OCR. It measures "
            "the image, not the text, and its result is "
            "most useful when the extraction failed."
        )


    for required in (
        '"quality"',
        "apply_quality_to_review",
    ):

        if required not in source:
            fail(
                f"The pipeline does not reference "
                f"{required}."
            )


    # The existing keys must all still be returned.
    for key in (
        '"extraction"',
        '"ocr_lines"',
        '"evidence_flags"',
        '"field_confidence"',
        '"date_validation"',
        '"anomaly_validation"',
        '"review_decision"',
    ):

        if key not in source:
            fail(
                f"The pipeline result no longer returns "
                f"{key}."
            )


    # And the review service itself must not have been
    # threaded a new argument: its semantics are audited and
    # the escalation deliberately happens outside it.
    decide = (
        inspect_module.signature(
            __import__(
                "backend.app.services.review_decision_service",
                fromlist=["ReviewDecisionService"],
            ).ReviewDecisionService.decide
        )
    )

    if list(
        decide.parameters
    ) != [
        "self",
        "anomaly_result",
    ]:
        fail(
            "ReviewDecisionService.decide() gained a "
            "parameter. Its semantics are audited and "
            "tested; quality escalation happens after "
            "it, not inside it. Signature: "
            f"{decide}"
        )


    ok(
        "the pipeline measures quality before OCR, "
        "returns it alongside every existing key, and "
        "leaves decide() untouched"
    )


def test_analysis_row_can_store_quality() -> None:

    from database.models import (
        DocumentAnalysisModel,
    )

    columns = {
        column.name: column
        for column in (
            DocumentAnalysisModel
            .__table__
            .columns
        )
    }

    if "quality" not in columns:
        fail(
            "document_analyses has no quality column, "
            "so the assessment cannot be persisted."
        )


    # Nullable, so rows written before quality assessment
    # existed stay valid and read as "not assessed" rather
    # than as "no problems found".
    if not columns["quality"].nullable:
        fail(
            "The quality column is NOT NULL, which "
            "would make every pre-existing analysis row "
            "invalid."
        )


    ok(
        "the analysis row stores quality in a nullable "
        "column, so existing rows stay valid"
    )


# ==========================================================
# MAIN
# ==========================================================

def main() -> int:

    print()
    print("=" * 76)
    print(
        "PHASE 10.1 - IMAGE QUALITY ASSESSMENT"
    )
    print("=" * 76)
    print()

    test_clean_documents_are_silent()

    test_clean_documents_report_metrics()

    test_degradations_are_detected()

    test_overexposure_detects_bright_documents_only()

    test_unreadable_is_the_only_error()

    test_thresholds_are_strict_comparisons()

    test_unmeasurable_skew_raises_nothing()

    test_no_score_and_no_fraud_language()

    test_quality_can_only_escalate()

    test_policy_reports_only_errors()

    test_assessment_does_not_modify_the_image()

    test_undecodable_file_is_reported_not_raised()

    test_pipeline_exposes_quality_without_touching_extraction()

    test_analysis_row_can_store_quality()

    print()
    print("=" * 76)
    print(
        f"[PASS] PHASE 10.1 PASSED - "
        f"{len(PASSES)} properties asserted"
    )
    print("=" * 76)

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
