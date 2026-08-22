# ==========================================================
# DOCUMENT CLASSIFICATION OUTCOME
# PHASE 10.2
# ==========================================================
#
# WHAT THIS ANSWERS
# ----------------------------------------------------------
#
#     "Is this one of the document types VIGILOX handles?"
#
# It is a different question from the one
# document_quality_service answers, which is:
#
#     "Can this image be read reliably?"
#
# The two are kept apart on purpose. A blurry Guard Licence is
# still a Guard Licence. A perfectly sharp receipt is still not
# a supported document. Neither question is allowed to answer
# the other.
#
#
# WHY THERE IS NO CLASSIFIER HERE
# ----------------------------------------------------------
#
# Classification is already done: the extraction schema's
# document_type is a Literal that has always included
# "unknown", and DocumentAnomalyValidator has always raised
# UNKNOWN_DOCUMENT_TYPE as an ERROR when it is returned. So
# unsupported input already reached REVIEW_REQUIRED and could
# never be auto-accepted.
#
# This module does not add a second opinion about what the
# document is. It decides what to DO about an unclassified
# one, which is the part that was missing.
# ==========================================================

from __future__ import annotations


UNKNOWN_DOCUMENT_TYPE = "unknown"


SUPPORTED_DOCUMENT_TYPES = (
    "sia_badge",
    "id_card",
    "guard_license",
)


# Operator-facing names for the three supported types.
#
# Here rather than in the frontend because the API states them
# in the unsupported message, and one list cannot drift from
# itself.
SUPPORTED_DOCUMENT_LABELS = (
    "Security Guard License",
    "ID Card",
    "SIA Badge",
)


# ==========================================================
# OUTCOMES
# ==========================================================

# One of the three supported types.
OUTCOME_SUPPORTED = "SUPPORTED"


# Confidently not one of the three. A receipt, a random
# photograph, an unrelated credential, a blank page.
#
# Does not go to a human. There is nothing for a reviewer to
# correct on a receipt, and a queue full of receipts is how a
# reviewer stops reading carefully.
OUTCOME_UNSUPPORTED = "UNSUPPORTED"


# Could not be classified, AND the evidence for concluding
# "unsupported" is not trustworthy, because the image itself
# could not be read reliably.
#
# This one DOES go to a human. A severely degraded Guard
# Licence must not become confidently unsupported just because
# the classification evidence was weak.
OUTCOME_UNCLASSIFIED_NEEDS_REVIEW = (
    "UNCLASSIFIED_NEEDS_REVIEW"
)


OUTCOMES = (
    OUTCOME_SUPPORTED,
    OUTCOME_UNSUPPORTED,
    OUTCOME_UNCLASSIFIED_NEEDS_REVIEW,
)


# ==========================================================
# THE THIRD MACHINE DECISION
# ==========================================================
#
# review_decision["decision"] has carried two values:
#
#     AUTO_ACCEPT
#     REVIEW_REQUIRED
#
# There is a genuine third answer to "what did the machine
# decide to do with this?", and it is neither of those:
#
#     UNSUPPORTED_DOCUMENT
#
#
# WHY A THIRD VALUE RATHER THAN A FILTER
# ----------------------------------------------------------
#
# The alternative was to leave unsupported documents as
# REVIEW_REQUIRED and exclude them from the review queue with
# an extra predicate. That puts the same fact in two places
# and lets them disagree: the decision field would say a human
# is required while the queue says otherwise.
#
# The deciding evidence is that every existing query which
# keys on
#
#     review_decision->>'decision' = 'REVIEW_REQUIRED'
#
# gets the correct behaviour from a third value with NO change
# at all:
#
#     ReviewQueueRepository.get_review_queue
#     DocumentSummaryRepository
#         .count_pending_review_by_priority
#
# When the smallest possible change is "add a value and touch
# no queries", the value is the natural shape.
#
# AUTO_ACCEPT and REVIEW_REQUIRED keep their exact meanings.
# Nothing that was auto-accepted becomes unsupported, and
# nothing unsupported becomes auto-accepted. See
# apply_classification_to_review.
# ==========================================================

DECISION_AUTO_ACCEPT = "AUTO_ACCEPT"

DECISION_REVIEW_REQUIRED = "REVIEW_REQUIRED"

DECISION_UNSUPPORTED_DOCUMENT = (
    "UNSUPPORTED_DOCUMENT"
)


MACHINE_DECISIONS = (
    DECISION_AUTO_ACCEPT,
    DECISION_REVIEW_REQUIRED,
    DECISION_UNSUPPORTED_DOCUMENT,
)


