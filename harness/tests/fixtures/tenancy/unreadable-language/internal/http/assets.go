// assets.go — a route handler whose scoping is enforced above the statement.
//
// This fixture exists to prove the checker's most important negative: that it
// says "I cannot see this" rather than "there is nothing here". Counting
// account-scoped routes by pattern gave 96 for gateway and 0 for darkroom, and
// the 0 was the CHECKER's syntax, not darkroom's. So a Go handler is declared
// as `operation: call`, the scanner cannot classify it, and what it prints is a
// warning naming this file and line — with an exit code of zero.
//
// The parameter is named `account_id` rather than `accountID` on purpose: this
// checker searches for the key the DECLARATION names, because the fleet has
// three vocabularies for it already and guessing which one a service uses would
// be guessing at the boundary rather than at the data. A Go service that spells
// it camelCase declares it that way and this scanner then correctly reports
// that it can find nothing.

package http

import (
	"net/http"
)

type Server struct {
	store *Store
}

// GetAsset serves one asset to the account the request authenticated as.
func (s *Server) GetAsset(w http.ResponseWriter, r *http.Request) {
	account_id := AuthFrom(r.Context()).AccountID
	row, err := s.store.FindAsset(r.PathValue("id"), account_id)
	if err != nil {
		// Absent, never forbidden: a 403 confirms the id exists, and the
		// difference between those two answers is an enumeration oracle.
		http.Error(w, `{"error":"not_found"}`, http.StatusNotFound)
		return
	}
	writeJSON(w, row)
}
