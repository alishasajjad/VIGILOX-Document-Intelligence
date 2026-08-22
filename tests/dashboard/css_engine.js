/* ==========================================================
   VIGILOX CSS DISPLAY ENGINE
   PHASE 8 FINAL VISUAL QA
   ==========================================================
   A small, deliberate CSS cascade that resolves one property:
   display. It exists because of a real defect that every
   existing test passed straight through.

   The product hides and shows things with the hidden
   attribute in eleven modules. The browser's own stylesheet
   says [hidden] { display: none }, but an author rule setting
   display beats it regardless of specificity, because author
   styles outrank the user-agent origin. The elements being
   hidden carry .btn, .alert, .badge, .file-card,
   .processing-panel, .drop-zone and img -- every one of which
   sets display. So hidden was inert on exactly the elements
   that depended on it.

   In a real browser that produced an upload page showing
   "Analysis in progress", "Document analyzed successfully"
   and "Analysis failed" at the same time, a file card whose
   <img> had no src rendered as a broken image, and a
   workspace offering Approve, Correct, Reject, Submit
   Corrections and Cancel at once.

   The tests could not see any of it, because they asked
   element.hidden -- a property that was being set perfectly
   correctly. The question they should have asked is whether
   the element would actually be painted.

   So this engine answers that question, and the harnesses
   assert on it. Asserting on .hidden proves the JavaScript
   ran; asserting on isDisplayed() proves the user cannot see
   two mutually exclusive states at once.

   Scope is intentionally narrow. It models cascade origin,
   !important, specificity, source order and width-based media
   queries, for display only. It is not a layout engine and
   makes no claim about geometry, colour or overflow.
   ========================================================== */

"use strict";

const fs = require("fs");
const path = require("path");

const PROJECT_ROOT = path.resolve(__dirname, "..", "..");
const STATIC_ROOT = path.join(PROJECT_ROOT, "frontend", "static");
const PAGES_ROOT = path.join(PROJECT_ROOT, "frontend", "pages");


/* ==========================================================
   USER-AGENT DEFAULTS
   ==========================================================
   Only the tags this product actually uses. An unknown tag
   throws rather than being guessed at, so a new element type
   cannot quietly acquire a wrong default.
   ========================================================== */

const UA_DISPLAY = {
    html: "block",
    body: "block",
    div: "block",
    p: "block",
    h1: "block",
    h2: "block",
    h3: "block",
    h4: "block",
    h5: "block",
    h6: "block",
    ul: "block",
    ol: "block",
    li: "list-item",
    section: "block",
    article: "block",
    header: "block",
    footer: "block",
    nav: "block",
    main: "block",
    aside: "block",
    form: "block",
    fieldset: "block",
    legend: "block",
    figure: "block",
    figcaption: "block",
    hr: "block",
    pre: "block",
    blockquote: "block",
    table: "table",
    thead: "table-header-group",
    tbody: "table-row-group",
    tfoot: "table-footer-group",
    tr: "table-row",
    td: "table-cell",
    th: "table-cell",
    caption: "table-caption",
    colgroup: "table-column-group",
    col: "table-column",
    span: "inline",
    a: "inline",
    strong: "inline",
    em: "inline",
    small: "inline",
    code: "inline",
    kbd: "inline",
    samp: "inline",
    abbr: "inline",
    time: "inline",
    label: "inline",
    button: "inline-block",
    input: "inline-block",
    select: "inline-block",
    textarea: "inline-block",
    option: "block",
    optgroup: "block",
    img: "inline",
    svg: "inline",
    video: "inline",
    canvas: "inline",
    iframe: "inline",
    template: "none",
    script: "none",
    style: "none",
    link: "none",
    meta: "none",
    title: "none",
    head: "none",
    /* A dialog is display:none until it is opened. That is the
       user-agent behaviour and it is load-bearing here: the
       confirmation dialog must not be painted before
       showModal(). */
    dialog: "none",
    progress: "inline-block",
    meter: "inline-block",
    details: "block",
    summary: "list-item"
};

function uaDisplay(node) {
    const tag = node.tagName;

    if (!Object.prototype.hasOwnProperty.call(UA_DISPLAY, tag)) {
        throw new Error(
            "css_engine: no user-agent display default for <" +
            tag + ">. Add it to UA_DISPLAY deliberately."
        );
    }

    /* The user-agent stylesheet's own [hidden] rule. It is
       modelled here rather than left out, because leaving it
       out would report a plain <div hidden> with no component
       class as painted -- which is wrong, and would have
       inflated the blast radius of the real defect from the
       elements that actually leaked to every hidden element on
       every page.

       This rule lives in the user-agent origin, so any author
       display declaration outranks it. That is the entire
       mechanism behind the defect. */
    if (node.hidden === true) {
        return "none";
    }

    if (tag === "dialog") {
        return node.open ? "block" : "none";
    }

    return UA_DISPLAY[tag];
}


