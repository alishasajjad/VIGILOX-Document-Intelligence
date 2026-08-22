"""
==========================================================
PHASE 10.6 - FINDING NORMALIZATION
==========================================================

WHAT THIS SUITE IS PROTECTING
----------------------------------------------------------

  1. NOTHING IS COUNTED TWICE.
     DocumentAnomalyValidator already absorbs every date
     logical issue and turns the expiry status into warnings.
     A normalized view that also walked date_validation would
     list every date problem twice, and because reason_codes
     is built from the anomaly issues, the duplicate would
     read as a second independent reason to distrust the
     document.

  2. NOTHING IS INVENTED.
     No severity is assigned that a producer did not assign.
     No risk score, fraud probability, tamper score or
     document-level confidence exists. The only derived value
     is the maximum of the severities already present.

  3. NOTHING IS LOST.
     A quality finding keeps its measured value and
     threshold. An expiry finding keeps the date and the day
     count. An evidence finding keeps the OCR line it cites.
     An unrecognised flag or an unrecognised severity is
     still reported. Uniformity was never the goal.

  4. UNSUPPORTED AND DUPLICATE ARE NOT FINDINGS.
     An unsupported document is a classification outcome and
     an exact duplicate is a source-identity outcome. Neither
     can appear in this list, because "anomaly" reads as
     suspicion and two uploads of one photograph is not
     evidence of anything.

  5. ONE DEFINITION, NOT TWO.
     Evidence-flag structure used to be reimplemented in
     vocabulary.js -- its own field list, its own flag
     vocabulary, its own prefix matching. That is the same
     shape of problem PHASE 10.5 found in the duplicated
     critical-field list, where a definitional gap hid a real
     critical-field error. The structure now lives beside the
     validator that emits it, and this suite asserts the
     browser and the backend agree.

  6. NOT ASSESSED IS NOT NO PROBLEMS.
     quality=None and quality={findings: []} stay
     distinguishable through normalization.


WHY THE DRIFT ASSERTIONS READ SOURCE
----------------------------------------------------------
Three of the definitions this module parses against are
written as inline literals in the services that emit them --
the evidence flag suffixes, the date logical codes. There is
no constant to import. So the assertions read the source and
extract the literals, which is what makes it impossible to
add a seventh evidence kind or a sixth date rule without this
suite noticing.

Each extractor carries a self-check proving it found anything
at all, because an extractor that silently matches nothing
would make every one of these assertions pass for the wrong
reason.


NO EXTERNAL DEPENDENCIES
----------------------------------------------------------
No PaddleOCR and no Groq. The real evidence, confidence, date
and anomaly validators all run against hand-built extractions
and hand-built OCR lines, because the property under test is
how their outputs combine, and a faked validator output would
prove nothing about that.

PostgreSQL IS used for the read-path test, because "the
detail endpoint returns this alongside the raw payloads" is a
statement about the application, not about a function.
"""

import ast
import json
import re
import shutil
import subprocess
import sys
import uuid

from datetime import date, timedelta
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


from backend.app.domain import findings as findings_module  # noqa: E402

from backend.app.domain.findings import (  # noqa: E402
    CATEGORIES,
    CATEGORY_ANOMALY,
    CATEGORY_DATE,
    CATEGORY_EVIDENCE,
    CATEGORY_EXPIRY,
    CATEGORY_QUALITY,
    DATE_LOGICAL_CODES,
    EVIDENCE_FIELDS,
    EVIDENCE_KINDS,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    SOURCE_ANOMALY,
    SOURCE_EVIDENCE,
    SOURCE_QUALITY,
    normalize_findings,
    parse_evidence_flag,
)

from backend.app.domain.classification import (  # noqa: E402
    DECISION_UNSUPPORTED_DOCUMENT,
)

from backend.app.domain.duplicates import (  # noqa: E402
    DUPLICATE_DOCUMENT,
    DUPLICATE_IN_PROGRESS,
)

from backend.app.domain.schemas import (  # noqa: E402
    DocumentExtraction,
)

from backend.app.services import (  # noqa: E402
    document_quality_service as quality_module,
)

from backend.app.services.confidence_service import (  # noqa: E402
    ConfidenceService,
)

from backend.app.services.date_logical_validator import (  # noqa: E402
    DateLogicalValidator,
)

from backend.app.services.document_anomaly_validator import (  # noqa: E402
    DocumentAnomalyValidator,
)

from backend.app.services.evidence_validator import (  # noqa: E402
    EvidenceValidator,
)

from backend.app.services.review_decision_service import (  # noqa: E402
    ReviewDecisionService,
)


# ==========================================================
# ASSERTIONS
# ==========================================================

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
# READING A PRODUCER'S SOURCE
# ==========================================================
#
# Three of the definitions this module parses against are
# written as inline literals in the service that emits them.
# There is no constant to import, so the drift assertions
# read the source and extract the literals.
# ==========================================================

def source_of(
    producer,
) -> str:

    path = (
        PROJECT_ROOT
        / (
            producer.__module__.replace(
                ".",
                "/",
            )
            + ".py"
        )
    )

    assert_true(
        path.exists(),
        (
            f"Cannot locate the source of "
            f"{producer.__name__} at {path}. The drift "
            f"assertions depend on reading it."
        ),
    )

    return path.read_text(
        encoding="utf-8"
    )


# ==========================================================
# BUILDERS
# ==========================================================

def field(
    value=None,
    line_ids=(),
):

    return {
        "value": value,

        "source_line_ids": list(
            line_ids
        ),
    }


def extraction(
    document_type="guard_license",
    **overrides,
):

    payload = {
        "document_type": document_type,

        "full_name": field(),
        "licence_number": field(),
        "id_number": field(),
        "expiry_date": field(),
        "date_of_birth": field(),
        "issue_date": field(),
        "issuer": field(),
    }

    payload.update(
        overrides
    )

    return DocumentExtraction(
        **payload
    )


def ocr_line(
    line_id,
    text,
    confidence=0.99,
):

    # line_id, not id. OCRService emits line_id and both the
    # evidence validator and the confidence service look it up
    # by that key -- a fixture using anything else falls back
    # to the legacy positional convention, silently shifts
    # every citation by one, and produces a document where
    # every field mismatches its evidence. Which looks like a
    # working fixture until you read what it asserted.
    return {
        "line_id": line_id,
        "text": text,
        "confidence": confidence,

        "bbox": [
            0,
            0,
            10,
            10,
        ],
    }


def issue(
    code,
    severity=SEVERITY_ERROR,
    field_name=None,
    message="Something happened.",
):

    return {
        "code": code,
        "severity": severity,
        "field": field_name,
        "message": message,
    }


def quality_finding(
    code="IMAGE_BLURRY",
    severity=SEVERITY_WARNING,
    metric_name="laplacian_variance",
    measured_value=41.2,
    threshold=60.0,
    message="The image is blurred.",
):

    return {
        "code": code,
        "severity": severity,
        "message": message,
        "metric_name": metric_name,
        "measured_value": measured_value,
        "threshold": threshold,
    }


def quality_payload(
    findings=(),
    error=None,
):

    return {
        "metrics": {
            "laplacian_variance": 41.2,
        },

        "findings": list(
            findings
        ),

        "highest_severity": None,

        "error": error,
    }


def by_code(
    result,
):

    grouped = {}

    for entry in result["findings"]:

        grouped.setdefault(
            entry["code"],
            [],
        ).append(
            entry
        )

    return grouped


# ==========================================================
# TEST 1 - ONE DEFINITION, NOT TWO
# ==========================================================

def test_definitions_have_one_source():

    section(
        "TEST 1 - THE DEFINITIONS THIS PARSER USES ARE THE "
        "ONES THE PRODUCERS USE"
    )


    # ------------------------------------------------------
    # EVIDENCE FIELDS
    # ------------------------------------------------------

    assert_equal(
        tuple(
            EVIDENCE_FIELDS
        ),
        tuple(
            EvidenceValidator.VALIDATED_FIELDS
        ),
        (
            "The evidence-flag parser must parse against the "
            "field list the validator actually iterates. A "
            "field present in one and missing from the other "
            "produces flags nothing can attribute."
        ),
    )

    ok(
        f"{len(EVIDENCE_FIELDS)} evidence fields, identical "
        f"to EvidenceValidator.VALIDATED_FIELDS"
    )


    # ------------------------------------------------------
    # EVIDENCE FLAG KINDS, READ OUT OF THE SOURCE
    # ------------------------------------------------------
    # The suffixes are inline string literals at each point a
    # flag is raised, so there is no constant to compare
    # against. Reading the source is the only assertion that
    # can actually fail when a seventh kind is added.
    # ------------------------------------------------------

    source_text = source_of(
        EvidenceValidator
    )

    emitted = {
        match
        for match in re.findall(
            r'"_([A-Z][A-Z_]*):?"',
            source_text,
        )
    }

    # SELF-CHECK. An extractor that matches nothing would make
    # the assertion below pass for the wrong reason, which is
    # the failure mode that matters most in a drift test.
    assert_true(
        len(
            emitted
        )
        >= 6,
        (
            "The flag-suffix extractor found "
            f"{len(emitted)} suffixes in the validator "
            "source. It is broken, not the validator -- an "
            "extractor that matches nothing makes every "
            "assertion below meaningless."
        ),
    )

    assert_equal(
        sorted(
            emitted
        ),
        sorted(
            EVIDENCE_KINDS
        ),
        (
            "Every flag suffix the evidence validator can "
            "emit must be known to the parser. An unknown "
            "suffix degrades to an unattributed finding with "
            "no message, which is how a real evidence "
            "problem becomes invisible."
        ),
    )

    ok(
        f"{len(EVIDENCE_KINDS)} evidence flag kinds, "
        f"extracted from the validator source: "
        f"{', '.join(sorted(EVIDENCE_KINDS))}"
    )


    # ------------------------------------------------------
    # DATE LOGICAL CODES, READ OUT OF THE SOURCE
    # ------------------------------------------------------

    date_source = source_of(
        DateLogicalValidator
    )

    literal_codes = {
        match
        for match in re.findall(
            r'"code":\s*(?:\n\s*)?"([A-Z][A-Z_]*)"',
            date_source,
        )
    }

    assert_true(
        len(
            literal_codes
        )
        >= 5,
        (
            "The date-code extractor found "
            f"{len(literal_codes)} codes. It is broken."
        ),
    )

    assert_equal(
        sorted(
            literal_codes
        ),
        sorted(
            DATE_LOGICAL_CODES
        ),
        (
            "Every literal code the date validator emits "
            "must be categorised as a DATE finding. One that "
            "is not falls through to ANOMALY and appears "
            "under the wrong heading."
        ),
    )

    # The per-field one is generated rather than literal, so
    # it is asserted separately.
    assert_true(
        findings_module.DATE_FORMAT_SUFFIX
        in date_source,
        (
            "The generated per-field date code suffix must "
            "still be what the validator produces."
        ),
    )

    ok(
        f"{len(DATE_LOGICAL_CODES)} date logical codes plus "
        f"the generated {findings_module.DATE_FORMAT_SUFFIX} "
        f"suffix, extracted from the validator source"
    )


    # ------------------------------------------------------
    # SEVERITY VOCABULARY
    # ------------------------------------------------------

    assert_equal(
        (
            SEVERITY_ERROR,
            SEVERITY_WARNING,
            SEVERITY_INFO,
        ),
        (
            quality_module.SEVERITY_ERROR,
            quality_module.SEVERITY_WARNING,
            quality_module.SEVERITY_INFO,
        ),
        (
            "The severity vocabulary is restated in the "
            "domain module to avoid a domain-to-service "
            "import. That is only safe while the two agree."
        ),
    )

    anomaly_source = source_of(
        DocumentAnomalyValidator
    )

    anomaly_severities = set(
        re.findall(
            r'severity=\(?\s*\n?\s*"([A-Z]+)"',
            anomaly_source,
        )
    ) | set(
        re.findall(
            r'severity="([A-Z]+)"',
            anomaly_source,
        )
    )

    assert_true(
        anomaly_severities,
        (
            "The anomaly-severity extractor found nothing. "
            "It is broken."
        ),
    )

    assert_true(
        anomaly_severities.issubset(
            set(
                findings_module.SEVERITIES
            )
        ),
        (
            "The anomaly validator emits a severity outside "
            "the normalizer's vocabulary: "
            f"{sorted(anomaly_severities)}. It would be "
            "counted as unrecognised and never ranked."
        ),
    )

    ok(
        "The anomaly validator emits only "
        f"{sorted(anomaly_severities)}, all inside the "
        "normalizer's vocabulary"
    )


