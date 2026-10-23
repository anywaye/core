#!/usr/bin/env python3
"""gate_check — does a repository's gate declaration still describe its gate?

    gate-check .                       # static: the declaration against the tree
    gate-check --prove .               # also RUNS the declared gate and checks its proofs
    gate-check --json .                # the same findings, as JSON

WHAT THIS IS

A gate that is discovered by getting it wrong is not a gate. Measured across the
fleet this was written for, there were five different spellings of "run the
gate" across fifteen repositories: `mise run prime` in nine of them,
`mise x -- ./bin/prime` in two, a task named `test` rather than `prime` in one,
`bash tests/validate.sh` in one, and — in the new repository — a task named
`gate` whose `run` string names a file that does not exist. Every one of those
was found by a human getting it wrong, which means every one of them is found
the same way again the next time.

So the gate is *declared*, in `gate.yml`, against `schemas/gate.schema.json`,
and this file checks the declaration against the repository it is in. The
checks are deliberately small and mechanical:

  * the command exists, and the file behind it exists and is executable;
  * the mise task the fleet's spelling resolves to is in `mise.toml`, and its
    `run` string still resolves to that same file;
  * the CI workflow the declaration names actually invokes the gate;
  * every external requirement names an argv you can paste, not a sentence;
  * and — the one no other check on this list can do — **running** the gate
    makes it emit every proof it promised.

THE PROOF IS THE POINT

Every other check here is string matching, and a checker that only string
matches is satisfied by a gate that exits 0 without having run anything. That
is not a hypothetical shape: it is what `exit 0` at the end of a mis-edited
script looks like, what a `--dry-run` that got left in looks like, and what a
`tests/validate.sh` that is a three-line exec of a file nobody noticed was
deleted looks like.

So a declaration carries `gate.proof`: one or more patterns that the gate's own
output must contain, with an optional `minimum` floor read from a single
capture group. A run that exits 0 without emitting a declared proof is
`gate.proof-missing`, and it is a **failure**. That is the whole difference
between this and a file that says `mise run prime`.

TWO PHASES, AND WHY

`--prove` runs the gate. The default does not, and `bin/prime` therefore calls
this checker *without* `--prove`: a gate that proves itself by running itself
proves nothing and terminates. So the static phase is the one a gate may run
about itself, the proving phase is the one CI and the red-proof self-test run,
and the split is stated in docs/gate.md rather than left to be discovered.

WHAT THIS NEVER PRINTS, AND WHY

No off-the-shelf tool detects a secret *leaked at runtime* into a log or an
error string — 0 of 268 Semgrep rules intersect CWE-532, gosec has no
`ast.CallExpr` case, Bandit is `ast.Constant`-only. So this file never prints
a command's environment, never prints a value read from one, and never prints
the gate's own output. A finding carries the command **as written** and a
remediation a reader can paste; the gate's stdout goes to a log file whose path
is reported, and reading it is the reader's decision. `tests/test_specs.py`
asserts this against a fixture whose gate prints the value of a variable from
its environment, so the property is a test and not a promise.

TRI-STATE, AND WHAT A WARNING IS NOT

Findings are `ok`, `warn` or `fail`, which is yamine's shape as MD13 recorded
it. **`warn` never moves the exit code.** A gate built on booleons forces a
choice between "fail on warnings" (noisy, gets disabled) and "ignore them" (the
report is a lie); three states are the only way out. The three warnings here are
all the same kind of thing — *this machine cannot answer that* — and a checker
that turned them into failures would be one that fails on a laptop and passes
on CI.

EXIT CODES

    0   no finding at severity `fail`. Warnings may still be printed.
    1   at least one `fail`.
    2   the check could not happen. Never 0, and never 1: a run that could not
        find the declaration has not found the gate, and converting an unknown
        into a green badge is the defect this repository exists to prevent.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:  # pragma: no cover - the version gate, asserted by the wrapper
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

try:
    from anywaye_contract import Refusal, read_yaml
except ModuleNotFoundError as _missing:  # pragma: no cover
    raise SystemExit(
        f"gate_check: cannot import anywaye_contract from {Path(__file__).resolve().parent}: "
        f"{_missing}. gate_check travels with the harness; a copy of one without the other "
        "would mean a second YAML dialect, which is the drift core exists to prevent."
    )

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_COULD_NOT_RUN = 2

#: The declaration file. One per repository, at its root.
DECLARATION = Path("gate.yml")

#: The schema the declaration is written against. This file is the *checker* and
#: it is stdlib-only, so it cannot import `jsonschema`; it re-implements the
#: handful of constraints that decide whether a declaration is well-formed, and
#: core's suite asserts that its re-implementation and the real schema reach the
#: same verdict on every example and every fixture. The duplication is asserted
#: rather than trusted, which is core's own idiom for a document and its schema
#: being the same contract written twice.
GATE_SCHEMA_RELATIVE = Path("schemas") / "gate.schema.json"

#: The shape a `ci.workflow` may take: a workflow, or — since the fleet's CI
#: moved out of GitHub Actions and into dev sandboxes — a gate script the
#: repository owns, `ci/gate.sh` by convention.
#:
#: A workflow is named by the directory it lives in: `ci/<name>.yml` where the
#: fleet keeps them now, or `.github/workflows/<name>.yml` where a repository
#: that has not moved yet keeps them.
#:
#: The script form is constrained the way the workflow form is: a path relative
#: to the repository root, with no `..` segment. A declaration that names a file
#: outside the repository would make this checker read a file it was not meant to
#: read, and a CI that ran one would run whatever the machine had there.
#:
#: The schema states the same pattern; core's suite asserts that the two agree.
CI_WORKFLOW_PATTERN = (
    r"((?:\.github/workflows|ci)/[A-Za-z0-9._-]+\.ya?ml"
    r"|(?!\.\.(?:/|$))[A-Za-z0-9._-]+(?:/(?!\.\.(?:/|$))[A-Za-z0-9._-]+)*\.sh)"
)

#: How many proofs a declaration may carry. The schema states the same number,
#: and identity is the reason it is not eight: it proves ten things, one per
#: package that carries a security boundary, and a cap that says a repository
#: may not say all of them is a cap that gets raised by whoever hits it next.
PROOF_MAX = 16

#: The toolchain floor. `mise.toml` is TOML and `tomllib` is stdlib from 3.11;
#: a 3.9 interpreter cannot read the config the declaration is cross-checked
#: against, and shelling out to `mise` would make this checker's answer depend
#: on which mise happens to be installed. So the gate is declared, the wrapper
#: enforces it, and the alternative is recorded as a trade-off rather than
#: papered over.
MINIMUM_PYTHON = (3, 11)

#: The modules this file may import, beyond the contract harness's own list.
#: `tomllib` is the reason this file needs 3.11 (see MINIMUM_PYTHON below),
#: `shlex` is how a mise `run` string becomes an argv, and `tempfile` is where
#: the gate's log goes when the caller does not say. All three are stdlib;
#: core's suite asserts that against `sys.stdlib_module_names` as well as
#: against this list, so the list cannot quietly become a wish.
EXTRA_STDLIB = frozenset({"shlex", "tempfile", "tomllib"})

#: The only characters that make a `run` string something other than an argv.
#: A string containing one of these is handed to a shell, and a shell is where
#: a pipeline's exit code stops being the gate's.
SHELL_OPERATORS = frozenset("|&;<>$`()\\\"'*?[]#~={}")

#: Captured gate output is written to a log and summarised, never printed. This
#: is the cap on what is held in memory, not on what is written.
MAX_CAPTURED_BYTES = 8_000_000

#: A `name` the declaration carries. Deliberately not compared to the
#: directory: a worktree's directory is not the repository's name.
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
TASK_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
ENTRYPOINT_PATTERN = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._/-]+$")
ARGV_ITEM_PATTERN = re.compile(r"^[A-Za-z0-9._:@%+=,/-]+$")

#: The findings this checker can report, and nothing else. Mirrored in
#: `harness/gate_findings.json` and asserted equal in both directions by core's
#: suite, because a finding the inventory does not describe is a finding nobody
#: was told about — the same argument `harness/rules.json` makes for the
#: contract rules.
#:
#: `severity` is fixed per id. A finding that is sometimes fatal and sometimes
#: advisory is two findings wearing one name, and a caller cannot branch on it.
FINDINGS: dict[str, tuple[str, str, str]] = {
    "gate.declaration-missing": (
        "fail",
        "the repository declares no gate, so the gate can only be discovered by getting it wrong.",
        "write gate.yml; schemas/gate.schema.json is the format and docs/gate.md is the worked example",
    ),
    "gate.declaration-unreadable": (
        "fail",
        "the declaration is not a YAML document core's reader accepts.",
        "run: python3 harness/bin/gate-check <repo> --explain, and read the file and line it names",
    ),
    "gate.schema": (
        "fail",
        "the declaration does not satisfy schemas/gate.schema.json.",
        "run: python3 harness/bin/gate-check <repo> --explain, for the constraint and the JSON path",
    ),
    "gate.command-missing": (
        "fail",
        "the declared gate command names a file in this repository that is not there.",
        "point gate.command at the file that exists, or restore the file it names",
    ),
    "gate.command-unknown": (
        "warn",
        "the declared gate command starts with a bare name that is not on PATH on this machine.",
        "run `command -v <name>`; a PATH lookup depends on the machine, so this is a warning and not a failure",
    ),
    "gate.entrypoint-missing": (
        "fail",
        "the declared gate entrypoint is not a file in this repository.",
        "point gate.entrypoint at the file that exists, or restore the file it names",
    ),
    "gate.entrypoint-not-executable": (
        "fail",
        "the declared gate entrypoint exists but cannot be run.",
        "chmod +x the file; a gate nobody can execute is documentation",
    ),
    "gate.task-config-missing": (
        "fail",
        "the declaration names a mise task and this repository has no mise config.",
        "add a mise.toml with that task, or drop gate.miseTask if there is no mise here",
    ),
    "gate.task-missing": (
        "fail",
        "the declaration names a mise task that is not in this repository's mise config.",
        "add the task to mise.toml, or point gate.miseTask at the task that exists",
    ),
    "gate.task-unresolvable": (
        "fail",
        "the mise task's `run` string does not resolve to the declared gate entrypoint.",
        "make the task's `run` name the same file gate.entrypoint names; the two are the same gate and they may not disagree",
    ),
    "gate.task-unreadable": (
        "warn",
        "the mise task's `run` is a shell string this checker cannot resolve without a shell.",
        "point `run` at a single executable, or accept that only the entrypoint on disk is cross-checked",
    ),
    "gate.task-undeclared": (
        "warn",
        "this repository has a mise config and the declaration names no mise task, so the fleet's spelling is unavailable.",
        "add gate.miseTask naming the task `mise run prime` resolves to",
    ),
    "gate.ci-missing": (
        "fail",
        "the declaration names a CI workflow that is not in this repository.",
        "point gate.ci.workflow at the workflow that exists, or drop the ci block if there is none",
    ),
    "gate.ci-disagrees": (
        "fail",
        "the CI workflow the declaration names never invokes the gate, and nothing in it defers to a task runner either.",
        "add a step running the declared argv; a declaration CI does not call is a claim, not a gate",
    ),
    "gate.ci-unproven": (
        "warn",
        "the workflow has no step this checker can read as the declared argv, but it defers to a task runner, and this checker reads no Makefile.",
        "read the workflow: if it reaches the gate through a wrapper, say so in gate.yml's ci block; if it does not, add a step running the gate",
    ),
    "gate.ci-undeclared": (
        "warn",
        "the declaration says nothing about CI, so nothing checks that CI runs this gate.",
        "add a ci block naming the workflow and the argv it runs",
    ),
    "gate.proof-invalid": (
        "fail",
        "a declared proof cannot be evaluated: its pattern does not compile, or it has a floor and no single capture group to read it from.",
        "fix gate.proof[].match as a Python regular expression, with exactly one capture group when `minimum` is set",
    ),
    "gate.proof-missing": (
        "fail",
        "the gate ran, exited zero, and did not emit a proof it declared — a command that exits zero is not a gate.",
        "make the gate print the line gate.proof[].match names, or delete the proof if the gate genuinely never prints it",
    ),
    "gate.floor": (
        "fail",
        "the gate emitted its proof with a count below the floor the declaration promised.",
        "raise the count, or raise gate.proof[].minimum deliberately; a suite that shrank is a change, not a pass",
    ),
    "gate.nonzero": (
        "fail",
        "the gate exited nonzero.",
        "read the log path this run reported; it holds the gate's own output, which this file deliberately does not print",
    ),
    "gate.timeout": (
        "fail",
        "the gate ran past gate.timeoutSeconds and was stopped.",
        "raise gate.timeoutSeconds deliberately, or find what the gate is waiting for",
    ),
    "gate.requirement-path-missing": (
        "fail",
        "an external requirement is not satisfiable as declared: its command names a file in this repository that is not there, or names no command at all.",
        "point satisfy.command at the file that exists, or at a bare command name for something on PATH",
    ),
    "gate.requirement-unproven": (
        "warn",
        "an external requirement is not proven on this machine, by design.",
        "satisfy it with the declared command before gating; a requirement nobody ran is not a requirement met",
    ),
}

SEVERITIES = ("ok", "warn", "fail")

#: Every key a gate declaration may carry. Mirrors the root `properties` of
#: `schemas/gate.schema.json`, and core's suite asserts the two sets are the
#: same, so a field added to the schema and never taught to this file is a red
#: rather than a silent acceptance.
TOP_LEVEL_KEYS = frozenset({"version", "name", "gate", "external", "ci"})

#: And the ones that must be there. A declaration missing any of these is not a
#: smaller declaration, it is a different document: the absence of `external`
#: is precisely the defect that let a gate run its whole suite against a
#: database nobody had migrated.
REQUIRED_TOP_LEVEL_KEYS = ("version", "name", "gate", "external")


@dataclass(frozen=True)
class Finding:
    """One check's answer, in the shape yamine uses and `caf`'s surface will read.

    `remediate` is not decoration. MD13's most transferable finding about
    yamine was that every check message carries the exact remediation command;
    a check that says only "not ok" makes the reader go and look, and the
    reader who does not look is the reason it is still broken next week.
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

    repo: Path
    findings: list[Finding]
    log: Path | None = None
    could_not_run: str | None = None

    def of(self, severity: str) -> list[Finding]:
        return [finding for finding in self.findings if finding.severity == severity]

    @property
    def exit_code(self) -> int:
        if self.could_not_run is not None:
            return EXIT_COULD_NOT_RUN
        if self.of("fail"):
            return EXIT_FAIL
        return EXIT_OK

    def render(self) -> str:
        lines = [finding.render() for finding in self.findings]
        lines.append("")
        failed = len(self.of("fail"))
        warned = len(self.of("warn"))
        if self.could_not_run is not None:
            lines.append(f"COULD NOT RUN {self.repo}: {self.could_not_run}")
            return "\n".join(lines)
        if self.log is not None:
            lines.append(f"the gate's own output is in {self.log} and is not printed here")
        verdict = "FAIL" if failed else "OK"
        # Warnings counted separately, every time. A gate that reports "0
        # findings" when two of them were warnings is a report that lies, and
        # the count of warnings is the number a reader is allowed to ignore
        # deliberately rather than by accident.
        lines.append(
            f"{verdict} {self.repo}: {failed} failure(s), {warned} warning(s) — "
            + (
                "warnings do not move the exit code"
                if warned
                else "no warnings, so nothing was left unproven silently"
            )
        )
        return "\n".join(lines)


