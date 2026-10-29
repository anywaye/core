#!/usr/bin/env python3

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

DECLARATION = Path("gate.yml")

GATE_SCHEMA_RELATIVE = Path("schemas") / "gate.schema.json"

CI_WORKFLOW_PATTERN = (
    r"((?:\.github/workflows|ci)/[A-Za-z0-9._-]+\.ya?ml"
    r"|(?!\.\.(?:/|$))[A-Za-z0-9._-]+(?:/(?!\.\.(?:/|$))[A-Za-z0-9._-]+)*\.sh)"
)

PROOF_MAX = 16

MINIMUM_PYTHON = (3, 11)

EXTRA_STDLIB = frozenset({"shlex", "tempfile", "tomllib"})

SHELL_OPERATORS = frozenset("|&;<>$`()\\\"'*?[]#~={}")

MAX_CAPTURED_BYTES = 8_000_000

NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
TASK_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
ENTRYPOINT_PATTERN = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._/-]+$")
ARGV_ITEM_PATTERN = re.compile(r"^[A-Za-z0-9._:@%+=,/-]+$")

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

TOP_LEVEL_KEYS = frozenset({"version", "name", "gate", "external", "ci"})

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



ANSI_ESCAPE = re.compile(
    r"""
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
        return found
    if isinstance(entrypoint, str) and normalised != entrypoint:
        return [finding(
            "gate.task-unresolvable",
            f"[tasks.{task}].run names {normalised!r} and gate.entrypoint names "
            f"{entrypoint!r}; those are two different gates",
        )]
    return found


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
                lines.append(inline)
            else:
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


_MISE_TASK_CALL = re.compile(r"\bmise\s+(?:run|r)\s+(?P<task>[A-Za-z0-9_][A-Za-z0-9_.-]*)")


def _invokes_declared_task(body: str, task: object) -> bool:
    if not isinstance(task, str) or not task:
        return False
    for match in _MISE_TASK_CALL.finditer(body):
        if match.group("task") == task:
            return True
    return False


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