# ==========================================================
# TEST 2 - EVIDENCE NORMALIZATION
# ==========================================================

def test_evidence_normalization():

    section(
        "TEST 2 - EVIDENCE FLAGS REGAIN THEIR STRUCTURE"
    )


    # ------------------------------------------------------
    # UNDERSCORES IN FIELD NAMES
    # ------------------------------------------------------
    # The reason the parser matches known prefixes instead of
    # splitting on "_". DATE_OF_BIRTH_NO_EVIDENCE split on
    # underscores attributes the problem to a field called
    # "date".
    # ------------------------------------------------------

    parsed = parse_evidence_flag(
        "DATE_OF_BIRTH_NO_EVIDENCE"
    )

    assert_equal(
        parsed["field"],
        "date_of_birth",
        (
            "A field name containing underscores must be "
            "recovered whole."
        ),
    )

    assert_equal(
        parsed["kind"],
        "NO_EVIDENCE",
        "The kind is what remains after the field prefix.",
    )

    ok(
        "DATE_OF_BIRTH_NO_EVIDENCE attributes to "
        "date_of_birth, not to a field called 'date'"
    )


    # ------------------------------------------------------
    # EVERY FIELD, EVERY KIND
    # ------------------------------------------------------

    checked = 0

    for name in EVIDENCE_FIELDS:

        for kind in EVIDENCE_KINDS:

            flag = (
                f"{name.upper()}_{kind}"
            )

            result = parse_evidence_flag(
                flag
            )

            assert_true(
                result["known"],
                (
                    f"{flag} is a flag the validator can "
                    f"emit and the parser did not recognise "
                    f"it."
                ),
            )

            assert_equal(
                result["field"],
                name,
                f"{flag} must attribute to {name}.",
            )

            assert_equal(
                result["kind"],
                kind,
                f"{flag} must parse as kind {kind}.",
            )

            checked += 1

    ok(
        f"{checked} field/kind combinations "
        f"({len(EVIDENCE_FIELDS)} fields x "
        f"{len(EVIDENCE_KINDS)} kinds) all parse"
    )


    # ------------------------------------------------------
    # THE CITED OCR LINE
    # ------------------------------------------------------

    with_line = parse_evidence_flag(
        "EXPIRY_DATE_INVALID_SOURCE_LINE_ID:L9"
    )

    assert_equal(
        with_line["field"],
        "expiry_date",
        "The field is recovered when a detail is attached.",
    )

    assert_equal(
        with_line["kind"],
        "INVALID_SOURCE_LINE_ID",
        "The kind is recovered when a detail is attached.",
    )

    assert_equal(
        with_line["source_line_id"],
        "L9",
        (
            "The cited OCR line must survive. Without it the "
            "finding cannot be checked against the page, "
            "which is the only thing that makes it "
            "actionable."
        ),
    )

    without_line = parse_evidence_flag(
        "FULL_NAME_EVIDENCE_MISMATCH"
    )

    assert_equal(
        without_line["source_line_id"],
        None,
        (
            "A kind that names no line must not appear to "
            "name one."
        ),
    )

    ok(
        "EXPIRY_DATE_INVALID_SOURCE_LINE_ID:L9 keeps its "
        "cited line; a mismatch flag reports no line"
    )


    # ------------------------------------------------------
    # AN UNRECOGNISED FLAG IS STILL A STATEMENT
    # ------------------------------------------------------

    unknown = parse_evidence_flag(
        "SOMETHING_ENTIRELY_NEW"
    )

    assert_equal(
        unknown["known"],
        False,
        "An unparseable flag reports itself as unparsed.",
    )

    assert_equal(
        unknown["flag"],
        "SOMETHING_ENTIRELY_NEW",
        (
            "The original string must survive verbatim. "
            "Dropping a flag nobody recognised is the worst "
            "available outcome: the validator said "
            "something and the interface would show nothing."
        ),
    )

    assert_equal(
        unknown["field"],
        None,
        "No field is guessed at.",
    )

    ok(
        "An unrecognised flag survives with known=False and "
        "no invented field"
    )


    # ------------------------------------------------------
    # IN THE ENVELOPE
    # ------------------------------------------------------

    result = normalize_findings(
        evidence_flags=[
            "FULL_NAME_EVIDENCE_MISMATCH",
            "EXPIRY_DATE_INVALID_SOURCE_LINE_ID:L9",
            "SOMETHING_ENTIRELY_NEW",
        ],
    )

    assert_equal(
        result["total"],
        3,
        (
            "Three flags in, three findings out. Nothing "
            "merged and nothing dropped."
        ),
    )

    for entry in result["findings"]:

        assert_equal(
            entry["category"],
            CATEGORY_EVIDENCE,
            "An evidence flag is an EVIDENCE finding.",
        )

        assert_equal(
            entry["source"],
            SOURCE_EVIDENCE,
            "The source names the payload it came from.",
        )

        assert_equal(
            entry["severity"],
            None,
            (
                "The evidence validator assigns no severity, "
                "so none is reported. Inventing one would be "
                "the normalizer asserting a judgement no "
                "measurement supports -- and the graded "
                "consequence is already in the list as "
                "CRITICAL_FIELD_NOT_TRUSTED or "
                "EXTRACTED_FIELD_INVALID_EVIDENCE."
            ),
        )

    grouped = by_code(
        result
    )

    assert_true(
        "EXPIRY_DATE_INVALID_SOURCE_LINE_ID" in grouped,
        (
            "The code must be the flag with the cited line "
            "stripped off, so it stays greppable against the "
            "validator that emitted it."
        ),
    )

    assert_equal(
        grouped[
            "EXPIRY_DATE_INVALID_SOURCE_LINE_ID"
        ][0]["detail"]["source_line_id"],
        "L9",
        "The cited line moves into detail, not into the code.",
    )

    assert_equal(
        result["unrated_count"],
        3,
        (
            "All three are ungraded, and the summary says so "
            "rather than implying they were graded INFO."
        ),
    )

    assert_equal(
        result["highest_severity"],
        None,
        (
            "Findings exist but nothing graded them. The "
            "highest severity is None, not INFO -- claiming "
            "INFO would be a grade nobody assigned."
        ),
    )

    ok(
        "Three evidence findings, all ungraded, "
        "highest_severity None with total 3"
    )


# ==========================================================
# TEST 3 - DATE AND LOGICAL FINDINGS, COUNTED ONCE
# ==========================================================

