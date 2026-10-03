package httpapi

import "net/http"

// The handlers this router mounts. They are here, and defined, rather than named
// and absent, for one reason that is part of the checker's contract:
//
// `account-scope.contradiction-unreadable` fires on a row declared
// `accountScoped: false` whose handler this checker cannot resolve to a file. The
// control fixture's `/healthz` is exactly such a row, and while these four
// functions did not exist the control answered `warnings: 1` — the checker
// correctly reporting that it could not verify a route it had no file for. That is
// the finding working. It is still the wrong shape for a fixture whose job is to be
// a service that declared its surface correctly, so the handlers are here.
//
// None of them names an account. The account arrives on the request from
// `requireAccount` and the handlers read what they were given, which is why the
// three account-scoped rows above are declared `true` with `accountFrom.via:
// requireAccount` and this one is honestly `false` with `reason: public`.

func (o *API) handleHealthz(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte(`{"status":"ok"}`))
}

func (o *API) handleSendMessage(w http.ResponseWriter, r *http.Request) {
	o.accepted(w, r)
}

func (o *API) handleListMessages(w http.ResponseWriter, r *http.Request) {
	o.ok(w, r, `{"data":[]}`)
}

func (o *API) handleGetMessage(w http.ResponseWriter, r *http.Request) {
	o.ok(w, r, `{"data":{"id":"msg_1"}}`)
}

func (o *API) accepted(w http.ResponseWriter, r *http.Request) {
	w.WriteHeader(http.StatusAccepted)
	_, _ = w.Write([]byte(`{"data":{"status":"accepted"}}`))
}

func (o *API) ok(w http.ResponseWriter, r *http.Request, body string) {
	w.Header().Set("Content-Type", "application/json")
	_, _ = w.Write([]byte(body))
}