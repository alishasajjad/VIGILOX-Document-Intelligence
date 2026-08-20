from datetime import datetime, timezone
from uuid import uuid4


class HumanReviewService:

    ALLOWED_ACTIONS = {
        "APPROVE",
        "REJECT",
        "CORRECT",
    }

    CORRECTABLE_FIELDS = {
        "document_type",
        "full_name",
        "licence_number",
        "id_number",
        "expiry_date",
        "date_of_birth",
        "issue_date",
        "issuer",
    }


    def submit_review(
        self,
        document_id: str,
        reviewer_id: str,
        review_result: dict,
        action: str,
        notes: str | None = None,
        corrections: dict | None = None,
    ) -> dict:

        action = action.upper().strip()

        corrections = corrections or {}


        # ==================================================
        # BASIC VALIDATION
        # ==================================================

        if not document_id.strip():
            raise ValueError(
                "document_id is required."
            )

        if not reviewer_id.strip():
            raise ValueError(
                "reviewer_id is required."
            )

        if action not in self.ALLOWED_ACTIONS:
            raise ValueError(
                f"Unsupported review action: {action}"
            )


        # ==================================================
        # CORRECTION VALIDATION
        # ==================================================

        if (
            action == "CORRECT"
            and not corrections
        ):
            raise ValueError(
                "CORRECT action requires "
                "at least one correction."
            )


        if (
            action != "CORRECT"
            and corrections
        ):
            raise ValueError(
                "Corrections are only allowed "
                "when action is CORRECT."
            )


        for field_name in corrections:

            if (
                field_name
                not in self.CORRECTABLE_FIELDS
            ):
                raise ValueError(
                    f"Unsupported correction field: "
                    f"{field_name}"
                )


        # ==================================================
        # CREATE HUMAN REVIEW RECORD
        # ==================================================

        reviewed_at = datetime.now(
            timezone.utc
        ).isoformat()


        return {

            "review_id":
                str(uuid4()),

            "document_id":
                document_id,

            "reviewer_id":
                reviewer_id,

            "machine_decision":
                review_result.get(
                    "decision"
                ),

            "machine_priority":
                review_result.get(
                    "priority"
                ),

            "machine_reason_codes":
                review_result.get(
                    "reason_codes",
                    [],
                ),

            "human_action":
                action,

            "corrections":
                corrections,

            "notes":
                notes,

            "reviewed_at":
                reviewed_at,

            "status":
                "COMPLETED",
        }