def test_date_and_logical_normalization():

    section(
        "TEST 3 - DATE FINDINGS APPEAR EXACTLY ONCE"
    )


    # ------------------------------------------------------
    # A document whose dates contradict each other, run
    # through the REAL validators.
    # ------------------------------------------------------

    lines = [
        ocr_line(
            "L1",
            "GUARD LICENCE",
        ),
        ocr_line(
            "L2",
            "NAME JOHN SMITH",
        ),
        ocr_line(
            "L3",
            "LICENCE NO 1234567890123456",
        ),
        ocr_line(
            "L4",
            "EXPIRES 2019-01-01",
        ),
        ocr_line(
            "L5",
            "DATE OF BIRTH 2030-05-05",
        ),
        ocr_line(
            "L6",
            "ISSUED 2020-01-01",
        ),
        ocr_line(
            "L7",
            "ISSUED BY TX DPS",
        ),
    ]

    parsed = extraction(
        document_type="guard_license",

        full_name=field(
            "JOHN SMITH",
            ["L2"],
        ),

        licence_number=field(
            "1234567890123456",
            ["L3"],
        ),

        expiry_date=field(
            "2019-01-01",
            ["L4"],
        ),

        date_of_birth=field(
            "2030-05-05",
            ["L5"],
        ),

        issue_date=field(
            "2020-01-01",
            ["L6"],
        ),

        issuer=field(
            "TX DPS",
            ["L7"],
        ),
    )

    evidence_flags = (
        EvidenceValidator().validate(
            parsed,
            lines,
        )
    )

    confidence = (
        ConfidenceService().calculate(
            parsed,
            lines,
            evidence_flags,
        )
    )

    reference = date(
        2024,
        6,
        1,
    )

    date_validation = (
        DateLogicalValidator().validate(
            parsed,
            confidence,
            reference_date=reference,
        )
    )

    anomaly = (
        DocumentAnomalyValidator().validate(
            parsed,
            confidence,
            date_validation,
        )
    )

    decision = (
        ReviewDecisionService().decide(
            anomaly
        )
    )

    logical_codes = [
        entry["code"]
        for entry in date_validation[
            "logical_issues"
        ]
    ]

    assert_true(
        logical_codes,
        (
            "The fixture must actually produce logical date "
            "issues, or this test asserts nothing."
        ),
    )

    result = normalize_findings(
        anomaly_validation=anomaly,
        date_validation=date_validation,
        evidence_flags=evidence_flags,
        review_decision=decision,
    )

    grouped = by_code(
        result
    )


    # ------------------------------------------------------
    # ONCE. NOT TWICE.
    # ------------------------------------------------------

    for code in logical_codes:

        assert_equal(
            len(
                grouped.get(
                    code,
                    [],
                )
            ),
            1,
            (
                f"{code} is emitted by the date validator "
                f"AND re-emitted by the anomaly validator. "
                f"It must appear exactly once. Listing it "
                f"twice would read as two independent "
                f"reasons to distrust the document, and "
                f"reason_codes is built from the anomaly "
                f"issues so the duplicate would look "
                f"authoritative."
            ),
        )

        assert_equal(
            grouped[code][0]["category"],
            CATEGORY_DATE,
            f"{code} is a DATE finding.",
        )

        assert_equal(
            grouped[code][0]["severity"],
            SEVERITY_ERROR,
            (
                f"{code} carries no severity where the date "
                f"validator raised it. The severity in the "
                f"envelope must be the one the anomaly "
                f"validator assigned, which is the "
                f"authoritative grade."
            ),
        )

    ok(
        f"{len(logical_codes)} date logical issues "
        f"({', '.join(sorted(set(logical_codes)))}) each "
        f"appear exactly once, as DATE / ERROR"
    )


    # ------------------------------------------------------
    # THE TOTAL IS THE TWO SOURCES, NOT THREE
    # ------------------------------------------------------

    assert_equal(
        result["total"],
        len(
            anomaly["issues"]
        )
        + len(
            evidence_flags
        ),
        (
            "The normalized total must be exactly the "
            "anomaly issues plus the evidence flags. "
            "Anything larger means date_validation was "
            "walked as a separate source."
        ),
    )

    ok(
        f"total {result['total']} == "
        f"{len(anomaly['issues'])} anomaly issues + "
        f"{len(evidence_flags)} evidence flags"
    )


    # ------------------------------------------------------
    # PER-FIELD FORMAT CODES
    # ------------------------------------------------------

    # ------------------------------------------------------
    # WHY THE VALUE IS 10/06/2024 AND NOT "not-a-date"
    # ------------------------------------------------------
    # {FIELD}_INVALID_FORMAT is only reachable by a value
    # that PASSES evidence validation and then FAILS strict
    # ISO parsing. "not-a-date" never gets there: the
    # evidence validator cannot find a date in it, so the
    # field is SKIPPED_INVALID_EVIDENCE and the date
    # validator never parses it.
    #
    # A slash-separated date does reach it -- the evidence
    # validator recognises it as a date and matches it
    # against the page, and then _parse_iso_date rejects it
    # because the extraction contract is YYYY-MM-DD.
    #
    # Which is the same ambiguity behind the guard_004
    # errors PHASE 10.5 found: 10/06 and 06/10 are the same
    # characters and different dates.
    # ------------------------------------------------------

    bad_format = extraction(
        document_type="id_card",

        full_name=field(
            "JOHN SMITH",
            ["L2"],
        ),

        id_number=field(
            "998877",
            ["L3"],
        ),

        expiry_date=field(
            "10/06/2024",
            ["L4"],
        ),
    )

    format_lines = [
        ocr_line(
            "L2",
            "NAME JOHN SMITH",
        ),
        ocr_line(
            "L3",
            "ID 998877",
        ),
        ocr_line(
            "L4",
            "EXPIRES 10/06/2024",
        ),
    ]

    format_flags = (
        EvidenceValidator().validate(
            bad_format,
            format_lines,
        )
    )

    format_confidence = (
        ConfidenceService().calculate(
            bad_format,
            format_lines,
            format_flags,
        )
    )

    format_dates = (
        DateLogicalValidator().validate(
            bad_format,
            format_confidence,
            reference_date=reference,
        )
    )

    format_anomaly = (
        DocumentAnomalyValidator().validate(
            bad_format,
            format_confidence,
            format_dates,
        )
    )

    format_result = normalize_findings(
        anomaly_validation=format_anomaly,
        date_validation=format_dates,
    )

    format_codes = [
        entry["code"]
        for entry in format_result[
            "findings"
        ]
        if entry["code"].endswith(
            findings_module.DATE_FORMAT_SUFFIX
        )
    ]

    assert_true(
        format_codes,
        (
            "An unparseable date must produce a per-field "
            "format finding, or the fixture is wrong."
        ),
    )

    for entry in format_result["findings"]:

        if entry["code"] in format_codes:

            assert_equal(
                entry["category"],
                CATEGORY_DATE,
                (
                    f"{entry['code']} is generated per field "
                    f"and must still be categorised by "
                    f"suffix as a DATE finding."
                ),
            )

    ok(
        f"generated {', '.join(format_codes)} categorised "
        f"DATE by suffix"
    )


# ==========================================================
# TEST 4 - EXPIRY KEEPS ITS DOMAIN DATA
# ==========================================================

def test_expiry_detail_preserved():

    section(
        "TEST 4 - AN EXPIRY FINDING CARRIES THE DATE AND THE "
        "DAY COUNT"
    )

    reference = date(
        2024,
        6,
        1,
    )

    soon = reference + timedelta(
        days=10
    )

    lines = [
        ocr_line(
            "L1",
            "NAME JANE DOE",
        ),
        ocr_line(
            "L2",
            "LICENCE NO 5555666677778888",
        ),
        ocr_line(
            "L3",
            f"EXPIRES {soon.isoformat()}",
        ),
        ocr_line(
            "L4",
            "ISSUED BY TX DPS",
        ),
    ]

    parsed = extraction(
        document_type="guard_license",

        full_name=field(
            "JANE DOE",
            ["L1"],
        ),

        licence_number=field(
            "5555666677778888",
            ["L2"],
        ),

        expiry_date=field(
            soon.isoformat(),
            ["L3"],
        ),

        issuer=field(
            "TX DPS",
            ["L4"],
        ),
    )

    flags = EvidenceValidator().validate(
        parsed,
        lines,
    )

    confidence = (
        ConfidenceService().calculate(
            parsed,
            lines,
            flags,
        )
    )

    date_validation = (
        DateLogicalValidator().validate(
            parsed,
            confidence,
            reference_date=reference,
        )
    )

    anomaly = (
        DocumentAnomalyValidator().validate(
            parsed,
            confidence,
            date_validation,
        )
    )

    assert_equal(
        date_validation["expiry"]["status"],
        "EXPIRING_SOON",
        (
            "The fixture must actually be expiring soon, or "
            "this test asserts nothing."
        ),
    )

    result = normalize_findings(
        anomaly_validation=anomaly,
        date_validation=date_validation,
    )

    expiry_findings = [
        entry
        for entry in result["findings"]
        if entry["category"] == CATEGORY_EXPIRY
    ]

    assert_equal(
        len(
            expiry_findings
        ),
        1,
        (
            "Exactly one expiry finding: the anomaly "
            "validator's DOCUMENT_EXPIRING_SOON."
        ),
    )

    entry = expiry_findings[0]

    assert_equal(
        entry["code"],
        "DOCUMENT_EXPIRING_SOON",
        "The code is the anomaly validator's.",
    )

    assert_equal(
        entry["detail"]["expiry_date"],
        soon.isoformat(),
        (
            "The actual expiry date must be attached. "
            "Without it the reader has to go to another "
            "panel to find out when."
        ),
    )

    assert_equal(
        entry["detail"]["days_until_expiry"],
        10,
        (
            "The day count must be the one the date "
            "validator computed against its own reference "
            "date. Recomputing it here would create a second "
            "definition of 'soon' that could disagree with "
            "the status beside it."
        ),
    )

    assert_equal(
        entry["detail"]["expiry_status"],
        "EXPIRING_SOON",
        "The status travels with the finding.",
    )

    # And the raw block is untouched.
    assert_equal(
        date_validation["expiry"][
            "days_until_expiry"
        ],
        10,
        (
            "Enrichment must read date_validation, not "
            "modify it."
        ),
    )

    ok(
        "DOCUMENT_EXPIRING_SOON carries expiry_date "
        f"{soon.isoformat()}, days_until_expiry 10, status "
        "EXPIRING_SOON, and date_validation is unchanged"
    )


# ==========================================================
# TEST 5 - QUALITY, AND THE THREE STATES
# ==========================================================

