#!/usr/bin/env bash

set -uo pipefail


interpreter_is_new_enough() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1
}

resolve_interpreter() {
  local candidate resolved
  if [ -n "${ANYWAYE_GATE_PYTHON:-}" ]; then
    if interpreter_is_new_enough "$ANYWAYE_GATE_PYTHON"; then
      printf '%s\n' "$ANYWAYE_GATE_PYTHON"
      return 0
    fi
    return 1
  fi
  for candidate in python3 python3.13 python3.12 python3.11 python; do
    resolved="$(command -v "$candidate" 2>/dev/null)" || continue
    if interpreter_is_new_enough "$resolved"; then
      printf '%s\n' "$resolved"
      return 0
    fi
  done
  return 1
}

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HARNESS="$ROOT/harness"
FIXTURE="$HARNESS/tests/fixtures/gates/conforming"
SELF="$HARNESS/tests/gate_self_test.sh"
ORIGINAL_PATH="$PATH"

PY="$(resolve_interpreter)" || PY=""
if [ -z "$PY" ]; then
  echo "gate_self_test: no python >= 3.11 found; set ANYWAYE_GATE_PYTHON" >&2
  exit 1
fi

if [ "${1:-}" = "--which-python" ]; then
  printf '%s\n' "$PY"
  exit 0
fi

if [ ! -d "$FIXTURE" ]; then
  echo "gate_self_test: the conforming fixture is missing at $FIXTURE" >&2
  exit 1
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/anywaye-gate-self-test.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

failures=0
breakages=0
red_cases=0
warn_cases=0
green_cases=0
spelling_cases=0
extractor_cases=0
colour_cases=0
leak_cases=0
search_cases=0
copy_name=""

fresh_copy() {
  copy_name="$1"
  local dst="$WORK/$copy_name"
  rm -rf "$dst"
  cp -R "$FIXTURE" "$dst"
  chmod +x "$dst/bin/gate"
  printf '%s' "$dst"
}

edit() {
  "$PY" - "$1" "$2" "$3" <<'PY'
import sys

path, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
body = open(path, encoding="utf-8").read()
if old not in body:
    sys.exit(f"gate_self_test: breakage no longer applies to {path}: {old!r} not found")
open(path, "w", encoding="utf-8").write(body.replace(old, new, 1))
PY
}

write() {
  cat > "$1"
}

expect_red() {
  local label="$1" repo="$2" expect="$3"
  local out
  out="$("$PY" "$HARNESS/gate_check.py" --prove --log-dir "$repo/.log" "$repo" 2>&1)"
  local code=$?
  if [ "$code" -ne 1 ]; then
    printf 'FAIL gate_self_test: %s — expected exit 1, got %s\n%s\n' "$label" "$code" "$out" >&2
    failures=$((failures + 1))
    return
  fi
  if ! printf '%s' "$out" | grep -q "$expect"; then
    printf 'FAIL gate_self_test: %s — went red as %s but never said %s\n%s\n' \
      "$label" "something else" "$expect" "$out" >&2
    failures=$((failures + 1))
    return
  fi
  red_cases=$((red_cases + 1))
  printf 'PASS gate_self_test: breakage %s: %s — caught by `%s`\n' "$breakages" "$label" "$expect"
}

expect_colour_red() {
  local label="$1" repo="$2" expect="$3"
  local out
  out="$("$PY" "$HARNESS/gate_check.py" --prove --log-dir "$repo/.log" "$repo" 2>&1)"
  local code=$?
  if [ "$code" -ne 1 ]; then
    printf 'FAIL gate_self_test: %s — expected exit 1, got %s\n%s\n' "$label" "$code" "$out" >&2
    failures=$((failures + 1))
    return
  fi
  if ! printf '%s' "$out" | grep -q "$expect"; then
    printf 'FAIL gate_self_test: %s — went red as %s but never said %s\n%s\n' \
      "$label" "something else" "$expect" "$out" >&2
    failures=$((failures + 1))
    return
  fi
  colour_cases=$((colour_cases + 1))
  printf 'PASS gate_self_test: colour red %s: %s — caught by `%s`\n' "$colour_cases" "$label" "$expect"
}