def finding(identifier: str, message: str) -> Finding:
    """Build a finding from the inventory, so an unknown id cannot be invented."""
    try:
        severity, _claim, remediate = FINDINGS[identifier]
    except KeyError:  # pragma: no cover - a test asserts the inventory is complete
        raise SystemExit(
            f"gate_check: {identifier} is not in FINDINGS. A finding the inventory does "
            f"not describe is a finding nobody was told about."
        )
    return Finding(id=identifier, severity=severity, message=message, remediate=remediate)


# --------------------------------------------------------------------------
# the format, re-implemented from schemas/gate.schema.json
# --------------------------------------------------------------------------


def validate(declaration: Any) -> list[str]:
    """The well-formedness half, without `jsonschema`.

    Every message names the JSON path and the constraint, because the point of
    this half is to tell a reader what to change and `jsonschema`'s own output
    is the reference the suite compares it against. The suite asserts that this
    function and the real schema accept and reject the same corpus
    (`test_the_gate_checker_and_the_schema_agree_on_every_example`), so the two
    cannot drift on anything core ships.
    """
    problems: list[str] = []

    def complain(path: str, constraint: str) -> None:
        problems.append(f"{path or '<root>'}: {constraint}")

    if not isinstance(declaration, dict):
        return ["<root>: type object"]

    allowed = {"version", "name", "gate", "external", "ci"}
    for key in sorted(declaration):
        if key not in allowed:
            complain("", f"additionalProperties: {key!r} is not a key of a gate declaration")

    for key in REQUIRED_TOP_LEVEL_KEYS:
        if key not in declaration:
            complain(key, "required")
    if declaration.get("version") != 1:
        complain("version", "const 1")
    name = declaration.get("name")
    if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name) or len(name) > 40:
        complain("name", "pattern ^[a-z][a-z0-9-]*$, maxLength 40")

    if "gate" in declaration:
        problems.extend(_validate_gate(declaration["gate"]))
    if "external" in declaration:
        problems.extend(_validate_external(declaration["external"]))
    if "ci" in declaration:
        problems.extend(_validate_ci(declaration["ci"]))
    return problems


