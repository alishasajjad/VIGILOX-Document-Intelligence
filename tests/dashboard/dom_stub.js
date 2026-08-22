/* ==========================================================
   VIGILOX DOM STUB
   PHASE 8.6B
   ==========================================================

   A small DOM implementation, good enough to EXECUTE the
   VIGILOX frontend modules under Node.

   WHY THIS EXISTS
   ----------------------------------------------------------
   Asserting on JavaScript source text proves only that a
   string is present. It cannot prove that four clicks issue
   one request, that a missing document id never produces
   /review/undefined, that a filter change resets the page
   number, or that a reviewer with read-only access cannot
   reach a submit path.

   Those are behaviours, so the tests run the real modules.

   The upload harness (Phase 8.7) carried its own inline stub
   that supported only getElementById. The Phase 8.6B+ screens
   build their DOM dynamically and query it, so this shared
   stub adds real element trees, aggregate textContent,
   selector matching, event propagation and dialogs.

   SCOPE
   ----------------------------------------------------------
   Deliberately not a browser. It implements what the VIGILOX
   frontend actually uses and nothing more. Anything missing
   throws loudly rather than silently returning undefined, so
   a test can never pass because the stub quietly did nothing.
   ========================================================== */

"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");
const cssEngine = require("./css_engine.js");

const PROJECT_ROOT = path.resolve(__dirname, "..", "..");
const STATIC_ROOT = path.join(PROJECT_ROOT, "frontend", "static");


/* ==========================================================
   SELECTOR MATCHING
   ==========================================================
   Supports the forms the frontend actually uses:

       tag          div
       .class       .alert-body
       #id          #main
       [attr]       [data-nav-match]
       [attr="v"]   [aria-current="page"]

   compounded          a.nav-item[data-nav-match]
   comma separated     .a, .b
   descendant          .card .btn

   Anything else throws, so an unsupported selector is a test
   failure rather than a silently empty result.
   ========================================================== */