expect_green() {
  local label="$1" repo="$2"
  local out code
  out="$("$PY" "$HARNESS/gate_check.py" --prove --log-dir "$repo/.log" "$repo" 2>&1)"
  code=$?
  if [ "$code" -ne 0 ]; then
    printf 'FAIL gate_self_test: %s — expected green, got exit %s\n%s\n' "$label" "$code" "$out" >&2
    failures=$((failures + 1))
    return
  fi
  green_cases=$((green_cases + 1))
  printf 'PASS gate_self_test: green case %s: %s — matched in both phases\n' "$green_cases" "$label"
}

expect_warn() {
  local prove_it=""
  if [ "${1:-}" = "--prove" ]; then prove_it="--prove"; shift; fi
  local label="$1" repo="$2" expect="$3"
  local out
  out="$("$PY" "$HARNESS/gate_check.py" $prove_it --log-dir "$repo/.log" "$repo" 2>&1)"
  local code=$?
  if [ "$code" -ne 0 ]; then
    printf 'FAIL gate_self_test: %s — a warning moved the exit code to %s\n%s\n' \
      "$label" "$code" "$out" >&2
    failures=$((failures + 1))
    return
  fi
  if ! printf '%s' "$out" | grep -q "$expect"; then
    printf 'FAIL gate_self_test: %s — exited 0 without even printing %s\n%s\n' \
      "$label" "$expect" "$out" >&2
    failures=$((failures + 1))
    return
  fi
  warn_cases=$((warn_cases + 1))
  printf 'PASS gate_self_test: warning %s: %s — said `%s` and still exited 0\n' \
    "$warn_cases" "$label" "$expect"
}

expect_no_leak() {
  local label="$1" repo="$2" secret="$3"
  local out log
  out="$(DATABASE_URL="$secret" "$PY" "$HARNESS/gate_check.py" \
    --prove --log-dir "$repo/.log" "$repo" 2>&1)"
  local code=$?
  log="$(cat "$repo/.log/gate.log" 2>/dev/null || true)"
  if [ "$code" -ne 1 ]; then
    printf 'FAIL gate_self_test: %s — expected the leaky gate to be red, got %s\n' "$label" "$code" >&2
    failures=$((failures + 1))
  elif printf '%s' "$out" | grep -qF "$secret"; then
    printf 'FAIL gate_self_test: %s — the checker copied a value out of the gate environment into its own report\n' \
      "$label" >&2
    failures=$((failures + 1))
  elif ! printf '%s' "$log" | grep -qF "$secret"; then
    printf 'FAIL gate_self_test: %s — the gate log should hold the gate output; it does not, so the check above proved nothing\n' \
      "$label" >&2
    failures=$((failures + 1))
  else
    leak_cases=$((leak_cases + 1))
    printf 'PASS gate_self_test: the gate that leaked at runtime: the report stayed clean and the log held it\n'
  fi
}