def _validate_argv(value: Any, path: str, problems: list[str]) -> list[str] | None:
    """An argv, not a shell string. Returns the items when they are an argv."""
    if not isinstance(value, list):
        problems.append(f"{path}: type array")
        return None
    if not 1 <= len(value) <= 32:
        problems.append(f"{path}: minItems 1, maxItems 32")
    items: list[str] = []
    for index, item in enumerate(value):
        where = f"{path}/{index}"
        if not isinstance(item, str):
            problems.append(f"{where}: type string")
            continue
        if not 1 <= len(item) <= 400:
            problems.append(f"{where}: minLength 1, maxLength 400")
            continue
        # The same character class the schema's `not` states, expressed as a set
        # so the two halves of this file cannot describe different lists. A
        # metacharacter in an ARGUMENT is not a shell bug here — this checker
        # runs the argv with no shell — but it is the author thinking in shell,
        # and a declaration that records the accident is the accident.
        offending = sorted(set(item) & SHELL_OPERATORS)
        if offending or "\r" in item or "\n" in item:
            shown = "".join(offending) or "a newline"
            problems.append(
                f"{where}: not — {shown!r} in an argv item; a command is not a shell string"
            )
            continue
        items.append(item)
    return items


def _validate_gate(gate: Any) -> list[str]:
    problems: list[str] = []
    if not isinstance(gate, dict):
        return ["gate: type object"]
    allowed = {"command", "miseTask", "entrypoint", "timeoutSeconds", "proof"}
    for key in sorted(gate):
        if key not in allowed:
            problems.append(f"gate: additionalProperties {key!r}")
    for key in ("command", "entrypoint", "proof"):
        if key not in gate:
            problems.append(f"gate/{key}: required")
    if "command" in gate:
        _validate_argv(gate["command"], "gate/command", problems)
    if "miseTask" in gate:
        task = gate["miseTask"]
        if not isinstance(task, str) or not TASK_PATTERN.fullmatch(task) or len(task) > 40:
            problems.append("gate/miseTask: pattern ^[a-z][a-z0-9-]*$, maxLength 40")
    entrypoint = gate.get("entrypoint")
    if entrypoint is not None:
        if not isinstance(entrypoint, str) or not ENTRYPOINT_PATTERN.fullmatch(entrypoint):
            problems.append("gate/entrypoint: pattern a repository-relative path, with a directory in it")
        elif ".." in entrypoint.split("/"):
            problems.append("gate/entrypoint: not — a path may not leave the repository")
    timeout = gate.get("timeoutSeconds")
    if timeout is not None and (not isinstance(timeout, int) or isinstance(timeout, bool)
                                or not 1 <= timeout <= 14400):
        problems.append("gate/timeoutSeconds: minimum 1, maximum 14400")
    if "proof" in gate:
        problems.extend(_validate_proof(gate["proof"]))
    return problems


