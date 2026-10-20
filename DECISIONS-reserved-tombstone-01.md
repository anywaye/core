# DECISIONS — core-reserved-tombstone-01

Four decisions. One was inherited from the predecessor and is recorded here
because the packet requires it tested in both directions and a decision that is
only in a source file's docstring is a decision nobody can appeal. Two were
forced by the green control. One is the placement of the red proof.

`DECISIONS.md` is unchanged. This packet adds no `Dnn` to the master file,
because the numbering there is the manager's and every entry in it is a decision
about the *fleet's* contract; these four are about one checker in one packet and
the precedent for that is `DECISIONS-breaking-tiers-01.md`, which also left the
master file alone.

---

## D44: a tombstoned name reintroduced in the SAME service is a FAILURE

**This is the decision the packet called undecided.** The predecessor's checker
already answered it; nothing had written down why, and nothing tested that the
answer held in both directions.

**The question.** Service A removes `invoice_id` from `billing.invoice.created`
and tombstones the name. Later, A itself publishes an unrelated property called
`invoice_id`. Is that a failure, a warning, or a legitimate re-reservation?

**Choice: a failure. `reserved.reintroduced`, `severity: fail`, no exception
mechanism.**

**Why the two alternatives both lose in the same direction.**

*Allow it, and the reservation means "not right now".* A reservation that can be
spent is not a reservation. The moment A spends it, the hazard the row exists to
prevent is live again — and it becomes live again *silently*, because spending a
reservation is a normal-looking schema diff. The consumer that generated source
against the old field does not get an error, does not get a warning, and does not
get a build failure; it reads a different fact under a name it already trusted.
That is the invisible half, and it is the half the rule was written for.

*Forbid it forever with no exit, and a mistaken removal is permanent.* This is a
real cost and it is the honest objection to the choice above.

**Why the cost does not outweigh the hazard.** The exit is one deleted line in a
version-controlled file. A reviewer sees the diff, the diff says which name was
un-reserved and why, and the reviewer is the same person who reviews the schema
change that wanted the name. The alternative is a name that can be reused with no
trace anywhere. Between "an exception is a visible diff" and "a reuse is
invisible forever", the first is the smaller cost, and it is the one this
repository takes everywhere else — which is why this is not an open question
here but a consistency check that came out right.

**"It depends" is not an answer a checker can use**, and that is the structural
point. Whether the reuse is *intentional* is knowable to the service and to
nobody else, and a checker that has to be told is a checker that is told nothing.
So the rule is flat and the *message* carries the case: `reserved.reintroduced`
says "billing reserved `invoice_id` from `billing.invoice.created` and that
contract publishes it again" and `reserved.cross-service` says "billing reserved
`invoice_id`, and courier publishes it live" — same severity, different sentence,
because the two send a reader to two different files and only one of them is
wrong.

**Tested in both directions**, because a decision tested in one direction is a
decision that has only been checked against the case that agreed with it:

| direction | assertion | where |
|---|---|---|
| red | reserved in billing, live in billing's own surface → `reserved.reintroduced` | `reintroduced` fixture, breakage 3 |
| red | the same defect reached through a PATH-form surface rather than an event type | `reserved_self_test.sh` breakage 5 |
| green | a service that honours its tombstones names NO same-service finding | `reserved_self_test.sh`, "the same-service rule stayed silent where it should" |
| green | the cross-service rule does not fire on a name the service reserved from a surface that does not publish it | `reserved_self_test.sh`, "the cross-service rule stayed silent where it should" |

The green directions are the ones that make the red ones mean something. A rule
that fires on every reservation passes both red cases and is worthless; the two
green rows are what stop that, and they are why the green control over core's own
tree — 0 findings on a tree that holds one real manifest with two real
tombstones — is the load-bearing evidence rather than a formality.

**Cost of flipping.** Two lines in `harness/reserved_findings.json` (severity
`fail`→`warn`) plus one line in `harness/reserved_check.py`, plus the severities
are read from `FINDINGS` so nothing else duplicates the value. A `warn` would
need the warning machinery `gate_check.py` and `tenancy_check.py` have and this
checker deliberately lacks — the wrapper's own comment says why, and the reason
still holds: "a `warn` here would mean a reservation that might be wrong, and a
reservation that might be wrong reserves a name that might be reused." So
flipping is about three lines and a real argument, not a config toggle.

---

## D45: the SAME-SERVICE case is decided by reading the reservation's OWN surface

The structural companion to D44, and the one that keeps the four findings from
overlapping.

