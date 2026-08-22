/* ==========================================================
   VIGILOX VOCABULARY
   PHASE 8.9
   ==========================================================

   One place that turns the backend's machine-readable codes
   into language a reviewer can act on.

   WHY THIS EXISTS
   ----------------------------------------------------------
   The API speaks in stable codes: MISSING_CRITICAL_FIELD,
   FULL_NAME_EVIDENCE_MISMATCH, SKIPPED_INVALID_EVIDENCE. Those
   codes are the contract and must not change.

   Showing them raw in the interface makes a reviewer decode
   the system instead of reading the document. Translating them
   in three different screens guarantees the three screens
   eventually disagree. So the translation lives here once, and
   the Review Queue and the document workspace both use it.


   TWO RULES
   ----------------------------------------------------------
   1. A label NEVER changes what a code means. It restates it.
      No threshold, severity or decision is introduced here.

   2. An unrecognised code is humanised and shown, never
      hidden and never relabelled as something known. If the
      backend gains a code tomorrow, it appears as itself
      rather than silently reading as healthy.
   ========================================================== */

(function (global) {
    "use strict";


    /* ======================================================
       FIELD NAMES
       ======================================================
       The eight correctable fields, matching
       FinalRecordService.FIELD_NAMES.
       ====================================================== */

    var FIELD_LABELS = {
        document_type: "Document Type",
        full_name: "Full Name",
        licence_number: "Licence Number",
        id_number: "ID Number",
        expiry_date: "Expiry Date",
        date_of_birth: "Date of Birth",
        issue_date: "Issue Date",
        issuer: "Issuer"
    };

    /* Every field the evidence validator can flag. Excludes
       document_type, which carries no source_line_ids. */
    var EVIDENCE_FIELDS = [
        "full_name",
        "licence_number",
        "id_number",
        "expiry_date",
        "date_of_birth",
        "issue_date",
        "issuer"
    ];

    function fieldLabel(name) {
        if (!name) {
            return "Document";
        }
        if (
            Object.prototype.hasOwnProperty.call(FIELD_LABELS, name)
        ) {
            return FIELD_LABELS[name];
        }
        return humanize(name);
    }

    function humanize(value) {
        return String(value || "")
            .toLowerCase()
            .split(/[_\s]+/)
            .filter(Boolean)
            .map(function (word) {
                return word.charAt(0).toUpperCase() + word.slice(1);
            })
            .join(" ");
    }


    /* ======================================================
       ANOMALY / REVIEW REASON CODES
       ======================================================
       Emitted by DocumentAnomalyValidator, and reused verbatim
       as ReviewDecisionService reason_codes.

       `title` is a short label for a badge or list row.
       `explanation` says why a reviewer is being asked to look.

       Severity is NOT declared here. The backend sends the
       severity with each issue, and inventing one for a bare
       reason code would be making it up.
       ====================================================== */

    var REASON_CODES = {

        UNKNOWN_DOCUMENT_TYPE: {
            title: "Unrecognised document type",
            explanation:
                "The document could not be classified as a " +
                "Guard Licence, ID Card or SIA Badge, so the " +
                "expected fields for it are unknown."
        },

        MISSING_CRITICAL_FIELD: {
            title: "Required field missing",
            explanation:
                "A field this document type must carry was " +
                "not found at all."
        },

        CRITICAL_FIELD_NOT_TRUSTED: {
            title: "Required field not supported by evidence",
            explanation:
                "The value was read, but it could not be " +
                "matched back to the OCR text it should have " +
                "come from."
        },

        LOW_CRITICAL_FIELD_CONFIDENCE: {
            title: "Low confidence on a required field",
            explanation:
                "The OCR text behind a required field was " +
                "read with low confidence."
        },

        EXTRACTED_FIELD_INVALID_EVIDENCE: {
            title: "Field evidence did not validate",
            explanation:
                "A value exists, but its supporting OCR " +
                "evidence failed validation."
        },

        DUPLICATE_IDENTIFIER_MAPPING: {
            title: "Same identifier used twice",
            explanation:
                "One identifier value was mapped to two " +
                "different fields, so at least one of them " +
                "is wrong."
        },

        DOCUMENT_EXPIRED: {
            title: "Document has expired",
            explanation:
                "The expiry date read from the document is " +
                "in the past."
        },

        DOCUMENT_EXPIRING_SOON: {
            title: "Document expires soon",
            explanation:
                "The expiry date read from the document is " +
                "close."
        },

        FUTURE_DATE_OF_BIRTH: {
            title: "Date of birth in the future",
            explanation:
                "A date of birth cannot be later than today."
        },

        FUTURE_ISSUE_DATE: {
            title: "Issue date in the future",
            explanation:
                "The document reports being issued after " +
                "today."
        },

        EXPIRY_BEFORE_ISSUE_DATE: {
            title: "Expires before it was issued",
            explanation:
                "The expiry date is earlier than the issue " +
                "date."
        },

        DOB_AFTER_ISSUE_DATE: {
            title: "Born after the document was issued",
            explanation:
                "The date of birth is later than the issue " +
                "date."
        },

        DOB_AFTER_EXPIRY_DATE: {
            title: "Born after the document expired",
            explanation:
                "The date of birth is later than the expiry " +
                "date."
        }
    };


    /* A per-field date format issue: EXPIRY_DATE_INVALID_FORMAT */
    var INVALID_FORMAT_SUFFIX = "_INVALID_FORMAT";

    function describeReasonCode(code) {
        var key = String(code || "").toUpperCase();

        if (
            Object.prototype.hasOwnProperty.call(REASON_CODES, key)
        ) {
            return {
                code: key,
                known: true,
                field: null,
                title: REASON_CODES[key].title,
                explanation: REASON_CODES[key].explanation
            };
        }

        /* {FIELD}_INVALID_FORMAT is generated per date field, so
           it is matched by shape rather than enumerated. */
        if (
            key.length > INVALID_FORMAT_SUFFIX.length &&
            key.slice(-INVALID_FORMAT_SUFFIX.length) ===
                INVALID_FORMAT_SUFFIX
        ) {
            var field = key
                .slice(0, key.length - INVALID_FORMAT_SUFFIX.length)
                .toLowerCase();

            return {
                code: key,
                known: true,
                field: field,
                title:
                    fieldLabel(field) + " is not a valid date",
                explanation:
                    "The value read for " +
                    fieldLabel(field) +
                    " is not a usable YYYY-MM-DD date."
            };
        }

        /* Unknown. Shown as itself: a future backend code must
           not be quietly presented as something familiar. */
        return {
            code: key,
            known: false,
            field: null,
            title: humanize(key) || "Validation issue",
            explanation: null
        };
    }


    /* ======================================================
       EVIDENCE FLAGS
       ======================================================
       EvidenceValidator returns a flat list of strings:

           FULL_NAME_EVIDENCE_MISMATCH
           EXPIRY_DATE_NO_EVIDENCE
           ISSUER_CONTEXT_MISSING
           FULL_NAME_INVALID_SOURCE_LINE_ID:L9

       Field and kind are recovered by matching against the
       known field names and the known suffixes, rather than by
       splitting on underscores, because field names contain
       underscores themselves.
       ====================================================== */

    var EVIDENCE_KINDS = {

        NO_EVIDENCE: {
            title: "No evidence recorded",
            explanation:
                "The value was extracted without naming any " +
                "OCR line as its source."
        },

        NO_VALID_EVIDENCE: {
            title: "No usable evidence",
            explanation:
                "Every OCR line cited for this value turned " +
                "out to be unusable."
        },

        EVIDENCE_MISMATCH: {
            title: "Value not found in its evidence",
            explanation:
                "The extracted value does not appear in the " +
                "OCR text it cites."
        },

        CONTEXT_MISSING: {
            title: "Expected context missing",
            explanation:
                "The cited OCR text does not contain the " +
                "label this field is normally printed with."
        },

        INVALID_SOURCE_LINE_ID: {
            title: "Cited OCR line does not exist",
            explanation:
                "The value cites an OCR line that is not " +
                "part of this document's OCR output."
        },

        INVALID_EVIDENCE_TEXT: {
            title: "Cited OCR line has no text",
            explanation:
                "The cited OCR line carries no readable text."
        }
    };


    var EVIDENCE_KIND_NAMES = Object.keys(EVIDENCE_KINDS);


    /* ======================================================
       PARSING MOVED TO THE BACKEND
       PHASE 10.6
       ======================================================
       The field list and the kind list above used to be the
       ONLY place a flag string was taken apart, which made
       this file a second, independent definition of what
       backend/app/services/evidence_validator.py emits -- in
       a language that validator cannot be tested against.

       That is the same shape of problem PHASE 10.5 found in
       the duplicated critical-field list, where a definitional
       gap hid a real critical-field error.

       backend/app/domain/findings.py now owns the structure
       and ships it in the normalized findings view:

           {code, category, severity, message, field, source,
            affects_routing, detail: {flag, kind,
            source_line_id, known}}

       So describeEvidenceFlag accepts EITHER:

         - a parsed object from that view, which is the
           authoritative path, or

         - a raw flag string, which is the fallback for the
           analysis.evidence_flags payload that older
           consumers still read.

       The local parser is kept only for that fallback.
       test_phase10_finding_normalization runs both parsers
       over every flag the validator can emit and asserts they
       agree, so the fallback cannot quietly drift away from
       the definition it mirrors.

       What stays here is what belongs here: the human title
       and the explanation for each kind.
       ====================================================== */

    function describeEvidenceFlag(flag) {
        /* Already structured by the backend. Trusted as-is:
           re-parsing a parsed finding would reintroduce
           exactly the second opinion this removes.

           A detail block the backend could not parse arrives
           with kind null. It is described from its raw flag
           rather than discarded -- the validator still said
           something, and showing nothing would be worse than
           showing it unlabelled. */
        if (flag && typeof flag === "object") {
            var kind =
                typeof flag.kind === "string" ? flag.kind : null;

            var known =
                kind !== null &&
                Object.prototype.hasOwnProperty.call(
                    EVIDENCE_KINDS,
                    kind
                );

            if (kind === null) {
                return describeEvidenceFlag(
                    String(flag.flag || "")
                );
            }

            return {
                flag: String(flag.flag || kind),
                known: known,
                field: flag.field || null,
                kind: kind,
                detail: flag.source_line_id || null,
                title: known
                    ? EVIDENCE_KINDS[kind].title
                    : humanize(kind) || "Evidence issue",
                explanation: known
                    ? EVIDENCE_KINDS[kind].explanation
                    : null
            };
        }

        var raw = String(flag || "");
        var parts = raw.split(":");
        var body = parts[0].toUpperCase();
        var detail = parts.length > 1 ? parts.slice(1).join(":") : null;

        var match = null;

        EVIDENCE_FIELDS.forEach(function (field) {
            var prefix = field.toUpperCase() + "_";

            if (body.indexOf(prefix) !== 0) {
                return;
            }

            var kind = body.slice(prefix.length);

            if (EVIDENCE_KIND_NAMES.indexOf(kind) === -1) {
                return;
            }

            /* Longest field prefix wins. No two current field
               names nest, but relying on that would be a trap
               for a future field. */
            if (!match || prefix.length > match.prefixLength) {
                match = {
                    prefixLength: prefix.length,
                    field: field,
                    kind: kind
                };
            }
        });

        if (!match) {
            return {
                flag: raw,
                known: false,
                field: null,
                kind: null,
                detail: detail,
                title: humanize(body) || "Evidence issue",
                explanation: null
            };
        }

        return {
            flag: raw,
            known: true,
            field: match.field,
            kind: match.kind,
            detail: detail,
            title: EVIDENCE_KINDS[match.kind].title,
            explanation: EVIDENCE_KINDS[match.kind].explanation
        };
    }

    /** Group flags by the field they belong to. */
    function evidenceFlagsByField(flags) {
        var grouped = {};

        (flags || []).forEach(function (flag) {
            var described = describeEvidenceFlag(flag);
            var key = described.field || "_unattributed";

            grouped[key] = grouped[key] || [];
            grouped[key].push(described);
        });

        return grouped;
    }


    /* ======================================================
       FINDING CATEGORIES
       PHASE 10.6
       ======================================================
       The five kinds of question the pipeline can answer.
       They are kept apart in the interface because they are
       not comparable: a blurred photograph of a valid licence
       and a licence whose dates contradict each other need
       different things done about them, and one heading for
       both would lose the distinction that makes either
       actionable.

       Backend authority: backend/app/domain/findings.py
       assigns the category. Nothing here decides one.
       ====================================================== */

    var FINDING_CATEGORIES = {

        QUALITY: {
            title: "Image quality",
            question: "Can this photograph be read reliably?"
        },

        EVIDENCE: {
            title: "Evidence",
            question:
                "Was each value actually read off the page?"
        },

        ANOMALY: {
            title: "Record consistency",
            question:
                "Does the extracted record hold together?"
        },

        DATE: {
            title: "Dates",
            question: "Do the dates make sense together?"
        },

        EXPIRY: {
            title: "Expiry",
            question: "Is the document still in date?"
        }
    };

    function describeFindingCategory(name) {
        var key = String(name || "").toUpperCase();

        if (
            Object.prototype.hasOwnProperty.call(
                FINDING_CATEGORIES,
                key
            )
        ) {
            return {
                category: key,
                title: FINDING_CATEGORIES[key].title,
                question: FINDING_CATEGORIES[key].question
            };
        }

        /* An unrecognised category is shown as itself. A new
           one added on the backend appears under its own
           humanised heading rather than vanishing. */
        return {
            category: key || null,
            title: humanize(key) || "Findings",
            question: null
        };
    }


    /* ======================================================
       FIELD CONFIDENCE STATUS
       ======================================================
       ConfidenceService emits exactly these four.
       ====================================================== */

    var CONFIDENCE_STATUS = {

        VALID: {
            label: "Evidence verified",
            tone: "success",
            explanation:
                "The value was matched to its OCR evidence " +
                "and carries an OCR confidence."
        },

        NOT_EXTRACTED: {
            label: "Not detected",
            tone: "neutral",
            explanation:
                "No value was found for this field."
        },

        INVALID_EVIDENCE: {
            label: "Evidence failed",
            tone: "danger",
            explanation:
                "A value exists, but evidence validation " +
                "rejected it, so no confidence is reported."
        },

        NO_CONFIDENCE: {
            label: "No confidence available",
            tone: "warning",
            explanation:
                "Evidence validated, but no usable OCR " +
                "confidence was recorded for it."
        }
    };

    function describeConfidenceStatus(status) {
        var key = String(status || "").toUpperCase();

        if (
            Object.prototype.hasOwnProperty.call(
                CONFIDENCE_STATUS,
                key
            )
        ) {
            return Object.assign(
                { status: key, known: true },
                CONFIDENCE_STATUS[key]
            );
        }

        return {
            status: key,
            known: false,
            label: humanize(key) || "Unknown",
            tone: "neutral",
            explanation: null
        };
    }


    /* ======================================================
       DATE FIELD STATUS
       ======================================================
       DateLogicalValidator emits exactly these four per date
       field.
       ====================================================== */

    var DATE_FIELD_STATUS = {

        VALID_DATE: {
            label: "Valid date",
            tone: "success"
        },

        NOT_EXTRACTED: {
            label: "Not detected",
            tone: "neutral"
        },

        SKIPPED_INVALID_EVIDENCE: {
            label: "Skipped, evidence failed",
            tone: "warning"
        },

        INVALID_DATE_FORMAT: {
            label: "Unusable date format",
            tone: "danger"
        }
    };

    function describeDateStatus(status) {
        var key = String(status || "").toUpperCase();

        if (
            Object.prototype.hasOwnProperty.call(
                DATE_FIELD_STATUS,
                key
            )
        ) {
            return Object.assign(
                { status: key, known: true },
                DATE_FIELD_STATUS[key]
            );
        }

        return {
            status: key,
            known: false,
            label: humanize(key) || "Unknown",
            tone: "neutral"
        };
    }


    /* ======================================================
       FINAL STATUS
       ======================================================
       The six values FinalRecordService can resolve. `usable`
       mirrors the service's own is_usable, so the wording and
       the record cannot disagree.
       ====================================================== */

    var FINAL_STATUS = {

        AUTO_ACCEPTED: {
            label: "Auto Accepted",
            usable: true,
            note:
                "VIGILOX confirmed every required field " +
                "against its own OCR evidence, so no human " +
                "review was required. These values are " +
                "available for downstream use."
        },

        PENDING_REVIEW: {
            label: "Pending Review",
            usable: false,
            note:
                "VIGILOX could not confirm this document on " +
                "its own evidence. No effective values are " +
                "published until a reviewer decides."
        },

        /* PHASE 10.2. usable false, matching the record's own
           is_usable. The note says what happened and does not
           promise that retrying will help, because reprocessing
           the same file reaches the same answer. */
        UNSUPPORTED: {
            label: "Unsupported",
            usable: false,
            note:
                "VIGILOX could not reliably identify this " +
                "file as a Security Guard License, an ID " +
                "Card or an SIA Badge, so no usable record " +
                "was produced. Nothing is wrong with the " +
                "upload itself, and no review is pending."
        },

        APPROVED: {
            label: "Approved",
            usable: true,
            note:
                "A reviewer accepted the machine values " +
                "without changing any of them."
        },

        CORRECTED: {
            label: "Corrected",
            usable: true,
            note:
                "A reviewer replaced one or more machine " +
                "values. The machine reading is preserved " +
                "alongside the correction."
        },

        REJECTED: {
            label: "Rejected",
            usable: false,
            note:
                "A reviewer rejected this document. It is " +
                "final, but nothing from it should be used " +
                "downstream."
        }
    };

    function describeFinalStatus(status) {
        var key = String(status || "").toUpperCase();

        if (
            Object.prototype.hasOwnProperty.call(FINAL_STATUS, key)
        ) {
            return Object.assign(
                { status: key, known: true },
                FINAL_STATUS[key]
            );
        }

        return {
            status: key,
            known: false,
            label: humanize(key) || "Unknown",
            usable: false,
            note: null
        };
    }


    /* ======================================================
       MACHINE REVIEW DECISION
       PHASE 10.2
       ======================================================
       The three values ReviewDecisionService and the Phase
       10.2 classification policy can write to
       review_decision.decision.

       Added when the third value arrived. Two values could be
       humanised by rule: "Auto Accept" and "Review Required"
       read correctly on their own. UNSUPPORTED_DOCUMENT
       humanises to "Unsupported Document", which is accurate
       but says nothing about why no reviewer is queued, and
       that is the part an operator needs.
       ====================================================== */

    var MACHINE_DECISIONS = {

        AUTO_ACCEPT: {
            label: "Auto Accept",
            explanation:
                "Every required field was confirmed against " +
                "the OCR evidence on the document itself."
        },

        REVIEW_REQUIRED: {
            label: "Review Required",
            explanation:
                "At least one finding needs a person to look " +
                "at this document."
        },

        UNSUPPORTED_DOCUMENT: {
            label: "Unsupported Document",
            explanation:
                "This file is not one of the supported " +
                "document types, so there is nothing for a " +
                "reviewer to check. It stays listed and " +
                "auditable but is not queued for review."
        }
    };

    function describeMachineDecision(decision) {
        var key = String(decision || "").toUpperCase();

        if (
            Object.prototype.hasOwnProperty.call(
                MACHINE_DECISIONS,
                key
            )
        ) {
            return Object.assign(
                { decision: key, known: true },
                MACHINE_DECISIONS[key]
            );
        }

        return {
            decision: key,
            known: false,
            label: humanize(key) || "Unknown",
            explanation: null
        };
    }


    /* ======================================================
       CLASSIFICATION OUTCOME
       PHASE 10.2
       ======================================================
       The three outcomes backend/app/domain/classification.py
       can derive.

       These describe whether the file is a supported document.
       They are NOT image quality, which is a separate question
       answered separately: a blurry Guard Licence is still a
       Guard Licence, and a sharp receipt is still unsupported.
       ====================================================== */

    var CLASSIFICATION_OUTCOMES = {

        SUPPORTED: {
            label: "Supported document",
            tone: "success",
            explanation:
                "Identified as one of the supported document " +
                "types."
        },

        UNSUPPORTED: {
            label: "Unsupported document",
            tone: "neutral",
            explanation:
                "Not one of the supported document types. No " +
                "usable record was produced, and no review " +
                "is pending."
        },

        UNCLASSIFIED_NEEDS_REVIEW: {
            label: "Could not be classified",
            tone: "warning",
            explanation:
                "The document type could not be determined, " +
                "and the image was too degraded to rule out " +
                "a supported document. A reviewer needs to " +
                "look at it."
        }
    };

    function describeClassification(outcome) {
        var key = String(outcome || "").toUpperCase();

        if (
            Object.prototype.hasOwnProperty.call(
                CLASSIFICATION_OUTCOMES,
                key
            )
        ) {
            return Object.assign(
                { outcome: key, known: true },
                CLASSIFICATION_OUTCOMES[key]
            );
        }

        return {
            outcome: key,
            known: false,
            label: humanize(key) || "Unknown",
            tone: "neutral",
            explanation: null
        };
    }


    /* ======================================================
       IMAGE QUALITY FINDINGS
       PHASE 10.1 / 10.2
       ======================================================
       The six codes document_quality_service can emit.

       Severity is NOT declared here. The backend sends the
       severity with each finding, and the measured threshold
       with it. Restating either would be inventing it.

       Every message answers "can this image be read?", and
       none of them says the document is invalid. A quality
       warning is not a verdict on the document.
       ====================================================== */

    var QUALITY_CODES = {

        IMAGE_TOO_SMALL: {
            title: "Image is very small",
            explanation:
                "The image has too few pixels for text to be " +
                "read reliably."
        },

        IMAGE_BLURRY: {
            title: "Image is blurred",
            explanation:
                "Edge detail is low, which usually means " +
                "camera shake or a missed focus."
        },

        IMAGE_UNREADABLE: {
            title: "Image could not be read",
            explanation:
                "Almost no edge detail was measured. Any text " +
                "extracted from this image should be treated " +
                "as unverified."
        },

        IMAGE_TOO_DARK: {
            title: "Image is underexposed",
            explanation:
                "The image is dark enough that text contrast " +
                "is reduced."
        },

        IMAGE_OVEREXPOSED: {
            title: "Image is overexposed",
            explanation:
                "The image is bright enough that text may be " +
                "washed out."
        },

        ROTATION_CONCERN: {
            title: "Document appears rotated",
            /* Not a repeat of the backend sentence, which
               already says a straighter scan reads better.
               This says what was measured, so the number
               beside it can be read. */
            explanation:
                "The dominant text lines sit at an angle to " +
                "the horizontal by more than the configured " +
                "threshold."
        }
    };

    function describeQualityCode(code) {
        var key = String(code || "").toUpperCase();

        if (
            Object.prototype.hasOwnProperty.call(
                QUALITY_CODES,
                key
            )
        ) {
            return Object.assign(
                { code: key, known: true },
                QUALITY_CODES[key]
            );
        }

        return {
            code: key,
            known: false,
            title: humanize(key) || "Image quality finding",
            explanation: null
        };
    }


    /* ======================================================
       WHAT FIELD CONFIDENCE MEANS
       PHASE 10.5
       ======================================================
       Stated once, here, because it is the single easiest
       number on the screen to misread.

       MEASURED, on all 63 evaluation documents and 441 fields
       (scripts/development/confidence_calibration_study.py):

         - Confidence runs from 0.944 to 0.999999, median
           0.9999. There is almost no spread.

         - Of the four incorrect fields that carried a
           confidence, the mean confidence was HIGHER than for
           correct fields, and the rank statistic came out at
           0.36 where 0.50 would mean no information at all.

         - The most confident error was a CRITICAL field, an
           expiry date, wrong at the 92nd percentile: it read
           2025-10-06 where the document said 2025-06-10.

       The reason is structural rather than unlucky. Confidence
       is the OCR character confidence of the lines a value
       cites, so it measures whether the TEXT WAS READ. It
       cannot measure whether the text was ASSIGNED to the
       right field, because a misassignment cites a real line
       whose characters were read perfectly -- a transposed day
       and month, or an issuer that kept its label.

       So: high support, and possibly still wrong.
       ====================================================== */

    var CONFIDENCE_MEANING = {
        label: "OCR evidence support",

        summary:
            "How cleanly OCR read the text a value was " +
            "taken from.",

        caveat:
            "It is not the probability that the value is " +
            "correct. A date can be read perfectly and still " +
            "be recorded in the wrong field, and measurement " +
            "on the evaluation set found exactly that -- " +
            "including a critical field that was wrong while " +
            "carrying one of the highest support scores.",

        no_document_score:
            "There is no document-level confidence score. " +
            "Averaging per-field numbers would invent a " +
            "statistic the system does not define."
    };


    /* ======================================================
       DUPLICATE SOURCE
       PHASE 10.3
       ======================================================
       The two outcomes an upload of already-seen bytes can
       produce.

       Neither is an error and neither is an accusation.
       Uploading the same file twice is, overwhelmingly,
       uploading the same file twice -- so the wording says
       what happened and what can be done about it, and says
       nothing about fraud, tampering or suspicion.
       ====================================================== */

    var DUPLICATE_CODES = {

        DUPLICATE_DOCUMENT: {
            title: "Duplicate document detected",
            tone: "info",
            explanation:
                "This exact file has already been " +
                "processed. Nothing is wrong with it."
        },

        DUPLICATE_IN_PROGRESS: {
            title: "Already being processed",
            tone: "info",
            explanation:
                "This exact file is being processed right " +
                "now. Following the existing job is faster " +
                "than starting another one."
        }
    };

    function describeDuplicate(code) {
        var key = String(code || "").toUpperCase();

        if (
            Object.prototype.hasOwnProperty.call(
                DUPLICATE_CODES,
                key
            )
        ) {
            return Object.assign(
                { code: key, known: true },
                DUPLICATE_CODES[key]
            );
        }

        return {
            code: key,
            known: false,
            title: humanize(key) || "Duplicate",
            tone: "info",
            explanation: null
        };
    }

    function isDuplicateCode(code) {
        return Object.prototype.hasOwnProperty.call(
            DUPLICATE_CODES,
            String(code || "").toUpperCase()
        );
    }


    /* ======================================================
       HUMAN REVIEW ACTIONS
       ====================================================== */

    var HUMAN_ACTIONS = {

        APPROVE: {
            label: "Approve",
            pastLabel: "Approved",
            summary:
                "Accept every machine-extracted value exactly " +
                "as it was read."
        },

        CORRECT: {
            label: "Correct",
            pastLabel: "Corrected",
            summary:
                "Replace one or more values. The machine " +
                "reading is kept and the correction is " +
                "recorded against you."
        },

        REJECT: {
            label: "Reject",
            pastLabel: "Rejected",
            summary:
                "Mark this document unusable. No effective " +
                "values will be published."
        }
    };

    function describeHumanAction(action) {
        var key = String(action || "").toUpperCase();

        if (
            Object.prototype.hasOwnProperty.call(HUMAN_ACTIONS, key)
        ) {
            return Object.assign(
                { action: key, known: true },
                HUMAN_ACTIONS[key]
            );
        }

        return {
            action: key,
            known: false,
            label: humanize(key) || "Unknown",
            pastLabel: humanize(key) || "Unknown",
            summary: null
        };
    }


    /* ======================================================
       DOCUMENT JOB STATUS
       PHASE 9.4
       ======================================================
       The five authoritative job states, and the advisory
       stage within PROCESSING.

       These labels replace what the Upload page used to do,
       which was rotate five invented sentences on a 2.6
       second timer -- "Extracting and validating
       information" appeared whether or not extraction had
       started, because nothing was telling the page
       anything. It read as progress and was decoration.

       Every string below now corresponds to a value the
       backend actually writes to the job row.

       There is still no percentage. The pipeline cannot
       report progress within a stage, so any number would be
       invented, and a stage name is the honest resolution.
       ====================================================== */

    var JOB_STATUS = {
        QUEUED: {
            label: "Queued",
            detail: "Waiting for a processing worker."
        },
        PROCESSING: {
            label: "Processing",
            detail: "Reading and validating the document."
        },
        RETRY_WAIT: {
            label: "Waiting to retry",
            detail:
                "The last attempt did not succeed. " +
                "This document will be retried " +
                "automatically."
        },
        COMPLETED: {
            label: "Completed",
            detail: "The document has been processed."
        },
        FAILED: {
            label: "Failed",
            detail: "The document could not be processed."
        }
    };

    /* Advisory only. A stale stage is cosmetic, so these are
       used for a label and never to decide what the page
       does. */
    var JOB_STAGES = {
        READING: "Reading the uploaded file",
        OCR: "Reading text from the document",
        EXTRACTING: "Extracting information",
        VALIDATING: "Validating the result",
        PERSISTING: "Saving the result"
    };

    function describeJobStatus(status, stage) {

        var known = Object.prototype.hasOwnProperty.call(
            JOB_STATUS,
            String(status)
        );

        var entry = known
            ? JOB_STATUS[String(status)]
            : null;

        /* An unrecognised status is humanised, never
           relabelled as something known. A new backend state
           reaching an old page should read as itself. */
        var label = entry
            ? entry.label
            : humanize(status);

        var detail = entry
            ? entry.detail
            : "";

        /* The stage refines the label only while PROCESSING.
           On any other status a stage is stale by
           definition. */
        if (
            String(status) === "PROCESSING" &&
            stage &&
            Object.prototype.hasOwnProperty.call(
                JOB_STAGES,
                String(stage)
            )
        ) {
            detail = JOB_STAGES[String(stage)];
        }

        return {
            known: known,
            label: label,
            detail: detail
        };
    }


    global.VigiloxVocabulary = {
        JOB_STATUS: JOB_STATUS,
        JOB_STAGES: JOB_STAGES,
        describeJobStatus: describeJobStatus,

        FIELD_LABELS: FIELD_LABELS,
        EVIDENCE_FIELDS: EVIDENCE_FIELDS,
        REASON_CODES: REASON_CODES,
        EVIDENCE_KINDS: EVIDENCE_KINDS,
        CONFIDENCE_STATUS: CONFIDENCE_STATUS,
        DATE_FIELD_STATUS: DATE_FIELD_STATUS,
        FINAL_STATUS: FINAL_STATUS,
        MACHINE_DECISIONS: MACHINE_DECISIONS,
        CLASSIFICATION_OUTCOMES: CLASSIFICATION_OUTCOMES,
        QUALITY_CODES: QUALITY_CODES,
        CONFIDENCE_MEANING: CONFIDENCE_MEANING,
        DUPLICATE_CODES: DUPLICATE_CODES,
        HUMAN_ACTIONS: HUMAN_ACTIONS,

        humanize: humanize,
        fieldLabel: fieldLabel,
        describeReasonCode: describeReasonCode,
        describeEvidenceFlag: describeEvidenceFlag,
        evidenceFlagsByField: evidenceFlagsByField,
        FINDING_CATEGORIES: FINDING_CATEGORIES,
        describeFindingCategory: describeFindingCategory,
        describeConfidenceStatus: describeConfidenceStatus,
        describeDateStatus: describeDateStatus,
        describeFinalStatus: describeFinalStatus,
        describeMachineDecision: describeMachineDecision,
        describeClassification: describeClassification,
        describeQualityCode: describeQualityCode,
        describeDuplicate: describeDuplicate,
        isDuplicateCode: isDuplicateCode,
        describeHumanAction: describeHumanAction
    };

}(typeof window !== "undefined" ? window : globalThis));
