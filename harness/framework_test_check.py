#!/usr/bin/env python3
"""framework_test_check — does this test assert behaviour, or the framework?

    framework-test-check .                  # every service in the fleet
    framework-test-check ../identity        # one service
    framework-test-check . --json           # the same findings, as JSON
    framework-test-check . --explain        # every finding this checker can report

WHAT THIS IS FOR

The manager's standing bar: "Ensure our tests are behaviour tests, and that we
are not testing the framework." A behaviour test asserts what the PRODUCT does
for a caller — a response, an observable effect, a persisted row, a refusal
with a reason. A framework test asserts that a LIBRARY is configured — that a
plug is in a pipeline, that Ecto.Changeset produced an error tuple, that a
route table contains a path, that a template rendered, that Swoosh.Adapters.Test
received mail.

The seam is whether the assertion is about the product's contract or about
the library's internals. A test that uses Swoosh.Adapters.Test to assert the
notice reached the person at the right address with a working link is a
behaviour test using a framework's test double.

THE TWO FAILURE MODES

1. A test that cannot fail for the reason it names. It passes while the product
   is wrong, because it is asserting the library did something rather than the
   product did something.
2. A test that breaks on a library upgrade for no product reason. It is coupled
   to the framework's internal representation rather than to the product's
   observable contract.

WHAT THIS CHECKER CAN AND CANNOT SEE

It reads source, so it can only see what is written down. It can flag a test
file that asserts nothing but a framework's own behaviour — a test whose only
assertions are on the framework's internal types or configuration. It CANNOT
tell a behaviour test that uses a test double from a framework test. That
distinction requires a human judgment about what the assertion means, not just
what it says.

So this checker is deliberately conservative. It flags the mechanical cases —
a test file that asserts only on framework internals — and stays silent on the
ones that require judgment. A checker that flags legitimate tests is worse than
no checker: it teaches people to ignore it.

THE EXIT CODES, WHICH ARE THE WHOLE CONTRACT

  0   no failure. Warnings may still have been printed; see below.
  1   at least one failure — a test file asserts only framework behaviour.
  2   the check could not happen. Never 0, and never collapsed into 1.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_CANNOT_RUN = 2

#: The findings this checker can report, and nothing else. Mirrored in
#: `harness/framework_test_findings.json` and asserted equal in both directions
#: by core's suite, for the same reason as every other checker: a finding
#: nobody was told about is a finding that will be wrong the first time
#: somebody needs it.
FINDINGS: dict[str, tuple[str, str, str]] = {
    "framework-test.changeset-assertion": (
        "fail",
        "a test asserts on Ecto.Changeset internals — changeset.errors, "
        "Ecto.Changeset.traverse_errors, or a pattern match on %Ecto.Changeset{} — "
        "rather than on the product's observable refusal",
        "assert on what the caller sees: the refusal reason, the error message, "
        "or the fact that no row was written. The changeset is the framework's "
        "internal representation of the refusal, not the refusal itself",
    ),
    "framework-test.swoosh-adapter-assertion": (
        "fail",
        "a test asserts on Swoosh.Adapters.Test configuration or behaviour — "
        "that the adapter was called, that it received mail, or that it is "
        "configured — rather than on the product's observable effect",
        "assert on what the recipient sees: the email content, the delivery "
        "status, or the fact that a notification was recorded. The adapter is "
        "the framework's test double, not the product's behaviour",
    ),
    "framework-test.plug-pipeline-assertion": (
        "fail",
        "a test asserts on plug pipeline configuration — that a plug is in a "
        "pipeline, that a route exists, or that a pipeline macro expanded — "
        "rather than on the product's observable response",
        "assert on what the caller sees: the response status, the response body, "
        "or the refusal reason. The pipeline is the framework's routing "
        "mechanism, not the product's contract",
    ),
    "framework-test.repo-assertion": (
        "fail",
        "a test asserts on Repo internals — Repo.get, Repo.all, Repo.aggregate, "
        "Repo.delete_all — as the primary assertion rather than as a setup step",
        "assert on what the caller sees: the API response, the observable side "
        "effect, or the persisted state through the product's own query "
        "interface. Repo is the framework's database handle, not the product's "
        "behaviour",
    ),
}


@dataclass(frozen=True)
class Pattern:
    """A framework pattern and the finding it maps to."""

    finding: str
    regex: re.Pattern


@dataclass(frozen=True)
class Language:
    """How one language's tests are recognised, and what framework patterns to look for."""

    name: str
    files: tuple[str, ...]
    #: Patterns that indicate a framework test. Each maps to a specific finding.
    framework_patterns: tuple[Pattern, ...]
    #: Patterns that indicate a behaviour test using a framework's test double.
    #: These are the legitimate uses that must NOT be flagged.
    behaviour_patterns: tuple[re.Pattern, ...]
    note: str = ""


