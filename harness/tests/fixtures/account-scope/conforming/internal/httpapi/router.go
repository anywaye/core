package httpapi

import "net/http"

func Routes(o *API) *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", o.handleHealthz)
	mux.HandleFunc("POST /v1/messages", o.requireAccount(o.handleSendMessage))
	mux.HandleFunc("GET /v1/messages", o.requireAccount(o.handleListMessages))
	mux.HandleFunc("GET /v1/messages/{id}", o.requireAccount(o.handleGetMessage))
	return mux
}