expect_python_search() {
  local sense="$1" label="$2" bindir="$3" want="$4"
  local trace="$WORK/search-$search_cases.trace" errf="$WORK/search-$search_cases.err"
  local out err code real got
  real="$("$PY" -c 'import sys; print(sys.executable)')"
  if [ "$sense" = "override" ]; then
    out="$(ANYWAYE_GATE_PYTHON="$bindir/python3" ANYWAYE_FIXTURE_PYTHON="$real" \
      ANYWAYE_FIXTURE_TRACE="$trace" PATH="$ORIGINAL_PATH" \
      "${BASH:-bash}" "$SELF" --which-python 2>"$errf")"
  else
    out="$(ANYWAYE_GATE_PYTHON='' ANYWAYE_FIXTURE_PYTHON="$real" ANYWAYE_FIXTURE_TRACE="$trace" \
      PATH="$bindir:$ORIGINAL_PATH" "${BASH:-bash}" "$SELF" --which-python 2>"$errf")"
  fi
  code=$?
  err="$(cat "$errf" 2>/dev/null || true)"
  got="$(cat "$trace" 2>/dev/null || true)"

  if [ "$got" != "$want" ]; then
    printf 'FAIL gate_self_test: %s — consulted these candidates:\n%s\nexpected exactly:\n%s\n' \
      "$label" "${got:-<none — nothing was probed at all}" "$want" >&2
    printf '  it exited %s and answered with: %s\n' "$code" "${out:-<nothing>}" >&2
    failures=$((failures + 1))
    return
  fi

  refused() {
    local n="$1" want_out="$2"
    if [ "$code" -ne 1 ]; then
      printf 'FAIL gate_self_test: %s — exited %s, expected 1\n' "$n" "$code" >&2
      return 1
    fi
    if [ "$err" != 'gate_self_test: no python >= 3.11 found; set ANYWAYE_GATE_PYTHON' ]; then
      printf 'FAIL gate_self_test: %s — exited 1 without saying exactly why\n  said: [%s]\n' \
        "$n" "${err:-<nothing>}" >&2
      return 1
    fi
    if [ "$out" != "$want_out" ]; then
      printf 'FAIL gate_self_test: %s — stdout was [%s], expected [%s]\n' \
        "$n" "${out:-<nothing>}" "${want_out:-<nothing>}" >&2
      return 1
    fi
    return 0
  }

  case "$sense" in
    walks-on)
      if [ "$code" -ne 0 ]; then
        printf 'FAIL gate_self_test: %s — a PATH whose FIRST candidate is 3.9 but whose SECOND qualifies exited %s\n' \
          "$label" "$code" >&2
        failures=$((failures + 1))
        return
      fi
      if [ "$out" != "$bindir/python3.13" ]; then
        printf 'FAIL gate_self_test: %s — took %s, which is not the qualifying interpreter on this PATH (%s)\n' \
          "$label" "${out:-<nothing>}" "$bindir/python3.13" >&2
        failures=$((failures + 1))
        return
      fi
      if [ -n "$err" ]; then
        printf 'FAIL gate_self_test: %s — found an interpreter and still complained\n%s\n' \
          "$label" "$err" >&2
        failures=$((failures + 1))
        return
      fi
      ;;
    exhausted)
      if ! refused "$label" ''; then
        failures=$((failures + 1))
        return
      fi
      ;;
    override)
      if ! refused "$label" ''; then
        failures=$((failures + 1))
        return
      fi
      ;;
    *)
      printf 'FAIL gate_self_test: %s — bad sense %s\n' "$label" "$sense" >&2
      failures=$((failures + 1))
      return
      ;;
  esac
  search_cases=$((search_cases + 1))
  printf 'PASS gate_self_test: interpreter search %s: %s\n' "$search_cases" "$label"
}

write_case_workflow() {
  {
    printf 'name: ci\n\non: [push]\n\njobs:\n  gate:\n    runs-on: ubuntu-latest\n'
    printf '    steps:\n      - uses: actions/checkout@v7\n      - name: the gate\n'
    cat
  } > "$1/ci/ci.yml"
}

accepts() {
  local label="$1"
  local repo out code
  spelling_cases=$((spelling_cases + 1))
  repo="$(fresh_copy "accept-$spelling_cases")"
  write_case_workflow "$repo"
  out="$("$PY" "$HARNESS/gate_check.py" "$repo" 2>&1)"
  code=$?
  if [ "$code" -ne 0 ] || printf '%s' "$out" | grep -qE '^(FAIL|WARN) gate\.'; then
    printf 'FAIL gate_self_test: shape %s: %s — a workflow that plainly runs the gate was rejected (exit %s)\n%s\n' \
      "$spelling_cases" "$label" "$code" "$out" >&2
    failures=$((failures + 1))
    return
  fi
  printf 'PASS gate_self_test: shape %s: %s — accepted\n' "$spelling_cases" "$label"
}

accepts_whole() {
  local label="$1"
  local repo out code
  spelling_cases=$((spelling_cases + 1))
  repo="$(fresh_copy "whole-$spelling_cases")"
  cat > "$repo/ci/ci.yml"
  out="$("$PY" "$HARNESS/gate_check.py" "$repo" 2>&1)"
  code=$?
  if [ "$code" -ne 0 ] || printf '%s' "$out" | grep -qE '^(FAIL|WARN) gate\.'; then
    printf 'FAIL gate_self_test: shape %s: %s — a workflow that plainly runs the gate was rejected (exit %s)\n%s\n' \
      "$spelling_cases" "$label" "$code" "$out" >&2
    failures=$((failures + 1))
    return
  fi
  printf 'PASS gate_self_test: shape %s: %s — accepted\n' "$spelling_cases" "$label"
}

