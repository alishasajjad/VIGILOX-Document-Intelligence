from dataclasses import (
    dataclass,
    field,
)
from pathlib import Path

import cv2
import numpy as np


# ==========================================================
# DOCUMENT IMAGE QUALITY ASSESSMENT
# PHASE 10.1
# ==========================================================
#
# WHAT THIS IS
# ----------------------------------------------------------
#
# Five deterministic measurements of an uploaded image, and a
# finding for each measurement that falls outside a threshold
# derived from data.
#
# It answers "is this image hard to read" and nothing else. It
# does not know whether the document is genuine, whether it has
# been altered, or whether anybody should be suspicious of it.
# Those would be different capabilities requiring evidence
# this project does not have, and calling a blur measurement
# TAMPER_SUSPECTED would be a lie a reviewer would reasonably
# act on.
#
#
# WHAT IT DELIBERATELY IS NOT
# ----------------------------------------------------------
#
# No model. No LLM. No learned scoring. Every number here is
# arithmetic over pixels that a person can reproduce with
# OpenCV in four lines, which is what makes a finding
# explainable to the reviewer it is shown to.
#
# No composite "quality score" either. Averaging a blur
# variance with a mean luminance produces a number with no
# unit and no meaning, and it would immediately be read as a
# percentage of something.
#
#
# QUALITY IS NOT VALIDITY
# ----------------------------------------------------------
#
# A dark photograph of a valid licence is a valid licence. A
# crisp photograph of an expired one is still expired. So
# these findings never touch the extraction, never modify a
# field, and never mark a document invalid. The only thing
# they may do -- and only under the explicit policy in
# quality_review_policy() -- is ask for a human to look.
# ==========================================================


# ==========================================================
# SEVERITY
# ==========================================================
#
# Deliberately the same vocabulary the existing validators
# use, so a quality finding sorts and renders beside a date
# finding without translation.
# ==========================================================

SEVERITY_ERROR = "ERROR"

SEVERITY_WARNING = "WARNING"

SEVERITY_INFO = "INFO"


# ==========================================================
# FINDING CODES
# ==========================================================

QUALITY_IMAGE_TOO_SMALL = "IMAGE_TOO_SMALL"

QUALITY_IMAGE_BLURRY = "IMAGE_BLURRY"

QUALITY_IMAGE_TOO_DARK = "IMAGE_TOO_DARK"

QUALITY_IMAGE_OVEREXPOSED = "IMAGE_OVEREXPOSED"

QUALITY_IMAGE_UNREADABLE = "IMAGE_UNREADABLE"

QUALITY_ROTATION_CONCERN = "ROTATION_CONCERN"


# What this service can actually emit.
#
# IMAGE_LOW_CONTRAST is deliberately absent: the metric is
# measured and returned but did not earn a threshold. The
# reason is recorded below, because "we measured it and it did
# not separate" is information worth keeping.
QUALITY_CODES = (
    QUALITY_IMAGE_TOO_SMALL,
    QUALITY_IMAGE_BLURRY,
    QUALITY_IMAGE_TOO_DARK,
    QUALITY_IMAGE_OVEREXPOSED,
    QUALITY_IMAGE_UNREADABLE,
    QUALITY_ROTATION_CONCERN,
)


# ==========================================================
# THRESHOLDS
# ==========================================================
#
# EVERY NUMBER BELOW CAME FROM MEASUREMENT, AND THE FIRST
# ATTEMPT WAS WRONG.
#
# These values were originally chosen by reasoning about what
# "blurry" and "low contrast" ought to mean. The study in
# scripts/development/quality_threshold_study.py then measured
# all 63 clean benchmark documents and reported that those
# thresholds fired on 40 of them.
#
# A guessed threshold is a threshold that rejects real
# documents. That is what it looks like in practice, and it is
# why the study exists and is cheap to run.
#
# Measured clean distributions, all 63 documents:
#
#   shorter_side_px      min  140     median  680    max  700
#   laplacian_variance   min 1454     median 1536    max 2655
#   mean_luminance       min  153.9   median  240.9  max  244.2
#   contrast_spread      min   25     median   28    max  234
#
# The corpus is synthetic and bright, which is why the
# luminance median sits at 241 and the contrast spread is
# narrow. That is a property of the data and it constrains what
# can be claimed from it.
#
# Each threshold is placed outside the clean range, so it fires
# on none of the 63 known-good documents, and inside the range
# of a generated degradation, so it detects something.
# ==========================================================