LANGUAGES: tuple[Language, ...] = (
    Language(
        name="elixir",
        files=("test/**/*_test.exs", "test/*_test.exs"),
        framework_patterns=(
            Pattern("framework-test.changeset-assertion", re.compile(r"changeset\.errors")),
            Pattern("framework-test.changeset-assertion", re.compile(r"Ecto\.Changeset\.traverse_errors")),
            Pattern("framework-test.changeset-assertion", re.compile(r"%Ecto\.Changeset\{\}")),
            Pattern("framework-test.swoosh-adapter-assertion", re.compile(r"Swoosh\.Adapters\.Test\.deliver")),
            Pattern("framework-test.plug-pipeline-assertion", re.compile(r"plug.*pipeline|pipeline.*plug|__pipelines__", re.IGNORECASE)),
            Pattern("framework-test.repo-assertion", re.compile(r"assert\s+Repo\.|refute\s+Repo\.")),
        ),
        behaviour_patterns=(
            # A test that uses Swoosh.Adapters.Test to assert the EMAIL CONTENT
            # is a behaviour test using a test double. The assertion is on what
            # the recipient sees, not on the adapter.
            re.compile(r"assert_email_sent"),
            re.compile(r"assert.*email.*body|assert.*email.*subject|assert.*email.*to"),
            # A test that uses Repo to SET UP a fixture is not asserting on the
            # database — it is arranging state.
            re.compile(r"Repo\.insert|Repo\.insert!"),
        ),
        note=(
            "Elixir's Ecto and Phoenix are the frameworks most likely to produce "
            "framework tests. The changeset is the framework's internal "
            "representation of a refusal; the pipeline is the framework's "
            "routing mechanism; the Repo is the framework's database handle. "
            "A test that asserts on any of these as the PRIMARY assertion is "
            "testing the framework, not the product."
        ),
    ),
    Language(
        name="go",
        files=("**/*_test.go",),
        framework_patterns=(
            Pattern("framework-test.repo-assertion", re.compile(r"assert.*\.Error|assert.*err\s*!=\s*nil|assert.*err\s*==\s*nil")),
            Pattern("framework-test.plug-pipeline-assertion", re.compile(r"assert.*route|assert.*handler|assert.*endpoint")),
        ),
        behaviour_patterns=(
            re.compile(r"assert.*err.*Error\(\)|assert.*err\.Error\(\)"),
            re.compile(r"assert.*strings\.Contains.*err"),
        ),
        note=(
            "Go's testing package is minimal, so framework tests are less common. "
            "The main risk is asserting on error types rather than error messages."
        ),
    ),
    Language(
        name="ruby",
        files=("test/**/*_test.rb", "test/*_test.rb", "spec/**/*_spec.rb", "spec/*_spec.rb"),
        framework_patterns=(
            Pattern("framework-test.changeset-assertion", re.compile(r"assert.*\.errors|assert.*\.valid\?|assert.*\.changes")),
            Pattern("framework-test.plug-pipeline-assertion", re.compile(r"assert.*route|assert.*path.*_url|assert.*path.*_path")),
        ),
        behaviour_patterns=(
            re.compile(r"assert.*errors\.on\?|assert.*errors\.full_messages"),
            re.compile(r"create\(|build\(|build_stubbed\("),
        ),
        note=(
            "Rails' ActiveSupport::Test and RSpec are the frameworks most likely "
            "to produce framework tests. The main risk is asserting on "
            "ActiveRecord::Errors internals or on route helpers."
        ),
    ),
    Language(
        name="python",
        files=("tests/**/*.py", "tests/*.py", "test/**/*.py", "test/*.py"),
        framework_patterns=(
            Pattern("framework-test.repo-assertion", re.compile(r"assert.*\.status_code|assert.*\.headers")),
            Pattern("framework-test.repo-assertion", re.compile(r"assert.*mock|assert.*patch|assert.*spy")),
        ),
        behaviour_patterns=(
            re.compile(r"assert.*response\.json|assert.*response\.text"),
            re.compile(r"assert.*result|assert.*output|assert.*value"),
        ),
        note=(
            "pytest and FastAPI's TestClient are the frameworks most likely to "
            "produce framework tests. The main risk is asserting on the response "
            "object's internals rather than on the response content."
        ),
    ),
    Language(
        name="typescript",
        files=("test/**/*.test.ts", "src/**/*.test.ts", "**/*.test.ts", "**/*.test.tsx"),
        framework_patterns=(
            Pattern("framework-test.plug-pipeline-assertion", re.compile(r"assert.*\.status|assert.*\.header")),
            Pattern("framework-test.plug-pipeline-assertion", re.compile(r"assert.*render|assert.*screen|assert.*getBy|assert.*queryBy")),
        ),
        behaviour_patterns=(
            re.compile(r"assert.*textContent|assert.*innerHTML|assert.*content"),
            re.compile(r"expect.*toBe|expect.*toEqual|expect.*toMatch"),
        ),
        note=(
            "Vitest and React Testing Library are the frameworks most likely to "
            "produce framework tests. The main risk is asserting on the "
            "rendering mechanism rather than on the rendered content."
        ),
    ),
    Language(
        name="rust",
        files=("tests/**/*.rs", "tests/*.rs", "src/**/*.rs", "src/*.rs"),
        framework_patterns=(
            Pattern("framework-test.repo-assertion", re.compile(r"assert.*\.is_err\(\)|assert.*\.is_ok\(\)")),
            Pattern("framework-test.repo-assertion", re.compile(r"assert.*\.unwrap\(\)|assert.*\.expect\(")),
        ),
        behaviour_patterns=(
            re.compile(r"assert.*err\.to_string|assert.*err\.Display"),
            re.compile(r"assert.*result|assert.*output"),
        ),
        note=(
            "Rust's std::test is minimal, so framework tests are less common. "
            "The main risk is asserting on Result types rather than on the "
            "underlying values."
        ),
    ),
)


