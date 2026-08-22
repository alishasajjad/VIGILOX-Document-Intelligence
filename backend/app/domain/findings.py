# ==========================================================
# FINDING NORMALIZATION
# PHASE 10.6
# ==========================================================
#
# One shared envelope for everything the pipeline can say
# about a document, derived from what is already persisted.
#
#
# WHAT THIS IS FOR
# ----------------------------------------------------------
# Five producers emit findings, and before this module they
# emitted five different shapes:
#
#   DocumentAnomalyValidator
#       {code, severity, field, message}
#
#   DateLogicalValidator.logical_issues
#       {code, field, message}          -- no severity
#
#   DateLogicalValidator.expiry
#       {value, status, days_until_expiry}
#       a status, not a finding at all
#
#   DocumentQualityService
#       {code, severity, message, metric_name,
#        measured_value, threshold}
#
#   EvidenceValidator
#       a flat string
#       "FULL_NAME_EVIDENCE_MISMATCH"
#       "EXPIRY_DATE_INVALID_SOURCE_LINE_ID:L9"
#       no severity, no message, field encoded in a prefix
#
# The interface had to understand all five. It did, by
# reimplementing the fifth one in JavaScript: vocabulary.js
# carried its own list of field names and its own list of flag
# suffixes and recovered the structure by longest-prefix
# matching. That is a second, independent definition of what
# the Python validator emits, in a language the validator
# cannot be tested against -- the same shape of problem as the
# duplicated critical-field list that PHASE 10.5 found hiding
# a real critical-field error.
#
# So the structure moves here, beside the code that produces
# it, and the browser keeps only human labels.
#
#
# WHAT THIS IS NOT FOR
# ----------------------------------------------------------
# This module does not decide anything. It has no routing
# effect, no severity of its own to assign, and nothing it
# returns is written back to the database.
#
# It normalizes PRESENTATION. Authority stays where it already
# is: ReviewDecisionService decides, quality_review_policy
# escalates, and the severities are the ones those services
# already attached.
#
#
# NO SCORE
# ----------------------------------------------------------
# The only derived value is highest_severity, which is the
# maximum of the severities the producers actually assigned.
# It is a severity, not a number, it can be explained in one
# sentence, and it cannot be mistaken for a percentage.
#
# There is deliberately no risk score, no fraud probability,
# no tamper score, and no document-level confidence. Every one
# of those would be a number this system has no evidence for.
# PHASE 10.5 measured what happens when a number looks more
# certain than it is.
#
#
# DATES ARE NOT COUNTED TWICE
# ----------------------------------------------------------
# The single most important thing to understand before reading
# the code: DocumentAnomalyValidator is ALREADY a normalizer.
# It re-emits every date logical issue with an ERROR severity
# attached, and it converts the expiry STATUS into
# DOCUMENT_EXPIRED / DOCUMENT_EXPIRING_SOON warnings.
#
# So a date problem is already present in
# anomaly_validation.issues. Walking date_validation as a
# sixth source would list it twice, and because reason_codes
# is built from the anomaly issues, the duplicate would look
# like a second independent reason to distrust the document.
#
# This module therefore reads the anomaly issues as the
# authoritative set and uses date_validation only to ENRICH
# them -- an expiry finding gets the actual date and the day
# count attached as detail. Nothing is re-derived and nothing
# is duplicated.
#
#
# CLASSIFICATION AND DUPLICATES ARE NOT FINDINGS
# ----------------------------------------------------------
# Neither is accepted as an input here, on purpose.
#
# An unsupported document is a classification outcome: the
# system read it correctly and it is not a document this
# product handles. Flattening that into an ERROR finding would
# put it back into ordinary review-queue semantics, which
# PHASE 10.2 deliberately took it out of.
#
# An exact duplicate is a source-identity outcome: the same
# bytes arrived twice. Flattening that into a finding would
# put it next to anomalies and expiry problems, and the
# nearest available reading of "anomaly" is suspicion. Two
# uploads of one photograph is not fraud, not tampering and
# not evidence of either.
#
# Both keep their own blocks on the read path.
# test_phase10_finding_normalization asserts that no code from
# either one can appear in this view.
# ==========================================================

