#!/usr/bin/env python3

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

MINIMUM_PYTHON = (3, 9)

EXTRA_STDLIB: frozenset[str] = frozenset()

RESERVED_KEY = "x-anywaye-reserved-properties"

EVENT_TYPE_PATTERN = re.compile(
    r"^[a-z][a-z0-9]*(-[a-z0-9]+)*\.[a-z][a-z0-9]*(_[a-z0-9]+)*\.[a-z][a-z0-9]*(_[a-z0-9]+)*$"
)

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




FIXTURE_PATH_PARTS = ("tests", "fixtures")


def _is_fixture(path: Path, root: Path) -> bool:
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
    try:
        document = read_yaml(path.read_text(encoding="utf-8"), path)
    except Refusal as exc:
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
        stem = relative[: -len(".schema.json")]
        if stem.endswith(".schema"):
            stem = stem[: -len(".schema")]
        event_type = ".".join(stem.split("/"))
        found[event_type] = (schema_path, names)
        found[relative] = (schema_path, names)
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

    if not tombstones:
        return Report(root=root, findings=findings)

    contracts = contracts_by_surface(root)

    resolved: list[tuple[Path, str, dict, Path, set[str]]] = []
    for path, manifest, entries in tombstones:
        service = str(manifest.get("name", path.stem))
        for entry in entries:
            name = entry.get("name")
            surface = entry.get("removedFrom")
            if not isinstance(name, str) or not isinstance(surface, str):
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
                findings.append(finding(
                    "reserved.surface-missing",
                    f"{path.name} reserves {name!r} from {surface!r}, which is not a contract "
                    f"document this checker can read property names out of, so the reservation "
                    f"could not be checked in either direction",
                ))
                continue
            resolved.append((path, service, entry, contracts[surface][0], contracts[surface][1]))

    for path, service, entry, _schema_path, live in resolved:
        if entry["name"] in live:
            findings.append(finding(
                "reserved.reintroduced",
                f"{service} reserved {entry['name']!r} from {entry['removedFrom']!r} and that "
                f"contract publishes it again, so the name is reserved and live at the same "
                f"time and a consumer's generated source would rebind the old field name to "
                f"whatever now sits behind it. Declared in {path.name}",
            ))

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
    if len(parts) == 5 and parts[0] == "schemas" and parts[1] == "events" \
            and parts[4].endswith(".schema.json"):
        return parts[2]
    return None


def _cross_service_pairs(tombstones, contracts) -> list[Finding]:
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