extracted() {
  local label="$1" sense="$2" needle="$3"
  local repo got
  extractor_cases=$((extractor_cases + 1))
  repo="$(fresh_copy "extract-$extractor_cases")"
  write_case_workflow "$repo"
  got="$("$PY" - "$HARNESS" "$repo" <<'PY' 2>&1
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import gate_check  # noqa: PLC0415 - the module under test, imported by path

repo = Path(sys.argv[2])
print("\n".join(gate_check.workflow_run_lines(repo, "ci/ci.yml")))
PY
)"
  case "$sense" in
    must)
      if printf '%s' "$got" | grep -qF -- "$needle"; then
        printf 'PASS gate_self_test: extractor %s: %s — read %s out of it, as it should\n' \
          "$extractor_cases" "$label" "$needle"
        return
      fi
      ;;
    must-not)
      if printf '%s' "$got" | grep -qF -- "$needle"; then
        printf 'FAIL gate_self_test: extractor %s: %s — read %s out of a run: that does not call it.\n%s\n' \
          "$extractor_cases" "$label" "$needle" "$got" >&2
        failures=$((failures + 1))
        return
      fi
      printf 'PASS gate_self_test: extractor %s: %s — did not invent %s, as it should not\n' \
        "$extractor_cases" "$label" "$needle"
      return
      ;;
    *)
      printf 'FAIL gate_self_test: extractor %s: %s — bad sense %s\n' \
        "$extractor_cases" "$label" "$sense" >&2
      failures=$((failures + 1))
      return
      ;;
  esac
  printf 'FAIL gate_self_test: extractor %s: %s — did not read %s out of it.\n%s\n' \
    "$extractor_cases" "$label" "$needle" "$got" >&2
  failures=$((failures + 1))
}

control="$(fresh_copy control)"
out="$("$PY" "$HARNESS/gate_check.py" --prove --log-dir "$control/.log" "$control" 2>&1)"
code=$?
if [ "$code" -ne 0 ]; then
  printf 'FAIL gate_self_test: the control — a repository whose declaration is true — did not come back green (exit %s)\n%s\n' \
    "$code" "$out" >&2
  failures=$((failures + 1))
else
  printf 'PASS gate_self_test: the control — a repository whose declaration is true — is green in both phases\n'
fi


breakages=$((breakages + 1))
one="$(fresh_copy no-declaration)"
rm -f "$one/gate.yml"
expect_red 'a repository that declares no gate at all' "$one" 'gate.declaration-missing'

breakages=$((breakages + 1))
two="$(fresh_copy command-missing)"
edit "$two/gate.yml" 'command: [bin/gate]' 'command: [bin/absent]'
expect_red 'a gate command naming a file this repository does not have' "$two" 'gate.command-missing'

breakages=$((breakages + 1))
two_a="$(fresh_copy entrypoint-missing)"
edit "$two_a/gate.yml" 'entrypoint: bin/gate' 'entrypoint: bin/absent'
expect_red 'a gate entrypoint this repository does not have, while the command still does' \
  "$two_a" 'gate.entrypoint-missing'

breakages=$((breakages + 1))
three="$(fresh_copy entrypoint-not-executable)"
chmod -x "$three/bin/gate"
expect_red 'a gate nobody is allowed to execute' "$three" 'gate.entrypoint-not-executable'

breakages=$((breakages + 1))
four="$(fresh_copy task-missing)"
edit "$four/gate.yml" 'miseTask: prime' 'miseTask: verify'
expect_red 'a mise task that is not in the mise config' "$four" 'gate.task-missing'

breakages=$((breakages + 1))
five="$(fresh_copy task-unresolvable)"
edit "$five/mise.toml" 'run = "bin/gate"' 'run = "bin/something-else"'
expect_red 'a mise task that resolves to a different file than the declaration names' \
  "$five" 'gate.task-unresolvable'

breakages=$((breakages + 1))
six="$(fresh_copy task-config-missing)"
rm -f "$six/mise.toml"
expect_red 'a mise task named in a repository that has no mise config' \
  "$six" 'gate.task-config-missing'

breakages=$((breakages + 1))
seven="$(fresh_copy false-green)"
write "$seven/bin/gate" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod +x "$seven/bin/gate"
expect_red 'a declaration that is entirely true about a gate that exited 0 without running anything' \
  "$seven" 'gate.proof-missing'

breakages=$((breakages + 1))
eight="$(fresh_copy floor)"
edit "$eight/gate.yml" 'minimum: 3' 'minimum: 40'
expect_red 'a gate that proves one test where the declaration promised forty' "$eight" 'gate.floor'

