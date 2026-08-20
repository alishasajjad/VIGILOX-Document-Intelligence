import re
import unicodedata

from datetime import (
    date,
    datetime,
)

from backend.app.domain.schemas import (
    DocumentExtraction,
)


class EvidenceValidator:

    # ======================================================
    # FIELDS THAT REQUIRE DATE SEMANTIC MATCHING
    # ======================================================

    DATE_FIELDS = {
        "expiry_date",
        "date_of_birth",
        "issue_date",
    }


    # ======================================================
    # EXPECTED LABELS / CONTEXT
    # ======================================================

    FIELD_LABELS = {

        "expiry_date": [
            "EXPIRES",
            "EXPIRY",
            "EXPIRY DATE",
            "EXPIRATION",
            "VALID UNTIL",
            "VALID TO",
        ],

        "date_of_birth": [
            "DOB",
            "DATE OF BIRTH",
            "BIRTH DATE",
        ],

        "issue_date": [
            "ISSUED",
            "ISSUE DATE",
            "DATE ISSUED",
            "PRINT DATE",
            "PRINTDATE",
        ],
    }


    # ======================================================
    # TEXT NORMALIZATION
    # ======================================================

    def _normalize_text(
        self,
        text: str,
    ) -> str:

        text = unicodedata.normalize(
            "NFKD",
            text,
        )


        text = "".join(
            char
            for char in text
            if not unicodedata.combining(
                char
            )
        )


        text = text.upper()


        text = "".join(
            char
            for char in text
            if char.isalnum()
        )


        return text


    # ======================================================
    # BUILD OCR EVIDENCE LOOKUP
    # PHASE 7C.2
    # ======================================================

    def _build_ocr_lookup(
        self,
        ocr_lines: list[dict],
    ) -> dict[str, dict]:

        # ==================================================
        # EXPLICIT PROVENANCE LOOKUP
        # ==================================================
        #
        # New OCR records contain:
        #
        # {
        #     "line_id": "L15",
        #     "text": "ISSUED BY TX DPS",
        #     "confidence": 0.99,
        #     "bbox": [...]
        # }
        #
        # EvidenceValidator now resolves evidence directly
        # through this explicit ID instead of converting:
        #
        # L15 -> integer 15 -> ocr_lines[15]
        #
        # That removes positional coupling from the
        # provenance chain.
        # ==================================================

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
                "text"
                not in line
            ):

                raise ValueError(
                    (
                        "OCR line at "
                        f"index {index} "
                        "is missing text."
                    )
                )


            # ==============================================
            # EXPLICIT LINE ID
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
            # Older persisted documents and older test
            # fixtures may not contain line_id.
            #
            # They retain the historical zero-based
            # positional convention:
            #
            # index 0 -> L0
            # index 1 -> L1
            #
            # New OCRService records always contain their
            # explicit line_id.
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

            if not re.fullmatch(
                r"L\d+",
                line_id,
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
    # DATE EXTRACTION
    # ======================================================

    def _extract_date_candidates(
        self,
        text: str,
    ) -> list[str]:

        patterns = [

            # 24 MAR 2021
            # 24 March 2021
            r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4}\b",

            # 24/03/2021
            # 24-03-2021
            r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",

            # 2021-03-24
            # 2021/03/24
            r"\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b",
        ]


        candidates: list[str] = []


        for pattern in patterns:

            matches = re.findall(
                pattern,
                text,
                flags=re.IGNORECASE,
            )


            candidates.extend(
                matches
            )


        return candidates


    # ======================================================
    # POSSIBLE DATE PARSING
    # ======================================================

    def _possible_dates(
        self,
        value: str,
    ) -> set[date]:

        possible: set[date] = set()


        formats = [

            # ISO
            "%Y-%m-%d",
            "%Y/%m/%d",

            # 24 MAR 2021
            "%d %b %Y",
            "%d %B %Y",

            # DD/MM/YYYY
            "%d/%m/%Y",
            "%d/%m/%y",
            "%d-%m-%Y",
            "%d-%m-%y",

            # MM/DD/YYYY
            "%m/%d/%Y",
            "%m/%d/%y",
            "%m-%d-%Y",
            "%m-%d-%y",
        ]


        value = (
            value.strip()
        )


        for date_format in formats:

            try:

                parsed = (
                    datetime.strptime(
                        value,
                        date_format,
                    )
                    .date()
                )


                possible.add(
                    parsed
                )


            except ValueError:

                continue


        return possible


    # ======================================================
    # DATE SEMANTIC MATCHING
    # ======================================================

    def _date_is_supported(
        self,
        extracted_value: str,
        evidence_texts: list[str],
    ) -> bool:

        target_dates = (
            self._possible_dates(
                extracted_value
            )
        )


        if not target_dates:

            return False


        for evidence in evidence_texts:

            candidates = (
                self._extract_date_candidates(
                    evidence
                )
            )


            for candidate in candidates:

                evidence_dates = (
                    self._possible_dates(
                        candidate
                    )
                )


                if target_dates.intersection(
                    evidence_dates
                ):

                    return True


        return False


    # ======================================================
    # NORMAL TEXT SEMANTIC MATCH
    # ======================================================

    def _text_is_supported(
        self,
        extracted_value: str,
        evidence_texts: list[str],
    ) -> bool:

        normalized_value = (
            self._normalize_text(
                extracted_value
            )
        )


        normalized_evidence = (
            self._normalize_text(
                " ".join(
                    evidence_texts
                )
            )
        )


        if not normalized_value:

            return False


        return (
            normalized_value
            in normalized_evidence
        )


    # ======================================================
    # CONTEXT LABEL CHECK
    # ======================================================

    def _has_expected_context(
        self,
        field_name: str,
        evidence_texts: list[str],
    ) -> bool:

        expected_labels = (
            self.FIELD_LABELS.get(
                field_name
            )
        )


        # Name, licence number, ID number
        # and issuer currently do not require
        # an explicit label.
        if not expected_labels:

            return True


        combined = (
            " ".join(
                evidence_texts
            )
            .upper()
        )


        return any(
            label
            in combined

            for label
            in expected_labels
        )


    # ======================================================
    # MAIN VALIDATOR
    # ======================================================

    def validate(
        self,
        extraction: DocumentExtraction,
        ocr_lines: list[dict],
    ) -> list[str]:

        flags: list[str] = []


        # ==================================================
        # BUILD EXPLICIT OCR EVIDENCE LOOKUP
        # PHASE 7C.2
        # ==================================================

        ocr_lookup = (
            self._build_ocr_lookup(
                ocr_lines
            )
        )


        valid_line_ids = set(
            ocr_lookup.keys()
        )


        # ==================================================
        # FIELDS TO VALIDATE
        # ==================================================

        fields = {

            "full_name":
                extraction.full_name,

            "licence_number":
                extraction.licence_number,

            "id_number":
                extraction.id_number,

            "expiry_date":
                extraction.expiry_date,

            "date_of_birth":
                extraction.date_of_birth,

            "issue_date":
                extraction.issue_date,

            "issuer":
                extraction.issuer,
        }


        # ==================================================
        # VALIDATE EACH FIELD
        # ==================================================

        for (
            field_name,
            field,
        ) in fields.items():


            # ==============================================
            # FIELD NOT EXTRACTED
            # ==============================================

            if field.value is None:

                continue


            # ==============================================
            # V1 — VALUE EXISTS BUT NO EVIDENCE
            # ==============================================

            if not field.source_line_ids:

                flags.append(
                    (
                        f"{field_name.upper()}"
                        "_NO_EVIDENCE"
                    )
                )


                continue


            # ==============================================
            # V1 — INVALID SOURCE IDS
            # ==============================================

            invalid_ids = [

                line_id

                for line_id
                in field.source_line_ids

                if (
                    line_id
                    not in valid_line_ids
                )
            ]


            if invalid_ids:

                for line_id in invalid_ids:

                    flags.append(
                        (
                            f"{field_name.upper()}"
                            "_INVALID_SOURCE_LINE_ID:"
                            f"{line_id}"
                        )
                    )


                # Semantic validation cannot continue
                # if source references are invalid.
                continue


            # ==============================================
            # GATHER OCR EVIDENCE BY EXPLICIT LINE ID
            # PHASE 7C.2
            # ==============================================

            evidence_texts: list[str] = []


            for line_id in (
                field.source_line_ids
            ):

                ocr_line = (
                    ocr_lookup.get(
                        line_id
                    )
                )


                # This should normally be impossible because
                # invalid IDs were already checked above.
                # Keep the guard for defensive integrity.
                if ocr_line is None:

                    flags.append(
                        (
                            f"{field_name.upper()}"
                            "_INVALID_SOURCE_LINE_ID:"
                            f"{line_id}"
                        )
                    )


                    continue


                evidence_text = (
                    ocr_line.get(
                        "text"
                    )
                )


                if not isinstance(
                    evidence_text,
                    str,
                ):

                    flags.append(
                        (
                            f"{field_name.upper()}"
                            "_INVALID_EVIDENCE_TEXT:"
                            f"{line_id}"
                        )
                    )


                    continue


                evidence_texts.append(
                    evidence_text
                )


            if not evidence_texts:

                flags.append(
                    (
                        f"{field_name.upper()}"
                        "_NO_VALID_EVIDENCE"
                    )
                )


                continue


            # ==============================================
            # V2 — VALUE SUPPORT
            # ==============================================

            if (
                field_name
                in self.DATE_FIELDS
            ):

                value_supported = (
                    self._date_is_supported(
                        field.value,
                        evidence_texts,
                    )
                )


            else:

                value_supported = (
                    self._text_is_supported(
                        field.value,
                        evidence_texts,
                    )
                )


            if not value_supported:

                flags.append(
                    (
                        f"{field_name.upper()}"
                        "_EVIDENCE_MISMATCH"
                    )
                )


                continue


            # ==============================================
            # V2 — FIELD CONTEXT SUPPORT
            # ==============================================

            context_supported = (
                self._has_expected_context(
                    field_name,
                    evidence_texts,
                )
            )


            if not context_supported:

                flags.append(
                    (
                        f"{field_name.upper()}"
                        "_CONTEXT_MISSING"
                    )
                )


        return flags