package httpapi

import (
	"net/http"

	"github.com/go-chi/chi/v5"
)

// The router, and the four ways this fleet's Go services put a handler where a
// router wants one. All four are real spellings read out of `identity`, and the
// point of putting them side by side is that a checker which resolves one of them
// resolves it for a REASON, and a checker that resolves none of them is
// indistinguishable from a checker that cannot read Go at all.
//
//	/healthz               r.Get("/healthz", handleHealthz)             a bare function
//	/readyz                r.Get("/readyz", o.handleReadyz(checks))     a method, GIVEN AN ARGUMENT
//	/livez                 r.Get("/livez", o.handleLivez)               a method, given nothing
//	/wrapped               r.Get("/wrapped", o.requireSession(o.handleWrapped))
//	                                                                    a method BEHIND A MIDDLEWARE
//	/internal/whoami       r.Get(probePrefix+"/whoami", o.handleWhoami) a path CONSTANT
//
// The first four are declared in `account_scope.yml`. The fifth is deliberately
// NOT declared, and the reason is written here rather than left to be inferred:
// core's chi recogniser requires the path expression to BEGIN with a string
// literal, so a path built from a constant is invisible to it.
//
// IT IS NOT DECLARED ANY MORE BECAUSE DECLARING IT HONESTLY WAS WRONG, AND THAT
// WAS THIS FIXTURE'S ARGUMENT AGAINST THE CHECKER. It used to say, here, that
// declaring it produces `account-scope.stale` — "registeredAt points at a line that
// does not register it", which is FALSE on that line — and that a checker which
// cries wolf on a correct declaration gets switched off. That is still true and it is
// no longer the end of it: a correct declaration behind an unevaluable prefix now
// reads `account-scope.registration-path-unreadable`, a warning, and this route is a
// `const` rather than the configuration pantry uses. Case 57 adds a route to a COPY
// of this fixture and requires the const to get the SAME answer, which is what stops
// this comment from being true in one direction and false in the other.
//
// The route is still undeclared because the floor is what it is: `minimum: 4` counts
// what the checker read, and this one is not read. The day the recogniser reads a
// constant this route becomes `undeclared`, `surface.minimum` moves, and both of those
// are correct: a route the checker can see is a route it can demand a declaration for.

const probePrefix = "/internal"

// newRouter is named rather than inlined so the declaration's `registeredAt`
// lines have something above them that is not another registration.
func newRouter(o options, checks []Check) chi.Router {
	r := chi.NewRouter()
	r.Get("/healthz", handleHealthz)
	r.Get("/readyz", o.handleReadyz(checks))
	r.Get("/livez", o.handleLivez)
	r.Get("/wrapped", o.requireSession(o.handleWrapped))
	r.Get(probePrefix+"/whoami", o.handleWhoami)
	return r
}

// Serve is here so `http` is imported for the Handler the two probe handlers
// return, which is the shape `handleReadyz` has in identity too.
func Serve(o options, checks []Check) http.Handler {
	return newRouter(o, checks)
}