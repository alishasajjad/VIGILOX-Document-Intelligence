"""
==========================================================
PHASE 10.2 - UNSUPPORTED / UNKNOWN DOCUMENT HANDLING
==========================================================

WHAT THIS SUITE IS PROTECTING
----------------------------------------------------------

Four statements, in descending order of how much damage
breaking them would do:

  1. An unsupported document can NEVER be auto-accepted, and
     never publishes an effective record.

  2. A SUPPORTED document is not affected by any of this.
     Phase 10.2 must be invisible to a Guard Licence, an ID
     Card or an SIA Badge -- including a badly photographed
     one.

  3. Image quality alone never means unsupported. A blurry
     Guard Licence is still a Guard Licence.

  4. A degraded document whose type could not be read still
     reaches a human. Being confidently unsupported requires
     the image to have been readable.

Statements 3 and 4 are two halves of the same rule and are
tested together, because getting one right by breaking the
other is the obvious way to fail.


NO EXTERNAL DEPENDENCIES
----------------------------------------------------------

OCR and extraction are replaced at the module level before
the pipeline is constructed, so the REAL quality, evidence,
confidence, date, anomaly, review and classification services
all run while PaddleOCR and Groq are never touched.

Image quality is measured against REAL evaluation images and
real deterministic degradations of them, because a fake
quality assessment would prove nothing about the interaction
between quality and classification, which is the whole point
of the phase.

PostgreSQL IS used. The review queue exclusion, the dashboard
counts and the documents filters are SQL behaviour, and
asserting them against anything other than the database would
assert nothing.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import uuid

from datetime import date
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


import cv2                                        # noqa: E402
import numpy as np                                # noqa: E402

from backend.app.domain.classification import (   # noqa: E402
    DECISION_AUTO_ACCEPT,
    DECISION_REVIEW_REQUIRED,
    DECISION_UNSUPPORTED_DOCUMENT,
    MACHINE_DECISIONS,
    OUTCOME_SUPPORTED,
    OUTCOME_UNCLASSIFIED_NEEDS_REVIEW,
    OUTCOME_UNSUPPORTED,
    OUTCOMES,
    READABILITY_IMPAIRING_QUALITY_CODES,
    SUPPORTED_DOCUMENT_TYPES,
    apply_classification_to_review,
    classify_outcome,
    describe_classification,
)

from backend.app.domain.schemas import (          # noqa: E402
    DocumentExtraction,
)

from backend.app.services.document_quality_service import (  # noqa: E402
    QUALITY_CODES,
    QUALITY_ROTATION_CONCERN,
)

from backend.app.services.final_record_service import (      # noqa: E402
    FinalRecordService,
)

from backend.app.services.review_decision_service import (   # noqa: E402
    ReviewDecisionService,
)


# ==========================================================
# ASSERTIONS
# ==========================================================

FAILURES: list[str] = []


def assert_equal(
    actual,
    expected,
    message: str,
) -> None:

    if actual != expected:

        raise AssertionError(
            f"{message}\n"
            f"Expected: {expected!r}\n"
            f"Actual:   {actual!r}"
        )


def assert_true(
    value,
    message: str,
) -> None:

    if not value:
        raise AssertionError(
            message
        )


def section(
    title: str,
) -> None:

    print()
    print(
        "-" * 74
    )
    print(
        title
    )
    print(
        "-" * 74
    )


def ok(
    message: str,
) -> None:

    print(
        f"[PASS] {message}"
    )


# ==========================================================
# FAKE OCR AND EXTRACTION
# ==========================================================
#
# The only two services replaced. Everything downstream of
# them is real.
# ==========================================================

GUARD_LINES = [
    "TEXAS DEPARTMENT OF PUBLIC SAFETY",
    "SECURITY GUARD LICENSE",
    "NAME SAMPLE, JANE",
    "LICENSE NO 12345678",
    "EXPIRES 2027-01-01",
    "ISSUED BY TX DPS",
]


def ocr_lines(
    texts=None,
) -> list[dict]:

    """
    OCR output in the real shape: explicit line_id, text,
    confidence, bbox. EvidenceValidator resolves evidence
    through line_id, so the ids have to be real.
    """

    texts = (
        GUARD_LINES
        if texts is None
        else texts
    )

    return [
        {
            "line_id": f"L{index}",
            "text": text,
            "confidence": 0.99,
            "bbox": [
                [0, index * 20],
                [200, index * 20],
                [200, index * 20 + 18],
                [0, index * 20 + 18],
            ],
        }
        for index, text in enumerate(
            texts
        )
    ]


def guard_extraction() -> dict:

    """A complete, internally consistent Guard Licence."""

    return {
        "document_type": "guard_license",

        "full_name": {
            "value": "SAMPLE, JANE",
            "source_line_ids": ["L2"],
        },

        "licence_number": {
            "value": "12345678",
            "source_line_ids": ["L3"],
        },

        "id_number": {
            "value": None,
            "source_line_ids": [],
        },

        "expiry_date": {
            "value": "2027-01-01",
            "source_line_ids": ["L4"],
        },

        "date_of_birth": {
            "value": None,
            "source_line_ids": [],
        },

        "issue_date": {
            "value": None,
            "source_line_ids": [],
        },

        "issuer": {
            "value": "TX DPS",
            "source_line_ids": ["L5"],
        },
    }


def unknown_extraction() -> dict:

    """
    What the extractor returns for a receipt, a random
    photograph or a blank page: the type it could not name,
    and no fields.

    Every field null with no source lines, which is what the
    schema requires for a null value.
    """

    return {
        "document_type": "unknown",

        "full_name": {
            "value": None,
            "source_line_ids": [],
        },

        "licence_number": {
            "value": None,
            "source_line_ids": [],
        },

        "id_number": {
            "value": None,
            "source_line_ids": [],
        },

        "expiry_date": {
            "value": None,
            "source_line_ids": [],
        },

        "date_of_birth": {
            "value": None,
            "source_line_ids": [],
        },

        "issue_date": {
            "value": None,
            "source_line_ids": [],
        },

        "issuer": {
            "value": None,
            "source_line_ids": [],
        },
    }


class FakeOCR:

    def __init__(
        self,
        lines=None,
    ) -> None:

        self.lines = (
            ocr_lines()
            if lines is None
            else lines
        )

        self.calls = 0


    def extract(
        self,
        image_path: str,
    ) -> list[dict]:

        self.calls += 1

        return [
            dict(
                line
            )
            for line in self.lines
        ]


class FakeExtraction:

    def __init__(
        self,
        payload=None,
    ) -> None:

        self.payload = (
            guard_extraction()
            if payload is None
            else payload
        )

        self.calls = 0


    def extract(
        self,
        lines,
    ) -> DocumentExtraction:

        self.calls += 1

        # Through the real Pydantic model, so a payload that
        # could not actually come back from the provider
        # cannot be used as a fixture.
        return DocumentExtraction(
            **self.payload
        )


def build_pipeline(
    *,
    lines=None,
    extraction=None,
):

    """
    A real DocumentPipelineService with only OCR and
    extraction replaced.

    The module attributes are swapped BEFORE __init__ runs,
    which means the real constructor executes and builds every
    other service itself. If a future phase adds a service to
    the pipeline, this helper picks it up automatically rather
    than testing a pipeline that no longer resembles the
    product.
    """

    import backend.app.services.pipeline_service as module

    real_ocr = module.OCRService
    real_extraction = module.ExtractionService

    fake_ocr = FakeOCR(
        lines
    )

    fake_extraction = FakeExtraction(
        extraction
    )

    module.OCRService = lambda: fake_ocr
    module.ExtractionService = lambda: fake_extraction

    try:
        pipeline = (
            module
            .DocumentPipelineService()
        )

    finally:
        module.OCRService = real_ocr
        module.ExtractionService = real_extraction


    return pipeline, fake_ocr, fake_extraction


# ==========================================================
# REAL IMAGES
# ==========================================================

EVALUATION_IMAGES = (
    PROJECT_ROOT
    / "evaluation"
    / "images"
)


def clean_image() -> Path:

    path = (
        EVALUATION_IMAGES
        / "guard_license"
        / "guard_001.jpg"
    )

    if not path.exists():

        raise AssertionError(
            (
                "Phase 10.2 measures the interaction "
                "between image quality and "
                "classification, which needs a real "
                "image. Expected the evaluation "
                f"fixture at {path}."
            )
        )

    return path


def degraded_copy(
    temp_dir: Path,
    *,
    name: str,
    blur_sigma: float = 0.0,
    brightness: float = 1.0,
) -> Path:

    """
    A deterministic degradation of a real evaluation image.

    The same transforms the Phase 10.1 threshold study used to
    measure the thresholds, so a document degraded here lands
    in the range those thresholds were derived from.
    """

    source = cv2.imread(
        str(
            clean_image()
        )
    )

    if source is None:

        raise AssertionError(
            "Could not decode the evaluation image."
        )


    image = source


    if blur_sigma > 0:

        image = cv2.GaussianBlur(
            image,
            (0, 0),
            blur_sigma,
        )


    if brightness != 1.0:

        image = np.clip(
            image.astype(
                np.float32
            )
            * brightness,
            0,
            255,
        ).astype(
            np.uint8
        )


    target = temp_dir / name

    cv2.imwrite(
        str(
            target
        ),
        image,
    )

    return target


def blank_image(
    temp_dir: Path,
    *,
    name: str = "blank.jpg",
    value: int = 255,
) -> Path:

    """A featureless page. No text, nothing to classify."""

    image = np.full(
        (700, 1000, 3),
        value,
        dtype=np.uint8,
    )

    target = temp_dir / name

    cv2.imwrite(
        str(
            target
        ),
        image,
    )

    return target


# ==========================================================
# 1. CLASSIFICATION POLICY
# ==========================================================

def test_supported_types_are_never_reclassified() -> None:

    section(
        "TEST 1 - A SUPPORTED TYPE IS NEVER UNSUPPORTED"
    )

    # Every readability finding, every combination of them,
    # and no OCR text at all. A supported document_type must
    # survive all of it.
    hostile_inputs = [
        (),
        ("IMAGE_BLURRY",),
        ("IMAGE_UNREADABLE",),
        ("IMAGE_TOO_DARK", "IMAGE_BLURRY"),
        tuple(
            READABILITY_IMPAIRING_QUALITY_CODES
        ),
        tuple(
            QUALITY_CODES
        ),
    ]

    for document_type in SUPPORTED_DOCUMENT_TYPES:

        for codes in hostile_inputs:

            for line_count in (0, 1, 40):

                outcome = classify_outcome(
                    document_type=(
                        document_type
                    ),
                    quality_finding_codes=(
                        codes
                    ),
                    ocr_line_count=(
                        line_count
                    ),
                )

                assert_equal(
                    outcome,
                    OUTCOME_SUPPORTED,
                    (
                        "A supported document type must "
                        "stay SUPPORTED regardless of image "
                        "quality or OCR volume. "
                        f"type={document_type} "
                        f"codes={codes} "
                        f"lines={line_count}"
                    ),
                )

    ok(
        "All 3 supported types stay SUPPORTED across "
        f"{len(hostile_inputs) * 3} quality and OCR "
        "combinations each: image quality alone never "
        "means unsupported"
    )


def test_unknown_classification_rule() -> None:

    section(
        "TEST 2 - THE UNKNOWN BRANCH"
    )

    # ------------------------------------------------------
    # A readable file that is not a supported document.
    # Receipt, random photograph, unrelated credential.
    # ------------------------------------------------------

    assert_equal(
        classify_outcome(
            document_type="unknown",
            quality_finding_codes=(),
            ocr_line_count=14,
        ),
        OUTCOME_UNSUPPORTED,
        (
            "A readable file that is not a supported "
            "document is UNSUPPORTED."
        ),
    )

    ok(
        "Readable and unclassified -> UNSUPPORTED "
        "(receipt, random photo, unrelated credential)"
    )


    # ------------------------------------------------------
    # A degraded file that produced text. Could be a
    # supported document nobody could read.
    # ------------------------------------------------------

    for code in sorted(
        READABILITY_IMPAIRING_QUALITY_CODES
    ):

        assert_equal(
            classify_outcome(
                document_type="unknown",
                quality_finding_codes=(
                    code,
                ),
                ocr_line_count=6,
            ),
            OUTCOME_UNCLASSIFIED_NEEDS_REVIEW,
            (
                "A readability-impairing finding with OCR "
                "text present must not conclude "
                f"unsupported. code={code}"
            ),
        )

    ok(
        f"All {len(READABILITY_IMPAIRING_QUALITY_CODES)} "
        "readability findings with text present -> "
        "UNCLASSIFIED_NEEDS_REVIEW (a degraded supported "
        "document still reaches a human)"
    )


    # ------------------------------------------------------
    # Degraded AND no text. A blank page, or a photograph of
    # nothing. Nothing for a reviewer to read.
    # ------------------------------------------------------

    assert_equal(
        classify_outcome(
            document_type="unknown",
            quality_finding_codes=(
                "IMAGE_UNREADABLE",
            ),
            ocr_line_count=0,
        ),
        OUTCOME_UNSUPPORTED,
        (
            "No OCR text means there is nothing for a "
            "reviewer to read, so it is UNSUPPORTED "
            "rather than queued."
        ),
    )

    ok(
        "Degraded with no OCR text -> UNSUPPORTED "
        "(blank and near-blank images do not become "
        "reviewer workload)"
    )


    # ------------------------------------------------------
    # Rotation is measured but does not impair readability.
    # ------------------------------------------------------

    assert_true(
        QUALITY_ROTATION_CONCERN
        not in READABILITY_IMPAIRING_QUALITY_CODES,
        (
            "ROTATION_CONCERN must not be treated as "
            "readability-impairing: Phase 10.1 measured "
            "that documents rotated 10 degrees still OCR."
        ),
    )

    assert_equal(
        classify_outcome(
            document_type="unknown",
            quality_finding_codes=(
                QUALITY_ROTATION_CONCERN,
            ),
            ocr_line_count=9,
        ),
        OUTCOME_UNSUPPORTED,
        (
            "A rotated but otherwise readable "
            "unclassified file is UNSUPPORTED."
        ),
    )

    ok(
        "ROTATION_CONCERN alone does not block an "
        "unsupported conclusion, because rotated documents "
        "were measured to still read"
    )


def test_quality_code_lists_agree() -> None:

    section(
        "TEST 3 - THE TWO CODE LISTS AGREE"
    )

    # The domain module lists the codes as strings so that it
    # does not import a service. That is only safe if the two
    # lists cannot drift, which is what this asserts.

    shipped = set(
        QUALITY_CODES
    )

    unknown_to_service = (
        READABILITY_IMPAIRING_QUALITY_CODES
        - shipped
    )

    assert_equal(
        sorted(
            unknown_to_service
        ),
        [],
        (
            "Every readability-impairing code must be a "
            "code the quality service can actually emit. "
            "A code listed here that the service never "
            "produces is dead policy."
        ),
    )

    excluded = (
        shipped
        - READABILITY_IMPAIRING_QUALITY_CODES
    )

    assert_equal(
        sorted(
            excluded
        ),
        [
            QUALITY_ROTATION_CONCERN
        ],
        (
            "ROTATION_CONCERN is the only shipped quality "
            "code deliberately excluded from the "
            "readability set. A new exclusion needs a "
            "measured reason recorded beside it."
        ),
    )

    ok(
        f"All {len(shipped)} shipped quality codes "
        "accounted for; ROTATION_CONCERN is the only "
        "intentional exclusion"
    )


# ==========================================================
# 2. EFFECT ON THE MACHINE REVIEW DECISION
# ==========================================================

def test_decision_effect_is_exhaustive() -> None:

    section(
        "TEST 4 - THE ONLY TRANSITION, EXHAUSTIVELY"
    )

    base_issues = [
        {
            "code": "UNKNOWN_DOCUMENT_TYPE",
            "severity": "ERROR",
            "field": None,
            "message": "Document type could not be "
                       "reliably classified.",
        }
    ]

    transitions = {}

    for outcome in OUTCOMES:

        for decision in MACHINE_DECISIONS:

            original = {
                "decision": decision,
                "review_required": (
                    decision
                    == DECISION_REVIEW_REQUIRED
                ),
                "priority": (
                    "HIGH"
                    if decision
                    == DECISION_REVIEW_REQUIRED
                    else "NONE"
                ),
                "reason_codes": [
                    "UNKNOWN_DOCUMENT_TYPE"
                ],
                "issues": base_issues,
            }

            snapshot = json.dumps(
                original,
                sort_keys=True,
            )

            result = (
                apply_classification_to_review(
                    original,
                    outcome,
                )
            )

            # ------------------------------------------
            # NEVER MUTATES ITS INPUT
            # ------------------------------------------

            assert_equal(
                json.dumps(
                    original,
                    sort_keys=True,
                ),
                snapshot,
                (
                    "apply_classification_to_review must "
                    "not modify the decision it was given."
                ),
            )

            # ------------------------------------------
            # NEVER PRODUCES AUTO_ACCEPT
            # ------------------------------------------

            if decision != DECISION_AUTO_ACCEPT:

                assert_true(
                    result["decision"]
                    != DECISION_AUTO_ACCEPT,
                    (
                        "Classification must never turn a "
                        "non-accepted decision into "
                        f"AUTO_ACCEPT. outcome={outcome} "
                        f"decision={decision}"
                    ),
                )

            # ------------------------------------------
            # REASON CODES SURVIVE
            # ------------------------------------------

            assert_equal(
                result["reason_codes"],
                [
                    "UNKNOWN_DOCUMENT_TYPE"
                ],
                (
                    "The reason the document was not "
                    "classified must survive, because it "
                    "is the explanation."
                ),
            )

            transitions[
                (outcome, decision)
            ] = result["decision"]


    # The one and only change.
    expected_changes = {
        (
            OUTCOME_UNSUPPORTED,
            DECISION_REVIEW_REQUIRED,
        ): DECISION_UNSUPPORTED_DOCUMENT
    }

    actual_changes = {
        key: value
        for key, value in transitions.items()
        if value != key[1]
    }

    assert_equal(
        actual_changes,
        expected_changes,
        (
            "Exactly one transition is permitted: "
            "REVIEW_REQUIRED becomes "
            "UNSUPPORTED_DOCUMENT when the outcome is "
            "UNSUPPORTED. Everything else passes through "
            "unchanged."
        ),
    )

    ok(
        f"All {len(transitions)} outcome/decision "
        "combinations checked: exactly one transition "
        "exists, no input is mutated, AUTO_ACCEPT is never "
        "written"
    )


    # ------------------------------------------------------
    # The unsupported decision itself.
    # ------------------------------------------------------

    unsupported = (
        apply_classification_to_review(
            {
                "decision": (
                    DECISION_REVIEW_REQUIRED
                ),
                "review_required": True,
                "priority": "HIGH",
                "reason_codes": [
                    "UNKNOWN_DOCUMENT_TYPE"
                ],
                "issues": base_issues,
            },
            OUTCOME_UNSUPPORTED,
        )
    )

    assert_equal(
        unsupported["review_required"],
        False,
        (
            "An unsupported document does not require a "
            "review."
        ),
    )

    assert_equal(
        unsupported["priority"],
        "NONE",
        (
            "An unsupported document carries no reviewer "
            "priority, because no reviewer is queued."
        ),
    )

    assert_equal(
        unsupported["issues"],
        base_issues,
        (
            "The issues are the audit trail and are kept "
            "verbatim."
        ),
    )

    ok(
        "UNSUPPORTED_DOCUMENT: review_required False, "
        "priority NONE, issues preserved verbatim"
    )


def test_review_decision_service_untouched() -> None:

    section(
        "TEST 5 - THE REVIEW DECISION SERVICE IS UNTOUCHED"
    )

    import inspect

    signature = inspect.signature(
        ReviewDecisionService.decide
    )

    assert_equal(
        list(
            signature.parameters
        ),
        [
            "self",
            "anomaly_result",
        ],
        (
            "ReviewDecisionService.decide must keep its "
            "audited signature. Phase 10.2 runs after it "
            "rather than threading a new input through it, "
            "so every existing guarantee about machine "
            "review semantics still holds."
        ),
    )

    # And it still cannot produce the third value itself.
    source = inspect.getsource(
        ReviewDecisionService
    )

    assert_true(
        DECISION_UNSUPPORTED_DOCUMENT
        not in source,
        (
            "The review decision service must not know "
            "about UNSUPPORTED_DOCUMENT. The "
            "classification policy owns it."
        ),
    )

    ok(
        "decide() keeps its signature and never writes "
        "UNSUPPORTED_DOCUMENT itself"
    )


# ==========================================================
# 3. PIPELINE INTEGRATION, REAL SERVICES, REAL IMAGES
# ==========================================================

def test_pipeline_supported_document_unaffected(
    temp_dir: Path,
) -> None:

    section(
        "TEST 6 - A SUPPORTED DOCUMENT IS UNAFFECTED"
    )

    pipeline, fake_ocr, fake_extraction = (
        build_pipeline()
    )

    reference = date(
        2026,
        8,
        20,
    )

    # ------------------------------------------------------
    # Clean image.
    # ------------------------------------------------------

    clean_result = pipeline.process(
        str(
            clean_image()
        ),
        reference_date=reference,
    )

    decision = (
        clean_result[
            "review_decision"
        ]["decision"]
    )

    assert_true(
        decision
        != DECISION_UNSUPPORTED_DOCUMENT,
        (
            "A Guard Licence must never be marked "
            "unsupported."
        ),
    )

    assert_equal(
        clean_result[
            "extraction"
        ]["document_type"],
        "guard_license",
        (
            "The extracted document type must reach the "
            "result unchanged."
        ),
    )

    ok(
        f"Clean Guard Licence -> decision {decision}, "
        "document_type preserved"
    )


    # ------------------------------------------------------
    # The same document, severely degraded.
    #
    # This is the case the phase exists to get right: the
    # image is unreadable, the document type is known, and
    # nothing about the classification may change.
    # ------------------------------------------------------

    for label, kwargs in (
        (
            "severely blurred",
            {
                "blur_sigma": 4.0,
            },
        ),
        (
            "very dark",
            {
                "brightness": 0.20,
            },
        ),
    ):

        degraded = degraded_copy(
            temp_dir,
            name=(
                f"guard-{label.replace(' ', '-')}.jpg"
            ),
            **kwargs,
        )

        result = pipeline.process(
            str(
                degraded
            ),
            reference_date=reference,
        )

        findings = [
            finding["code"]
            for finding in result[
                "quality"
            ]["findings"]
        ]

        assert_true(
            findings,
            (
                f"The {label} image should produce at "
                "least one quality finding, or this test "
                "is not testing what it claims to."
            ),
        )

        assert_true(
            result[
                "review_decision"
            ]["decision"]
            != DECISION_UNSUPPORTED_DOCUMENT,
            (
                f"A {label} Guard Licence must not become "
                "unsupported. Its type was read; only the "
                "photograph is bad."
            ),
        )

        assert_equal(
            result[
                "extraction"
            ]["document_type"],
            "guard_license",
            (
                "A degraded supported document keeps its "
                "type."
            ),
        )

        ok(
            f"{label.capitalize()} Guard Licence -> "
            f"quality {findings}, decision "
            f"{result['review_decision']['decision']}, "
            "still guard_license"
        )


def test_pipeline_unsupported_clean_image(
    temp_dir: Path,
) -> None:

    section(
        "TEST 7 - A READABLE FILE THAT IS NOT SUPPORTED"
    )

    # A clean image, readable OCR text, and an extractor that
    # could not name the type. A receipt.
    pipeline, _, _ = build_pipeline(
        lines=ocr_lines(
            [
                "THANK YOU FOR YOUR PURCHASE",
                "TOTAL 42.60",
                "VISA ENDING 4411",
                "STORE 0142 TILL 3",
            ]
        ),
        extraction=(
            unknown_extraction()
        ),
    )

    result = pipeline.process(
        str(
            clean_image()
        ),
        reference_date=date(
            2026,
            8,
            20,
        ),
    )

    review = result[
        "review_decision"
    ]

    assert_equal(
        review["decision"],
        DECISION_UNSUPPORTED_DOCUMENT,
        (
            "A readable file the extractor could not "
            "classify becomes UNSUPPORTED_DOCUMENT."
        ),
    )

    assert_equal(
        review["review_required"],
        False,
        (
            "It must not create reviewer workload."
        ),
    )

    assert_true(
        "UNKNOWN_DOCUMENT_TYPE"
        in review["reason_codes"],
        (
            "The reason must still be recorded."
        ),
    )

    assert_equal(
        result[
            "quality"
        ]["findings"],
        [],
        (
            "The clean evaluation image must produce no "
            "quality findings, which is what makes the "
            "unsupported conclusion safe here."
        ),
    )

    ok(
        "Readable unclassified file -> "
        "UNSUPPORTED_DOCUMENT, review_required False, "
        "reason preserved, zero quality findings"
    )


def test_pipeline_unclassified_degraded_image(
    temp_dir: Path,
) -> None:

    section(
        "TEST 8 - AN UNCLASSIFIED FILE THAT COULD NOT BE READ"
    )

    degraded = degraded_copy(
        temp_dir,
        name="unclassified-blurred.jpg",
        blur_sigma=4.0,
    )

    pipeline, _, _ = build_pipeline(
        lines=ocr_lines(
            [
                "TEXAS DEPAR MENT 0F PU8LIC 5AFETY",
                "5ECURI Y GU RD",
            ]
        ),
        extraction=(
            unknown_extraction()
        ),
    )

    result = pipeline.process(
        str(
            degraded
        ),
        reference_date=date(
            2026,
            8,
            20,
        ),
    )

    findings = [
        finding["code"]
        for finding in result[
            "quality"
        ]["findings"]
    ]

    assert_true(
        bool(
            set(
                findings
            )
            & READABILITY_IMPAIRING_QUALITY_CODES
        ),
        (
            "The blurred image must raise a readability "
            "finding, or this test proves nothing. "
            f"findings={findings}"
        ),
    )

    review = result[
        "review_decision"
    ]

    assert_equal(
        review["decision"],
        DECISION_REVIEW_REQUIRED,
        (
            "An unclassified document whose image could "
            "not be read must reach a human rather than "
            "being confidently declared unsupported."
        ),
    )

    assert_equal(
        review["review_required"],
        True,
        (
            "It is genuine reviewer work: a person looking "
            "at the image can resolve it."
        ),
    )

    ok(
        f"Unclassified and unreadable -> quality "
        f"{findings}, decision REVIEW_REQUIRED (not "
        "confidently unsupported)"
    )


def test_pipeline_blank_image(
    temp_dir: Path,
) -> None:

    section(
        "TEST 9 - BLANK AND NEAR-BLANK IMAGES"
    )

    for label, value, lines in (
        (
            "blank white",
            255,
            [],
        ),
        (
            "blank black",
            0,
            [],
        ),
        (
            "near blank",
            250,
            [],
        ),
    ):

        path = blank_image(
            temp_dir,
            name=(
                f"{label.replace(' ', '-')}.jpg"
            ),
            value=value,
        )

        pipeline, _, _ = build_pipeline(
            lines=lines,
            extraction=(
                unknown_extraction()
            ),
        )

        result = pipeline.process(
            str(
                path
            ),
            reference_date=date(
                2026,
                8,
                20,
            ),
        )

        review = result[
            "review_decision"
        ]

        assert_equal(
            review["decision"],
            DECISION_UNSUPPORTED_DOCUMENT,
            (
                f"A {label} image produces no OCR text, so "
                "there is nothing for a reviewer to read. "
                "It must not enter the queue."
            ),
        )

        assert_equal(
            review["review_required"],
            False,
            (
                f"A {label} image must not create reviewer "
                "workload."
            ),
        )

        findings = [
            finding["code"]
            for finding in result[
                "quality"
            ]["findings"]
        ]

        ok(
            f"{label.capitalize()} image -> quality "
            f"{findings}, UNSUPPORTED_DOCUMENT, no "
            "reviewer workload"
        )


def test_pipeline_never_auto_accepts_unknown(
    temp_dir: Path,
) -> None:

    section(
        "TEST 10 - AN UNKNOWN TYPE CAN NEVER AUTO-ACCEPT"
    )

    # Across every image condition available, and with OCR
    # text present or absent.
    conditions = [
        (
            "clean",
            str(
                clean_image()
            ),
        ),
        (
            "blurred",
            str(
                degraded_copy(
                    temp_dir,
                    name="aa-blur.jpg",
                    blur_sigma=2.0,
                )
            ),
        ),
        (
            "dark",
            str(
                degraded_copy(
                    temp_dir,
                    name="aa-dark.jpg",
                    brightness=0.30,
                )
            ),
        ),
        (
            "bright",
            str(
                degraded_copy(
                    temp_dir,
                    name="aa-bright.jpg",
                    brightness=1.60,
                )
            ),
        ),
        (
            "blank",
            str(
                blank_image(
                    temp_dir,
                    name="aa-blank.jpg",
                )
            ),
        ),
    ]

    checked = 0

    for label, path in conditions:

        for line_set in (
            [],
            ocr_lines(
                [
                    "SOME TEXT",
                    "MORE TEXT",
                ]
            ),
        ):

            pipeline, _, _ = build_pipeline(
                lines=line_set,
                extraction=(
                    unknown_extraction()
                ),
            )

            result = pipeline.process(
                path,
                reference_date=date(
                    2026,
                    8,
                    20,
                ),
            )

            decision = (
                result[
                    "review_decision"
                ]["decision"]
            )

            assert_true(
                decision
                != DECISION_AUTO_ACCEPT,
                (
                    "An unknown document type must never "
                    "be auto-accepted. "
                    f"image={label} "
                    f"ocr_lines={len(line_set)} "
                    f"decision={decision}"
                ),
            )

            checked += 1

    ok(
        f"{checked} image and OCR combinations: an "
        "unknown document type never reached AUTO_ACCEPT"
    )


# ==========================================================
# 4. FINAL RECORD SEMANTICS
# ==========================================================

def test_final_record_parity_and_usability() -> None:

    section(
        "TEST 11 - FINAL RECORD SEMANTICS"
    )

    service = FinalRecordService()

    extraction = (
        unknown_extraction()
    )

    actions = [
        None,
        "APPROVE",
        "CORRECT",
        "REJECT",
    ]

    # ------------------------------------------------------
    # resolve_final_status and build must agree for every
    # combination, including the new decision value. The list
    # endpoint uses the first and the detail endpoint uses
    # the second, so a disagreement means two screens
    # describing the same document differently.
    # ------------------------------------------------------

    combinations = 0

    for decision in list(
        MACHINE_DECISIONS
    ) + [
        None
    ]:

        for action in actions:

            human = (
                None
                if action is None
                else {
                    "human_action": action,
                    "corrections": (
                        {
                            "full_name": "X"
                        }
                        if action == "CORRECT"
                        else {}
                    ),
                }
            )

            resolved = (
                FinalRecordService
                .resolve_final_status(
                    machine_decision=(
                        decision
                    ),
                    human_action=(
                        action
                    ),
                )
            )

            built = service.build(
                extraction=(
                    extraction
                ),
                machine_review_decision=(
                    {
                        "decision": decision
                    }
                    if decision
                    else {}
                ),
                human_review=human,
            )

            assert_equal(
                built["final_status"],
                resolved,
                (
                    "The list path and the detail path "
                    "must resolve the same final status. "
                    f"decision={decision} action={action}"
                ),
            )

            combinations += 1

    ok(
        f"{combinations} decision/action combinations: "
        "resolve_final_status and build agree exactly"
    )


    # ------------------------------------------------------
    # The unsupported record publishes nothing.
    # ------------------------------------------------------

    record = service.build(
        extraction=extraction,
        machine_review_decision={
            "decision": (
                DECISION_UNSUPPORTED_DOCUMENT
            )
        },
        human_review=None,
    )

    assert_equal(
        record["final_status"],
        "UNSUPPORTED",
        "An unsupported decision resolves to UNSUPPORTED.",
    )

    assert_equal(
        record["is_usable"],
        False,
        (
            "An unsupported document is never usable. This "
            "is the statement that keeps a receipt out of "
            "any downstream system."
        ),
    )

    assert_equal(
        record["effective_values"],
        None,
        (
            "No effective values may be published for an "
            "unsupported document."
        ),
    )

    assert_equal(
        record["value_sources"],
        None,
        (
            "With no effective values there are no value "
            "sources."
        ),
    )

    assert_equal(
        record["is_final"],
        True,
        (
            "Nothing further happens automatically, so it "
            "is final. Reporting it as pending would "
            "describe a wait that never ends."
        ),
    )

    assert_true(
        record["machine_values"]
        is not None,
        (
            "The machine reading is kept for audit, so an "
            "operator can see why the file was set aside."
        ),
    )

    ok(
        "UNSUPPORTED record: is_usable False, "
        "effective_values None, value_sources None, "
        "is_final True, machine reading retained"
    )


    # ------------------------------------------------------
    # A human can still reject it.
    # ------------------------------------------------------

    rejected = service.build(
        extraction=extraction,
        machine_review_decision={
            "decision": (
                DECISION_UNSUPPORTED_DOCUMENT
            )
        },
        human_review={
            "human_action": "REJECT",
            "corrections": {},
        },
    )

    assert_equal(
        rejected["final_status"],
        "REJECTED",
        (
            "A human decision still wins over the machine "
            "one, so an unsupported document a reviewer "
            "rejects becomes REJECTED."
        ),
    )

    assert_equal(
        rejected["is_usable"],
        False,
        "A rejected document remains unusable.",
    )

    ok(
        "A human REJECT on an unsupported document "
        "resolves to REJECTED and stays unusable"
    )


def test_final_status_query_spec_round_trip() -> None:

    section(
        "TEST 12 - THE QUERY SPEC IS A TRUE INVERSE"
    )

    for status in FinalRecordService.FINAL_STATUSES:

        spec = (
            FinalRecordService
            .final_status_query_spec(
                status
            )
        )

        # Every machine-only status must exclude documents
        # that already carry a human review, otherwise the
        # filter would return documents whose real status is
        # APPROVED, CORRECTED or REJECTED.
        if status in (
            "AUTO_ACCEPTED",
            "PENDING_REVIEW",
            "UNSUPPORTED",
        ):

            assert_equal(
                spec["human_action_isnull"],
                True,
                (
                    f"{status} is a machine-only status "
                    "and must require the absence of a "
                    "human review."
                ),
            )


    # PENDING_REVIEW is the one that had to change: it must
    # now exclude the unsupported decision too, or every
    # unsupported document would be listed as pending.
    pending = (
        FinalRecordService
        .final_status_query_spec(
            "PENDING_REVIEW"
        )
    )

    excluded = pending[
        "machine_decision_not"
    ]

    assert_true(
        not isinstance(
            excluded,
            str
        ),
        (
            "machine_decision_not must be a collection. A "
            "bare string is iterable, so a repository "
            "building NOT IN from it would compare against "
            "single characters and match nothing."
        ),
    )

    assert_equal(
        set(
            excluded
        ),
        {
            DECISION_AUTO_ACCEPT,
            DECISION_UNSUPPORTED_DOCUMENT,
        },
        (
            "PENDING_REVIEW must exclude both the accepted "
            "and the unsupported decisions."
        ),
    )

    unsupported = (
        FinalRecordService
        .final_status_query_spec(
            "UNSUPPORTED"
        )
    )

    assert_equal(
        unsupported["machine_decision"],
        DECISION_UNSUPPORTED_DOCUMENT,
        (
            "Filtering by UNSUPPORTED must select the "
            "unsupported decision exactly."
        ),
    )

    ok(
        f"All {len(FinalRecordService.FINAL_STATUSES)} "
        "final statuses produce a coherent query spec; "
        "PENDING_REVIEW excludes both machine decisions"
    )


# ==========================================================
# 5. DERIVED DESCRIPTION FOR READ PATHS
# ==========================================================

def test_describe_classification() -> None:

    section(
        "TEST 13 - THE DERIVED DESCRIPTION"
    )

    for document_type in SUPPORTED_DOCUMENT_TYPES:

        for decision in MACHINE_DECISIONS:

            described = (
                describe_classification(
                    document_type=(
                        document_type
                    ),
                    machine_decision=(
                        decision
                    ),
                )
            )

            assert_equal(
                described["outcome"],
                OUTCOME_SUPPORTED,
                (
                    "A supported type is SUPPORTED "
                    "whatever the decision was."
                ),
            )

            assert_equal(
                described["supported"],
                True,
                "A supported type reports supported True.",
            )

    ok(
        "Supported types describe as SUPPORTED under all "
        f"{len(MACHINE_DECISIONS)} decisions"
    )


    unsupported = (
        describe_classification(
            document_type="unknown",
            machine_decision=(
                DECISION_UNSUPPORTED_DOCUMENT
            ),
        )
    )

    assert_equal(
        unsupported["outcome"],
        OUTCOME_UNSUPPORTED,
        "The unsupported decision derives UNSUPPORTED.",
    )

    assert_equal(
        unsupported["supported"],
        False,
        "Unsupported reports supported False.",
    )

    assert_equal(
        unsupported["retryable"],
        False,
        (
            "Unsupported is not retryable. Reprocessing "
            "the same bytes runs the same deterministic "
            "classification and reaches the same answer, "
            "so offering a retry would promise a different "
            "result that cannot happen."
        ),
    )

    assert_true(
        unsupported["message"],
        "Unsupported carries an operator-facing sentence.",
    )

    assert_equal(
        len(
            unsupported[
                "supported_document_types"
            ]
        ),
        3,
        (
            "The three supported type names come from the "
            "domain, so the frontend does not maintain a "
            "second copy of the list."
        ),
    )

    ok(
        "UNSUPPORTED: supported False, retryable False, "
        "message present, three supported type names "
        "supplied by the backend"
    )


    # ------------------------------------------------------
    # Rows written before Phase 10.2.
    #
    # An unclassified document then had decision
    # REVIEW_REQUIRED, and that is exactly what it was:
    # unclassified and waiting for a human.
    # ------------------------------------------------------

    legacy = (
        describe_classification(
            document_type="unknown",
            machine_decision=(
                DECISION_REVIEW_REQUIRED
            ),
        )
    )

    assert_equal(
        legacy["outcome"],
        OUTCOME_UNCLASSIFIED_NEEDS_REVIEW,
        (
            "A pre-Phase-10.2 unclassified row derives as "
            "UNCLASSIFIED_NEEDS_REVIEW, which is what it "
            "was."
        ),
    )

    # A missing decision must not read as supported.
    for decision in (
        None,
        "",
        "SOMETHING_NEW",
    ):

        described = (
            describe_classification(
                document_type="unknown",
                machine_decision=decision,
            )
        )

        assert_equal(
            described["supported"],
            False,
            (
                "An unknown document type is never "
                "supported, whatever the decision field "
                f"holds. decision={decision!r}"
            ),
        )

    ok(
        "Legacy and unrecognised decisions derive "
        "conservatively and never read as supported"
    )


    # ------------------------------------------------------
    # No invented score anywhere in the block.
    # ------------------------------------------------------

    forbidden = (
        "risk",
        "fraud",
        "tamper",
        "score",
        "probability",
        "fake",
        "suspicious",
    )

    for described in (
        unsupported,
        legacy,
        describe_classification(
            document_type="id_card",
            machine_decision=(
                DECISION_AUTO_ACCEPT
            ),
        ),
    ):

        text = json.dumps(
            described
        ).lower()

        for word in forbidden:

            assert_true(
                word not in text,
                (
                    "The classification block must not "
                    "introduce a risk, fraud or tamper "
                    f"signal. Found {word!r} in {text}"
                ),
            )

    ok(
        "No risk, fraud, tamper, score or probability "
        "language anywhere in the classification block"
    )


# ==========================================================
# 6. READ PATHS AGAINST POSTGRESQL
# ==========================================================

RUN_MARKER = (
    f"phase10-2-{uuid.uuid4().hex[:8]}"
)


def build_persisted_result(
    *,
    document_type: str,
    decision: str,
    priority: str,
    quality: dict | None = None,
) -> dict:

    """
    A pipeline result in the persisted shape, for seeding the
    database directly. Only the parts the read paths use.
    """

    issues = (
        []
        if decision == DECISION_AUTO_ACCEPT
        else [
            {
                "code": "UNKNOWN_DOCUMENT_TYPE",
                "severity": "ERROR",
                "field": None,
                "message": (
                    "Document type could not be "
                    "reliably classified."
                ),
            }
        ]
    )

    extraction = (
        unknown_extraction()
        if document_type == "unknown"
        else guard_extraction()
    )

    extraction[
        "document_type"
    ] = document_type

    return {
        "extraction": extraction,

        "ocr_lines": [],

        "evidence_flags": [],

        "field_confidence": {},

        "date_validation": {
            "reference_date": "2026-08-20",
            "date_fields": {},
            "expiry": {
                "value": None,
                "status": "NOT_AVAILABLE",
                "days_until_expiry": None,
            },
            "logical_issues": [],
            "valid": True,
        },

        "anomaly_validation": {
            "document_type": document_type,
            "valid": not issues,
            "has_anomalies": bool(
                issues
            ),
            "error_count": len(
                issues
            ),
            "warning_count": 0,
            "issues": issues,
        },

        "quality": quality,

        "review_decision": {
            "decision": decision,
            "review_required": (
                decision
                == DECISION_REVIEW_REQUIRED
            ),
            "priority": priority,
            "reason_codes": [
                issue["code"]
                for issue in issues
            ],
            "issues": issues,
        },
    }


def test_read_paths() -> None:

    section(
        "TEST 14 - READ PATHS AGAINST POSTGRESQL"
    )

    from database.database import SessionLocal
    from database.repositories import (
        DocumentAnalysisRepository,
        DocumentRepository,
    )
    from backend.app.services.query_service import (
        DocumentQueryService,
    )

    created: list[str] = []

    seeds = [
        (
            "unsupported",
            "unknown",
            DECISION_UNSUPPORTED_DOCUMENT,
            "NONE",
        ),
        (
            "unclassified",
            "unknown",
            DECISION_REVIEW_REQUIRED,
            "HIGH",
        ),
        (
            "review",
            "guard_license",
            DECISION_REVIEW_REQUIRED,
            "MEDIUM",
        ),
        (
            "accepted",
            "guard_license",
            DECISION_AUTO_ACCEPT,
            "NONE",
        ),
    ]

    identifiers = {}

    quality_payload = {
        "metrics": {
            "laplacian_variance": 118.25,
        },
        "findings": [
            {
                "code": "IMAGE_BLURRY",
                "severity": "WARNING",
                "message": "This image is blurred.",
                "metric_name": (
                    "laplacian_variance"
                ),
                "measured_value": 118.25,
                "threshold": 350.0,
            }
        ],
        "highest_severity": "WARNING",
        "error": None,
    }

    try:

        with SessionLocal.begin() as session:

            documents = (
                DocumentRepository(
                    session
                )
            )

            analyses = (
                DocumentAnalysisRepository(
                    session
                )
            )

            for (
                label,
                document_type,
                decision,
                priority,
            ) in seeds:

                document = (
                    documents
                    .create_document(
                        original_filename=(
                            f"{RUN_MARKER}-"
                            f"{label}.jpg"
                        ),
                        content_type=(
                            "image/jpeg"
                        ),
                        document_type=(
                            document_type
                        ),
                    )
                )

                analyses.create_analysis(
                    document_id=(
                        document.id
                    ),
                    pipeline_result=(
                        build_persisted_result(
                            document_type=(
                                document_type
                            ),
                            decision=(
                                decision
                            ),
                            priority=(
                                priority
                            ),
                            quality=(
                                quality_payload
                                if label
                                == "unclassified"
                                else None
                            ),
                        )
                    ),
                )

                identifiers[
                    label
                ] = document.id

                created.append(
                    document.id
                )


        query_service = (
            DocumentQueryService()
        )


        # ==============================================
        # THE REVIEW QUEUE
        # ==============================================

        queue = (
            query_service
            .get_review_queue()
        )

        queue_ids = {
            item["document_id"]
            for item in queue[
                "documents"
            ]
        }

        assert_true(
            identifiers["unsupported"]
            not in queue_ids,
            (
                "An unsupported document must not appear "
                "in the human review queue. This is the "
                "queue-pollution guarantee: receipts and "
                "random photographs must not become "
                "reviewer workload."
            ),
        )

        assert_true(
            identifiers["unclassified"]
            in queue_ids,
            (
                "An unclassified document whose image "
                "could not be read MUST appear in the "
                "queue. Suppressing it would lose a "
                "degraded supported document."
            ),
        )

        assert_true(
            identifiers["review"]
            in queue_ids,
            (
                "An ordinary review-required document "
                "must still be queued."
            ),
        )

        assert_true(
            identifiers["accepted"]
            not in queue_ids,
            (
                "An auto-accepted document is not queued, "
                "as before."
            ),
        )

        ok(
            "Review queue: unsupported excluded, "
            "unclassified-and-unreadable included, "
            "ordinary review included, accepted excluded"
        )


        # ==============================================
        # THE DASHBOARD
        # ==============================================

        summary = (
            query_service
            .get_dashboard_summary()
        )

        review_counts = summary[
            "review"
        ]

        assert_true(
            "unsupported"
            in review_counts,
            (
                "The dashboard must report unsupported "
                "documents as their own count."
            ),
        )

        assert_true(
            review_counts[
                "unsupported"
            ] >= 1,
            (
                "The seeded unsupported document must be "
                "counted."
            ),
        )

        ok(
            "Dashboard reports unsupported separately: "
            f"unsupported={review_counts['unsupported']}, "
            "pending_review="
            f"{review_counts['pending_review']}, "
            "review_required="
            f"{review_counts['review_required']}"
        )


        # ==============================================
        # THE DOCUMENTS LIST AND ITS FILTERS
        # ==============================================

        listing = (
            query_service
            .list_documents(
                search=RUN_MARKER,
                page=1,
                page_size=50,
            )
        )

        by_id = {
            item["document_id"]: item
            for item in listing[
                "items"
            ]
        }

        assert_equal(
            len(
                by_id
            ),
            len(
                seeds
            ),
            (
                "All four seeded documents must be "
                "listed."
            ),
        )

        unsupported_row = by_id[
            identifiers[
                "unsupported"
            ]
        ]

        assert_equal(
            unsupported_row[
                "final_state"
            ],
            "UNSUPPORTED",
            (
                "The list must report the unsupported "
                "final state."
            ),
        )

        assert_equal(
            unsupported_row[
                "classification_outcome"
            ],
            OUTCOME_UNSUPPORTED,
            (
                "The list must carry the classification "
                "outcome."
            ),
        )

        assert_equal(
            by_id[
                identifiers[
                    "unclassified"
                ]
            ][
                "classification_outcome"
            ],
            OUTCOME_UNCLASSIFIED_NEEDS_REVIEW,
            (
                "An unclassified document reads as "
                "UNCLASSIFIED_NEEDS_REVIEW in the list."
            ),
        )

        assert_equal(
            by_id[
                identifiers[
                    "review"
                ]
            ][
                "classification_outcome"
            ],
            OUTCOME_SUPPORTED,
            (
                "A supported document reads as SUPPORTED "
                "in the list."
            ),
        )

        ok(
            "Documents list carries final_state and "
            "classification_outcome for all four seeded "
            "documents"
        )


        # ---- final_state=PENDING_REVIEW must exclude ----

        pending = (
            query_service
            .list_documents(
                search=RUN_MARKER,
                final_state=(
                    "PENDING_REVIEW"
                ),
                page=1,
                page_size=50,
            )
        )

        pending_ids = {
            item["document_id"]
            for item in pending[
                "items"
            ]
        }

        assert_true(
            identifiers["unsupported"]
            not in pending_ids,
            (
                "Filtering by PENDING_REVIEW must not "
                "return unsupported documents. This is "
                "the tuple exclusion working: a bare "
                "string would have matched only "
                "AUTO_ACCEPT and listed every "
                "unsupported document as pending."
            ),
        )

        assert_true(
            identifiers["unclassified"]
            in pending_ids
            and identifiers["review"]
            in pending_ids,
            (
                "Both genuinely pending documents must be "
                "returned."
            ),
        )

        assert_true(
            identifiers["accepted"]
            not in pending_ids,
            (
                "An accepted document is not pending."
            ),
        )

        ok(
            "final_state=PENDING_REVIEW returns exactly "
            "the two genuinely pending documents"
        )


        # ---- final_state=UNSUPPORTED must select ----

        only_unsupported = (
            query_service
            .list_documents(
                search=RUN_MARKER,
                final_state="UNSUPPORTED",
                page=1,
                page_size=50,
            )
        )

        assert_equal(
            {
                item["document_id"]
                for item in only_unsupported[
                    "items"
                ]
            },
            {
                identifiers[
                    "unsupported"
                ]
            },
            (
                "Filtering by UNSUPPORTED must return "
                "exactly the unsupported document."
            ),
        )

        ok(
            "final_state=UNSUPPORTED selects exactly the "
            "unsupported document"
        )


        # ==============================================
        # DETAIL PATH, AND AGREEMENT WITH THE LIST
        # ==============================================

        for label, document_id in identifiers.items():

            detail = (
                query_service
                .get_document(
                    document_id
                )
            )

            assert_true(
                "classification" in detail,
                (
                    "The detail payload must always "
                    "carry a classification key."
                ),
            )

            assert_equal(
                detail[
                    "classification"
                ]["outcome"],
                by_id[
                    document_id
                ][
                    "classification_outcome"
                ],
                (
                    "The list and the detail path must "
                    "agree about the classification "
                    "outcome. They derive it from the "
                    "same function precisely so they "
                    f"cannot disagree. label={label}"
                ),
            )

            assert_true(
                "quality"
                in detail["analysis"],
                (
                    "The detail payload must expose the "
                    "stored quality assessment."
                ),
            )

        ok(
            "Detail path exposes classification and "
            "quality, and agrees with the list on all "
            f"{len(identifiers)} documents"
        )


        # ---- null quality stays null ----

        accepted_detail = (
            query_service
            .get_document(
                identifiers[
                    "accepted"
                ]
            )
        )

        assert_equal(
            accepted_detail[
                "analysis"
            ]["quality"],
            None,
            (
                "A document stored without a quality "
                "assessment must report null, not an "
                "empty assessment. null means NOT "
                "ASSESSED; an empty assessment would "
                "mean NO PROBLEMS FOUND, and those are "
                "different statements."
            ),
        )

        unclassified_detail = (
            query_service
            .get_document(
                identifiers[
                    "unclassified"
                ]
            )
        )

        assert_equal(
            len(
                unclassified_detail[
                    "analysis"
                ]["quality"]["findings"]
            ),
            1,
            (
                "A stored quality assessment must reach "
                "the detail payload intact."
            ),
        )

        ok(
            "quality null stays null (NOT ASSESSED) and a "
            "stored assessment survives intact"
        )


        # ==============================================
        # NO USABLE RECORD
        # ==============================================

        unsupported_detail = (
            query_service
            .get_document(
                identifiers[
                    "unsupported"
                ]
            )
        )

        final_record = (
            unsupported_detail[
                "final_record"
            ]
        )

        assert_equal(
            final_record[
                "final_status"
            ],
            "UNSUPPORTED",
            (
                "The persisted unsupported document "
                "resolves to UNSUPPORTED end to end."
            ),
        )

        assert_equal(
            final_record["is_usable"],
            False,
            (
                "No usable record may be published for a "
                "persisted unsupported document."
            ),
        )

        assert_equal(
            final_record[
                "effective_values"
            ],
            None,
            (
                "No effective values may be published."
            ),
        )

        ok(
            "End to end: a persisted unsupported document "
            "publishes no usable record and no effective "
            "values"
        )


    finally:

        # ==============================================
        # CLEAN UP
        # ==============================================
        #
        # Only rows this run created, found by primary key.
        # ==============================================

        if created:

            with SessionLocal.begin() as session:

                repository = (
                    DocumentRepository(
                        session
                    )
                )

                for document_id in created:

                    document = (
                        repository
                        .get_document(
                            document_id
                        )
                    )

                    if document is not None:

                        repository.delete_document(
                            document
                        )


# ==========================================================
# 7. THE ASYNC JOB PATH
# ==========================================================

def test_job_path() -> None:

    section(
        "TEST 15 - THE ASYNC JOB PATH"
    )

    from database.database import SessionLocal
    from database.job_repositories import (
        DocumentJobRepository,
    )
    from database.models import (
        DocumentJobModel,
    )
    from database.repositories import (
        DocumentRepository,
    )
    from backend.app.services.job_service import (
        JobService,
    )
    from backend.app.services.job_source_store import (
        JobSourceStore,
    )
    from backend.app.services.document_worker import (
        DocumentWorker,
    )
    from backend.app.services.persistence_service import (
        PersistenceService,
    )

    temp_root = Path(
        tempfile.mkdtemp(
            prefix="vigilox-phase102-",
        )
    )

    created_documents: list[str] = []

    # Captured outside the try so the cleanup below can always
    # see it, including when the run fails before the worker
    # ever claims the job. An earlier version left its own
    # QUEUED row behind on failure, which then tripped the
    # quiet-queue guard on the next run -- a failure that
    # poisons the next run of the same test.
    queued_job_id: str | None = None

    try:

        store = JobSourceStore(
            pending_root=(
                temp_root / "pending"
            ),
        )

        jobs = JobService(
            source_store=store,
        )

        # A real image, so the real quality service runs.
        #
        # PHASE 10.3. The bytes are made UNIQUE PER RUN by
        # appending the run marker.
        #
        # Copying the fixture unchanged made this test depend
        # on nobody having ever processed guard_001.jpg, which
        # is not something a test can assume once exact
        # duplicate detection exists -- and it failed the
        # moment another suite had processed those bytes. The
        # appended marker keeps the image decodable, since a
        # JPEG decoder stops at the end-of-image marker.
        upload = (
            temp_root
            / "receipt.jpg"
        )

        upload.write_bytes(
            clean_image().read_bytes()
            + RUN_MARKER.encode()
        )

        payload = jobs.create_job(
            original_filename=(
                f"{RUN_MARKER}-receipt.jpg"
            ),
            content_type="image/jpeg",
            size_bytes=(
                upload.stat().st_size
            ),
            upload_path=upload,
        )

        job_id = payload["job_id"]

        queued_job_id = job_id

        assert_equal(
            payload["status"],
            "QUEUED",
            "A new job starts QUEUED.",
        )

        # Real pipeline, real persistence, fake OCR and
        # extraction only.
        pipeline, _, _ = build_pipeline(
            lines=ocr_lines(
                [
                    "THANK YOU FOR YOUR PURCHASE",
                    "TOTAL 42.60",
                ]
            ),
            extraction=(
                unknown_extraction()
            ),
        )

        worker = DocumentWorker(
            pipeline=pipeline,
            persistence=(
                PersistenceService()
            ),
            job_service=jobs,
            worker_id=(
                f"phase102-{uuid.uuid4().hex[:8]}"
            ),
            lease_seconds=180,
        )

        # ==============================================
        # CLAIM THIS JOB, NOT WHATEVER IS OLDEST
        # ==============================================
        #
        # process_one() with no argument claims the oldest
        # claimable job in the database, which is not
        # necessarily the one this test just queued -- it could
        # be a real upload somebody made through the browser.
        # Processing that with the pipeline injected below,
        # which returns a receipt, would write a wrong
        # extraction onto a real document.
        #
        # Naming the job removes the hazard rather than
        # detecting it. An earlier version asserted the queue
        # was empty instead, which failed the whole suite
        # whenever the application had been used.
        # ==============================================

        claimed = (
            worker.process_one(
                only_job_ids=job_id,
            )
        )

        assert_true(
            claimed,
            (
                "The worker must claim and process the "
                "queued job."
            ),
        )


        with SessionLocal.begin() as session:

            job = (
                DocumentJobRepository(
                    session
                )
                .get_job(
                    job_id
                )
            )

            status = job.status
            document_id = job.document_id
            attempts = job.attempt_count
            error_code = job.safe_error_code


        # ==============================================
        # COMPLETED, NOT FAILED
        # ==============================================

        assert_equal(
            status,
            "COMPLETED",
            (
                "An unsupported document is a DOMAIN "
                "OUTCOME, not an infrastructure failure. "
                "The pipeline ran to the end and produced "
                "a record, so the job COMPLETED. Failing "
                "the job would make the outcome look "
                "transient and invite a retry that cannot "
                "change anything."
            ),
        )

        assert_equal(
            error_code,
            None,
            (
                "A completed job carries no error code. "
                "Unsupported is not an error."
            ),
        )

        assert_equal(
            attempts,
            1,
            (
                "Exactly one attempt. An unsupported "
                "document is not retried, because "
                "reprocessing the same bytes reaches the "
                "same deterministic answer."
            ),
        )

        assert_true(
            document_id,
            (
                "A completed job must reference the "
                "document it produced, so the outcome "
                "stays discoverable and auditable through "
                "the Documents experience."
            ),
        )

        created_documents.append(
            document_id
        )

        ok(
            "Unsupported document -> job COMPLETED, no "
            f"error code, {attempts} attempt, document "
            "reference returned"
        )


        # ==============================================
        # THE PERSISTED OUTCOME
        # ==============================================

        from backend.app.services.query_service import (
            DocumentQueryService,
        )

        detail = (
            DocumentQueryService()
            .get_document(
                document_id
            )
        )

        assert_equal(
            detail[
                "analysis"
            ]["review_decision"]["decision"],
            DECISION_UNSUPPORTED_DOCUMENT,
            (
                "The unsupported decision must be "
                "persisted."
            ),
        )

        assert_equal(
            detail[
                "classification"
            ]["outcome"],
            OUTCOME_UNSUPPORTED,
            (
                "The persisted job result derives as "
                "UNSUPPORTED."
            ),
        )

        assert_equal(
            detail[
                "classification"
            ]["retryable"],
            False,
            (
                "The API must tell the caller this is not "
                "retryable."
            ),
        )

        assert_equal(
            detail[
                "final_record"
            ]["is_usable"],
            False,
            (
                "No usable record from the async path "
                "either."
            ),
        )

        assert_true(
            detail[
                "analysis"
            ]["quality"] is not None,
            (
                "The worker path must persist the quality "
                "assessment, because the classification "
                "decision depended on it."
            ),
        )

        ok(
            "Persisted async outcome: "
            "UNSUPPORTED_DOCUMENT decision, UNSUPPORTED "
            "classification, retryable False, no usable "
            "record, quality assessment stored"
        )


    finally:

        # ==============================================
        # THIS RUN CLEANS UP AFTER ITSELF
        # ==============================================
        #
        # The job row first. It is deleted by primary key,
        # so this can only ever remove the row this test
        # created -- never a job belonging to anything else.
        # ==============================================

        if queued_job_id is not None:

            with SessionLocal.begin() as session:

                job = session.get(
                    DocumentJobModel,
                    queued_job_id,
                )

                if job is not None:

                    session.delete(
                        job
                    )


        if created_documents:

            with SessionLocal.begin() as session:

                repository = (
                    DocumentRepository(
                        session
                    )
                )

                for document_id in created_documents:

                    document = (
                        repository
                        .get_document(
                            document_id
                        )
                    )

                    if document is not None:

                        repository.delete_document(
                            document
                        )

        shutil.rmtree(
            temp_root,
            ignore_errors=True,
        )


# ==========================================================
# 8. THE INTERFACE
# ==========================================================

WORKSPACE_HARNESS = (
    PROJECT_ROOT
    / "tests"
    / "dashboard"
    / "workspace_harness.js"
)


def test_workspace_interface() -> None:

    section(
        "TEST 16 - THE DOCUMENT WORKSPACE"
    )

    node = shutil.which(
        "node"
    )

    if node is None:

        raise AssertionError(
            (
                "Node is required to execute the "
                "workspace. Asserting on source text "
                "instead would prove nothing about what a "
                "reviewer sees."
            )
        )


    completed = subprocess.run(
        [
            node,
            str(
                WORKSPACE_HARNESS
            ),
        ],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(
            PROJECT_ROOT
        ),
    )


    if completed.returncode != 0:

        raise AssertionError(
            (
                "Workspace harness failed.\n"
                f"{completed.stdout[:3000]}\n"
                f"{completed.stderr[:3000]}"
            )
        )


    results = json.loads(
        completed.stdout
    )


    # ------------------------------------------------------
    # THE UNSUPPORTED WORKSPACE
    # ------------------------------------------------------

    unsupported = results[
        "classification_unsupported"
    ]

    assert_equal(
        unsupported["alert_count"],
        1,
        (
            "An unsupported document must be explained "
            "once, at the top of the overview."
        ),
    )

    for fragment in (
        "Unsupported document",
        "could not reliably identify",
        "Security Guard License",
        "ID Card",
        "SIA Badge",
    ):

        assert_true(
            fragment
            in unsupported["alert_text"],
            (
                "The unsupported message must name what "
                "happened and which types are supported. "
                f"Missing: {fragment!r}"
            ),
        )

    assert_true(
        "alert-warning"
        not in unsupported[
            "alert_classes"
        ],
        (
            "An unsupported file is not a fault the "
            "uploader has to fix, so it must not be "
            "styled as a warning."
        ),
    )

    ok(
        "Unsupported workspace explains the outcome once "
        "and names all three supported types"
    )


    # ---- and offers no way to publish anything ----

    assert_equal(
        unsupported["form_hidden"],
        True,
        (
            "No review form on an unsupported document."
        ),
    )

    assert_equal(
        unsupported["approve_visible"],
        False,
        (
            "Approve must be unreachable. Approving an "
            "unsupported document would publish an "
            "effective record whose type is unknown and "
            "whose fields are empty, which is exactly the "
            "outcome this policy exists to prevent."
        ),
    )

    assert_equal(
        unsupported["locked_hidden"],
        False,
        (
            "The reason no review is offered must be "
            "stated rather than left blank."
        ),
    )

    assert_true(
        "nothing here for a reviewer"
        in unsupported["locked_text"],
        (
            "The locked message must say why, not just "
            "that."
        ),
    )

    assert_true(
        "No effective values are published"
        in unsupported["effective_text"],
        (
            "The effective-values panel must state that "
            "nothing was published."
        ),
    )

    ok(
        "Unsupported workspace offers no form, no Approve, "
        "and publishes no effective values"
    )


    # ------------------------------------------------------
    # THE UNREADABLE WORKSPACE STILL TAKES A REVIEW
    # ------------------------------------------------------

    unreadable = results[
        "classification_unreadable"
    ]

    assert_equal(
        unreadable["form_hidden"],
        False,
        (
            "An unclassified document whose image could "
            "not be read is genuine reviewer work, so the "
            "form must be offered."
        ),
    )

    assert_equal(
        unreadable["approve_visible"],
        True,
        (
            "A reviewer looking at the image can resolve "
            "it, so the decision controls must be "
            "available."
        ),
    )

    assert_true(
        "alert-warning"
        in unreadable["alert_classes"],
        (
            "This one DOES need someone to act, so it is "
            "styled as a warning."
        ),
    )

    assert_true(
        "Could not be classified"
        in unreadable["alert_text"],
        (
            "It must not be described as unsupported, "
            "because that is precisely what could not be "
            "established."
        ),
    )

    ok(
        "Unclassified-and-unreadable workspace keeps the "
        "review form and is not described as unsupported"
    )


    # ------------------------------------------------------
    # THE THREE QUALITY STATES
    # ------------------------------------------------------

    not_assessed = results[
        "quality_not_assessed"
    ]["text"]

    assert_true(
        "Not assessed" in not_assessed,
        (
            "A document with no stored assessment must "
            "read as NOT ASSESSED."
        ),
    )

    assert_true(
        "No image quality problems"
        not in not_assessed,
        (
            "NOT ASSESSED must never be presented as NO "
            "PROBLEMS FOUND. That is the whole reason the "
            "column is nullable."
        ),
    )

    clean = results[
        "quality_clean"
    ]["text"]

    assert_true(
        "No image quality problems were measured"
        in clean,
        (
            "An assessment with no findings must say so "
            "explicitly, distinctly from not having been "
            "assessed."
        ),
    )

    findings = results[
        "quality_findings"
    ]["text"]

    for fragment in (
        "Image is blurred",
        "laplacian_variance measured 118.25 "
        "against a threshold of 350",
        "IMAGE_BLURRY",
        "Document appears rotated",
        "not a verdict on the document",
        "calibrated on the VIGILOX evaluation set",
    ):

        assert_true(
            fragment in findings,
            (
                "A quality finding must show its measured "
                "value against its threshold, its stable "
                "code, and the limits of the calibration. "
                f"Missing: {fragment!r}"
            ),
        )

    for word in (
        "risk",
        "fraud",
        "tamper",
        "invalid document",
    ):

        assert_true(
            word.lower()
            not in findings.lower(),
            (
                "Quality findings must not imply a "
                "verdict on the document. Found "
                f"{word!r}."
            ),
        )

    ok(
        "Three quality states render distinctly; findings "
        "show measured value against threshold and state "
        "the calibration limits"
    )


    # ------------------------------------------------------
    # THE FINAL RECORD PANEL
    # ------------------------------------------------------

    record = results[
        "final_unsupported"
    ]

    assert_equal(
        record["status_text"],
        "Unsupported",
        (
            "The final record panel names the status."
        ),
    )

    assert_true(
        "Not usable" in record["badges"],
        (
            "The panel must show the record is not "
            "usable."
        ),
    )

    assert_true(
        "final-record-unsupported"
        in record["classes"],
        (
            "The panel must carry the state class, so it "
            "is styled rather than falling back to the "
            "default."
        ),
    )

    ok(
        "Final record panel: Unsupported, Not usable, "
        "styled with its own state class"
    )


# ==========================================================
# MAIN
# ==========================================================

def main() -> int:

    print()
    print(
        "=" * 74
    )
    print(
        "PHASE 10.2 - UNSUPPORTED / UNKNOWN DOCUMENT "
        "HANDLING"
    )
    print(
        "=" * 74
    )

    temp_dir = Path(
        tempfile.mkdtemp(
            prefix="vigilox-p102-img-",
        )
    )

    try:

        test_supported_types_are_never_reclassified()
        test_unknown_classification_rule()
        test_quality_code_lists_agree()
        test_decision_effect_is_exhaustive()
        test_review_decision_service_untouched()

        test_pipeline_supported_document_unaffected(
            temp_dir
        )
        test_pipeline_unsupported_clean_image(
            temp_dir
        )
        test_pipeline_unclassified_degraded_image(
            temp_dir
        )
        test_pipeline_blank_image(
            temp_dir
        )
        test_pipeline_never_auto_accepts_unknown(
            temp_dir
        )

        test_final_record_parity_and_usability()
        test_final_status_query_spec_round_trip()
        test_describe_classification()

        test_read_paths()
        test_job_path()
        test_workspace_interface()

    finally:

        shutil.rmtree(
            temp_dir,
            ignore_errors=True,
        )


    print()
    print(
        "=" * 74
    )
    print(
        "[PASS] PHASE 10.2 UNSUPPORTED DOCUMENT TEST "
        "PASSED"
    )
    print(
        "=" * 74
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
