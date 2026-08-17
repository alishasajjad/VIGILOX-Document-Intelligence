from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    StringConstraints,
    field_validator,
    model_validator,
)


# ==========================================================
# VALID OCR LINE ID
# ==========================================================

LineId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^L\d+$",
    ),
]


# ==========================================================
# EXTRACTED FIELD
# ==========================================================

class ExtractedField(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    value: str | None

    source_line_ids: list[LineId]


    # ======================================================
    # NORMALIZE NULL-LIKE MODEL OUTPUT
    # ======================================================

    @field_validator(
        "value",
        mode="before",
    )
    @classmethod
    def normalize_null_values(
        cls,
        value,
    ):

        if value is None:
            return None

        if isinstance(value, str):

            cleaned = value.strip()

            if cleaned.lower() in {
                "",
                "null",
                "none",
                "n/a",
                "na",
            }:
                return None

            return cleaned

        return value


    # ======================================================
    # VALUE / EVIDENCE CONSISTENCY
    # ======================================================

    @model_validator(
        mode="after"
    )
    def validate_evidence_consistency(
        self,
    ):

        # ----------------------------------------------
        # NULL FIELD MUST NOT HAVE SOURCE LINES
        # ----------------------------------------------

        if (
            self.value is None
            and self.source_line_ids
        ):

            raise ValueError(
                "A null field must have "
                "source_line_ids = []."
            )


        # ----------------------------------------------
        # EXTRACTED VALUE MUST HAVE EVIDENCE
        # ----------------------------------------------

        if (
            self.value is not None
            and not self.source_line_ids
        ):

            raise ValueError(
                "A non-null extracted field "
                "must have at least one "
                "source_line_id."
            )


        # ----------------------------------------------
        # DUPLICATE SOURCE IDS NOT ALLOWED
        # ----------------------------------------------

        if (
            len(self.source_line_ids)
            != len(
                set(self.source_line_ids)
            )
        ):

            raise ValueError(
                "Duplicate source_line_ids "
                "are not allowed."
            )


        return self


# ==========================================================
# COMPLETE DOCUMENT EXTRACTION
# ==========================================================

class DocumentExtraction(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    document_type: Literal[
        "sia_badge",
        "id_card",
        "guard_license",
        "unknown",
    ]

    full_name: ExtractedField

    licence_number: ExtractedField

    id_number: ExtractedField

    expiry_date: ExtractedField

    date_of_birth: ExtractedField

    issue_date: ExtractedField

    issuer: ExtractedField