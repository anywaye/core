# The registration shapes `account_scope_check.py` recognises

One file per recogniser, holding **the exact line the pattern was read from**, and
nothing else. That is the whole purpose of this directory, and it exists because
of D9: a check that cannot see the defect it is written for is worse than no
check, because it reports green.

A recogniser whose example lived only in its own `example=` field would be a
pattern matching the author's idea of a route. Every line below is either copied
out of a repository this fleet runs, with the commit `fleet.yml` records for it, or
is the conforming fixture's own router, which is a measurement rather than an
invention.

`test_every_recogniser_is_fired_by_the_shape_it_was_read_from` asserts that each
`Recogniser.example` appears **verbatim** in one of these files, and that each
recogniser matches its own example and none of the others. Deleting a file here is
therefore a test failure rather than a silent reduction in what the checker can
see.

| file | framework | read from |
|---|---|---|
| `chi.go` | net/http chi | `identity/internal/httpapi/accounts.go:590` |
| `chi-1.22.go` | net/http, Go 1.22 pattern method | the conforming fixture's own router |
| `hono.ts` | Hono / Express | `guard/src/index.ts:150` |
| `phoenix.ex` | Phoenix / Plug.Router | `courier/lib/courier_web/router.ex:115` |
| `axum.rs` | axum | `pantry/src/http.rs:99` |

**These files are not read by the checker.** They are here to be compared against,
and nothing more — a `shapes/` directory inside a service's tree would be five more
routes to report as `undeclared`.

## What each shape decides

`chi.go`, `chi-1.22.go` and `hono.ts` put the handler on the registration line, so
a route that stopped calling its account middleware is readable as
`account-scope.scoping-bypassed`. `phoenix.ex` and `axum.rs` do not — Phoenix
mounts middleware in a `pipeline` block above the route and axum takes a bare
function reference — so for those two the registration line says nothing about
scoping and the check must not fire. That asymmetry is declared on
`Recogniser.carries_handler` rather than being discovered by a reader.