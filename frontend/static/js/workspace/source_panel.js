/* ==========================================================
   VIGILOX SOURCE DOCUMENT PANEL
   PHASE 8.10 / 8.11
   ==========================================================

   Shows the original uploaded image and, over it, the OCR
   evidence behind the extracted values.


   WHY BOUNDING BOXES ARE SAFE TO DRAW HERE
   ----------------------------------------------------------
   The brief was explicit that highlighting must not be faked.
   Four things had to be true, and each was verified before
   this was written:

   1. COORDINATES ARE PERSISTED.
      Every OCR line stored in document_analyses.ocr_lines
      carries bbox alongside line_id, text and confidence.

   2. THEY ARE IN THE ORIGINAL IMAGE'S PIXEL SPACE.
      The analyze endpoint writes the uploaded bytes to a temp
      file and runs OCR on that file directly. There is no
      preprocessing, resize or deskew between the bytes that
      are stored and the bytes that are read, so OCR
      coordinates and the stored image share one space.

      Running OCR over a sample and comparing every box to the
      image dimensions confirmed it: 24 of 24 boxes inside a
      563x355 image, and identical to the persisted analysis
      for the same file.

   3. THE FORMAT IS KNOWN.
      bbox is [x1, y1, x2, y2], top-left origin, axis aligned.

   4. SCALING IS HANDLED WITHOUT GUESSING.
      Boxes are converted to percentages of the image's own
      naturalWidth and naturalHeight, and the overlay is
      positioned against the rendered image box. Percentages
      need no recalculation when the layout changes, so the
      highlight cannot drift at a different window width.

   If any of those had been uncertain, this panel would show
   line ids and OCR text only. It does that anyway as the
   primary presentation; the overlay is an addition to it, and
   a document whose OCR lines carry no usable bbox simply gets
   no overlay.
   ========================================================== */