def strip_literals(line: str) -> str:
    """Return `line` with string literals and trailing comments removed."""
    without_strings = re.sub(r'r#"(.*?)"#|"""(.*?)"""|"(.*?)"|\'(.*?)\'', "", line)
    without_strings = re.sub(r"^\s*//[/!]?", "", without_strings)
    return without_strings.split("//")[0].split("#")[0].split("--")[0]


def strip_comments(text: str) -> list[str]:
    """Return `text`'s lines with every comment removed, blanked in place."""
    out: list[str] = []
    in_block = False
    for line in text.splitlines():
        if in_block:
            out.append("")
            if "*/" in line:
                in_block = False
            continue
        if line.lstrip().startswith("/*"):
            out.append("")
            if "*/" not in line:
                in_block = True
            continue
        head = re.split(r"//|/\*|#(?![{])", line, maxsplit=1)[0]
        out.append(head if head.strip() else "")
    return out


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


@dataclass
class ServiceReport:
    """One service's verdict, with the framework patterns found."""

    name: str
    path: str
    language: str = ""
    framework_assertions: list[str] = field(default_factory=list)
    behaviour_assertions: list[str] = field(default_factory=list)
    files_with_framework_tests: list[str] = field(default_factory=list)
    finding_for_file: dict[str, str] = field(default_factory=dict)

    @property
    def verdict(self) -> tuple[str, str]:
        """(finding id, severity) or ("", "") when there is nothing to report."""
        if self.files_with_framework_tests:
            # Return the finding for the first flagged file
            first_file = self.files_with_framework_tests[0]
            finding_id = self.finding_for_file.get(first_file, "framework-test.changeset-assertion")
            return (finding_id, "fail")
        return ("", "")