def test_quality_normalization_and_three_states():

    section(
        "TEST 5 - NOT ASSESSED, ASSESSED-AND-CLEAN, AND "
        "ASSESSED-WITH-FINDINGS STAY THREE DIFFERENT THINGS"
    )


    # ------------------------------------------------------
    # 1. NOT ASSESSED
    # ------------------------------------------------------

    not_assessed = normalize_findings(
        quality=None,
    )

    assert_equal(
        not_assessed["quality_assessed"],
        False,
        (
            "quality=None means nobody measured the image. "
            "Every document analysed before Phase 10.1 is in "
            "this state."
        ),
    )

    assert_equal(
        [
            entry
            for entry in not_assessed["findings"]
            if entry["category"] == CATEGORY_QUALITY
        ],
        [],
        "Nothing measured, nothing reported.",
    )


    # ------------------------------------------------------
    # 2. ASSESSED, NOTHING FIRED
    # ------------------------------------------------------

    assessed_clean = normalize_findings(
        quality=quality_payload(),
    )

    assert_equal(
        assessed_clean["quality_assessed"],
        True,
        (
            "An assessment with no findings was still an "
            "assessment."
        ),
    )

    assert_equal(
        [
            entry
            for entry in assessed_clean["findings"]
            if entry["category"] == CATEGORY_QUALITY
        ],
        [],
        "Measured and clean produces no findings.",
    )


    # ------------------------------------------------------
    # THE DISTINCTION IS THE WHOLE POINT
    # ------------------------------------------------------
    # Both states have an empty QUALITY finding list. If the
    # only thing the interface could see was that list, it
    # would have to say the same thing about a document
    # nobody measured and a document that measured clean.
    # ------------------------------------------------------

    assert_true(
        not_assessed["quality_assessed"]
        != assessed_clean["quality_assessed"],
        (
            "NOT ASSESSED and ASSESSED-AND-CLEAN both have "
            "zero quality findings. They must remain "
            "distinguishable through normalization, or the "
            "interface is forced to claim an unmeasured "
            "image had no problems."
        ),
    )

    ok(
        "quality=None -> quality_assessed False; "
        "quality={findings: []} -> quality_assessed True; "
        "both have zero quality findings and remain distinct"
    )


    # ------------------------------------------------------
    # 3. ASSESSED, FINDINGS FIRED
    # ------------------------------------------------------

    with_findings = normalize_findings(
        quality=quality_payload(
            findings=[
                quality_finding(),
                quality_finding(
                    code="IMAGE_TOO_DARK",
                    severity=SEVERITY_ERROR,
                    metric_name="mean_luminance",
                    measured_value=18.4,
                    threshold=40.0,
                    message="The image is underexposed.",
                ),
            ]
        ),
    )

    quality_findings = [
        entry
        for entry in with_findings["findings"]
        if entry["category"] == CATEGORY_QUALITY
    ]

    assert_equal(
        len(
            quality_findings
        ),
        2,
        "Two findings in, two out.",
    )

    for entry in quality_findings:

        assert_equal(
            entry["source"],
            SOURCE_QUALITY,
            "The source names the quality payload.",
        )

        assert_equal(
            entry["field"],
            None,
            (
                "Quality measures the photograph, not a "
                "field. Naming a field would be wrong."
            ),
        )

        detail = entry["detail"]

        assert_true(
            detail["metric_name"],
            (
                "The metric name must survive. A quality "
                "finding without its measurement is an "
                "opinion rather than something checkable."
            ),
        )

        assert_true(
            isinstance(
                detail["measured_value"],
                (
                    int,
                    float,
                ),
            ),
            "The measured value must survive.",
        )

        assert_true(
            isinstance(
                detail["threshold"],
                (
                    int,
                    float,
                ),
            ),
            "The threshold must survive.",
        )

    dark = [
        entry
        for entry in quality_findings
        if entry["code"] == "IMAGE_TOO_DARK"
    ][0]

    assert_equal(
        dark["detail"]["measured_value"],
        18.4,
        "The measurement is passed through, not rounded again.",
    )

    assert_equal(
        dark["detail"]["threshold"],
        40.0,
        "The threshold is passed through.",
    )

    assert_equal(
        with_findings["highest_severity"],
        SEVERITY_ERROR,
        (
            "One ERROR quality finding makes the document's "
            "highest severity ERROR."
        ),
    )

    ok(
        "two quality findings keep metric_name, "
        "measured_value and threshold; mean_luminance 18.4 "
        "against 40.0 survives verbatim"
    )


    # ------------------------------------------------------
    # 4. THE ASSESSMENT FAILED
    # ------------------------------------------------------

    failed = normalize_findings(
        quality=quality_payload(
            error="cv2 could not open the file",
        ),
    )

    assert_equal(
        failed["quality_assessed"],
        True,
        "An attempt was made.",
    )

    assert_equal(
        failed["quality_error"],
        "cv2 could not open the file",
        (
            "A failed assessment must be reported as a "
            "failure, not as a clean result."
        ),
    )

    ok(
        "a failed assessment reports its error rather than "
        "reading as clean"
    )


# ==========================================================
# TEST 6 - HIGHEST SEVERITY, AND UNKNOWN SEVERITY
# ==========================================================

def test_severity_derivation():

    section(
        "TEST 6 - HIGHEST SEVERITY IS A MAXIMUM, AND AN "
        "UNRECOGNISED SEVERITY IS NEITHER RANKED NOR HIDDEN"
    )

    cases = [
        (
            [],
            None,
            "nothing fired",
        ),
        (
            [
                issue(
                    "A",
                    SEVERITY_INFO,
                )
            ],
            SEVERITY_INFO,
            "INFO only",
        ),
        (
            [
                issue(
                    "A",
                    SEVERITY_INFO,
                ),
                issue(
                    "B",
                    SEVERITY_WARNING,
                ),
            ],
            SEVERITY_WARNING,
            "INFO + WARNING",
        ),
        (
            [
                issue(
                    "A",
                    SEVERITY_WARNING,
                ),
                issue(
                    "B",
                    SEVERITY_ERROR,
                ),
            ],
            SEVERITY_ERROR,
            "WARNING + ERROR",
        ),
        (
            [
                issue(
                    "A",
                    SEVERITY_ERROR,
                ),
                issue(
                    "B",
                    SEVERITY_INFO,
                ),
            ],
            SEVERITY_ERROR,
            "ERROR + INFO, worst wins regardless of order",
        ),
    ]

    for issues, expected, label in cases:

        result = normalize_findings(
            anomaly_validation={
                "issues": issues,
            },
        )

        assert_equal(
            result["highest_severity"],
            expected,
            f"highest_severity for {label}.",
        )

    ok(
        f"{len(cases)} severity combinations each derive the "
        f"maximum of what the producers assigned"
    )


    # ------------------------------------------------------
    # AN UNRECOGNISED SEVERITY
    # ------------------------------------------------------

    result = normalize_findings(
        anomaly_validation={
            "issues": [
                issue(
                    "GRADED",
                    SEVERITY_WARNING,
                ),
                issue(
                    "UNGRADEABLE",
                    "CATASTROPHIC",
                ),
            ],
        },
    )

    assert_equal(
        result["total"],
        2,
        (
            "An unrecognised severity must not cause the "
            "finding to be dropped. The producer still said "
            "something."
        ),
    )

    assert_equal(
        result["unrecognised_severities"],
        [
            "CATASTROPHIC",
        ],
        (
            "It must be named, so that whoever introduced it "
            "can see it arrived."
        ),
    )

    assert_equal(
        result["highest_severity"],
        SEVERITY_WARNING,
        (
            "highest_severity is computed over recognised "
            "severities only.\n"
            "Ranking an unknown string highest would let one "
            "typo turn every document red. Ranking it lowest "
            "would hide it. So it is counted and named "
            "instead, where it stays visible without "
            "distorting the summary."
        ),
    )

    assert_equal(
        result["counts"],
        {
            SEVERITY_ERROR: 0,
            SEVERITY_WARNING: 1,
            SEVERITY_INFO: 0,
        },
        (
            "The counts cover the vocabulary only, so an "
            "unknown severity cannot silently inflate one of "
            "the three real ones."
        ),
    )

    ok(
        "CATASTROPHIC is kept, named in "
        "unrecognised_severities, excluded from counts, and "
        "not ranked into highest_severity (which stays "
        "WARNING)"
    )


    # ------------------------------------------------------
    # LOWERCASE IS THE SAME SEVERITY
    # ------------------------------------------------------

    lowered = normalize_findings(
        anomaly_validation={
            "issues": [
                issue(
                    "A",
                    "error",
                ),
            ],
        },
    )

    assert_equal(
        lowered["highest_severity"],
        SEVERITY_ERROR,
        (
            "Severity is normalized to upper case, so a "
            "producer that changed its casing does not lose "
            "its grade."
        ),
    )

    ok(
        "a lower-case 'error' is recognised as ERROR rather "
        "than treated as unknown"
    )


# ==========================================================
# TEST 7 - ORDERING GIVES THE INTERFACE ITS HIERARCHY
# ==========================================================

def test_ordering():

    section(
        "TEST 7 - WORST FIRST, UNGRADED LAST, AND THE SAME "
        "ORDER EVERY TIME"
    )

    result = normalize_findings(
        anomaly_validation={
            "issues": [
                issue(
                    "AN_INFO",
                    SEVERITY_INFO,
                ),
                issue(
                    "AN_ERROR",
                    SEVERITY_ERROR,
                ),
                issue(
                    "A_WARNING",
                    SEVERITY_WARNING,
                ),
            ],
        },

        evidence_flags=[
            "FULL_NAME_EVIDENCE_MISMATCH",
        ],

        quality=quality_payload(
            findings=[
                quality_finding(
                    code="IMAGE_UNREADABLE",
                    severity=SEVERITY_ERROR,
                ),
            ]
        ),
    )

    severities = [
        entry["severity"]
        for entry in result["findings"]
    ]

    assert_equal(
        severities,
        [
            SEVERITY_ERROR,
            SEVERITY_ERROR,
            SEVERITY_WARNING,
            SEVERITY_INFO,
            None,
        ],
        (
            "Errors first, then warnings, then info, then "
            "the ungraded evidence detail.\n"
            "The interface gets its hierarchy from this "
            "order rather than sorting for itself, which is "
            "how the dashboard, the workspace and any future "
            "consumer stay consistent without duplicating "
            "the rule."
        ),
    )

    assert_equal(
        result["findings"][-1]["category"],
        CATEGORY_EVIDENCE,
        (
            "Ungraded supporting detail must never appear "
            "above a graded error."
        ),
    )


    # ------------------------------------------------------
    # DETERMINISTIC
    # ------------------------------------------------------

    shuffled = normalize_findings(
        anomaly_validation={
            "issues": [
                issue(
                    "A_WARNING",
                    SEVERITY_WARNING,
                ),
                issue(
                    "AN_INFO",
                    SEVERITY_INFO,
                ),
                issue(
                    "AN_ERROR",
                    SEVERITY_ERROR,
                ),
            ],
        },

        evidence_flags=[
            "FULL_NAME_EVIDENCE_MISMATCH",
        ],

        quality=quality_payload(
            findings=[
                quality_finding(
                    code="IMAGE_UNREADABLE",
                    severity=SEVERITY_ERROR,
                ),
            ]
        ),
    )

    assert_equal(
        [
            entry["code"]
            for entry in shuffled["findings"]
        ],
        [
            entry["code"]
            for entry in result["findings"]
        ],
        (
            "The same findings in a different input order "
            "must render in the same output order, or the "
            "interface reshuffles itself between reloads."
        ),
    )

    ok(
        "ERROR, ERROR, WARNING, INFO, ungraded -- and the "
        "same order from a shuffled input"
    )