/* ==========================================================
   COMMENT STRIPPING
   ========================================================== */

function stripComments(css) {
    return css.replace(/\/\*[\s\S]*?\*\//g, "");
}


/* ==========================================================
   MEDIA QUERIES
   ==========================================================
   Only width conditions are evaluated. Anything else -- print,
   prefers-reduced-motion, prefers-color-scheme, hover -- is
   treated as not matching, which is the correct default for a
   normal screen at a given width.
   ========================================================== */

function mediaMatches(query, width) {
    const text = query.toLowerCase().trim();

    if (text.indexOf("print") !== -1) {
        return false;
    }
    if (text.indexOf("prefers-") !== -1) {
        return false;
    }

    /* Comma in a media query is OR. Any matching branch wins. */
    return text.split(",").some(function (branch) {
        const conditions = [];
        const pattern = /\((min-width|max-width)\s*:\s*([\d.]+)px\)/g;
        let found;

        while ((found = pattern.exec(branch)) !== null) {
            conditions.push({ kind: found[1], value: parseFloat(found[2]) });
        }

        if (conditions.length === 0) {
            /* A screen-only or bare "screen" branch matches. */
            return /^\s*(screen|all)?\s*$/.test(branch);
        }

        return conditions.every(function (condition) {
            if (condition.kind === "min-width") {
                return width >= condition.value;
            }
            return width <= condition.value;
        });
    });
}


/* ==========================================================
   SPECIFICITY
   ==========================================================
   (id, class + attribute + pseudo-class, type). Pseudo-elements
   count as type. Matches CSS Selectors level 3, which is all
   this stylesheet set uses.
   ========================================================== */

function specificity(selector) {
    let ids = 0;
    let classes = 0;
    let types = 0;

    /* Strip attribute values first so a value containing a dot
       or a hash is not counted as a class or an id. */
    const cleaned = selector.replace(/\[[^\]]*\]/g, function (attr) {
        classes += 1;
        return " ";
    });

    const tokens = cleaned.match(
        /#[\w-]+|\.[\w-]+|::[\w-]+|:[\w-]+(?:\([^)]*\))?|[a-zA-Z][\w-]*|\*/g
    ) || [];

    tokens.forEach(function (token) {
        if (token.charAt(0) === "#") {
            ids += 1;
        } else if (token.charAt(0) === ".") {
            classes += 1;
        } else if (token.indexOf("::") === 0) {
            types += 1;
        } else if (token.charAt(0) === ":") {
            /* :not() contributes its argument, not itself. */
            if (token.indexOf(":not(") === 0) {
                const inner = token.slice(5, -1);
                const innerScore = specificity(inner);
                ids += innerScore[0];
                classes += innerScore[1];
                types += innerScore[2];
            } else {
                classes += 1;
            }
        } else if (token !== "*") {
            types += 1;
        }
    });

    return [ids, classes, types];
}

function compareSpecificity(left, right) {
    for (let index = 0; index < 3; index += 1) {
        if (left[index] !== right[index]) {
            return left[index] - right[index];
        }
    }
    return 0;
}


/* ==========================================================
   RULE EXTRACTION
   ==========================================================
   Pulls out only the declarations that set display. Everything
   else is skipped, so this stays fast and stays honest about
   what it models.
   ========================================================== */

function extractRules(css, sourceName, startOrder) {
    const clean = stripComments(css);
    const rules = [];
    let order = startOrder;

    /* Walk the top level, tracking @media blocks by depth. */
    let index = 0;
    let mediaQuery = null;
    let mediaEnd = -1;

    while (index < clean.length) {
        const atMedia = clean.indexOf("@media", index);
        const braceOpen = clean.indexOf("{", index);

        if (braceOpen === -1) {
            break;
        }

        if (atMedia !== -1 && atMedia < braceOpen && mediaQuery === null) {
            mediaQuery = clean.slice(atMedia + 6, braceOpen).trim();
            mediaEnd = matchBrace(clean, braceOpen);
            index = braceOpen + 1;
            continue;
        }

        if (mediaEnd !== -1 && braceOpen > mediaEnd) {
            mediaQuery = null;
            mediaEnd = -1;
        }

        /* Skip any other at-rule block wholesale. Nothing in
           this product sets display inside @supports,
           @keyframes or @font-face, and pretending to parse
           them would be worse than skipping them. */
        const selectorText = clean.slice(index, braceOpen).trim();

        if (selectorText.charAt(0) === "@") {
            index = matchBrace(clean, braceOpen) + 1;
            continue;
        }

        const blockEnd = matchBrace(clean, braceOpen);
        const body = clean.slice(braceOpen + 1, blockEnd);

        const display = readDisplay(body);

        if (display) {
            selectorText.split(",").forEach(function (one) {
                const selector = one.trim();

                if (!selector) {
                    return;
                }

                rules.push({
                    selector: selector,
                    media: mediaQuery,
                    value: display.value,
                    important: display.important,
                    specificity: specificity(selector),
                    order: order,
                    source: sourceName
                });

                order += 1;
            });
        } else {
            order += 1;
        }

        index = blockEnd + 1;
    }

    return { rules: rules, order: order };
}