# Shorter side, in pixels.
#
# Clean minimum is 140. Two benchmark documents are that small
# and both extract correctly, so 140 px is demonstrably usable
# for this document set and the floor has to sit below it.
#
# 120 is below every known-good document. It is an honestly
# weak signal on this corpus: a downscale to 40% still has a
# 5th percentile of 240 px, so most degraded images pass it. It
# catches genuinely tiny uploads and nothing subtler, and that
# is all it claims.
MIN_SHORTER_SIDE_PX = 120

# Total pixels. A 4000x50 strip passes a shorter-side check and
# is not a document.
MIN_TOTAL_PIXELS = 15000


# Variance of the Laplacian. The standard sharpness proxy: a
# blurred image has less high-frequency energy, so its second
# derivative varies less.
#
# Measured:
#
#   clean            1454 - 2655
#   blur sigma 1      100 -  318
#   blur sigma 2       14 -   30
#   blur sigma 4        1 -    3
#
# and, importantly, the confound:
#
#   darkened 0.50x    364 -  666
#   contrast 0.50x    363 -  666
#
# Reducing brightness or contrast also reduces Laplacian
# variance. A floor above ~660 would report a merely dim
# photograph as blurred, which is a wrong and confusing
# finding to put in front of a reviewer.
#
# 350 sits below the 0.50x darkened and 0.50x contrast ranges
# and above the whole blur-sigma-1 range, so it separates real
# blur from mild dimness. Zero of 63 clean documents fire, and
# every blur-sigma-1 image does.
#
# The confound is reduced, not eliminated, and the study shows
# exactly where it survives: darkening to 0.35x or 0.20x, and
# contrast reduction to 0.25x, drop the variance below 350 and
# do raise IMAGE_BLURRY.
#
# For the darkened cases that is tolerable -- they raise
# IMAGE_TOO_DARK as well, so the reviewer sees the real reason
# beside it. For the 0.25x contrast case IMAGE_BLURRY is the
# only finding and it names the wrong cause, which is the
# honest cost of not shipping a contrast finding. The document
# is still correctly reported as hard to read, which is what
# the finding is for.
BLUR_VARIANCE_FLOOR = 350.0

# Blurred past the point where OCR recovers anything.
#
# Measured: blur sigma 2 tops out at 30, sigma 4 at 3, and the
# most extreme darkening tested (0.20x) bottoms out at 58. 40
# catches every sigma-2 and sigma-4 image and never fires on a
# merely dark one.
BLUR_VARIANCE_UNREADABLE = 40.0


# Mean luminance, 0-255.
#
# Measured:
#
#   clean            153.9 - 244.2
#   darkened 0.50x    76.9 - 122.4
#   darkened 0.35x    53.9 -  85.3
#   darkened 0.20x    30.8 -  48.9
#
# 135 is below every clean document and above every darkened
# one. This is the cleanest separation of the five metrics.
DARKNESS_FLOOR = 135.0

# Measured: no clean document exceeds 244.2. Brightening by
# 1.3x puts the 5th percentile at 246.0 and the median at
# 248.8.
#
# 246 is above the clean maximum and below most of the
# brightened range. The margin is thinner than the darkness
# floor's, because this corpus is already bright -- worth
# knowing if a darker corpus is ever added.
OVEREXPOSURE_CEILING = 246.0


# Absolute skew from horizontal, in degrees.
#
# THIS THRESHOLD EXISTS BECAUSE THE STUDY CORRECTED A SECOND
# WRONG CONCLUSION.
#
# The first reading of the study showed every clean document at
# exactly 0.00 degrees, and that was interpreted as the Hough
# estimator finding nothing and falling back to zero -- so the
# signal was written off as unmeasurable and shipped as no
# finding at all.
#
# The estimator was then changed to return None for "nothing
# found", which made the distinction visible, and the study
# reported:
#
#   clean            0.00 on all 63, ZERO unmeasurable
#   rotated 3 deg   -8.4 to -2.3   (median  -3.0)
#   rotated 10 deg -11.0 to -9.4   (median -10.0)
#
# The estimator measures every clean document successfully and
# returns exactly zero for all of them. It was the best
# separating signal of the five the whole time, and the
# write-off was wrong.
#
# 5.0 degrees, not 1.5:
#
# The corpus is synthetic, and its documents have perfectly
# axis-aligned rules and borders, which is why they read
# exactly 0.00. A hand-held photograph will not: a degree or
# two of skew is normal and PaddleOCR handles it, since
# use_textline_orientation is enabled. A threshold tight enough
# to catch the generated 3-degree cases would fire constantly
# on real photographs, and its false-positive rate there is not
# something this corpus can bound.
#
# 5 degrees catches the clearly-rotated cases -- the whole
# 10-degree set and the tail of the 3-degree set -- while
# leaving minor skew alone. It is a WARNING, so under the
# review policy below it changes no decision.
ROTATION_CONCERN_DEGREES = 5.0


