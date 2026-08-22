import json
import logging
import os

import groq
import httpx

from groq import Groq

from backend.app.core.logging import (
    get_operational_logger,
    log_event,
)
from backend.app.domain.schemas import DocumentExtraction


# ==========================================================
# STRUCTURED OPERATIONAL LOGGER
# PHASE 7C.7d
# ==========================================================

logger = get_operational_logger(
    "extraction"
)


# ==========================================================
# PROVIDER CONFIGURATION
# PHASE 10.4
# ==========================================================
#
# Every value here used to be either hard-coded in the middle
# of extract() or left to a Groq SDK default nobody had looked
# at. Both are now explicit, because they decide the worst-case
# cost of one document and that number has to be knowable.
#
# The defaults are MEASURED, not chosen. See
# scripts/development/extraction_latency_study.py, which timed
# the extraction call alone across twelve documents:
#
#     median   1.18s
#     max     28.11s
#
#
# WHAT THE MAXIMUM ACTUALLY IS
# ----------------------------------------------------------
#
# Not slow generation, and it is worth being exact about this
# because two decisions below depend on it.
#
# The slowest cases came from the SMALLEST prompts in the set
# (8 OCR lines, 90 and 156 characters), which ruled out prompt
# size. So the same document was run three times with only the
# retry count changed:
#
#     max_retries=0    1.32s   ok
#     max_retries=0    0.20s   RateLimitError 429
#     max_retries=1   28.34s   ok
#
# Generation takes about 1.3 seconds. The outliers are the SDK
# sleeping out a 429 Retry-After and then succeeding.
#
# ONE: the retry earns its place. It turned a hard 429 into a
# slow success. Without it the job layer would have re-run the
# whole pipeline, and OCR measured 28s median and 43s maximum
# -- so the alternative to a 27 second sleep is a 28 second OCR
# pass plus a backoff wait.
#
# TWO: a 40 second read timeout is generous, not tight. It
# bounds ONE HTTP request, and a request takes about 1.3
# seconds. The 28s figure is sleep plus request, and httpx
# applies its timeout per request rather than to the whole
# call.
# ==========================================================

DEFAULT_MODEL = "openai/gpt-oss-20b"


# 40 seconds, bounding ONE HTTP request.
#
# Measured generation is about 1.3 seconds, so this is roughly
# thirty times the normal case. That is deliberate headroom for
# a larger prompt or a genuinely slow generation, not padding
# for the 28 second observations -- those were retry sleeps,
# which this timeout does not cover and does not need to.
#
# Not looser, because the read timeout is the largest term in
# the worst-case arithmetic and that arithmetic has to fit
# inside the worker lease.
DEFAULT_READ_TIMEOUT_SECONDS = 40.0


DEFAULT_CONNECT_TIMEOUT_SECONDS = 5.0


# ONE, deliberately, where the Groq SDK default is two.
#
# Keeping a retry at all looks like duplicating the job layer,
# which also handles 429 and 5xx. It is not equivalent in cost.
# An SDK retry re-sends one HTTP request. A job retry re-runs
# the WHOLE pipeline including OCR, which measured 28s median
# and 43s maximum.
#
# The probe above measured this directly: with the retry
# disabled the call failed on a 429 in 0.20 seconds; with one
# retry it succeeded in 28.34. Sleeping out a rate limit is
# strictly cheaper than failing and re-running OCR.
#
# The SECOND retry is the one that does not pay for itself. It
# only helps when two attempts fail consecutively, which is the
# situation the job layer exists for -- it has real backoff and
# it honours Retry-After, neither of which the SDK does beyond
# 60 seconds.
#
# And it is expensive in the one place that matters. Each extra
# SDK retry adds a read timeout plus a sleep to the worst case,
# and the worst case has to fit inside the worker lease:
#
#     retries=1   220s per job attempt
#     retries=2   320s per job attempt
#
# test_call_budget_fits_lease asserts the fit, so this is not
# a comment anybody has to remember to re-check.
DEFAULT_MAX_RETRIES = 1


