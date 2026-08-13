import re
import unicodedata
from datetime import (
    datetime,
    date,
)

from src.schemas import (
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
    # SOURCE LINE ID -> OCR INDEX
    # ======================================================

    def _line_id_to_index(
        self,
        line_id: str,
    ) -> int | None:

        if not isinstance(
            line_id,
            str,
        ):
            return None

        if not re.fullmatch(
            r"L\d+",
            line_id,
        ):
            return None

        try:

            return int(
                line_id[1:]
            )

        except ValueError:

            return None


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


        value = value.strip()


        for date_format in formats:

            try:

                parsed = datetime.strptime(
                    value,
                    date_format,
                ).date()

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


        combined = " ".join(
            evidence_texts
        ).upper()


        return any(
            label in combined
            for label in expected_labels
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


        # --------------------------------------------------
        # Valid OCR IDs
        # --------------------------------------------------

        valid_line_ids = {
            f"L{index}"
            for index in range(
                len(ocr_lines)
            )
        }


        # --------------------------------------------------
        # Fields to validate
        # --------------------------------------------------

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


        # --------------------------------------------------
        # Validate each field
        # --------------------------------------------------

        for field_name, field in (
            fields.items()
        ):


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
                    f"{field_name.upper()}"
                    "_NO_EVIDENCE"
                )

                continue


            # ==============================================
            # V1 — INVALID SOURCE IDS
            # ==============================================

            invalid_ids = [

                line_id

                for line_id
                in field.source_line_ids

                if line_id
                not in valid_line_ids
            ]


            if invalid_ids:

                for line_id in invalid_ids:

                    flags.append(
                        f"{field_name.upper()}"
                        "_INVALID_SOURCE_LINE_ID:"
                        f"{line_id}"
                    )

                # Semantic validation cannot continue
                # if source references are invalid.
                continue


            # ==============================================
            # GATHER OCR EVIDENCE
            # ==============================================

            evidence_texts: list[str] = []


            for line_id in (
                field.source_line_ids
            ):

                line_index = (
                    self._line_id_to_index(
                        line_id
                    )
                )


                if line_index is None:

                    flags.append(
                        f"{field_name.upper()}"
                        "_INVALID_SOURCE_LINE_ID:"
                        f"{line_id}"
                    )

                    continue


                if not (
                    0
                    <= line_index
                    < len(ocr_lines)
                ):

                    flags.append(
                        f"{field_name.upper()}"
                        "_INVALID_SOURCE_LINE_ID:"
                        f"{line_id}"
                    )

                    continue


                evidence_texts.append(
                    ocr_lines[
                        line_index
                    ]["text"]
                )


            if not evidence_texts:

                flags.append(
                    f"{field_name.upper()}"
                    "_NO_VALID_EVIDENCE"
                )

                continue


            # ==============================================
            # V2 — VALUE SUPPORT
            # ==============================================

            if field_name in self.DATE_FIELDS:

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
                    f"{field_name.upper()}"
                    "_EVIDENCE_MISMATCH"
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
                    f"{field_name.upper()}"
                    "_CONTEXT_MISSING"
                )


        return flags