package httpapi

import "net/http"

// The handlers `router.go` mounts, and the three things this fixture exists to
// pin about how a checker resolves them.
//
// `account-scope.contradiction-unreadable` fires on a row declared
// `accountScoped: false` whose handler the checker cannot resolve to a file. Every
// row in the declaration above is `false`, so before these functions existed the
// fixture answered "I could not verify any of my own routes" — which is the
// finding working and is also the wrong shape for a control fixture. The three
// definitions below are the three spellings that have to work:
//
//   1. handleHealthz     `func handleHealthz(…)`            BARE — no receiver at all
//   2. handleReadyz      `func (o options) handleReadyz(…)`  A METHOD — receiver first
//   3. handleLivez       `func (o options) handleLivez(…)`   A METHOD, registered bare
//
// (2) is the one whose DEFINITION has a receiver sitting between the `func` and the
// name, and (1) is the one whose NAME at the registration has no receiver — so it
// is a bare symbol, and a bare symbol is the shape a definition search has to be
// willing to start from.
//
// None of these resolves an account, and none of them so much as SAYS the word.
// That is not incidental: a row declared `false` is only checkable if the handler's
// own code can be read and read as clean, so the fixture has to be a handler the
// checker can genuinely open. `harness/tests/account_scope_self_test.sh` asserts
// both halves — that these three resolve, and that a copy of the checker with the
// resolution deleted can still name them — so "they resolve no account" is a fact
// about this file rather than a hope.

// Check is one probe this process was configured with. It is here so
// `handleReadyz`'s parameter names something that exists, which is what makes the
// fixture honest about the shape it is reproducing.
type Check struct {
	Name string
}

// options is identity's own spelling — a value receiver, not a pointer — so the
// method definitions below read exactly as the ones that were measured.
type options struct{}

// handleHealthz is (1): a bare package function. The registration names it with
// no receiver at all, so the symbol the checker reads off the line is
// `handleHealthz` and not `o.handleHealthz` — and a definition search that only
// runs for a DOTTED symbol never looks for it.
func handleHealthz(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte(`{"status":"ok"}`))
}

// handleReadyz is (2): a method whose definition puts the receiver between the
// `func` and the name. It is registered with an ARGUMENT, which is the other half
// of what has to be read correctly: the line ends `o.handleReadyz(checks))`, so a
// checker that takes the last symbol on the line reads `checks` — a parameter of a
// parameter — and goes looking for a definition of it. `checks` appears in
// `New(checks []Check, …)` in identity as a PARAMETER, so that search would find
// a file and report a confident wrong answer rather than admitting it could not
// read the line.
func (o options) handleReadyz(checks []Check) http.HandlerFunc {
	return func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"ready":true}`))
	}
}

// handleWrapped is (4): a handler behind a MIDDLEWARE, and the reason
// `_handler_candidates` returns a LIST. This registration and the `/readyz` one are
// syntactically identical — a call of a call, with a bare identifier as the inner
// argument — and no rule about parentheses can tell them apart:
//
//	r.Get("/readyz",  o.handleReadyz(checks))   the inner identifier is a PARAMETER
//	r.Get("/wrapped", o.requireSession(o.handleWrapped))  it is the HANDLER
//
// So the line decides the ORDER and the repository decides the CHOICE: each
// candidate is resolved against this repository and the first that resolves wins.
// `checks` is not a definition and drops out; `handleWrapped` is one and is read.
// Getting this backwards is not a warning — it is a row checked against the
// MIDDLEWARE's file instead of the handler's, which is a confident answer about the
// wrong code.
func (o options) requireSession(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		next(w, r)
	}
}

func (o options) handleWrapped(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte(`{"wrapped":true}`))
}

// handleLivez is (3): the shape that already worked, kept so the other two cannot
// pass by accident. `o.handleLivez` is dotted and bare of arguments, so it resolves
// today; if a fix broke it, this is the function that would notice.
func (o options) handleLivez(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte(`{"live":true}`))
}

// handleWhoami is the handler on the path-constant registration `router.go` does
// not declare. It is defined here anyway, so that the one route this fixture
// cannot declare is a route whose handler is present — the gap is the
// RECOGNISER, not a handler that failed to be written.
func (o options) handleWhoami(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte(`{"who":"you"}`))
}