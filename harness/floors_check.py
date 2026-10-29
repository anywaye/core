#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from gate_check import _compile, strip_ansi  # noqa: E402 - one reader, one dialect
from anywaye_contract import read_yaml  # noqa: E402 - travels with the harness

DECLARATION = "gate.yml"

EXACT = "exact"
BELOW = "below"
ABOVE = "above"
NOT_MEASURED = "not-measured"

BASELINE_ASSIGNMENT = re.compile(
    r"^[ \t]*(BASELINE_[A-Z0-9_]+)[ \t]*:[ \t]*['\"]?([0-9]+)['\"]?[ \t]*$",
    re.MULTILINE,
)


def declared_floors(repo: Path) -> list[dict[str, Any]]:
    """Every floor this repository declares, read out of its own gate.yml."""
    declaration = repo / DECLARATION
    if not declaration.is_file():
        return []
    try:
        document = read_yaml(declaration.read_text(encoding="utf-8"), declaration)
    except Exception as error:  # noqa: BLE001 - a refusal is a row, not a crash
        return [{
            "repo": repo.name, "id": "<declaration>", "match": None,
            "declared": None, "measured": None, "verdict": NOT_MEASURED,
            "reason": f"gate.yml is not readable by core's reader: {error}",
        }]
    if not isinstance(document, dict):
        return []
    gate = document.get("gate")
    if not isinstance(gate, dict):
        return []
    rows: list[dict[str, Any]] = []
    proofs = gate.get("proof")
    for index, proof in enumerate(proofs if isinstance(proofs, list) else []):
        if not isinstance(proof, dict) or "minimum" not in proof:
            continue
        rows.append({
            "repo": repo.name,
            "id": proof.get("id") or f"proof/{index}",
            "match": proof.get("match"),
            "declared": proof.get("minimum"),
            "command": gate.get("command"),
            "timeoutSeconds": gate.get("timeoutSeconds"),
        })
    return rows


def workflow_baselines(repo: Path) -> list[dict[str, Any]]:
    """Every `BASELINE_*: 'N'` declared by a workflow in this repository.

    Reported beside the gate.yml floors and never merged into their column,
    because this is a different kind of claim with a different owner and a
    different comparator: `gate.yml`'s number is read by `gate_check.py`, this
    one is read by a shell `if` in a workflow. The packet's own worked example
    is a repository whose two halves of one ratchet disagreed.
    """
    rows: list[dict[str, Any]] = []
    workflows = repo / "ci"
    if not workflows.is_dir():
        return rows
    for workflow in sorted(workflows.glob("*.y*ml")):
        try:
            text = workflow.read_text(encoding="utf-8")
        except OSError:
            continue
        for name, value in BASELINE_ASSIGNMENT.findall(text):
            rows.append({
                "repo": repo.name,
                "id": name,
                "declared": int(value),
                "file": str(workflow.relative_to(repo)),
            })
    return rows


def fleet_repositories(fleet: Path) -> list[Path]:
    """Every directory under `fleet` that declares a gate.

    Derived by walking, not from a list. A worktree directory matches too - it
    carries the same gate.yml - so pointing this at the workspace root counts
    every live worker's branch as well as every checkout; the audit that wants
    one row per repository points it at the checkouts themselves.
    """
    found: list[Path] = []
    try:
        children = sorted(fleet.iterdir())
    except OSError as error:
        raise SystemExit(f"floors-check: cannot read {fleet}: {error}")
    for child in children:
        if child.is_dir() and (child / DECLARATION).is_file():
            found.append(child)
    return found