# ==========================================================
# ONE SIGNAL MEASURED AND DELIBERATELY NOT SHIPPED
# ==========================================================
#
# CONTRAST_SPREAD
# ----------------------------------------------------------
# Measured:
#
#   clean             25 - 234   (median 28)
#   darkened 0.50x    13 - 117
#   contrast 0.50x    12 - 117
#   contrast 0.25x     6 -  59
#
# The clean minimum of 25 sits inside the degraded ranges. The
# only kind of threshold that avoids firing on good documents
# -- below 25 -- catches just the most extreme reductions, and
# those are already caught by the darkness floor. So it would
# add a second finding to a document that is already flagged,
# in exchange for a 20% margin against false positives.
#
# Worse, a blurred image scores HIGHER here than a clean one
# (blur sigma 2: 67-183 against clean's 25-234), because
# blurring lifts the 5th percentile off the page background. A
# metric that moves the wrong way under a degradation is not
# measuring what its name suggests on this corpus.
#
# Measured, returned in metrics, raises nothing. Kept only so
# the study can keep reporting against it.
CONTRAST_FLOOR_STUDY_ONLY = 20.0


# ==========================================================
# FINDING
# ==========================================================

@dataclass(frozen=True)
class QualityFinding:

    code: str

    severity: str

    message: str

    metric_name: str

    measured_value: float

    threshold: float

    def to_dict(
        self,
    ) -> dict:

        return {
            "code":
                self.code,

            "severity":
                self.severity,

            "message":
                self.message,

            "metric_name":
                self.metric_name,

            # Rounded: the exact float is noise and would
            # otherwise end up rendered in an interface.
            "measured_value":
                round(
                    float(
                        self.measured_value
                    ),
                    2,
                ),

            "threshold":
                round(
                    float(
                        self.threshold
                    ),
                    2,
                ),
        }


@dataclass
class QualityAssessment:

    metrics: dict = field(
        default_factory=dict,
    )

    findings: list = field(
        default_factory=list,
    )

    error: str | None = None

    def to_dict(
        self,
    ) -> dict:

        return {
            "metrics":
                self.metrics,

            "findings": [
                finding.to_dict()
                for finding in self.findings
            ],

            # The single derived value, and it is a severity
            # rather than a score: the highest severity among
            # the findings, or None. Deterministic, explainable
            # in one sentence, and impossible to mistake for a
            # percentage.
            "highest_severity":
                self.highest_severity(),

            "error":
                self.error,
        }

    def highest_severity(
        self,
    ) -> str | None:

        order = {
            SEVERITY_INFO: 1,
            SEVERITY_WARNING: 2,
            SEVERITY_ERROR: 3,
        }

        best = None

        for finding in self.findings:

            if best is None or order.get(
                finding.severity,
                0,
            ) > order.get(
                best,
                0,
            ):
                best = finding.severity

        return best

    def codes(
        self,
    ) -> list:

        return [
            finding.code
            for finding in self.findings
        ]


# ==========================================================
# THE SERVICE
# ==========================================================

