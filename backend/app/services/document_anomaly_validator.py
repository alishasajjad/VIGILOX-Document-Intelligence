import re

from backend.app.domain.schemas import DocumentExtraction


class DocumentAnomalyValidator:

    # ======================================================
    # ALL STRUCTURED FIELDS
    # ======================================================

    FIELD_NAMES = (
        "full_name",
        "licence_number",
        "id_number",
        "expiry_date",
        "date_of_birth",
        "issue_date",
        "issuer",
    )


    # ======================================================
    # DOCUMENT-SPECIFIC CRITICAL FIELDS
    # ======================================================

    CRITICAL_FIELDS = {

        "sia_badge": (
            "full_name",
            "licence_number",
            "expiry_date",
            "issuer",
        ),

        "guard_license": (
            "full_name",
            "licence_number",
            "expiry_date",
            "issuer",
        ),

        "id_card": (
            "full_name",
            "id_number",
        ),

        "unknown": (),
    }


    def __init__(
        self,
        low_confidence_threshold: float = 0.90,
    ):

        self.low_confidence_threshold = (
            low_confidence_threshold
        )


    # ======================================================
    # NORMALIZE IDENTIFIER
    # ======================================================

    def _normalize_identifier(
        self,
        value: str,
    ) -> str:

        return re.sub(
            r"[^A-Z0-9]",
            "",
            value.upper(),
        )


    # ======================================================
    # ADD ANOMALY
    # ======================================================

    def _add_issue(
        self,
        issues: list[dict],
        code: str,
        severity: str,
        field: str | None,
        message: str,
    ) -> None:

        issues.append(
            {
                "code": code,
                "severity": severity,
                "field": field,
                "message": message,
            }
        )


    # ======================================================
    # MAIN VALIDATION
    # ======================================================

    def validate(
        self,
        extraction: DocumentExtraction,
        confidence_results: dict,
        date_validation: dict,
    ) -> dict:

        issues: list[dict] = []

        document_type = (
            extraction.document_type
        )


        # ==================================================
        # 1. UNKNOWN DOCUMENT TYPE
        # ==================================================

        if document_type == "unknown":

            self._add_issue(
                issues=issues,
                code="UNKNOWN_DOCUMENT_TYPE",
                severity="ERROR",
                field=None,
                message=(
                    "Document type could not be "
                    "reliably classified."
                ),
            )


        # ==================================================
        # 2. GET REQUIRED FIELDS
        # ==================================================

        critical_fields = (
            self.CRITICAL_FIELDS.get(
                document_type,
                (),
            )
        )


        # ==================================================
        # 3. VALIDATE CRITICAL FIELDS
        # ==================================================

        for field_name in critical_fields:

            field = getattr(
                extraction,
                field_name,
            )

            confidence_result = (
                confidence_results.get(
                    field_name,
                    {}
                )
            )


            # ----------------------------------------------
            # MISSING CRITICAL FIELD
            # ----------------------------------------------

            if field.value is None:

                self._add_issue(
                    issues=issues,
                    code=(
                        "MISSING_CRITICAL_FIELD"
                    ),
                    severity="ERROR",
                    field=field_name,
                    message=(
                        f"Required field "
                        f"'{field_name}' "
                        f"is missing for "
                        f"document type "
                        f"'{document_type}'."
                    ),
                )

                continue


            # ----------------------------------------------
            # CRITICAL FIELD EVIDENCE NOT VALID
            # ----------------------------------------------

            status = (
                confidence_result.get(
                    "status"
                )
            )


            if status != "VALID":

                self._add_issue(
                    issues=issues,
                    code=(
                        "CRITICAL_FIELD_NOT_TRUSTED"
                    ),
                    severity="ERROR",
                    field=field_name,
                    message=(
                        f"Critical field "
                        f"'{field_name}' "
                        f"does not have trusted "
                        f"validated evidence."
                    ),
                )

                continue


            # ----------------------------------------------
            # LOW OCR-BASED FIELD CONFIDENCE
            # ----------------------------------------------

            confidence = (
                confidence_result.get(
                    "confidence"
                )
            )


            if (
                confidence is not None
                and confidence
                < self.low_confidence_threshold
            ):

                self._add_issue(
                    issues=issues,
                    code=(
                        "LOW_CRITICAL_FIELD_CONFIDENCE"
                    ),
                    severity="WARNING",
                    field=field_name,
                    message=(
                        f"Critical field "
                        f"'{field_name}' has "
                        f"confidence "
                        f"{confidence:.2%}, "
                        f"below the configured "
                        f"threshold of "
                        f"{self.low_confidence_threshold:.2%}."
                    ),
                )


        # ==================================================
        # 4. NON-CRITICAL EXTRACTED FIELDS WITH
        #    INVALID EVIDENCE
        # ==================================================

        for field_name in self.FIELD_NAMES:

            # Critical fields were already handled above.
            if field_name in critical_fields:
                continue


            field = getattr(
                extraction,
                field_name,
            )


            if field.value is None:
                continue


            confidence_result = (
                confidence_results.get(
                    field_name,
                    {}
                )
            )


            status = (
                confidence_result.get(
                    "status"
                )
            )


            if status == "INVALID_EVIDENCE":

                self._add_issue(
                    issues=issues,
                    code=(
                        "EXTRACTED_FIELD_INVALID_EVIDENCE"
                    ),
                    severity="WARNING",
                    field=field_name,
                    message=(
                        f"Extracted field "
                        f"'{field_name}' exists, "
                        f"but its evidence did not "
                        f"pass validation."
                    ),
                )


        # ==================================================
        # 5. DUPLICATE IDENTIFIER MAPPING
        # ==================================================

        licence_number = (
            extraction.licence_number.value
        )

        id_number = (
            extraction.id_number.value
        )


        if (
            licence_number is not None
            and id_number is not None
        ):

            normalized_licence = (
                self._normalize_identifier(
                    licence_number
                )
            )

            normalized_id = (
                self._normalize_identifier(
                    id_number
                )
            )


            if (
                normalized_licence
                and normalized_id
                and normalized_licence
                == normalized_id
            ):

                self._add_issue(
                    issues=issues,
                    code=(
                        "DUPLICATE_IDENTIFIER_MAPPING"
                    ),
                    severity="ERROR",
                    field=None,
                    message=(
                        "The same identifier value "
                        "was mapped to both "
                        "licence_number and "
                        "id_number."
                    ),
                )


        # ==================================================
        # 6. PROPAGATE DATE LOGICAL ISSUES FROM PHASE 4B
        # ==================================================

        for logical_issue in (
            date_validation.get(
                "logical_issues",
                [],
            )
        ):

            self._add_issue(
                issues=issues,
                code=logical_issue["code"],
                severity="ERROR",
                field=logical_issue.get(
                    "field"
                ),
                message=logical_issue[
                    "message"
                ],
            )


        # ==================================================
        # 7. EXPIRY STATUS ALERTS
        # ==================================================

        expiry = date_validation.get(
            "expiry",
            {}
        )

        expiry_status = expiry.get(
            "status"
        )


        if expiry_status == "EXPIRED":

            self._add_issue(
                issues=issues,
                code="DOCUMENT_EXPIRED",
                severity="WARNING",
                field="expiry_date",
                message=(
                    "The document has passed "
                    "its validated expiry date."
                ),
            )


        elif expiry_status == "EXPIRING_SOON":

            days = expiry.get(
                "days_until_expiry"
            )

            self._add_issue(
                issues=issues,
                code="DOCUMENT_EXPIRING_SOON",
                severity="WARNING",
                field="expiry_date",
                message=(
                    f"The document expires in "
                    f"{days} day(s)."
                ),
            )


        # ==================================================
        # 8. FINAL SUMMARY
        # ==================================================

        error_count = sum(
            1
            for issue in issues
            if issue["severity"] == "ERROR"
        )


        warning_count = sum(
            1
            for issue in issues
            if issue["severity"] == "WARNING"
        )


        return {

            "document_type":
                document_type,

            "valid":
                error_count == 0,

            "has_anomalies":
                len(issues) > 0,

            "error_count":
                error_count,

            "warning_count":
                warning_count,

            "issues":
                issues,
        }