def _validate_proof(proof: Any) -> list[str]:
    problems: list[str] = []
    if not isinstance(proof, list):
        return ["gate/proof: type array"]
    if not 1 <= len(proof) <= PROOF_MAX:
        problems.append(f"gate/proof: minItems 1, maxItems {PROOF_MAX}")
    identifiers: set[str] = set()
    for index, item in enumerate(proof):
        where = f"gate/proof/{index}"
        if not isinstance(item, dict):
            problems.append(f"{where}: type object")
            continue
        for key in sorted(item):
            if key not in {"id", "match", "minimum"}:
                problems.append(f"{where}: additionalProperties {key!r}")
        for key in ("id", "match"):
            if key not in item:
                problems.append(f"{where}/{key}: required")
        identifier = item.get("id")
        if not isinstance(identifier, str) or not TASK_PATTERN.fullmatch(identifier) or len(identifier) > 40:
            problems.append(f"{where}/id: pattern ^[a-z][a-z0-9-]*$, maxLength 40")
        elif identifier in identifiers:
            problems.append(f"{where}/id: uniqueItems — {identifier!r} appears twice")
        else:
            identifiers.add(identifier)
        pattern = item.get("match")
        if not isinstance(pattern, str) or not 1 <= len(pattern) <= 300:
            problems.append(f"{where}/match: minLength 1, maxLength 300")
        elif _compile(pattern) is None:
            # A pattern this checker cannot compile is `gate.proof-invalid`,
            # and it is checked again in the proving phase. Here it is reported
            # as a shape problem, because a regular expression that does not
            # compile is a malformed declaration.
            problems.append(f"{where}/match: not a Python regular expression this checker can compile")
        minimum = item.get("minimum")
        if minimum is not None and (not isinstance(minimum, int) or isinstance(minimum, bool)
                                    or not 0 <= minimum <= 10_000_000):
            problems.append(f"{where}/minimum: minimum 0, maximum 10000000")
    return problems


def _validate_external(external: Any) -> list[str]:
    problems: list[str] = []
    if not isinstance(external, dict):
        return ["external: type object"]
    allowed = {"selfContained", "requirements"}
    for key in sorted(external):
        if key not in allowed:
            problems.append(f"external: additionalProperties {key!r}")
    for key in ("selfContained", "requirements"):
        if key not in external:
            problems.append(f"external/{key}: required")
    self_contained = external.get("selfContained")
    if not isinstance(self_contained, bool):
        problems.append("external/selfContained: type boolean")
    requirements = external.get("requirements")
    if not isinstance(requirements, list):
        return problems
    if len(requirements) > 16:
        problems.append("external/requirements: maxItems 16")
    if self_contained is True and requirements:
        problems.append(
            "external/requirements: maxItems 0 — the declaration says the gate is "
            "self-contained and names "
            f"{len(requirements)} thing(s) it needs"
        )
    if self_contained is False and not requirements:
        problems.append(
            "external/requirements: minItems 1 — the declaration says the gate is not "
            "self-contained and names no way to satisfy what it needs"
        )
    for index, item in enumerate(requirements):
        where = f"external/requirements/{index}"
        if not isinstance(item, dict):
            problems.append(f"{where}: type object")
            continue
        for key in sorted(item):
            if key not in {"kind", "name", "satisfy"}:
                problems.append(f"{where}: additionalProperties {key!r}")
        for key in ("kind", "name", "satisfy"):
            if key not in item:
                problems.append(f"{where}/{key}: required")
        if "kind" in item and item["kind"] not in {
            "database", "service", "toolchain", "credential", "network", "filesystem",
        }:
            problems.append(f"{where}/kind: enum")
        label = item.get("name")
        if not isinstance(label, str) or not 1 <= len(label) <= 200:
            problems.append(f"{where}/name: minLength 1, maxLength 200")
        satisfy = item.get("satisfy")
        if not isinstance(satisfy, dict):
            problems.append(f"{where}/satisfy: type object")
            continue
        for key in sorted(satisfy):
            if key not in {"command", "unmet"}:
                problems.append(f"{where}/satisfy: additionalProperties {key!r}")
        if "command" not in satisfy:
            problems.append(f"{where}/satisfy/command: required")
        else:
            items = _validate_argv(satisfy["command"], f"{where}/satisfy/command", problems)
            if items == []:
                problems.append(f"{where}/satisfy/command: minItems 1 — a requirement "
                                "with nothing to run is a pointer to a page that does not exist")
        unmet = satisfy.get("unmet")
        if unmet is not None and (not isinstance(unmet, str) or not 1 <= len(unmet) <= 400):
            problems.append(f"{where}/satisfy/unmet: minLength 1, maxLength 400")
    return problems


def _validate_ci(ci: Any) -> list[str]:
    problems: list[str] = []
    if not isinstance(ci, dict):
        return ["ci: type object"]
    allowed = {"workflow", "invokes"}
    for key in sorted(ci):
        if key not in allowed:
            problems.append(f"ci: additionalProperties {key!r}")
    for key in ("workflow", "invokes"):
        if key not in ci:
            problems.append(f"ci/{key}: required")
    workflow = ci.get("workflow")
    if workflow is not None:
        if (not isinstance(workflow, str)
                or not re.fullmatch(CI_WORKFLOW_PATTERN, workflow)
                or len(workflow) > 200):
            problems.append(f"ci/workflow: pattern {CI_WORKFLOW_PATTERN}")
    if "invokes" in ci:
        _validate_argv(ci["invokes"], "ci/invokes", problems)
    return problems


def _compile(pattern: str) -> re.Pattern[str] | None:
    try:
        return re.compile(pattern, re.MULTILINE)
    except re.error:
        return None


# --------------------------------------------------------------------------
# terminal escapes
# --------------------------------------------------------------------------
#
# WHY THIS EXISTS. A person writes `proof[].match` by reading their terminal, and
# a terminal does not show them the bytes. `vitest` prints
#
#     \x1b[2m      Tests \x1b[22m \x1b[1m\x1b[32m377 passed\x1b[39m\x1b[22m
#
# so a declaration written against what they SEE is `^[ ]*Tests…`, and against
# what the checker CAPTURES the line begins with an escape rather than a space
# and the pattern cannot match. That produced `gate.proof-missing` on a gate that
# had just proved, in the same log, that it ran 377 tests. MD17 ruled: strip here,
# not in the declaration and not with `NO_COLOR` in the gate. The second reason is
# the one that decides it — colour carries no assertion, so no proof could have
# depended on it.
#
# The inverse case is the quieter one and it is why this is not only about false
# REDS. `\x1b[38;5;208m` is a 256-colour index. A gate that ran 3 tests and printed
# `\x1b[38;5;208m3 passed` matches `^.*?([0-9]+).* passed$` with group(1) == "38",
# so `minimum: 38` was green over a suite of three. Stripping removes that reading
# as well as the false reds.
#
# THE SHAPE, AND WHY IT IS ONE CALL SITE. Four checks apply `proof[].match`.
# Stripping inside each of them is four call sites that will drift, and the fourth
# one added by a later packet is the one nobody remembers. So this is one function
# called exactly once, in `prove()`, where the output is read. The log keeps the
# raw bytes on purpose: it is the operator's evidence, and a log that disagreed
# with the output it records would be a worse lie than the one being fixed.
#
# WHAT IS HANDLED, and what is not, is not left to a reader to guess:
#
#   CSI   ESC [ … final  — SGR colour, cursor moves, erase, private modes; and
#                           its 8-bit form 0x9b. This is what test runners emit.
#   OSC   ESC ] … BEL|ST  — window titles, OSC 8 hyperlinks; and 8-bit 0x9d.
#   DCS   ESC P … ST     — device control, wrapped payloads.
#   two-character escapes, charset selection, keypad mode — ESC ( B, ESC 7, …
#
# NOT handled, deliberately, with the consequence stated rather than left to be
# discovered: an UNTERMINATED sequence. A string sequence with no terminator is
# left in place instead of being consumed to end-of-input. The tempting
# alternative consumes the rest of the log — including the proof line — and turns
# an absent proof into a green, which is precisely the class of defect this packet
# exists to end. A gate that leaves a sequence unterminated is malformed, and a
# malformed gate is allowed to fail loudly.
#
# The `.` in the OSC and DCS bodies deliberately excludes a newline. If a stripper
# could span a line it would JOIN two lines, and `^`/`$` would stop meaning "start
# and end of this line" for every other pattern in the fleet.