# ==========================================================
# TEST 8 - ROUTING EFFECT IS READ, NOT RE-DERIVED
# ==========================================================

def test_routing_effect():

    section(
        "TEST 8 - affects_routing COMES FROM THE STORED "
        "DECISION"
    )

    issues = [
        issue(
            "MISSING_CRITICAL_FIELD",
            SEVERITY_ERROR,
            "full_name",
        ),
    ]

    quality = quality_payload(
        findings=[
            quality_finding(
                code="IMAGE_UNREADABLE",
                severity=SEVERITY_ERROR,
            ),
        ]
    )

    decision = {
        "decision": "REVIEW_REQUIRED",
        "review_required": True,
        "priority": "HIGH",

        "reason_codes": [
            "MISSING_CRITICAL_FIELD",
            "IMAGE_UNREADABLE",
        ],

        "issues": issues,
    }

    result = normalize_findings(
        anomaly_validation={
            "issues": issues,
        },
        quality=quality,
        evidence_flags=[
            "FULL_NAME_EVIDENCE_MISMATCH",
        ],
        review_decision=decision,
    )

    grouped = by_code(
        result
    )

    assert_equal(
        grouped["MISSING_CRITICAL_FIELD"][0][
            "affects_routing"
        ],
        True,
        (
            "An anomaly issue in reason_codes drove the "
            "decision."
        ),
    )

    assert_equal(
        grouped["IMAGE_UNREADABLE"][0][
            "affects_routing"
        ],
        True,
        (
            "apply_quality_to_review adds ERROR quality "
            "codes to reason_codes, so the quality finding's "
            "routing effect is read from the same place."
        ),
    )

    assert_equal(
        grouped["FULL_NAME_EVIDENCE_MISMATCH"][0][
            "affects_routing"
        ],
        False,
        (
            "An evidence flag is never a reason code. Its "
            "routing effect is already represented by the "
            "anomaly finding it produced, and claiming it "
            "separately would double-count the cause."
        ),
    )

    assert_equal(
        result["routing_finding_count"],
        2,
        (
            "Two of the three findings drove routing, and "
            "the count is derived from membership rather "
            "than from a policy restated here."
        ),
    )

    ok(
        "affects_routing is reason_codes membership: "
        "2 of 3 findings, read from the stored decision"
    )


    # ------------------------------------------------------
    # NO DECISION IS UNKNOWN, NOT FALSE
    # ------------------------------------------------------

    without = normalize_findings(
        anomaly_validation={
            "issues": issues,
        },
    )

    for entry in without["findings"]:

        assert_equal(
            entry["affects_routing"],
            None,
            (
                "With no stored decision, whether a finding "
                "affected routing is UNKNOWN. Reporting "
                "False would be a claim, and the claim would "
                "be wrong for a document whose decision "
                "simply was not passed in."
            ),
        )

    assert_equal(
        without["routing_finding_count"],
        0,
        (
            "The count is of findings known to have driven "
            "routing, so unknown does not count as yes."
        ),
    )

    ok(
        "no stored decision -> affects_routing None for "
        "every finding, not False"
    )


# ==========================================================
# TEST 9 - UNSUPPORTED AND DUPLICATE ARE NOT FINDINGS
# ==========================================================

def test_outcomes_are_not_findings():

    section(
        "TEST 9 - CLASSIFICATION AND DUPLICATE OUTCOMES "
        "CANNOT ENTER THIS LIST"
    )


    # ------------------------------------------------------
    # THE FUNCTION DOES NOT ACCEPT THEM
    # ------------------------------------------------------
    # Structural rather than conditional. There is no code
    # path that could flatten either outcome into a finding,
    # because neither can be passed in.
    # ------------------------------------------------------

    for keyword in (
        "classification",
        "duplicate",
    ):

        try:
            normalize_findings(
                **{
                    keyword: {
                        "anything": True,
                    },
                }
            )

        except TypeError:
            pass

        else:
            raise AssertionError(
                f"normalize_findings accepted a "
                f"'{keyword}' argument. An unsupported "
                f"document is a classification outcome and "
                f"an exact duplicate is a source-identity "
                f"outcome; the normalizer must not be able "
                f"to see either, so that no future change "
                f"can quietly turn one into a generic ERROR."
            )

    ok(
        "normalize_findings accepts neither a classification "
        "nor a duplicate argument"
    )


    # ------------------------------------------------------
    # AND NO OUTCOME CODE CAN APPEAR
    # ------------------------------------------------------

    forbidden = {
        DECISION_UNSUPPORTED_DOCUMENT,
        DUPLICATE_DOCUMENT,
        DUPLICATE_IN_PROGRESS,
    }

    # An unsupported document's real analysis: the classifier
    # transitions the DECISION, and the issues it was
    # transitioned from are preserved.
    unsupported_decision = {
        "decision": DECISION_UNSUPPORTED_DOCUMENT,
        "review_required": False,
        "priority": "NONE",

        "reason_codes": [
            "UNKNOWN_DOCUMENT_TYPE",
        ],

        "issues": [
            issue(
                "UNKNOWN_DOCUMENT_TYPE",
                SEVERITY_ERROR,
            ),
        ],
    }

    result = normalize_findings(
        anomaly_validation={
            "issues": unsupported_decision[
                "issues"
            ],
        },
        review_decision=unsupported_decision,
    )

    codes = {
        entry["code"]
        for entry in result["findings"]
    }

    overlap = codes & forbidden

    assert_equal(
        sorted(
            overlap
        ),
        [],
        (
            "An outcome code appeared as a finding: "
            f"{sorted(overlap)}.\n"
            "UNSUPPORTED_DOCUMENT is a classification "
            "outcome, not an anomaly -- flattening it into "
            "this list would put the document back into "
            "ordinary review-queue semantics that PHASE 10.2 "
            "deliberately took it out of.\n"
            "DUPLICATE_DOCUMENT is a source-identity "
            "outcome. The nearest reading of 'anomaly' is "
            "suspicion, and two uploads of one photograph is "
            "not fraud, not tampering, and not evidence of "
            "either."
        ),
    )

    assert_true(
        "UNKNOWN_DOCUMENT_TYPE" in codes,
        (
            "The finding that CAUSED the unsupported outcome "
            "is still a real anomaly finding and must "
            "survive. Only the outcome itself is excluded."
        ),
    )

    ok(
        "an unsupported document's findings contain "
        "UNKNOWN_DOCUMENT_TYPE and no outcome code"
    )


# ==========================================================
# TEST 10 - NO INVENTED NUMBER
# ==========================================================

def test_no_invented_score():

    section(
        "TEST 10 - NO RISK SCORE, NO FRAUD PROBABILITY, NO "
        "DOCUMENT CONFIDENCE"
    )


    # ------------------------------------------------------
    # THE KEY SET IS FIXED
    # ------------------------------------------------------
    # Asserted exactly, so a score cannot be added to the
    # summary without this test failing. A subset assertion
    # would let one through.
    # ------------------------------------------------------

    result = normalize_findings(
        anomaly_validation={
            "issues": [
                issue(
                    "A",
                    SEVERITY_ERROR,
                ),
            ],
        },
        quality=quality_payload(),
    )

    assert_equal(
        sorted(
            result.keys()
        ),
        sorted(
            [
                "findings",
                "total",
                "counts",
                "unrated_count",
                "unrecognised_severities",
                "highest_severity",
                "categories",
                "quality_assessed",
                "quality_error",
                "routing_finding_count",
            ]
        ),
        (
            "The summary key set is fixed. Anything new here "
            "is a new claim about the document, and the "
            "claims this system can support are counts and a "
            "maximum severity."
        ),
    )

    assert_equal(
        sorted(
            result["findings"][0].keys()
        ),
        sorted(
            [
                "code",
                "category",
                "severity",
                "message",
                "field",
                "source",
                "affects_routing",
                "detail",
            ]
        ),
        "The envelope key set is fixed.",
    )

    assert_true(
        isinstance(
            result["highest_severity"],
            str,
        ),
        (
            "The single derived value is a severity string. "
            "A number here could be mistaken for a "
            "probability, and PHASE 10.5 measured what "
            "happens when a number looks more certain than "
            "it is."
        ),
    )

    ok(
        "10 summary keys and 8 envelope keys, asserted "
        "exactly; the one derived value is a severity string"
    )


    # ------------------------------------------------------
    # AND NOTHING LIKE IT IS DEFINED ANYWHERE
    # ------------------------------------------------------

    banned = (
        "risk_score",
        "riskScore",
        "fraud_score",
        "fraudScore",
        "fraud_probability",
        "tamper_score",
        "tamperScore",
        "tamper_probability",
        "danger_score",
        "document_confidence",
        "documentConfidence",
        "overall_confidence",
        "overallConfidence",
        "average_confidence",
        "averageConfidence",
        "trust_score",
        "trustScore",
    )

    searched = []

    scan_roots = (
        PROJECT_ROOT / "backend",
        PROJECT_ROOT / "frontend",
        PROJECT_ROOT / "database",
    )

    hits = []

    for root in scan_roots:

        for path in sorted(
            list(
                root.rglob(
                    "*.py"
                )
            )
            + list(
                root.rglob(
                    "*.js"
                )
            )
        ):

            if "__pycache__" in path.parts:
                continue

            text = path.read_text(
                encoding="utf-8",
                errors="replace",
            )

            searched.append(
                path
            )

            for name in banned:

                # Definition or assignment, not the word in
                # a comment explaining why it does not
                # exist -- those comments are the point.
                for pattern in (
                    f'"{name}"',
                    f"'{name}'",
                    f"{name} =",
                    f"{name}=",
                    f"{name}:",
                    f"def {name}",
                    f"function {name}",
                ):

                    if pattern in text:

                        hits.append(
                            (
                                path.relative_to(
                                    PROJECT_ROOT
                                ),
                                pattern,
                            )
                        )

    assert_equal(
        hits,
        [],
        (
            "An invented score is defined somewhere: "
            f"{hits}.\n"
            "None of these exist in VIGILOX and none can be "
            "supported by anything it measures."
        ),
    )

    ok(
        f"{len(searched)} backend/frontend/database source "
        f"files searched for {len(banned)} invented-score "
        f"identifiers: none defined"
    )


