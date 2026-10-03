// The chi registration syntax, copied from identity at the commit fleet.yml records
// for it, because that line is the ONLY evidence that this checker recognises what
// identity actually writes. A recogniser whose example lived only in the pattern's
// own source would be a pattern matching the author's idea of a route.
//
// identity/internal/httpapi/accounts.go:590
	r.Get("/v1/accounts/{accountID}", o.requireAccountRole(accounts.RoleMember, o.handleGetAccount))
