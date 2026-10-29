#!/usr/bin/env python3

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

FINDINGS: dict[str, tuple[str, str, str]] = {
    "framework-test.changeset-assertion": (
        "fail",
        "a test asserts on the framework's internal representation of a refusal "
        "— a changeset's errors, a changeset's error tuples — rather than on "
        "the product's observable refusal",
        "assert on what the caller sees: the refusal reason, the error message, "
        "or the fact that no row was written. The changeset is the framework's "
        "internal representation of the refusal, not the refusal itself",
    ),
    "framework-test.swoosh-adapter-assertion": (
        "fail",
        "a test asserts on a framework's test double — that the adapter was "
        "called, that it received a message, that it is configured, that a mock "
        "recorded the call — rather than on the product's observable effect",
        "assert on what the recipient sees: the email content, the delivery "
        "status, or the fact that a notification was recorded. The adapter is "
        "the framework's test double, not the product's behaviour",
    ),
    "framework-test.plug-pipeline-assertion": (
        "fail",
        "a test asserts on routing configuration — that a plug is in a "
        "pipeline, that a route exists in a route table, that a handler is "
        "mounted — rather than on the product's observable response",
        "assert on what the caller sees: the response status, the response body, "
        "or the refusal reason. The pipeline is the framework's routing "
        "mechanism, not the product's contract",
    ),
    "framework-test.repo-assertion": (
        "fail",
        "a test asserts on the framework's machinery — its database handle, its "
        "error types — as the primary assertion rather than as a setup step",
        "assert on what the caller sees: the API response, the observable side "
        "effect, or the persisted state through the product's own query "
        "interface. The framework's handle is not the product's behaviour",
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
    framework_patterns: tuple[Pattern, ...]
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
        note=(
            "Elixir's Ecto and Phoenix are the frameworks most likely to produce "
            "framework tests. The changeset is the framework's internal "
            "representation of a refusal; the pipeline is the framework's "
            "routing mechanism; the Repo is the framework's database handle. "
            "A test that asserts on any of these as the PRIMARY assertion is "
            "testing the framework, not the product. A test that drives the "
            "product and then observes the persisted row through Repo is a "
            "behaviour test, and one product assertion anywhere in the file "
            "keeps it green."
        ),
    ),
    Language(
        name="go",
        files=("**/*_test.go",),
        framework_patterns=(
            Pattern("framework-test.plug-pipeline-assertion", re.compile(r"assert.*route|assert.*handler|assert.*endpoint")),
        ),
        note=(
            "Go's testing package is minimal, so framework tests are less common. "
            "The main risk is asserting on routing wiring — that a route exists, "
            "that a handler is mounted — rather than on the response. Asserting "
            "on an error value is a judgment this checker stays silent on: a "
            "product sentinel and a framework error are spelled the same."
        ),
    ),
    Language(
        name="ruby",
        files=("test/**/*_test.rb", "test/*_test.rb", "spec/**/*_spec.rb", "spec/*_spec.rb"),
        framework_patterns=(
            Pattern("framework-test.plug-pipeline-assertion", re.compile(r"assert.*route|assert.*path.*_url|assert.*path.*_path")),
        ),
        note=(
            "Rails' routing is the framework most likely to produce a framework "
            "test: a route table that contains a path, a template that "
            "rendered, a mailer that recorded a delivery. Asserting on a model's "
            "own refusal — valid?, errors — is a behaviour test at the model "
            "level: the model is the product, and its errors are what a "
            "controller serializes into the 422."
        ),
    ),
    Language(
        name="python",
        files=("tests/**/*.py", "tests/*.py", "test/**/*.py", "test/*.py"),
        framework_patterns=(
            Pattern("framework-test.swoosh-adapter-assertion", re.compile(r"assert.*\bmock|assert.*\bpatch\b|assert.*\bspy")),
        ),
        note=(
            "pytest and FastAPI's TestClient are the frameworks most likely to "
            "produce framework tests. The main risk is asserting on the test "
            "double's machinery — that a mock was called, that a patch took — "
            "rather than on the response. Asserting on response.status_code or "
            "response.headers is a behaviour test: the status and the headers "
            "are what the caller sees."
        ),
    ),
    Language(
        name="typescript",
        files=("test/**/*.test.ts", "src/**/*.test.ts", "**/*.test.ts", "**/*.test.tsx"),
        framework_patterns=(
            Pattern("framework-test.plug-pipeline-assertion", re.compile(r"assert.*\.status|assert.*\.header")),
            Pattern("framework-test.plug-pipeline-assertion", re.compile(r"assert.*render|assert.*screen|assert.*getBy|assert.*queryBy")),
        ),
        note=(
            "Vitest and React Testing Library are the frameworks most likely to "
            "produce framework tests. The main risk is asserting on the "
            "rendering mechanism rather than on the rendered content. The "
            "expect(...) spelling is not pattern-matched, which is the silent "
            "direction."
        ),
    ),
    Language(
        name="rust",
        files=("tests/**/*.rs", "tests/*.rs", "src/**/*.rs", "src/*.rs"),
        framework_patterns=(
            Pattern("framework-test.repo-assertion", re.compile(r"assert.*\.is_err\(\)|assert.*\.is_ok\(\)")),
            Pattern("framework-test.repo-assertion", re.compile(r"assert.*\.unwrap\(\)|assert.*\.expect\(")),
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
        file_has_product_claim = False
        file_finding = ""
        framework_vars: dict[str, str] = {}
        for number, line in enumerate(code_lines, start=1):
            bare = strip_literals(line)
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
                    for var, finding in framework_vars.items():
                        if re.search(rf"\b{re.escape(var)}\b", bare):
                            report.framework_assertions.append(f"{relative}:{number}")
                            file_has_framework = True
                            file_finding = finding
                            line_finding = finding
                            break
                if not line_finding:
                    report.behaviour_assertions.append(f"{relative}:{number}")
                    file_has_product_claim = True
            else:
                for pattern in language.framework_patterns:
                    if pattern.regex.search(bare):
                        assigned = re.match(r"\s*([A-Za-z_]\w*)\s*=", bare)
                        if assigned:
                            framework_vars[assigned.group(1)] = pattern.finding
                        break
        if file_has_framework and not file_has_product_claim:
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
            lines.append("  ok   framework patterns found, and product assertions beside them")
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
