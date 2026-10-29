#!/usr/bin/env python3

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

VERSION_FILE = "VERSION"


class GrammarError(ValueError):
    """A string is not a anywaye core constraint, or not a core version.

    Named rather than reusing `ValueError` so a caller can tell "the fleet
    cannot express this" from "this harness has a bug".
    """


_CONSTRAINT = re.compile(r"^(\^|~|>=)?([0-9]+)\.([0-9]+)\.([0-9]+)$")

_VERSION = re.compile(r"^([0-9]+)\.([0-9]+)\.([0-9]+)$")

_PREFIX = {"caret": "^", "tilde": "~", "floor": ">=", "exact": ""}

_OPERATOR = {"^": "caret", "~": "tilde", ">=": "floor", None: "exact"}


@dataclass(frozen=True)
class Version:
    """A core spec version: three non-negative integers and nothing else."""

    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def compare(self, other: "Version") -> int:
        """Order two versions numerically: -1, 0 or 1.

        Component by component, so 10.0.0 is newer than 9.0.0 — which a string
        comparison gets backwards, and which a resolver must not.
        """
        for mine, theirs in (
            (self.major, other.major),
            (self.minor, other.minor),
            (self.patch, other.patch),
        ):
            if mine != theirs:
                return -1 if mine < theirs else 1
        return 0


@dataclass(frozen=True)
class Constraint:
    """A parsed `core` field: an operator and the version it applies to."""

    operator: str
    version: Version

    def __str__(self) -> str:
        return f"{_PREFIX[self.operator]}{self.version}"

    @property
    def floor(self) -> Version:
        return self.version

    @property
    def open(self) -> bool:
        """Whether there is no ceiling. A floor has none; nothing else does."""
        return self.operator == "floor"

    @property
    def ceiling(self) -> Version:
        """The exclusive upper bound, for the three closed forms.

        A caller must check `open` first: the zero version is a real version, so
        an open-ended range cannot be represented by a large ceiling.
        """
        if self.operator == "exact":
            return self.version
        if self.operator == "caret":
            return _caret_ceiling(self.version)
        if self.operator == "tilde":
            return Version(self.version.major, self.version.minor + 1, 0)
        raise GrammarError("a floor has no ceiling; check `open` first")

    def bounds(self) -> tuple[Version, Version | None]:
        """The interval admitted: `(floor, None)` when open, else `(floor, ceiling)`."""
        return (self.version, None) if self.open else (self.version, self.ceiling)

    def satisfies(self, version: Version) -> bool:
        if self.operator == "exact":
            return version.compare(self.version) == 0
        floor, ceiling = self.bounds()
        if version.compare(floor) < 0:
            return False
        return ceiling is None or version.compare(ceiling) < 0

    def rationale(self, version: Version) -> str:
        """The sentence `caf contract resolve` prints after the answer.

        "no" on its own sends a person back to the grammar; saying which edge of
        the range they are on sends them to the fix.
        """
        satisfied = self.satisfies(version)
        if self.operator == "exact":
            verb = "is" if satisfied else "is not"
            return f"{version} {verb} exactly {self.version}"
        if self.operator == "floor":
            verb = "is" if satisfied else "is"
            edge = "at or above" if satisfied else "below"
            return f"{version} {verb} {edge} {self.version}"
        floor, ceiling = self.bounds()
        inside = "is in" if satisfied else "is not in"
        return f"{version} {inside} [{floor}, {ceiling})"


@dataclass(frozen=True)
class Resolution:
    """The answer to one resolve question."""

    constraint: Constraint
    version: Version
    satisfied: bool
    rationale: str


def _caret_ceiling(version: Version) -> Version:
    if version.major > 0:
        return Version(version.major + 1, 0, 0)
    if version.minor > 0:
        return Version(0, version.minor + 1, 0)
    return Version(0, 0, version.patch + 1)


def _components(*parts: str) -> tuple[int, int, int]:
    numbers = []
    for part in parts:
        if len(part) > 1 and part[0] == "0":
            raise GrammarError(
                f"{part!r} is not a number: a leading zero is a second spelling "
                f"of the same version"
            )
        numbers.append(int(part))
    return (numbers[0], numbers[1], numbers[2])


def parse_version(text: str) -> Version:
    """Read a core spec version. Raises `GrammarError` if it is not one."""
    match = _VERSION.match(text.strip())
    if match is None:
        raise GrammarError(
            f"{text!r} is not a core version: want MAJOR.MINOR.PATCH, with no "
            f"prefix, no prerelease and no leading zeros"
        )
    major, minor, patch = _components(*match.groups())
    return Version(major, minor, patch)


def parse_constraint(text: str) -> Constraint:
    """Read a `core` constraint. Raises `GrammarError` if it is not one."""
    match = _CONSTRAINT.match(text.strip())
    if match is None:
        raise GrammarError(
            f"{text!r} is not a anywaye core constraint: want MAJOR.MINOR.PATCH, "
            f"optionally prefixed by ^ (compatible), ~ (pin the minor) or >= (floor)"
        )
    major, minor, patch = _components(*match.groups()[1:])
    return Constraint(_OPERATOR[match.group(1)], Version(major, minor, patch))