#: CSI, OSC, DCS and the two-character escapes, in the order they must be tried.
#: Every class that can be recognised from its own bytes is listed here, and this
#: list is the answer to "which sequences does the gate checker handle" — there is
#: no second list to drift from it.
ANSI_ESCAPE = re.compile(
    r"""
      \x1b\[[0-?]*[ -/]*[@-~]                      # CSI, 7-bit  (ESC [ … final)
    | \x9b[0-?]*[ -/]*[@-~]                        # CSI, 8-bit  (0x9b)
    | \x1b\][^\n\x07\x1b\x9c]*(?:\x07|\x1b\\|\x9c)  # OSC … BEL / ST / 0x9c
    | \x9d[^\n\x07\x1b\x9c]*(?:\x07|\x1b\\|\x9c)    # OSC, 8-bit
    | \x1b[P^_X][^\n\x1b\x9c]*(?:\x1b\\|\x9c)       # DCS / SOS / PM / APC … ST
    | \x1b[ -/]*[0-~]                               # nF, Fe, Fp: ESC ( B, ESC 7 …
    """,
    re.VERBOSE,
)


def strip_ansi(output: str) -> str:
    """The gate's output with its terminal escapes removed, for matching only.

    Called once, from `prove()`, and it **only ever deletes**: every character it
    returns was in the input, in order. That is the property the ruling rests on
    and it is what the accompanying test asserts, one character at a time.
    """
    return ANSI_ESCAPE.sub("", output)


# --------------------------------------------------------------------------
# reading the declaration
# --------------------------------------------------------------------------


def declaration_path(repo: Path) -> Path:
    return repo / DECLARATION


def read_declaration(repo: Path) -> tuple[Any, Finding | None]:
    """The declaration, or the finding that says there isn't one."""
    path = declaration_path(repo)
    if not path.is_file():
        return None, finding("gate.declaration-missing", f"{DECLARATION} is not in {repo}")
    try:
        return read_yaml(path.read_text(encoding="utf-8"), path), None
    except Refusal as refusal:
        return None, finding(
            "gate.declaration-unreadable",
            f"{DECLARATION} could not be read: {refusal.detail} (at {refusal.path})",
        )
    except OSError as error:
        return None, finding("gate.declaration-unreadable", f"{DECLARATION} is unreadable: {error}")


# --------------------------------------------------------------------------
# the checks
# --------------------------------------------------------------------------


def check_command(repo: Path, gate: dict) -> list[Finding]:
    """The declared command resolves to something that exists and runs.

    A repository-relative path that is not there is a **failure**: the
    declaration is checkable on this machine, and this machine is the machine
    the declaration is about. A bare name is a PATH lookup, which depends on
    the machine, so it is a **warning** and never moves the exit code — the
    alternative is a checker that is red on a laptop and green on CI, which is
    the same defect in a new place.
    """
    found: list[Finding] = []
    argv = gate.get("command") or []
    if not argv or not isinstance(argv[0], str):
        return found
    head = argv[0]
    if "/" in head:
        target = repo / head
        if not target.exists():
            found.append(finding(
                "gate.command-missing",
                f"gate.command starts with {head!r}, which is not in this repository",
            ))
    elif shutil.which(head) is None:
        found.append(finding(
            "gate.command-unknown",
            f"gate.command starts with {head!r}, which is not on PATH here",
        ))
    return found


def check_entrypoint(repo: Path, gate: dict) -> list[Finding]:
    entrypoint = gate.get("entrypoint")
    if not isinstance(entrypoint, str) or not entrypoint:
        return []
    target = repo / entrypoint
    if not target.is_file():
        return [finding("gate.entrypoint-missing", f"gate.entrypoint names {entrypoint!r}, which is not a file")]
    if not os.access(target, os.X_OK):
        return [finding(
            "gate.entrypoint-not-executable",
            f"gate.entrypoint names {entrypoint!r}, which is not executable",
        )]
    return []


def read_mise_config(repo: Path) -> dict | None:
    path = repo / "mise.toml"
    if not path.is_file() or tomllib is None:
        return None
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, ValueError):
        return None


def mise_task_run(config: dict, task: str, seen: set[str] | None = None) -> tuple[str | None, str | None]:
    """The argv a mise task runs, following one chain of `depends`.

    Returns `(argv, None)` or `(None, why-it-is-not-an-argv)`. The `depends`
    chain is followed because an alias task is how a repository spells
    `mise run test` and `mise run prime` as the same thing, and a checker that
    only understood `run` would report every alias as a missing task.
    """
    seen = seen or set()
    if task in seen:
        return None, f"the task {task!r} depends on itself"
    seen.add(task)
    table = (config.get("tasks") or {}).get(task)
    if not isinstance(table, dict):
        return None, f"no [tasks.{task}] table"
    run = table.get("run")
    if isinstance(run, list) and run and all(isinstance(item, str) for item in run):
        return list(run), None
    if isinstance(run, str):
        if any(operator in run for operator in SHELL_OPERATORS):
            return None, (
                f"[tasks.{task}].run is a shell string, not an argv, so the file it "
                "runs is only knowable by running a shell"
            )
        try:
            return shlex.split(run), None
        except ValueError as error:
            return None, f"[tasks.{task}].run does not split: {error}"
    depends = table.get("depends")
    if isinstance(depends, list):
        for target in depends:
            if isinstance(target, str):
                found, why = mise_task_run(config, target, seen)
                if found is not None:
                    return found, None
                if why and "no [tasks." in why:
                    return None, why
    return None, f"[tasks.{task}] has no run"


