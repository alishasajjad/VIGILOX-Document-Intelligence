from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
)


# ==========================================================
# INDIVIDUAL EXTRACTED FIELD
# ==========================================================

class ExtractedField(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    value: str | None

    source_line_ids: list[str]


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