from __future__ import annotations


# ==========================================================
# SEVERITY
# ==========================================================
#
# The vocabulary the producers already use. Restated here
# rather than imported, because a domain module importing a
# service would invert the dependency -- and the test asserts
# these are the same three strings DocumentQualityService
# defines and DocumentAnomalyValidator emits, so they cannot
# drift apart quietly.
# ==========================================================

SEVERITY_ERROR = "ERROR"

SEVERITY_WARNING = "WARNING"

SEVERITY_INFO = "INFO"


SEVERITIES = (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    SEVERITY_INFO,
)


# Higher is worse. Used only to pick a maximum and to order
# the list for display.
SEVERITY_RANK = {
    SEVERITY_INFO: 1,
    SEVERITY_WARNING: 2,
    SEVERITY_ERROR: 3,
}


# ==========================================================
# CATEGORY
# ==========================================================
#
# What KIND of question a finding answers. This is the axis
# the interface groups on, and the reason the categories are
# not merged: they are not comparable.
#
#   EVIDENCE    Was this value actually read off the page?
#   DATE        Do the dates hold together?
#   EXPIRY      Is the document still in date?
#   QUALITY     Can the image be read at all?
#   ANOMALY     Is the extracted record internally consistent?
#
# QUALITY is kept apart from the rest for the reason PHASE
# 10.1 established: a blurred photograph of a valid licence is
# a different statement from a licence whose data contradicts
# itself, and collapsing them loses the distinction that makes
# either one actionable.
# ==========================================================

CATEGORY_EVIDENCE = "EVIDENCE"

CATEGORY_DATE = "DATE"

CATEGORY_EXPIRY = "EXPIRY"

CATEGORY_QUALITY = "QUALITY"

CATEGORY_ANOMALY = "ANOMALY"


CATEGORIES = (
    CATEGORY_QUALITY,
    CATEGORY_EVIDENCE,
    CATEGORY_ANOMALY,
    CATEGORY_DATE,
    CATEGORY_EXPIRY,
)


# Display order within one severity. Not an importance
# ranking -- severity already carries importance. This exists
# so the same document always renders in the same order.
CATEGORY_ORDER = {
    name: index
    for index, name in enumerate(
        CATEGORIES
    )
}


# ==========================================================
# SOURCE
# ==========================================================
#
# Which persisted payload a finding was read out of. Kept in
# the envelope so that anything surprising in the interface
# can be traced back to a stored value rather than guessed at.
# ==========================================================

SOURCE_ANOMALY = "anomaly_validation"

SOURCE_QUALITY = "quality"

SOURCE_EVIDENCE = "evidence_flags"


# ==========================================================
# CODE TO CATEGORY
# ==========================================================
#
# The anomaly validator emits one flat list containing three
# different kinds of finding, because it absorbed the date
# validator's output. Categorising by code is how they are
# told apart again without changing the validator.
# ==========================================================

# DateLogicalValidator emits these. test_phase10_finding_
# normalization reads the validator's source and asserts this
# tuple is exactly the set of codes it can produce, so a new
# date rule cannot silently land in the wrong category.
DATE_LOGICAL_CODES = (
    "FUTURE_DATE_OF_BIRTH",
    "FUTURE_ISSUE_DATE",
    "EXPIRY_BEFORE_ISSUE_DATE",
    "DOB_AFTER_ISSUE_DATE",
    "DOB_AFTER_EXPIRY_DATE",
)


# Generated per date field, so it is matched by suffix:
# EXPIRY_DATE_INVALID_FORMAT, DATE_OF_BIRTH_INVALID_FORMAT.
DATE_FORMAT_SUFFIX = "_INVALID_FORMAT"


# Derived by the anomaly validator from the expiry STATUS
# rather than from a logical rule, which is why they are their
# own category: they describe the document's standing, not a
# contradiction in it.
EXPIRY_CODES = (
    "DOCUMENT_EXPIRED",
    "DOCUMENT_EXPIRING_SOON",
)


