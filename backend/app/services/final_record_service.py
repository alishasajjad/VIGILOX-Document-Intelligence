from backend.app.domain.classification import (
    DECISION_AUTO_ACCEPT,
    DECISION_UNSUPPORTED_DOCUMENT,
)


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
    # FINAL STATUS RESOLUTION
    # PHASE 8.6A / 8.8A
    # ======================================================
    #
    # WHY THIS EXISTS
    # ------------------------------------------------------
    #
    # build() needs the full extraction JSONB, because it
    # also assembles machine and effective values. A document
    # LIST must not load extraction for every row.
    #
    # The status itself depends only on the machine decision
    # and the human action, so that rule is expressed once
    # here and reused by both paths. The list endpoint and the
    # detail endpoint therefore cannot disagree.
    #
    # test_phase8_final_status_parity asserts this returns the
    # same status as build() for every combination.
    # ======================================================

    FINAL_STATUS_BY_HUMAN_ACTION = {
        "APPROVE": "APPROVED",
        "CORRECT": "CORRECTED",
        "REJECT": "REJECTED",
    }


    # ======================================================
    # THE SIXTH STATUS
    # PHASE 10.2
    # ======================================================
    #
    # UNSUPPORTED was added reluctantly, and only after
    # establishing that the alternative was to record a false
    # statement.
    #
    # Phase 10.2 gave the machine a third decision:
    # UNSUPPORTED_DOCUMENT, for a file that is confidently not
    # a Guard Licence, an ID Card or an SIA Badge. Such a
    # document is never queued for review, because there is
    # nothing on a receipt for a reviewer to correct.
    #
    # Mapping it to PENDING_REVIEW would then have this field
    # -- the authoritative one, the one the interface prints --
    # say a review is pending for a document that no reviewer
    # will ever be shown. A wrong value in the authoritative
    # field is worse than a sixth value in this tuple.
    #
    # It is a MACHINE-ONLY status, exactly like AUTO_ACCEPTED
    # and PENDING_REVIEW. A human can still open an
    # unsupported document and reject it, and the moment they
    # do, human_action wins and the status becomes REJECTED.
    # ======================================================

    FINAL_STATUSES = (
        "AUTO_ACCEPTED",
        "PENDING_REVIEW",
        "UNSUPPORTED",
        "APPROVED",
        "CORRECTED",
        "REJECTED",
    )


    @classmethod
    def resolve_final_status(
        cls,
        *,
        machine_decision: str | None,
        human_action: str | None,
    ) -> str:

        # ==================================================
        # HUMAN REVIEW WINS
        # ==================================================

        if human_action:

            action = (
                str(
                    human_action
                )
                .strip()
                .upper()
            )


            if (
                action
                not in cls.FINAL_STATUS_BY_HUMAN_ACTION
            ):

                raise ValueError(
                    (
                        "Unsupported stored human "
                        "review action: "
                        f"{action}"
                    )
                )


            return (
                cls.FINAL_STATUS_BY_HUMAN_ACTION[
                    action
                ]
            )


        # ==================================================
        # MACHINE ONLY
        # ==================================================

        normalized_decision = (
            str(
                machine_decision
                or ""
            )
            .strip()
            .upper()
        )


        if (
            normalized_decision
            == DECISION_AUTO_ACCEPT
        ):

            return "AUTO_ACCEPTED"


        # PHASE 10.2.
        if (
            normalized_decision
            == DECISION_UNSUPPORTED_DOCUMENT
        ):

            return "UNSUPPORTED"


        return "PENDING_REVIEW"


    @classmethod
    def final_status_query_spec(
        cls,
        final_status: str,
    ) -> dict:

        # ==================================================
        # INVERSE OF resolve_final_status
        # ==================================================
        #
        # Returns neutral primitives that a repository can
        # turn into SQL, so the repository never encodes
        # final-state business rules itself.
        #
        #     human_action        exact match, or None
        #     human_action_isnull whether a review must be
        #                         absent
        #     machine_decision    exact match, or None
        #     machine_decision_not
        #                         tuple of decisions to
        #                         exclude, for the
        #                         "everything that is
        #                         neither auto-accepted nor
        #                         unsupported" case
        #
        # PHASE 10.2 made machine_decision_not a TUPLE rather
        # than a single value. PENDING_REVIEW now has two
        # decisions to exclude, and a caller that received a
        # bare string would have silently matched only the
        # first of them -- listing every unsupported document
        # as pending review.
        # ==================================================

        status = (
            str(
                final_status
            )
            .strip()
            .upper()
        )


        if status not in cls.FINAL_STATUSES:

            raise ValueError(
                (
                    "Unsupported final status: "
                    f"{final_status}"
                )
            )


        if status == "AUTO_ACCEPTED":

            return {
                "human_action":
                    None,

                "human_action_isnull":
                    True,

                "machine_decision":
                    DECISION_AUTO_ACCEPT,

                "machine_decision_not":
                    None,
            }


        # PHASE 10.2.
        if status == "UNSUPPORTED":

            return {
                "human_action":
                    None,

                "human_action_isnull":
                    True,

                "machine_decision":
                    (
                        DECISION_UNSUPPORTED_DOCUMENT
                    ),

                "machine_decision_not":
                    None,
            }


        if status == "PENDING_REVIEW":

            return {
                "human_action":
                    None,

                "human_action_isnull":
                    True,

                "machine_decision":
                    None,

                # Everything with no human review that the
                # machine neither accepted nor set aside as
                # unsupported. Stated as an exclusion rather
                # than as "= REVIEW_REQUIRED" so that a row
                # carrying no analysis, or no recorded
                # decision, still counts as pending -- which
                # it is, and which a bare equality would
                # silently drop.
                "machine_decision_not":
                    (
                        DECISION_AUTO_ACCEPT,
                        DECISION_UNSUPPORTED_DOCUMENT,
                    ),
            }


        # APPROVED / CORRECTED / REJECTED

        for (
            action,
            mapped_status,
        ) in cls.FINAL_STATUS_BY_HUMAN_ACTION.items():

            if mapped_status == status:

                return {
                    "human_action":
                        action,

                    "human_action_isnull":
                        False,

                    "machine_decision":
                        None,

                    "machine_decision_not":
                        None,
                }


        raise ValueError(
            (
                "Unsupported final status: "
                f"{final_status}"
            )
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
            # MACHINE: UNSUPPORTED DOCUMENT
            # PHASE 10.2
            # ==============================================
            #
            # is_final is True and is_usable is False, and both
            # halves matter.
            #
            # final, because nothing further will happen
            # automatically: no reviewer is queued and
            # reprocessing the same bytes reaches the same
            # deterministic answer. Reporting it as pending
            # would describe a wait that never ends.
            #
            # not usable, because there is no supported
            # document here to publish. effective_values stays
            # None -- the same as PENDING_REVIEW -- so no
            # downstream consumer can read values off a
            # receipt.
            #
            # machine_values is still returned. Whatever the
            # extractor read is part of the audit record and is
            # what lets an operator see why the file was set
            # aside.
            # ==============================================

            if (
                decision
                == DECISION_UNSUPPORTED_DOCUMENT
            ):

                return {
                    "final_status":
                        "UNSUPPORTED",

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