def run_gate(repo: Path, command: list[Any], timeout_seconds: int, log_path: Path
             ) -> tuple[str, int | None, str | None]:
    """Run the declared gate. Returns (output, exit code, error-or-None).

    No shell and no pipe, and the exit code is `subprocess.run`'s own - the same
    rule `gate_check.prove` follows and for the same recorded reason: a
    pipeline under zsh reports `tail`'s exit code, which is always 0.
    """
    argv = [str(item) for item in command]
    try:
        done = subprocess.run(  # noqa: S603 - argv, no shell; the whole point
            argv, cwd=str(repo), capture_output=True, text=True,
            timeout=timeout_seconds, check=False,
        )
    except subprocess.TimeoutExpired as expired:
        return f"{expired.stdout or ''}{expired.stderr or ''}", None, (
            f"the gate did not finish inside its declared timeoutSeconds "
            f"({timeout_seconds}); this is a reported row, not a pass"
        )
    except OSError as error:
        return "", -1, f"the gate could not be started: {error}"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(f"{done.stdout}{done.stderr}", encoding="utf-8")
    except OSError:
        pass
    return f"{done.stdout}{done.stderr}", done.returncode, None


def count_proof(output: str, floor: dict[str, Any]) -> tuple[int | None, str | None]:
    """The floor's number off one run, or None plus why it is not there.

    The LAST match, not the first, and exactly as `gate_check.prove` reads it:
    a suite that prints a running count and then a summary must be read at the
    summary, and a floor that quietly disagreed with the checker that enforces
    it would be a second answer to one question.
    """
    compiled = _compile(floor.get("match") or "")
    if compiled is None:
        return None, "the declared pattern does not compile"
    matches = list(compiled.finditer(strip_ansi(output)))
    if not matches:
        return None, "the declared pattern never appeared in the gate's output"
    if compiled.groups != 1:
        return None, (f"the declared pattern has {compiled.groups} capture groups; "
                      f"a floor is read from exactly one")
    counted = [int(m.group(1)) for m in matches if (m.group(1) or "").isdigit()]
    if not counted:
        return None, "the capture group never held a number"
    return counted[-1], None


def verdict_for(declared: int, measured: int) -> str:
    """`exact`, or which way it drifted. Only this function decides drift."""
    if measured == declared:
        return EXACT
    return BELOW if measured > declared else ABOVE


def measure_repository(repo: Path, log_dir: Path, cap_seconds: int = 0) -> list[dict[str, Any]]:
    """Declare this repository's floors, run its gate ONCE, and read every floor.

    One run for the whole repository. Six floors in one declaration are not six
    suites: a floor is a claim about the same run, and running the gate once per
    claim multiplies a four-minute suite by its own proof count.

    `cap_seconds`, when it bites, is recorded in the row rather than quietly
    applied: a bound that shortened a run is a bound a reader has to know about,
    because a floor reported `not-measured` at 240s and one reported
    `not-measured` at a declared 900s are different facts about the same tree.
    """
    floors = declared_floors(repo)
    if not floors:
        return []
    command = floors[0].get("command")
    if not isinstance(command, list) or not command:
        for row in floors:
            row["measured"] = None
            row["verdict"] = NOT_MEASURED
            row["reason"] = "the declaration names no gate.command to run"
        return floors
    timeout = floors[0].get("timeoutSeconds")
    declared_timeout = timeout if isinstance(timeout, int) and timeout > 0 else 900
    capped = bool(cap_seconds) and cap_seconds < declared_timeout
    timeout = min(declared_timeout, cap_seconds) if capped else declared_timeout
    log_path = log_dir / (repo.name + ".gate.log")
    output, code, error = run_gate(repo, command, timeout, log_path)
    if capped and error is not None:
        error += (f"; this sweep capped every gate at {cap_seconds}s, below the "
                  f"{declared_timeout}s the declaration allows")

    for row in floors:
        row["gate-exit"] = code
        row["gate-log"] = str(log_path)
        measured, why = count_proof(output, row)
        if error is not None:
            row["measured"] = None
            row["verdict"] = NOT_MEASURED
            row["reason"] = error
        elif code not in (0, None):
            row["measured"] = None
            row["verdict"] = NOT_MEASURED
            row["reason"] = (f"the gate exited {code}, so its output is not a measurement; "
                             f"read {log_path}")
        elif measured is None:
            row["measured"] = None
            row["verdict"] = NOT_MEASURED
            row["reason"] = why
        else:
            row["measured"] = measured
            row["verdict"] = verdict_for(int(row["declared"]), measured)
    return floors


