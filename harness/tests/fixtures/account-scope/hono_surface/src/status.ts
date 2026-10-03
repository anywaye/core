// Two answers this gateway gives without an account in them.
//
// They are here for the declaration's sake rather than the service's: a `false`
// row is a VERDICT when the checker can read the code behind it and finds no
// account, and a GAP — `contradiction-unreadable`, a warning — when it cannot.
// An inline handler whose body is a call to something in this file resolves, so
// these two rows are decided rather than skipped. A fixture whose public routes
// resolved to nothing at all would be a control that passes for the reason the
// checker gave up, which is the failure mode cases 20 and 25 exist to rule out.

export function liveness(): { status: string } {
  return { status: "ok" };
}

export function sessionStatus(): { ok: boolean } {
  return { ok: true };
}