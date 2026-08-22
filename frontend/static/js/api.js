/* ==========================================================
   VIGILOX API CLIENT
   PHASE 8.5
   ==========================================================

   One place for every HTTP call to the VIGILOX API.

   WHY THIS EXISTS
   ----------------------------------------------------------
   The Phase 8.3 audit found 8 separate fetch() sites across
   dashboard.js and review_detail.js, each with its own error
   handling, and all of them reading the legacy top-level
   `detail` field instead of the structured error contract.

   This module centralises:

       fetch and JSON parsing
       the structured error contract
       request ID extraction
       network failure handling

   It is deliberately additive. Existing fetch sites are not
   rewritten in this subphase; new code uses this, and the
   old sites migrate as each screen is rebuilt.


   ERROR CONTRACT
   ----------------------------------------------------------
   The API returns:

       {
         "status": "error",
         "detail": "...",                  legacy
         "error": {
           "code": "DOCUMENT_NOT_FOUND",
           "message": "Document not found.",
           "request_id": "..."
         }
       }

   `error.code` and `error.message` are authoritative.
   `detail` is legacy and used only as a fallback.

   Every response also carries an X-Request-ID header. For
   errors it matches error.request_id. It is surfaced so a
   reviewer can quote it in a support request.

   The API never returns a stack trace, and this client never
   invents one.
   ========================================================== */

