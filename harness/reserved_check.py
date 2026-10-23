#!/usr/bin/env python3
"""reserved_check — does a tombstoned property name stay reserved?

    reserved-check <fleet-root>            # the tombstones against the contracts
    reserved-check --explain               # every finding this checker can report
    reserved-check --json <fleet-root>     # the same findings, as JSON

WHAT THIS IS

`harness/breaking_tiers.json` publishes a rule called `reserved-no-delete`,
classified SOURCE + JSON, whose `why` reads: *"tombstoning the name is what
keeps the slot from being reused, so delete-and-tombstone is the wire-safe form
and delete-and-say-nothing is not."* Until this file existed, nothing
implemented that. The string `x-anywaye-reserved-properties` appeared once in
the fleet — in that sentence. A rule that names a mechanism that does not exist
is documentation.

The mechanism is a name reuse hazard, and it is worth stating in full because
every finding below is one clause of it:

  1. Service A publishes a property called `invoice_id`.
  2. A consumer generates source against it, and the generated struct carries
     the field name.
  3. A deletes the property, and puts the NAME on `x-anywaye-reserved-properties`.
  4. Later, an unrelated field wants the same name. Nothing in step 3's absence
     stops it, so it is published.
  5. The consumer upgrades its generated source. It compiles. It reads a
     DIFFERENT field under a name it already trusted, and nothing errors
     anywhere — not in the consumer, not in A, not in the generator.

Tombstoning the name is the whole of the defence, and it is a defence that can
be enforced in both directions, which is the part everybody gets wrong:

  * A name that is tombstoned and then LIVE again is a failure. That is the
    hazard, caught after the fact.
  * A tombstone for a name nobody ever had is ALSO a failure. It is the quieter
    half and it is the one that decays: the entry reserves a string no consumer
    ever generated against, it will block a legitimate future field with that
    name forever, and it reports nothing while it does. A checker that only
    looks for collisions cannot see it, which is why `reserved.surface-missing`
    is a finding of the same severity as the collision it guards.

WHICH IS WHY EACH ENTRY CARRIES A SURFACE. A bare list of names cannot say
whether a name was ever published, so there would be nothing to compare a stale
entry against and the stale-entry check would be unfalsifiable. Each entry names
the contract surface it was removed from, and this checker resolves that surface
in the checkout. A surface that does not resolve is a reservation with nothing
behind it, and `reserved.surface-missing` says so.

THE SAME-SERVICE ANSWER, AND WHY IT IS A FAILURE

A tombstoned name reintroduced **in the service that tombstoned it** is a
FAILURE, not a warning and not a re-reservation. See
`DECISIONS-reserved-tombstone-01.md` for the argument; the short form is that
"it depends" is not an answer a checker can use, and the two available answers
are both bad in the same direction:

  * Allow it, and the reservation means "not right now". A reservation that can
    be spent is not a reservation, and the service that spent it had to
    renegotiate with every consumer by hand — which is the invisible,
    unenforceable part of the hazard, and the reason the rule was worth writing.
  * Forbid it forever with no exit, and a service whose removal was a mistake
    cannot undo it. That is a real cost, and it is the cheapest possible path
    out: the reservation is a line in a version-controlled file, so the
    exception is a diff a reviewer can see, and the alternative is a name that
    can be reused silently.

So the rule is flat — the same verdict in the same service and across services
— and the finding message says which case it is, because "billing reintroduced
its own reserved name" and "courier publishes a name billing reserved" send a
reader to two different files. Same severity, different sentence.

WHAT THIS IS NOT

It does NOT classify diffs. `caf contract breaking` reads two revisions of an
OpenAPI document and decides whether a change is breaking; a second opinion
computed here would be two answers about one diff, which is the exact defect the
tiers exist to prevent. This checker reads DECLARATIONS — a manifest's
tombstone list and the contracts in the checkout — and says whether they agree.

EXIT CODES, THE SAME THREE EVERY CHECKER IN THIS DIRECTORY USES

    0   no finding at severity `fail`.
    1   at least one `fail`.
    2   the check could not happen. Never 0, and never collapsed into 1.

`packaging`: standard library only, on Python 3.9, and it imports exactly one
sibling — `anywaye_contract.read_yaml`, the same import `tenancy_check.py` makes
and for the same reason: a second YAML dialect in this directory would be two
answers about one manifest. No network, ever. No process is run. This checker
reads files and nothing else, which is the property `tenancy_check.py` was
required to earn and this one inherits by construction.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from anywaye_contract import Refusal, read_yaml
except ImportError as exc:  # pragma: no cover - a test asserts this cannot happen
    raise SystemExit(
        f"reserved_check: cannot import anywaye_contract from {Path(__file__).resolve().parent}: "
        f"{exc}. reserved_check.py travels with harness/anywaye_contract.py; a copy of one "
        f"without the other would mean a second YAML dialect."
    )

#: The floor. Same reasoning as `tenancy_check.py`: this reads no TOML and runs
#: no process, so it does not inherit `gate_check`'s 3.11.
MINIMUM_PYTHON = (3, 9)

#: The modules this file may import beyond the contract harness's own list.
EXTRA_STDLIB: frozenset[str] = frozenset()

#: The key on the manifest. Named once, because a checker that spells the
#: declaration in two places is a checker with two spellings to keep in step.
RESERVED_KEY = "x-anywaye-reserved-properties"

#: The two forms of `removedFrom`, and this file's own copy of what each means.
#: The schema decides what is WELL-FORMED; this decides what RESOLVES, which is
#: the half no pattern can reach. An event type resolves to the payload schema
#: core keeps at `schemas/events/<service>/<entity>/<action>.schema.json`; a
#: path resolves relative to the root it was found under.
EVENT_TYPE_PATTERN = re.compile(
    r"^[a-z][a-z0-9]*(-[a-z0-9]+)*\.[a-z][a-z0-9]*(_[a-z0-9]+)*\.[a-z][a-z0-9]*(_[a-z0-9]+)*$"
)

#: The findings this checker can report, and nothing else. Mirrored in
#: `harness/reserved_findings.json` and asserted equal in BOTH directions by
#: core's suite, for the reason `harness/rules.json` and
#: `harness/gate_findings.json` are both asserted: a finding the inventory does
#: not describe is a finding nobody was told about, and an inventory entry the
#: checker cannot reach is a promise nobody keeps.
#:
#: `severity` is fixed per id. All four are `fail`, and that is a decision worth
#: naming: a reservation that is wrong is wrong in the one direction that is
#: invisible. There is no state in which this checker has an opinion it is
#: willing to hold softly, because "softly" is how the stale entry survives.
FINDINGS: dict[str, tuple[str, str, str]] = {
    "reserved.declaration-unreadable": (
        "fail",
        "a manifest in this fleet is not a YAML document this checker can read, so its tombstones could not be checked at all.",
        "run: python3 harness/bin/reserved-check <root> --explain, and fix the file and line it names; a tombstone nobody can read reserves nothing",
    ),
    "reserved.surface-missing": (
        "fail",
        "a tombstone names a contract surface that is not in this checkout, so nothing was ever removed from it — a reservation for a name nobody ever had.",
        "point removedFrom at a surface that exists (an event type whose payload schema is in schemas/events/, or a components schema path in this repository), or delete the entry: as written it blocks a legitimate future field with that name forever and reports nothing while it does",
    ),
    "reserved.reintroduced": (
        "fail",
        "a name this service reserved is live in the very contract it was removed from.",
        "rename the new property, or delete the reservation — but note that spending a reservation is a visible diff precisely because the name is meant to be permanent; see DECISIONS-reserved-tombstone-01.md",
    ),
    "reserved.cross-service": (
        "fail",
        "a name one service reserved is published as a live property by another, so a consumer's generated source would rebind the old name to the new field.",
        "rename the property in the service that publishes it, or drop the reservation if the two services were always talking about the same thing — the finding names both services and the name so you can tell which",
    ),
}

SEVERITIES = ("ok", "warn", "fail")

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_COULD_NOT_RUN = 2


@dataclass(frozen=True)
class Finding:
    """One answer, carrying the exact command that fixes it.

    `remediate` is not decoration, and the reason is MD13's finding about
    yamine: a check that says only "not ok" makes the reader go and look, and
    the reader who does not look is the reason it is still broken next week.
    """

    id: str
    severity: str
    message: str
    remediate: str

    def render(self) -> str:
        return f"{self.severity.upper()} {self.id}: {self.message}\n    fix: {self.remediate}"


@dataclass
class Report:
    """Everything one run produced. `exit_code` is the only thing to branch on."""

    root: Path
    findings: list[Finding]

    def of(self, severity: str) -> list[Finding]:
        return [finding for finding in self.findings if finding.severity == severity]

    @property
    def exit_code(self) -> int:
        return EXIT_FAIL if self.of("fail") else EXIT_OK

    def render(self) -> str:
        lines = [finding.render() for finding in self.findings]
        failed = len(self.of("fail"))
        lines.append(
            f"{'FAIL' if failed else 'OK'} {self.root}: {failed} failure(s)"
            + (
                ""
                if failed
                else " — every tombstoned name is still reserved and every reservation points at a surface that exists"
            )
        )
        return "\n".join(lines)


def finding(identifier: str, message: str) -> Finding:
    """Build a finding from the inventory, so an unknown id cannot be invented."""
    try:
        severity, _claim, remediate = FINDINGS[identifier]
    except KeyError:  # pragma: no cover - a test asserts the inventory is complete
        raise SystemExit(
            f"reserved_check: {identifier} is not in FINDINGS. A finding the inventory does "
            f"not describe is a finding nobody was told about."
        )
    return Finding(id=identifier, severity=severity, message=message, remediate=remediate)


# --------------------------------------------------------------------------
# reading a fleet
# --------------------------------------------------------------------------


#: The fixtures of a checker are not a fleet, and the path shape that says so is
#: the `tests/fixtures` PAIR rather than the name `fixtures` alone. A service
#: with a top-level `fixtures/` directory has real manifests in it and this
#: checker must read them; core's own `harness/tests/fixtures/` holds files
#: broken ON PURPOSE to trip each checker in this directory, and reading those as
#: fleet members is how running the checker over core's own tree reported two
#: `reserved.declaration-unreadable` findings about files whose whole purpose is
#: to be unreadable. The skip is DECLARED rather than silent: it is the first
#: entry in `harness/reserved_findings.json`'s `notEnforced` list, because a
#: path a checker silently does not read is the one nobody goes looking at.
FIXTURE_PATH_PARTS = ("tests", "fixtures")


def _is_fixture(path: Path, root: Path) -> bool:
    """Whether `path` lives in a checker's own fixture tree.

    Decided on the path RELATIVE TO THE ROOT, so pointing this checker at
    `harness/tests/fixtures/reserved-properties/stale` still reads that
    directory's manifests -- which is the only way a red proof can drive it --
    while pointing it at core's root does not read core's fixtures.
    """
    parts = path.relative_to(root).parts
    return any(
        parts[index: index + 2] == FIXTURE_PATH_PARTS
        for index in range(len(parts) - 1)
    )


def manifest_paths(root: Path) -> list[Path]:
    """Every manifest under `root`, sorted, skipping directories nobody means.

    The three names are the three spellings the fleet uses for a service
    manifest, and `*.anywaye.yml` is here because core's own
    `examples/valid/*.anywaye.yml` are manifests and this checker has to be able
    to be pointed at core's examples rather than only at a fleet of services.

    A manifest inside a `tests/fixtures` tree is skipped, for the reason
    `_is_fixture` gives, and this is the whole of the skip: there is no second
    one, so the set of files this checker does not read is exactly the set
    `_is_fixture` names and nothing else grew while nobody was looking.
    """
    found: set[Path] = set()
    for pattern in ("anywaye.yml", "*.anywaye.yml"):
        found.update(
            path for path in root.rglob(pattern)
            if path.is_file() and not _is_fixture(path, root)
        )
    return sorted(found)


def _load_manifest(path: Path) -> tuple[dict | None, Finding | None]:
    """One manifest, or the finding that says it could not be read.

    A refusal is a FAILURE and not a skip, and it is the same rule the rest of
    this directory holds: a checker that could not read a declaration has not
    checked it, and reporting that as a pass converts an unknown into a green
    badge. The one thing a refusal here could be mistaken for is "this manifest
    declares no tombstones", which is exactly why it cannot be silent.
    """
    try:
        document = read_yaml(path.read_text(encoding="utf-8"), path)
    except Refusal as exc:
        # `exc.rule` and `exc.detail`, not `str(exc)`: the string form is the
        # generic refusal sentence with the detail appended in parentheses, and a
        # finding that prints it reads as a sentence about refusals in general
        # rather than as this file and this line.
        return None, finding(
            "reserved.declaration-unreadable",
            f"{path}: this manifest could not be read, so its tombstones were not checked — "
            f"{exc.rule} at {exc.path or path}"
            + (f": {exc.detail}" if exc.detail else ""),
        )
    except OSError as exc:
        return None, finding(
            "reserved.declaration-unreadable", f"{path}: {exc}, so its tombstones were not checked"
        )
    if not isinstance(document, dict):
        return None, finding(
            "reserved.declaration-unreadable",
            f"{path}: a manifest is a mapping and this one is {type(document).__name__}, "
            f"so it cannot declare anything",
        )
    return document, None


def reservations(manifest: dict) -> list[dict]:
    """The tombstone entries, or `[]`.

    The shape is the SCHEMA's business — `minItems`, `uniqueItems`,
    `additionalProperties: false` and both `pattern`s are enforced there, and a
    document that fails them never reaches a fleet check. This function assumes
    a well-formed block and reads it, so that a checker failure here is about
    the CONTRACT and not about a spelling the schema already refused.
    """
    entries = manifest.get(RESERVED_KEY) or []
    return [entry for entry in entries if isinstance(entry, dict)]


# --------------------------------------------------------------------------
# the contracts a reservation points at
# --------------------------------------------------------------------------


def surface_path(surface: str, root: Path) -> Path | None:
    """Where `removedFrom` resolves to, or `None` when it resolves to nothing.

    `None` is the answer that makes the stale half of the rule decidable, and it
    is deliberately the ONLY answer for "I could not work out where this
    points": there is no third state in which this function shrugs. A surface
    that cannot be resolved is a reservation with nothing behind it.
    """
    if EVENT_TYPE_PATTERN.match(surface):
        return root / "schemas" / "events" / Path(*surface.split(".")).with_suffix(".schema.json")
    candidate = root / surface
    return candidate if candidate.is_file() else None


def live_properties(schema_path: Path) -> set[str] | None:
    """Every property name a JSON Schema declares, or `None` if it cannot say.

    Recursive rather than top-level, because a tombstone's job is to hold a
    name wherever it was published: a property nested three objects deep is a
    name a consumer's generated struct still carries, and a checker that only
    read the top level would report the collision as absent.
    """
    try:
        document = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    names: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                names.update(name for name in properties if isinstance(name, str))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(document)
    return names


def contracts_by_surface(root: Path) -> dict[str, tuple[Path, set[str]]]:
    """Every contract document in the checkout, keyed by both surface spellings.

    Keyed twice because a reservation may name a surface either way and the
    collision check has to work whichever spelling was used: an event type maps
    to its payload schema, and a path maps to itself. Every document is read
    once, so a fleet of N services costs N reads rather than one per
    reservation.
    """
    found: dict[str, tuple[Path, set[str]]] = {}
    events = root / "schemas" / "events"
    if not events.is_dir():
        return found
    for schema_path in sorted(events.rglob("*.schema.json")):
        names = live_properties(schema_path)
        if names is None:
            continue
        relative = schema_path.relative_to(events).as_posix()
        # `created.schema.json` -> `created`, and `Path.with_suffix("")` will
        # NOT do it: that strips one suffix and leaves `created.schema`. The
        # event type is derived from the whole suffix pair, and a key that read
        # `billing.invoice.created.schema` matched no reservation at all — which
        # is the shape of a checker that reports every surface as missing and is
        # therefore read as a checker that complains.
        stem = relative[: -len(".schema.json")]
        if stem.endswith(".schema"):
            stem = stem[: -len(".schema")]
        event_type = ".".join(stem.split("/"))
        found[event_type] = (schema_path, names)
        found[relative] = (schema_path, names)
        # ...and the SAME document under a path relative to the ROOT. Both keys
        # are needed and the omission of this one was found by running the
        # checker over core's own tree rather than over a fixture: `surface_path`
        # accepts `schemas/events/<service>/…` because that path exists relative
        # to the root, and then `contracts_by_surface` had no key for it, so the
        # two findings disagreed about core's own valid example — it RESOLVED,
        # and was then reported as a reservation against a contract this checker
        # could not read. Two spellings of one surface, and each half of the
        # check only knew one of them.
        found[f"schemas/events/{relative}"] = (schema_path, names)
    return found


# --------------------------------------------------------------------------
# the checks
# --------------------------------------------------------------------------


def check(root: Path) -> Report:
    """Every disagreement between a declared tombstone and the contracts.

    Read the four findings in the order they are appended, because the order is
    the order a reader needs them in: what could not be read, then the
    reservations with nothing behind them, then the collisions — within a
    service and across the fleet.
    """
    findings: list[Finding] = []
    tombstones: list[tuple[Path, dict, list[dict]]] = []

    for path in manifest_paths(root):
        manifest, problem = _load_manifest(path)
        if problem is not None:
            findings.append(problem)
            continue
        entries = reservations(manifest)
        if entries:
            tombstones.append((path, manifest, entries))

    # No tombstones anywhere is a PASS and not a skip, and that is worth being
    # explicit about because it is the shape a vacuous rule hides in. The rule
    # is falsifiable — `harness/tests/reserved_self_test.sh` breaks one
    # reservation at a time and requires each breakage to go red — so a fleet
    # with nothing reserved is the same answer as a fleet whose reservations are
    # all still honoured, rather than the answer a checker returns when it has
    # nothing to say.
    if not tombstones:
        return Report(root=root, findings=findings)

    contracts = contracts_by_surface(root)

    # (surface, service, entry) for every reservation, resolved once. The
    # service is the manifest's own `name`, which is the routing prefix and the
    # repository name, so it is what a reader recognises.
    resolved: list[tuple[Path, str, dict, Path, set[str]]] = []
    for path, manifest, entries in tombstones:
        service = str(manifest.get("name", path.stem))
        for entry in entries:
            name = entry.get("name")
            surface = entry.get("removedFrom")
            if not isinstance(name, str) or not isinstance(surface, str):
                continue  # the schema refused the shape already
            target = surface_path(surface, root)
            if target is None or not target.is_file():
                findings.append(finding(
                    "reserved.surface-missing",
                    f"{path.name} reserves {name!r} from {surface!r}, which is not a contract "
                    f"in this checkout under either spelling (an event type with a payload schema "
                    f"at schemas/events/, or a path relative to {root}). Nothing was removed "
                    f"from a surface that does not exist, so the name is not reserved and a "
                    f"future field with it would be blocked by an entry nobody can audit",
                ))
                continue
            if surface not in contracts:
                # The surface exists but is not a document this checker indexes
                # for live names, so the collision half cannot be answered. That
                # is an unknown, and the same rule applies: reported, not passed.
                findings.append(finding(
                    "reserved.surface-missing",
                    f"{path.name} reserves {name!r} from {surface!r}, which is not a contract "
                    f"document this checker can read property names out of, so the reservation "
                    f"could not be checked in either direction",
                ))
                continue
            resolved.append((path, service, entry, contracts[surface][0], contracts[surface][1]))

    # Direction 1, within one service: the name is live in the very contract it
    # was removed from. Same severity as the cross-service case and a different
    # sentence, because the reader's next file is different.
    for path, service, entry, _schema_path, live in resolved:
        if entry["name"] in live:
            findings.append(finding(
                "reserved.reintroduced",
                f"{service} reserved {entry['name']!r} from {entry['removedFrom']!r} and that "
                f"contract publishes it again, so the name is reserved and live at the same "
                f"time and a consumer's generated source would rebind the old field name to "
                f"whatever now sits behind it. Declared in {path.name}",
            ))

    # Direction 1, across the fleet: reserved here, published there. The finding
    # names BOTH services and the name, because "billing reintroduced its own
    # reserved name" and "courier publishes a name billing reserved" send a
    # reader to two different files and only one of them is wrong.
    findings.extend(_cross_service_pairs(tombstones, contracts))

    return Report(root=root, findings=findings)


def publisher_of(surface: str) -> str | None:
    """Which service publishes a contract surface, or `None` when unknowable.

    An event type carries its publisher in its own first segment — that is what
    the three-segment grammar is FOR, and it is why this checker does not have
    to be told which manifest publishes what.

    A PATH-form surface names a file rather than a publisher, so it used to
    return `None` outright and the cross-service half silently did not fire from
    it. That gap was closable without being told anything, because core's
    payload schemas live at a fixed depth: a path under `schemas/events/` spells
    the same `<service>/<entity>/<action>.schema.json` the event type spells, so
    the publisher is the first segment and is as decidable as the event type's.
    Only a path pointing SOMEWHERE ELSE — an OpenAPI document, say — is genuinely
    unknowable, and it returns `None`, because this checker never turns an
    unknown into a claim. The consequence is recorded rather than hidden: a
    reservation against such a path is still checked against its own surface
    (`reserved.reintroduced`) and still has to resolve (`reserved.surface-missing`),
    but it cannot be reported as colliding with a different service.
    """
    if EVENT_TYPE_PATTERN.match(surface):
        return surface.split(".", 1)[0]
    parts = surface.split("/")
    # `schemas/events/<service>/<entity>/<action>.schema.json` — five components
    # is the shape core writes, and it is checked rather than assumed, so a
    # directory called `events` somewhere else cannot invent a publisher.
    if len(parts) == 5 and parts[0] == "schemas" and parts[1] == "events" \
            and parts[4].endswith(".schema.json"):
        return parts[2]
    return None


def _cross_service_pairs(tombstones, contracts) -> list[Finding]:
    """Every (reserving service, publishing service, name) triple, once each.

    Written as its own function because the nested loop over two collections is
    the one place this checker could report the same conflict twice, and a
    finding printed twice reads as two problems where there is one. The
    `reported` set is keyed by the triple rather than by the pair, so two
    surfaces colliding on one name are two findings (two different files to go
    and read) while the same surface seen through two spellings is one.

    The same-service case is NOT here. It is `reserved.reintroduced`, which
    reads the reservation's OWN surface; this one deliberately skips a publisher
    equal to the reserving service, so the two findings cannot both fire for one
    defect and send a reader looking for two problems.
    """
    findings: list[Finding] = []
    published: dict[tuple[str, str], list[str]] = {}
    for surface, (_schema_path, live) in contracts.items():
        service = publisher_of(surface)
        if service is None:
            continue
        for name in sorted(live):
            published.setdefault((service, name), []).append(surface)

    reported: set[tuple[str, str, str]] = set()
    for path, manifest, entries in tombstones:
        service = str(manifest.get("name", path.stem))
        for entry in entries:
            name, surface = entry.get("name"), entry.get("removedFrom")
            if not isinstance(name, str) or not isinstance(surface, str):
                continue  # the schema refused the shape already
            for (other_service, other_name), surfaces in published.items():
                if other_name != name or other_service == service:
                    continue
                for other_surface in surfaces:
                    key = (service, other_service, name)
                    if key in reported:
                        continue
                    reported.add(key)
                    findings.append(finding(
                        "reserved.cross-service",
                        f"{service} reserved the property name {name!r} (removed from {surface!r}, "
                        f"declared in {path.name}), and {other_service} publishes {name!r} live in "
                        f"{other_surface!r}. A consumer that generated source against {service}'s "
                        f"old {name!r} and then upgrades would bind to {other_service}'s field "
                        f"under the name it already trusted, and nothing anywhere would error",
                    ))
    return findings


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="reserved-check",
        description="Does a tombstoned property name stay reserved across a fleet?",
    )
    parser.add_argument("root", nargs="?", default=".",
                        help="the fleet root to read manifests and contracts under")
    parser.add_argument("--explain", action="store_true",
                        help="print every finding this checker can report and exit")
    parser.add_argument("--json", action="store_true", help="the findings, as JSON")
    args = parser.parse_args(argv[1:])

    if args.explain:
        width = max(len(identifier) for identifier in FINDINGS)
        for identifier, (severity, claim, remediate) in sorted(FINDINGS.items()):
            print(f"{identifier:<{width}}  {severity}  {claim}")
            print(f"{'':<{width}}        fix: {remediate}")
        return EXIT_OK

    root = Path(args.root)
    if not root.is_dir():
        print(f"reserved-check: {root} is not a directory, so the fleet could not be read.",
              file=sys.stderr)
        print("  This is not a pass: a check that could not find the fleet has not checked it.",
              file=sys.stderr)
        return EXIT_COULD_NOT_RUN

    report = check(root)
    if args.json:
        print(json.dumps({
            "root": str(root),
            "findings": [
                {"id": f.id, "severity": f.severity, "message": f.message,
                 "remediate": f.remediate}
                for f in report.findings
            ],
            "exitCode": report.exit_code,
        }, indent=2, sort_keys=True))
        return report.exit_code
    print(report.render())
    return report.exit_code


if __name__ == "__main__":
    if sys.version_info < MINIMUM_PYTHON:  # pragma: no cover - the wrapper refuses first
        print(f"reserved-check: needs Python >= "
              f"{MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]}; this is "
              f"{sys.version_info[0]}.{sys.version_info[1]}.", file=sys.stderr)
        sys.exit(EXIT_COULD_NOT_RUN)
    sys.exit(_main(sys.argv))