def resolve(constraint: str, version: str) -> Resolution:
    """Report whether `version` satisfies `constraint`, and why.

    A pure function of its two strings: the same question has the same answer
    forever, which is what makes it usable in a CI gate and in a test.
    """
    parsed = parse_constraint(constraint)
    parsed_version = parse_version(version)
    return Resolution(
        constraint=parsed,
        version=parsed_version,
        satisfied=parsed.satisfies(parsed_version),
        rationale=parsed.rationale(parsed_version),
    )


# --------------------------------------------------------------------------
# reading core's published version
# --------------------------------------------------------------------------


class VersionAbsent(Exception):
    """Core publishes no readable version.

    A distinct exception from `GrammarError` because the two are different
    failures with different fixes: a malformed VERSION is a bug in core, and a
    missing one is core not having been released.
    """


def read_version(core_root: Path) -> str:
    """Read the version core publishes at `core_root`.

    Raises `VersionAbsent` if the file is missing, unreadable, empty, or holds
    more than one non-blank line. The last of those matters: a VERSION file
    that has been appended to is the most likely way this goes wrong, and
    reading only the first line would make it a version again.
    """
    path = Path(core_root) / VERSION_FILE
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise VersionAbsent(f"no readable {VERSION_FILE} in {core_root}: {error}") from error
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) != 1:
        raise VersionAbsent(
            f"{path} holds {len(lines)} non-blank lines, want exactly 1: a version file "
            f"that has been appended to is not a version"
        )
    return lines[0]



RULE_CONSTRAINT_UNMET = "core.constraint-unmet"
RULE_CONSTRAINT_UNRESOLVABLE = "core.constraint-unresolvable"
RULE_VERSION_ABSENT = "core.version-absent"


def check(manifest: dict, core_root: Path, finding_type, where: str = "core:"):
    """Compare a manifest's declared `core:` with the version core publishes.

    `finding_type` is `anywaye_contract.Finding`, passed in rather than imported:
    this module is imported *by* the harness, and an import back would be a
    cycle. Returns a list of findings, empty when the two agree.

    Two failure shapes, and the difference is the whole point of the rule:

      * core publishes no version — **raises `VersionAbsent`**, which the caller
        turns into a refusal and therefore exit 2. The run could not happen, and
        a version check that cannot find a version must not be green.
      * the two disagree, or one of them is not in the grammar — a **finding**,
        exit 1. The run happened and the service is wrong.

    The version is read *first* even though the constraint is the subject,
    because a missing version makes every other question unaskable. Reading the
    manifest first and reporting a stale `core:` on a core that publishes
    nothing would be reporting a defect in a service on the strength of a check
    that had not run.

    An absent or non-string `core` is reported here as unresolvable rather than
    skipped. `schemas/anywaye.manifest.schema.json` lists `core` in `required`,
    so `manifest.schema` should have reported it first; this branch exists so
    that a future loosening of that schema degrades to a clear finding instead
    of a crash.
    """
    try:
        published = read_version(core_root)
    except VersionAbsent:
        raise

    declared = manifest.get("core")
    if declared is None:
        return [
            finding_type(
                RULE_CONSTRAINT_UNRESOLVABLE,
                where,
                "no `core:` constraint is declared, so there is nothing to resolve "
                "against. `core` is in `required` in the manifest schema, so this "
                "is also a `manifest.schema` finding; it is reported here as well "
                "because a check that silently passes an undeclared constraint is "
                "worse than one that says so twice.",
            )
        ]
    if not isinstance(declared, str):
        return [
            finding_type(
                RULE_CONSTRAINT_UNRESOLVABLE,
                where,
                f"`core:` is a {type(declared).__name__}, not a constraint string.",
            )
        ]

    try:
        answer = resolve(declared, published)
    except GrammarError as error:
        return [
            finding_type(
                RULE_CONSTRAINT_UNRESOLVABLE,
                where,
                f"{error}. The manifest schema's `semverRange` pattern is "
                f"`^(\\^|~|>=)?[0-9]+\\.[0-9]+\\.[0-9]+$` and admits it, so this "
                f"manifest is schema-valid and unresolvable at the same time. The "
                f"resolver is the stricter of the two on purpose: a range that "
                f"accepts two spellings of one version is a range nobody can "
                f"reason about. `caf`'s resolver refuses it for the same reason.",
            )
        ]

    if answer.satisfied:
        return []
    return [
        finding_type(
            RULE_CONSTRAINT_UNMET,
            where,
            f"core publishes {published} and this service declares "
            f"`core: {declared}`, which {answer.rationale}. Either the service is "
            f"compiling against a core version it said it would not, or the "
            f"declaration is stale. The service that says which core it wants is "
            f"the one that is wrong here — core did not move under it, it said so "
            f"in advance and was not listened to.",
        )
    ]
