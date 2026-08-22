from datetime import date

from backend.app.services.ocr_service import OCRService
from backend.app.services.extraction_service import ExtractionService
from backend.app.services.evidence_validator import EvidenceValidator
from backend.app.services.confidence_service import ConfidenceService
from backend.app.services.date_logical_validator import DateLogicalValidator
from backend.app.services.document_anomaly_validator import DocumentAnomalyValidator
from backend.app.services.review_decision_service import ReviewDecisionService

from backend.app.core.timing import StageTimer

from backend.app.services.document_quality_service import (
    DocumentQualityService,
    apply_quality_to_review,
)

from backend.app.domain.classification import (
    apply_classification_to_review,
    classify_outcome,
)


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


        # ==================================================
        # PHASE 10.1 - IMAGE QUALITY
        # ==================================================
        #
        # Stateless and cheap: five OpenCV measurements over
        # one image. Constructed here for symmetry with the
        # other services rather than because it holds
        # anything.
        # ==================================================

        self.quality_service = (
            DocumentQualityService()
        )


    # ======================================================
    # PROCESS DOCUMENT
    # ======================================================

    def process(
        self,
        image_path: str,
        reference_date: date | None = None,
        timer: StageTimer | None = None,
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

        timer:
            Optional StageTimer. When supplied, each stage
            records how long it took.

            PHASE 9.1. It is an out-parameter rather than a
            key in the returned dict because that dict is
            persisted almost verbatim, and how long OCR took
            is not part of what was read off the document.
            The returned value is unchanged whether a timer
            is passed or not.
        """

        # A discard timer keeps one code path below rather
        # than an "if timer" around all seven stages.
        stages = (
            timer
            if timer is not None
            else StageTimer()
        )


        # ==================================================
        # PHASE 1 — OCR
        # ==================================================

        # ==================================================
        # PHASE 10.1 - IMAGE QUALITY
        # ==================================================
        #
        # Before OCR, because it measures the image rather than
        # the text, and because a reviewer looking at a failed
        # extraction wants to know the photograph was unusable.
        #
        # It cannot affect what OCR reads: it opens the file
        # read-only and returns numbers.
        # ==================================================

        with stages.stage("quality"):

            quality_assessment = (
                self.quality_service.assess(
                    image_path
                )
            )


        with stages.stage("ocr"):

            ocr_lines = (
                self.ocr_service.extract(
                    image_path
                )
            )


        # ==================================================
        # PHASE 2 — STRUCTURED EXTRACTION
        # ==================================================

        with stages.stage("extraction"):

            extraction = (
                self.extraction_service.extract(
                    ocr_lines
                )
            )


        # ==================================================
        # PHASE 3 — EVIDENCE VALIDATION
        # ==================================================

        with stages.stage("evidence"):

            evidence_flags = (
                self.evidence_validator.validate(
                    extraction,
                    ocr_lines,
                )
            )


        # ==================================================
        # PHASE 4A — FIELD CONFIDENCE
        # ==================================================

        with stages.stage("confidence"):

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

        with stages.stage("dates"):

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

        with stages.stage("anomalies"):

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

        with stages.stage("review_decision"):

            review_result = (
                self.review_decision_service.decide(
                    anomaly_result
                )
            )

            # PHASE 10.1. Applied after the review service,
            # which is untouched. Can only escalate
            # AUTO_ACCEPT to REVIEW_REQUIRED; never the
            # reverse. See apply_quality_to_review().
            review_result = (
                apply_quality_to_review(
                    review_result,
                    quality_assessment,
                )
            )


            # ==========================================
            # PHASE 10.2 - CLASSIFICATION OUTCOME
            # ==========================================
            #
            # Runs last, and reads three things the pipeline
            # has already produced: the extracted
            # document_type, the quality finding codes, and
            # how many OCR lines were read.
            #
            # Its only effect is REVIEW_REQUIRED ->
            # UNSUPPORTED_DOCUMENT for a document that is
            # confidently not one of the three supported
            # types. It cannot produce AUTO_ACCEPT.
            #
            # After quality on purpose: the decision whether
            # "unsupported" is a safe conclusion depends on
            # whether the image could be read at all, so the
            # quality findings have to exist first.
            # ==========================================

            classification_outcome = (
                classify_outcome(
                    document_type=(
                        extraction.document_type
                    ),
                    quality_finding_codes=[
                        finding.code
                        for finding in (
                            quality_assessment
                            .findings
                        )
                    ],
                    ocr_line_count=len(
                        ocr_lines
                    ),
                )
            )

            review_result = (
                apply_classification_to_review(
                    review_result,
                    classification_outcome,
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

            # PHASE 10.1. Image measurements and any findings.
            # Separate from the extraction on purpose: this
            # describes the photograph, not the document.
            "quality":
                quality_assessment.to_dict(),

            "review_decision":
                review_result,
        }