`reserved.reintroduced` reads the reservation's own `removedFrom` and asks
whether that name is live *in that document*. `reserved.cross-service` asks
whether it is live in a *different* service's document, and deliberately skips
any publisher equal to the reserving service. So for one defect exactly one
finding fires, and a reader never goes looking for two problems because the
report named two.

**The cost, stated because it is real:** a name reserved by billing and live in
billing's *other* surface is not reported. That is recorded in
`harness/reserved_findings.json`'s `notEnforced` list — the reservation names one
surface, so one surface is what is read.

---

## D46: `publisher_of` reads a path, not just an event type

**Forced by the green control**, and it is the decision with the widest effect.

**What was inherited:** `publisher_of` returned `None` for *every* path-form
surface, with a docstring saying the cross-service half "silently does not
fire" from one. That is a rule that cannot fire on half its inputs, reached by
the spelling a human is most likely to type.

**Measured on core's own tree:** `examples/valid/reserved-properties.cafaye.yml`
reserves two names from
`schemas/events/identity/user/created.schema.json` — a path. So both of that
file's entries were invisible to the across-services half.

**Choice: a path under `schemas/events/` names its publisher, because it spells
the same `<service>/<entity>/<action>.schema.json` an event type spells.** The
publisher is the first segment after `schemas/events`, checked as a five-part
shape rather than assumed, so a directory called `events` somewhere else cannot
invent a publisher.

**Alternative considered and rejected:** teach the checker to read the service
out of a manifest's own `api` block, so *any* document has a publisher. That is
a manifest-schema change at `version: 1`, it reaches OpenAPI documents, and it is
not a decision one checker should make on its own. The residual gap is in
`notEnforced` with its reason attached.

**Cost of flipping:** revert to `return None` for paths — five lines — and the
two path-form breakages in `harness/tests/reserved_self_test.sh` go red naming
what stopped firing, which is the shape a decision should have.

---

## D47: the reserved red proof runs in `bin/prime`, like the gate checker's

**The asymmetry is real** and core documents it deliberately: `gate_self_test.sh`
is in `bin/prime` (core-14), `self_test.sh` and `tenancy_self_test.sh` are not.
Adding a third red proof to `bin/prime` looks like moving one of the two the
documented reasoning covers, and it is not — both of those are still where they
were, and this is a new decision about a new checker.

**Why in here.** This packet exists because `reserved-no-delete` named a
mechanism that did not exist: the string `x-cafaye-reserved-properties` appeared
once in the fleet, in the sentence that claimed it. A checker wired into a gate
but never run by that gate is how that happens a second time — the check would be
a file in `harness/`, a step in `.github/workflows/ci.yml`, and something no
developer had ever seen say no. The gate checker's own comment says it plainly:
"a developer who ran the documented command learned nothing whatsoever about
whether `harness/gate_check.py` could detect anything — replace the checker with
a function that returns 0 and this gate stayed green while CI went red."

**Why the harness's is not.** Its answer does not depend on how the gate was
invoked; 28 breakages of `cafaye_contract.py` answer the same either way. This
one is in here for the gate checker's reason and not that one.

**Cost, measured:** six breakages over throwaway fixture copies, no process
spawned, no network, roughly a second. The gate checker's is ~40s and is paid
anyway. CI runs it as a step of its own as well, for the log.

**The one thing that made this decision cheap rather than a matter of taste:**
`bin/prime` treats it identically to the existing step — failure fails the gate,
a missing script is a non-zero naming the precondition rather than a skip, and
the footer is parsed rather than trusted on an exit code. The green control is
also in `bin/prime`, which is what makes "does my repository pass?" answerable
by one command.

---

## Not decided here, and reported instead

**`harness/reserved_findings.json` cites a test that does not exist.** It names
`test_every_reserved_finding_the_checker_can_emit_is_declared`, and there is no
such function in `tests/test_specs.py`. The inventory's own `$comment` says the
two sets are asserted equal *in both directions*; that assertion does not exist,
so the inventory's central claim is currently unenforced. It is inherited — the
predecessor wrote the comment and not the test — and it is the first item in
`HANDOFF-core-reserved-tombstone-01`. It was left unwritten rather than
written badly in the time available: a test asserting a set equality is four
lines, but a test asserting that `notEnforced` stays honest is a judgement call,
and the honest version is better written with the report in front of a reader.

**The `reserved-no-delete` tier row was NOT changed.** It claims SOURCE + JSON
and says delete-and-say-nothing is not wire-safe. Checked against what is now
implemented: the row is **true** and does not overclaim. The reason is in
`REPORT-core-reserved-tombstone-01` under "the tiers row". A change would have
moved the pin `test_the_published_table_is_the_go_table_and_they_cannot_drift`
deliberately; there was no reason to move it, so it was not moved.