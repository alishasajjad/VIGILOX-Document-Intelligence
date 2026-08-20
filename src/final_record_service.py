class FinalRecordService:

    FIELD_NAMES = (
        "document_type",
        "full_name",
        "licence_number",
        "id_number",
        "expiry_date",
        "date_of_birth",
        "issue_date",
        "issuer",
    )


    # ======================================================
    # EXTRACT FLAT MACHINE VALUES
    # ======================================================

    def _extract_machine_values(
        self,
        extraction: dict,
    ) -> dict:

        values = {}


        # document_type is a top-level string,
        # unlike the other extracted fields.
        values["document_type"] = (
            extraction.get(
                "document_type"
            )
        )


        for field_name in (
            "full_name",
            "licence_number",
            "id_number",
            "expiry_date",
            "date_of_birth",
            "issue_date",
            "issuer",
        ):

            field = (
                extraction.get(
                    field_name
                )
                or {}
            )


            values[
                field_name
            ] = field.get(
                "value"
            )


        return values


    # ======================================================
    # BUILD VALUE SOURCES
    # ======================================================

    def _machine_sources(
        self,
    ) -> dict:

        return {
            field_name:
                "MACHINE"

            for field_name
            in self.FIELD_NAMES
        }


    # ======================================================
    # BUILD FINAL / EFFECTIVE RECORD
    # ======================================================

    def build(
        self,
        *,
        extraction: dict,
        machine_review_decision: dict | None,
        human_review: dict | None,
    ) -> dict:

        machine_values = (
            self._extract_machine_values(
                extraction
            )
        )


        machine_decision = (
            machine_review_decision
            or {}
        )


        # ==================================================
        # NO HUMAN REVIEW
        # ==================================================

        if human_review is None:

            decision = (
                machine_decision.get(
                    "decision"
                )
            )


            # ==============================================
            # MACHINE AUTO ACCEPT
            # ==============================================

            if (
                decision
                == "AUTO_ACCEPT"
            ):

                return {
                    "final_status":
                        "AUTO_ACCEPTED",

                    "is_final":
                        True,

                    "is_usable":
                        True,

                    "machine_values":
                        machine_values,

                    "effective_values":
                        dict(
                            machine_values
                        ),

                    "value_sources":
                        self._machine_sources(),

                    "human_action":
                        None,
                }


            # ==============================================
            # MACHINE REVIEW REQUIRED
            # ==============================================

            return {
                "final_status":
                    "PENDING_REVIEW",

                "is_final":
                    False,

                "is_usable":
                    False,

                "machine_values":
                    machine_values,

                "effective_values":
                    None,

                "value_sources":
                    None,

                "human_action":
                    None,
            }


        # ==================================================
        # HUMAN REVIEW EXISTS
        # ==================================================

        action = (
            str(
                human_review.get(
                    "human_action",
                    ""
                )
            )
            .strip()
            .upper()
        )


        # ==================================================
        # APPROVE
        # ==================================================

        if action == "APPROVE":

            return {
                "final_status":
                    "APPROVED",

                "is_final":
                    True,

                "is_usable":
                    True,

                "machine_values":
                    machine_values,

                "effective_values":
                    dict(
                        machine_values
                    ),

                "value_sources":
                    self._machine_sources(),

                "human_action":
                    "APPROVE",
            }


        # ==================================================
        # CORRECT
        # ==================================================

        if action == "CORRECT":

            corrections = (
                human_review.get(
                    "corrections"
                )
                or {}
            )


            effective_values = dict(
                machine_values
            )


            value_sources = (
                self._machine_sources()
            )


            for (
                field_name,
                corrected_value,
            ) in corrections.items():

                if (
                    field_name
                    not in self.FIELD_NAMES
                ):

                    raise ValueError(
                        (
                            "Stored human review "
                            "contains unsupported "
                            "correction field: "
                            f"{field_name}"
                        )
                    )


                # Important:
                #
                # A human correction may intentionally
                # replace a machine value with None.
                #
                # Therefore key presence matters,
                # not truthiness.
                effective_values[
                    field_name
                ] = corrected_value


                value_sources[
                    field_name
                ] = "HUMAN_CORRECTION"


            return {
                "final_status":
                    "CORRECTED",

                "is_final":
                    True,

                "is_usable":
                    True,

                "machine_values":
                    machine_values,

                "effective_values":
                    effective_values,

                "value_sources":
                    value_sources,

                "human_action":
                    "CORRECT",
            }


        # ==================================================
        # REJECT
        # ==================================================

        if action == "REJECT":

            return {
                "final_status":
                    "REJECTED",

                "is_final":
                    True,

                "is_usable":
                    False,

                "machine_values":
                    machine_values,

                "effective_values":
                    None,

                "value_sources":
                    None,

                "human_action":
                    "REJECT",
            }


        # ==================================================
        # INVALID STORED STATE
        # ==================================================

        raise ValueError(
            (
                "Unsupported stored human "
                "review action: "
                f"{action}"
            )
        )