def check_mise_task(repo: Path, gate: dict) -> list[Finding]:
    """The fleet's spelling resolves, and resolves to the declared entrypoint.

    Two directions, and the second is the one that finds drift: a task can be
    present and still name a different file than the declaration does, which is
    the local gate and the mise task quietly disagreeing about what the gate is.
    """
    found: list[Finding] = []
    task = gate.get("miseTask")
    config = read_mise_config(repo)
    if task is None:
        if config is not None and (config.get("tasks")):
            found.append(finding(
                "gate.task-undeclared",
                "this repository has mise tasks and the declaration names none of them",
            ))
        return found
    if not isinstance(task, str):
        return found
    if config is None:
        return [finding(
            "gate.task-config-missing",
            f"the declaration names mise task {task!r} and there is no mise.toml here",
        )]
    argv, why = mise_task_run(config, task)
    if argv is None:
        if why and "shell string" in why:
            return [finding("gate.task-unreadable", why)]
        return [finding("gate.task-missing", f"mise.toml has no runnable [tasks.{task}]: {why}")]
    if not argv:
        return [finding("gate.task-missing", f"[tasks.{task}].run is empty")]
    entrypoint = gate.get("entrypoint")
    head = argv[0]
    normalised = head[2:] if head.startswith("./") else head
    if "/" not in normalised:
        # A bare name, e.g. `run = "go test ./..."` or `run = "uv run pytest"`.
        # The file it runs is whatever PATH finds, so it cannot be compared to
        # the declared entrypoint. The task exists and runs, which is all this
        # check can honestly say.
        return found
    if isinstance(entrypoint, str) and normalised != entrypoint:
        return [finding(
            "gate.task-unresolvable",
            f"[tasks.{task}].run names {normalised!r} and gate.entrypoint names "
            f"{entrypoint!r}; those are two different gates",
        )]
    return found


# A `run:` key, in every spelling GitHub Actions accepts and every spelling this
# fleet has written.
#
# IT WAS WRONG, AND IT WAS WRONG BY AN ANCHOR. This pattern used to end `\s*$`,
# so `run: |` matched and `run: ./bin/prime` did not — and the shape it could not
# see is how the gate is written in gateway/ci.yml:65, parlor/ci.yml:81, and every
# repository this standard has been adopted into since. `gate.ci-disagrees` fired
# on correct workflows, which is the same defect as staying quiet on broken ones:
# both teach the reader to ignore the finding, and this one taught it on the
# first repository that adopted the standard. The caller's `if not
# matched.group("block")` branch for `run: <command>` on one line was DEAD CODE
# the whole time — no input could ever reach it. That is the signature of a
# pattern that was written for one fixture and never met another.
#
# The three parts, and each is load-bearing:
#
#   (?:-\s+)?     the sequence-item spelling, `- run: x`. Zero occurrences in
#                 this fleet's twelve workflow trees, and included anyway: it is
#                 the same key in the same position, and a pattern that cannot
#                 see it fails silently in exactly the way the anchor failed. A
#                 shape absent from today's tree is not a shape that should be
#                 invisible. Handling it here rather than in the caller keeps one
#                 key in one place — splitting it would make the reader check
#                 both.
#   [|>][+-]?\d*  a block scalar. `\d*` is the explicit indentation indicator
#                 (`run: |2`), which is rare and harmless to accept.
#   inline        `\S.*?` — the command, when it is on the key's own line. It is
#                 NOT `\S+`, because a command with arguments and a quoted
#                 variable is the common case, not the exotic one:
#                 `run: cargo llvm-cov --fail-under-lines "$COVERAGE_FAIL_UNDER"`.
#
# The caller decides what an `inline` that is only a comment means, because only
# the caller knows that a comment is not a command. That is the one judgement
# this pattern deliberately does not make.
RUN_KEY = re.compile(
    r"^(?P<indent>\s*)"
    r"(?:-\s+)?run:"
    r"(?:\s+(?P<block>[|>][+-]?\d*)?(?P<inline>\S.*?)?)?"
    r"\s*$"
)


def ci_body(repo: Path, workflow: str) -> str:
    """The text of the thing CI runs, as one string to search.

    A GitHub Actions workflow is read through its `run:` bodies, because a
    workflow is a document core has no schema for and the question being
    asked is only "does any step's command mention this argv".

    Anything else is read whole. The fleet's CI is no longer GitHub Actions:
    the gate runs in a dev sandbox, and what the runner executes is a file in
    the repository — `ci/gate.sh` — so the proof that CI runs the gate is
    that the file says so. The same question, asked of a different shape of
    file.

    A workflow is recognised by its suffix. A file called `ci.yml` that is
    not a workflow would be misread, and a repository that has one is a
    repository whose CI is a workflow with a different name — so the suffix
    is the rule and a shell script is the case this branch exists for.
    """
    path = repo / workflow
    if path.suffix.lower() in (".yml", ".yaml"):
        return "\n".join(workflow_run_lines(repo, workflow))
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def workflow_run_lines(repo: Path, workflow: str) -> list[str]:
    """Every `run:` body in a workflow, flattened to one string per line.

    Deliberately textual. A workflow is not a document core has a schema for,
    and reading it as one would mean a second YAML dialect in this file; the
    question being asked is only "does any step's command mention this argv",
    and a substring over the run bodies answers it without a parser.

    Two rules, and the second is the one that is easy to get wrong:

    The block-scalar rule is indentation, not a blank line: a `run: |` body
    continues through blank lines for as long as the following non-blank lines
    stay more indented than the `run:` key. Ending a body at the first blank
    line is the obvious implementation and it is wrong — half of this
    repository's own workflow puts a blank line and a comment inside a run
    body, and a body that stops early is a body whose second half nobody reads.

    The comment rule: a `run:` whose value is nothing but a comment carries no
    command at all (PyYAML reads the value as None), so the line below it is a
    continuation or nothing — never a command. `run: # TODO: wire up bin/gate`
    is the shape that turns this function from a false red into a false green,
    and it is asserted in the self-test from both sides: the comment is not read
    as a command, and a real command that merely has a comment after it is.

    A trailing comment on a line that DOES carry a command is not stripped.
    `run: bin/gate 2>&1 | tee "$LOG"  # the gate` keeps its `# the gate`, because
    removing it would truncate the only part that matters, and an extra token in a
    line that is about to be substring-searched is harmless.
    """
    path = repo / workflow
    if not path.is_file():
        return []
    lines: list[str] = []
    key_indent: int | None = None
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = raw.strip()
        if key_indent is not None:
            if not stripped:
                lines.append("")
                continue
            indent = len(raw) - len(raw.lstrip())
            if indent <= key_indent:
                key_indent = None
            else:
                lines.append(stripped)
                continue
        matched = RUN_KEY.match(raw)
        if matched:
            inline = matched.group("inline")
            if inline is not None and not inline.startswith("#"):
                # `run: <command>`, all on one line. The command is the captured
                # group, not `raw.split("run:", 1)[1]` — the split could not tell
                # this key from any other line that happens to contain `run:`.
                lines.append(inline)
            else:
                # A block scalar (`run: |`), or a bare `run:` whose value is on
                # the lines below it. Keep reading while the following lines stay
                # deeper than this key, which the top of this loop already does.
                key_indent = len(matched.group("indent"))
    return lines


