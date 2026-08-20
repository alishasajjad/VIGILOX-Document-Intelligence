from datetime import date, datetime

from backend.app.domain.schemas import DocumentExtraction


class DateLogicalValidator:

    DATE_FIELDS = (
        "expiry_date",
        "date_of_birth",
        "issue_date",
    )


    def __init__(
        self,
        expiring_soon_days: int = 30,
    ):

        self.expiring_soon_days = (
            expiring_soon_days
        )


    # ======================================================
    # PARSE ISO DATE
    # ======================================================

    def _parse_iso_date(
        self,
        value: str,
    ) -> date | None:
        """
        Phase 2 normalizes extracted dates to YYYY-MM-DD.

        Example:
            2026-01-01

        If parsing fails, return None.
        """

        try:

            return datetime.strptime(
                value,
                "%Y-%m-%d",
            ).date()

        except ValueError:

            return None


    # ======================================================
    # CHECK WHETHER FIELD CAN BE TRUSTED
    # ======================================================

    def _field_is_valid(
        self,
        field_name: str,
        confidence_results: dict,
    ) -> bool:
        """
        Date logic should only run when Phase 4A says
        the field has valid evidence.
        """

        result = confidence_results.get(
            field_name
        )

        if not result:
            return False

        return (
            result.get("status")
            == "VALID"
        )


    # ======================================================
    # MAIN VALIDATION
    # ======================================================

    def validate(
        self,
        extraction: DocumentExtraction,
        confidence_results: dict,
        reference_date: date | None = None,
    ) -> dict:

        today = (
            reference_date
            if reference_date is not None
            else date.today()
        )


        logical_issues: list[dict] = []

        parsed_dates: dict[
            str,
            date | None
        ] = {}


        date_fields: dict[
            str,
            dict
        ] = {}


        # ==================================================
        # STEP 1 — PARSE VALIDATED DATE FIELDS
        # ==================================================

        for field_name in self.DATE_FIELDS:

            field = getattr(
                extraction,
                field_name,
            )


            # ----------------------------------------------
            # DATE WAS NOT EXTRACTED
            # ----------------------------------------------

            if field.value is None:

                parsed_dates[field_name] = None

                date_fields[field_name] = {
                    "value": None,
                    "status": "NOT_EXTRACTED",
                }

                continue


            # ----------------------------------------------
            # EVIDENCE DID NOT PASS
            # ----------------------------------------------

            if not self._field_is_valid(
                field_name,
                confidence_results,
            ):

                parsed_dates[field_name] = None

                date_fields[field_name] = {
                    "value": field.value,
                    "status":
                        "SKIPPED_INVALID_EVIDENCE",
                }

                continue


            # ----------------------------------------------
            # PARSE NORMALIZED DATE
            # ----------------------------------------------

            parsed = self._parse_iso_date(
                field.value
            )


            if parsed is None:

                parsed_dates[field_name] = None

                date_fields[field_name] = {
                    "value": field.value,
                    "status": "INVALID_DATE_FORMAT",
                }


                logical_issues.append(
                    {
                        "code":
                            f"{field_name.upper()}_INVALID_FORMAT",

                        "field":
                            field_name,

                        "message":
                            (
                                f"{field_name} value "
                                f"'{field.value}' is not "
                                f"a valid YYYY-MM-DD date."
                            ),
                    }
                )

                continue


            parsed_dates[field_name] = (
                parsed
            )


            date_fields[field_name] = {
                "value": field.value,
                "status": "VALID_DATE",
            }


        # ==================================================
        # STEP 2 — EXPIRY STATUS
        # ==================================================

        expiry_date = parsed_dates.get(
            "expiry_date"
        )


        expiry_result = {
            "value": None,
            "status": "NOT_AVAILABLE",
            "days_until_expiry": None,
        }


        if expiry_date is not None:

            days_until_expiry = (
                expiry_date - today
            ).days


            if days_until_expiry < 0:

                expiry_status = (
                    "EXPIRED"
                )

            elif days_until_expiry == 0:

                expiry_status = (
                    "EXPIRES_TODAY"
                )

            elif (
                days_until_expiry
                <= self.expiring_soon_days
            ):

                expiry_status = (
                    "EXPIRING_SOON"
                )

            else:

                expiry_status = (
                    "ACTIVE"
                )


            expiry_result = {
                "value":
                    expiry_date.isoformat(),

                "status":
                    expiry_status,

                "days_until_expiry":
                    days_until_expiry,
            }


        # ==================================================
        # STEP 3 — FUTURE DOB CHECK
        # ==================================================

        date_of_birth = parsed_dates.get(
            "date_of_birth"
        )


        if (
            date_of_birth is not None
            and date_of_birth > today
        ):

            logical_issues.append(
                {
                    "code":
                        "FUTURE_DATE_OF_BIRTH",

                    "field":
                        "date_of_birth",

                    "message":
                        (
                            "Date of birth cannot "
                            "be in the future."
                        ),
                }
            )


        # ==================================================
        # STEP 4 — FUTURE ISSUE DATE
        # ==================================================

        issue_date = parsed_dates.get(
            "issue_date"
        )


        if (
            issue_date is not None
            and issue_date > today
        ):

            logical_issues.append(
                {
                    "code":
                        "FUTURE_ISSUE_DATE",

                    "field":
                        "issue_date",

                    "message":
                        (
                            "Issue date cannot "
                            "be in the future."
                        ),
                }
            )


        # ==================================================
        # STEP 5 — EXPIRY BEFORE ISSUE DATE
        # ==================================================

        if (
            expiry_date is not None
            and issue_date is not None
            and expiry_date < issue_date
        ):

            logical_issues.append(
                {
                    "code":
                        "EXPIRY_BEFORE_ISSUE_DATE",

                    "field":
                        "expiry_date",

                    "message":
                        (
                            "Expiry date occurs before "
                            "the issue date."
                        ),
                }
            )


        # ==================================================
        # STEP 6 — DOB AFTER ISSUE DATE
        # ==================================================

        if (
            date_of_birth is not None
            and issue_date is not None
            and date_of_birth > issue_date
        ):

            logical_issues.append(
                {
                    "code":
                        "DOB_AFTER_ISSUE_DATE",

                    "field":
                        "date_of_birth",

                    "message":
                        (
                            "Date of birth occurs after "
                            "the document issue date."
                        ),
                }
            )


        # ==================================================
        # STEP 7 — DOB AFTER EXPIRY DATE
        # ==================================================

        if (
            date_of_birth is not None
            and expiry_date is not None
            and date_of_birth > expiry_date
        ):

            logical_issues.append(
                {
                    "code":
                        "DOB_AFTER_EXPIRY_DATE",

                    "field":
                        "date_of_birth",

                    "message":
                        (
                            "Date of birth occurs after "
                            "the document expiry date."
                        ),
                }
            )


        # ==================================================
        # FINAL RESULT
        # ==================================================

        return {

            "reference_date":
                today.isoformat(),

            "date_fields":
                date_fields,

            "expiry":
                expiry_result,

            "logical_issues":
                logical_issues,

            "valid":
                len(logical_issues) == 0,
        }