breakages=$((breakages + 1))
nine="$(fresh_copy nonzero)"
write "$nine/bin/gate" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
echo "2/3 passed"
echo "FAIL test_the_third_thing" >&2
exit 1
SH
chmod +x "$nine/bin/gate"
expect_red 'a gate that ran the suite, printed its proof, and failed' "$nine" 'gate.nonzero'

breakages=$((breakages + 1))
ten="$(fresh_copy ci-disagrees)"
edit "$ten/ci/ci.yml" 'bin/gate' 'echo "nothing here"'
expect_red 'a CI workflow that never runs the gate' "$ten" 'gate.ci-disagrees'

breakages=$((breakages + 1))
eleven="$(fresh_copy proof-uncompilable)"
edit "$eleven/gate.yml" "match: '^([0-9]+)/[0-9]+ passed\$'" "match: '^([0-9]+/[0-9]+ passed\$'"
expect_red 'a proof whose pattern does not compile, which would otherwise read as "no proof required"' \
  "$eleven" 'gate.schema'

breakages=$((breakages + 1))
twelve="$(fresh_copy requirement-empty)"
edit "$twelve/gate.yml" '  selfContained: true' '  selfContained: false'
expect_red 'a gate that says it is not self-contained and names no way to satisfy what it needs' \
  "$twelve" 'gate.schema'

breakages=$((breakages + 1))
thirteen="$(fresh_copy requirement-path-missing)"
edit "$thirteen/gate.yml" '  selfContained: true
  requirements: []' '  selfContained: false
  requirements:
    - kind: toolchain
      name: a venv builder that this repository does not carry
      satisfy:
        command: [bin/absent-setup]'
expect_red 'an external requirement satisfied by a file that is not in this repository' \
  "$thirteen" 'gate.requirement-path-missing'

breakages=$((breakages + 1))
fourteen="$(fresh_copy declaration-unreadable)"
edit "$fourteen/gate.yml" 'name: gate-fixture' 'name: &anchor gate-fixture'
expect_red 'a declaration using a YAML construct core'"'"'s reader refuses' \
  "$fourteen" 'gate.declaration-unreadable'

breakages=$((breakages + 1))
fifteen="$(fresh_copy command-unknown)"
edit "$fifteen/gate.yml" 'command: [bin/gate]' 'command: [gate-check-not-on-any-path]'
expect_warn 'a gate command that is a bare name this machine does not have' \
  "$fifteen" 'gate.command-unknown'

breakages=$((breakages + 1))
sixteen="$(fresh_copy task-unreadable)"
edit "$sixteen/mise.toml" 'run = "bin/gate"' 'run = "bin/gate | tee /dev/null"'
expect_warn 'a mise task whose run string is a pipeline, so only a shell could say what it runs' \
  "$sixteen" 'gate.task-unreadable'

breakages=$((breakages + 1))
seventeen="$(fresh_copy task-undeclared)"
edit "$seventeen/gate.yml" '  miseTask: prime
' ''
expect_warn 'a repository with mise tasks and a declaration that names none of them' \
  "$seventeen" 'gate.task-undeclared'

breakages=$((breakages + 1))
eighteen="$(fresh_copy ci-missing)"
edit "$eighteen/gate.yml" 'workflow: ci/ci.yml' 'workflow: ci/nope.yml'
expect_red 'a declaration naming a CI workflow that is not in this repository' \
  "$eighteen" 'gate.ci-missing'

breakages=$((breakages + 1))
nineteen="$(fresh_copy ci-undeclared)"
edit "$nineteen/gate.yml" 'ci:
  workflow: ci/ci.yml
  invokes: [bin/gate]
' ''
expect_warn 'a declaration that says nothing about CI' "$nineteen" 'gate.ci-undeclared'

breakages=$((breakages + 1))
twenty="$(fresh_copy requirement-unproven)"
edit "$twenty/gate.yml" '  selfContained: true
  requirements: []' '  selfContained: false
  requirements:
    - kind: toolchain
      name: a command on PATH that this checker deliberately did not run
      satisfy:
        command: [mise, install]'
expect_warn --prove 'an external requirement nobody ran, which is reported and never acted on' \
  "$twenty" 'gate.requirement-unproven'

