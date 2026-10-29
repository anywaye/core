package httpapi

import "net/http"


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