# ==========================================================
# TEST 11 - THE BACKEND AND THE BROWSER AGREE
# ==========================================================

def test_browser_agrees_with_backend():

    section(
        "TEST 11 - THE JAVASCRIPT PARSER AND THE PYTHON "
        "PARSER AGREE ON EVERY FLAG THE VALIDATOR CAN EMIT"
    )

    node = shutil.which(
        "node"
    )

    assert_true(
        node is not None,
        (
            "Node is required to execute the browser "
            "parser. Reading its source and reasoning about "
            "it would not prove the two agree."
        ),
    )

    corpus = []

    for name in EVIDENCE_FIELDS:

        for kind in EVIDENCE_KINDS:

            flag = f"{name.upper()}_{kind}"

            corpus.append(
                flag
            )

            if kind in (
                findings_module
                .EVIDENCE_KINDS_WITH_LINE_ID
            ):
                corpus.append(
                    f"{flag}:L9"
                )

    corpus.append(
        "SOMETHING_ENTIRELY_NEW"
    )

    probe = (
        "global.window = global;"
        "require("
        + json.dumps(
            str(
                PROJECT_ROOT
                / "frontend"
                / "static"
                / "js"
                / "common.js"
            )
        )
        + ");"
        "require("
        + json.dumps(
            str(
                PROJECT_ROOT
                / "frontend"
                / "static"
                / "js"
                / "vocabulary.js"
            )
        )
        + ");"
        "var v = global.VigiloxVocabulary;"
        "var flags = "
        + json.dumps(
            corpus
        )
        + ";"
        "var out = {};"
        "flags.forEach(function (flag) {"
        "  var d = v.describeEvidenceFlag(flag);"
        "  out[flag] = {"
        "    known: d.known,"
        "    field: d.field,"
        "    kind: d.kind"
        "  };"
        "});"
        "console.log(JSON.stringify(out));"
    )

    completed = subprocess.run(
        [
            node,
            "-e",
            probe,
        ],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(
            PROJECT_ROOT
        ),
    )

    assert_equal(
        completed.returncode,
        0,
        (
            "The browser parser probe must run.\n"
            f"{completed.stderr[:2000]}"
        ),
    )

    browser = json.loads(
        completed.stdout
    )

    disagreements = []

    for flag in corpus:

        expected = parse_evidence_flag(
            flag
        )

        actual = browser[flag]

        if (
            actual["known"] != expected["known"]
            or actual["field"] != expected["field"]
            or actual["kind"] != expected["kind"]
        ):
            disagreements.append(
                (
                    flag,
                    expected,
                    actual,
                )
            )

    assert_equal(
        disagreements,
        [],
        (
            "The browser and the backend disagree about "
            "which field an evidence flag belongs to:\n"
            f"{disagreements}\n"
            "This is the same class of problem PHASE 10.5 "
            "found in the duplicated critical-field list, "
            "where a definitional gap hid a real "
            "critical-field error. The browser keeps its "
            "parser only as a fallback for raw flag strings, "
            "and it has to agree with the definition beside "
            "the validator."
        ),
    )

    ok(
        f"{len(corpus)} flags parsed identically by "
        f"backend.app.domain.findings and vocabulary.js"
    )


# ==========================================================
# TEST 12 - THE READ PATH
# ==========================================================

def test_read_path():

    section(
        "TEST 12 - THE DETAIL ENDPOINT ADDS THE VIEW AND "
        "KEEPS THE RAW PAYLOADS"
    )

    from backend.app.services.persistence_service import (
        PersistenceService,
    )

    from backend.app.services.query_service import (
        DocumentQueryService,
    )

    from backend.app.services.document_deletion_service import (
        DocumentDeletionService,
    )

    marker = uuid.uuid4().hex[:8]

    lines = [
        ocr_line(
            "L1",
            "GUARD LICENCE",
        ),
        ocr_line(
            "L2",
            "NAME PHASE TEN SIX",
        ),
        ocr_line(
            "L3",
            "LICENCE NO 4444555566667777",
        ),
        ocr_line(
            "L4",
            "EXPIRES 2019-03-03",
        ),
        ocr_line(
            "L5",
            "ISSUED BY TX DPS",
        ),
    ]

    parsed = extraction(
        document_type="guard_license",

        full_name=field(
            "PHASE TEN SIX",
            ["L2"],
        ),

        licence_number=field(
            "4444555566667777",
            ["L3"],
        ),

        expiry_date=field(
            "2019-03-03",
            ["L4"],
        ),

        issuer=field(
            "TX DPS",
            ["L5"],
        ),

        # No evidence line exists for this value, so the
        # evidence validator raises a flag for it. The read
        # path then has at least one ungraded finding to
        # carry, which is the case most likely to be
        # mishandled.
        date_of_birth=field(
            "1980-01-01",
            ["L1"],
        ),
    )

    evidence_flags = (
        EvidenceValidator().validate(
            parsed,
            lines,
        )
    )

    confidence = (
        ConfidenceService().calculate(
            parsed,
            lines,
            evidence_flags,
        )
    )

    date_validation = (
        DateLogicalValidator().validate(
            parsed,
            confidence,
            reference_date=date(
                2024,
                6,
                1,
            ),
        )
    )

    anomaly = (
        DocumentAnomalyValidator().validate(
            parsed,
            confidence,
            date_validation,
        )
    )

    decision = (
        ReviewDecisionService().decide(
            anomaly
        )
    )

    quality = quality_payload(
        findings=[
            quality_finding(),
        ]
    )

    assert_true(
        evidence_flags,
        (
            "The fixture must produce evidence flags, or the "
            "read-path assertion about ungraded findings "
            "asserts nothing."
        ),
    )

    pipeline_result = {
        "extraction":
            parsed.model_dump(),

        "ocr_lines":
            lines,

        "evidence_flags":
            evidence_flags,

        "field_confidence":
            confidence,

        "date_validation":
            date_validation,

        "anomaly_validation":
            anomaly,

        "quality":
            quality,

        "review_decision":
            decision,
    }

    stored = PersistenceService().save_processed_document(
        original_filename=(
            f"phase106_{marker}.jpg"
        ),
        content_type="image/jpeg",
        pipeline_result=pipeline_result,
    )

    document_id = stored[
        "document_id"
    ]

    # ------------------------------------------------------
    # THE ROW THIS TEST CREATES MUST NOT OUTLIVE IT
    # ------------------------------------------------------
    # PHASE 11.1 found why this matters.
    #
    # save_processed_document is called here without a
    # source_path, because this test has no image -- it builds
    # the extraction and the OCR lines directly. So no file is
    # written to managed storage, and the row it creates is a
    # row whose file does not exist.
    #
    # StorageIntegrityService classifies exactly that as
    # MISSING_STORAGE, which in production means a stored
    # identity document has disappeared. Leaving these rows
    # behind does not break anything, but it fills a
    # production data-loss signal with test noise until nobody
    # reads it -- and eight of them were already sitting in
    # the local database from earlier runs of this suite.
    #
    # A test that degrades a monitoring signal is a test that
    # has to clean up after itself.
    # ------------------------------------------------------

    try:
        detail = (
            DocumentQueryService().get_document(
                document_id
            )
        )

        assert_true(
            detail is not None,
            "The document must be readable back.",
        )


        # ------------------------------------------------------
        # ADDED, NOT SUBSTITUTED
        # ------------------------------------------------------

        analysis = detail["analysis"]

        assert_equal(
            analysis["evidence_flags"],
            evidence_flags,
            (
                "evidence_flags must still be returned exactly "
                "as stored. A cleaner interface is not a reason "
                "to break a working contract."
            ),
        )

        assert_equal(
            analysis["anomaly_validation"]["issues"],
            anomaly["issues"],
            "anomaly_validation must still be returned as stored.",
        )

        assert_equal(
            analysis["date_validation"]["expiry"],
            date_validation["expiry"],
            "date_validation must still be returned as stored.",
        )

        assert_equal(
            analysis["quality"]["findings"],
            quality["findings"],
            "quality must still be returned as stored.",
        )

        ok(
            "analysis.evidence_flags, .anomaly_validation, "
            ".date_validation and .quality all returned "
            "unchanged"
        )


        # ------------------------------------------------------
        # AND THE VIEW AGREES WITH THEM
        # ------------------------------------------------------

        view = detail["findings"]

        assert_true(
            view is not None,
            "The normalized view must be present.",
        )

        assert_equal(
            view["total"],
            len(
                anomaly["issues"]
            )
            + len(
                evidence_flags
            )
            + len(
                quality["findings"]
            ),
            (
                "The view must account for exactly the anomaly "
                "issues, the evidence flags and the quality "
                "findings -- no more, which would mean "
                "double-counting, and no fewer, which would mean "
                "something the pipeline said is not being shown."
            ),
        )

        view_codes = [
            entry["code"]
            for entry in view["findings"]
        ]

        for stored_issue in anomaly["issues"]:

            assert_equal(
                view_codes.count(
                    stored_issue["code"]
                ),
                1,
                (
                    f"{stored_issue['code']} must appear exactly "
                    f"once in the view."
                ),
            )

        for flag in evidence_flags:

            code = flag.partition(
                ":"
            )[0]

            assert_true(
                code in view_codes,
                (
                    f"Evidence flag {flag} is missing from the "
                    f"view."
                ),
            )

        assert_equal(
            view["quality_assessed"],
            True,
            "This document was assessed.",
        )

        assert_true(
            view["unrated_count"] >= 1,
            (
                "The ungraded evidence findings must be counted "
                "as ungraded."
            ),
        )

        ok(
            f"findings.total {view['total']} accounts for "
            f"{len(anomaly['issues'])} anomaly + "
            f"{len(evidence_flags)} evidence + "
            f"{len(quality['findings'])} quality, each exactly "
            f"once"
        )


        # ------------------------------------------------------
        # THE OTHER DERIVED BLOCKS ARE UNTOUCHED
        # ------------------------------------------------------

        assert_true(
            detail["classification"] is not None,
            (
                "PHASE 10.2's classification block must still be "
                "there. Normalization adds a view; it does not "
                "absorb the outcomes."
            ),
        )

        assert_true(
            detail["duplicate"] is not None,
            "PHASE 10.3's duplicate block must still be there.",
        )

        assert_true(
            detail["final_record"] is not None,
            "The final record must still be there.",
        )


        ok(
            "classification, duplicate and final_record "
            "blocks all still present alongside the new view"
        )

    finally:

        # Removes the row, its analysis, its audit events and
        # any managed storage. Deliberately the real deletion
        # service rather than a raw DELETE: if document
        # deletion is broken, this suite should be one of the
        # things that notices.
        DocumentDeletionService().delete_document(
            document_id
        )

    return document_id


