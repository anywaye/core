package httpapi

import "net/http"

func (o *API) requireAccount(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		accountID, err := o.accounts.Resolve(r.Context(), bearerToken(r))
		if err != nil {
			writeProblem(w, r, err)
			return
		}
		next(w, r.WithContext(withAccount(r.Context(), accountID)))
	}
}

func bearerToken(r *http.Request) string {
	return r.Header.Get("Authorization")
}