class ReviewDecisionService:

    LOW_PRIORITY_WARNING_CODES = {
        "DOCUMENT_EXPIRING_SOON",
    }

    MEDIUM_PRIORITY_WARNING_CODES = {
        "DOCUMENT_EXPIRED",
        "LOW_CRITICAL_FIELD_CONFIDENCE",
        "EXTRACTED_FIELD_INVALID_EVIDENCE",
    }


    def decide(
        self,
        anomaly_result: dict,
    ) -> dict:

        issues = anomaly_result.get(
            "issues",
            [],
        )

        error_count = anomaly_result.get(
            "error_count",
            0,
        )

        warning_count = anomaly_result.get(
            "warning_count",
            0,
        )


        # ==================================================
        # 1. CLEAN DOCUMENT
        # ==================================================

        if (
            error_count == 0
            and warning_count == 0
            and not issues
        ):

            return {
                "decision": "AUTO_ACCEPT",
                "review_required": False,
                "priority": "NONE",
                "reason_codes": [],
                "issues": [],
            }


        # ==================================================
        # 2. DOCUMENT CONTAINS ERROR
        # ==================================================

        if (
            error_count > 0
            or anomaly_result.get("valid") is False
        ):

            return {
                "decision": "REVIEW_REQUIRED",
                "review_required": True,
                "priority": "HIGH",
                "reason_codes": [
                    issue["code"]
                    for issue in issues
                ],
                "issues": issues,
            }


        # ==================================================
        # 3. WARNING-ONLY DOCUMENT
        # ==================================================

        warning_codes = {
            issue["code"]
            for issue in issues
            if issue.get("severity")
            == "WARNING"
        }


        # ==================================================
        # 4. ONLY LOW-PRIORITY WARNINGS
        # ==================================================

        if (
            warning_codes
            and warning_codes.issubset(
                self.LOW_PRIORITY_WARNING_CODES
            )
        ):

            priority = "LOW"


        # ==================================================
        # 5. OTHER WARNINGS
        # ==================================================

        else:

            priority = "MEDIUM"


        return {
            "decision": "REVIEW_REQUIRED",
            "review_required": True,
            "priority": priority,
            "reason_codes": [
                issue["code"]
                for issue in issues
            ],
            "issues": issues,
        }