(function (global) {
    "use strict";

    var REQUEST_ID_HEADER = "X-Request-ID";


    /* ======================================================
       API ERROR
       ======================================================
       A single error shape for callers, whether the failure
       came from HTTP, the network, or bad JSON.
       ====================================================== */

    function ApiError(options) {
        this.name = "ApiError";
        this.status = options.status || 0;
        this.code = options.code || "UNKNOWN_ERROR";
        this.message = options.message || "The request could not be completed.";
        this.requestId = options.requestId || null;
        this.details = options.details || null;
        this.isNetworkError = options.isNetworkError === true;
    }

    ApiError.prototype = Object.create(Error.prototype);
    ApiError.prototype.constructor = ApiError;

    /* True when retrying could plausibly help. */
    ApiError.prototype.isRetryable = function () {
        return (
            this.isNetworkError ||
            this.status === 503 ||
            this.status === 504 ||
            this.status === 429
        );
    };

    /* True when the reviewer lacks permission rather than the
       request being malformed. */
    ApiError.prototype.isAuthError = function () {
        return this.status === 401 || this.status === 403;
    };


    /* ======================================================
       ERROR EXTRACTION
       ======================================================
       Prefer the structured contract. Fall back to legacy
       `detail`, then to an HTTP-status-derived message.
       ====================================================== */

    function messageForStatus(status) {
        var map = {
            400: "The request was invalid.",
            401: "Authentication is required.",
            403: "You are not authorized to perform this action.",
            404: "The requested resource was not found.",
            409: "This conflicts with the current state of the document.",
            413: "The file is too large.",
            415: "That file type is not supported.",
            422: "Some of the submitted values are invalid.",
            500: "An internal server error occurred.",
            503: "The service is temporarily unavailable."
        };
        return map[status] || "The request could not be completed.";
    }

    function buildApiError(status, body, requestId) {
        var structured = body && body.error ? body.error : null;

        if (structured) {
            return new ApiError({
                status: status,
                code: structured.code || "UNKNOWN_ERROR",
                message: structured.message || messageForStatus(status),
                /* error.request_id must agree with the header;
                   the header is preferred because it is present
                   even when the body is not JSON. */
                requestId: requestId || structured.request_id || null,
                details: structured.details || null
            });
        }

        /* Legacy compatibility. `detail` may be a string, or a
           FastAPI validation array. */
        var legacy = body ? body.detail : null;
        var legacyMessage = null;

        if (typeof legacy === "string" && legacy) {
            legacyMessage = legacy;
        } else if (Array.isArray(legacy) && legacy.length) {
            legacyMessage = "Some of the submitted values are invalid.";
        }

        return new ApiError({
            status: status,
            code: "HTTP_" + status,
            message: legacyMessage || messageForStatus(status),
            requestId: requestId
        });
    }


    /* ======================================================
       CORE REQUEST
       ====================================================== */

    function request(path, options) {
        var config = options || {};

        var init = {
            method: config.method || "GET",
            headers: {},
            /* Same-origin only. The API is served by the same
               FastAPI app, so credentials never cross an
               origin boundary. */
            credentials: "same-origin"
        };

        if (config.headers) {
            Object.keys(config.headers).forEach(function (key) {
                init.headers[key] = config.headers[key];
            });
        }

        /* JSON body. FormData is passed through untouched so
           the browser can set its own multipart boundary. */
        if (config.body !== undefined && config.body !== null) {
            if (global.FormData && config.body instanceof global.FormData) {
                init.body = config.body;
            } else {
                init.headers["Content-Type"] = "application/json";
                init.body = JSON.stringify(config.body);
            }
        }

        if (config.signal) {
            init.signal = config.signal;
        }

        return global.fetch(path, init).then(
            function (response) {
                var requestId = response.headers.get(REQUEST_ID_HEADER);

                if (config.raw === true) {
                    if (!response.ok) {
                        return response.json().catch(function () {
                            return null;
                        }).then(function (body) {
                            throw buildApiError(response.status, body, requestId);
                        });
                    }
                    return { response: response, requestId: requestId };
                }

                if (response.status === 204) {
                    return { data: null, requestId: requestId };
                }

                return response.json().catch(function () {
                    /* A non-JSON body on an error is still an
                       error; on success it is a contract break. */
                    if (!response.ok) {
                        throw buildApiError(response.status, null, requestId);
                    }
                    throw new ApiError({
                        status: response.status,
                        code: "INVALID_RESPONSE",
                        message: "The server returned an unreadable response.",
                        requestId: requestId
                    });
                }).then(function (body) {
                    if (!response.ok) {
                        throw buildApiError(response.status, body, requestId);
                    }
                    return { data: body, requestId: requestId };
                });
            },
            function (networkError) {
                if (networkError && networkError.name === "AbortError") {
                    throw new ApiError({
                        status: 0,
                        code: "REQUEST_ABORTED",
                        message: "The request was cancelled.",
                        isNetworkError: false
                    });
                }
                throw new ApiError({
                    status: 0,
                    code: "NETWORK_ERROR",
                    message:
                        "Could not reach the VIGILOX API. " +
                        "Check your connection and try again.",
                    isNetworkError: true
                });
            }
        );
    }

    function getJson(path, options) {
        return request(path, options).then(function (result) {
            return result.data;
        });
    }


    /* ======================================================
       IN-FLIGHT DEDUPLICATION
       ======================================================
       The audit found the same endpoints being fetched more
       than once per page load. Concurrent GETs for the same
       path share one network request.
       ====================================================== */

    var inFlight = {};

    function getJsonShared(path) {
        if (Object.prototype.hasOwnProperty.call(inFlight, path)) {
            return inFlight[path];
        }

        var pending = getJson(path).then(
            function (data) {
                delete inFlight[path];
                return data;
            },
            function (error) {
                delete inFlight[path];
                throw error;
            }
        );

        inFlight[path] = pending;
        return pending;
    }


    /* ======================================================
       ENDPOINTS
       ======================================================
       Named methods, so no caller hand-builds a URL and no
       document id is concatenated unescaped.
       ====================================================== */

    function documentPath(documentId, suffix) {
        return (
            "/api/v1/documents/" +
            encodeURIComponent(documentId) +
            (suffix || "")
        );
    }

    var endpoints = {

        /* Reviewer identity is resolved server-side. The
           client sends nothing and cannot influence it. */
        getReviewerIdentity: function () {
            return getJsonShared("/api/v1/reviewer/me");
        },

        getHealth: function () {
            return getJson("/health");
        },

        getReadiness: function () {
            return getJson("/health/ready");
        },

        /* Dashboard aggregation is SQL. One request returns
           every count on the screen, so the dashboard never
           issues one request per metric. */
        getDashboardSummary: function () {
            return getJsonShared("/api/v1/dashboard/summary");
        },

        /* Documents list.

           Only keys the caller actually set are appended, so
           the server applies its own defaults for the rest
           and the URL stays readable. Values are encoded, so
           a search term can contain & or = safely.

           page_size is NOT clamped here. The backend rejects
           an oversized page_size with PAGE_SIZE_TOO_LARGE
           rather than silently returning fewer rows, and
           hiding that behind a client clamp would mask a real
           contract break. */
        getDocuments: function (params, options) {
            var p = params || {};
            var query = [];

            function add(key, value) {
                if (
                    value === null ||
                    value === undefined ||
                    value === ""
                ) {
                    return;
                }
                query.push(
                    key + "=" + encodeURIComponent(value)
                );
            }

            add("page", p.page);
            add("page_size", p.pageSize);
            add("document_type", p.documentType);
            add("final_state", p.finalState);
            add("machine_decision", p.machineDecision);
            add("expiry_status", p.expiryStatus);
            add("search", p.search);
            add("sort", p.sort);
            add("direction", p.direction);

            return getJson(
                "/api/v1/documents" +
                (query.length ? "?" + query.join("&") : ""),
                {
                    signal: options ? options.signal : undefined
                }
            );
        },

        getReviewQueue: function (filters) {
            var query = [];
            var f = filters || {};

            if (f.priority) {
                query.push("priority=" + encodeURIComponent(f.priority));
            }
            if (f.documentType) {
                query.push(
                    "document_type=" + encodeURIComponent(f.documentType)
                );
            }

            return getJson(
                "/api/v1/reviews/queue" +
                (query.length ? "?" + query.join("&") : "")
            );
        },

        getDocument: function (documentId) {
            return getJson(documentPath(documentId));
        },

        getDocumentHistory: function (documentId) {
            return getJson(documentPath(documentId, "/history"));
        },

        documentImageUrl: function (documentId) {
            return documentPath(documentId, "/image");
        },

        /* The request body deliberately carries no reviewer
           id. The backend resolves the reviewer itself and
           ignores any client-supplied value. */
        submitReview: function (documentId, payload) {
            return getJson(documentPath(documentId, "/reviews"), {
                method: "POST",
                body: payload
            });
        },

        /* ==================================================
           SYNCHRONOUS ANALYZE
           ==================================================
           Kept, unchanged, and no longer used by the Upload
           page. It blocks for the whole pipeline -- an
           eighteen second median on measured documents -- so
           the product uses the job endpoints below instead.

           It is still the right call for a script that wants
           one answer from one request, and nothing about it
           is deprecated.
           ================================================== */

        analyzeDocument: function (file, options) {
            var form = new global.FormData();
            form.append("file", file);

            return getJson("/api/v1/documents/analyze", {
                method: "POST",
                body: form,
                signal: options ? options.signal : undefined
            });
        },


        /* ==================================================
           ASYNC DOCUMENT JOBS
           ==================================================
           Submit returns 202 with a job id. Status is polled
           until the job reports is_terminal.

           Deliberately NOT routed through getJsonShared:
           that deduplicates concurrent GETs for the same
           path, which is right for a dashboard summary and
           wrong here. Two polls of the same job a second
           apart must be two requests, or the second one
           returns the first one's stale answer and the page
           stops updating.
           ================================================== */

        createDocumentJob: function (file, options) {
            var form = new global.FormData();
            form.append("file", file);

            /* PHASE 10.3. Only sent when explicitly asked
               for, so the default request is unchanged and a
               caller cannot reprocess by accident. */
            if (options && options.reprocess === true) {
                form.append("reprocess", "true");
            }

            return getJson("/api/v1/document-jobs", {
                method: "POST",
                body: form,
                signal: options ? options.signal : undefined
            });
        },

        getDocumentJob: function (jobId, options) {
            return getJson(
                "/api/v1/document-jobs/" +
                    global.encodeURIComponent(jobId),
                {
                    signal: options ? options.signal : undefined
                }
            );
        },

        /* Every file goes in one multipart request under the
           same field name, which is what the endpoint's
           list[UploadFile] expects. */
        createDocumentBatch: function (files, options) {
            var form = new global.FormData();
            var index = 0;

            for (index = 0; index < files.length; index += 1) {
                form.append("files", files[index]);
            }

            /* PHASE 10.3. Same conservative default. */
            if (options && options.reprocess === true) {
                form.append("reprocess", "true");
            }

            return getJson("/api/v1/document-batches", {
                method: "POST",
                body: form,
                signal: options ? options.signal : undefined
            });
        },

        getDocumentBatch: function (batchId, options) {
            return getJson(
                "/api/v1/document-batches/" +
                    global.encodeURIComponent(batchId),
                {
                    signal: options ? options.signal : undefined
                }
            );
        }
    };


    global.VigiloxApi = {
        ApiError: ApiError,
        request: request,
        getJson: getJson,
        getJsonShared: getJsonShared,
        buildApiError: buildApiError,
        messageForStatus: messageForStatus,
        REQUEST_ID_HEADER: REQUEST_ID_HEADER,
        endpoints: endpoints
    };

}(window));