# ==========================================================
# WHICH QUALITY FINDINGS BLOCK AN UNSUPPORTED CONCLUSION
# ==========================================================
#
# Only findings that mean "the text on this image could not be
# read reliably". If one of these is present, the reason
# classification failed may well be the photograph rather than
# the document, so "unsupported" is not a safe conclusion.
#
# ROTATION_CONCERN is deliberately NOT here. Phase 10.1
# measured that documents rotated a full 10 degrees still OCR:
# the finding fired on 63 of 63 rotated documents while the
# text was still read, and PaddleOCR runs with
# use_textline_orientation enabled. Skew is a print-quality
# note, not a reason to doubt a classification.
#
# The codes are strings rather than imports from
# document_quality_service so that this domain module stays
# free of service imports; the test suite asserts the two
# lists agree, which is what actually keeps them together.
# ==========================================================

READABILITY_IMPAIRING_QUALITY_CODES = frozenset(
    {
        "IMAGE_UNREADABLE",
        "IMAGE_BLURRY",
        "IMAGE_TOO_DARK",
        "IMAGE_OVEREXPOSED",
        "IMAGE_TOO_SMALL",
    }
)


UNSUPPORTED_MESSAGE = (
    "VIGILOX could not reliably identify this file "
    "as one of the currently supported document "
    "types. No usable record was produced."
)


UNCLASSIFIED_NEEDS_REVIEW_MESSAGE = (
    "VIGILOX could not classify this document, and "
    "the image quality was too poor to rule out a "
    "supported document. A reviewer needs to look "
    "at it."
)


# ==========================================================
# CLASSIFY
# ==========================================================

def classify_outcome(
    *,
    document_type: str | None,
    quality_finding_codes=(),
    ocr_line_count: int = 0,
) -> str:

    """
    Decide the classification outcome for one processed
    document.

    Deterministic, and derived only from values the pipeline
    already produced: the extracted document_type, the Phase
    10.1 quality finding codes, and how many OCR lines were
    read. No model call, no heuristic over the image.


    THE RULE
    ------------------------------------------------------

        supported type
            -> SUPPORTED

        unknown, readability-impairing quality finding,
        AND at least one OCR line
            -> UNCLASSIFIED_NEEDS_REVIEW

        unknown, anything else
            -> UNSUPPORTED


    WHY OCR TEXT IS PART OF IT
    ------------------------------------------------------

    It is what separates the two cases the product must treat
    differently:

        A blank page, or a photograph of a wall, produces a
        quality finding AND no text. There is nothing for a
        reviewer to read, and routing it to a human creates
        work with no possible outcome. UNSUPPORTED.

        A dark or blurred Guard Licence produces a quality
        finding AND text -- degraded, partial, enough that
        something was printed there. A person looking at the
        image can resolve it. UNCLASSIFIED_NEEDS_REVIEW.


    THE KNOWN LIMITATION, STATED
    ------------------------------------------------------

    A sharp, well-lit image of a genuinely supported document
    that the extractor nonetheless fails to classify is called
    UNSUPPORTED and does not reach a reviewer.

    That is a real miss, and it is the cost of not filling the
    queue with receipts. Two things bound it: document-type
    accuracy measured 100% on the 63-document benchmark, so
    this is not an observed failure mode; and the record stays
    fully discoverable and reviewable through the Documents
    experience, so the miss is recoverable rather than silent.
    """

    normalized_type = (
        str(
            document_type
            or ""
        )
        .strip()
        .lower()
    )


    if normalized_type in SUPPORTED_DOCUMENT_TYPES:
        return OUTCOME_SUPPORTED


    # An empty or unrecognised document_type is treated
    # exactly like "unknown". Being lenient here rather than
    # raising means a future extraction value cannot take the
    # pipeline down, and the conservative branch below is the
    # one it lands in.

    codes = {
        str(
            code
        )
        .strip()
        .upper()
        for code in (
            quality_finding_codes
            or ()
        )
    }


    readability_impaired = bool(
        codes
        & READABILITY_IMPAIRING_QUALITY_CODES
    )


    if (
        readability_impaired
        and int(
            ocr_line_count
            or 0
        ) > 0
    ):
        return (
            OUTCOME_UNCLASSIFIED_NEEDS_REVIEW
        )


    return OUTCOME_UNSUPPORTED


# ==========================================================
# APPLY TO THE MACHINE REVIEW DECISION
# ==========================================================