def detect_language(repo: Path) -> Language | None:
    """The language whose test files this repository has, from its manifest."""
    if (repo / "Cargo.toml").is_file():
        return next(l for l in LANGUAGES if l.name == "rust")
    if (repo / "go.mod").is_file():
        return next(l for l in LANGUAGES if l.name == "go")
    if (repo / "mix.exs").is_file():
        return next(l for l in LANGUAGES if l.name == "elixir")
    if (repo / "Gemfile").is_file():
        return next(l for l in LANGUAGES if l.name == "ruby")
    if (repo / "pyproject.toml").is_file():
        return next(l for l in LANGUAGES if l.name == "python")
    if (repo / "package.json").is_file():
        return next(l for l in LANGUAGES if l.name == "typescript")
    return None


def test_files(repo: Path, language: Language) -> list[Path]:
    found: list[Path] = []
    for pattern in language.files:
        found.extend(p for p in repo.glob(pattern) if p.is_file())
    skip = {"node_modules", "target", "_build", ".venv", "__pycache__", "dist", "vendor", "deps"}
    return sorted({p for p in found if not skip & set(p.parts)})


def scan_service(repo: Path, language: Language) -> ServiceReport:
    report = ServiceReport(name=repo.name, path=str(repo), language=language.name)
    files = test_files(repo, language)
    if not files:
        return report

    for path in files:
        relative = str(path.relative_to(repo))
        text = read_text(path)
        if not text:
            continue
        code_lines = strip_comments(text)
        file_has_framework = False
        file_has_behaviour = False
        file_finding = ""
        # Variables assigned from a framework-pattern call, and the finding
        # that call maps to. An assertion that mentions one of these is an
        # assertion ABOUT the framework's internal representation even when
        # the framework token itself sits on the setup line — the seam is
        # what the assertion is about, not which line the token is on.
        framework_vars: dict[str, str] = {}
        for number, line in enumerate(code_lines, start=1):
            bare = strip_literals(line)
            # Check if this is an assertion line
            is_assertion = bool(re.search(r"\bassert\b|\brefute\b", bare))
            if is_assertion:
                line_finding = ""
                for pattern in language.framework_patterns:
                    if pattern.regex.search(bare):
                        report.framework_assertions.append(f"{relative}:{number}")
                        file_has_framework = True
                        file_finding = pattern.finding
                        line_finding = pattern.finding
                        break
                if not line_finding:
                    # No framework token on the assertion line itself. The
                    # assertion may still be about one: `pipeline =
                    # Router.__pipelines__()` followed by `assert :ok in
                    # pipeline` asserts on the pipeline — the framework's
                    # internal representation — reached through a variable.
                    for var, finding in framework_vars.items():
                        if re.search(rf"\b{re.escape(var)}\b", bare):
                            report.framework_assertions.append(f"{relative}:{number}")
                            file_has_framework = True
                            file_finding = finding
                            break
                for pattern in language.behaviour_patterns:
                    if pattern.search(bare):
                        report.behaviour_assertions.append(f"{relative}:{number}")
                        file_has_behaviour = True
                        break
            else:
                # Non-assertion line: check for behaviour patterns (setup steps)
                for pattern in language.behaviour_patterns:
                    if pattern.search(bare):
                        report.behaviour_assertions.append(f"{relative}:{number}")
                        file_has_behaviour = True
                        break
                for pattern in language.framework_patterns:
                    if pattern.regex.search(bare):
                        # A setup line that calls a framework pattern records
                        # its variable, so a later assertion mentioning it is
                        # recognised as an assertion about the framework.
                        assigned = re.match(r"\s*([A-Za-z_]\w*)\s*=", bare)
                        if assigned:
                            framework_vars[assigned.group(1)] = pattern.finding
                        break
        if file_has_framework and not file_has_behaviour:
            report.files_with_framework_tests.append(relative)
            report.finding_for_file[relative] = file_finding

    return report