def category_for_code(
    code: str | None,
) -> str:

    """
    The category of an anomaly-validator code.

    Anything unrecognised falls to ANOMALY, which is where an
    anomaly-validator finding belongs by default. A new code
    therefore appears in the interface correctly grouped-ish
    and never disappears -- the failure mode is a slightly
    wrong heading, not a missing finding.
    """

    if not code:
        return CATEGORY_ANOMALY

    name = str(
        code
    ).upper()

    if name in EXPIRY_CODES:
        return CATEGORY_EXPIRY

    if name in DATE_LOGICAL_CODES:
        return CATEGORY_DATE

    if name.endswith(
        DATE_FORMAT_SUFFIX
    ):
        return CATEGORY_DATE

    return CATEGORY_ANOMALY


# ==========================================================
# EVIDENCE FLAGS
# ==========================================================
#
# EvidenceValidator returns strings. This is where they
# regain their structure.
#
# The two lists below are what vocabulary.js used to carry.
# They are asserted against the validator itself:
#
#   EVIDENCE_FIELDS  == EvidenceValidator.VALIDATED_FIELDS
#   EVIDENCE_KINDS   == every flag suffix the validator's
#                       source can actually emit
#
# The second assertion reads the source rather than the class,
# because the suffixes are written inline at the point each
# flag is raised. Reading the source is what makes it
# impossible to add a seventh kind without this parser
# learning about it.
# ==========================================================

EVIDENCE_FIELDS = (
    "full_name",
    "licence_number",
    "id_number",
    "expiry_date",
    "date_of_birth",
    "issue_date",
    "issuer",
)


EVIDENCE_KINDS = (
    "NO_EVIDENCE",
    "NO_VALID_EVIDENCE",
    "EVIDENCE_MISMATCH",
    "CONTEXT_MISSING",
    "INVALID_SOURCE_LINE_ID",
    "INVALID_EVIDENCE_TEXT",
)


# The sentence shown for each kind. The interface keeps a
# short title for each one; this is the explanation, and it is
# authored here so that an evidence finding carries a message
# like every other finding in the envelope does.
EVIDENCE_MESSAGES = {

    "NO_EVIDENCE":
        (
            "The value was extracted without naming any "
            "OCR line as its source."
        ),

    "NO_VALID_EVIDENCE":
        (
            "Every OCR line cited for this value turned out "
            "to be unusable."
        ),

    "EVIDENCE_MISMATCH":
        (
            "The extracted value does not appear in the OCR "
            "text it cites."
        ),

    "CONTEXT_MISSING":
        (
            "The cited OCR text does not contain the label "
            "this field is normally printed with."
        ),

    "INVALID_SOURCE_LINE_ID":
        (
            "The value cites an OCR line that is not part of "
            "this document's OCR output."
        ),

    "INVALID_EVIDENCE_TEXT":
        (
            "The cited OCR line carries no readable text."
        ),
}


# Kinds that name a specific OCR line in the part of the flag
# after the colon. The rest carry no detail.
EVIDENCE_KINDS_WITH_LINE_ID = (
    "INVALID_SOURCE_LINE_ID",
    "INVALID_EVIDENCE_TEXT",
)


def parse_evidence_flag(
    flag: str,
) -> dict:

    """
    Recover the structure of one evidence flag.

    Returns:

        {
            "flag":            the string as received,
            "known":           parsed against the vocabulary,
            "field":           field name, or None,
            "kind":            flag kind, or None,
            "source_line_id":  cited line, or None,
        }

    Field and kind are recovered by matching the known field
    names and the known kinds, NOT by splitting on
    underscores: every field name contains underscores itself,
    so splitting would attribute DATE_OF_BIRTH_NO_EVIDENCE to
    a field called "date".

    An unparseable flag comes back known=False with the
    original string intact. It is never dropped and never
    guessed at -- an unrecognised flag is still a real
    statement by the validator, and silently discarding it
    would be the worst available outcome.
    """

    raw = (
        ""
        if flag is None
        else str(
            flag
        )
    )

    head, _, tail = raw.partition(
        ":"
    )

    body = head.upper()

    detail = (
        tail
        if tail
        else None
    )

    match = None

    for field in EVIDENCE_FIELDS:

        prefix = (
            field.upper()
            + "_"
        )

        if not body.startswith(
            prefix
        ):
            continue

        kind = body[
            len(prefix):
        ]

        if kind not in EVIDENCE_KINDS:
            continue

        # Longest field prefix wins. No two current field
        # names nest inside each other, but depending on that
        # would be a trap for whoever adds the next field.
        if (
            match is None
            or len(prefix) > match[0]
        ):
            match = (
                len(prefix),
                field,
                kind,
            )

    if match is None:

        return {
            "flag": raw,
            "known": False,
            "field": None,
            "kind": None,
            "source_line_id": None,
        }

    _, field_name, kind_name = match

    return {
        "flag": raw,
        "known": True,
        "field": field_name,
        "kind": kind_name,

        "source_line_id": (
            detail
            if kind_name
            in EVIDENCE_KINDS_WITH_LINE_ID
            else None
        ),
    }