def apply_classification_to_review(
    review_result: dict,
    outcome: str,
) -> dict:

    """
    Record an UNSUPPORTED outcome in the machine review
    decision.

    Returns a new dict; the input is not modified.


    THIS FUNCTION HAS EXACTLY ONE EFFECT
    ------------------------------------------------------

        REVIEW_REQUIRED  ->  UNSUPPORTED_DOCUMENT

    and only when the outcome is UNSUPPORTED. Every other
    input is returned unchanged.

    It cannot produce AUTO_ACCEPT. There is no branch that
    writes that value, so an unsupported document cannot
    become auto-accepted no matter what the review service
    decided -- and the release-critical invariant that false
    auto-accepts must not increase holds by construction
    rather than by enumerating cases.

    The guard against AUTO_ACCEPT on the way in is
    unreachable in the current pipeline, because
    document_type == "unknown" always raises
    UNKNOWN_DOCUMENT_TYPE as an ERROR and decide() cannot
    return AUTO_ACCEPT with an error present. It is here so
    that a future change to either service fails safe --
    leaving the decision alone -- instead of quietly turning
    an accepted document into an unsupported one.

    ReviewDecisionService.decide() is not touched. Its
    semantics are audited and tested; this runs after it.
    """

    if outcome != OUTCOME_UNSUPPORTED:
        return dict(
            review_result
        )


    decision = (
        str(
            review_result.get(
                "decision"
            )
            or ""
        )
        .strip()
        .upper()
    )


    if decision != DECISION_REVIEW_REQUIRED:
        return dict(
            review_result
        )


    unsupported = dict(
        review_result
    )

    unsupported["decision"] = (
        DECISION_UNSUPPORTED_DOCUMENT
    )

    # No reviewer is being asked for anything, so there is no
    # reviewer priority. The issues and reason codes are kept
    # verbatim: UNKNOWN_DOCUMENT_TYPE is why this happened and
    # deleting it would remove the explanation.
    unsupported["review_required"] = False

    unsupported["priority"] = "NONE"

    return unsupported


# ==========================================================
# DESCRIBE, FOR READ PATHS
# ==========================================================

def describe_classification(
    *,
    document_type: str | None,
    machine_decision: str | None,
) -> dict:

    """
    Derive the classification outcome from two values every
    read path already has.

    WHY DERIVED RATHER THAN STORED
    ------------------------------------------------------

    The outcome is a function of document_type and the machine
    decision, both of which are already persisted and already
    loaded by the document list query as well as the detail
    query. Storing it again in a new column would create a
    second copy that can disagree with the decision it was
    derived from, and would need a migration to say nothing
    new.

    This is the same pattern as
    FinalRecordService.resolve_final_status: one rule,
    expressed once, used by the list and the detail path, so
    the two cannot report different things about the same
    document.

    Rows written before Phase 10.2 derive correctly. An
    unclassified document then had decision REVIEW_REQUIRED,
    which maps to UNCLASSIFIED_NEEDS_REVIEW -- exactly what it
    was: unclassified and waiting for a human.

    usable is deliberately absent. FinalRecordService owns
    is_usable and remains the only authority on it.
    """

    normalized_type = (
        str(
            document_type
            or ""
        )
        .strip()
        .lower()
    )

    normalized_decision = (
        str(
            machine_decision
            or ""
        )
        .strip()
        .upper()
    )


    if normalized_type in SUPPORTED_DOCUMENT_TYPES:

        return {
            "outcome":
                OUTCOME_SUPPORTED,

            "document_type":
                normalized_type,

            "supported":
                True,

            "retryable":
                False,

            "supported_document_types":
                list(
                    SUPPORTED_DOCUMENT_LABELS
                ),

            "message":
                None,
        }


    if (
        normalized_decision
        == DECISION_UNSUPPORTED_DOCUMENT
    ):

        outcome = OUTCOME_UNSUPPORTED

        message = UNSUPPORTED_MESSAGE


    else:

        outcome = (
            OUTCOME_UNCLASSIFIED_NEEDS_REVIEW
        )

        message = (
            UNCLASSIFIED_NEEDS_REVIEW_MESSAGE
        )


    return {
        "outcome":
            outcome,

        "document_type":
            UNKNOWN_DOCUMENT_TYPE,

        "supported":
            False,

        # Reprocessing the same bytes runs the same
        # deterministic classification and reaches the same
        # answer. Presenting a retry would promise a different
        # result that cannot happen.
        "retryable":
            False,

        "supported_document_types":
            list(
                SUPPORTED_DOCUMENT_LABELS
            ),

        "message":
            message,
    }