breakages=$((breakages + 1))
twentyone="$(fresh_copy timeout)"
edit "$twentyone/gate.yml" 'timeoutSeconds: 60' 'timeoutSeconds: 1'
write "$twentyone/bin/gate" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
end=$(( SECONDS + 3 ))
while [ "$SECONDS" -lt "$end" ]; do
  :
done
echo "3/3 passed"
SH
chmod +x "$twentyone/bin/gate"
expect_red 'a gate that outlived the budget its own declaration gave it' "$twentyone" 'gate.timeout'

breakages=$((breakages + 1))
twentytwo="$(fresh_copy proof-unmeasurable)"
edit "$twentytwo/gate.yml" "match: '^([0-9]+)/[0-9]+ passed\$'" "match: '^[0-9]+/[0-9]+ passed\$'"
expect_red 'a proof with a floor and no capture group to read the floor from' \
  "$twentytwo" 'gate.proof-invalid'


accepts 'the block scalar, 101 of 139 keys in this fleet, gate on the second body line' <<'YAML'
        run: |
          set -euo pipefail
          bin/gate
YAML

accepts 'a one-line run with no ./ — gateway/ci.yml:65 spells the gate exactly this way' <<'YAML'
        run: bin/gate
YAML

accepts 'a one-line run with a leading ./ — parlor/ci.yml:81, and anywaye-rb before it worked around this' <<'YAML'
        run: ./bin/gate
YAML

accepts 'a one-line run carrying arguments and a quoted variable — kit:349, darkroom:172' <<'YAML'
        run: bin/gate --fail-under "$COVERAGE_FAIL_UNDER"
YAML

accepts 'a one-line run with a trailing comment, next to a comment that is not one — core:186' <<'YAML'
YAML

accepts 'the sequence-item spelling, - run:, which no workflow here writes yet' <<'YAML'
        - run: bin/gate
YAML

accepts 'a bare run: key whose value is on the lines below it' <<'YAML'
        run:
          bin/gate
YAML

accepts_whole 'gateway/ci.yml: a kit reusable-workflow job, and the gate as a one-liner' <<'YAML'
name: ci

on: [push]

jobs:
  ci:
    name: ci (kit)
    uses: anywaye/kit/ci/ci.reusable.yml@master
    with:
      language: bun
      working-dir: .
      versions: '{"bun":"1.3.12"}'

  prime:
    name: bin/prime
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: oven-sh/setup-bun@v2
        with:
          bun-version: "1.3.12"
      - name: bin/prime
        run: bin/gate
      - name: bun.lock is untouched
        run: |
          git diff --exit-code -- bun.lock \
            || { echo "bin/prime moved bun.lock — the gate is no longer frozen"; exit 1; }
YAML

accepts_whole 'parlor/ci.yml: the same shape, the gate spelled with a leading ./' <<'YAML'
name: ci

on: [push]

jobs:
  ci:
    name: ci (kit, node)
    uses: anywaye/kit/ci/ci.reusable.yml@master
    with:
      language: node
      working-dir: .
      versions: '{"node":"22.23.4"}'

  prime:
    name: bin/prime
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-node@v7
        with:
          node-version-file: package.json
      - name: the gate a developer runs
        run: ./bin/gate
      - name: the gate leaves package-lock.json alone
        run: git diff --exit-code -- package-lock.json
YAML

accepts_whole 'two invocations of one gate in one workflow — core/ci.yml:186 and :338' <<'YAML'
name: ci

on: [push]

jobs:
  gate:
    name: gate
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - name: the gate a developer runs
        shell: bash
        run: |
          set -euo pipefail
          bin/gate 2>&1 | tee "$RUNNER_TEMP/gate.log"
      - name: the pytest entry point, and that it agrees with the script one
        shell: bash
        run: |
          set -euo pipefail
          bin/gate --pytest 2>&1 | tee "$RUNNER_TEMP/pytest.log"
YAML


extracted 'a run: whose whole value is a comment' must-not 'bin/gate' <<'YAML'
YAML

extracted 'a run: whose whole value is a comment, at a different indent' must-not 'bin/gate' <<'YAML'
YAML

extracted 'a one-line run whose command is real, next to a comment about it' must 'bin/gate' <<'YAML'
YAML

extracted 'the block scalar, read through the same extractor' must 'bin/gate' <<'YAML'
        run: |
          set -euo pipefail
          bin/gate
