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
//	/internal/whoami       r.Get(probePrefix+"/whoami", o.handleWhoami) a path CONSTANT
//
// The first three are declared in `account_scope.yml`. The fourth is deliberately
// NOT declared, and the reason is written here rather than left to be inferred:
// core's chi recogniser requires the path expression to BEGIN with a string
// literal, so a path built from a constant is invisible to it. Declaring it
// honestly produces `account-scope.stale` — "registeredAt points at a line that
// does not register it", which is FALSE on that line. So it is omitted, and this
// comment is where the gap lives instead of in a report nobody reads. The day the
// recogniser reads a constant this route becomes `undeclared` and `surface.minimum`
// moves, and both of those are correct: a route the checker can see is a route it
// can demand a declaration for.

const probePrefix = "/internal"

// newRouter is named rather than inlined so the declaration's `registeredAt`
// lines have something above them that is not another registration.
func newRouter(o options, checks []Check) chi.Router {
	r := chi.NewRouter()
	r.Get("/healthz", handleHealthz)
	r.Get("/readyz", o.handleReadyz(checks))
	r.Get("/livez", o.handleLivez)
	r.Get(probePrefix+"/whoami", o.handleWhoami)
	return r
}

// Serve is here so `http` is imported for the Handler the two probe handlers
// return, which is the shape `handleReadyz` has in identity too.
func Serve(o options, checks []Check) http.Handler {
	return newRouter(o, checks)
}