# ==========================================================
# THE ENVELOPE
# ==========================================================
#
# Shared keys, always present:
#
#   code             the producer's own code
#   category         one of CATEGORIES
#   severity         the producer's severity, or None
#   message          the producer's sentence
#   field            field name, or None
#   source           which persisted payload it came from
#   affects_routing  whether it is in reason_codes
#   detail           domain-specific, or None
#
# SEVERITY MAY BE None, AND THAT IS NOT A GAP
# ----------------------------------------------------------
# Evidence flags have no severity. The validator does not
# assign one, and inventing one here would be this module
# asserting a judgement no measurement supports.
#
# What actually happens to an evidence problem is that
# ConfidenceService turns it into a field status and the
# anomaly validator raises CRITICAL_FIELD_NOT_TRUSTED or
# EXTRACTED_FIELD_INVALID_EVIDENCE -- and THOSE carry the
# authoritative severity. So the graded consequence of an
# evidence problem is already in the list, next to the
# ungraded detail explaining it.
#
# severity=None therefore reads as "this is supporting detail
# for a finding that is graded elsewhere", which is exactly
# what it is.
#
#
# DETAIL IS NOT FLATTENED
# ----------------------------------------------------------
# A quality finding without its measured value and threshold
# is an opinion. An expiry finding without the date and the
# day count sends the reader back to another panel. An
# evidence finding without the cited line ID cannot be
# checked against the page.
#
# So the envelope carries the shared keys AND the
# domain-specific ones. Uniformity was never the goal;
# consistency of the shared parts was.
# ==========================================================

def _finding(
    *,
    code,
    category,
    severity,
    message,
    field,
    source,
    affects_routing,
    detail=None,
) -> dict:

    normalized_severity = None

    if severity is not None:

        text = str(
            severity
        ).strip().upper()

        if text:
            normalized_severity = text

    return {

        "code": (
            None
            if code is None
            else str(
                code
            )
        ),

        "category": category,

        # As reported, upper-cased. An unrecognised value is
        # preserved rather than remapped: see the summary,
        # which counts it and refuses to rank it.
        "severity": normalized_severity,

        "message": (
            None
            if message is None
            else str(
                message
            )
        ),

        "field": field,

        "source": source,

        "affects_routing": affects_routing,

        "detail": detail,
    }


def _sort_key(
    finding: dict,
) -> tuple:

    """
    Deterministic order: worst first.

    Severity descending, then category, then code, then field.
    An unrated finding sorts after every rated one, so the
    ungraded evidence detail never appears above a graded
    error.

    This is what gives the interface its hierarchy without the
    interface having to sort anything itself.
    """

    rank = SEVERITY_RANK.get(
        finding.get(
            "severity"
        ),
        0,
    )

    return (
        -rank,

        CATEGORY_ORDER.get(
            finding.get(
                "category"
            ),
            len(
                CATEGORIES
            ),
        ),

        finding.get(
            "code"
        )
        or "",

        finding.get(
            "field"
        )
        or "",
    )


# ==========================================================
# NORMALIZE
# ==========================================================

