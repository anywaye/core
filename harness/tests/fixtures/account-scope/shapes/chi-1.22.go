// Go 1.22 moved the method into the pattern string, so `mux.HandleFunc` and
// `r.Get` are two SYNTAXES and not one. identity has not adopted the 1.22 form;
// this shape is the conforming fixture's own router, which is what makes the
// fixture a measurement rather than an invention.
	mux.HandleFunc("GET /healthz", o.handleHealthz)
