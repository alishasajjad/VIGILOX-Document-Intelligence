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

    def extract(
        self,
        image_path: str,
    ) -> list[dict]:

        results = self.ocr.predict(
            image_path
        )

        extracted_lines: list[dict] = []

        for result in results:

            data = result.json["res"]

            texts = data["rec_texts"]
            scores = data["rec_scores"]
            boxes = data["rec_boxes"]

            for text, score, box in zip(
                texts,
                scores,
                boxes,
            ):

                # Depending on PaddleOCR output,
                # bbox may already be a Python list.
                bbox = (
                    box.tolist()
                    if hasattr(box, "tolist")
                    else box
                )

                extracted_lines.append(
                    {
                        "text": text,
                        "confidence": float(score),
                        "bbox": bbox,
                    }
                )

        return extracted_lines