function matchBrace(text, openIndex) {
    let depth = 0;

    for (let index = openIndex; index < text.length; index += 1) {
        if (text.charAt(index) === "{") {
            depth += 1;
        } else if (text.charAt(index) === "}") {
            depth -= 1;

            if (depth === 0) {
                return index;
            }
        }
    }

    throw new Error("css_engine: unbalanced braces");
}

function readDisplay(body) {
    /* Last display declaration in the block wins. */
    let result = null;
    const pattern = /(^|;)\s*display\s*:\s*([^;!}]+)(!\s*important)?\s*(?=;|$)/gi;
    let found;

    while ((found = pattern.exec(body)) !== null) {
        result = {
            value: found[2].trim(),
            important: Boolean(found[3])
        };
    }

    return result;
}


/* ==========================================================
   STYLESHEET LOADING
   ==========================================================
   Order comes from the page's own <link> tags, so the cascade
   reflects what the browser actually receives. A page that
   reorders its stylesheets changes the answer here too.
   ========================================================== */

function stylesheetsForPage(pageName) {
    const html = fs.readFileSync(
        path.join(PAGES_ROOT, pageName),
        "utf8"
    );

    const hrefs = [];
    const pattern = /<link\b[^>]*href\s*=\s*["']([^"']+)["'][^>]*>/gi;
    let found;

    while ((found = pattern.exec(html)) !== null) {
        const href = found[1];

        if (/\.css($|\?)/.test(href)) {
            hrefs.push(href);
        }
    }

    if (hrefs.length === 0) {
        throw new Error(
            "css_engine: " + pageName + " links no stylesheets"
        );
    }

    return hrefs.map(function (href) {
        /* /review/static/css/base.css -> frontend/static/css/base.css */
        const marker = "/review/static/";
        const at = href.indexOf(marker);

        if (at === -1) {
            throw new Error(
                "css_engine: unexpected stylesheet href " + href
            );
        }

        return href.slice(at + marker.length);
    });
}

const sheetCache = {};

function readSheet(relativePath) {
    if (!Object.prototype.hasOwnProperty.call(sheetCache, relativePath)) {
        sheetCache[relativePath] = fs.readFileSync(
            path.join(STATIC_ROOT, relativePath),
            "utf8"
        );
    }
    return sheetCache[relativePath];
}


/* ==========================================================
   THE ENGINE
   ========================================================== */

function createEngine(pageName, options) {
    const settings = options || {};
    const width = settings.width || 1440;
    const sheets = settings.sheets || stylesheetsForPage(pageName);

    let rules = [];
    let order = 0;

    sheets.forEach(function (relativePath) {
        const extracted = extractRules(
            readSheet(relativePath),
            relativePath,
            order
        );

        rules = rules.concat(extracted.rules);
        order = extracted.order;
    });

    /* Drop rules whose media query does not apply at this
       width, once, rather than on every lookup. */
    const active = rules.filter(function (rule) {
        return rule.media === null || mediaMatches(rule.media, width);
    });

    function declarationsFor(node, matches) {
        return active.filter(function (rule) {
            return matches(node, rule.selector);
        });
    }

    function winner(candidates) {
        let best = null;

        candidates.forEach(function (rule) {
            if (best === null) {
                best = rule;
                return;
            }

            if (rule.important !== best.important) {
                if (rule.important) {
                    best = rule;
                }
                return;
            }

            const bySpecificity = compareSpecificity(
                rule.specificity,
                best.specificity
            );

            if (bySpecificity > 0) {
                best = rule;
                return;
            }
            if (bySpecificity === 0 && rule.order > best.order) {
                best = rule;
            }
        });

        return best;
    }

    return {
        width: width,
        sheets: sheets,
        ruleCount: active.length,

        /* The resolved display value for one element, ignoring
           ancestors. */
        displayOf: function (node, matches) {
            const best = winner(declarationsFor(node, matches));

            if (best) {
                return {
                    value: best.value,
                    from: best.source + " { " + best.selector + " }",
                    important: best.important
                };
            }

            return {
                value: uaDisplay(node),
                from: "user-agent",
                important: false
            };
        },

        matchingRules: function (node, matches) {
            return declarationsFor(node, matches);
        }
    };
}


module.exports = {
    createEngine: createEngine,
    stylesheetsForPage: stylesheetsForPage,
    specificity: specificity,
    compareSpecificity: compareSpecificity,
    mediaMatches: mediaMatches,
    extractRules: extractRules,
    readDisplay: readDisplay,
    stripComments: stripComments,
    uaDisplay: uaDisplay,
    UA_DISPLAY: UA_DISPLAY
};
