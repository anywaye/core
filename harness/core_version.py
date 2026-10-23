#!/usr/bin/env python3
"""Resolve a service's declared `core:` constraint against core's own version.

    harness/core_version.py            # print what the tree resolves to
    harness/core_version.py --check . # findings, in the harness's vocabulary

WHY THIS IS A SEPARATE FILE
---------------------------
Not tidiness. `harness/anywaye_contract.py` opens by arguing that this must be a
*single* Python file with no dependencies, so a Go service's CI can run it with
nothing installed. That argument is about dependencies, and this file adds none:
it imports the standard library and `anywaye_contract`'s own `Finding`, and it
travels in the same directory, so the "one file a runner must have" property is
unchanged. What the single-file rule does buy is that a rule and its
enforcement cannot drift apart in two places — so the rule lives here, in one
place, and `anywaye_contract.py` reaches it rather than restating it.

It is separated because this packet's work is additive and the file
`anywaye_contract.py` is under active edit by another packet, and because a
resolver is the one piece of this harness a reader will want to read on its own.

IT IS NOT A SECOND DIALECT
--------------------------
`caf/internal/contract/version.go` already resolves these strings, in Go, and
`caf contract resolve` prints the answer. Every function below is a
transliteration of that file, and `harness/tests/core_version_test.sh` pins the
rows that differ. Re-deriving the semantics here would mean a service could be
told it is conforming by the Go tool and nonconforming by this one, and the
second one would be the one that blocks the build.

The two patterns are byte-identical to their Go originals, which is the
checkable form of "the same grammar":

    Go   ^(\^|~|>=)?([0-9]+)\.([0-9]+)\.([0-9]+)$     constraintPattern
    here ^(\^|~|>=)?([0-9]+)\.([0-9]+)\.([0-9]+)$     _CONSTRAINT

**One deliberate leniency, and it is the only one.** `parse_constraint` and
`parse_version` call `.strip()` on their input; the Go functions do not. The
reason is that this module's callers are file readers — `read_version` on a
`VERSION` file, which is `0.2.0\n` and nothing else — and a resolver that
rejects a trailing newline is a resolver whose callers each grow a workaround.
It cannot change an answer: `semverRange` in
`schemas/anywaye.manifest.schema.json` is anchored `^…$`, so a `core:` value
carrying stray whitespace is not a schema-valid manifest and never reaches here.
The strictness that *is* load-bearing — the refusal of a leading zero — is kept
exactly as Go has it.

The rules, in full, so there is nothing left to the reader's memory:

  * A version is `MAJOR.MINOR.PATCH`, three non-negative integers, no prefix,
    no prerelease, no build metadata, and **no leading zero in any component**.
  * A constraint is a version optionally prefixed by `^`, `~` or `>=`. No
    prefix means exactly that version.
  * `^` admits every version that does not change the left-most non-zero
    component. `^1.2.3` is `[1.2.3, 2.0.0)`; `^0.1.0` is `[0.1.0, 0.2.0)`;
    `^0.0.3` is `[0.0.3, 0.0.4)`.
  * `~` pins the minor: `[1.2.3, 1.3.0)`.
  * `>=` is an open-ended floor.
  * An exact constraint is that version and nothing else.

The caret rule for a 0.x release is the load-bearing one and is the reason
this packet exists: before 1.0 the *minor* is the breaking surface, so
`^0.1.0` does not admit `0.2.0`. A service that declares `^0.1.0` and compiles
against 0.2.0 content is compiling against something it said it would not.

WHAT "NO `core:` AT ALL" MEANS
------------------------------
Deliberately not this module's job, and the omission is on purpose. `core` is
listed in `required` by `schemas/anywaye.manifest.schema.json`, so a manifest
that validates has one; absence is `manifest.schema`'s finding, and a second
rule for the same fact would be two rules that could disagree about the same
manifest. `parlor` is the live case — its `anywaye.yml` is a `v0-draft` document
with no `core:` key and a different shape throughout — and it is already
`manifest.schema`'s to report.

`check()` is nonetheless total: handed something that is not a parseable
constraint string it reports `core.constraint-unresolvable` rather than raising.
Defense in depth costs one branch, and a crash in a gate is a worse outcome
than a finding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

#: The published version. One file, at the root, holding exactly what
#: `parse_version` accepts and nothing else.
VERSION_FILE = "VERSION"


class GrammarError(ValueError):
    """A string is not a anywaye core constraint, or not a core version.

    Named rather than reusing `ValueError` so a caller can tell "the fleet
    cannot express this" from "this harness has a bug".
    """


#: The whole constraint grammar in one line: an optional operator and three
#: dotted integers. Mirrors `constraintPattern` in `caf/internal/contract/version.go`.
_CONSTRAINT = re.compile(r"^(\^|~|>=)?([0-9]+)\.([0-9]+)\.([0-9]+)$")

#: A version is a version: the same three components with no operator.
_VERSION = re.compile(r"^([0-9]+)\.([0-9]+)\.([0-9]+)$")

#: How each operator is written in a manifest. Mirrors `Operator.prefix`.
_PREFIX = {"caret": "^", "tilde": "~", "floor": ">=", "exact": ""}

#: How each operator is read off the front of a string. Mirrors `operatorOf`.
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
    """Allow every change to the right of the left-most non-zero component.

    This is what makes `^0.1.0` mean `[0.1.0, 0.2.0)` and not `[0.1.0, 1.0.0)`:
    before 1.0 the minor *is* the breaking surface, so a caret pins it.
    """
    if version.major > 0:
        return Version(version.major + 1, 0, 0)
    if version.minor > 0:
        return Version(0, version.minor + 1, 0)
    return Version(0, 0, version.patch + 1)


def _components(*parts: str) -> tuple[int, int, int]:
    """Three integers, none of them written with a leading zero.

    `01.2.3` reads like a version to a person and is not one to a resolver: two
    spellings of the same number are two different strings, and a range that
    accepts both is a range nobody can reason about. npm refuses them for the
    same reason, and `caf`'s resolver refuses them too — which is the whole
    reason this check is not a regex, because `[0-9]+` would accept `01`.
    """
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


# --------------------------------------------------------------------------
# the rules, in the harness's vocabulary
# --------------------------------------------------------------------------

#: The findings this module can produce, in the harness's `RULE_IDS`. The
#: inventory in `harness/rules.json` and the table in `docs/contract-harness.md`
#: both carry these, and core's suite asserts all three agree.
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
        # Re-raised with the rule id attached, because the caller should not have
        # to know which of this module's failures is a refusal.
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