def table(rows: list[dict[str, Any]]) -> str:
    """The table, and the counts. A skipped row is named here, never absent.

    The DELTA column is not decoration. Several of this fleet's floors are
    deliberately set a little UNDER the measured number - caf holds `875` against
    a measured 876 and gateway holds a five-test margin on `pass` - and a verdict
    of `below` on its own cannot tell a documented margin from a number nobody
    moved. The delta is what makes those two readable in one glance: a floor one
    or two under with a comment saying so is a margin, and a floor forty-four
    under is a floor that stopped checking.
    """
    if not rows:
        return "no floors are declared anywhere under this directory"
    width = max(len(f"{r['repo']}/{r['id']}") for r in rows)
    lines = [f"{'repository/proof'.ljust(width)}  {'declared':>9}  {'measured':>9}  {'delta':>7}  verdict"]
    for row in rows:
        declared = "-" if row["declared"] is None else str(row["declared"])
        measured = "-" if row["measured"] is None else str(row["measured"])
        delta = "-"
        if row["declared"] is not None and row["measured"] is not None:
            delta = f"{row['measured'] - row['declared']:+d}"
        lines.append(
            f"{f'{row['repo']}/{row['id']}'.ljust(width)}  {declared:>9}  {measured:>9}  {delta:>7}  {row['verdict']}")
        if row.get("reason"):
            lines.append(" " * (width + 15) + "- " + str(row["reason"]))
    exact = sum(1 for r in rows if r["verdict"] == EXACT)
    below = sum(1 for r in rows if r["verdict"] == BELOW)
    above = sum(1 for r in rows if r["verdict"] == ABOVE)
    skipped = sum(1 for r in rows if r["verdict"] == NOT_MEASURED)
    lines.append("")
    lines.append(f"{len(rows)} floors: {exact} exact, {below} below, {above} above, {skipped} not measured")
    if skipped:
        lines.append(f"{skipped} could not be settled on this machine. Each one is named above "
                     f"with its reason; none of them is a pass and none is counted as one.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="floors-check",
        description="measure every declared floor in the fleet against its tree",
    )
    parser.add_argument("--fleet", type=Path,
                        help="a directory of repositories to sweep")
    parser.add_argument("--repo", action="append", default=[], type=Path,
                        help="one repository; repeatable, and it is measured")
    parser.add_argument("--declare-only", action="store_true",
                        help="read every floor and measure none; the audit's first pass")
    parser.add_argument("--ci-baselines", action="store_true",
                        help="also report BASELINE_* declared in ci/")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--log-dir", type=Path, help="where the gate logs are written")
    parser.add_argument("--cap-seconds", type=int, default=0,
                        help="an upper bound on every gate, overriding a declared "
                             "timeoutSeconds that is longer; a run this stops is a "
                             "reported row naming the bound, never a silent pass")
    arguments = parser.parse_args(argv)

    if not arguments.fleet and not arguments.repo:
        parser.error("one of --fleet or --repo is required")

    repos = [path.resolve() for path in arguments.repo]
    if arguments.fleet:
        repos.extend(fleet_repositories(arguments.fleet.resolve()))

    log_dir = arguments.log_dir or (
        Path(os.environ.get("TMPDIR") or "/tmp") / "floors-check")
    rows: list[dict[str, Any]] = []
    ci_rows: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for repo in repos:
        if repo in seen:
            continue
        seen.add(repo)
        if arguments.declare_only:
            for row in declared_floors(repo):
                row["measured"] = None
                row["verdict"] = NOT_MEASURED
                row["reason"] = "not measured: --declare-only was asked for"
                rows.append(row)
        else:
            rows.extend(measure_repository(repo, log_dir, arguments.cap_seconds))
        if arguments.ci_baselines:
            ci_rows.extend(workflow_baselines(repo))

    if arguments.json:
        print(json.dumps({"floors": rows, "ci-baselines": ci_rows}, indent=1))
    else:
        print(table(rows))
        if ci_rows:
            print("")
            print("CI baselines - a different comparator, in a different language:")
            for row in ci_rows:
                print(f"  {row['repo']}/{row['id']:<26} {row['declared']:>8}  {row['file']}")

    return 1 if any(row["verdict"] in (BELOW, ABOVE) for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())