from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)


class HumanReviewRequest(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    reviewer_id: str = Field(
        min_length=1,
        max_length=100,
    )

    action: Literal[
        "APPROVE",
        "REJECT",
        "CORRECT",
    ]

    notes: str | None = None

    corrections: (
        dict[str, str | None]
        | None
    ) = None