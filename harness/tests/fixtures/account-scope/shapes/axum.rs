// axum, copied from pantry. `.route(path, get(handler))` — the method is in the
// handler position rather than in the call, which is why `verb_from_handler`
// exists, and the handler is a bare function reference rather than a wrapped
// call, which is why `carries_handler` is false.
        .route("/v1/services", get(list_services))