const SIMPLE_PART =
    /^(\*|[a-zA-Z][\w-]*)?((?:[.#][\w-]+|\[[^\]]+\])*)$/;

function parseCompound(text) {
    const match = SIMPLE_PART.exec(text.trim());

    if (!match) {
        throw new Error("dom_stub: unsupported selector: " + text);
    }

    const spec = {
        /* "*" matches any tag, which is the same thing as not
           constraining the tag at all. */
        tag:
            match[1] && match[1] !== "*"
                ? match[1].toLowerCase()
                : null,
        classes: [],
        id: null,
        attrs: []
    };

    const rest = match[2] || "";
    /* Attribute operators: exact (=), substring (*=), prefix (^=)
       and suffix ($=). Anything else throws below, so an
       unsupported operator can never silently degrade into
       "has this attribute at all" and match the wrong node.
       That exact bug produced a passing-looking result while
       inspecting the wrong element. */
    const token = /\.([\w-]+)|#([\w-]+)|\[([\w-]+)(?:([*^$~|]?)=["']?([^"'\]]*)["']?)?\]|(\S)/g;
    let found;

    while ((found = token.exec(rest)) !== null) {
        if (found[1]) {
            spec.classes.push(found[1]);
        } else if (found[2]) {
            spec.id = found[2];
        } else if (found[3]) {
            const operator = found[4] || "";

            if (["", "*", "^", "$"].indexOf(operator) === -1) {
                throw new Error(
                    "dom_stub: unsupported attribute operator " +
                    operator + "= in selector: " + text
                );
            }

            spec.attrs.push({
                name: found[3],
                operator: operator,
                value: found[5]
            });
        } else {
            throw new Error(
                "dom_stub: unsupported selector fragment " +
                JSON.stringify(found[6]) + " in: " + text
            );
        }
    }

    return spec;
}

function parseSelector(selector) {
    return String(selector)
        .split(",")
        .map(function (group) {
            return group
                .trim()
                .split(/\s+/)
                .filter(Boolean)
                .map(parseCompound);
        })
        .filter(function (chain) {
            return chain.length > 0;
        });
}

/* Boolean IDL attributes that this stub stores as properties.
   Present with an empty value when true, absent when false --
   which is how a real browser exposes them to a selector. */
const REFLECTED_BOOLEAN = {
    hidden: true,
    disabled: true,
    checked: true,
    open: true
};

function matchesCompound(node, spec) {
    if (spec.tag && node.tagName !== spec.tag) {
        return false;
    }
    if (spec.id && node.id !== spec.id) {
        return false;
    }
    if (
        spec.classes.some(function (name) {
            return !node.classList.contains(name);
        })
    ) {
        return false;
    }
    return spec.attrs.every(function (attr) {
        /* Some attributes are live properties on this stub
           rather than entries in the attribute map. In a real
           DOM these are IDL attributes that reflect the content
           attribute, so a selector must see them. [hidden] is
           the one that matters most: the display cascade below
           depends on it, and reading the attribute map instead
           would report every element as not hidden. */
        let actual;

        if (attr.name === "class") {
            actual = node.className;
        } else if (REFLECTED_BOOLEAN[attr.name]) {
            actual = node[attr.name] ? "" : null;
        } else {
            actual = node.getAttribute(attr.name);
        }

        if (actual === null || actual === undefined) {
            return false;
        }
        if (attr.value === undefined) {
            return true;
        }
        if (attr.operator === "*") {
            return actual.indexOf(attr.value) !== -1;
        }
        if (attr.operator === "^") {
            return actual.indexOf(attr.value) === 0;
        }
        if (attr.operator === "$") {
            return (
                actual.length >= attr.value.length &&
                actual.slice(actual.length - attr.value.length) ===
                    attr.value
            );
        }
        return actual === attr.value;
    });
}

/* A chain matches when the last compound matches the node and
   every earlier compound matches some ancestor, in order. */
function matchesChain(node, chain) {
    if (!matchesCompound(node, chain[chain.length - 1])) {
        return false;
    }

    let index = chain.length - 2;
    let current = node.parentNode;

    while (index >= 0) {
        if (!current) {
            return false;
        }
        if (current.nodeType === 1 && matchesCompound(current, chain[index])) {
            index -= 1;
        }
        current = current.parentNode;
    }

    return true;
}


/* ==========================================================
   ELEMENT
   ========================================================== */

class StubElement {

    constructor(tagName, ownerDocument) {
        this.nodeType = 1;
        this.tagName = String(tagName).toLowerCase();
        this.ownerDocument = ownerDocument;
        this.parentNode = null;
        this.childNodes = [];

        this._text = "";
        this._attributes = {};
        this._classes = new Set();
        this._listeners = {};

        this.style = {};
        this.dataset = {};

        this.hidden = false;
        this.disabled = false;
        this.checked = false;
        this.value = "";
        this.src = null;
        this.open = false;
        this.focused = false;

        /* Real images report their intrinsic size. Evidence
           highlighting scales by these, so tests set them. */
        this.naturalWidth = 0;
        this.naturalHeight = 0;

        const self = this;

        this.classList = {
            add() {
                Array.prototype.forEach.call(arguments, function (name) {
                    self._classes.add(name);
                });
            },
            remove() {
                Array.prototype.forEach.call(arguments, function (name) {
                    self._classes.delete(name);
                });
            },
            contains(name) {
                return self._classes.has(name);
            },
            toggle(name, force) {
                if (force === undefined) {
                    if (self._classes.has(name)) {
                        self._classes.delete(name);
                    } else {
                        self._classes.add(name);
                    }
                    return self._classes.has(name);
                }
                if (force) {
                    self._classes.add(name);
                } else {
                    self._classes.delete(name);
                }
                return force;
            },
            get length() {
                return self._classes.size;
            }
        };
    }


    /* ------------------------------------------------------
       IDENTITY
       ------------------------------------------------------ */

    get id() {
        return this._attributes.id || "";
    }

    set id(value) {
        this._attributes.id = String(value);
        this.ownerDocument._register(this);
    }

    get className() {
        return Array.from(this._classes).join(" ");
    }

    set className(value) {
        this._classes = new Set(
            String(value).split(/\s+/).filter(Boolean)
        );
    }


    /* ------------------------------------------------------
       TEXT
       ------------------------------------------------------
       Aggregate, exactly like the real property. Setting it
       drops existing children, which is what makes it the
       safe alternative to innerHTML.
       ------------------------------------------------------ */

    get textContent() {
        if (!this.childNodes.length) {
            return this._text;
        }
        return (
            this._text +
            this.childNodes
                .map(function (child) {
                    return child.textContent;
                })
                .join("")
        );
    }

    set textContent(value) {
        this.childNodes.forEach(function (child) {
            child.parentNode = null;
        });
        this.childNodes = [];
        this._text = value === null || value === undefined
            ? ""
            : String(value);
    }

    /* innerHTML exists only so a test can prove nothing
       assigns to it. Any write is an immediate failure. */
    set innerHTML(value) {
        throw new Error(
            "dom_stub: innerHTML was assigned. Phase 8 " +
            "rendering must build nodes and use textContent."
        );
    }

    get innerHTML() {
        return this.textContent;
    }


    /* ------------------------------------------------------
       ATTRIBUTES
       ------------------------------------------------------ */

    setAttribute(name, value) {
        this._attributes[name] = String(value);
        if (name === "id") {
            this.ownerDocument._register(this);
        }
        if (name.indexOf("data-") === 0) {
            this.dataset[dashToCamel(name.slice(5))] = String(value);
        }
    }

    getAttribute(name) {
        return Object.prototype.hasOwnProperty.call(this._attributes, name)
            ? this._attributes[name]
            : null;
    }

    hasAttribute(name) {
        return Object.prototype.hasOwnProperty.call(this._attributes, name);
    }

    removeAttribute(name) {
        delete this._attributes[name];

        /* A real <img> drops its resolved source when the
           attribute goes, so mirror that or the stub would
           report a stale preview. */
        if (name === "src") {
            this.src = null;
        }
        if (name.indexOf("data-") === 0) {
            delete this.dataset[dashToCamel(name.slice(5))];
        }
    }


    /* ------------------------------------------------------
       TREE
       ------------------------------------------------------ */

    appendChild(child) {
        if (!child) {
            throw new Error("dom_stub: appendChild(null)");
        }
        if (child.parentNode) {
            child.parentNode.removeChild(child);
        }
        child.parentNode = this;
        this.childNodes.push(child);
        return child;
    }

    insertBefore(child, reference) {
        if (!reference) {
            return this.appendChild(child);
        }
        const index = this.childNodes.indexOf(reference);
        if (index === -1) {
            return this.appendChild(child);
        }
        if (child.parentNode) {
            child.parentNode.removeChild(child);
        }
        child.parentNode = this;
        this.childNodes.splice(index, 0, child);
        return child;
    }

    removeChild(child) {
        const index = this.childNodes.indexOf(child);
        if (index !== -1) {
            this.childNodes.splice(index, 1);
            child.parentNode = null;
        }
        return child;
    }

    remove() {
        if (this.parentNode) {
            this.parentNode.removeChild(this);
        }
    }

    get firstChild() {
        return this.childNodes.length ? this.childNodes[0] : null;
    }

    get lastChild() {
        return this.childNodes.length
            ? this.childNodes[this.childNodes.length - 1]
            : null;
    }

    get children() {
        return this.childNodes.filter(function (node) {
            return node.nodeType === 1;
        });
    }

    get childElementCount() {
        return this.children.length;
    }

    /* Depth-first, document order. */
    _descendants() {
        const out = [];
        this.childNodes.forEach(function (child) {
            if (child.nodeType !== 1) {
                return;
            }
            out.push(child);
            child._descendants().forEach(function (node) {
                out.push(node);
            });
        });
        return out;
    }


    /* ------------------------------------------------------
       QUERIES
       ------------------------------------------------------ */

    querySelectorAll(selector) {
        const chains = parseSelector(selector);
        return this._descendants().filter(function (node) {
            return chains.some(function (chain) {
                return matchesChain(node, chain);
            });
        });
    }

    querySelector(selector) {
        const found = this.querySelectorAll(selector);
        return found.length ? found[0] : null;
    }

    matches(selector) {
        const node = this;
        return parseSelector(selector).some(function (chain) {
            return matchesChain(node, chain);
        });
    }

    closest(selector) {
        let current = this;
        while (current && current.nodeType === 1) {
            if (current.matches(selector)) {
                return current;
            }
            current = current.parentNode;
        }
        return null;
    }


    /* ------------------------------------------------------
       EVENTS
       ------------------------------------------------------
       Click bubbles, which is what lets a test click a real
       button inside a rendered table row.
       ------------------------------------------------------ */

    addEventListener(name, handler) {
        this._listeners[name] = this._listeners[name] || [];
        this._listeners[name].push(handler);
    }

    removeEventListener(name, handler) {
        const list = this._listeners[name] || [];
        const index = list.indexOf(handler);
        if (index !== -1) {
            list.splice(index, 1);
        }
    }

    dispatchEvent(event) {
        const type = event.type;
        let node = this;
        let stopped = false;

        event.target = event.target || this;
        event.preventDefault = event.preventDefault || function () {
            event.defaultPrevented = true;
        };
        event.stopPropagation = function () {
            stopped = true;
        };

        while (node) {
            event.currentTarget = node;
            (node._listeners[type] || []).slice().forEach(function (handler) {
                handler.call(node, event);
            });
            if (stopped || !BUBBLING_EVENTS[type]) {
                break;
            }
            node = node.parentNode;
        }

        return !event.defaultPrevented;
    }

    /* Convenience used by tests. */
    fire(type, extra) {
        const event = Object.assign({ type: type }, extra || {});
        return this.dispatchEvent(event);
    }

    /*
       A real browser focuses a button before dispatching its
       click, and code that remembers document.activeElement in
       order to restore focus later depends on that.

       Without this, a dialog opened from a button had no
       "previously focused" element to return to, and the
       harness reported a focus-restore failure that would not
       happen in a browser.
    */
    click() {
        if (FOCUSABLE_TAGS[this.tagName] && !this.disabled) {
            this.focus();
        }
        return this.fire("click", {});
    }


    /* ------------------------------------------------------
       FOCUS / DIALOG
       ------------------------------------------------------ */

    focus() {
        this.focused = true;
        this.ownerDocument.activeElement = this;
    }

    blur() {
        this.focused = false;
        if (this.ownerDocument.activeElement === this) {
            this.ownerDocument.activeElement = null;
        }
    }

    showModal() {
        if (this.tagName !== "dialog") {
            throw new Error("dom_stub: showModal on <" + this.tagName + ">");
        }
        this.open = true;
        this.ownerDocument.openDialogs.push(this);
    }

    close(returnValue) {
        this.open = false;
        this.returnValue = returnValue;
        const list = this.ownerDocument.openDialogs;
        const index = list.indexOf(this);
        if (index !== -1) {
            list.splice(index, 1);
        }
        this.fire("close", {});
    }
}


const FOCUSABLE_TAGS = {
    a: true,
    button: true,
    input: true,
    select: true,
    textarea: true,
    summary: true
};


const BUBBLING_EVENTS = {
    click: true,
    change: true,
    input: true,
    submit: true,
    keydown: true,
    keyup: true
};


function dashToCamel(value) {
    return value.replace(/-([a-z])/g, function (m, ch) {
        return ch.toUpperCase();
    });
}


/* ==========================================================
   DOCUMENT
   ========================================================== */

class StubDocument {

    constructor() {
        this.nodeType = 9;
        this.readyState = "loading";
        this.activeElement = null;
        this.openDialogs = [];
        this._byId = {};
        this._listeners = {};

        this.documentElement = new StubElement("html", this);
        this.body = new StubElement("body", this);
        this.documentElement.appendChild(this.body);
    }

    _register(element) {
        if (element.id) {
            this._byId[element.id] = element;
        }
    }

    createElement(tagName) {
        return new StubElement(tagName, this);
    }

    createTextNode(text) {
        const node = new StubElement("#text", this);
        node.nodeType = 3;
        node.textContent = text;
        return node;
    }

    getElementById(id) {
        const registered = this._byId[id];
        if (registered) {
            return registered;
        }
        const found = this.body.querySelectorAll("#" + id);
        return found.length ? found[0] : null;
    }

    querySelector(selector) {
        return this.body.querySelector(selector);
    }

    querySelectorAll(selector) {
        return this.body.querySelectorAll(selector);
    }

    addEventListener(name, handler) {
        this._listeners[name] = this._listeners[name] || [];
        this._listeners[name].push(handler);
    }

    /* Fire DOMContentLoaded, which is how every page module
       boots. */
    ready() {
        this.readyState = "complete";
        (this._listeners.DOMContentLoaded || []).slice().forEach(
            function (handler) {
                handler({ type: "DOMContentLoaded" });
            }
        );
    }
}


/* ==========================================================
   PAGE BUILDER
   ==========================================================
   Builds a real element tree from a compact description, so a
   test does not have to hand-assemble twenty nodes.

       { tag: "div", id: "x", class: "card",
         attrs: { role: "status" },
         children: [ ... ] }
   ========================================================== */

function buildTree(documentStub, spec) {
    const node = documentStub.createElement(spec.tag || "div");

    if (spec.id) {
        node.id = spec.id;
    }
    if (spec.class) {
        node.className = spec.class;
    }
    if (spec.text) {
        node.textContent = spec.text;
    }
    if (spec.hidden) {
        node.hidden = true;
    }
    if (spec.attrs) {
        Object.keys(spec.attrs).forEach(function (name) {
            node.setAttribute(name, spec.attrs[name]);
        });
    }
    (spec.children || []).forEach(function (child) {
        node.appendChild(buildTree(documentStub, child));
    });

    return node;
}


/* ==========================================================
   WINDOW
   ========================================================== */

function createWindow(options) {
    const config = options || {};
    const documentStub = new StubDocument();

    const record = {
        objectUrls: { created: [], revoked: [] },
        navigations: [],
        historyStates: [],
        timers: [],
        intervals: [],
        copied: [],
        downloads: []
    };

    const win = {
        document: documentStub,

        location: {
            pathname: config.pathname || "/",
            search: config.search || "",
            hash: "",
            origin: "http://testserver",
            get href() {
                return this.origin + this.pathname + this.search;
            },
            assign(url) {
                record.navigations.push(url);
            },
            replace(url) {
                record.navigations.push(url);
            }
        },

        history: {
            replaceState(state, title, url) {
                record.historyStates.push({ url: url, mode: "replace" });
                if (typeof url === "string") {
                    const parts = url.split("?");
                    win.location.pathname = parts[0];
                    win.location.search = parts[1] ? "?" + parts[1] : "";
                }
            },
            pushState(state, title, url) {
                record.historyStates.push({ url: url, mode: "push" });
                if (typeof url === "string") {
                    const parts = url.split("?");
                    win.location.pathname = parts[0];
                    win.location.search = parts[1] ? "?" + parts[1] : "";
                }
            }
        },

        URL: {
            createObjectURL(source) {
                const url =
                    "blob:vigilox/" + record.objectUrls.created.length;
                record.objectUrls.created.push({
                    url: url,
                    name: (source && source.name) || null
                });
                return url;
            },
            revokeObjectURL(url) {
                record.objectUrls.revoked.push(url);
            }
        },

        Blob: class Blob {
            constructor(parts, opts) {
                this.parts = parts || [];
                this.type = (opts && opts.type) || "";
                this.size = this.parts.join("").length;
            }
        },

        FormData: class FormData {
            constructor() {
                this.entries = [];
            }
            append(key, value) {
                this.entries.push([key, value]);
            }
        },

        AbortController: class AbortController {
            constructor() {
                this.signal = { aborted: false, reason: null };
            }
            abort(reason) {
                this.signal.aborted = true;
                this.signal.reason = reason || "aborted";
            }
        },

        /* Timers never fire on their own. A test advances them
           explicitly, so a debounce is observable instead of
           being a race. */
        setTimeout(fn, delay) {
            record.timers.push({ fn: fn, delay: delay, cleared: false });
            return record.timers.length;
        },
        clearTimeout(handle) {
            const entry = record.timers[handle - 1];
            if (entry) {
                entry.cleared = true;
            }
        },
        /* Recorded so a test can prove a screen does not
           poll. Never actually fires. */
        setInterval(fn, delay) {
            record.intervals.push({ delay: delay });
            return record.intervals.length;
        },
        clearInterval() {},

        requestAnimationFrame(fn) {
            fn(0);
            return 1;
        },

        confirm() {
            return config.confirm === undefined ? true : config.confirm;
        },

        navigator: {
            clipboard: {
                writeText(text) {
                    record.copied.push(text);
                    return Promise.resolve();
                }
            }
        },

        fetch() {
            return Promise.reject(
                new Error(
                    "dom_stub: fetch() was called. Page modules " +
                    "must go through the shared API client, and " +
                    "tests stub its endpoints."
                )
            );
        },

        /* Any console call from production frontend code is a
           privacy failure, because the payloads carry OCR text
           and extracted identity values. */
        console: {
            log() { throw new Error("dom_stub: console.log in frontend code"); },
            info() { throw new Error("dom_stub: console.info in frontend code"); },
            warn() { throw new Error("dom_stub: console.warn in frontend code"); },
            error() { throw new Error("dom_stub: console.error in frontend code"); },
            debug() { throw new Error("dom_stub: console.debug in frontend code"); }
        },

        _listeners: {},
        addEventListener(name, handler) {
            win._listeners[name] = win._listeners[name] || [];
            win._listeners[name].push(handler);
        },
        removeEventListener() {},

        record: record
    };

    win.window = win;
    win.globalThis = win;
    win.self = win;

    /* Advance every pending timer that is still live. */
    win.runTimers = function () {
        const pending = record.timers.slice();
        record.timers.length = 0;
        pending.forEach(function (entry) {
            if (!entry.cleared) {
                entry.fn();
            }
        });
    };

    win.fireWindowEvent = function (name, event) {
        (win._listeners[name] || []).slice().forEach(function (handler) {
            handler(event || { type: name });
        });
    };

    if (config.page) {
        documentStub.body.appendChild(
            buildTree(documentStub, config.page)
        );
    }

    return win;
}


/* ==========================================================
   SCRIPT LOADING
   ========================================================== */

function loadScript(win, relativePath) {
    const full = path.join(STATIC_ROOT, relativePath);
    const code = fs.readFileSync(full, "utf8");
    vm.runInNewContext(code, win, { filename: relativePath });
}


/* ==========================================================
   PAGE IDS
   ==========================================================
   Every id a shipped page declares. Used by tests that assert
   on the set of ids rather than on the tree.
   ========================================================== */

function idsFromPage(pageName) {
    const file = path.join(
        PROJECT_ROOT,
        "frontend",
        "pages",
        pageName
    );
    const html = fs.readFileSync(file, "utf8");
    const ids = [];
    const pattern = /id="([^"]+)"/g;
    let found;

    while ((found = pattern.exec(html)) !== null) {
        if (ids.indexOf(found[1]) === -1) {
            ids.push(found[1]);
        }
    }

    return ids;
}


/* ==========================================================
   HTML PARSER
   ==========================================================
   Builds the real element tree from a shipped page.

   WHY A PARSER RATHER THAN A LIST OF IDS
   ----------------------------------------------------------
   The first version of this stub reconstructed a page as a
   flat list of divs, one per id. That was enough for the
   Dashboard and Documents screens, which look elements up by
   id and then build their own subtrees.

   It was NOT enough for the workspace. Its tab controller
   discovers tabs with

       tablist.querySelectorAll('[role="tab"]')

   which found nothing in a flat page, because the tab buttons
   were siblings of the tablist rather than inside it, and
   carried no role attribute. Three checks failed for a reason
   that had nothing to do with the code under test.

   So the stub parses the page instead. Structure, tags,
   attributes, hidden and text all come from the shipped HTML,
   which means a renamed id, a moved element or a dropped
   role attribute breaks the test rather than being papered
   over.

   SCOPE
   ----------------------------------------------------------
   The VIGILOX pages are machine-formatted, well-formed, and
   contain no inline scripts inside <body> except the trailing
   <script src> tags. This handles exactly that: tags,
   attributes, comments, void elements and text. Anything more
   exotic is not present and is not supported.
   ========================================================== */

const VOID_ELEMENTS = {
    area: true,
    base: true,
    br: true,
    col: true,
    embed: true,
    hr: true,
    img: true,
    input: true,
    link: true,
    meta: true,
    source: true,
    track: true,
    wbr: true
};


/* Parsed once per page and reused: reading and tokenising the
   same file for every boot is pure waste. */
const parseCache = {};


function tokenizeHtml(html) {
    const tokens = [];
    let index = 0;
    const length = html.length;

    while (index < length) {
        const next = html.indexOf("<", index);

        if (next === -1) {
            tokens.push({ type: "text", value: html.slice(index) });
            break;
        }

        if (next > index) {
            tokens.push({
                type: "text",
                value: html.slice(index, next)
            });
        }

        /* Comment. */
        if (html.slice(next, next + 4) === "<!--") {
            const close = html.indexOf("-->", next + 4);
            index = close === -1 ? length : close + 3;
            continue;
        }

        /* Doctype or other declaration. */
        if (html.charAt(next + 1) === "!") {
            const close = html.indexOf(">", next);
            index = close === -1 ? length : close + 1;
            continue;
        }

        const close = html.indexOf(">", next);

        if (close === -1) {
            break;
        }

        const raw = html.slice(next + 1, close);

        if (raw.charAt(0) === "/") {
            tokens.push({
                type: "close",
                name: raw.slice(1).trim().toLowerCase()
            });
        } else {
            const selfClosing = raw.charAt(raw.length - 1) === "/";
            const body = selfClosing
                ? raw.slice(0, raw.length - 1)
                : raw;

            const match = /^([a-zA-Z][\w-]*)([\s\S]*)$/.exec(body);

            if (match) {
                tokens.push({
                    type: "open",
                    name: match[1].toLowerCase(),
                    attrs: parseAttributes(match[2] || ""),
                    selfClosing: selfClosing
                });
            }
        }

        index = close + 1;
    }

    return tokens;
}


function parseAttributes(text) {
    const attrs = {};
    const pattern =
        /([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\s*=\s*("[^"]*"|'[^']*'|[^\s"'>]+))?/g;

    let found;

    while ((found = pattern.exec(text)) !== null) {
        let value = found[2];

        if (value === undefined) {
            /* A bare attribute, like hidden or checked. */
            value = "";
        } else if (
            (value.charAt(0) === '"' && value.slice(-1) === '"') ||
            (value.charAt(0) === "'" && value.slice(-1) === "'")
        ) {
            value = value.slice(1, -1);
        }

        attrs[found[1].toLowerCase()] = value;
    }

    return attrs;
}


function decodeEntities(text) {
    return String(text)
        .replace(/&hellip;/g, "\u2026")
        .replace(/&middot;/g, "\u00b7")
        .replace(/&amp;/g, "&")
        .replace(/&lt;/g, "<")
        .replace(/&gt;/g, ">")
        .replace(/&quot;/g, '"')
        .replace(/&#39;/g, "'")
        .replace(/&nbsp;/g, " ");
}


/**
 * Build a spec tree from a page's <body>.
 *
 * Returned as plain data so it can be cached and rebuilt into
 * fresh elements for every boot.
 */
function specFromHtml(pageName) {
    if (parseCache[pageName]) {
        return parseCache[pageName];
    }

    const file = path.join(
        PROJECT_ROOT,
        "frontend",
        "pages",
        pageName
    );

    const html = fs.readFileSync(file, "utf8");

    const bodyStart = html.indexOf("<body");
    const bodyOpen = html.indexOf(">", bodyStart);
    const bodyEnd = html.lastIndexOf("</body>");

    const body =
        bodyStart === -1 || bodyEnd === -1
            ? html
            : html.slice(bodyOpen + 1, bodyEnd);

    const root = { tag: "div", attrs: {}, children: [], text: "" };
    const stack = [root];

    tokenizeHtml(body).forEach(function (token) {
        const top = stack[stack.length - 1];

        if (token.type === "text") {
            const text = decodeEntities(token.value);
            if (text.trim()) {
                top.children.push({
                    tag: "#text",
                    text: text.trim()
                });
            }
            return;
        }

        if (token.type === "open") {
            const element = {
                tag: token.name,
                attrs: token.attrs,
                children: [],
                text: ""
            };

            top.children.push(element);

            if (
                !token.selfClosing &&
                !VOID_ELEMENTS[token.name]
            ) {
                stack.push(element);
            }

            return;
        }

        /* Close. Unwind to the matching open, tolerating a
           stray close tag rather than corrupting the tree. */
        for (let i = stack.length - 1; i > 0; i -= 1) {
            if (stack[i].tag === token.name) {
                stack.length = i;
                break;
            }
        }
    });

    parseCache[pageName] = root;
    return root;
}


function buildFromSpec(documentStub, spec) {
    if (spec.tag === "#text") {
        return documentStub.createTextNode(spec.text);
    }

    const node = documentStub.createElement(spec.tag);

    Object.keys(spec.attrs || {}).forEach(function (name) {
        const value = spec.attrs[name];

        if (name === "class") {
            node.className = value;
            return;
        }

        if (name === "hidden") {
            node.hidden = true;
            return;
        }

        if (name === "checked") {
            node.checked = true;
        }

        if (name === "value") {
            node.value = value;
        }

        node.setAttribute(name, value);
    });

    (spec.children || []).forEach(function (child) {
        node.appendChild(buildFromSpec(documentStub, child));
    });

    return node;
}


/**
 * Load a shipped page into a window's document.
 *
 * Every element, attribute and text run comes from the real
 * HTML, so the harness renders into the same structure the
 * browser would.
 */
function loadPage(win, pageName) {
    const spec = specFromHtml(pageName);
    const built = buildFromSpec(win.document, spec);

    while (built.childNodes.length) {
        win.document.body.appendChild(built.childNodes[0]);
    }

    return win.document.body;
}


/* ==========================================================
   COMPUTED VISIBILITY
   ==========================================================
   Answers the only question that matters for a state machine:
   would the user see this element?

   Asserting on element.hidden proves the JavaScript ran.
   It does not prove anything about what is painted, because an
   author rule setting display defeats the user-agent
   [hidden] { display: none } no matter how weak its selector
   is. That is not a hypothetical -- it shipped, and it made
   the upload page show three mutually exclusive states at
   once while every test passed.

   So the harnesses assert on isDisplayed(). It runs the real
   shipped stylesheets, in the order the page links them, at a
   given viewport width, through the same selector matcher the
   rest of this stub uses.
   ========================================================== */

function selectorMatches(node, selector) {
    return parseSelector(selector).some(function (chain) {
        return matchesChain(node, chain);
    });
}

function createVisibility(pageName, options) {
    const engine = cssEngine.createEngine(pageName, options);

    function displayOf(node) {
        return engine.displayOf(node, selectorMatches);
    }

    /* An element is displayed when neither it nor any ancestor
       resolves to display:none. That ancestor walk is the
       whole point: hiding a container has to hide its
       children, and a test that only looked at the element
       itself would miss a panel inside a hidden section. */
    function isDisplayed(node) {
        let current = node;

        while (current && current.nodeType === 1) {
            if (current.tagName === "html") {
                return true;
            }
            if (displayOf(current).value === "none") {
                return false;
            }
            current = current.parentNode;
        }

        return true;
    }

    /* Why an element is or is not displayed, for failure
       messages. A test that says "expected hidden" and nothing
       else costs an hour; this says which rule won. */
    function explain(node) {
        let current = node;
        const chain = [];

        while (current && current.nodeType === 1) {
            const resolved = displayOf(current);
            const label =
                (current.id ? "#" + current.id : current.tagName) +
                " -> display:" + resolved.value +
                " from " + resolved.from +
                (current.hidden ? " [hidden]" : "");

            chain.push(label);

            if (resolved.value === "none") {
                break;
            }
            if (current.tagName === "html") {
                break;
            }

            current = current.parentNode;
        }

        return chain.join("\n    ");
    }

    return {
        width: engine.width,
        sheets: engine.sheets,
        ruleCount: engine.ruleCount,
        displayOf: displayOf,
        isDisplayed: isDisplayed,
        explain: explain,
        matchingRules: function (node) {
            return engine.matchingRules(node, selectorMatches);
        }
    };
}


module.exports = {
    createWindow: createWindow,
    createVisibility: createVisibility,
    selectorMatches: selectorMatches,
    loadPage: loadPage,
    specFromHtml: specFromHtml,
    loadScript: loadScript,
    buildTree: buildTree,
    idsFromPage: idsFromPage,
    parseSelector: parseSelector,
    StubElement: StubElement,
    StubDocument: StubDocument,
    PROJECT_ROOT: PROJECT_ROOT
};