class DocumentQualityService:

    """
    Measures an image and reports what is outside range.

    Stateless and side-effect free: it opens a file, computes
    five numbers, and returns them. It never writes, never
    modifies the image, and never touches the extraction --
    which is what makes it safe to run beside OCR.
    """

    def assess(
        self,
        image_path: str | Path,
    ) -> QualityAssessment:

        path = Path(
            image_path
        )

        assessment = (
            QualityAssessment()
        )

        image = self._load(
            path
        )


        if image is None:

            # A file that cannot be decoded is not a quality
            # problem to report against a threshold -- there is
            # nothing to measure. The pipeline's own error
            # handling owns this, so the assessment carries a
            # reason and no findings.
            assessment.error = (
                "The image could not be decoded."
            )

            return assessment


        gray = (
            image
            if image.ndim == 2
            else cv2.cvtColor(
                image,
                cv2.COLOR_BGR2GRAY,
            )
        )

        height, width = gray.shape[:2]

        assessment.metrics = (
            self._measure(
                gray,
                width,
                height,
            )
        )

        assessment.findings = (
            self._evaluate(
                assessment.metrics
            )
        )

        return assessment


    # ======================================================
    # LOADING
    # ======================================================

    def _load(
        self,
        path: Path,
    ):

        try:
            # imdecode over imread: imread silently fails on a
            # path containing non-ASCII characters on Windows,
            # and an upload filename is not something to trust
            # with that.
            data = np.fromfile(
                str(
                    path
                ),
                dtype=np.uint8,
            )

            if data.size == 0:
                return None

            return cv2.imdecode(
                data,
                cv2.IMREAD_COLOR,
            )

        except Exception:      # noqa: BLE001
            return None


    # ======================================================
    # MEASUREMENT
    # ======================================================

    def _measure(
        self,
        gray: np.ndarray,
        width: int,
        height: int,
    ) -> dict:

        # Variance of the Laplacian: less high-frequency
        # content means a softer image.
        laplacian_variance = float(
            cv2.Laplacian(
                gray,
                cv2.CV_64F,
            ).var()
        )

        mean_luminance = float(
            gray.mean()
        )

        # The 5th-to-95th percentile spread rather than the
        # standard deviation. One specular highlight moves a
        # standard deviation a long way while saying nothing
        # about whether the text separates from the page; the
        # percentile spread ignores it.
        low, high = np.percentile(
            gray,
            [5, 95],
        )

        contrast_spread = float(
            high - low
        )

        # None when no near-horizontal line was found, which is
        # not the same as zero degrees.
        skew_degrees = (
            self._estimate_skew(
                gray
            )
        )

        return {
            "width_px":
                int(
                    width
                ),

            "height_px":
                int(
                    height
                ),

            "shorter_side_px":
                int(
                    min(
                        width,
                        height,
                    )
                ),

            "total_pixels":
                int(
                    width * height
                ),

            "laplacian_variance":
                round(
                    laplacian_variance,
                    2,
                ),

            "mean_luminance":
                round(
                    mean_luminance,
                    2,
                ),

            "contrast_spread":
                round(
                    contrast_spread,
                    2,
                ),

            # None means "no angle could be measured".
            # Reporting 0.0 there would claim the document is
            # perfectly square when nothing was measured.
            "estimated_skew_degrees":
                (
                    round(
                        skew_degrees,
                        2,
                    )
                    if skew_degrees is not None
                    else None
                ),
        }


    def _estimate_skew(
        self,
        gray: np.ndarray,
    ) -> float | None:

        """
        Dominant deviation from horizontal in degrees, or None
        when no usable line was found.

        The None is the point. Returning 0.0 for "nothing to
        measure" made all 63 clean documents read as exactly
        0.00 skew in the threshold study and looked like a
        perfect signal; it was the fallback value, not a
        measurement.

        Reported for operators and for the study. Raises no
        finding -- see the threshold block.
        """

        try:

            edges = cv2.Canny(
                gray,
                50,
                150,
                apertureSize=3,
            )

            lines = cv2.HoughLinesP(
                edges,
                rho=1,
                theta=np.pi / 180,
                threshold=80,
                minLineLength=30,
                maxLineGap=10,
            )

            if lines is None:
                return None


            angles = []

            for line in lines:

                coordinates = np.asarray(
                    line
                ).ravel()

                if coordinates.size < 4:
                    continue

                x1, y1, x2, y2 = coordinates[:4]

                if x2 == x1:
                    continue

                angle = np.degrees(
                    np.arctan2(
                        float(
                            y2 - y1
                        ),
                        float(
                            x2 - x1
                        ),
                    )
                )

                # Near-horizontal only: text baselines and
                # document edges. A vertical border would
                # otherwise read as 90 degrees of rotation.
                if abs(
                    angle
                ) <= 45:
                    angles.append(
                        angle
                    )


            if not angles:
                return None


            return float(
                np.median(
                    angles
                )
            )

        except Exception:      # noqa: BLE001
            return None


    # ======================================================
    # EVALUATION
    # ======================================================

    def _evaluate(
        self,
        metrics: dict,
    ) -> list:

        findings: list = []


        # ---- RESOLUTION ----

        if metrics["shorter_side_px"] < MIN_SHORTER_SIDE_PX:

            findings.append(
                QualityFinding(
                    code=(
                        QUALITY_IMAGE_TOO_SMALL
                    ),
                    severity=(
                        SEVERITY_WARNING
                    ),
                    message=(
                        "This image is smaller than the "
                        "size at which document text can be "
                        "read reliably. A larger scan or "
                        "photograph will give a better "
                        "result."
                    ),
                    metric_name=(
                        "shorter_side_px"
                    ),
                    measured_value=(
                        metrics["shorter_side_px"]
                    ),
                    threshold=(
                        MIN_SHORTER_SIDE_PX
                    ),
                )
            )


        elif metrics["total_pixels"] < MIN_TOTAL_PIXELS:

            # elif: a 4000x50 strip passes the shorter-side
            # check and is not a document. Reported once rather
            # than twice for the same problem.
            findings.append(
                QualityFinding(
                    code=(
                        QUALITY_IMAGE_TOO_SMALL
                    ),
                    severity=(
                        SEVERITY_WARNING
                    ),
                    message=(
                        "This image contains too few pixels "
                        "to read a document from."
                    ),
                    metric_name=(
                        "total_pixels"
                    ),
                    measured_value=(
                        metrics["total_pixels"]
                    ),
                    threshold=(
                        MIN_TOTAL_PIXELS
                    ),
                )
            )


        # ---- SHARPNESS ----

        variance = metrics[
            "laplacian_variance"
        ]

        if variance < BLUR_VARIANCE_UNREADABLE:

            findings.append(
                QualityFinding(
                    code=(
                        QUALITY_IMAGE_UNREADABLE
                    ),
                    severity=(
                        SEVERITY_ERROR
                    ),
                    message=(
                        "This image is too blurred to read. "
                        "Please upload a sharper photograph "
                        "or scan."
                    ),
                    metric_name=(
                        "laplacian_variance"
                    ),
                    measured_value=variance,
                    threshold=(
                        BLUR_VARIANCE_UNREADABLE
                    ),
                )
            )


        elif variance < BLUR_VARIANCE_FLOOR:

            findings.append(
                QualityFinding(
                    code=(
                        QUALITY_IMAGE_BLURRY
                    ),
                    severity=(
                        SEVERITY_WARNING
                    ),
                    message=(
                        "This image is less sharp than "
                        "usual, which can affect how "
                        "accurately text is read."
                    ),
                    metric_name=(
                        "laplacian_variance"
                    ),
                    measured_value=variance,
                    threshold=(
                        BLUR_VARIANCE_FLOOR
                    ),
                )
            )


        # ---- EXPOSURE ----

        luminance = metrics[
            "mean_luminance"
        ]

        if luminance < DARKNESS_FLOOR:

            findings.append(
                QualityFinding(
                    code=(
                        QUALITY_IMAGE_TOO_DARK
                    ),
                    severity=(
                        SEVERITY_WARNING
                    ),
                    message=(
                        "This image is very dark, which can "
                        "affect how accurately text is read."
                    ),
                    metric_name=(
                        "mean_luminance"
                    ),
                    measured_value=luminance,
                    threshold=(
                        DARKNESS_FLOOR
                    ),
                )
            )


        elif luminance > OVEREXPOSURE_CEILING:

            findings.append(
                QualityFinding(
                    code=(
                        QUALITY_IMAGE_OVEREXPOSED
                    ),
                    severity=(
                        SEVERITY_WARNING
                    ),
                    message=(
                        "This image is very bright and "
                        "detail may have been lost."
                    ),
                    metric_name=(
                        "mean_luminance"
                    ),
                    measured_value=luminance,
                    threshold=(
                        OVEREXPOSURE_CEILING
                    ),
                )
            )


        # ---- ROTATION ----
        #
        # None means no angle could be measured, which is not
        # the same as zero. Nothing is raised in that case:
        # heavy blur destroys the edges Hough needs, and the
        # blur finding already covers that document.

        skew = metrics[
            "estimated_skew_degrees"
        ]

        if (
            skew is not None
            and abs(
                skew
            ) > ROTATION_CONCERN_DEGREES
        ):

            findings.append(
                QualityFinding(
                    code=(
                        QUALITY_ROTATION_CONCERN
                    ),
                    severity=(
                        SEVERITY_WARNING
                    ),
                    message=(
                        "This document appears rotated. "
                        "Text was still read, but a "
                        "straighter photograph or scan "
                        "gives a more reliable result."
                    ),
                    metric_name=(
                        "estimated_skew_degrees"
                    ),
                    measured_value=abs(
                        skew
                    ),
                    threshold=(
                        ROTATION_CONCERN_DEGREES
                    ),
                )
            )


        # ---- NOT EVALUATED ----
        #
        # contrast_spread is measured and returned, and raises
        # nothing: the clean corpus's own spread sits inside
        # the degraded range, so no threshold separates them.
        # See the threshold block.

        return findings


