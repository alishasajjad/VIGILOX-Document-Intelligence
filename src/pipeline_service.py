from datetime import date

from src.ocr_service import OCRService
from src.extraction_service import ExtractionService
from src.evidence_validator import EvidenceValidator
from src.confidence_service import ConfidenceService
from src.date_logical_validator import DateLogicalValidator
from src.document_anomaly_validator import DocumentAnomalyValidator
from src.review_decision_service import ReviewDecisionService


class DocumentPipelineService:

    def __init__(self):

        # ==================================================
        # PHASE 1 — OCR SERVICE
        # ==================================================

        self.ocr_service = (
            OCRService()
        )


        # ==================================================
        # PHASE 2 — STRUCTURED EXTRACTION SERVICE
        # ==================================================

        self.extraction_service = (
            ExtractionService()
        )


        # ==================================================
        # PHASE 3 — EVIDENCE VALIDATION SERVICE
        # ==================================================

        self.evidence_validator = (
            EvidenceValidator()
        )


        # ==================================================
        # PHASE 4A — FIELD CONFIDENCE SERVICE
        # ==================================================

        self.confidence_service = (
            ConfidenceService()
        )


        # ==================================================
        # PHASE 4B — DATE / LOGICAL VALIDATION SERVICE
        # ==================================================

        self.date_logical_validator = (
            DateLogicalValidator()
        )


        # ==================================================
        # PHASE 4C — DOCUMENT ANOMALY SERVICE
        # ==================================================

        self.document_anomaly_validator = (
            DocumentAnomalyValidator()
        )


        # ==================================================
        # PHASE 5A — MACHINE REVIEW DECISION SERVICE
        # ==================================================

        self.review_decision_service = (
            ReviewDecisionService()
        )


    # ======================================================
    # PROCESS DOCUMENT
    # ======================================================

    def process(
        self,
        image_path: str,
        reference_date: date | None = None,
    ) -> dict:

        """
        Run the complete VIGILOX document intelligence
        pipeline for a single document image.

        reference_date:
            Optional fixed date used by the date/logical
            validator.

            If None, the validator uses the current date.

            A fixed reference date is useful for research
            evaluation so expiry results remain reproducible.
        """


        # ==================================================
        # PHASE 1 — OCR
        # ==================================================

        ocr_lines = (
            self.ocr_service.extract(
                image_path
            )
        )


        # ==================================================
        # PHASE 2 — STRUCTURED EXTRACTION
        # ==================================================

        extraction = (
            self.extraction_service.extract(
                ocr_lines
            )
        )


        # ==================================================
        # PHASE 3 — EVIDENCE VALIDATION
        # ==================================================

        evidence_flags = (
            self.evidence_validator.validate(
                extraction,
                ocr_lines,
            )
        )


        # ==================================================
        # PHASE 4A — FIELD CONFIDENCE
        # ==================================================

        confidence_results = (
            self.confidence_service.calculate(
                extraction,
                ocr_lines,
                evidence_flags,
            )
        )


        # ==================================================
        # PHASE 4B — DATE / LOGICAL VALIDATION
        # ==================================================

        date_validation = (
            self.date_logical_validator.validate(
                extraction,
                confidence_results,
                reference_date=reference_date,
            )
        )


        # ==================================================
        # PHASE 4C — DOCUMENT ANOMALIES
        # ==================================================

        anomaly_result = (
            self.document_anomaly_validator.validate(
                extraction,
                confidence_results,
                date_validation,
            )
        )


        # ==================================================
        # PHASE 5A — MACHINE REVIEW DECISION
        # ==================================================

        review_result = (
            self.review_decision_service.decide(
                anomaly_result
            )
        )


        # ==================================================
        # COMPLETE RESULT
        # ==================================================

        return {

            "extraction":
                extraction.model_dump(),

            "ocr_lines":
                ocr_lines,

            "evidence_flags":
                evidence_flags,

            "field_confidence":
                confidence_results,

            "date_validation":
                date_validation,

            "anomaly_validation":
                anomaly_result,

            "review_decision":
                review_result,
        }