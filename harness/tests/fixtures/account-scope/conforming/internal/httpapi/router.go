package httpapi

import "net/http"

// Routes mounts this service's HTTP surface. It is the file
// account_scope.yml's `surface.sources` names, so it is the whole world the
// checker compares the declaration against — which is the point of the file
// being one file and not the tree.
func Routes(o *API) *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", o.handleHealthz)
	mux.HandleFunc("POST /v1/messages", o.requireAccount(o.handleSendMessage))
	mux.HandleFunc("GET /v1/messages", o.requireAccount(o.handleListMessages))
	mux.HandleFunc("GET /v1/messages/{id}", o.requireAccount(o.handleGetMessage))
	return mux
}