# ==========================================================
# REVIEW POLICY
# ==========================================================
#
# The ONLY route from a quality finding to the review
# decision, deliberately one function so the policy can be
# read in one place and tested directly.
#
# THE POLICY
# ----------------------------------------------------------
#
# An ERROR quality finding requires human review. There is
# exactly one: IMAGE_UNREADABLE, meaning the image is blurred
# past the point where OCR recovers anything. Auto-accepting an
# extraction from an image nobody can read is the one quality
# outcome that would be indefensible.
#
# A WARNING quality finding does NOT change the decision. A
# dark or slightly soft photograph of a licence is still a
# licence, and the existing validators already judge whether
# the extraction from it holds together -- evidence support,
# field confidence, date consistency. Routing every dim
# photograph to a human would bury the reviewer in documents
# that were extracted correctly, and a reviewer who stops
# reading carefully is worse than no reviewer.
#
# So this can only ever ADD a review requirement. It cannot
# clear one, cannot downgrade one, and cannot turn a
# REVIEW_REQUIRED into an AUTO_ACCEPT.
#
# False auto-accepts therefore cannot increase because of
# quality assessment. That is the release-critical invariant,
# and it holds structurally -- by what this function is able to
# return -- rather than by testing every combination of
# findings.
# ==========================================================

