#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_COULD_NOT_RUN = 2

DEFAULT_BASE = "https://docs.anywaye.com/errors"

DEFAULT_TIMEOUT = 5.0

DEFAULT_SAMPLE = 25


class _Result:

    def __init__(self, uri: str, status: int | None, detail: str) -> None:
        self.uri = uri
        self.status = status
        self.detail = detail

    @property
    def resolved(self) -> bool:
        return self.status == 200


def _contract_module():
    try:
        import anywaye_contract
    except ModuleNotFoundError as _missing:  # pragma: no cover - travels together
        raise SystemExit(
            f"errors-resolve: cannot import anywaye_contract from "
            f"{Path(__file__).resolve().parent}: {_missing}. The harness travels whole; a copy "
            f"of one without the other would be a second YAML dialect and a second "
            f"`type` base."
        )
    return anywaye_contract


def read_types(service: Path, core: Path) -> list[str]:
    """Every distinct problem `type` URI the service's document publishes.

    Read through `anywaye_contract`'s own scan, for the reason `ERROR_TYPE_BASE`
    is: one reader, one set of rules about what an example is. This module
    decides *whether the URIs resolve*; it does not decide what a URI is.

    The order is the document's own, not sorted, and the list is deduplicated
    keeping first appearance — so a reader looking at a report sees the codes
    in the order the document defines them and not an alphabetical shuffle
    that loses which one 404'd first.
    """
    contract = _contract_module()
    manifest_path = service / "anywaye.yml"
    if not manifest_path.is_file():
        raise _Refusal(
            "errors.manifest-absent",
            str(manifest_path),
            "this is not a service repository, so there is no document to read "
            "`type` URIs from",
        )
    manifest = contract.read_yaml(manifest_path.read_text(encoding="utf-8"), manifest_path)
    if not isinstance(manifest, dict):
        raise _Refusal(
            "yaml.unsupported", str(manifest_path), "a manifest must be a mapping at the top level"
        )
    reference = (manifest.get("exposes") or {}).get("api")
    if not isinstance(reference, str) or not reference:
        raise _Refusal(
            "errors.no-document",
            "anywaye.yml: exposes/api",
            "the manifest declares no exposes.api, so no problem example exists "
            "to read a `type` from. A service with no HTTP surface has no error "
            "URIs, and reporting 0 over it would say the page tree is complete "
            "about a document that named nothing",
        )
    path = service / reference
    if not path.is_file():
        raise _Refusal(
            "errors.document-missing",
            str(path),
            f"exposes.api names {reference!r} and there is no such file",
        )
    document = contract.read_yaml(path.read_text(encoding="utf-8"), path)
    if not isinstance(document, dict):
        raise _Refusal("yaml.unsupported", str(path), "an OpenAPI document must be a mapping")
    scan = contract._openapi_scan(document, reference)
    if scan.unresolved:
        raise _Refusal(
            "errors.unreadable-document",
            str(path),
            f"{len(scan.unresolved)} reference(s) in the document could not be followed, "
            "so the problem examples behind them were never read. Checking the URIs that "
            "were readable would report the page tree as complete about the half that "
            "was not",
        )
    seen: list[str] = []
    for operation in scan.operations:
        for status, response, decided in operation.responses:
            if contract._is_success(status) or not decided:
                continue
            for body in contract._problem_examples(response):
                declared = body.get("type")
                if isinstance(declared, str) and declared and declared not in seen:
                    seen.append(declared)
    if not seen:
        raise _Refusal(
            "errors.no-examples",
            str(path),
            "the document carries no problem example with a `type`, so there is "
            "no URI for this check to fetch. A green over that would be a "
            "statement about a page nobody linked",
        )
    return seen


class _Refusal(Exception):

    def __init__(self, rule: str, where: str, detail: str) -> None:
        super().__init__(detail)
        self.rule = rule
        self.where = where
        self.detail = detail