# ==========================================================
# TEST 13 - THE INTERFACE
# ==========================================================

def test_interface():

    section(
        "TEST 13 - THE WORKSPACE RENDERS THE VIEW SAFELY AND "
        "WITH A HIERARCHY"
    )

    harness = (
        PROJECT_ROOT
        / "tests"
        / "dashboard"
        / "workspace_harness.js"
    )

    node = shutil.which(
        "node"
    )

    assert_true(
        node is not None,
        "Node is required to execute the workspace modules.",
    )

    completed = subprocess.run(
        [
            node,
            str(
                harness
            ),
        ],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(
            PROJECT_ROOT
        ),
    )

    assert_equal(
        completed.returncode,
        0,
        (
            "The workspace harness must pass.\n"
            f"{completed.stdout[-6000:]}\n"
            f"{completed.stderr[-3000:]}"
        ),
    )

    results = json.loads(
        completed.stdout
    )


    # ------------------------------------------------------
    # NO innerHTML WITH A VALUE
    # ------------------------------------------------------

    view_files = sorted(
        (
            PROJECT_ROOT
            / "frontend"
            / "static"
            / "js"
        ).rglob(
            "*.js"
        )
    )

    # ASSIGNMENT, not the word. Several modules explain in a
    # comment why they never write innerHTML, and a rule that
    # matched the word flagged that prose -- which is the rule
    # punishing the documentation that exists to reassure the
    # reader.
    ASSIGNMENT = re.compile(
        r"innerHTML\s*="
    )

    # Clearing a node with the empty string carries no
    # untrusted value and is how this codebase resets a
    # container.
    CLEARING = re.compile(
        r"innerHTML\s*=\s*(\"\"|'')\s*;?\s*$"
    )

    # SELF-CHECK, both directions. A rule that cannot see a
    # real assignment would pass on a genuinely unsafe file.
    assert_true(
        ASSIGNMENT.search(
            "node.innerHTML = value;"
        )
        is not None,
        (
            "The innerHTML detector cannot see a real "
            "assignment. It is broken."
        ),
    )

    assert_true(
        ASSIGNMENT.search(
            "/* This module contains no innerHTML. */"
        )
        is None,
        (
            "The innerHTML detector matches prose. It would "
            "flag the comments that exist to document the "
            "rule."
        ),
    )

    assert_true(
        CLEARING.search(
            'node.innerHTML = "";'
        )
        is not None,
        (
            "The clearing exemption does not recognise the "
            "form this codebase actually uses."
        ),
    )

    unsafe = []

    for path in view_files:

        text = path.read_text(
            encoding="utf-8"
        )

        for number, line in enumerate(
            text.splitlines(),
            start=1,
        ):

            if not ASSIGNMENT.search(
                line
            ):
                continue

            if CLEARING.search(
                line.strip()
            ):
                continue

            unsafe.append(
                (
                    str(
                        path.relative_to(
                            PROJECT_ROOT
                        )
                    ),
                    number,
                    line.strip(),
                )
            )

    assert_equal(
        unsafe,
        [],
        (
            "innerHTML is assigned a value somewhere: "
            f"{unsafe}.\n"
            "Findings carry OCR text, filenames and "
            "extracted values. All of it reaches the DOM as "
            "text nodes."
        ),
    )

    ok(
        f"{len(view_files)} frontend modules contain no "
        f"innerHTML assignment other than clearing a node"
    )


    # ------------------------------------------------------
    # NO PII IN THE CONSOLE
    # ------------------------------------------------------

    logging_hits = []

    for path in view_files:

        text = path.read_text(
            encoding="utf-8"
        )

        for number, line in enumerate(
            text.splitlines(),
            start=1,
        ):

            if re.search(
                r"console\.(log|info|debug|warn)",
                line,
            ):
                logging_hits.append(
                    (
                        path.relative_to(
                            PROJECT_ROOT
                        ),
                        number,
                        line.strip(),
                    )
                )

    assert_equal(
        logging_hits,
        [],
        (
            "The interface logs to the console: "
            f"{logging_hits}.\n"
            "Findings carry names, licence numbers and dates "
            "of birth. None of it belongs in a browser log."
        ),
    )

    ok(
        "no console logging in any frontend module"
    )


    # ------------------------------------------------------
    # THE HARNESS CHECKS
    # ------------------------------------------------------

    required = (
        "normalized_findings",
        "normalized_hierarchy",
        "normalized_evidence_section",
        "normalized_fallback",
        "normalized_quality_not_assessed",
        "normalized_quality_clean",
        "normalized_evidence_in_fields",
    )

    for name in required:

        assert_true(
            name in results,
            (
                f"The workspace harness must run the "
                f"'{name}' check."
            ),
        )

        assert_true(
            "error" not in results[name],
            (
                f"Harness check '{name}' failed:\n"
                f"{results[name]}"
            ),
        )

    ok(
        f"the workspace harness runs all "
        f"{len(required)} normalized findings checks"
    )


    # ------------------------------------------------------
    # THE FIXTURE IS THE REAL SHAPE
    # ------------------------------------------------------
    # The harness hand-writes a normalized view, which would
    # otherwise be a THIRD definition of the envelope -- and a
    # fixture that has drifted away from the backend tests a
    # shape nothing produces, which is worse than no test.
    #
    # So the harness echoes its own key sets back and they are
    # compared against a real normalize_findings result.
    # ------------------------------------------------------

    reference = normalize_findings(
        anomaly_validation={
            "issues": [
                issue(
                    "MISSING_CRITICAL_FIELD",
                    SEVERITY_ERROR,
                    "id_number",
                ),
            ],
        },
        quality=quality_payload(),
    )

    rendered = results[
        "normalized_findings"
    ]

    assert_equal(
        rendered["view_keys"],
        sorted(
            reference.keys()
        ),
        (
            "The harness fixture's summary keys must be the "
            "ones normalize_findings actually produces."
        ),
    )

    assert_equal(
        rendered["finding_keys"],
        sorted(
            reference["findings"][0].keys()
        ),
        (
            "The harness fixture's envelope keys must be the "
            "ones normalize_findings actually produces."
        ),
    )

    ok(
        f"the harness fixture's {len(rendered['view_keys'])} "
        f"summary keys and "
        f"{len(rendered['finding_keys'])} envelope keys match "
        f"a real normalize_findings result"
    )


    # ------------------------------------------------------
    # EVERY FINDING REACHES THE SCREEN
    # ------------------------------------------------------

    assert_equal(
        rendered["item_count"],
        6,
        (
            "All six findings in the view must be rendered. "
            "An earlier version of this panel read the "
            "quality findings from the raw payload instead of "
            "the view and rendered five out of six without "
            "saying so."
        ),
    )

    assert_equal(
        rendered["block_titles"],
        [
            "Record findings",
            "Image quality",
            "Evidence",
        ],
        (
            "Three sections, because the categories answer "
            "different questions. Graded sections first, "
            "ungraded supporting detail last."
        ),
    )

    assert_equal(
        rendered["summary_badges"],
        [
            "2 errors",
            "1 warning",
            "1 notice",
            "2 supporting details",
        ],
        (
            "The summary counts what the producers graded, "
            "and names the ungraded findings as supporting "
            "detail rather than grading them."
        ),
    )

    ok(
        "6 findings rendered across 3 sections, summarised as "
        + ", ".join(
            rendered["summary_badges"]
        )
    )


    # ------------------------------------------------------
    # DOMAIN DETAIL SURVIVES TO THE SCREEN
    # ------------------------------------------------------

    for key, description in (
        (
            "has_expiry_days",
            (
                "the expiry finding's day count "
                "(231 day(s) ago)"
            ),
        ),
        (
            "has_measurement",
            (
                "the quality finding's measurement "
                "(laplacian_variance 9.44 against 40)"
            ),
        ),
        (
            "has_cited_line",
            (
                "the evidence finding's cited OCR line (L9)"
            ),
        ),
    ):

        assert_equal(
            rendered[key],
            True,
            (
                f"{description} must be visible. A shared "
                f"envelope that dropped it would have made "
                f"the finding unverifiable, which is the "
                f"whole reason the domain detail is kept."
            ),
        )

    assert_equal(
        rendered["has_routing_badge"],
        True,
        (
            "A finding known to have driven the machine "
            "decision says so."
        ),
    )

    ok(
        "expiry day count, quality measurement, cited OCR "
        "line and routing effect all reach the screen"
    )


    # ------------------------------------------------------
    # HIERARCHY
    # ------------------------------------------------------

    hierarchy = results[
        "normalized_hierarchy"
    ]

    weights = hierarchy[
        "weights"
    ]

    assert_equal(
        weights,
        [
            "ERROR",
            "WARNING",
            "PLAIN",
            "ERROR",
            "DETAIL",
            "DETAIL",
        ],
        (
            "Within the record section: error, warning, then "
            "the plainly-drawn info. Then the graded quality "
            "error. Then the ungraded detail last.\n"
            "Only errors and warnings carry a weight class, "
            "so nothing else is drawn as an emergency."
        ),
    )

    last_graded = max(
        index
        for index, weight in enumerate(
            weights
        )
        if weight != "DETAIL"
    )

    first_detail = min(
        index
        for index, weight in enumerate(
            weights
        )
        if weight == "DETAIL"
    )

    assert_true(
        first_detail > last_graded,
        (
            "Every ungraded finding must come after every "
            "graded one. Supporting detail above a graded "
            "error inverts the hierarchy the reviewer reads "
            "top-down."
        ),
    )

    for badges in hierarchy["ungraded_badges"]:

        for label in badges:

            assert_true(
                label
                not in (
                    "Error",
                    "Warning",
                    "Info",
                    "Notice",
                    "Critical",
                ),
                (
                    f"An ungraded finding carries a severity "
                    f"badge '{label}'. Even a neutral "
                    f"'Notice' chip reads as a grade, and the "
                    f"evidence validator assigned none."
                ),
            )

    ok(
        "ERROR, WARNING, plain, ERROR, detail, detail -- and "
        "no severity chip on any ungraded finding"
    )


    # ------------------------------------------------------
    # THE EVIDENCE SECTION EXPLAINS ITSELF
    # ------------------------------------------------------

    evidence_section = results[
        "normalized_evidence_section"
    ]

    assert_equal(
        evidence_section["explains_ungraded"],
        True,
        (
            "The panel must say why the evidence findings "
            "carry no severity. Without it, an ungraded "
            "finding beside graded ones reads as an "
            "oversight."
        ),
    )

    ok(
        "the evidence section states that its findings carry "
        "no severity of their own and why"
    )


    # ------------------------------------------------------
    # THE FALLBACK STILL RENDERS
    # ------------------------------------------------------

    fallback = results[
        "normalized_fallback"
    ]

    assert_equal(
        fallback["item_count"],
        2,
        (
            "A payload with no normalized view must still "
            "render its raw anomaly issues. A document with "
            "no analysis row has no view to normalize, and an "
            "empty panel would be the interface losing "
            "findings it was given."
        ),
    )

    assert_equal(
        fallback["titles"],
        [
            "Required field missing",
            "Document has expired",
        ],
        "The fallback renders exactly what it did before.",
    )

    ok(
        "a payload with no normalized view still renders "
        f"{fallback['item_count']} findings through the "
        "unchanged path"
    )


    # ------------------------------------------------------
    # NOT ASSESSED vs ASSESSED-AND-CLEAN, ON SCREEN
    # ------------------------------------------------------

    not_assessed = results[
        "normalized_quality_not_assessed"
    ]

    clean = results[
        "normalized_quality_clean"
    ]

    assert_equal(
        (
            not_assessed["says_not_assessed"],
            not_assessed["says_assessed_clean"],
        ),
        (
            True,
            False,
        ),
        (
            "quality_assessed false must render as NOT "
            "ASSESSED."
        ),
    )

    assert_equal(
        (
            clean["says_not_assessed"],
            clean["says_assessed_clean"],
        ),
        (
            False,
            True,
        ),
        (
            "quality_assessed true with no quality finding "
            "must render as ASSESSED AND CLEAN.\n"
            "Both states have zero quality findings. If the "
            "panel could not tell them apart it would have to "
            "claim an unmeasured image had no problems, which "
            "is a statement nothing supports."
        ),
    )

    ok(
        "on screen: 'Not assessed' for an unmeasured image, "
        "'Assessed. No image quality problems were measured.' "
        "for a clean one"
    )


    # ------------------------------------------------------
    # THE FIELDS PANEL RENDERS BOTH PATHS IDENTICALLY
    # ------------------------------------------------------
    # The fields panel shows evidence problems per field. It
    # used to recover the field from the flag string itself;
    # it now groups the backend's answer, and falls back to
    # its own parser only when no view was sent.
    #
    # Rendering the same three problems both ways and
    # comparing the DOM is what proves the fallback has not
    # drifted -- and the fallback is the path nobody would
    # notice breaking.
    # ------------------------------------------------------

    fields_panel = results[
        "normalized_evidence_in_fields"
    ]

    assert_equal(
        fields_panel["identical"],
        True,
        (
            "The fields panel renders differently from the "
            "normalized view than from the raw flags.\n"
            f"from flags: {fields_panel['from_flags']}\n"
            f"from view:  {fields_panel['from_view']}"
        ),
    )

    assert_equal(
        fields_panel["view_has_line_ref"],
        True,
        (
            "The cited OCR line must survive the normalized "
            "path. Without it the reviewer cannot check the "
            "problem against the page."
        ),
    )

    attributed = [
        row
        for row in fields_panel["from_view"]
        if row["titles"]
    ]

    assert_equal(
        len(
            attributed
        ),
        3,
        (
            "Three evidence problems, each attributed to its "
            "own field."
        ),
    )

    ok(
        "the fields panel renders the same 3 evidence "
        "problems from the normalized view as from the raw "
        "flags, cited line included"
    )

    return results