def services_in(root: Path) -> list[Path]:
    """Every service under `root`, skipping the ones that own no tests."""
    if detect_language(root) is not None:
        return [root]
    found = []
    for candidate in sorted(root.iterdir()):
        if candidate.is_dir() and candidate.name not in {".git", "node_modules"}:
            if detect_language(candidate) is not None:
                found.append(candidate)
    return found


def check(root: Path) -> list[ServiceReport]:
    reports = []
    for repo in services_in(root):
        language = detect_language(repo)
        if language is None:
            continue
        report = scan_service(repo, language)
        if report.framework_assertions:
            reports.append(report)
    return reports


def render(reports: list[ServiceReport]) -> str:
    if not reports:
        return (
            "framework-test-check: no service with framework test patterns was found.\n"
            "  A service with tests and no framework patterns cannot have this defect;\n"
            "  that is a finding, not an absence of one."
        )
    lines: list[str] = []
    failures = 0
    for report in reports:
        identifier, severity = report.verdict
        if identifier:
            failures += 1
        lines.append(f"{report.name}  ({report.language})")
        lines.append(f"  framework assertions: {len(report.framework_assertions)}")
        lines.append(f"  behaviour assertions: {len(report.behaviour_assertions)}")
        if report.files_with_framework_tests:
            lines.append(f"  FAIL {identifier} [{severity}]")
            lines.append(f"       {FINDINGS[identifier][1]}")
            lines.append(f"       fix: {FINDINGS[identifier][2]}")
            lines.append(f"  files with framework tests:")
            for f in report.files_with_framework_tests:
                lines.append(f"    {f}")
        else:
            lines.append("  ok   framework patterns found but behaviour patterns also present")
    lines.append("")
    lines.append(f"{failures} failure(s)")
    return "\n".join(lines)


def to_json(reports: list[ServiceReport]) -> str:
    payload = []
    for report in reports:
        identifier, severity = report.verdict
        payload.append(
            {
                "service": report.name,
                "language": report.language,
                "framework_assertions": report.framework_assertions,
                "behaviour_assertions": report.behaviour_assertions,
                "files_with_framework_tests": report.files_with_framework_tests,
                "finding": identifier,
                "severity": severity,
            }
        )
    return json.dumps({"services": payload}, indent=2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="framework-test-check",
        description="Does this test assert behaviour, or the framework?",
    )
    parser.add_argument("repo", nargs="?", default=".", help="a service, or a fleet root")
    parser.add_argument("--json", action="store_true", help="emit the findings as JSON")
    parser.add_argument("--explain", action="store_true", help="list every finding")
    arguments = parser.parse_args(argv)

    if arguments.explain:
        for identifier in sorted(FINDINGS):
            severity, claim, remediate = FINDINGS[identifier]
            print(f"{identifier}  [{severity}]\n  {claim}\n  fix: {remediate}")
        return EXIT_OK

    root = Path(arguments.repo)
    if not root.is_dir():
        print(f"framework-test-check: {root} is not a directory", file=sys.stderr)
        return EXIT_CANNOT_RUN

    reports = check(root)
    print(to_json(reports) if arguments.json else render(reports))
    return EXIT_FINDINGS if any(r.verdict[0] for r in reports) else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