def check_ci(repo: Path, declaration: dict) -> list[Finding]:
    """Does the workflow the declaration names actually run the gate?

    The policy, in full, with its reasoning in docs/gate.md. Three answers, and
    which one you get is stated here because a check that decides this silently
    is how the one-line `run:` bug happened:

    A PASS, in three shapes. Every element of `invokes` appearing in some `run:`
    body — ONCE OR ANY NUMBER OF TIMES, because `invokes` claims the gate is
    REACHABLE from CI, not how often it is reached; core's own workflow runs
    `bin/prime` AND `bin/prime --pytest`, and asserting on the count would fire
    on the repository that wrote the rule. Or the body calling the mise task the
    declaration names, which this checker has separately proven resolves to the
    declared entrypoint. Or a job that only calls a reusable workflow, sitting
    beside a step that runs the gate — which is gateway and parlor both.

    A WARNING when the body defers to a task runner and the gate is not visible.
    This checker reads no Makefile and no shell script, so a `make gate` step and
    a `make gate` step whose target was emptied look identical to it. Failing
    there is the false red this checker spent a release committing; staying
    silent is the false green. It says what it cannot see and exits 0.

    A FAILURE when the run bodies contain nothing that gates at all. CI plainly
    does not run the gate, and that is the whole job of this check.

    The warning tier's leak is real and is named rather than hidden: a workflow
    whose only task invocation is unrelated also warns instead of failing, so
    deleting the gate step from a repository that also runs `mise run lint` costs
    a warning rather than a red. The message says so, and says how to settle it.
    """
    ci = declaration.get("ci")
    if ci is None:
        return [finding(
            "gate.ci-undeclared",
            "the declaration has no ci block, so nothing checks that CI runs this gate",
        )]
    if not isinstance(ci, dict):
        return []
    found: list[Finding] = []
    workflow = ci.get("workflow")
    if not isinstance(workflow, str):
        return found
    if not (repo / workflow).is_file():
        return [finding("gate.ci-missing", f"gate.ci.workflow names {workflow!r}, which is not a file here")]
    body = ci_body(repo, workflow)
    argv = ci.get("invokes")
    if isinstance(argv, list) and argv and all(_appears(element, body) for element in argv if element):
        return found
    gate = declaration.get("gate")
    task = gate.get("miseTask") if isinstance(gate, dict) else None
    if _invokes_declared_task(body, task):
        # `mise run prime`, where `prime` is the task gate.yml names. If that task
        # does NOT resolve to the declared entrypoint, check_task has already
        # reported gate.task-unresolvable as a failure, so the repository is red
        # either way and this second spelling cannot talk it green.
        return found
    printable = " ".join(str(element) for element in argv) if isinstance(argv, list) else "?"
    if _defers_to_a_task_runner(body):
        return [finding(
            "gate.ci-unproven",
            f"{workflow} has no step this checker can read as {printable}, but it does defer to a "
            "task runner. This checker reads no Makefile and no shell script, so it cannot tell a "
            "wrapper that calls the gate from a wrapper that was emptied — and because it cannot "
            "tell, it will not call it a failure. Read the workflow and settle it. Note the leak "
            "in both directions: this also fires on a workflow whose only task call is unrelated, "
            "so a deleted gate step in such a repository warns rather than fails. If CI really "
            f"does not run the gate, add a step running {printable}; if it runs the gate through a "
            "wrapper, say so in gate.yml's ci block so the next reader does not have to guess",
        )]
    return [finding(
        "gate.ci-disagrees",
        f"{workflow} never runs {printable}",
    )]


# `mise run prime`, `mise r prime`. The task the declaration names is the only
# indirect call this checker will accept as proof, and the reason it is entitled
# to accept it: check_task has already read mise.toml and established that this
# task runs the declared entrypoint. A task the declaration does not name gets
# no such benefit, and neither does a make target, because nothing reads a
# Makefile.
_MISE_TASK_CALL = re.compile(r"\bmise\s+(?:run|r)\s+(?P<task>[A-Za-z0-9_][A-Za-z0-9_.-]*)")


def _invokes_declared_task(body: str, task: object) -> bool:
    if not isinstance(task, str) or not task:
        return False
    for match in _MISE_TASK_CALL.finditer(body):
        if match.group("task") == task:
            return True
    return False


# A `run:` line that STARTS by deferring to a task runner. Anchored to the start
# of a line (after any VAR=value prefix) rather than searched for anywhere, so a
# `mise` or `make` mentioned in prose, in a comment, or as a substring of a path
# does not quietly turn a failure into a warning. Deliberately narrow: it is a
# reason to doubt this checker's own verdict, not a way to avoid it.
TASK_RUNNER_CALL = re.compile(
    r"^(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*(?:mise|make|just)\s+\S", re.MULTILINE
)


def _defers_to_a_task_runner(body: str) -> bool:
    return TASK_RUNNER_CALL.search(body) is not None


def _appears(element: str, body: str) -> bool:
    return element in body or (element.startswith("./") and element[2:] in body)


def check_requirements(repo: Path, external: dict) -> list[Finding]:
    """Every requirement names an argv, and every repo-relative one is checked.

    The split is the honest one: `satisfy.command[0]` containing a `/` is a
    claim about **this** repository and is checked against it; a bare name is a
    claim about the machine and is not, because this checker does not run the
    command and does not pretend to have.
    """
    found: list[Finding] = []
    requirements = external.get("requirements") or []
    for item in requirements:
        if not isinstance(item, dict):
            continue
        satisfy = item.get("satisfy")
        if not isinstance(satisfy, dict):
            continue
        argv = satisfy.get("command")
        label = item.get("name", "an unnamed requirement")
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
            # Unreachable through `check()`: `validate()` has already refused a
            # requirement with no argv, and a declaration that gets past
            # `validate()` has one by construction. Kept because this function
            # is also called directly by core's suite, and a helper that trusts
            # its caller to have checked is a helper that is wrong the first
            # time somebody calls it a different way.
            found.append(finding(
                "gate.requirement-path-missing",
                f"external requirement {label!r} names no command that satisfies it",
            ))
            continue
        head = argv[0]
        if "/" in head:
            if not (repo / head).exists():
                found.append(finding(
                    "gate.requirement-path-missing",
                    f"external requirement {label!r} is satisfied by {head!r}, "
                    "which is not in this repository",
                ))
        else:
            found.append(finding(
                "gate.requirement-unproven",
                f"external requirement {label!r} is satisfied by {head!r}, a command on "
                "PATH; this checker did not run it and cannot say whether it is there",
            ))
    return found