def normalise_base(base: str) -> str:
    """The base with exactly one trailing slash, or a refusal.

    "No host, ever" does not apply here — this is the one host the plan freezes.
    What does apply is that a base spelled with or without the slash must mean
    the same thing, because the same run in two places must fetch the same
    URIs. `https://docs.anywaye.com/errors` and
    `https://docs.anywaye.com/errors/` are the same page tree and a local mirror
    spelled either way must not change the answer.
    """
    text = base.strip().rstrip("/")
    if not text:
        raise _Refusal(
            "errors.base-empty",
            "--base / ANYWAYE_ERRORS_BASE_URL",
            "the base URL is empty, so there is nothing to fetch. An empty base "
            "is not a mirror at the root",
        )
    if "://" not in text:
        scheme = "http" if text.startswith(("127.", "localhost", "[::1]")) else "https"
        text = f"{scheme}://{text}"
    return text


def retarget(uri: str, base: str) -> str:
    """The document's URI, rewritten onto the base being fetched.

    **This is the whole reason `--base` exists, and it is a substitution and
    not a prefix.** A service's document publishes
    `https://docs.anywaye.com/errors/validation_failed`, because that is what
    the frozen base says it must publish. Against a local docs mirror that
    URI is wrong twice over: it reaches out to the network the live tier is
    supposed to replace, and it does it for a page the mirror has under a
    different host. So the code — the part after `ERROR_TYPE_BASE`, which is
    the part the document actually chose — is lifted off its URI and carried
    onto the base being fetched.

    The code is the part that travels, and it is exactly the part that is not
    infrastructure: PLAN §1 stability rule 2 freezes the base and says
    nothing about the set of codes, which a service extends on its own.
    Lifting the whole URI and re-prefixing it would carry the frozen base
    into the fetch, which is the bug `--base` was added to avoid.

    A URI that is not at the base at all is refused rather than guessed at.
    `openapi.problem-type-base` is the rule that decides that on the
    document, and this module imports the same constant rather than
    restating it, so the two cannot disagree about what "at the base" means
    — but a URI the static rule would already have red-penned is also a URI
    this check has no code to lift, and rewriting it onto a mirror would
    turn a defect into a pass.
    """
    contract = _contract_module()
    if not uri.startswith(contract.ERROR_TYPE_BASE):
        raise _Refusal(
            "errors.type-not-at-base",
            "--base / ANYWAYE_ERRORS_BASE_URL",
            f"{uri!r} is not at {contract.ERROR_TYPE_BASE}, so it has no code to carry "
            f"onto another base. `openapi.problem-type-base` already reports this on the "
            f"document itself; run the contract harness first, because a live check over a "
            f"URI the document should not have published answers a question about the wrong "
            f"page tree",
        )
    code = uri[len(contract.ERROR_TYPE_BASE):]
    return f"{base}/{code}"


def resolve_uri(uri: str, timeout: float) -> _Result:
    """GET one URI, and say what it answered.

    Every failure is a `_Result` with a `status` of `None` and a human
    sentence, rather than an exception: the point of this function is the
    report, and a traceback is not a report. `socket.timeout` and
    `urllib.error.HTTPError` are both caught because a 404 raises the second
    and a hang raises the first, and a reader needs to know which of the two
    happened.
    """
    request = urllib.request.Request(uri, headers={"User-Agent": "anywaye-errors-resolve/1"})
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(response.status)
    except urllib.error.HTTPError as error:
        return _Result(uri, int(error.code), f"answered {int(error.code)}")
    except socket.timeout:
        return _Result(uri, None, f"no answer within {timeout:g}s")
    except urllib.error.URLError as error:
        reason = getattr(error, "reason", error)
        return _Result(uri, None, f"unreachable: {reason}")
    except (ConnectionError, OSError) as error:
        return _Result(uri, None, f"unreachable: {error}")
    elapsed = time.monotonic() - started
    return _Result(uri, status, f"answered 200 in {elapsed * 1000:.0f}ms")