YAML


accepts_whole 'indirect invocation through the task the declaration names — mise run prime' <<'YAML'
name: ci

on: [push]

jobs:
  gate:
    name: gate
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - name: the gate a developer runs
        run: mise run prime
YAML

accepts_whole 'the same through mise x --, and the gate named directly as well' <<'YAML'
name: ci

on: [push]

jobs:
  gate:
    name: gate
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - name: the gate a developer runs
        run: mise x -- bin/gate
YAML

breakages=$((breakages + 1))
twentythree="$(fresh_copy ci-wrapper-undeclared)"
edit "$twentythree/ci/ci.yml" 'bin/gate' 'make gate'
expect_warn 'a CI workflow that reaches the gate through a make target this checker cannot read' \
  "$twentythree" 'gate.ci-unproven'

breakages=$((breakages + 1))
twentyfour="$(fresh_copy ci-wrapper-unrelated-task)"
edit "$twentyfour/ci/ci.yml" 'bin/gate' 'make lint'
expect_warn 'a CI workflow whose only task invocation is unrelated, where this checker cannot tell a wrapper from a wrapper that was emptied' \
  "$twentyfour" 'gate.ci-unproven'

leak="$(fresh_copy secret-output)"
write "$leak/bin/gate" <<'SH'
#!/usr/bin/env bash
set -uo pipefail
echo "could not reach ${DATABASE_URL:-unset}"
echo "2/3 passed"
exit 1
SH
chmod +x "$leak/bin/gate"
expect_no_leak 'the gate that leaked at runtime' "$leak" \
  'postgres://gate:should-never-be-printed@localhost:5432/gate'


colour="$(fresh_copy colour-proof)"
edit "$colour/gate.yml" "match: '^([0-9]+)/[0-9]+ passed\$'" \
  "match: '^[ ]*Tests[ ]+([0-9]+) passed'"
