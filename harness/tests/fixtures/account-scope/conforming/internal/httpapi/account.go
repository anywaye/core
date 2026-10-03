package httpapi

import "net/http"

// requireAccount resolves the caller's account from the bearer token and puts it
// on the request context. This is what every account-scoped route on the declared
// surface goes through, and it is why the line below is the one
// account_scope.yml names: delete the middleware from one route and this
// repository stops being account-scoped there, and the declaration says so
// before anything reads it.
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