# ==========================================================
# TEST 14 - THE NORMALIZER DOES NOT DECIDE ANYTHING
# ==========================================================

def test_normalizer_has_no_authority():

    section(
        "TEST 14 - THE NORMALIZER CANNOT CHANGE A DECISION"
    )


    # ------------------------------------------------------
    # IT DOES NOT MUTATE ITS INPUTS
    # ------------------------------------------------------

    issues = [
        issue(
            "DOCUMENT_EXPIRED",
            SEVERITY_WARNING,
            "expiry_date",
        ),
    ]

    anomaly = {
        "issues": issues,
        "valid": True,
        "error_count": 0,
        "warning_count": 1,
    }

    quality = quality_payload(
        findings=[
            quality_finding(),
        ]
    )

    date_validation = {
        "expiry": {
            "value": "2019-01-01",
            "status": "EXPIRED",
            "days_until_expiry": -1978,
        },

        "logical_issues": [],
    }

    decision = {
        "decision": "REVIEW_REQUIRED",
        "review_required": True,
        "priority": "MEDIUM",

        "reason_codes": [
            "DOCUMENT_EXPIRED",
        ],

        "issues": issues,
    }

    before = json.dumps(
        [
            anomaly,
            quality,
            date_validation,
            decision,
        ],
        sort_keys=True,
    )

    normalize_findings(
        anomaly_validation=anomaly,
        quality=quality,
        date_validation=date_validation,
        evidence_flags=[
            "FULL_NAME_EVIDENCE_MISMATCH",
        ],
        review_decision=decision,
    )

    after = json.dumps(
        [
            anomaly,
            quality,
            date_validation,
            decision,
        ],
        sort_keys=True,
    )

    assert_equal(
        after,
        before,
        (
            "The normalizer modified one of its inputs. It "
            "is a read-model builder: the payloads it reads "
            "are the persisted record, and it has no "
            "business changing them."
        ),
    )

    ok(
        "all five input payloads byte-identical after "
        "normalization"
    )


    # ------------------------------------------------------
    # AND IT WRITES NOTHING
    # ------------------------------------------------------
    # A source rule rather than a behavioural one, because
    # the absence of a write cannot be observed by calling
    # the function.
    # ------------------------------------------------------

    module_source = (
        PROJECT_ROOT
        / "backend"
        / "app"
        / "domain"
        / "findings.py"
    ).read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        module_source
    )

    forbidden_names = {
        "session",
        "commit",
        "SessionLocal",
        "execute",
        "add",
        "flush",
    }

    writes = []

    for node in ast.walk(
        tree
    ):

        if isinstance(
            node,
            ast.Attribute,
        ):

            if node.attr in forbidden_names:
                writes.append(
                    node.attr
                )

        if isinstance(
            node,
            (
                ast.Import,
                ast.ImportFrom,
            ),
        ):

            names = [
                alias.name
                for alias in node.names
            ]

            module = getattr(
                node,
                "module",
                "",
            ) or ""

            if (
                "database" in module
                or any(
                    "database" in name
                    for name in names
                )
            ):
                writes.append(
                    f"import {module}"
                )

    # SELF-CHECK: the detector must be able to see a write.
    probe = ast.parse(
        "session.commit()"
    )

    seen = [
        node.attr
        for node in ast.walk(
            probe
        )
        if isinstance(
            node,
            ast.Attribute,
        )
        and node.attr in forbidden_names
    ]

    assert_true(
        seen,
        (
            "The write detector cannot see "
            "session.commit(). It is broken, and every "
            "assertion using it is meaningless."
        ),
    )

    assert_equal(
        writes,
        [],
        (
            "The normalizer touches the database: "
            f"{writes}.\n"
            "It derives a view from values already loaded. A "
            "stored copy would be correct at write time and "
            "wrong as soon as anything else changed."
        ),
    )

    ok(
        "findings.py imports no database module and calls "
        "nothing that could write (detector self-checked "
        "against session.commit())"
    )


# ==========================================================
# MAIN
# ==========================================================

def main() -> int:

    print(
        "=" * 74
    )
    print(
        "PHASE 10.6 - FINDING NORMALIZATION"
    )
    print(
        "=" * 74
    )

    test_definitions_have_one_source()
    test_evidence_normalization()
    test_date_and_logical_normalization()
    test_expiry_detail_preserved()
    test_quality_normalization_and_three_states()
    test_severity_derivation()
    test_ordering()
    test_routing_effect()
    test_outcomes_are_not_findings()
    test_no_invented_score()
    test_browser_agrees_with_backend()
    test_read_path()
    test_interface()
    test_normalizer_has_no_authority()

    print()
    print(
        "=" * 74
    )
    print(
        "[PASS] PHASE 10.6 FINDING NORMALIZATION TEST PASSED"
    )
    print(
        "=" * 74
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
