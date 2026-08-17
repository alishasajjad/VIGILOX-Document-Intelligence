import json

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class AuditService:

    def __init__(
        self,
        log_path: str = (
            "output/audit/audit_log.jsonl"
        ),
    ):

        self.log_path = Path(
            log_path
        )

        self.log_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

    # ======================================================
    # APPEND AUDIT EVENT
    # ======================================================

    def log_event(
        self,
        document_id: str,
        event_type: str,
        actor_type: str,
        actor_id: str | None = None,
        details: dict | None = None,
    ) -> dict:

        if not document_id.strip():
            raise ValueError(
                "document_id is required."
            )

        if not event_type.strip():
            raise ValueError(
                "event_type is required."
            )

        if not actor_type.strip():
            raise ValueError(
                "actor_type is required."
            )

        event = {
            "audit_id": str(uuid4()),
            "document_id": document_id,
            "event_type": event_type,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "details": details or {},
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
        }

        with self.log_path.open(
            "a",
            encoding="utf-8",
        ) as file:

            file.write(
                json.dumps(
                    event,
                    ensure_ascii=False,
                )
            )

            file.write("\n")

        return event

    # ======================================================
    # LOG MACHINE REVIEW DECISION
    # ======================================================

    def log_machine_decision(
        self,
        document_id: str,
        review_result: dict,
    ) -> dict:

        return self.log_event(
            document_id=document_id,
            event_type=(
                "MACHINE_REVIEW_DECISION"
            ),
            actor_type="SYSTEM",
            actor_id=None,
            details={
                "decision":
                    review_result.get(
                        "decision"
                    ),

                "review_required":
                    review_result.get(
                        "review_required"
                    ),

                "priority":
                    review_result.get(
                        "priority"
                    ),

                "reason_codes":
                    review_result.get(
                        "reason_codes",
                        [],
                    ),
            },
        )

    # ======================================================
    # LOG HUMAN REVIEW
    # ======================================================

    def log_human_review(
        self,
        human_review: dict,
    ) -> dict:

        document_id = (
            human_review.get(
                "document_id"
            )
        )

        reviewer_id = (
            human_review.get(
                "reviewer_id"
            )
        )

        if not document_id:
            raise ValueError(
                "Human review does not "
                "contain document_id."
            )

        return self.log_event(
            document_id=document_id,
            event_type="HUMAN_REVIEW",
            actor_type="HUMAN",
            actor_id=reviewer_id,
            details={
                "review_id":
                    human_review.get(
                        "review_id"
                    ),

                "human_action":
                    human_review.get(
                        "human_action"
                    ),

                "machine_decision":
                    human_review.get(
                        "machine_decision"
                    ),

                "machine_priority":
                    human_review.get(
                        "machine_priority"
                    ),

                "machine_reason_codes":
                    human_review.get(
                        "machine_reason_codes",
                        [],
                    ),

                "corrections":
                    human_review.get(
                        "corrections",
                        {},
                    ),

                "notes":
                    human_review.get(
                        "notes"
                    ),

                "reviewed_at":
                    human_review.get(
                        "reviewed_at"
                    ),
            },
        )

    # ======================================================
    # READ DOCUMENT AUDIT HISTORY
    # ======================================================

    def get_document_history(
        self,
        document_id: str,
    ) -> list[dict]:

        if not self.log_path.exists():
            return []

        history = []

        with self.log_path.open(
            "r",
            encoding="utf-8",
        ) as file:

            for line in file:

                line = line.strip()

                if not line:
                    continue

                event = json.loads(
                    line
                )

                if (
                    event.get(
                        "document_id"
                    )
                    == document_id
                ):

                    history.append(
                        event
                    )

        return history