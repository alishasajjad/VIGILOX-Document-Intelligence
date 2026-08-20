from src.schemas import (
    DocumentExtraction,
)


class ConfidenceService:

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
    # BUILD OCR EVIDENCE LOOKUP
    # PHASE 7C.2
    # ======================================================

    def _build_ocr_lookup(
        self,
        ocr_lines: list[dict],
    ) -> dict[str, dict]:

        lookup: dict[str, dict] = {}


        for (
            index,
            line,
        ) in enumerate(
            ocr_lines
        ):

            # ==============================================
            # OCR RECORD STRUCTURE
            # ==============================================

            if not isinstance(
                line,
                dict,
            ):

                raise ValueError(
                    (
                        "Invalid OCR line at "
                        f"index {index}. "
                        "Expected a dictionary."
                    )
                )


            if (
                "confidence"
                not in line
            ):

                raise ValueError(
                    (
                        "OCR line at "
                        f"index {index} "
                        "is missing confidence."
                    )
                )


            # ==============================================
            # EXPLICIT LINE ID
            # PHASE 7C.2
            # ==============================================

            line_id = (
                line.get(
                    "line_id"
                )
            )


            # ==============================================
            # LEGACY BACKWARD COMPATIBILITY
            # ==============================================
            #
            # Older OCR fixtures and persisted records may
            # not contain explicit line_id.
            #
            # Preserve the historical zero-based mapping:
            #
            # index 0 -> L0
            # index 1 -> L1
            # ...
            #
            # New OCRService output always contains line_id.
            # ==============================================

            if (
                line_id is None
                or str(
                    line_id
                ).strip()
                == ""
            ):

                line_id = (
                    f"L{index}"
                )


            line_id = (
                str(
                    line_id
                )
                .strip()
            )


            # ==============================================
            # LINE ID FORMAT VALIDATION
            # ==============================================

            if (
                not line_id.startswith(
                    "L"
                )
                or len(
                    line_id
                ) < 2
                or not line_id[
                    1:
                ].isdigit()
            ):

                raise ValueError(
                    (
                        "Invalid OCR line_id "
                        f"at index {index}: "
                        f"{line_id}. "
                        "Expected format "
                        "L0, L1, L2, ..."
                    )
                )


            # ==============================================
            # DUPLICATE LINE ID PROTECTION
            # ==============================================

            if (
                line_id
                in lookup
            ):

                raise ValueError(
                    (
                        "Duplicate OCR line_id "
                        f"detected: {line_id}."
                    )
                )


            lookup[
                line_id
            ] = line


        return lookup


    # ======================================================
    # CALCULATE FIELD CONFIDENCE
    # ======================================================

    def calculate(
        self,
        extraction: DocumentExtraction,
        ocr_lines: list[dict],
        evidence_flags: list[str],
    ) -> dict:

        results = {}


        # ==================================================
        # BUILD EXPLICIT OCR LOOKUP
        # PHASE 7C.2
        # ==================================================

        ocr_lookup = (
            self._build_ocr_lookup(
                ocr_lines
            )
        )


        for field_name in self.FIELD_NAMES:

            field = getattr(
                extraction,
                field_name,
            )


            # ==============================================
            # FIELD NOT EXTRACTED
            # ==============================================

            if field.value is None:

                results[
                    field_name
                ] = {
                    "value":
                        None,

                    "confidence":
                        None,

                    "status":
                        "NOT_EXTRACTED",
                }


                continue


            # ==============================================
            # CHECK EVIDENCE VALIDATION FLAGS
            # ==============================================

            field_prefix = (
                field_name.upper()
            )


            field_has_validation_error = any(
                flag.startswith(
                    field_prefix
                )

                for flag
                in evidence_flags
            )


            if field_has_validation_error:

                results[
                    field_name
                ] = {
                    "value":
                        field.value,

                    "confidence":
                        None,

                    "status":
                        "INVALID_EVIDENCE",
                }


                continue


            # ==============================================
            # GET OCR CONFIDENCES BY EXPLICIT LINE ID
            # PHASE 7C.2
            # ==============================================

            evidence_confidences: list[float] = []


            for line_id in (
                field.source_line_ids
            ):

                ocr_line = (
                    ocr_lookup.get(
                        line_id
                    )
                )


                # ==========================================
                # DEFENSIVE INVALID SOURCE HANDLING
                # ==========================================
                #
                # Normally EvidenceValidator already catches
                # invalid source IDs and this field becomes
                # INVALID_EVIDENCE before reaching here.
                #
                # Keep this guard so ConfidenceService does
                # not crash if called independently.
                # ==========================================

                if ocr_line is None:

                    continue


                confidence = (
                    ocr_line.get(
                        "confidence"
                    )
                )


                if confidence is None:

                    continue


                try:

                    normalized_confidence = (
                        float(
                            confidence
                        )
                    )

                except (
                    TypeError,
                    ValueError,
                ):

                    continue


                evidence_confidences.append(
                    normalized_confidence
                )


            # ==============================================
            # NO VALID CONFIDENCE
            # ==============================================

            if not evidence_confidences:

                results[
                    field_name
                ] = {
                    "value":
                        field.value,

                    "confidence":
                        None,

                    "status":
                        "NO_CONFIDENCE",
                }


                continue


            # ==============================================
            # CONSERVATIVE FIELD CONFIDENCE
            # ==============================================
            #
            # A field supported by multiple OCR lines receives
            # the minimum evidence confidence.
            #
            # Example:
            #
            # L8  -> EXPIRES     confidence 0.99
            # L9  -> 01/01/2026 confidence 0.94
            #
            # expiry confidence = 0.94
            #
            # This preserves the Phase 4 confidence policy.
            # ==============================================

            field_confidence = min(
                evidence_confidences
            )


            results[
                field_name
            ] = {
                "value":
                    field.value,

                "confidence":
                    field_confidence,

                "status":
                    "VALID",
            }


        return results