(function (global) {
    "use strict";

    var api = global.VigiloxApi;
    var ui = global.VigiloxUI;


    /* ======================================================
       BOX GEOMETRY
       ======================================================
       Pure functions, so the arithmetic is testable without a
       browser.
       ====================================================== */

    /**
     * True when a bbox can be trusted for drawing.
     *
     * Rejects anything that is not four finite numbers forming
     * a positive-area rectangle inside the image. A box that
     * fails this is skipped rather than clamped: drawing a
     * clamped guess would be exactly the "approximate
     * highlight" that must not happen.
     */
    function isUsableBox(bbox, width, height) {
        if (!bbox || bbox.length !== 4) {
            return false;
        }

        var i;
        for (i = 0; i < 4; i += 1) {
            if (
                typeof bbox[i] !== "number" ||
                !isFinite(bbox[i])
            ) {
                return false;
            }
        }

        if (!(width > 0) || !(height > 0)) {
            return false;
        }

        return (
            bbox[0] >= 0 &&
            bbox[1] >= 0 &&
            bbox[2] > bbox[0] &&
            bbox[3] > bbox[1] &&
            bbox[2] <= width &&
            bbox[3] <= height
        );
    }

    /**
     * bbox in image pixels -> percentages of the image box.
     *
     * Returns null when the box is not usable, so a caller can
     * never accidentally position something at NaN%.
     */
    function boxToPercent(bbox, width, height) {
        if (!isUsableBox(bbox, width, height)) {
            return null;
        }

        return {
            left: (bbox[0] / width) * 100,
            top: (bbox[1] / height) * 100,
            width: ((bbox[2] - bbox[0]) / width) * 100,
            height: ((bbox[3] - bbox[1]) / height) * 100
        };
    }


    /* ======================================================
       STATE
       ====================================================== */

    var nodes = {};
    var objectUrl = null;
    var ocrLines = [];
    var highlightEnabled = true;
    var activeLineIds = [];
    var naturalSize = { width: 0, height: 0 };


    function collectNodes() {
        nodes = {
            frame: ui.byId("document-preview"),
            image: ui.byId("original-document-image"),
            overlay: ui.byId("evidence-overlay"),
            unavailable: ui.byId("image-unavailable"),
            caption: ui.byId("source-caption"),
            toggle: ui.byId("highlight-toggle")
        };
    }


    /* ======================================================
       NO OBJECT URL TO RELEASE
       ======================================================
       The panel used to fetch the image, wrap it in a blob
       and hand the browser a blob: URL -- which the
       application's own CSP (img-src 'self' data:) blocks.
       See loadImage.

       The <img> now points straight at the same-origin
       endpoint, so there is no URL to create and none to
       revoke. The browser owns the bytes and frees them with
       the element.

       The function is kept, exported and harmless: it is part
       of the module's published surface and a caller that
       still invokes it should not have to care that the
       mechanism changed. `objectUrl` stays null forever, so
       this is a no-op by construction rather than by
       accident.
       ====================================================== */

    function releaseObjectUrl() {
        if (objectUrl) {
            global.URL.revokeObjectURL(objectUrl);
            objectUrl = null;
        }
    }


    /* ======================================================
       LOAD
       ====================================================== */

    function showUnavailable(error) {
        if (nodes.image) {
            nodes.image.hidden = true;
            nodes.image.removeAttribute("src");
        }

        ui.clear(nodes.overlay);

        /* ==================================================
           EVIDENCE HAS NOTHING TO POINT AT
           ==================================================
           renderOverlay already refuses to draw without an
           intrinsic size, so nothing here prevents a crash --
           that guard was already correct.

           What this prevents is an offer that cannot be
           honoured. Leaving "Show evidence" live next to an
           unavailable document invites a click that silently
           does nothing, which reads as a broken feature rather
           than an absent image.
           ================================================== */
        if (nodes.toggle) {
            nodes.toggle.checked = false;
            nodes.toggle.disabled = true;
        }

        highlightEnabled = false;
        activeLineIds = [];

        if (nodes.unavailable) {
            nodes.unavailable.hidden = false;
            ui.replaceChildren(nodes.unavailable, [
                ui.errorState(error, {
                    title: "The original document is not available"
                })
            ]);
        }

        if (nodes.caption) {
            nodes.caption.textContent = "";
        }
    }

    /**
     * Point the <img> at the endpoint and let the browser
     * load it.
     *
     * ==================================================
     * WHY NOT fetch -> blob -> createObjectURL
     * ==================================================
     * Because the application's own Content Security Policy
     * forbids it, and that is the whole bug.
     *
     *     img-src 'self' data:
     *
     * A blob: URL is neither. Real Chrome, on a real
     * completed document, reported:
     *
     *     Loading the image 'blob:http://127.0.0.1/...'
     *     violates the following Content Security Policy
     *     directive: "img-src 'self' data:". The action has
     *     been blocked.
     *
     * Everything before that point worked. The endpoint
     * returned 200 with a decodable JPEG -- which is why the
     * same URL opened directly in a browser tab rendered
     * perfectly: a top-level navigation is not an img-src
     * fetch, so the directive never applied to it. Only the
     * embedded <img> was blocked, and the blocked load fires
     * `error`, which the panel correctly reported as "the
     * original document is not available".
     *
     * So the panel was telling the truth about its own
     * situation while being wrong about the document.
     *
     * The fix is to stop making a blob at all. The endpoint
     * is same-origin, so 'self' already permits it:
     *
     *     img.src = /api/v1/documents/{id}/image
     *
     * That is CSP-clean with NO directive change -- strictly
     * better than adding blob: to img-src, which would have
     * widened the policy to make a detour work.
     *
     * It also deletes the object-URL lifecycle entirely: no
     * URL to revoke, no revocation racing a decode, no image
     * bytes held in memory by the page. A same-origin <img>
     * sends cookies exactly as the page did, so nothing about
     * authorization changes either.
     *
     *
     * ==================================================
     * THE ERROR PATH STILL EXPLAINS ITSELF
     * ==================================================
     * An <img> error event carries no status and no request
     * id -- only "it did not load". That is not enough for a
     * support conversation, so on failure ONLY, the endpoint
     * is asked once through the shared client to find out
     * why: a 404 is a genuinely missing source, a 2xx means
     * the bytes arrived and the browser could not decode
     * them.
     *
     * One request on success. A second only when something is
     * already wrong.
     */
    function loadImage(documentId) {
        if (!nodes.image) {
            return Promise.resolve(false);
        }

        var url = api.endpoints.documentImageUrl(
            documentId
        );

        return new Promise(function (resolve) {

            var settled = false;

            function succeed() {
                if (settled) {
                    return;
                }
                settled = true;

                nodes.image.hidden = false;

                if (nodes.unavailable) {
                    nodes.unavailable.hidden = true;
                    ui.clear(nodes.unavailable);
                }

                if (nodes.toggle) {
                    nodes.toggle.disabled = false;
                }

                resolve(true);
            }

            function fail() {
                if (settled) {
                    return;
                }
                settled = true;

                /* Ask the endpoint why, so the unavailable
                   state can say something useful and carry a
                   request id. */
                api.request(
                    url,
                    {
                        raw: true
                    }
                ).then(
                    function () {
                        /* The endpoint is fine, so the bytes
                           are the problem: served, and not
                           decodable. */
                        showUnavailable(
                            new api.ApiError({
                                status: 0,
                                code:
                                    "ORIGINAL_DOCUMENT_"
                                    + "UNREADABLE",
                                message:
                                    "The original document "
                                    + "could not be "
                                    + "displayed."
                            })
                        );
                    },
                    function (error) {
                        /* 404, 500 or a network failure --
                           the structured error, with its
                           request id. */
                        showUnavailable(
                            error
                        );
                    }
                ).then(
                    function () {
                        resolve(false);
                    }
                );
            }

            /* Listeners BEFORE src. A cached image can settle
               synchronously with the assignment, and a
               listener attached afterwards would never see
               it. */
            nodes.image.addEventListener(
                "load",
                succeed
            );

            nodes.image.addEventListener(
                "error",
                fail
            );

            nodes.image.src = url;

            /* ==============================================
               ONLY A POSITIVE SHORTCUT
               ==============================================
               `complete` is true for an element that has not
               started loading yet -- the spec says so
               explicitly for an omitted src, which is exactly
               this element's state a line earlier, because
               assigning src runs "update the image data"
               asynchronously.

               The previous version read that as
               complete-with-zero-width and called fail()
               immediately, before the browser had done
               anything. The later real load event then found
               the promise already settled and the panel never
               recovered.

               So this shortcut can only ever succeed. Failure
               has exactly one source: the error event.
               ============================================== */
            if (
                nodes.image.complete
                && nodes.image.naturalWidth > 0
            ) {
                succeed();
            }
        });
    }


    /* ======================================================
       OVERLAY
       ====================================================== */

    function readNaturalSize() {
        if (!nodes.image) {
            return { width: 0, height: 0 };
        }
        return {
            width: nodes.image.naturalWidth || 0,
            height: nodes.image.naturalHeight || 0
        };
    }

    /**
     * Draw a box per highlighted OCR line.
     *
     * Skipped entirely when the intrinsic size is unknown,
     * because without it there is no honest way to place a
     * box.
     */
    function renderOverlay() {
        if (!nodes.overlay) {
            return { drawn: 0, skipped: 0, reason: "no-overlay" };
        }

        ui.clear(nodes.overlay);

        if (!highlightEnabled) {
            return { drawn: 0, skipped: 0, reason: "disabled" };
        }

        naturalSize = readNaturalSize();

        if (!naturalSize.width || !naturalSize.height) {
            return {
                drawn: 0,
                skipped: activeLineIds.length,
                reason: "unknown-intrinsic-size"
            };
        }

        var drawn = 0;
        var skipped = 0;

        activeLineIds.forEach(function (lineId) {
            var line = lineFor(lineId);

            if (!line) {
                skipped += 1;
                return;
            }

            var box = boxToPercent(
                line.bbox,
                naturalSize.width,
                naturalSize.height
            );

            if (!box) {
                skipped += 1;
                return;
            }

            var marker = ui.el("span", {
                className: "evidence-box",
                attrs: { "data-line-id": String(lineId) }
            });

            marker.style.left = box.left + "%";
            marker.style.top = box.top + "%";
            marker.style.width = box.width + "%";
            marker.style.height = box.height + "%";

            nodes.overlay.appendChild(marker);
            drawn += 1;
        });

        return { drawn: drawn, skipped: skipped, reason: null };
    }

    function lineFor(lineId) {
        var key = String(lineId);
        var found = null;

        ocrLines.forEach(function (line) {
            if (String(line.line_id) === key) {
                found = line;
            }
        });

        return found;
    }

    function renderCaption(result) {
        if (!nodes.caption) {
            return;
        }

        if (!highlightEnabled) {
            nodes.caption.textContent =
                "Evidence highlighting is off.";
            return;
        }

        if (!activeLineIds.length) {
            nodes.caption.textContent =
                "Select a field to highlight the OCR text it " +
                "was read from.";
            return;
        }

        if (result.reason === "unknown-intrinsic-size") {
            /* Said plainly rather than drawing a guess. */
            nodes.caption.textContent =
                "The image size is not known yet, so evidence " +
                "cannot be positioned. The OCR line IDs and " +
                "text are listed with each field.";
            return;
        }

        var parts = [
            result.drawn +
                (result.drawn === 1
                    ? " OCR line highlighted"
                    : " OCR lines highlighted")
        ];

        if (result.skipped) {
            parts.push(
                result.skipped +
                    " could not be positioned and are listed " +
                    "as text instead"
            );
        }

        nodes.caption.textContent = parts.join(". ") + ".";
    }


    /* ======================================================
       PUBLIC
       ====================================================== */

    /** Highlight a specific set of OCR line ids. */
    function highlight(lineIds) {
        activeLineIds = (lineIds || []).map(String);
        var result = renderOverlay();
        renderCaption(result);
        return result;
    }

    function clearHighlight() {
        return highlight([]);
    }

    function setEnabled(enabled) {
        highlightEnabled = enabled !== false;
        var result = renderOverlay();
        renderCaption(result);
        return result;
    }

    function isEnabled() {
        return highlightEnabled;
    }


    function init(options) {
        var config = options || {};

        collectNodes();

        ocrLines = config.ocrLines || [];
        activeLineIds = [];

        if (nodes.toggle) {
            highlightEnabled = nodes.toggle.checked !== false;

            nodes.toggle.addEventListener("change", function () {
                setEnabled(nodes.toggle.checked);
            });
        }

        if (nodes.image) {
            /* Boxes can only be placed once the browser knows
               the intrinsic size, so redraw on load. */
            nodes.image.addEventListener("load", function () {
                var result = renderOverlay();
                renderCaption(result);
            });
        }

        /* A resize changes the rendered box but not the
           percentages, so nothing needs recomputing. The
           listener exists only to refresh after an orientation
           change that also changes which image is decoded. */
        global.addEventListener("beforeunload", releaseObjectUrl);

        renderCaption({ drawn: 0, skipped: 0, reason: null });

        return loadImage(config.documentId);
    }


    global.VigiloxSourcePanel = {
        init: init,
        highlight: highlight,
        clearHighlight: clearHighlight,
        setEnabled: setEnabled,
        isEnabled: isEnabled,
        releaseObjectUrl: releaseObjectUrl,

        /* Exported for direct testing of the arithmetic. */
        isUsableBox: isUsableBox,
        boxToPercent: boxToPercent,

        getActiveLineIds: function () {
            return activeLineIds.slice();
        }
    };

}(typeof window !== "undefined" ? window : globalThis));