def check(service: Path, core: Path, base: str, sample: int, timeout: float) -> int:
    """Fetch a sample of the document's own `type` URIs. Returns an exit code."""
    resolved_base = normalise_base(base)
    uris = read_types(service, core)[:sample]
    print(
        f"errors-resolve: fetching {len(uris)} type URI(s) declared by "
        f"{service} at {resolved_base}"
    )
    try:
        targets = [(uri, retarget(uri, resolved_base)) for uri in uris]
    except _Refusal as refusal:
        print(f"REFUSED errors-resolve ({refusal.rule}) {refusal.where}: {refusal.detail}",
              file=sys.stderr)
        return EXIT_COULD_NOT_RUN
    results = [resolve_uri(target, timeout) for _, target in targets]
    for (published, target), result in zip(targets, results):
        mark = "ok  " if result.resolved else "FAIL"
        print(f"  {mark} {target} — {result.detail}  (published as {published})")

    unreachable = [result for result in results if not result.resolved]
    if unreachable and all(result.status is None for result in unreachable):
        print(
            f"FAIL errors-resolve: {len(unreachable)} of {len(results)} URI(s) could not "
            f"be reached at all, and none of them answered. That is a base that is down "
            f"rather than a page that is missing: {resolved_base} did not respond, and a "
            f"live check that cannot reach its base is a failure and not a skip. Start a "
            f"docs mirror, or pass --base to the one you already have."
        )
        return EXIT_FAIL

    for result in unreachable:
        print(
            f"FAIL errors-resolve: {result.uri} did not resolve — {result.detail}. PLAN "
            f"§1 stability rule 2 freezes the base for the life of the platform, so a "
            f"client that stored this URI dereferences it years from now; the page has "
            f"to be there."
        )
    return EXIT_FAIL if unreachable else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="errors-resolve",
        description=(
            "Fetch a sample of the live problem `type` URIs a service's OpenAPI "
            "document publishes, and assert each answers 200. Offline: nothing. "
            "This is the live tier and it says so by failing when it cannot "
            "reach the base."
        ),
    )
    parser.add_argument("service", nargs="?", default=".", help="the service repository root")
    parser.add_argument("--core", help="a anywaye/core checkout (default: $ANYWAYE_CORE)")
    parser.add_argument(
        "--base",
        default=None,
        help=(
            "the docs base to fetch against: a local mirror, or the canonical "
            f"{DEFAULT_BASE}. Defaults to $ANYWAYE_ERRORS_BASE_URL, else {DEFAULT_BASE}"
        ),
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=DEFAULT_SAMPLE,
        help=f"at most this many URIs to fetch (default {DEFAULT_SAMPLE})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"seconds to wait for any one URI (default {DEFAULT_TIMEOUT:g})",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable report on stdout")
    arguments = parser.parse_args(argv)

    base = arguments.base or os.environ.get("ANYWAYE_ERRORS_BASE_URL") or DEFAULT_BASE
    core_root = (
        Path(arguments.core) if arguments.core else Path(os.environ.get("ANYWAYE_CORE") or ".")
    )

    try:
        if arguments.sample < 1:
            raise _Refusal(
                "errors.sample-empty",
                "--sample",
                "a sample of zero fetches nothing, and a check that fetches nothing "
                "cannot have checked anything",
            )
        if arguments.timeout <= 0:
            raise _Refusal(
                "errors.timeout-empty",
                "--timeout",
                "a timeout of zero answers nothing, and an unbounded fetch is the hang "
                "this whole check exists to refuse",
            )
        return check(
            Path(arguments.service), core_root, base, arguments.sample, arguments.timeout
        )
    except _Refusal as refusal:
        print(f"REFUSED errors-resolve ({refusal.rule}) {refusal.where}: {refusal.detail}",
              file=sys.stderr)
        return EXIT_COULD_NOT_RUN


if __name__ == "__main__":
    sys.exit(main())