edit "$colour/gate.yml" 'minimum: 3' 'minimum: 377'
write "$colour/bin/gate" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%b\n' '\033[2m      Tests \033[22m \033[1m\033[32m377 passed\033[39m\033[22m \033[90m(377)\033[39m'
SH
chmod +x "$colour/bin/gate"
expect_green 'a colourising gate whose proof matches once the escapes are stripped' "$colour"

swallow="$(fresh_copy colour-must-stay-red)"
write "$swallow/bin/gate" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%b\n' '\033[1;32m2\033[0m/4 \033[33msomething else entirely\033[0m'
exit 0
SH
chmod +x "$swallow/bin/gate"
expect_colour_red 'a proof that is genuinely absent from a gate that prints colour everywhere' \
  "$swallow" 'gate.proof-missing'

floorcolour="$(fresh_copy colour-floor)"
edit "$floorcolour/gate.yml" 'minimum: 3' 'minimum: 4'
write "$floorcolour/bin/gate" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%b\n' '\033[32m2\033[0m/4 \033[90mpassed\033[0m'
SH
chmod +x "$floorcolour/bin/gate"
expect_colour_red 'a suite below its floor, printed through a colourising runner' \
  "$floorcolour" 'gate.floor'

osc="$(fresh_copy colour-osc)"
edit "$osc/gate.yml" "match: '^([0-9]+)/[0-9]+ passed\$'" "match: '^Tests[ ]+([0-9]+) passed'"
write "$osc/bin/gate" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '\033]0;vitest run\007\033]8;;https://example.dev/tests\033\\Tests  377 passed\033]8;;\033\\'
printf '%s\n' ''
SH
chmod +x "$osc/bin/gate"
edit "$osc/gate.yml" 'minimum: 3' 'minimum: 377'
expect_green 'a proof on a line that also carries OSC title and hyperlink sequences' "$osc"

unterminated="$(fresh_copy colour-unterminated)"
edit "$unterminated/gate.yml" "match: '^([0-9]+)/[0-9]+ passed\$'" "match: '^Tests[ ]+([0-9]+) passed'"
write "$unterminated/bin/gate" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%b\n' 'INFO starting'
printf '\033]0;never-terminated'
printf '%s\n' ''
printf '%b\n' 'Tests  377 passed'
SH
chmod +x "$unterminated/bin/gate"
edit "$unterminated/gate.yml" 'minimum: 3' 'minimum: 377'
expect_green 'a proof that follows an unterminated OSC on the previous line' "$unterminated"

# --------------------------------------------------------------------------
# THE INTERPRETER SEARCH. The only three cases here about this script rather
# than about the checker, and they are here at the end for that reason:
# everything above needs an interpreter before it can start, so these are the
# last claims available to a run that found one.
#
# The defect, in the shape two of these reproduce. The candidate list is
#
#     python3  python3.13  python3.12  python3.11  python
#
# and the loop broke out of it on the first name that RESOLVED, then checked the
# version afterwards and gave up if that one was too old. A candidate that
# resolves is not a candidate that qualifies. On a machine whose `python3` is
# 3.9.6 the search therefore took 3.9.6, stopped, and printed "no python >= 3.11
# found" while 3.13 and 3.14 sat on the same PATH unused — a false negative in
# the project's own proof-of-failure, and one that is indistinguishable from a
# machine that genuinely has nothing. That is why it survived: the only way to
# see it is to be the developer whose `python3` is 3.9.6, and `bin/prime` and CI
# both export ANYWAYE_GATE_PYTHON or run on setup-python, so the escaped-into-
# silence was complete.
#
# All three live in harness/tests/fixtures/interpreter-path, so none of them
# depends on the machine running it — which is the whole reason the bug survived
# to be reported, restated as a fixture. The third pins the same interpreter the
# other two take, because the trap in fixing this is to make the search so eager
# that a deliberate override stops meaning anything.
# --------------------------------------------------------------------------

expect_python_search walks-on 'a PATH whose FIRST candidate is too old and whose SECOND qualifies — it walked on and took the qualifying one' \
  "$HARNESS/tests/fixtures/interpreter-path/stale-first/bin" \
  "$(printf 'python3\npython3.13')"

expect_python_search exhausted 'a PATH with no qualifying python at all — it walked all five candidates and exited 1 saying so' \
  "$HARNESS/tests/fixtures/interpreter-path/stale-only/bin" \
  "$(printf 'python3\npython3.13\npython3.12\npython3.11\npython')"

expect_python_search override 'a ANYWAYE_GATE_PYTHON that resolves and is too old — it is an error, not a reason to go looking for another one' \
  "$HARNESS/tests/fixtures/interpreter-path/stale-first/bin" \
  "$(printf 'python3')"


printf '\n'
printf 'gate_self_test — counts, reported separately so a green cannot hide one:\n'
printf '  breakages that went RED and named their finding : %s\n' "$red_cases"
printf '  warning cases that stayed GREEN                 : %s\n' "$warn_cases"
printf '  green cases that matched a colour-bearing gate  : %s\n' "$green_cases"
printf '  colour reds that still went red                 : %s\n' "$colour_cases"
printf '  real-workflow shapes that were ACCEPTED         : %s\n' "$spelling_cases"
printf '  extractor assertions (must / must-not)          : %s\n' "$extractor_cases"
printf '  the case that kept a secret out of the report   : %s\n' "$leak_cases"
printf '  interpreter searches that were MEASURED         : %s\n' "$search_cases"
printf '  the control (a true declaration, unbroken)      : 1\n'
printf '  SKIPPED                                         : 0\n'
printf '  (nothing here is conditional on the machine: no case skips, and a case\n'
printf '   that could not run would exit non-zero above rather than report a skip.)\n'
if [ "$failures" -ne 0 ]; then
  printf 'FAIL: gate_self_test — %s of %s breakages, %s warning cases, %s spellings accepted, %s colour-green cases, %s extractor assertions and %s colour reds the gate checker did not get right.\n' \
    "$failures" "$red_cases" "$warn_cases" "$spelling_cases" "$green_cases" "$extractor_cases" "$colour_cases"
  exit 1
fi
printf 'PASS: gate_self_test — %s breakages went red naming their finding, %s warning cases stayed green,\n' \
  "$red_cases" "$warn_cases"
printf '      %s real-workflow spellings were ACCEPTED, %s extractor assertions held,\n' \
  "$spelling_cases" "$extractor_cases"
printf '      %s green cases matched a colour-bearing gate, %s colour reds still went red, %s leak case held,\n' \
  "$green_cases" "$colour_cases" "$leak_cases"
printf '      %s interpreter searches were measured, the control is green, 0 skipped,\n' "$search_cases"
printf '      and the report carried no secret.\n'
