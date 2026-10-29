#!/usr/bin/env bash
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
harness_dir="$(dirname "$here")"
core="$(dirname "$harness_dir")"
checker="$core/harness/framework_test_check.py"
fixtures="$here/fixtures"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

python="$(command -v python3 || true)"
if [ -z "$python" ]; then
  echo "framework_test_self_test.sh: python3 not found on PATH — cannot run the checker" >&2
  exit 2
fi

pass=0
fail=0

note() { printf '\n--- %s\n' "$1"; }

expect_red() {
  local label="$1" expect="$2" output status
  output="$("$python" "$checker" "$work/$label" 2>&1)"
  status=$?
  if [ "$status" -eq 0 ]; then
    printf '  RED EXPECTED, GOT CLEAN  %s\n' "$label"
    printf '%s\n' "$output" | sed 's/^/    /'
    fail=$((fail + 1))
    return
  fi
  if ! printf '%s' "$output" | grep -q "$expect"; then
    printf '  WRONG FINDING            %s (wanted %s)\n' "$label" "$expect"
    printf '%s\n' "$output" | sed 's/^/    /'
    fail=$((fail + 1))
    return
  fi
  printf '  red, and named           %s -> %s\n' "$label" "$expect"
  pass=$((pass + 1))
}

expect_clean() {
  local label="$1" output status
  output="$("$python" "$checker" "$work/$label" 2>&1)"
  status=$?
  if [ "$status" -ne 0 ]; then
    printf '  CLEAN EXPECTED, GOT RED  %s\n' "$label"
    printf '%s\n' "$output" | sed 's/^/    /'
    fail=$((fail + 1))
    return
  fi
  printf '  clean                    %s\n' "$label"
  pass=$((pass + 1))
}

fresh() {
  rm -rf "$work/$2"
  cp -R "$fixtures/$1" "$work/$2"
}

for required in elixir_service go_service ruby_service python_service typescript_service rust_service; do
  if [ ! -d "$fixtures/$required" ]; then
    echo "framework_test_self_test.sh: the fixture $fixtures/$required is missing." >&2
    echo "  Without a known shape to break, every red below proves nothing: a" >&2
    echo "  checker that refused everything would satisfy all of them." >&2
    exit 2
  fi
done

note "control: the safe fixture, unbroken, which must be CLEAN"
fresh elixir_service control
expect_clean control

note "case 1: a test that asserts on changeset.errors — a framework test"
fresh elixir_service changeset_framework
cat > "$work/changeset_framework/test/framework_test.exs" <<'EXS'
defmodule FrameworkTest do
  use ExUnit.Case

  test "asserts on changeset internals" do
    changeset = Ecto.Changeset.change(%User{}, email: "bad")
    assert Enum.any?(changeset.errors, fn {key, _} -> key == :email end)
  end
end
EXS
expect_red changeset_framework "framework-test.changeset-assertion"

note "case 2: a test that asserts on Swoosh.Adapters.Test — a framework test"
fresh elixir_service swoosh_framework
cat > "$work/swoosh_framework/test/framework_test.exs" <<'EXS'
defmodule FrameworkTest do
  use ExUnit.Case

  test "asserts on the adapter" do
    email = Swoosh.Email.new(to: "user@example.com", subject: "Hello")
    assert Swoosh.Adapters.Test.deliver(email, []) == {:ok, %{}}
  end
end
EXS
expect_red swoosh_framework "framework-test.swoosh-adapter-assertion"

note "case 3: a test that asserts on plug pipeline configuration — a framework test"
fresh elixir_service plug_framework
cat > "$work/plug_framework/test/framework_test.exs" <<'EXS'
defmodule FrameworkTest do
  use ExUnit.Case

  test "asserts on pipeline" do
    pipeline = MyApp.Router.__pipelines__()
    assert :authenticated in pipeline
  end
end
EXS
expect_red plug_framework "framework-test.plug-pipeline-assertion"

note "case 4: a test that asserts on Repo.get as the primary assertion"
fresh elixir_service repo_framework
cat > "$work/repo_framework/test/framework_test.exs" <<'EXS'
defmodule FrameworkTest do
  use ExUnit.Case

  test "asserts on Repo" do
    assert Repo.get(User, 1).name == "Alice"
  end
end
EXS
expect_red repo_framework "framework-test.repo-assertion"

note "case 5 (negative control): a behaviour test USING Swoosh.Adapters.Test"
fresh elixir_service swoosh_behaviour
cat > "$work/swoosh_behaviour/test/behaviour_test.exs" <<'EXS'
defmodule BehaviourTest do
  use ExUnit.Case

  test "asserts on the email content, not the adapter" do
    email = Swoosh.Email.new(to: "user@example.com", subject: "Hello")
    Swoosh.Adapters.Test.deliver(email, [])
    assert_email_sent(to: "user@example.com", subject: "Hello")
  end
end
EXS
expect_clean swoosh_behaviour

note "case 6 (negative control): a behaviour test USING Repo for setup"
fresh elixir_service repo_behaviour
cat > "$work/repo_behaviour/test/behaviour_test.exs" <<'EXS'
defmodule BehaviourTest do
  use ExUnit.Case

  test "asserts on the response, not the database" do
    user = Repo.insert!(%User{name: "Alice"})
    response = MyApp.Users.get_user(user.id)
    assert response.name == "Alice"
  end
end
EXS
expect_clean repo_behaviour

note "case 7 (negative control): a behaviour test USING Ecto.Changeset.change"
fresh elixir_service changeset_behaviour
cat > "$work/changeset_behaviour/test/behaviour_test.exs" <<'EXS'
defmodule BehaviourTest do
  use ExUnit.Case

  test "asserts on the refusal, not the changeset" do
    changeset = Ecto.Changeset.change(%User{}, email: "bad")
    assert {:error, _} = MyApp.Users.create_user(changeset)
  end
end
EXS
expect_clean changeset_behaviour

printf '\n%s passed, %s failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