def normalize_findings(
    *,
    anomaly_validation: dict | None = None,
    quality: dict | None = None,
    evidence_flags=None,
    date_validation: dict | None = None,
    review_decision: dict | None = None,
) -> dict:

    """
    One view over everything the pipeline found.

    Every argument is a payload already persisted on the
    analysis row, so this adds no query and no stored column,
    and the view cannot disagree with the raw payloads beside
    it.

    date_validation is used ONLY to enrich expiry findings
    with the date and the day count. Its logical issues are
    already present in anomaly_validation, and reading them
    again would list every date problem twice.

    review_decision is used ONLY to answer whether a finding
    is in reason_codes. That is read from the stored decision
    rather than re-derived, so this module cannot come to a
    different conclusion than the service that actually
    decided.
    """

    findings: list[dict] = []


    # ------------------------------------------------------
    # WHAT ACTUALLY DROVE ROUTING
    # ------------------------------------------------------
    # reason_codes as the decision service and the quality
    # policy left it. None means no decision is stored, which
    # is not the same as "nothing affected routing" -- so
    # affects_routing stays None for the whole document rather
    # than claiming False.
    # ------------------------------------------------------

    reason_codes = None

    if isinstance(
        review_decision,
        dict,
    ):
        reason_codes = {
            str(
                code
            )
            for code in (
                review_decision.get(
                    "reason_codes"
                )
                or []
            )
        }


    def routing_effect(
        code,
    ):

        if reason_codes is None:
            return None

        return str(
            code
        ) in reason_codes


    # ------------------------------------------------------
    # EXPIRY DETAIL, FOR ENRICHMENT ONLY
    # ------------------------------------------------------

    expiry = {}

    if isinstance(
        date_validation,
        dict,
    ):
        expiry = (
            date_validation.get(
                "expiry"
            )
            or {}
        )


    # ------------------------------------------------------
    # 1. ANOMALY VALIDATOR
    #    the authoritative set, and the only one that has
    #    already absorbed the date findings
    # ------------------------------------------------------

    anomaly_issues = []

    if isinstance(
        anomaly_validation,
        dict,
    ):
        anomaly_issues = (
            anomaly_validation.get(
                "issues"
            )
            or []
        )


    for issue in anomaly_issues:

        if not isinstance(
            issue,
            dict,
        ):
            continue

        code = issue.get(
            "code"
        )

        category = category_for_code(
            code
        )

        detail = None

        # An expiry finding says the document is out of date;
        # the date and the day count say by how much, and
        # they are already computed by the date validator
        # against its own reference date. Attaching them here
        # means the reader does not have to hold two panels
        # in their head, and means nothing recomputes "soon"
        # a second way.
        if (
            category == CATEGORY_EXPIRY
            and expiry
        ):
            detail = {

                "expiry_date":
                    expiry.get(
                        "value"
                    ),

                "expiry_status":
                    expiry.get(
                        "status"
                    ),

                "days_until_expiry":
                    expiry.get(
                        "days_until_expiry"
                    ),
            }

        findings.append(
            _finding(
                code=code,
                category=category,

                severity=issue.get(
                    "severity"
                ),

                message=issue.get(
                    "message"
                ),

                field=issue.get(
                    "field"
                ),

                source=SOURCE_ANOMALY,

                affects_routing=(
                    routing_effect(
                        code
                    )
                ),

                detail=detail,
            )
        )


    # ------------------------------------------------------
    # 2. IMAGE QUALITY
    # ------------------------------------------------------
    # quality is None for every document analysed before
    # PHASE 10.1. That is NOT ASSESSED, and it is reported as
    # a separate fact below rather than as an empty finding
    # list, because an empty list is the interface claiming
    # the image was measured and found clean.
    # ------------------------------------------------------

    quality_assessed = isinstance(
        quality,
        dict,
    )

    quality_error = None

    if quality_assessed:

        quality_error = quality.get(
            "error"
        )

        for finding in (
            quality.get(
                "findings"
            )
            or []
        ):

            if not isinstance(
                finding,
                dict,
            ):
                continue

            code = finding.get(
                "code"
            )

            findings.append(
                _finding(
                    code=code,
                    category=CATEGORY_QUALITY,

                    severity=finding.get(
                        "severity"
                    ),

                    message=finding.get(
                        "message"
                    ),

                    # Quality measures the photograph, not a
                    # field. There is no field to name, and
                    # naming one would be wrong.
                    field=None,

                    source=SOURCE_QUALITY,

                    affects_routing=(
                        routing_effect(
                            code
                        )
                    ),

                    # The measurement. This is what makes a
                    # quality finding checkable instead of an
                    # assertion, so it is never dropped.
                    detail={

                        "metric_name":
                            finding.get(
                                "metric_name"
                            ),

                        "measured_value":
                            finding.get(
                                "measured_value"
                            ),

                        "threshold":
                            finding.get(
                                "threshold"
                            ),
                    },
                )
            )


    # ------------------------------------------------------
    # 3. EVIDENCE
    # ------------------------------------------------------
    # Ungraded on purpose. See the envelope notes above.
    # ------------------------------------------------------

    for flag in (
        evidence_flags
        or []
    ):

        parsed = parse_evidence_flag(
            flag
        )

        kind = parsed[
            "kind"
        ]

        # The code is the flag with any cited line stripped
        # off, so it stays greppable against the validator
        # that emitted it.
        code = (
            parsed[
                "flag"
            ].partition(
                ":"
            )[0]
            or None
        )

        detail = {
            "flag":
                parsed[
                    "flag"
                ],

            "kind":
                kind,

            "source_line_id":
                parsed[
                    "source_line_id"
                ],

            "known":
                parsed[
                    "known"
                ],
        }

        findings.append(
            _finding(
                code=code,
                category=CATEGORY_EVIDENCE,

                # No severity exists to report. None, not a
                # guess.
                severity=None,

                message=(
                    EVIDENCE_MESSAGES.get(
                        kind
                    )
                    if kind
                    else None
                ),

                field=parsed[
                    "field"
                ],

                source=SOURCE_EVIDENCE,

                affects_routing=(
                    routing_effect(
                        code
                    )
                ),

                detail=detail,
            )
        )


    findings.sort(
        key=_sort_key
    )


    # ------------------------------------------------------
    # SUMMARY
    # ------------------------------------------------------
    # Counts of what the producers said, plus one derived
    # value that is a severity rather than a score.
    # ------------------------------------------------------

    counts = {
        name: 0
        for name in SEVERITIES
    }

    unrated_count = 0

    unrecognised: list[str] = []

    for finding in findings:

        severity = finding[
            "severity"
        ]

        if severity is None:
            unrated_count += 1
            continue

        if severity in counts:
            counts[severity] += 1
            continue

        # A severity string outside the vocabulary. It is
        # counted and named, and it is NOT ranked.
        #
        # Ranking it highest would let one typo turn every
        # document red. Ranking it lowest would hide it. So
        # highest_severity is computed over recognised values
        # only, and the unrecognised ones are reported
        # separately where they stay visible.
        if severity not in unrecognised:
            unrecognised.append(
                severity
            )


    highest = None

    for finding in findings:

        severity = finding[
            "severity"
        ]

        if severity not in SEVERITY_RANK:
            continue

        if (
            highest is None
            or SEVERITY_RANK[severity]
            > SEVERITY_RANK[highest]
        ):
            highest = severity


    present_categories = [
        name
        for name in CATEGORIES
        if any(
            finding["category"] == name
            for finding in findings
        )
    ]


    routing_count = sum(
        1
        for finding in findings
        if finding["affects_routing"]
        is True
    )


    return {

        "findings": findings,

        "total": len(
            findings
        ),

        "counts": counts,

        "unrated_count": unrated_count,

        "unrecognised_severities": sorted(
            unrecognised
        ),

        # The one derived value in this module, and it is a
        # severity. Highest of the severities the producers
        # assigned, or None when nothing graded fired.
        "highest_severity": highest,

        "categories": present_categories,

        # NOT ASSESSED and ASSESSED-AND-CLEAN are different
        # statements and stay different here. False means
        # nobody measured the image; True with no QUALITY
        # finding means it was measured and nothing fired.
        "quality_assessed": quality_assessed,

        "quality_error": quality_error,

        "routing_finding_count": routing_count,
    }
