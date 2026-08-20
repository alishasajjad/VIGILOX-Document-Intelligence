/* ==========================================================
   VIGILOX SHARED UI
   PHASE 8.5
   ==========================================================

   Shared helpers for the application shell and for rendering.

   SAFE RENDERING RULE
   ----------------------------------------------------------
   Everything here builds DOM nodes and assigns textContent.
   Nothing in this file writes innerHTML.

   OCR text, extracted values, filenames and reviewer ids all
   originate from uploaded documents, so they are untrusted
   input. Interpolating them into innerHTML would be an
   injection path. New Phase 8 code uses these helpers; the
   legacy innerHTML sites in review_detail.js are known debt
   and are replaced as each screen is rebuilt.
   ========================================================== */

(function (global) {
    "use strict";

    var api = global.VigiloxApi;


    /* ======================================================
       DOM CONSTRUCTION
       ====================================================== */

    /**
     * Build an element.
     *
     * `text` is always applied via textContent, so callers
     * cannot accidentally inject markup.
     */
    function el(tag, options) {
        var node = document.createElement(tag);
        var config = options || {};

        if (config.className) {
            node.className = config.className;
        }

        if (config.text !== undefined && config.text !== null) {
            node.textContent = String(config.text);
        }

        if (config.attrs) {
            Object.keys(config.attrs).forEach(function (name) {
                var value = config.attrs[name];
                if (value !== null && value !== undefined) {
                    node.setAttribute(name, String(value));
                }
            });
        }

        if (config.children) {
            config.children.forEach(function (child) {
                if (child) {
                    node.appendChild(child);
                }
            });
        }

        return node;
    }

    function clear(node) {
        if (!node) {
            return;
        }
        while (node.firstChild) {
            node.removeChild(node.firstChild);
        }
    }

    function replaceChildren(node, children) {
        clear(node);
        (children || []).forEach(function (child) {
            if (child) {
                node.appendChild(child);
            }
        });
    }

    function byId(id) {
        return document.getElementById(id);
    }


    /* ======================================================
       VALUE FORMATTING
       ====================================================== */

    var EMPTY_DISPLAY = "Not detected";

    function isBlank(value) {
        return (
            value === null ||
            value === undefined ||
            (typeof value === "string" && value.trim() === "")
        );
    }

    function displayValue(value) {
        return isBlank(value) ? EMPTY_DISPLAY : String(value);
    }

    /** Machine-readable enum to human label: PENDING_REVIEW -> Pending Review */
    function humanizeEnum(value) {
        if (isBlank(value)) {
            return "Unknown";
        }
        return String(value)
            .toLowerCase()
            .split(/[_\s]+/)
            .map(function (word) {
                return word ? word.charAt(0).toUpperCase() + word.slice(1) : "";
            })
            .join(" ");
    }

    function formatDocumentType(value) {
        if (isBlank(value)) {
            return "Unknown type";
        }
        var map = {
            guard_license: "Guard Licence",
            sia_badge: "SIA Badge",
            id_card: "ID Card"
        };
        return map[value] || humanizeEnum(value);
    }

    /** ISO date -> 12 Sep 2026. Returns the input unchanged if unparseable. */
    function formatDate(value) {
        if (isBlank(value)) {
            return EMPTY_DISPLAY;
        }
        var parsed = new Date(value);
        if (isNaN(parsed.getTime())) {
            return String(value);
        }
        var months = [
            "Jan", "Feb", "Mar", "Apr", "May", "Jun",
            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
        ];
        return (
            parsed.getDate() + " " +
            months[parsed.getMonth()] + " " +
            parsed.getFullYear()
        );
    }

    function formatDateTime(value) {
        if (isBlank(value)) {
            return EMPTY_DISPLAY;
        }
        var parsed = new Date(value);
        if (isNaN(parsed.getTime())) {
            return String(value);
        }
        var hours = String(parsed.getHours()).padStart(2, "0");
        var minutes = String(parsed.getMinutes()).padStart(2, "0");
        return formatDate(value) + ", " + hours + ":" + minutes;
    }

    function formatBytes(bytes) {
        if (typeof bytes !== "number" || isNaN(bytes)) {
            return "";
        }
        if (bytes < 1024) {
            return bytes + " B";
        }
        if (bytes < 1024 * 1024) {
            return (bytes / 1024).toFixed(0) + " KB";
        }
        return (bytes / (1024 * 1024)).toFixed(1) + " MB";
    }


    /* ======================================================
       CONFIDENCE
       ======================================================
       Backend supplies a 0..1 confidence. Band thresholds
       live here so the CSS band colours and the JS labels
       cannot drift apart.
       ====================================================== */

    var CONFIDENCE_HIGH = 0.90;
    var CONFIDENCE_MEDIUM = 0.70;

    function confidenceBand(value) {
        if (typeof value !== "number" || isNaN(value)) {
            return "unknown";
        }
        if (value >= CONFIDENCE_HIGH) {
            return "high";
        }
        if (value >= CONFIDENCE_MEDIUM) {
            return "medium";
        }
        return "low";
    }

    function formatConfidence(value) {
        if (typeof value !== "number" || isNaN(value)) {
            return "N/A";
        }
        return Math.round(value * 100) + "%";
    }

    /** Track + fill + percentage. Returns a DOM node. */
    function confidenceIndicator(value) {
        var band = confidenceBand(value);
        var percent = typeof value === "number" && !isNaN(value)
            ? Math.max(0, Math.min(100, Math.round(value * 100)))
            : 0;

        var fill = el("div", {
            className: "confidence-fill is-" + band
        });
        fill.style.width = percent + "%";

        return el("div", {
            className: "confidence",
            attrs: {
                title: "Field confidence: " + formatConfidence(value)
            },
            children: [
                el("div", {
                    className: "confidence-track",
                    children: [fill]
                }),
                el("span", {
                    className:
                        "confidence-value" +
                        (band === "unknown" ? " is-unknown" : ""),
                    text: formatConfidence(value)
                })
            ]
        });
    }


    /* ======================================================
       BADGES
       ====================================================== */

    function badge(text, modifier) {
        return el("span", {
            className: "badge " + (modifier || "badge-neutral"),
            text: text
        });
    }

    function slug(value) {
        return String(value || "").toLowerCase().replace(/_/g, "-");
    }

    function priorityBadge(priority) {
        var known = { HIGH: 1, MEDIUM: 1, LOW: 1 };
        var key = String(priority || "").toUpperCase();
        return badge(
            humanizeEnum(key) || "Unknown",
            known[key]
                ? "badge-priority-" + slug(key)
                : "badge-neutral"
        );
    }

    /** Final record state, mirroring backend final_status. */
    function finalStateBadge(state) {
        var known = {
            AUTO_ACCEPTED: 1,
            PENDING_REVIEW: 1,
            APPROVED: 1,
            CORRECTED: 1,
            REJECTED: 1
        };
        var key = String(state || "").toUpperCase();
        return badge(
            known[key] ? humanizeEnum(key) : "Unknown",
            known[key] ? "badge-state-" + slug(key) : "badge-neutral"
        );
    }

    /** Expiry status from date_validation.expiry.status. */
    function expiryBadge(status) {
        var known = { EXPIRED: 1, EXPIRING_SOON: 1, VALID: 1 };
        var key = String(status || "").toUpperCase();
        if (!known[key]) {
            return badge("Unknown", "badge-expiry-unknown");
        }
        return badge(humanizeEnum(key), "badge-expiry-" + slug(key));
    }

    /**
     * Anomaly severity. Only severities the backend actually
     * emits are mapped; anything else falls back to neutral
     * rather than inventing a severity level.
     */
    function severityBadge(severity) {
        var known = { CRITICAL: 1, ERROR: 1, WARNING: 1, INFO: 1 };
        var key = String(severity || "").toUpperCase();
        return badge(
            known[key] ? humanizeEnum(key) : "Notice",
            known[key] ? "badge-severity-" + slug(key) : "badge-neutral"
        );
    }

    /**
     * Provenance. MACHINE vs HUMAN_CORRECTION must be
     * unmistakable, so they get distinct colour families.
     */
    function provenanceBadge(source) {
        var key = String(source || "").toUpperCase();
        if (key === "HUMAN_CORRECTION") {
            return badge("Human Corrected", "badge-provenance-human");
        }
        if (key === "MACHINE") {
            return badge("Machine", "badge-provenance-machine");
        }
        return badge(humanizeEnum(key), "badge-neutral");
    }


    /* ======================================================
       LOADING
       ======================================================
       Indeterminate only. No fake percentages: the analyze
       endpoint is synchronous and reports no stage progress.
       ====================================================== */

    function loadingBlock(message) {
        return el("div", {
            className: "loading-block",
            attrs: { role: "status", "aria-live": "polite" },
            children: [
                el("div", { className: "spinner" }),
                el("span", { text: message || "Loading..." })
            ]
        });
    }

    function skeletonRows(rowCount, columnCount) {
        var widths = ["skeleton-w-60", "skeleton-w-40", "skeleton-w-25"];
        var rows = [];
        var r;
        var c;

        for (r = 0; r < (rowCount || 4); r += 1) {
            var cells = [];
            for (c = 0; c < (columnCount || 4); c += 1) {
                cells.push(
                    el("div", {
                        className:
                            "skeleton " + widths[c % widths.length],
                        attrs: { "aria-hidden": "true" }
                    })
                );
            }
            rows.push(
                el("div", { className: "skeleton-row", children: cells })
            );
        }

        return el("div", {
            attrs: { role: "status", "aria-label": "Loading content" },
            children: rows
        });
    }

    function skeletonCards(count) {
        var cards = [];
        var i;
        for (i = 0; i < (count || 4); i += 1) {
            cards.push(
                el("div", {
                    className: "skeleton skeleton-card",
                    attrs: { "aria-hidden": "true" }
                })
            );
        }
        return el("div", {
            className: "grid grid-4",
            attrs: { role: "status", "aria-label": "Loading summary" },
            children: cards
        });
    }

    /**
     * Put a button into its pending state and return a
     * restore function. Guards against double submission,
     * which matters because a duplicate review is rejected
     * with HTTP 409 by the backend.
     */
    function setButtonPending(button, isPending) {
        if (!button) {
            return function () {};
        }
        if (isPending) {
            button.disabled = true;
            button.classList.add("is-pending");
            button.setAttribute("aria-busy", "true");
        } else {
            button.disabled = false;
            button.classList.remove("is-pending");
            button.removeAttribute("aria-busy");
        }
        return function () {
            setButtonPending(button, false);
        };
    }


    /* ======================================================
       EMPTY AND ERROR STATES
       ====================================================== */

    function emptyState(options) {
        var config = options || {};
        return el("div", {
            className: "empty-state",
            children: [
                el("p", {
                    className: "empty-title",
                    text: config.title || "Nothing to show"
                }),
                config.description
                    ? el("p", {
                        className: "empty-description",
                        text: config.description
                    })
                    : null
            ]
        });
    }

    /**
     * Render an ApiError.
     *
     * Shows the friendly message, plus the stable error code
     * and request id for support. Never a stack trace: the
     * API does not expose one and the UI must not imply it.
     */
    function errorState(error, options) {
        var config = options || {};
        var isApiError = error && error.code !== undefined;

        var message = isApiError
            ? error.message
            : "Something went wrong.";

        var meta = [];

        if (isApiError && error.code) {
            meta.push(el("span", { text: "Code: " + error.code }));
        }
        if (isApiError && error.requestId) {
            meta.push(
                el("span", { text: "Request: " + error.requestId })
            );
        }

        return el("div", {
            className: "alert alert-danger",
            attrs: { role: "alert" },
            children: [
                el("div", {
                    className: "alert-body",
                    children: [
                        el("p", {
                            className: "alert-title",
                            text: config.title || "Could not load this"
                        }),
                        el("p", { text: message }),
                        meta.length
                            ? el("div", {
                                className: "alert-meta",
                                children: meta
                            })
                            : null
                    ]
                })
            ]
        });
    }

    /** Inline status message bound to an aria-live region. */
    function setStatusMessage(node, message, kind) {
        if (!node) {
            return;
        }
        node.textContent = message || "";
        node.classList.remove("is-success", "is-error", "is-info");
        if (message) {
            node.classList.add("is-visible");
            node.classList.add("is-" + (kind || "info"));
        } else {
            node.classList.remove("is-visible");
        }
    }


    /* ======================================================
       APPLICATION SHELL
       ====================================================== */

    /**
     * Mark the current navigation item.
     *
     * aria-current drives the visual state in layout.css, so
     * the accessible state and the styling cannot diverge.
     */
    function markActiveNav() {
        var path = global.location.pathname;
        var items = document.querySelectorAll(".nav-item[data-nav-match]");

        Array.prototype.forEach.call(items, function (item) {
            var match = item.getAttribute("data-nav-match");
            var isActive =
                match === "exact"
                    ? path === item.getAttribute("href")
                    : path.indexOf(item.getAttribute("data-nav-prefix")) === 0;

            if (isActive) {
                item.setAttribute("aria-current", "page");
                item.classList.add("active");
            } else {
                item.removeAttribute("aria-current");
                item.classList.remove("active");
            }
        });
    }

    function initials(value) {
        var text = String(value || "").trim();
        if (!text) {
            return "?";
        }
        var parts = text.split(/[\s._-]+/).filter(Boolean);
        if (parts.length === 1) {
            return parts[0].slice(0, 2);
        }
        return (parts[0][0] || "") + (parts[1][0] || "");
    }

    /**
     * Load and render the reviewer identity in the shell.
     *
     * Identity comes from GET /api/v1/reviewer/me and is
     * resolved server-side. There is no input for it and the
     * browser cannot influence who the reviewer is.
     *
     * Returns the identity so callers can gate write actions
     * on can_review.
     */
    /**
     * Render an already-resolved reviewer into the shell.
     *
     * Separate from fetching so a page that has already
     * loaded the identity can populate the shell without a
     * second request. review_detail.js does exactly that.
     *
     * `reviewer` is the object from the API's `reviewer` key,
     * or null when identity could not be resolved.
     */
    function applyShellReviewer(reviewer, options) {
        var nameNode = byId("shell-reviewer-name");
        var roleNode = byId("shell-reviewer-role");
        var accessNode = byId("shell-reviewer-access");
        var avatarNode = byId("shell-reviewer-avatar");
        var config = options || {};

        if (!nameNode) {
            return null;
        }

        if (!reviewer) {
            nameNode.textContent =
                config.unauthenticated
                    ? "Not signed in"
                    : "Identity unavailable";

            if (avatarNode) {
                avatarNode.textContent = "?";
            }
            if (roleNode) {
                roleNode.textContent = "";
            }
            if (accessNode) {
                accessNode.textContent = "";
                accessNode.classList.remove("can-review", "read-only");
            }
            return null;
        }

        nameNode.textContent = displayValue(reviewer.reviewer_id);

        if (avatarNode) {
            avatarNode.textContent = initials(reviewer.reviewer_id);
        }

        if (roleNode) {
            roleNode.textContent = displayValue(reviewer.role);
        }

        if (accessNode) {
            /* can_review is decided by the server from the
               reviewer's role. The shell only displays it. */
            var canReview = reviewer.can_review === true;
            accessNode.textContent =
                canReview ? "Can review" : "Read only";
            accessNode.classList.remove("can-review", "read-only");
            accessNode.classList.add(
                canReview ? "can-review" : "read-only"
            );
        }

        return reviewer;
    }

    /** Fetch the identity and render it into the shell. */
    function initShellReviewer() {
        if (!byId("shell-reviewer-name")) {
            return Promise.resolve(null);
        }

        return api.endpoints.getReviewerIdentity().then(
            function (payload) {
                return applyShellReviewer(
                    (payload && payload.reviewer) || null
                );
            },
            function (error) {
                /* An unauthenticated reviewer is a legitimate
                   state, not a crash. Say so plainly and do
                   not leak the error code into the shell. */
                return applyShellReviewer(null, {
                    unauthenticated: Boolean(
                        error && error.isAuthError && error.isAuthError()
                    )
                });
            }
        );
    }

    /**
     * Liveness indicator.
     *
     * Uses GET /health, which is the lightweight endpoint and
     * performs no dependency or inference work. Checked once
     * on load rather than polled, so the shell adds no
     * recurring traffic.
     */
    function initSystemStatus() {
        var dot = byId("status-indicator");
        var label = byId("status-text");

        if (!dot && !label) {
            return Promise.resolve(null);
        }

        return api.endpoints.getHealth().then(
            function () {
                if (dot) {
                    dot.classList.add("online");
                    dot.classList.remove("offline");
                }
                if (label) {
                    label.textContent = "API online";
                }
                return true;
            },
            function () {
                if (dot) {
                    dot.classList.add("offline");
                    dot.classList.remove("online");
                }
                if (label) {
                    label.textContent = "API unreachable";
                }
                return false;
            }
        );
    }

    /**
     * Navigation and liveness only.
     *
     * For pages that already fetch the reviewer identity for
     * their own UI and then call applyShellReviewer, so the
     * shell adds no duplicate request.
     */
    function initShellChrome() {
        markActiveNav();
        initSystemStatus();
    }

    /** Wire up every shell behaviour. Safe to call once per page. */
    function initShell() {
        markActiveNav();
        var reviewer = initShellReviewer();
        initSystemStatus();
        return reviewer;
    }


    global.VigiloxUI = {
        el: el,
        clear: clear,
        replaceChildren: replaceChildren,
        byId: byId,

        isBlank: isBlank,
        displayValue: displayValue,
        humanizeEnum: humanizeEnum,
        formatDocumentType: formatDocumentType,
        formatDate: formatDate,
        formatDateTime: formatDateTime,
        formatBytes: formatBytes,

        CONFIDENCE_HIGH: CONFIDENCE_HIGH,
        CONFIDENCE_MEDIUM: CONFIDENCE_MEDIUM,
        confidenceBand: confidenceBand,
        formatConfidence: formatConfidence,
        confidenceIndicator: confidenceIndicator,

        badge: badge,
        priorityBadge: priorityBadge,
        finalStateBadge: finalStateBadge,
        expiryBadge: expiryBadge,
        severityBadge: severityBadge,
        provenanceBadge: provenanceBadge,

        loadingBlock: loadingBlock,
        skeletonRows: skeletonRows,
        skeletonCards: skeletonCards,
        setButtonPending: setButtonPending,

        emptyState: emptyState,
        errorState: errorState,
        setStatusMessage: setStatusMessage,

        markActiveNav: markActiveNav,
        applyShellReviewer: applyShellReviewer,
        initShellReviewer: initShellReviewer,
        initSystemStatus: initSystemStatus,
        initShellChrome: initShellChrome,
        initShell: initShell
    };

}(window));