def apply_quality_to_review(
    review_result: dict,
    assessment: QualityAssessment,
) -> dict:

    """
    Escalate a review decision when image quality requires it.

    Returns a new dict; the input is not modified.

    THIS FUNCTION CAN ONLY ESCALATE.
    ----------------------------------------------------------
    It has exactly one effect: turning AUTO_ACCEPT into
    REVIEW_REQUIRED when an ERROR quality finding is present.
    It never clears a review requirement, never lowers a
    priority, and never removes a reason code.

    That is why quality assessment cannot increase false
    auto-accepts. The property holds by construction rather
    than by testing combinations of findings, which matters
    because the combinations are unbounded and the invariant is
    release-critical.

    ReviewDecisionService.decide() is deliberately not touched.
    The existing machine review semantics are audited and
    tested, and threading a new input through them would put
    every one of those guarantees back in play. This runs
    after it instead, and does one thing.
    """

    verdict = (
        quality_review_policy(
            assessment
        )
    )


    if not verdict["requires_review"]:
        return dict(
            review_result
        )


    # Already going to a human: leave the decision, priority
    # and reasons exactly as the review service set them, and
    # add the quality reason so the reviewer knows why the
    # image is also a problem.
    escalated = dict(
        review_result
    )

    reasons = list(
        escalated.get(
            "reason_codes",
            [],
        )
    )

    for reason in verdict["reasons"]:
        if reason not in reasons:
            reasons.append(
                reason
            )

    escalated["reason_codes"] = reasons

    if not escalated.get(
        "review_required"
    ):

        escalated["decision"] = (
            "REVIEW_REQUIRED"
        )

        escalated["review_required"] = True

        # HIGH, because the one ERROR finding means OCR read an
        # image nobody can read. Whatever it extracted is not
        # to be trusted without a person looking.
        escalated["priority"] = "HIGH"

    return escalated


def quality_review_policy(
    assessment: QualityAssessment,
) -> dict:

    """
    Whether image quality alone requires human review.

    Returns the decision and the reasons, so a caller never
    has to re-derive it and an audit trail can record why.
    """

    if assessment is None:

        return {
            "requires_review": False,
            "reasons": [],
        }


    reasons = [
        finding.code
        for finding in assessment.findings
        if finding.severity == SEVERITY_ERROR
    ]

    return {
        "requires_review": bool(
            reasons
        ),
        "reasons": reasons,
    }
