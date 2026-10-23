# The base for the LATENT case, and it exists because Go is not Rust.
#
# `cargo` parallelizes test functions BY DEFAULT, so a Rust suite with a shared
# database and a blanket cleanup is the full hazard. A Go suite is the opposite:
# `go test` runs a package's tests sequentially UNLESS one calls `t.Parallel()`,
# so the same shared database with the same cleanup is one opt-in away rather than
# already broken.
#
# That difference is the whole of `db-isolation.latent`, and a self-test that
# could only express the hazard would leave that finding — the one with no failing
# service in the fleet today — completely unproven. A finding nobody has ever
# seen go red is a finding nobody was told about.

module github.com/anywaye/serialservice

go 1.26