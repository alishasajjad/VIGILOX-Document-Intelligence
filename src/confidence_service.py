from src.schemas import DocumentExtraction


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


    def calculate(
        self,
        extraction: DocumentExtraction,
        ocr_lines: list[dict],
        evidence_flags: list[str],
    ) -> dict:

        results = {}


        for field_name in self.FIELD_NAMES:

            field = getattr(
                extraction,
                field_name,
            )


            # ==============================================
            # FIELD NOT EXTRACTED
            # ==============================================

            if field.value is None:

                results[field_name] = {
                    "value": None,
                    "confidence": None,
                    "status": "NOT_EXTRACTED",
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
                for flag in evidence_flags
            )


            if field_has_validation_error:

                results[field_name] = {
                    "value": field.value,
                    "confidence": None,
                    "status": "INVALID_EVIDENCE",
                }

                continue


            # ==============================================
            # GET OCR CONFIDENCES
            # ==============================================

            evidence_confidences = []


            for line_id in field.source_line_ids:

                line_index = int(
                    line_id[1:]
                )


                confidence = (
                    ocr_lines[
                        line_index
                    ]["confidence"]
                )


                evidence_confidences.append(
                    confidence
                )


            # ==============================================
            # NO VALID CONFIDENCE
            # ==============================================

            if not evidence_confidences:

                results[field_name] = {
                    "value": field.value,
                    "confidence": None,
                    "status": "NO_CONFIDENCE",
                }

                continue


            # ==============================================
            # CONSERVATIVE FIELD CONFIDENCE
            # ==============================================

            field_confidence = min(
                evidence_confidences
            )


            results[field_name] = {
                "value": field.value,
                "confidence": field_confidence,
                "status": "VALID",
            }


        return results