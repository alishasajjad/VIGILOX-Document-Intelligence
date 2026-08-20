from paddleocr import PaddleOCR


class OCRService:

    def __init__(self):

        self.ocr = PaddleOCR(
            lang="en",
            device="cpu",

            # Important compatibility fix for the
            # Paddle/PIR oneDNN issue we encountered.
            enable_mkldnn=False,

            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=True,
        )


    # ======================================================
    # EXTRACT OCR LINES
    # PHASE 7C.2
    # ======================================================

    def extract(
        self,
        image_path: str,
    ) -> list[dict]:

        results = self.ocr.predict(
            image_path
        )


        extracted_lines: list[dict] = []


        for result in results:

            data = (
                result.json[
                    "res"
                ]
            )


            texts = (
                data[
                    "rec_texts"
                ]
            )


            scores = (
                data[
                    "rec_scores"
                ]
            )


            boxes = (
                data[
                    "rec_boxes"
                ]
            )


            for (
                text,
                score,
                box,
            ) in zip(
                texts,
                scores,
                boxes,
            ):

                # ==========================================
                # NORMALIZE BOUNDING BOX
                # ==========================================

                bbox = (
                    box.tolist()
                    if hasattr(
                        box,
                        "tolist",
                    )
                    else box
                )


                # ==========================================
                # EXPLICIT OCR EVIDENCE LINE ID
                # PHASE 7C.2
                # ==========================================
                #
                # line_id is now created at the OCR source
                # rather than later inside ExtractionService.
                #
                # The ID is zero-based to preserve the
                # existing VIGILOX evidence convention:
                #
                # first OCR line  -> L0
                # second OCR line -> L1
                # ...
                #
                # len(extracted_lines) is used instead of
                # a nested-loop index so IDs remain globally
                # sequential even if PaddleOCR returns more
                # than one result block.
                # ==========================================

                line_id = (
                    f"L{len(extracted_lines)}"
                )


                extracted_lines.append(
                    {
                        "line_id":
                            line_id,

                        "text":
                            text,

                        "confidence":
                            float(
                                score
                            ),

                        "bbox":
                            bbox,
                    }
                )


        return extracted_lines