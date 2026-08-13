import json
import os

from groq import Groq

from src.schemas import (
    DocumentExtraction,
)


class ExtractionService:

    def __init__(self):

        api_key = os.getenv(
            "GROQ_API_KEY"
        )

        if not api_key:

            raise RuntimeError(
                "GROQ_API_KEY was not found. "
                "Make sure .env is loaded before "
                "creating ExtractionService."
            )

        self.client = Groq(
            api_key=api_key
        )


    # ======================================================
    # EXTRACT STRUCTURED DOCUMENT DATA
    # ======================================================

    def extract(
        self,
        ocr_lines: list[dict],
    ) -> DocumentExtraction:

        # --------------------------------------------------
        # Prepare OCR evidence for LLM
        # --------------------------------------------------

        llm_input: list[dict] = []


        for index, line in enumerate(
            ocr_lines
        ):

            llm_input.append(
                {
                    "line_id":
                        f"L{index}",

                    "text":
                        line["text"],

                    "bbox":
                        line["bbox"],
                }
            )


        document_text = json.dumps(
            llm_input,
            indent=2,
            ensure_ascii=False,
        )


        # --------------------------------------------------
        # Strict extraction prompt
        # --------------------------------------------------

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

5. Never classify an unlabeled date as issue_date.

Only extract issue_date when OCR contains clear evidence such as:

ISSUED
ISSUE DATE
DATE ISSUED
PRINT DATE

6. If the same date appears twice in different formats,
do NOT assume they represent two different fields.

Example:

24 MAR 2021
24/03/21

These may be duplicate representations of the same date.

7. Preserve licence numbers and ID numbers exactly
as shown by OCR.

8. Normalize clearly supported dates to YYYY-MM-DD.

9. If a date is ambiguous, return null.

10. Document classification rules:

- If the document contains
  "Security Industry Authority"
  and licence information,
  classify it as "sia_badge".

- Generic private/security licence documents
  without SIA evidence may be "guard_license".

- National identity documents should be "id_card".

- Otherwise return "unknown".

11. Do not generate confidence scores.

12. Ignore decorative or irrelevant OCR text.

13. Never fill a field simply because the schema contains it.
Missing information must be returned as null.

14. source_line_ids must contain ONLY exact line IDs
that exist in the provided OCR input.

15. OCR line IDs are strings in this format:

"L0"
"L1"
"L2"
"L3"
"L4"
"L5"

You MUST copy these IDs exactly.

16. Never concatenate, modify, invent, or transform line IDs.

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

17. For fields where both a label and value are available,
include BOTH line IDs separately.

Example:

"L4" -> EXPIRES
"L5" -> 24 MAR 2021

Correct:
source_line_ids = ["L4", "L5"]

18. Every source_line_id must exactly match one of the
line_id values supplied in the OCR input.

19. Never create a source_line_id that was not present
in the OCR input.
"""


        # --------------------------------------------------
        # Groq structured output
        # --------------------------------------------------

        response = (
            self.client.chat.completions.create(
                model="openai/gpt-oss-20b",

                messages=[
                    {
                        "role": "system",
                        "content":
                            system_prompt,
                    },

                    {
                        "role": "user",
                        "content":
                            document_text,
                    },
                ],

                response_format={
                    "type":
                        "json_schema",

                    "json_schema": {
                        "name":
                            "document_extraction",

                        "strict":
                            True,

                        "schema":
                            DocumentExtraction
                            .model_json_schema(),
                    },
                },
            )
        )


        content = (
            response
            .choices[0]
            .message
            .content
        )


        if not content:

            raise ValueError(
                "Groq returned empty "
                "structured output."
            )


        raw_data = json.loads(
            content
        )


        # --------------------------------------------------
        # Final deterministic Pydantic validation
        # --------------------------------------------------

        return (
            DocumentExtraction
            .model_validate(
                raw_data
            )
        )