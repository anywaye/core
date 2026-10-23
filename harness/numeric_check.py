#!/usr/bin/env python3
"""numeric_check.py — the contract's numeric surface, measured and checked.

  python3 harness/numeric_check.py --survey            # the measurement
  python3 harness/numeric_check.py schemas/ ...        # check documents
  python3 harness/numeric_check.py --explain           # every finding id
  python3 harness/numeric_check.py --json <paths...>   # findings as JSON

WHAT THIS IS FOR

anywaye has one contract and six languages reading it. The hazard this closes
is the class of bug that bites ONE language and not the others: a value that is
correct in the language that wrote it and silently wrong in the language that
read it. JSON.stringify in TypeScript rounds every number through an IEEE-754
binary64, so a Go service that writes 9007199254740993 produces a document
TypeScript cannot represent — Python's int and Ruby's Integer can, so nothing
fails, nothing logs, and the value is wrong. That is precisely what a contract
layer exists to prevent, and nothing in core's checker prevented it.

WHERE THE VOCABULARY LIVES, AND WHY IT IS NOT IN THE SCHEMA

A JSON Schema can say `type: integer`. It cannot ask whether a line of
TypeScript holds an int, whether a Go uint64 survived a JSON round trip, or
whether an enum is one a client may add to. So the four numeric vocabularies
live HERE, in the checker, for the same reason harness/tenancy_check.py keeps
its token vocabularies in the checker rather than in the schema — and that
duplication is a constraint the repo requires to be TESTED, which
test_the_float64_limit_is_stated_once_in_the_checker_and_agrees_with_the_doc
in tests/test_specs.py is.

THE FOUR RULES AND THEIR SEVERITY, each measured before it was written

  numeric.float64-unsafe   FINDING. An integer whose declared maximum reaches
                           the float64 exact range, an integer with no
                           maximum at all on a field whose name says it carries
                           an identity, or an integer ENUM with a member past
                           it, must be a string. Zero fields in the fleet
                           violate this today, which is why it can be a failure
                           rather than a warning: a rule that fires on every
                           existing field is a rule that gets disabled.
  numeric.float            WARNING. 3 positions, and all 3 are ratios
                           (slo.objective, slo-windows.factor). A ratio that
                           cannot be a whole number is not a rounding bug.
  numeric.unsigned         NOT ENFORCED. 45 positions, and they are counts,
                           amounts and status codes — the fleet's own
                           vocabulary. See the notEnforced ledger.
  numeric.enum             WARNING. 3 positions. The real cost of a numeric
                           enum is that codegen makes it a closed union, so
                           adding a value is a breaking change in six languages
                           at once — worth saying out loud, not worth failing
                           probes.statusCode over.

WHAT IT IS NOT

It reads documents. It does not read a line of any of the six languages, it
runs no test, and it opens no connection — for the same reason
harness/tenancy_check.py does not: harness/ may not take a dependency or reach
a database. A service's own typed client is what proves that its Go int64
became a TypeScript number; this proves that the CONTRACT did not invite it.

PYTHON 3.9, LIKE harness/tenancy_check.py: no TOML, no packages beyond PyYAML,
and no process. See harness/bin/tenancy-check for why the floor is inherited
rather than raised.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from anywaye_contract import Refusal, read_yaml
except ModuleNotFoundError as _missing:  # pragma: no cover
    raise SystemExit(
        "numeric_check: cannot import anywaye_contract from %s: %s. numeric_check "
        "travels with the harness; a copy of one without the other would mean a second "
        "YAML dialect, which is the drift core exists to prevent."
        % (Path(__file__).resolve().parent, _missing)
    )

# --------------------------------------------------------------------------
# THE VOCABULARY. Four rules, one number, and the number is a constant rather
# than a literal at each use, because the doc and this module have to agree
# about it and tests/test_specs.py asserts that they do.
# --------------------------------------------------------------------------

#: 2**53 — the largest integer a binary64 holds EXACTLY. Every integer below
#: and including this one round-trips through JSON.stringify/JSON.parse in
#: TypeScript. One more does not: 2**53 + 1 parses back as 2**53.
FLOAT64_EXACT_LIMIT = 2 ** 53  # 9007199254740992

#: The first integer float64 CANNOT represent. A document carrying this value
#: is correct in Go, Python and Ruby and is already wrong in TypeScript, by one.
FLOAT64_FIRST_UNREPRESENTABLE = FLOAT64_EXACT_LIMIT + 1  # 9007199254740993

FINDING_IDS = (
    "numeric.float64-unsafe",
    "numeric.float",
    "numeric.enum",
)

#: Rules this checker deliberately does NOT enforce, with the count measured at
#: the commit that wrote this. Same honesty as tenancy_findings.json's
#: notEnforced list: a rule examined and excluded on purpose is a decision; the
#: same rule excluded silently is the defect this harness exists to stop.
NOT_ENFORCED = {
    "numeric.unsigned": (
        "45 numeric positions across core/schemas and the seven service "
        "OpenAPI specs declare minimum: 0, and every one of them is a count, "
        "an amount in minor units, or a status code. Refusing them refuses the "
        "fleet's own vocabulary, and — the part that decides it — a rule that "
        "fires on 45 of 97 fields is a rule that is disabled within one "
        "release, which leaves the fleet with NO unsigned check rather than an "
        "incomplete one. Unsignedness is also invisible here for a structural "
        "reason: no unsigned integer type exists in JSON at all. Go has no "
        "unsigned JSON, TypeScript has no unsigned number, and Python's bool "
        "IS an int. The rule is enforceable only in a service's own types, "
        "where the successor's first move is."
    ),
}

#: Field-name tokens that mean "this integer IS an identity or a raw byte
#: count", i.e. the unbounded integers where exceeding 2**53 is reachable
#: rather than absurd. Kept in the CHECKER, not the schema, for the reason in
#: the module docstring: a JSON Schema can constrain a type and cannot know
#: what a name means. Tests assert this list and the doc agree.
IDENTITY_NAME_TOKENS = (
    "byte_size", "bytes", "iat", "exp", "nbf", "created", "last_used_at",
    "expires_at", "issued_at", "sequence", "seq", "offset", "cursor",
    "timestamp_ns", "micros", "nanoseconds",
)

_WARNING = "warning"
_FAILURE = "failure"


# --------------------------------------------------------------------------
# the walk
# --------------------------------------------------------------------------

def _load(path):
    """Read one document, or raise. Nothing is defaulted.

    JSON is read by the standard library and YAML by `anywaye_contract.read_yaml`
    — core's own reader, the one `harness/tenancy_check.py` reads declarations
    with — rather than by PyYAML. `harness/` may not take a dependency:
    `test_the_harness_imports_nothing_outside_the_standard_library` walks every
    module that travels, and a check that needs a package is a check a Go
    service's CI cannot run. One YAML dialect is also the point: a second reader
    in the same directory is the four-way drift `harness/` exists to end.
    """
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    if path.endswith(".json"):
        return json.loads(text)
    return read_yaml(text, Path(path))


def _is_int(value):
    """True for a JSON integer, and False for bool. bool IS an int in Python
    and `true` is emphatically not a number in JSON, so this is not pedantry."""
    return isinstance(value, int) and not isinstance(value, bool)


def walk(node, path, out, enums, source):
    """Collect every numeric-typed schema position and every numeric enum."""
    if isinstance(node, dict):
        declared = node.get("type")
        if isinstance(declared, str):
            kinds = [declared]
        elif isinstance(declared, list):
            kinds = [k for k in declared if isinstance(k, str)]
        else:
            kinds = []
        if "integer" in kinds or "number" in kinds:
            out.append({
                "source": source,
                "path": path,
                "types": kinds,
                "float": "number" in kinds,
                "format": node.get("format"),
                "minimum": node.get("minimum"),
                "maximum": node.get("maximum"),
                "name": path.rsplit(".", 1)[-1].split("[")[0],
                "description": (node.get("description") or "").strip(),
            })
        values = node.get("enum")
        if isinstance(values, list) and values and all(_is_int(v) for v in values):
            enums.append({
                "source": source,
                "path": path,
                "enum": values,
                "types": kinds,
                "name": path.rsplit(".", 1)[-1].split("[")[0],
                "description": (node.get("description") or "").strip(),
            })
        for key, value in node.items():
            if key in ("enum", "const", "default", "examples", "example"):
                continue
            walk(value, "%s.%s" % (path, key), out, enums, source)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            walk(value, "%s[%d]" % (path, index), out, enums, source)


def collect(paths):
    """Walk every JSON Schema and OpenAPI document in `paths`.

    A path may be a file or a directory; a directory is walked for `.json`,
    `.yaml` and `.yml`. Returns (positions, numeric_enums, unreadable)."""
    positions, enums, unreadable = [], [], []
    for root in paths:
        if os.path.isdir(root):
            files = []
            for base, dirs, names in os.walk(root):
                dirs[:] = sorted(d for d in dirs if d not in (".git", "node_modules"))
                for name in sorted(names):
                    if name.endswith((".json", ".yaml", ".yml")):
                        files.append(os.path.join(base, name))
        else:
            files = [root]
        for path in sorted(files):
            try:
                document = _load(path)
            except Refusal as refusal:
                # Core's own YAML reader refusing a construct. Its rule id and
                # its file:line are the answer, so it is quoted rather than
                # flattened into an exception name.
                unreadable.append((path, "%s at %s — %s"
                                   % (refusal.rule, refusal.path, refusal.detail)))
                continue
            except Exception as exc:  # noqa: BLE001 - reported as a warning
                unreadable.append((path, "%s: %s" % (type(exc).__name__, exc)))
                continue
            if document is None:
                continue
            walk(document, "#", positions, enums, path)
    return positions, enums, unreadable


# --------------------------------------------------------------------------
# the rules
# --------------------------------------------------------------------------

def _last_token(name):
    return name.split("_")[-1] if "_" in name else name


#: The sentence every `numeric.float64-unsafe` finding ends with, whatever shape
#: the offending declaration had — a declared maximum, or an enum member. Named
#: once because the NUMBER is already named once, and a remedy stated twice in
#: one file is one edit away from being stated twice in two different ways. The
#: rendered message is byte-identical to the one this replaced.
_FLOAT64_TAIL = (
    "A value at or past %d is exact in Go, Python and Ruby and is already wrong "
    "in TypeScript, by one. It must be a string." % FLOAT64_FIRST_UNREPRESENTABLE
)


def _unrepresentable(value):
    """Whether `value` is an integer a binary64 cannot hold EXACTLY.

    MAGNITUDE, never the signed value: -9007199254740993 is as unrepresentable
    as +9007199254740993, and every language that reads the number asks the same
    question of it. This is the test the enum branch uses, and it is a named
    function rather than an inline `abs(v) > LIMIT` because the whole argument
    for it is that a SET has no sign — a signed comparison answers "is the
    largest member too big", which is a question about a maximum, and the enum
    is not a maximum.
    """
    return abs(value) > FLOAT64_EXACT_LIMIT


def float64_unsafe(position):
    """Does this position carry an integer that float64 cannot hold exactly?

    Two ways to be unsafe, and the distinction matters:

      a DECLARED maximum at or above 2**53 — the document already says the
        value gets that big, so it is a bug today, not a possibility.

      NO maximum on a field whose NAME says it is an identity or a byte count —
        unbounded is only alarming where the ceiling is reachable. A token
        count with no maximum cannot plausibly reach 9e15, so demanding a
        string of it would be inventing work; an int64 `byte_size` or a JWT
        `exp` with no maximum can, because the only thing bounding it is
        whatever the writer felt like putting there.
    """
    maximum = position["maximum"]
    if _is_int(maximum) and maximum >= FLOAT64_EXACT_LIMIT:
        return ("declares maximum %d, at or past the float64 exact range %d"
                % (maximum, FLOAT64_EXACT_LIMIT))
    if maximum is None and position["name"] in IDENTITY_NAME_TOKENS:
        return ("is an unbounded integer named %r, and only the writer bounds it"
                % position["name"])
    return None


def enum_float64_unsafe(entry):
    """Does this enum carry a value a binary64 cannot hold exactly?

    An enum is a STRONGER statement than a `maximum`, not a weaker one, and that
    is the whole reason it belongs beside the maximum rule rather than under the
    enum warning:

      A maximum BOUNDS A RANGE. It says how big the value may get, and a writer
      that stays inside it produces nothing a reader cannot hold. The hazard is
      real but prospective, and the rule treats it as one.

      An enum ENUMERATES THE COMPLETE SET of legal values. A member past the
      float64 exact range is not a possibility the contract tolerates, it is a
      value the contract REQUIRES — and every one of those values is a value a
      JavaScript client silently rounds. There is nothing prospective about it.

    So the member itself is named in the message, because a member is a line in
    the document and a maximum is a line in the document, and the reader's next
    move is to delete the member or quote it.

    THE BOUNDARY IS `>`, NOT `>=`, and that differs from the maximum branch by
    exactly one value. 2**53 IS representable: `JSON.stringify` of it returns
    "9007199254740992" and `JSON.parse` of that returns 2**53, so an enum whose
    largest member sits ON the boundary is a document that is correct and a rule
    that refused it would be refusing a correct document. The declared-maximum
    branch fires at `>=`, which is one value conservative; it is a RANGE BOUND
    rather than a set of values, it is the published rule, and
    `harness/tests/numeric_self_test.sh` case (1) pins it. The asymmetry is
    deliberate and DECISIONS.md D44 carries the argument rather than leaving a
    reader to wonder which of the two numbers is the typo.

    Returns the reason string, or `None`. The `all(_is_int(v) ...)` guard in
    `walk()` is what keeps a string enum, an enum of floats and an enum with one
    non-integer member out of `enums` at all, and this function does NOT widen
    it: a value that is not a JSON integer is not a value `Number()` mangles.
    """
    offenders = [value for value in entry["enum"] if _unrepresentable(value)]
    if not offenders:
        return None
    worst = max(offenders, key=abs)
    # `int(float(...))` rather than the float: the point of the sentence is what
    # a JavaScript client actually READS, and printing it as a float would say
    # so badly.
    listed = ", ".join(str(value) for value in offenders)
    more = "" if len(offenders) == 1 else " (and %d more)" % (len(offenders) - 1)
    return ("enumerates %s, which a binary64 cannot hold exactly — it parses back as %d%s"
            % (listed, int(float(worst)), more))


def check(positions, enums):
    """Decide findings and warnings. Pure: takes the walk, returns the report.

    THE TWO LISTS MEET HERE, and the order of the two loops is a decision rather
    than an accident. `positions` is walked first and every node it reports is
    remembered, so the enum loop can yield on a node that already has one
    `numeric.float64-unsafe` — ONE finding per node, not two, because the two
    would be the same id about the same file with the same fix and a finding
    printed twice reads as two problems where there is one. That is
    `harness/reserved_check.py`'s `_cross_service_pairs` rule, for the same
    reason and with the same `reported` set. `numeric.enum` is NOT yielded: a
    node that is an unrepresentable value is also a closed union, and those are
    two true statements about it rather than two copies of one.
    """
    findings = []
    reported = set()
    for position in positions:
        if position["float"]:
            # A union that merely PERMITS number among six types is not a
            # float field — it is an opaque payload. Only a bare `number`, or
            # a union that is number and null, is one.
            if position["types"] == ["number"]:
                findings.append({
                    "id": "numeric.float",
                    "severity": _WARNING,
                    "source": position["source"],
                    "path": position["path"],
                    "message": (
                        "is declared `type: number`. Floats cannot be reliably "
                        "round-tripped across six languages; this one is "
                        "read exactly once in TypeScript as a binary64 and "
                        "printed back differently."
                    ),
                })
            continue
        reason = float64_unsafe(position)
        if reason is None:
            continue
        reported.add((position["source"], position["path"]))
        findings.append({
            "id": "numeric.float64-unsafe",
            "severity": _FAILURE,
            "source": position["source"],
            "path": position["path"],
            "message": "%s. %s" % (reason, _FLOAT64_TAIL),
        })
    for entry in enums:
        # Decision 2 of DECISIONS.md D44: the DECLARED MAXIMUM reports and the
        # enum yields. It is the branch that already existed, the reader's next
        # file is the same either way, and suppressing a second copy is the
        # direction in which there is nothing left to get wrong.
        if (entry["source"], entry["path"]) not in reported:
            enum_reason = enum_float64_unsafe(entry)
            if enum_reason is not None:
                findings.append({
                    "id": "numeric.float64-unsafe",
                    "severity": _FAILURE,
                    "source": entry["source"],
                    "path": entry["path"],
                    "message": "%s. %s" % (enum_reason, _FLOAT64_TAIL),
                })
        if entry["types"] and "integer" not in entry["types"]:
            continue
        findings.append({
            "id": "numeric.enum",
            "severity": _WARNING,
            "source": entry["source"],
            "path": entry["path"],
            "message": (
                "is a numeric enum %r. Codegen closes it into a union in every "
                "language at once, so adding a value is a breaking change in "
                "six of them — the reference calls numeric enums out for "
                "exactly this, and adding one is NOT a compatible change."
                % (entry["enum"],)
            ),
        })
    return findings


def explain():
    lines = ["FINDINGS AND WARNINGS numeric_check.py can report:", ""]
    lines.append("  numeric.float64-unsafe   FAILURE. An integer at or past the")
    lines.append("                           float64 exact range (%d), an" % FLOAT64_EXACT_LIMIT)
    lines.append("                           unbounded integer on a field named like")
    lines.append("                           an identity, or an integer ENUM with a")
    lines.append("                           member past the range. An enum member is")
    lines.append("                           compared by MAGNITUDE and must be strictly")
    lines.append("                           past the limit: exactly %d round-trips."
                 % FLOAT64_EXACT_LIMIT)
    lines.append("                           It must be a string.")
    lines.append("  numeric.float            WARNING. `type: number`, which cannot be")
    lines.append("                           reliably round-tripped across languages.")
    lines.append("  numeric.enum             WARNING. A numeric enum, which codegen")
    lines.append("                           turns into a closed union in all six.")
    lines.append("")
    lines.append("NOT ENFORCED, and why:")
    for rule, why in sorted(NOT_ENFORCED.items()):
        lines.append("  %s" % rule)
        for chunk in _wrap(why, 74):
            lines.append("      %s" % chunk)
    lines.append("")
    lines.append("THE NUMBER, STATED ONCE: the largest integer a binary64 holds")
    lines.append("  exactly is %d. The first it cannot is %d."
                 % (FLOAT64_EXACT_LIMIT, FLOAT64_FIRST_UNREPRESENTABLE))
    return "\n".join(lines)


def _wrap(text, width):
    words, line, out = text.split(), "", []
    for word in words:
        if line and len(line) + 1 + len(word) > width:
            out.append(line)
            line = word
        else:
            line = word if not line else line + " " + word
    if line:
        out.append(line)
    return out


# --------------------------------------------------------------------------
# the survey — the packet's FIRST deliverable, and a tool rather than a claim
# --------------------------------------------------------------------------

def survey(positions, enums):
    def bucket(position):
        if position["float"] and position["types"] == ["number"]:
            return "RULE numeric.float"
        if position["float"]:
            return "union permitting number (opaque payload)"
        reason = float64_unsafe(position)
        if reason and reason.startswith("declares"):
            return "RULE numeric.float64-unsafe (declared)"
        if reason:
            return "RULE numeric.float64-unsafe (unbounded identity)"
        if position["maximum"] is None:
            return "unbounded, bounded in practice"
        return "bounded below the float64 range"

    out = ["THE CONTRACT'S NUMERIC SURFACE, measured", ""]
    out.append("  numeric positions : %d" % len(positions))
    out.append("  numeric enums     : %d" % len(enums))
    out.append("")
    out.append("  %-52s %5s  %s" % ("bucket", "count", "the four rules, and what each one hits"))
    buckets = {}
    for position in positions:
        buckets.setdefault(bucket(position), []).append(position)
    for name in sorted(buckets):
        out.append("  %-52s %5d" % (name, len(buckets[name])))
    out.append("")
    by_source = {}
    for position in positions:
        by_source.setdefault(position["source"], []).append(position)
    out.append("  %-52s %5s  %s" % ("source", "count", "buckets"))
    for source in sorted(by_source):
        group = by_source[source]
        names = sorted({bucket(p) for p in group})
        out.append("  %-52s %5d  %s"
                   % (source, len(group), "; ".join(names) or "-"))
    out.append("")
    out.append("  every position the failure-severity rule names, in full:")
    named = [p for p in positions if float64_unsafe(p)]
    if not named:
        out.append("    (none among the POSITIONS — no field declares a maximum at")
        out.append("     or past %d, and no unbounded integer carries an identity"
                   % FLOAT64_EXACT_LIMIT)
        out.append("     name. The enums are counted separately below, because")
        out.append("     walk() files a field that is both `type: integer` and an")
        out.append("     `enum` in two lists, and only one of them is a position.)")
    for position in named:
        out.append("    %s %s" % (position["source"], position["path"]))
        out.append("        %s" % float64_unsafe(position))
    out.append("")
    out.append("  every numeric enum, in full:")
    if not enums:
        out.append("    (none)")
    for entry in enums:
        reason = enum_float64_unsafe(entry)
        out.append("    %s %s -> %r%s"
                   % (entry["source"], entry["path"], entry["enum"],
                      "" if reason is None
                      else "\n        RULE numeric.float64-unsafe: %s" % reason))
    crossing = [entry for entry in enums if enum_float64_unsafe(entry)]
    out.append("")
    out.append("  numeric enums carrying a value a binary64 cannot hold exactly: %d"
               % len(crossing))
    out.append("    (This list reports what the ENUM branch says about each node, which")
    out.append("     is not always what `check()` prints: where a field has both a")
    out.append("     maximum past the range and an enum past it, the declared maximum")
    out.append("     reports and the enum yields, so that one node carries one")
    out.append("     numeric.float64-unsafe. The bucket table above counts POSITIONS")
    out.append("     only, so an enum is visible nowhere else in this survey.)")
    out.append("")
    return "\n".join(out)


# --------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="numeric_check.py",
        description="The contract's numeric surface, measured and checked.",
    )
    parser.add_argument("paths", nargs="*",
                        help="JSON Schema files, OpenAPI documents, or directories")
    parser.add_argument("--survey", action="store_true",
                        help="print the measurement instead of checking")
    parser.add_argument("--explain", action="store_true",
                        help="every finding id this checker can report")
    parser.add_argument("--json", action="store_true",
                        help="findings as JSON on stdout")
    args = parser.parse_args(argv)

    if args.explain:
        print(explain())
        return 0

    targets = args.paths or ["schemas"]
    positions, enums, unreadable = collect(targets)

    if args.survey:
        print(survey(positions, enums))
        for path, why in unreadable:
            print("  UNREADABLE %s: %s" % (path, why))
        return 0

    findings = check(positions, enums)
    failures = [f for f in findings if f["severity"] == _FAILURE]
    warnings = [f for f in findings if f["severity"] == _WARNING]

    if args.json:
        print(json.dumps({
            "findings": findings,
            "notEnforced": NOT_ENFORCED,
            "float64ExactLimit": FLOAT64_EXACT_LIMIT,
        }, indent=2, sort_keys=True))
    else:
        for finding in findings:
            print("%-24s %-8s %s" % (finding["id"], finding["severity"],
                                      finding["source"]))
            print("    %s" % finding["path"])
            for chunk in _wrap(finding["message"], 72):
                print("      %s" % chunk)
        for path, why in unreadable:
            print("numeric.unreadable      %-8s %s" % ("warning", path))
            print("    %s — counted separately, and it never moves the verdict."
                  % why)
        # The notEnforced ledger, on every run rather than only under --explain.
        # A checker that prints nothing about what it does not prove reads as
        # covering everything, and a green over a surface it declined to rule on
        # is indistinguishable from a green over a surface it cleared. This is
        # harness/tenancy_findings.json's rule applied to a second checker: a rule
        # examined and excluded on purpose is a decision; the same rule excluded
        # silently is the defect this harness exists to stop.
        for rule in sorted(NOT_ENFORCED):
            print("")
            print("%-24s %-8s %s" % (rule, "notEnforced", "(deliberately not a finding)"))
            for chunk in _wrap(NOT_ENFORCED[rule], 72):
                print("    %s" % chunk)
        print("")
        print("numeric_check — %d failure(s), %d warning(s), over %d numeric "
              "position(s) in %d document(s)."
              % (len(failures), len(warnings), len(positions), len(targets)))

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