def prove(repo: Path, gate: dict, log_dir: Path) -> tuple[list[Finding], Path]:
    """Run the declared gate and check it actually ran.

    The exit code is the process's own, read from `subprocess.run` with no
    shell and no pipe. That is not a style preference: this fleet's one
    recorded false green was `… | tail -45; echo "PRIME EXIT=$?"` under zsh,
    where `$?` is the exit code of `tail`. A checker that put the gate through
    a pipe would reproduce the defect it exists to catch, so it does not, and
    the wrapper documents the `PIPESTATUS` spelling for the caller who does.

    The gate's output is written to a log and **not printed**. No off-the-shelf
    tool detects a secret leaked at runtime into a log — 0 of 268 Semgrep rules
    intersect CWE-532 — so the only safe thing to do with a test log is to keep
    it out of the report.
    """
    found: list[Finding] = []
    argv = [str(item) for item in (gate.get("command") or [])]
    if not argv:
        return [finding("gate.proof-missing", "there is no gate.command to run")], log_dir / "gate.log"
    timeout = gate.get("timeoutSeconds") or 900
    log_path = log_dir / "gate.log"
    try:
        completed = subprocess.run(  # noqa: S603 - argv, no shell; the whole point
            argv,
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        output = f"{completed.stdout}{completed.stderr}"
        code = completed.returncode
    except subprocess.TimeoutExpired as expired:
        output = f"{expired.stdout or ''}{expired.stderr or ''}"
        code = None
    except OSError as error:
        output = ""
        code = -1
        found.append(finding(
            "gate.command-missing",
            f"gate.command could not be started: {error}",
        ))
    try:
        log_path.write_text(output[:MAX_CAPTURED_BYTES], encoding="utf-8")
    except OSError as error:  # pragma: no cover - a read-only log dir
        found.append(finding("gate.nonzero", f"the gate's output could not be written to {log_path}: {error}"))

    if code is None:
        found.append(finding(
            "gate.timeout",
            f"the gate was stopped after gate.timeoutSeconds ({timeout})",
        ))
    elif code != 0:
        found.append(finding("gate.nonzero", f"the gate exited {code}"))

    # THE ONE PLACE. Read the output once, strip it once, and let every pattern
    # below see the same colour-free text — four call sites would drift, and a
    # checker that matches four differently is worse than one that matches the
    # bytes. `output` itself is untouched above and below this line, so the log
    # keeps the gate's real bytes: it is the evidence a human reads when a proof
    # does not appear, and evidence that has been quietly reformatted is not
    # evidence. See ANSI_ESCAPE above for the sequences handled and the one
    # deliberately left alone.
    matchable = strip_ansi(output)

    for index, item in enumerate(gate.get("proof") or []):
        if not isinstance(item, dict):
            continue
        identifier = item.get("id", f"proof/{index}")
        pattern = item.get("match")
        if not isinstance(pattern, str):
            continue
        compiled = _compile(pattern)
        if compiled is None:
            found.append(finding(
                "gate.proof-invalid",
                f"proof {identifier!r} has a match that does not compile: {pattern!r}",
            ))
            continue
        matches = list(compiled.finditer(matchable))
        if not matches:
            found.append(finding(
                "gate.proof-missing",
                f"proof {identifier!r} never appeared; no line of the gate's output, with "
                f"terminal escapes stripped, matches {pattern!r}",
            ))
            continue
        minimum = item.get("minimum")
        if minimum is None:
            continue
        if compiled.groups != 1:
            found.append(finding(
                "gate.proof-invalid",
                f"proof {identifier!r} sets a minimum of {minimum} and its pattern has "
                f"{compiled.groups} capture group(s); a floor is read from exactly one",
            ))
            continue
        counted = [int(match.group(1)) for match in matches if match.group(1).isdigit()]
        if not counted:
            found.append(finding(
                "gate.proof-invalid",
                f"proof {identifier!r} sets a minimum but its capture group is not a number",
            ))
            continue
        seen = counted[-1]
        if seen < minimum:
            found.append(finding(
                "gate.floor",
                f"proof {identifier!r} reported {seen} and the declaration's floor is {minimum}",
            ))
    return found, log_path


# --------------------------------------------------------------------------
# the run
# --------------------------------------------------------------------------


def check(repo: Path, *, prove_it: bool = False, log_dir: Path | None = None) -> Report:
    """Check one repository's gate declaration against that repository."""
    repo = repo.resolve()
    if not repo.is_dir():
        return Report(repo=repo, findings=[], could_not_run=f"{repo} is not a directory")
    if tomllib is None or sys.version_info < MINIMUM_PYTHON:  # pragma: no cover
        return Report(
            repo=repo,
            findings=[],
            could_not_run=(
                f"gate_check needs python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]} or newer, because "
                "it reads mise.toml with tomllib, which is stdlib from 3.11. This is exit 2 and "
                "never 0: a check that could not read the config has not checked the gate."
            ),
        )

    declaration, problem = read_declaration(repo)
    if problem is not None:
        return Report(repo=repo, findings=[problem])
    if not isinstance(declaration, dict):
        return Report(
            repo=repo,
            findings=[finding("gate.schema", f"{DECLARATION} is not a mapping")],
        )

    problems = validate(declaration)
    found: list[Finding] = []
    if problems:
        found.append(finding(
            "gate.schema",
            f"{DECLARATION} does not satisfy schemas/gate.schema.json: "
            + "; ".join(problems[:6])
            + (f" (and {len(problems) - 6} more)" if len(problems) > 6 else ""),
        ))
        return Report(repo=repo, findings=found)

    gate = declaration.get("gate") or {}
    external = declaration.get("external") or {}
    found += check_command(repo, gate)
    found += check_entrypoint(repo, gate)
    found += check_mise_task(repo, gate)
    found += check_requirements(repo, external)
    found += check_ci(repo, declaration)

    log_path: Path | None = None
    if prove_it:
        # A temporary directory by default, never a directory inside the
        # repository. core's CI asserts `git diff --exit-code` after the gate,
        # and a checker that wrote its log into the tree would be adding a
        # file the gate is supposed to leave alone.
        target = log_dir or Path(tempfile.mkdtemp(prefix="gate-check."))
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as error:  # pragma: no cover
            return Report(repo=repo, findings=found, could_not_run=f"the log directory is unusable: {error}")
        proved, log_path = prove(repo, gate, target)
        found += proved
    return Report(repo=repo, findings=found, log=log_path)


def to_json(report: Report) -> str:
    return json.dumps(
        {
            "repo": str(report.repo),
            "exitCode": report.exit_code,
            "couldNotRun": report.could_not_run,
            "log": str(report.log) if report.log else None,
            "counts": {severity: len(report.of(severity)) for severity in SEVERITIES},
            "findings": [
                {
                    "id": item.id,
                    "severity": item.severity,
                    "message": item.message,
                    "remediate": item.remediate,
                }
                for item in report.findings
            ],
        },
        indent=2,
        sort_keys=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gate-check",
        description="Check a repository's gate declaration against that repository.",
    )
    parser.add_argument("repo", nargs="?", default=".", help="the repository to check (default: .)")
    parser.add_argument(
        "--prove",
        action="store_true",
        help="also RUN the declared gate and require every proof it declared to appear",
    )
    parser.add_argument("--log-dir", type=Path, default=None, help="where to write the gate's own output")
    parser.add_argument("--json", action="store_true", help="emit the findings as JSON")
    parser.add_argument(
        "--explain",
        action="store_true",
        help="list every finding this checker can report, and what each one means",
    )
    arguments = parser.parse_args(argv)

    if arguments.explain:
        for identifier in sorted(FINDINGS):
            severity, claim, remediate = FINDINGS[identifier]
            print(f"{identifier}  [{severity}]\n  {claim}\n  fix: {remediate}")
        return EXIT_OK

    report = check(Path(arguments.repo), prove_it=arguments.prove, log_dir=arguments.log_dir)
    print(to_json(report) if arguments.json else report.render())
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
