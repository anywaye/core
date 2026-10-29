package httpapi

import (
	"net/http"

	"github.com/go-chi/chi/v5"
)


const probePrefix = "/internal"

func newRouter(o options, checks []Check) chi.Router {
	r := chi.NewRouter()
	r.Get("/healthz", handleHealthz)
	r.Get("/readyz", o.handleReadyz(checks))
	r.Get("/livez", o.handleLivez)
	r.Get("/wrapped", o.requireSession(o.handleWrapped))
	r.Get(probePrefix+"/whoami", o.handleWhoami)
	return r
}

func Serve(o options, checks []Check) http.Handler {
	return newRouter(o, checks)
}