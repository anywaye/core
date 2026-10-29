
package http

import (
	"net/http"
)

type Server struct {
	store *Store
}

func (s *Server) GetAsset(w http.ResponseWriter, r *http.Request) {
	account_id := AuthFrom(r.Context()).AccountID
	row, err := s.store.FindAsset(r.PathValue("id"), account_id)
	if err != nil {
		http.Error(w, `{"error":"not_found"}`, http.StatusNotFound)
		return
	}
	writeJSON(w, row)
}
