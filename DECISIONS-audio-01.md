# DECISIONS — core-audio-01

**A proposal, not a decision. Nothing here has been ruled.** Two questions that
are core's to settle before any service builds the audio plane, stated with the
options, the evidence and a recommendation each. The status of both is
**awaiting a ruling from the manager**, and the rulings needed are listed at the
end under [Awaiting a ruling](#awaiting-a-ruling).

**This is a packet-scoped record and it does not touch `DECISIONS.md`.** That
follows `DECISIONS-breaking-tiers-01.md` and `DECISIONS-reserved-tombstone-01.md`,
which both left the master file alone because the numbering there is the
manager's. It also does not take a `Dnn` of its own: those two predecessors
numbered themselves D43–D45 and D44–D47, and every one of those numbers already
belongs to a different decision in [`DECISIONS.md`](DECISIONS.md) (D43–D46) — so
reusing the sequence here would put two decisions under one citation, which is
the thing `test_open_decisions_are_numbered_and_complete` exists to prevent. A
number is claimed when the ruling lands, in the same commit as the schema change
it authorises.

**Nothing in this record is enforced.** No schema, no document, no example and
no test changed with it. A question nobody has answered cannot be a rule, and a
proposal that edits the convention would hide its own existence from the reader
who comes back to check whether the question is still open.

---

## Q1: what are the capability scopes for speech and transcription?

## Q2: how is non-token usage metered and published?