# Bounded structured-output recovery, unchanged from Phase 2.
#
# This layer owns ONLY malformed or schema-invalid structured
# responses. Everything else -- 429, 5xx, connection, timeout
# -- propagates immediately to the job layer, which owns
# transient infrastructure failure and has the backoff and the
# Retry-After handling for it.
#
# That separation is what stops the two mechanisms
# multiplying. See ExtractionService.call_budget below, which
# computes the maximum from the values actually in force.
DEFAULT_STRUCTURED_OUTPUT_ATTEMPTS = 3


def _configured(
    name: str,
    default,
    cast,
):

    raw = os.getenv(
        name
    )

    if raw is None or not str(
        raw
    ).strip():
        return default


    try:
        return cast(
            str(
                raw
            ).strip()
        )

    except (
        TypeError,
        ValueError,
    ):
        # A malformed setting falls back to the measured
        # default rather than taking the process down. The
        # value is a tuning knob, not a correctness input.
        return default


class ExtractionService:

    def __init__(
        self,
        *,
        model: str | None = None,
        fallback_model: str | None = None,
    ):

        api_key = os.getenv(
            "GROQ_API_KEY"
        )

        if not api_key:

            raise RuntimeError(
                "GROQ_API_KEY was not found. "
                "Make sure .env is loaded before "
                "creating ExtractionService."
            )


        # ==================================================
        # MODEL
        # ==================================================
        #
        # Configurable, and that is not cosmetic. Models get
        # retired: llama-3.3-70b-versatile already returns
        # 404 model_not_found on this account. With the model
        # hard-coded, a retirement is a total outage that
        # needs a code change and a deploy to fix. With it
        # configured, it is an environment variable.
        # ==================================================

        self.model = (
            model
            or _configured(
                "VIGILOX_GROQ_MODEL",
                DEFAULT_MODEL,
                str,
            )
        )


        # ==================================================
        # FALLBACK MODEL
        # ==================================================
        #
        # OFF unless configured. There is no default, and no
        # hard-coded second model.
        #
        # DELIBERATELY NARROW: it is used only when the
        # provider says the primary model does not exist or is
        # not accessible. Not on 429, not on 5xx, not on a
        # timeout -- those are transient and the job layer
        # already owns them, and silently switching models
        # because of a rate limit would change extraction
        # semantics for a reason that had nothing to do with
        # the model.
        #
        # Same strict schema, same evidence contract, same
        # prompt. The only thing that changes is which model
        # is asked, and every use is logged.
        # ==================================================

        self.fallback_model = (
            fallback_model
            or _configured(
                "VIGILOX_GROQ_FALLBACK_MODEL",
                None,
                str,
            )
            or None
        )


        self.max_structured_output_attempts = (
            _configured(
                "VIGILOX_EXTRACTION_ATTEMPTS",
                DEFAULT_STRUCTURED_OUTPUT_ATTEMPTS,
                int,
            )
        )


        self.max_retries = _configured(
            "VIGILOX_GROQ_MAX_RETRIES",
            DEFAULT_MAX_RETRIES,
            int,
        )


        self.read_timeout_seconds = (
            _configured(
                "VIGILOX_GROQ_READ_TIMEOUT_SECONDS",
                DEFAULT_READ_TIMEOUT_SECONDS,
                float,
            )
        )


        self.connect_timeout_seconds = (
            _configured(
                "VIGILOX_GROQ_CONNECT_TIMEOUT_SECONDS",
                DEFAULT_CONNECT_TIMEOUT_SECONDS,
                float,
            )
        )


        # ==================================================
        # THE CLIENT
        # ==================================================
        #
        # Explicit timeout and retry count. The SDK defaults
        # were connect=5 / read=60 / max_retries=2, and the
        # read timeout is the term that decides whether the
        # worst case fits inside a worker lease.
        # ==================================================

        self.client = Groq(
            api_key=api_key,

            max_retries=(
                self.max_retries
            ),

            timeout=httpx.Timeout(
                self.read_timeout_seconds,
                connect=(
                    self.connect_timeout_seconds
                ),
            ),
        )


    # ======================================================
    # WORST-CASE PROVIDER CALLS FOR ONE DOCUMENT
    # PHASE 10.4
    # ======================================================

    def call_budget(
        self,
        *,
        job_attempts: int,
    ) -> dict:

        """
        The maximum real provider work one document can cause.

        A method rather than a comment, so the numbers come
        from the values actually in force and a test can assert
        the result fits inside the worker lease.


        WHY THE TWO RETRY LAYERS DO NOT MULTIPLY
        --------------------------------------------------

        The structured-output loop catches ONLY a 400 whose
        body says JSON generation failed. The SDK does not
        retry 400s, so each of those attempts costs exactly one
        HTTP request.

        Every other provider error -- 429, 5xx, connection,
        timeout -- is not caught by that loop at all. The SDK
        retries it internally and then it propagates straight
        out to the job layer.

        So within one job attempt at most ONE structured-output
        attempt can spend more than a single request, and it is
        necessarily the last one executed. The naive product

            job_attempts x extraction_attempts x (1 + retries)

        is therefore NOT the answer. It overstates it.
        """

        attempts = (
            self.max_structured_output_attempts
        )

        requests_per_create = (
            1
            + self.max_retries
        )

        # (attempts - 1) json failures at one request each,
        # plus one attempt that ends in a retryable error and
        # therefore pays for the SDK retries.
        http_per_job_attempt = (
            (
                attempts
                - 1
            )
            + requests_per_create
        )

        # The SDK sleeps between its own retries: the
        # Retry-After header when it is 60s or less, otherwise
        # exponential backoff capped at 8s. 60 is the
        # pessimistic term.
        sdk_sleep_seconds = 60.0

        seconds_per_job_attempt = (
            (
                attempts
                - 1
            )
            * self.read_timeout_seconds

            + requests_per_create
            * self.read_timeout_seconds

            + self.max_retries
            * sdk_sleep_seconds
        )

        return {
            "model":
                self.model,

            "fallback_model":
                self.fallback_model,

            "structured_output_attempts":
                attempts,

            "sdk_max_retries":
                self.max_retries,

            "read_timeout_seconds":
                self.read_timeout_seconds,

            "http_requests_per_create":
                requests_per_create,

            "http_requests_per_job_attempt":
                http_per_job_attempt,

            "http_requests_per_document":
                http_per_job_attempt
                * job_attempts,

            "seconds_per_job_attempt":
                seconds_per_job_attempt,
        }


    # ======================================================
    # ONE COMPLETION, WITH THE OPTIONAL FALLBACK
    # PHASE 10.4
    # ======================================================

    @staticmethod
    def _is_model_unavailable(
        error: BaseException,
    ) -> bool:

        """
        Whether the provider said the MODEL is the problem.

        Narrow on purpose. Only a 404 whose body names the
        model counts. A 404 on some other path, or any other
        status, is not a reason to change models.
        """

        if not isinstance(
            error,
            groq.NotFoundError,
        ):
            return False


        text = str(
            error
        ).lower()

        return (
            "model_not_found" in text
            or "does not exist" in text
        )


    def _create_completion(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ):

        """
        One structured completion.

        Tries the configured model. If the provider says that
        model does not exist AND a fallback is configured,
        tries the fallback exactly once and logs it.

        No loop, no chain, no third model. A fallback that
        retried would become a second retry layer, and this
        one exists to survive a retired model rather than to
        keep asking.
        """

        def request(
            model: str,
        ):

            return (
                self.client
                .chat
                .completions
                .create(
                    model=model,

                    messages=[
                        {
                            "role": "system",
                            "content": system_prompt,
                        },
                        {
                            "role": "user",
                            "content": user_prompt,
                        },
                    ],

                    # This task is constrained
                    # OCR-to-schema extraction.
                    reasoning_effort="low",

                    # We do not need model reasoning
                    # content in the response.
                    include_reasoning=False,

                    # Gives enough room for a valid
                    # structured JSON response.
                    max_completion_tokens=2048,

                    response_format={
                        "type": "json_schema",

                        "json_schema": {
                            "name":
                                "document_extraction",

                            "strict": True,

                            "schema": (
                                DocumentExtraction
                                .model_json_schema()
                            ),
                        },
                    },
                )
            )


        try:
            return request(
                self.model
            )

        except Exception as error:      # noqa: BLE001

            if not (
                self.fallback_model
                and self._is_model_unavailable(
                    error
                )
            ):
                raise


            log_event(
                logger,

                event=(
                    "llm_model_fallback"
                ),

                message=(
                    "The configured extraction model is "
                    "unavailable. Falling back to the "
                    "configured alternative for this "
                    "request."
                ),

                level=logging.WARNING,

                error_type=(
                    type(
                        error
                    ).__name__
                ),
            )


            return request(
                self.fallback_model
            )


    # ======================================================
    # PREPARE OCR EVIDENCE FOR LLM
    # PHASE 7C.2
    # ======================================================

    def _prepare_llm_input(
        self,
        ocr_lines: list[dict],
    ) -> list[dict]:

        # ==================================================
        # SINGLE SOURCE OF TRUTH FOR EVIDENCE IDS
        # ==================================================
        #
        # New OCRService records already contain:
        #
        # {
        #     "line_id": "L0",
        #     "text": "...",
        #     "confidence": 0.99,
        #     "bbox": [...]
        # }
        #
        # ExtractionService must REUSE that line_id exactly.
        #
        # It must not generate a second independent
        # evidence-ID sequence.
        # ==================================================

        llm_input: list[dict] = []

        seen_line_ids: set[str] = set()


        for (
            index,
            line,
        ) in enumerate(
            ocr_lines
        ):

            # ==============================================
            # BASIC OCR LINE STRUCTURE
            # ==============================================

            if not isinstance(
                line,
                dict,
            ):

                raise ValueError(
                    (
                        "Invalid OCR line at "
                        f"index {index}. "
                        "Expected a dictionary."
                    )
                )


            if (
                "text"
                not in line
            ):

                raise ValueError(
                    (
                        "OCR line at "
                        f"index {index} "
                        "is missing text."
                    )
                )


            if (
                "bbox"
                not in line
            ):

                raise ValueError(
                    (
                        "OCR line at "
                        f"index {index} "
                        "is missing bbox."
                    )
                )


            # ==============================================
            # EXPLICIT OCR LINE ID
            # PHASE 7C.2
            # ==============================================

            line_id = (
                line.get(
                    "line_id"
                )
            )


            # ==============================================
            # LEGACY BACKWARD COMPATIBILITY
            # ==============================================
            #
            # Older tests / stored fixtures may still
            # provide OCR dictionaries without line_id:
            #
            # {
            #     "text": "...",
            #     "confidence": ...,
            #     "bbox": [...]
            # }
            #
            # During Phase 7C.2 migration they remain
            # supported using the historical zero-based
            # positional convention:
            #
            # index 0 -> L0
            # index 1 -> L1
            #
            # New OCRService output always supplies an
            # explicit line_id.
            # ==============================================

            if (
                line_id is None
                or str(
                    line_id
                ).strip()
                == ""
            ):

                line_id = (
                    f"L{index}"
                )


            line_id = (
                str(
                    line_id
                )
                .strip()
            )


            # ==============================================
            # LINE ID FORMAT VALIDATION
            # ==============================================
            #
            # Allowed:
            #
            # L0
            # L1
            # L14
            # L105
            #
            # Rejected:
            #
            # 0
            # 14
            # l14
            # LINE14
            # L
            # L14A
            # ==============================================

            if (
                not line_id.startswith(
                    "L"
                )
                or len(
                    line_id
                ) < 2
                or not line_id[
                    1:
                ].isdigit()
            ):

                raise ValueError(
                    (
                        "Invalid OCR line_id: "
                        f"{line_id}. "
                        "Expected format "
                        "L0, L1, L2, ..."
                    )
                )


            # ==============================================
            # DUPLICATE LINE ID PROTECTION
            # ==============================================

            if (
                line_id
                in seen_line_ids
            ):

                raise ValueError(
                    (
                        "Duplicate OCR line_id "
                        f"detected: {line_id}."
                    )
                )


            seen_line_ids.add(
                line_id
            )


            # ==============================================
            # PREPARE LLM EVIDENCE
            # ==============================================
            #
            # OCR confidence is intentionally NOT included.
            #
            # Confidence remains a deterministic downstream
            # calculation based on validated evidence.
            # ==============================================

            llm_input.append(
                {
                    "line_id":
                        line_id,

                    "text":
                        line[
                            "text"
                        ],

                    "bbox":
                        line[
                            "bbox"
                        ],
                }
            )


        return llm_input


    # ======================================================
    # EXTRACT STRUCTURED DOCUMENT DATA
    # ======================================================

    def extract(
        self,
        ocr_lines: list[dict],
    ) -> DocumentExtraction:

        # ==================================================
        # PREPARE OCR EVIDENCE FOR LLM
        # PHASE 7C.2
        # ==================================================

        llm_input = (
            self._prepare_llm_input(
                ocr_lines
            )
        )


        # ==================================================
        # SERIALIZE OCR EVIDENCE
        # ==========================================================

        document_text = json.dumps(
            llm_input,
            indent=2,
            ensure_ascii=False,
        )


        # ==================================================
        # STRICT EXTRACTION SYSTEM PROMPT
        # ==================================================

        system_prompt = """
You are a strict document information extraction system.

You receive OCR text lines extracted from identity,
security, licence, and compliance documents.

Your job is ONLY to map OCR evidence into the provided schema.

IMPORTANT RULES:

1. Never invent, infer, or guess a field.

2. Every extracted field must be directly supported
by OCR evidence.

3. If a field does not have an explicit supporting label
or clear document context, return null.

4. source_line_ids must include:
   - the value line
   - and the relevant label/context line when available.

Example:

line_id = "L4"
text = "EXPIRES"

line_id = "L5"
text = "24 MAR 2021"

Correct extraction:

expiry_date:
value = 2021-03-24
source_line_ids = ["L4", "L5"]


5. ISSUE DATE RULE:

Never classify an unlabeled date as issue_date.

Only extract issue_date when OCR contains clear evidence such as:

ISSUED
ISSUE DATE
DATE ISSUED
PRINT DATE
PRINTDATE

If the issue-date label and date appear on the same OCR line,
that single line may support both the field context and value.

Example:

line_id = "L4"
text = "PRINTDATE 01/01/2025"

Correct:

issue_date:
value = 2025-01-01
source_line_ids = ["L4"]

Do not return issue_date = null when a clearly labelled
issue or print date is present in OCR evidence.


6. If the same date appears twice in different formats,
do NOT assume they represent two different fields.

Example:

24 MAR 2021
24/03/21

These may be duplicate representations of the same date.


7. Preserve every non-date text value EXACTLY as shown
by OCR.

This applies to:

full_name
licence_number
id_number
issuer

Copy the value characters directly from the supporting OCR
evidence line.

You MAY exclude surrounding label or context words such as:

"ISSUED BY"
"LICENSE"
"LICENCE NO"
"DOB"
"EXPIRES"
"NAME"

But the characters you DO return must appear exactly as
printed, in their original order.

Do NOT reorder, reformat, re-case, expand, abbreviate,
split, join or otherwise tidy a text value.

Names must be copied verbatim, including the original
word order and punctuation. Many identity documents print
names in "SURNAME,GIVENNAME" order. That order is part of
the evidence and must be preserved.

Example — preserve printed name order:

line_id = "L14"
text = "SAMPLE,JANE"

Correct:

full_name = "SAMPLE,JANE"

Incorrect:

full_name = "Jane Sample"

Incorrect:

full_name = "JaneSample"

Incorrect:

full_name = "JANE SAMPLE"


Example — exclude the label, keep the value verbatim:

line_id = "L15"
text = "ISSUED BY TX DPS"

Correct:

issuer = "TX DPS"

Incorrect:

issuer = "ISSUED BY TX DPS"

Incorrect:

issuer = "Texas DPS"


Dates are the ONLY values that may be reformatted.
See rule 8.


8. Normalize clearly supported dates to YYYY-MM-DD.


9. If a date is ambiguous, return null.


10. DOCUMENT CLASSIFICATION RULES:

- If the document contains
  "Security Industry Authority"
  and licence information,
  classify it as "sia_badge".

- Generic private/security licence documents
  without SIA evidence may be "guard_license".

- National identity documents should be "id_card".

- Otherwise return "unknown".


FIELD MAPPING RULES:


A. SIA BADGE

For an SIA badge:

- A number associated with the label "LICENCE"
  must be extracted as licence_number,
  not id_number.

- If OCR contains a licence number that is clearly
  associated with the word "LICENCE",
  extract it as licence_number.

- Do not populate id_number for an SIA badge unless
  the document explicitly identifies a separate value
  as an ID number.

Example:

L0 -> 1099 4265 1706 9065
L1 -> LICENCE

Correct:

licence_number = "1099 4265 1706 9065"
source_line_ids = ["L1", "L0"]

id_number = null


B. GUARD / PRIVATE SECURITY LICENCE

For a guard_license:

- A number associated with labels such as:

  LICENSE
  LICENCE
  LICENSE NUMBER
  LICENCE NUMBER

  must be extracted as licence_number.

- Do NOT classify an isolated numeric value as id_number.

- Do NOT assume that every additional number appearing
  on the document is an ID number.

- Only extract id_number when OCR explicitly identifies
  the number as an ID number, identification number,
  identity number, or equivalent clear context.

Example:

L5 -> LICENSE
L6 -> 12345678
L13 -> 2301

Correct:

licence_number = "12345678"
source_line_ids = ["L5", "L6"]

id_number = null

Incorrect:

id_number = "2301"

because "2301" has no explicit ID label or clear ID context.

Unlabelled numeric OCR values must be ignored unless their
meaning is established by explicit document context.


C. NATIONAL IDENTITY CARD

For a national identity card:

- The primary identity/document number should normally
  be mapped to id_number, not licence_number.

- Do not populate licence_number unless the document
  explicitly represents a licence.

- An identity-card number may be extracted as id_number
  when the document type and surrounding OCR context
  clearly establish that it is the primary identity number.

Never interchange licence_number and id_number merely because
both fields contain numeric identifiers.


11. ISSUER EXTRACTION RULE:

Extract issuer only when the OCR clearly identifies an organization
or authority responsible for issuing the document.

A country name, national slogan, government heading,
document title, republic name, or decorative header alone
must NOT be treated as the issuer.


For an SIA badge:

If "Security Industry Authority" appears in OCR,
extract:

issuer = "Security Industry Authority"

using the exact OCR line containing that organization.


For a security licence:

If OCR explicitly contains evidence such as:

"ISSUED BY TX DPS"

the issuer may be extracted as:

issuer = "TX DPS"

using that source line.


For an identity card:

Do NOT infer the issuer from the country name,
national heading, republic name, document title,
or general government wording.

If a specific issuing authority is not clearly visible
in OCR, return:

issuer = null

Never guess the issuer from general document context alone.


12. DATE OF BIRTH RULE:

Only extract date_of_birth when OCR evidence or sufficiently
clear document context identifies a date as the person's
date of birth.

Strong labels include:

DOB
DATE OF BIRTH
BIRTH DATE

Do not assign an arbitrary or unrelated date to date_of_birth.

If the visible date is likely a DOB based on document structure
but the OCR evidence does not provide reliable semantic context,
use only the available OCR line IDs and do not invent supporting
labels.

Downstream evidence validation may determine whether the
semantic context is strong enough.


13. Do not generate confidence scores.

Confidence is calculated separately from OCR evidence.


14. Ignore decorative, corrupted, or irrelevant OCR text
that does not clearly support a schema field.


15. Never fill a field simply because the schema contains it.

Missing or unsupported information must be returned as null.


SOURCE LINE ID RULES:


16. source_line_ids must contain ONLY exact line IDs
that exist in the provided OCR input.


17. OCR line IDs are strings in this format:

"L0"
"L1"
"L2"
"L3"
"L4"
"L5"

You MUST copy these IDs exactly.


18. Never concatenate, modify, invent,
or transform line IDs.

Example:

line_id = "L4"
text = "EXPIRES"

line_id = "L5"
text = "24 MAR 2021"

Correct:

source_line_ids = ["L4", "L5"]

Incorrect:

source_line_ids = ["L45"]

Incorrect:

source_line_ids = ["4", "5"]

Incorrect:

source_line_ids = [4, 5]


19. For fields where both a label and value are available,
include BOTH line IDs separately.

Example:

"L4" -> EXPIRES
"L5" -> 24 MAR 2021

Correct:

source_line_ids = ["L4", "L5"]


20. Every source_line_id must exactly match one of the
line_id values supplied in the OCR input.


21. Never create a source_line_id that was not present
in the OCR input.


22. FIELD SUPPORT RULE:

A field value is not considered supported merely because
the same text or number appears somewhere in OCR.

The OCR evidence must also support the semantic meaning
of the field whenever that meaning requires context.

Example:

"2301"

does NOT automatically mean:

id_number = "2301"

because there is no ID context.

Similarly:

"01/01/2025"

does NOT automatically mean issue_date unless labels such as:

PRINTDATE
PRINT DATE
ISSUED
ISSUE DATE

establish its meaning.


23. PREFER NULL OVER GUESSING:

When there is uncertainty between:

- licence_number vs id_number
- expiry_date vs issue_date
- issuer vs general government heading
- meaningful field vs irrelevant OCR number

return null for the unsupported field rather than guessing.


24. FINAL EXTRACTION PRINCIPLE:

Your output must reflect what the OCR evidence proves,
not what a typical document might normally contain.

Do not use assumptions about document templates to fill
missing fields.

Only use document context when it clearly establishes
the meaning of OCR evidence.


25. JSON NULL RULE:

When a field is missing or unsupported,
the value MUST be JSON null.

Correct:

"value": null

Incorrect:

"value": "null"

Incorrect:

"value": "None"

Incorrect:

"value": ""

Never represent a missing value using a string.


26. NULL FIELD SOURCE RULE:

If value is null:

source_line_ids MUST be []

Correct:

"value": null
"source_line_ids": []

Incorrect:

"value": null
"source_line_ids": [""]

Incorrect:

"value": null
"source_line_ids": ["L2"]

If value is NOT null:

source_line_ids must contain at least one valid OCR line ID.

Never use an empty string as a source_line_id.


27. TOP-LEVEL FIELD STRUCTURE RULE:

Every document field must appear exactly once as a direct
top-level property of the output document.

The required top-level fields are:

document_type
full_name
licence_number
id_number
expiry_date
date_of_birth
issue_date
issuer

Never nest one document field inside another field.

Incorrect:

expiry_date:
    value = null
    date_of_birth:
        value = null

Correct:

expiry_date:
    value = null
    source_line_ids = []

date_of_birth:
    value = null
    source_line_ids = []

Even when a field is missing, its field object must still
appear in the correct top-level position with:

value = null
source_line_ids = []


28. COMPLETE OUTPUT RULE:

Always return all required schema fields.

Never omit:

full_name
licence_number
id_number
expiry_date
date_of_birth
issue_date
issuer

If a field is unsupported, return:

value = null
source_line_ids = []

Do not omit the field.
Do not place it inside another field.
"""

        # ==================================================
        # USER PROMPT
        # ==================================================

        user_prompt = f"""
Extract structured information from the OCR evidence below.

Follow every rule from the system prompt.

Use ONLY the OCR lines provided below.

Do not invent missing information.

Do not use information that is not present in the OCR evidence.

Return every required schema field exactly once.

Keep every document field at the top level.

For unsupported fields use:
value = null
source_line_ids = []

OCR INPUT:

{document_text}
"""

        # ==================================================
        # STRUCTURED OUTPUT, WITH BOUNDED RECOVERY
        # ==================================================
        #
        # PHASE 10.4. The attempt count and the request itself
        # both moved out of here.
        #
        # The count comes from the service configuration, so
        # call_budget() reports the number actually in force
        # rather than a literal that has drifted from it.
        #
        # The request lives in _create_completion(), which owns
        # the one narrow model fallback. Keeping it out of this
        # loop matters: the fallback must not become a second
        # retry layer, and it cannot if the loop cannot see it.
        #
        # WHAT THIS LOOP OWNS, AND ONLY THIS
        # --------------------------------------------------
        # A 400 whose body says the provider could not generate
        # JSON matching the schema. That is a formatting
        # failure, it is worth asking again, and the SDK does
        # not retry 400s so each attempt is exactly one request.
        #
        # Everything else -- 429, 5xx, connection, timeout --
        # is not caught here at all. It propagates to the job
        # layer, which owns transient infrastructure failure
        # and has the backoff and Retry-After handling for it.
        # That is what keeps the two mechanisms from
        # multiplying.
        # ==================================================

        max_attempts = (
            self.max_structured_output_attempts
        )

        response = None


        for attempt in range(
            1,
            max_attempts + 1,
        ):

            try:

                response = (
                    self._create_completion(
                        system_prompt=(
                            system_prompt
                        ),
                        user_prompt=(
                            user_prompt
                        ),
                    )
                )


                # Successful structured response.
                break


            except groq.BadRequestError as exc:

                error_text = str(
                    exc
                )


                # ------------------------------------------
                # RETRY ONLY STRUCTURED-OUTPUT GENERATION
                # FAILURES
                # ------------------------------------------

                is_json_generation_error = (
                    "json_validate_failed"
                    in error_text
                    or
                    "Failed to generate JSON"
                    in error_text
                    or
                    "Generated JSON does not match"
                    in error_text
                )


                # Genuine unrelated API errors should
                # immediately propagate.
                if not is_json_generation_error:

                    raise


                # Final failed attempt.
                if (
                    attempt
                    == max_attempts
                ):

                    raise RuntimeError(
                        (
                            "Groq failed to generate "
                            "a valid structured document "
                            "after "
                            f"{max_attempts} attempts."
                        )
                    ) from exc


                log_event(
                    logger,

                    event=(
                        "llm_structured"
                        "_extraction_retry"
                    ),

                    message=(
                        "Groq structured output "
                        "generation failed "
                        f"(attempt "
                        f"{attempt}/"
                        f"{max_attempts}). "
                        "Retrying."
                    ),

                    level=(
                        logging.WARNING
                    ),

                    error_type=(
                        type(
                            exc
                        ).__name__
                    ),
                )


        # ==================================================
        # SAFETY CHECK
        # ==================================================

        if response is None:

            raise RuntimeError(
                "Groq failed to produce "
                "a structured response."
            )


        # ==================================================
        # READ STRUCTURED RESPONSE
        # ==================================================

        content = (
            response
            .choices[
                0
            ]
            .message
            .content
        )


        if not content:

            raise ValueError(
                "Groq returned empty "
                "structured output."
            )


        # ==================================================
        # PARSE JSON
        # ==================================================

        try:

            raw_data = json.loads(
                content
            )


        except json.JSONDecodeError as exc:

            raise ValueError(
                "Groq returned invalid JSON."
            ) from exc


        # ==================================================
        # FINAL DETERMINISTIC PYDANTIC VALIDATION
        # ==================================================

        return (
            DocumentExtraction
            .model_validate(
                raw_data
            )
        )