#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import core_version
except ModuleNotFoundError as _missing:  # pragma: no cover - travels together
    raise SystemExit(
        f"anywaye-contract: cannot import core_version from "
        f"{Path(__file__).resolve().parent}: {_missing}. The harness travels whole; a "
        f"copy of one without the other cannot resolve a `core:` constraint and must "
        f"refuse rather than quietly check less."
    )

MINIMUM_PYTHON = (3, 9)

IMPLEMENTED_KEYWORDS = frozenset(
    {
        "$defs",
        "$ref",
        "additionalProperties",
        "allOf",
        "anyOf",
        "const",
        "enum",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "format",
        "if",
        "items",
        "maxItems",
        "maxLength",
        "maxProperties",
        "maximum",
        "minItems",
        "minLength",
        "minProperties",
        "minimum",
        "not",
        "oneOf",
        "pattern",
        "prefixItems",
        "properties",
        "required",
        "then",
        "type",
        "uniqueItems",
    }
)

CHECKED_FORMATS = frozenset({"date", "date-time", "email", "uri", "uuid"})

RULE_IDS = (
    "compose.postgres-pin",
    "compose.postgres-tag-absent",
    "core.absent",
    "core.constraint-unmet",
    "core.constraint-unresolvable",
    "core.digest-mismatch",
    "core.not-a-checkout",
    "core.version-absent",
    "event.own-prefix",
    "event.no-self-consume",
    "event.payload-schema-missing",
    "event.unknown-consumed",
    "event.unknown-published",
    "manifest.api-file-missing",
    "manifest.schema",
    "openapi.document-is-31",
    "openapi.errors-are-problems",
    "openapi.has-paths",
    "openapi.idempotency-conflict-documented",
    "openapi.idempotency-key",
    "openapi.info-version",
    "openapi.no-offset-pagination",
    "openapi.one-version-prefix",
    "openapi.page-envelope",
    "openapi.paths-are-versioned",
    "openapi.problem-code-matches-type",
    "openapi.problem-has-trace-id",
    "openapi.problem-type-base",
    "openapi.reserved-error-codes",
    "service.manifest-absent",
    "slo.duplicate-name",
    "slo.no-infrastructure-slo",
    "slo.no-unbounded-dimension",
    "slo.schema",
    "slo.sli-canonical",
    "slo.unknown-metric",
    "slo.window-override",
    "slo.window-token",
    "yaml.unsupported",
)

WARNING_IDS = (
    "openapi.no-document",
    "openapi.not-declared",
    "openapi.unresolved-ref",
    "compose.pin-scan-truncated",
)

WARNINGS = {
    "openapi.no-document": (
        "this manifest declares no exposes.api, so none of the openapi.* rules ran. "
        "That is not a pass over the document: it is no document. docs/contract-harness.md "
        "records this as a ceiling on enforcement, and it lifts the moment a service "
        "declares one."
    ),
    "openapi.not-declared": (
        "a document is checked in here that exposes.api does not name, so every openapi.* "
        "rule skipped it. The harness reads what the manifest declares and nothing it can "
        "guess at — pointing exposes.api at the file is a one-line change, and it is the "
        "difference between being checked and not being checked."
    ),
    "openapi.unresolved-ref": (
        "a $ref that is not a local pointer, which the harness cannot read: it reads a "
        "checkout of core and never fetches a file. Whatever is behind that pointer was "
        "not checked, and no rule below claims otherwise."
    ),
    "compose.pin-scan-truncated": (
        "a compose-shaped file below the depth compose.postgres-pin scans. Nothing in it "
        "was read, so a postgres pin in there is a pin no rule checked. The bound is "
        "deliberate — an unbounded walk finds node_modules — which is exactly why a file "
        "outside it has to be named rather than passed over."
    ),
}

REFUSALS = {
    "compose.postgres-tag-absent": (
        "core publishes no postgres tag: no readable POSTGRES_TAG at its root, holding "
        "exactly one tag. Every postgres image reference in a service is compared against "
        "it, so without it there is nothing to compare against and a run that cannot find "
        "what it is checking has converted an unknown into a pass. This is the same defect "
        "as core.version-absent and it exits 2 for the same reason."
    ),
    "core.absent": (
        "no anywaye/core checkout found; pass --core PATH, or set ANYWAYE_CORE. "
        "core is offline by contract — the harness never fetches a schema, because a "
        "contract check that needs the network is one nobody runs on an air-gapped runner."
    ),
    "core.not-a-checkout": (
        "that directory is not a anywaye/core checkout: no "
        "schemas/anywaye.manifest.schema.json. A directory that exists is not proof."
    ),
    "core.version-absent": (
        "core publishes no version: no readable VERSION at its root, holding "
        "exactly one MAJOR.MINOR.PATCH line. Without it no `core:` constraint "
        "can be resolved, and a check that cannot find what it is checking has "
        "converted an unknown into a pass. This is the same defect as muse's "
        "MUSE_CORE_SCHEMAS tier and pantry's PANTRY_ANYWAYE_ROOT — a core that "
        "was never found — and it exits 2 for the same reason those must not "
        "be allowed to skip."
    ),
    "service.manifest-absent": (
        "no anywaye.yml at the service root. An empty report's OK is indistinguishable "
        "from the OK of a repository nobody looked at."
    ),
    "yaml.unsupported": (
        "outside the YAML subset this harness reads. The subset is YAML_SUBSET below "
        "and everything refused is YAML_REFUSALS; the harness refuses rather than "
        "guessing, because guessing means validating a document nobody wrote."
    ),
    "inventory.out-of-date": (
        "harness/rules.json does not describe every id this harness can emit, so there "
        "is no honest answer to give. A rule the inventory does not describe is a rule "
        "nobody was told about, and an inventory that has drifted from the code is the "
        "same defect as a schema that has drifted from its examples."
    ),
}

YAML_REFUSALS = {
    "&anchor": "anchors are not read",
    "*alias": "aliases are not read",
    "!tag": "tags are not read",
    "%YAML": "directives are not read",
    "<<": "merge keys are not read",
    "[{": (
        "flow collections of scalars, including across lines — a nested flow "
        "collection, a trailing comma, and a `[` closed with `}` are not read"
    ),
    "tab": "a tab cannot be used for indentation",
    "duplicate key": "a key that appears twice is refused rather than resolved",
    "second document": "a multi-document file is not merged",
}

YAML_SUBSET = (
    "block mappings, block sequences, block scalars (| and >, with chomping and "
    "indentation indicators), plain scalars continued across lines, quoted scalars, "
    "flow collections of scalars including across lines, the empty collections [] and "
    "{}, the literals null/true/false, integers, a leading --- document marker, and "
    "comments on their own line or after a value."
)

EXIT_CONFORMS = 0
EXIT_VIOLATIONS = 1
EXIT_REFUSED = 2

MANIFEST_SCHEMA_RELATIVE = Path("schemas") / "anywaye.manifest.schema.json"
EVENT_CATALOG_RELATIVE = Path("docs") / "event-naming.md"
CATALOG_HEADING = "## Catalog"

SEMVER_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
VERSION_PREFIX = re.compile(r"^/v(\d+)(/|$)")
PATH_PARAM = re.compile(r"\{[^{}]+\}")


RESERVED_ERROR_CODES = {
    "unauthorized": 401,
    "forbidden": 403,
    "not_found": 404,
    "conflict": 409,
    "validation_failed": 422,
    "rate_limited": 429,
    "idempotency_key_reused": 409,
    "internal": 500,
    "unavailable": 503,
}

PROBLEM_MEDIA_TYPE = "application/problem+json"

SNAKE_CASE_SLUG = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")

ERROR_TYPE_BASE = "https://docs.anywaye.com/errors/"

HTTP_METHODS = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
)

#: Query parameter names that are offset pagination under another spelling.
#: `docs/openapi-conventions.md`, "Pagination": "Cursor-based everywhere,
#: including for admin and export endpoints. Offset pagination does not scale past
#: a few thousand rows and cannot be stable while rows are being inserted."
#:
#: A short, named list rather than a pattern, because a false accusation here is
#: worse than a missed `per_page`: a harness that bars every parameter containing
#: "page" also bars a customer's own `/v1/pages` filter. These five are the
#: spellings the convention is actually about. `start` and `since` are
#: deliberately absent — they are time ranges, and a document that pages by time
#: is still cursor-paginated.
OFFSET_PARAMETER_NAMES = frozenset(
    {"offset", "page", "page_number", "page_no", "skip"}
)

PAGINATION_REQUEST_PARAMETERS = frozenset({"limit", "cursor", "order"})

IDEMPOTENCY_HEADER = "idempotency-key"

MAX_REF_DEPTH = 8

OPENAPI_DOCUMENT_GLOBS = ("openapi.yaml", "openapi.yml", "openapi.json")
OPENAPI_DOCUMENT_DIRECTORIES = ("openapi",)
OPENAPI_DOCUMENT_SUFFIXES = (".yaml", ".yml", ".json")

DATE_SHAPE = re.compile(r"^\d{4}-\d{2}-\d{2}$", re.ASCII)

YAML_FLOAT = re.compile(r"^[-+]?(?:[0-9]+\.[0-9]*|\.[0-9]+)$", re.ASCII)

RFC3339 = re.compile(
    r"""
    ^
    (\d{4})
    -
    (0[1-9]|1[0-2])
    -
    (\d{2})
    [Tt]
    (?:[01]\d|2[0123])
    :
    (?:[0-5]\d)
    :
    (?:[0-5]\d)
    (?:\.\d+)?
    (?:
      [Zz]
      | [+-](?:[01]\d|2[0123]):[0-5]\d
    )
    $
    """,
    re.VERBOSE | re.ASCII,
)

URI_SHAPE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:[^\s\x00-\x20\x7f]*$", re.ASCII)

_DAYS_IN_MONTH = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


# --------------------------------------------------------------------------
# results
# --------------------------------------------------------------------------


class Refusal(Exception):
    """The run could not happen.

    Carries a rule id from `RULE_IDS`, so a refusal is as greppable as a
    violation and neither of them is ever exit 0. The *location* is a separate
    field rather than part of the message, because the finding that wraps it
    already prints the path and a refusal that names its file twice reads like
    two failures.
    """

    def __init__(self, rule: str, path: str = "", detail: str = "") -> None:
        self.rule = rule
        self.path = path
        self.detail = detail
        message = REFUSALS.get(rule, rule)
        if detail:
            message = f"{message} ({detail})"
        super().__init__(message)


@dataclass(frozen=True)
class Violation:
    """One schema violation, flattened for a readable assertion.

    The three fields mirror `tests/test_specs.py`'s `Failure`, which is
    deliberate: the harness and the suite are comparing the same thing about the
    same schemas, and the equivalence test reads better when both sides are the
    same shape.
    """

    keyword: str
    path: str
    message: str

    def __str__(self) -> str:
        where = self.path or "<root>"
        return f"{where}: {self.message} [{self.keyword}]"


@dataclass(frozen=True)
class Finding:
    """One broken rule, as a service's CI sees it."""

    rule: str
    path: str
    message: str

    def __str__(self) -> str:
        where = self.path or "<root>"
        return f"FAIL {self.rule} {where}: {self.message}"


@dataclass(frozen=True)
class Warning:
    """One thing the harness did **not** check.

    A separate type from `Finding` rather than a flag on it, because the two
    differ in what a reader is entitled to do: a finding must be fixed before
    the build passes, and a warning cannot be, because most of the fleet has
    nothing to fix yet. Collapsing them is how "checked nothing" comes to read
    as "found nothing", which is the defect core's exit-2 rule exists to
    prevent and which a warning is the honest way out of.

    `Result.exit_code` never looks at these.
    """

    rule: str
    path: str
    message: str

    def __str__(self) -> str:
        where = self.path or "<root>"
        return f"WARN {self.rule} {where}: {self.message}"


@dataclass
class Result:
    """Everything one run produced. `exit_code` is the only thing to branch on.

    `refused` is what separates "the service does not conform" from "the run did
    not happen", and the two are different exit codes. Collapsing them is how a
    check that could not find the contract ends up reporting success: both cases
    produce a non-empty `findings`, so a caller branching on "did I get any
    output" cannot tell them apart, and a caller branching on the exit code
    reads 2 as 1 and files it as a contract bug rather than as a missing
    checkout.

    `warnings` is the third answer — the run happened, nothing failed, and here
    is what was not looked at — and it deliberately does not reach
    `exit_code`. See `WARNING_IDS` for why that is a ceiling on enforcement and
    not an oversight.
    """

    service_root: Path
    core_root: Path | None
    digest: str | None
    findings: tuple[Finding, ...] = ()
    stopped_after_schema: bool = False
    core_commit: str | None = None
    refused: bool = False
    warnings: tuple[Warning, ...] = ()

    @property
    def exit_code(self) -> int:
        if self.refused:
            return EXIT_REFUSED
        if self.findings:
            return EXIT_VIOLATIONS
        return EXIT_CONFORMS

    @property
    def rules(self) -> tuple[str, ...]:
        return tuple(finding.rule for finding in self.findings)

    @property
    def warning_rules(self) -> tuple[str, ...]:
        return tuple(warning.rule for warning in self.warnings)




def _type_matches(value: Any, name: str) -> bool:
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "null":
        return value is None
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return False


def _json_type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "null"


def _resolve_pointer(root: Any, pointer: str) -> Any:
    if pointer in ("", "#"):
        return root
    if not pointer.startswith("#/"):
        raise Refusal("core.not-a-checkout", pointer, "only local $ref pointers are resolvable")
    node = root
    for raw in pointer[2:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            node = node[int(token)]
        elif isinstance(node, dict):
            node = node[token]
        else:
            raise Refusal("core.not-a-checkout", pointer, f"{token} is not in the schema")
    return node


def _format_ok(value: Any, name: str) -> bool:
    if name not in CHECKED_FORMATS:
        return True
    if not isinstance(value, str):
        return True
    if name == "email":
        return "@" in value
    if name == "uuid":
        return _is_uuid(value)
    if name == "date":
        return _is_date(value)
    if name == "date-time":
        return _is_rfc3339(value)
    return bool(URI_SHAPE.match(value))


def _is_uuid(value: str) -> bool:
    stripped = value.strip()
    candidate = stripped
    if candidate.startswith("{") and candidate.endswith("}"):
        candidate = candidate[1:-1]
    if candidate.startswith("urn:uuid:"):
        candidate = candidate[9:]
    body = candidate.replace("-", "")
    if len(body) != 32 or any(character not in "0123456789abcdefABCDEF" for character in body):
        return False
    if candidate == body:
        return False
    return all(stripped[position] == "-" for position in (8, 13, 18, 23))


def _is_date(value: str) -> bool:
    if not DATE_SHAPE.match(value):
        return False
    year, month, day = (int(part) for part in value.split("-"))
    if not 1 <= month <= 12:
        return False
    limit = _DAYS_IN_MONTH[month - 1]
    if month == 2 and (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
        limit = 29
    return 1 <= day <= limit


def _is_rfc3339(value: str) -> bool:
    match = RFC3339.match(value.upper())
    if match is None:
        return False
    year, month, day = (int(part) for part in match.groups())
    if year == 0:
        return False
    return 1 <= day <= _DAYS_IN_MONTH[month - 1] + (
        1 if month == 2 and year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 0
    )


def _equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_equal(left[k], right[k]) for k in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_equal(a, b) for a, b in zip(left, right))
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    return type(left) is type(right) and left == right


def _hashable(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def evaluate(instance: Any, schema: Any, root: Any = None, path: str = "") -> list[Violation]:
    """Every way `instance` fails `schema`, as a flat list.

    `root` is the document the schema came from, which is what makes `$ref` and
    `$defs` resolvable; it defaults to `schema` so a caller validating against a
    self-contained document need not pass it.
    """
    if root is None:
        root = schema
    if schema is True or schema == {}:
        return []
    if schema is False:
        return [Violation(keyword="false", path=path, message="no value is allowed here")]
    if not isinstance(schema, dict):
        raise Refusal("core.not-a-checkout", path, f"a schema must be an object, got {type(schema)}")

    found: list[Violation] = []

    if "$ref" in schema:
        target = _resolve_pointer(root, schema["$ref"])
        found.extend(evaluate(instance, target, root, path))

    where = "the value" if not path else path

    names = _as_names(schema.get("type"))
    if names and not any(_type_matches(instance, name) for name in names):
        found.append(Violation(
            keyword="type", path=path,
            message=f"{where} is {_json_type_name(instance)}, not any of {names}",
        ))

    if "const" in schema and not _equal(instance, schema["const"]):
        found.append(Violation(
            keyword="const", path=path,
            message=f"{where} must be {schema['const']!r}, not {instance!r}",
        ))

    if "enum" in schema and not any(_equal(instance, option) for option in schema["enum"]):
        found.append(Violation(
            keyword="enum", path=path,
            message=f"{where} must be one of {schema['enum']!r}, not {instance!r}",
        ))

    if isinstance(instance, str):
        found.extend(_string_violations(instance, schema, path, where))
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            found.append(Violation(
                keyword="minimum", path=path,
                message=f"{where} is {instance}, below the minimum {schema['minimum']}",
            ))
        if "maximum" in schema and instance > schema["maximum"]:
            found.append(Violation(
                keyword="maximum", path=path,
                message=f"{where} is {instance}, above the maximum {schema['maximum']}",
            ))
        if "exclusiveMaximum" in schema and instance >= schema["exclusiveMaximum"]:
            found.append(Violation(
                keyword="exclusiveMaximum", path=path,
                message=(
                    f"{where} is {instance}, at or above the exclusive maximum "
                    f"{schema['exclusiveMaximum']}"
                ),
            ))
        if "exclusiveMinimum" in schema and instance <= schema["exclusiveMinimum"]:
            found.append(Violation(
                keyword="exclusiveMinimum", path=path,
                message=(
                    f"{where} is {instance}, at or below the exclusive minimum "
                    f"{schema['exclusiveMinimum']}"
                ),
            ))
    if isinstance(instance, list):
        found.extend(_array_violations(instance, schema, root, path, where))
    if isinstance(instance, dict):
        found.extend(_object_violations(instance, schema, root, path, where))

    for keyword in ("allOf", "anyOf", "oneOf"):
        if keyword not in schema:
            continue
        found.extend(_combinator_violations(keyword, instance, schema[keyword], root, path, where))

    if "not" in schema and not evaluate(instance, schema["not"], root, path):
        found.append(Violation(
            keyword="not", path=path,
            message=f"{where} matches a shape core forbids here",
        ))

    if "if" in schema and not evaluate(instance, schema["if"], root, path):
        if "then" in schema:
            found.extend(evaluate(instance, schema["then"], root, path))

    return found


def _as_names(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [name for name in value if isinstance(name, str)]


def _string_violations(instance: str, schema: dict, path: str, where: str) -> list[Violation]:
    found = []
    if "minLength" in schema and len(instance) < schema["minLength"]:
        found.append(Violation(
            keyword="minLength", path=path,
            message=f"{where} is {len(instance)} characters, minimum {schema['minLength']}",
        ))
    if "maxLength" in schema and len(instance) > schema["maxLength"]:
        found.append(Violation(
            keyword="maxLength", path=path,
            message=f"{where} is {len(instance)} characters, maximum {schema['maxLength']}",
        ))
    if "pattern" in schema and not _pattern_search(schema["pattern"], instance):
        found.append(Violation(
            keyword="pattern", path=path,
            message=f"{where} does not match {schema['pattern']}",
        ))
    if "format" in schema and not _format_ok(instance, schema["format"]):
        found.append(Violation(
            keyword="format", path=path,
            message=f"{where} is not a valid {schema['format']}: {instance!r}",
        ))
    return found


def _pattern_search(pattern: str, value: str) -> bool:
    try:
        return re.search(pattern, value, re.ASCII) is not None
    except re.error as error:
        raise Refusal("core.not-a-checkout", pattern, f"not a usable regular expression: {error}")


def _array_violations(instance: list, schema: dict, root: Any, path: str, where: str) -> list[Violation]:
    found = []
    if "minItems" in schema and len(instance) < schema["minItems"]:
        found.append(Violation(
            keyword="minItems", path=path,
            message=f"{where} has {len(instance)} items, minimum {schema['minItems']}",
        ))
    if "maxItems" in schema and len(instance) > schema["maxItems"]:
        found.append(Violation(
            keyword="maxItems", path=path,
            message=f"{where} has {len(instance)} items, maximum {schema['maxItems']}",
        ))
    if schema.get("uniqueItems") and len(instance) != len({_hashable(item) for item in instance}):
        found.append(Violation(
            keyword="uniqueItems", path=path,
            message=f"{where} repeats a value and the schema says each is unique",
        ))
    positional = schema.get("prefixItems") or []
    for index, subschema in enumerate(positional):
        if index < len(instance):
            found.extend(evaluate(instance[index], subschema, root, _join(path, index)))
    if "items" in schema:
        for index in range(len(positional), len(instance)):
            found.extend(evaluate(instance[index], schema["items"], root, _join(path, index)))
    return found


def _object_violations(
    instance: dict, schema: dict, root: Any, path: str, where: str
) -> list[Violation]:
    found = []
    for name in schema.get("required", []):
        if name not in instance:
            found.append(Violation(
                keyword="required", path=path,
                message=f"{where} is missing the required {name!r}",
            ))
    if "minProperties" in schema and len(instance) < schema["minProperties"]:
        found.append(Violation(
            keyword="minProperties", path=path,
            message=f"{where} has {len(instance)} keys, minimum {schema['minProperties']}",
        ))
    if "maxProperties" in schema and len(instance) > schema["maxProperties"]:
        found.append(Violation(
            keyword="maxProperties", path=path,
            message=f"{where} has {len(instance)} keys, maximum {schema['maxProperties']}",
        ))

    properties = schema.get("properties") or {}
    extra = schema.get("additionalProperties", True)
    for name, value in instance.items():
        child = _join(path, name)
        if name in properties:
            found.extend(evaluate(value, properties[name], root, child))
        elif extra is False:
            found.append(Violation(
                keyword="additionalProperties", path=path,
                message=f"{where} declares {name!r}, which core's schema does not have",
            ))
        elif extra is not True:
            found.extend(evaluate(value, extra, root, child))
    return found


def _combinator_violations(
    keyword: str, instance: Any, subschemas: list, root: Any, path: str, where: str
) -> list[Violation]:
    if keyword == "allOf":
        found = []
        for subschema in subschemas:
            found.extend(evaluate(instance, subschema, root, path))
        return found
    matched = sum(1 for subschema in subschemas if not evaluate(instance, subschema, root, path))
    if keyword == "anyOf" and matched == 0:
        return [Violation(
            keyword="anyOf", path=path,
            message=f"{where} matches none of the {len(subschemas)} shapes core allows here",
        )]
    if keyword == "oneOf" and matched != 1:
        return [Violation(
            keyword="oneOf", path=path,
            message=(
                f"{where} matches {matched} of the {len(subschemas)} shapes core allows here, "
                "and oneOf means exactly one"
            ),
        )]
    return []


def _join(path: str, part: Any) -> str:
    return f"{path}/{part}" if path else str(part)




class _Line:

    __slots__ = ("number", "raw", "text", "indent", "blank")

    def __init__(self, number: int, raw: str) -> None:
        self.number = number
        self.raw = raw.rstrip("\n").rstrip("\r")
        stripped = _strip_comment(self.raw)
        self.blank = not stripped.strip()
        self.text = stripped.strip()
        self.indent = len(stripped) - len(stripped.lstrip(" "))


def read_yaml(text: str, path: Path) -> Any:
    """Read the declared subset, or refuse with a file and a line."""
    lines = _all_lines(text, path)
    index = _skip_blank(lines, 0)
    if index >= len(lines):
        return None
    if lines[index].text in ("---", "..."):
        index = _skip_blank(lines, index + 1)
        if index >= len(lines):
            return None
        if lines[index].text == "---":
            raise Refusal(
                "yaml.unsupported", f"{path}:{lines[index].number}",
                "a second document in one file; this reader reads the first and does not merge",
            )
    value, index = _parse_block(lines, index, lines[index].indent, path)
    index = _skip_blank(lines, index)
    if index < len(lines) and lines[index].text not in ("...",):
        orphan = lines[index]
        continuation = _plain_key_end(orphan.text) is None and not orphan.text.startswith("- ")
        reason = (
            "this continues the value on the line above it; a multi-line plain scalar folds "
            "to a single line and this harness does not fold anything"
            if continuation
            else "this line is not part of the block above it"
        )
        raise Refusal("yaml.unsupported", f"{path}:{orphan.number}", reason)
    return value


def _all_lines(text: str, path: Path) -> list[_Line]:
    lines: list[_Line] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        leading = raw[: len(raw) - len(raw.lstrip())]
        if "\t" in leading:
            raise Refusal(
                "yaml.unsupported", f"{path}:{number}", "a tab cannot be used for indentation"
            )
        lines.append(_Line(number, raw))
    return lines


def _skip_blank(lines: list[_Line], index: int) -> int:
    while index < len(lines) and lines[index].blank:
        index += 1
    return index


def _strip_comment(line: str) -> str:
    quote = ""
    for index, character in enumerate(line):
        if quote:
            if character == quote:
                quote = ""
            continue
        if character in "\"'":
            quote = character
            continue
        if character == "#" and (index == 0 or line[index - 1] in " \t"):
            return line[:index]
    return line


def _parse_block(lines: list[_Line], index: int, indent: int, path: Path) -> tuple[Any, int]:
    index = _skip_blank(lines, index)
    if index >= len(lines):
        return None, index
    if lines[index].text == "-" or lines[index].text.startswith("- "):
        return _parse_sequence(lines, index, indent, path)
    return _parse_mapping(lines, index, indent, path)


def _parse_mapping(lines: list[_Line], index: int, indent: int, path: Path) -> tuple[dict, int]:
    mapping: dict[str, Any] = {}
    while True:
        index = _skip_blank(lines, index)
        if index >= len(lines) or lines[index].indent != indent:
            return mapping, index
        line = lines[index]
        if line.text == "-" or line.text.startswith("- "):
            return mapping, index
        key, rest = _split_key(line, path)
        if key == "<<":
            raise Refusal("yaml.unsupported", f"{path}:{line.number}", YAML_REFUSALS["<<"])
        if key in mapping:
            raise Refusal(
                "yaml.unsupported", f"{path}:{line.number}",
                f"{key!r} appears twice; the harness refuses rather than pick one",
            )
        index += 1
        if rest == "":
            after = _skip_blank(lines, index)
            if after < len(lines) and lines[after].indent > indent:
                if lines[after].text[:1] in ("[", "{"):
                    mapping[key], index = _parse_value(
                        lines[after].text, lines[after], lines, after + 1, indent, path
                    )
                else:
                    mapping[key], index = _parse_block(lines, after, lines[after].indent, path)
            else:
                mapping[key] = None
        else:
            mapping[key], index = _parse_value(rest, line, lines, index, indent, path)


def _parse_sequence(lines: list[_Line], index: int, indent: int, path: Path) -> tuple[list, int]:
    items: list[Any] = []
    while True:
        index = _skip_blank(lines, index)
        if index >= len(lines) or lines[index].indent != indent:
            return items, index
        line = lines[index]
        if not (line.text == "-" or line.text.startswith("- ")):
            return items, index
        body = line.text[1:].strip()
        index += 1
        if body == "":
            after = _skip_blank(lines, index)
            if after < len(lines) and lines[after].indent > indent:
                value, index = _parse_block(lines, after, lines[after].indent, path)
            else:
                value = None
            items.append(value)
            continue
        if _looks_like_key(body, path, line):
            item_indent = indent + (len(line.text) - len(body))
            synthetic = [_Line(line.number, " " * item_indent + body)]
            while index < len(lines) and (lines[index].blank or lines[index].indent >= item_indent):
                synthetic.append(lines[index])
                index += 1
            value, _ = _parse_mapping(synthetic, 0, item_indent, path)
            items.append(value)
        else:
            items.append(_parse_value(body, line, lines, index, indent, path)[0])
    return items, index


def _split_key(line: _Line, path: Path) -> tuple[str, str]:
    text = line.text
    if text[0] in "\"'":
        quote = text[0]
        offset = 1
        while offset < len(text) and text[offset] != quote:
            offset += 2 if text[offset] == "\\" else 1
        if offset >= len(text):
            raise Refusal("yaml.unsupported", f"{path}:{line.number}", "an unterminated quoted key")
        key = _unquote(text[: offset + 1])
        rest = text[offset + 1 :]
        if not rest.startswith(":"):
            raise Refusal("yaml.unsupported", f"{path}:{line.number}", "expected `:` after the key")
        return key, rest[1:].strip()
    marker = _plain_key_end(text)
    if marker is None:
        raise Refusal(
            "yaml.unsupported", f"{path}:{line.number}",
            f"{text!r} is not `key: value`, and a bare scalar is not read",
        )
    return text[:marker].strip(), text[marker + 1 :].strip()


def _plain_key_end(text: str) -> int | None:
    for index, character in enumerate(text):
        if character != ":":
            continue
        if index + 1 == len(text):
            return index
        if text[index + 1] in " \t":
            return index
    return None


def _looks_like_key(body: str, path: Path, line: _Line) -> bool:
    try:
        _split_key(_Line(line.number, body), path)
    except Refusal:
        return False
    return True


def _parse_value(
    text: str, line: _Line, lines: list[_Line], index: int, indent: int, path: Path
) -> tuple[Any, int]:
    value = text.strip()
    if not value:
        return None, index
    if value[0] == "&":
        raise Refusal("yaml.unsupported", f"{path}:{line.number}", YAML_REFUSALS["&anchor"])
    if value[0] == "*":
        raise Refusal("yaml.unsupported", f"{path}:{line.number}", YAML_REFUSALS["*alias"])
    if value[0] == "!":
        raise Refusal("yaml.unsupported", f"{path}:{line.number}", YAML_REFUSALS["!tag"])
    if value[0] == "%":
        raise Refusal("yaml.unsupported", f"{path}:{line.number}", YAML_REFUSALS["%YAML"])
    if value[0] in "|>":
        return _read_block_scalar(value, line, lines, index, indent, path)
    if value[0] in "[{":
        value, index = _read_flow_span(value, lines, index, indent, path)
        return _parse_scalar(value, line, path), index
    if value[0] in "\"'":
        return _parse_scalar(value, line, path), index
    parts, index = _read_plain_continuation(value, line, lines, index, indent, path)
    return _parse_scalar(_fold_parts(parts), line, path), index


def _read_plain_continuation(
    value: str, line: _Line, lines: list[_Line], index: int, indent: int, path: Path
) -> tuple[list[tuple[str, int]], int]:
    parts: list[tuple[str, int]] = [(value, 0)]
    blanks = 0
    while index < len(lines):
        candidate = lines[index]
        if candidate.blank:
            blanks += 1
            index += 1
            continue
        if candidate.indent <= indent:
            break
        if candidate.text == "-" or candidate.text.startswith("- "):
            break
        if _looks_like_key(candidate.text, path, candidate):
            raise Refusal(
                "yaml.unsupported", f"{path}:{candidate.number}",
                f"{candidate.text!r} follows the scalar on the line above it; a plain scalar "
                "cannot be continued into a mapping",
            )
        parts.append((candidate.text, blanks))
        blanks = 0
        index += 1
    return parts, index


def _fold_parts(parts: list[tuple[str, int]]) -> str:
    folded = parts[0][0]
    for text, blanks in parts[1:]:
        folded += "\n" * blanks if blanks else " "
        folded += text
    return folded


def _read_flow_span(
    value: str, lines: list[_Line], index: int, indent: int, path: Path
) -> tuple[str, int]:
    buffer = [value]
    while not _flow_complete("".join(buffer)):
        if index >= len(lines):
            last = lines[index - 1].number if index else 0
            raise Refusal(
                "yaml.unsupported", f"{path}:{last}",
                "the flow collection opened here never closes",
            )
        candidate = lines[index]
        index += 1
        if candidate.blank:
            continue
        if candidate.indent <= indent:
            raise Refusal(
                "yaml.unsupported", f"{path}:{candidate.number}",
                "the flow collection opened above it never closes",
            )
        buffer.append(" " + candidate.text)
    return "".join(buffer), index


def _flow_complete(text: str) -> bool:
    depth = 0
    quote = ""
    for character in text:
        if quote:
            if character == quote:
                quote = ""
            continue
        if character in "\"'":
            quote = character
        elif character in "[{":
            depth += 1
        elif character in "]}":
            depth -= 1
    return depth == 0 and not quote


def _parse_scalar(text: str, line: _Line, path: Path) -> Any:
    value = text.strip()
    if value[0] in "[{":
        return _parse_flow(value, line, path)
    return _scalar_value(value, line, path)


def _scalar_value(value: str, line: _Line, path: Path) -> Any:
    if value[:1] in "\"'":
        return _unquote(value)
    if value in ("null", "~"):
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    if value.lstrip("-").isdigit():
        return int(value)
    if YAML_FLOAT.fullmatch(value):
        return float(value)
    return value


def _parse_flow(value: str, line: _Line, path: Path) -> Any:
    if value == "[]":
        return []
    if value == "{}":
        return {}
    if not value.endswith(("]", "}")):
        raise Refusal(
            "yaml.unsupported", f"{path}:{line.number}",
            "a flow collection that does not close is not read",
        )
    opening, closing = value[0], value[-1]
    if (opening, closing) not in (("[", "]"), ("{", "}")):
        raise Refusal(
            "yaml.unsupported", f"{path}:{line.number}",
            f"{value!r} opens with {opening!r} and closes with {closing!r}; this reader does "
            "not repair a typo",
        )
    body = value[1:-1].strip()
    entries = _split_flow_items(body, line, path) if body else []
    if opening == "[":
        return [_flow_member(entry, line, path) for entry in entries]
    return _flow_mapping(entries, line, path)


def _flow_mapping(entries: list[str], line: _Line, path: Path) -> dict:
    mapping: dict[str, Any] = {}
    for entry in entries:
        key, separator, rest = entry.partition(":")
        if not separator:
            raise Refusal(
                "yaml.unsupported", f"{path}:{line.number}",
                f"{entry!r} in a flow mapping has no `:`; a flow mapping is not a sequence",
            )
        name = key.strip()
        if name[:1] in "\"'":
            name = _unquote(name)
        if name in mapping:
            raise Refusal(
                "yaml.unsupported", f"{path}:{line.number}",
                f"{name!r} appears twice in one flow mapping; the harness refuses rather "
                "than pick one",
            )
        mapping[name] = _flow_member(rest, line, path)
    return mapping


def _flow_member(entry: str, line: _Line, path: Path) -> Any:
    entry = entry.strip()
    if not entry:
        raise Refusal(
            "yaml.unsupported", f"{path}:{line.number}",
            "a trailing comma in a flow collection is not read",
        )
    if entry[0] in "[{" or entry[-1] in "]}":
        raise Refusal(
            "yaml.unsupported", f"{path}:{line.number}",
            f"{entry!r} nests one flow collection inside another, which is not read",
        )
    return _scalar_value(entry, line, path)


def _split_flow_items(body: str, line: _Line, path: Path) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    quote = ""
    for character in body:
        if quote:
            current.append(character)
            if character == quote:
                quote = ""
            continue
        if character in "\"'":
            quote = character
            current.append(character)
            continue
        if character == ",":
            items.append("".join(current))
            current = []
            continue
        current.append(character)
    if quote:
        raise Refusal(
            "yaml.unsupported", f"{path}:{line.number}", "an unterminated quoted scalar"
        )
    items.append("".join(current))
    return items


def _unquote(text: str) -> str:
    quote = text[0]
    body = text[1:-1] if len(text) > 1 and text[-1] == quote else text[1:]
    if quote == "'":
        return body.replace("''", "'")
    try:
        return json.loads(f'"{body}"')
    except ValueError:
        return body


BLOCK_HEADER = re.compile(r"^([|>])(?:([+-])|([1-9]))?(?:([1-9])?([+-])?)?$")


def _read_block_scalar(
    header: str, line: _Line, lines: list[_Line], index: int, indent: int, path: Path
) -> tuple[str, int]:
    match = BLOCK_HEADER.match(header)
    if match is None:
        raise Refusal(
            "yaml.unsupported", f"{path}:{line.number}",
            f"{header!r} is not a block scalar header; this reader reads `|`, `>` and their "
            "chomping and indentation indicators",
        )
    style, chomp_before, indicator_a, indicator_b, chomp_after = match.groups()
    chomp = {"-": "strip", "+": "keep"}.get(chomp_before or chomp_after or "", "clip")
    indicator = indicator_a or indicator_b

    body: list[str] = []
    block_indent = indent + int(indicator) if indicator else None
    while index < len(lines):
        raw = lines[index].raw
        if not raw.strip():
            body.append("")
            index += 1
            continue
        column = len(raw) - len(raw.lstrip(" "))
        if column <= indent:
            break
        if block_indent is None:
            block_indent = column
        if column < block_indent:
            break
        body.append(raw[block_indent:].rstrip())
        index += 1

    trailing = 0
    while body and body[-1] == "":
        body.pop()
        trailing += 1
    if block_indent is None:
        return "", index

    value = "\n".join(body) if style == "|" else _fold(body)
    if chomp == "strip":
        return value, index
    if chomp == "keep":
        return value + "\n" * (trailing + 1), index
    return value + "\n", index


def _fold(body: list[str]) -> str:
    parts: list[str] = []
    previous_more = False
    blanks = 0
    for entry in body:
        if entry == "":
            blanks += 1
            continue
        more = entry[:1] in (" ", "\t")
        if parts:
            parts.append("\n" * blanks)
            if more or previous_more:
                parts.append("\n")
            elif blanks == 0:
                parts.append(" ")
        parts.append(entry)
        previous_more = more
        blanks = 0
    return "".join(parts)


# --------------------------------------------------------------------------
# core: resolution, provenance, the event catalog
# --------------------------------------------------------------------------


def resolve_core(explicit: Path | None = None, *, env: dict | None = None) -> Path:
    """The core checkout to read, or a `Refusal`.

    Resolution order, and the reason it is a list rather than one answer: an
    explicit flag is a person, an environment variable is a CI step that read a
    repository variable, and walking up is a developer with a sibling checkout.
    The last is deliberately not the default — muse's `MUSE_CORE_SCHEMAS` tier
    and pantry's `PANTRY_ANYWAYE_ROOT` are both "a directory that happened to be
    next to me", and both are the reason a fleet ended up with four ways to find
    core. A harness that guesses its contract is a harness whose answer depends
    on the directory it was run from.
    """
    settings = os.environ if env is None else env
    candidates = []
    if explicit is not None:
        candidates.append(Path(explicit))
    elif settings.get("ANYWAYE_CORE"):
        candidates.append(Path(settings["ANYWAYE_CORE"]))
    for candidate in candidates:
        if not candidate.is_dir():
            raise Refusal(
                "core.not-a-checkout", str(candidate),
                "the path given is not a directory",
            )
        if not (candidate / MANIFEST_SCHEMA_RELATIVE).is_file():
            raise Refusal("core.not-a-checkout", str(candidate))
        return candidate.resolve()
    raise Refusal("core.absent", "searched: --core, $ANYWAYE_CORE")


def is_core_checkout(root: Path) -> bool:
    return (root / MANIFEST_SCHEMA_RELATIVE).is_file()


def contract_digest(root: Path) -> str:
    """A sha256 over everything under `schemas/`, path-sorted.

    **This is the pin.** Not a git ref: a ref names a commit in a repository the
    harness cannot see, and the harness is offline by contract. A digest names
    the bytes, and the bytes are the thing a service is actually compiling
    against.

    Three properties, and all three matter:
      * the same core ref gives the same digest in a worktree and in a runner, so
        a laptop and CI are the same harness rather than two that happen to look
        alike;
      * a one-byte edit to one schema changes it, so `--expect-digest` catches
        the smallest possible drift — the kind a re-vendor fan-out produces;
      * it covers all of `schemas/`, not the two files a service happens to
        vendor, so a service cannot be pinned against a partial copy.

    What it does not do is notice a *dirty* tree that has not been committed.
    A developer with an edited schema and a clean HEAD gets a different digest
    from CI, and that is the truth rather than a bug: their tree really is
    different.
    """
    digest = hashlib.sha256()
    directory = root / "schemas"
    if not directory.is_dir():
        return ""
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def core_commit(root: Path) -> str | None:
    """The commit a core checkout is at, read from `.git`, or None.

    Reported, never checked. A git ref is a *name* the harness cannot verify
    offline, and pinning on a name is what made four repositories answer
    "where is core" four ways. The digest is the pin; this is provenance for a
    human reading a CI log.
    """
    head = root / ".git"
    try:
        if head.is_file():
            for line in head.read_text(encoding="utf-8").splitlines():
                if line.startswith("gitdir:"):
                    head = Path(line.split(":", 1)[1].strip())
                    if not head.is_absolute():
                        head = (root / head).resolve()
                    break
        reference = (head / "HEAD").read_text(encoding="utf-8").strip()
        if not reference.startswith("ref:"):
            return reference or None
        target = head / reference.split(":", 1)[1].strip()
        return target.read_text(encoding="utf-8").strip() if target.is_file() else None
    except OSError:
        return None


def event_catalog(core: Path) -> set[str]:
    """Every event type the catalog declares, read from `docs/event-naming.md`.

    Read from the doc, not from a data file, because the doc is the spec and
    there is no machine-readable catalog: `docs/manifest-conventions.md` rule 6
    ("every consumed type exists in the core catalog") is a rule *about* that
    document. A harness that shipped its own copy of the list would be a second
    catalog, and the drift between the two would be invisible — which is
    decision D22's neighbour and is listed as owed in docs/contract-harness.md.
    """
    text = (core / EVENT_CATALOG_RELATIVE).read_text(encoding="utf-8")
    start = text.find(CATALOG_HEADING)
    if start == -1:
        raise Refusal("core.not-a-checkout", str(EVENT_CATALOG_RELATIVE), "no catalog section")
    catalog = text[start:]
    end = catalog.find("\n## ", 1)
    if end != -1:
        catalog = catalog[:end]
    return set(re.findall(r"^\|\s*`([a-z][a-z0-9_.-]+)`\s*\|", catalog, flags=re.MULTILINE))


# --------------------------------------------------------------------------
# the rules
# --------------------------------------------------------------------------


def check_manifest_schema(manifest: Any, core: Path, service: Path) -> tuple[list[Finding], bool]:
    """`manifest.schema` — the manifest against `schemas/anywaye.manifest.schema.json`.

    The second element of the return says whether the schema held, and it is
    what `run` uses to decide whether the cross-field rules are worth running at
    all. A document whose fields are the wrong type is a document whose
    cross-field comparisons would be comparing nothing, and a finding computed
    from it is a finding about a document nobody wrote. `caf`'s linter makes the
    same call, for the same reason.
    """
    schema = _load_schema(core / MANIFEST_SCHEMA_RELATIVE)
    violations = evaluate(manifest, schema)
    if not violations:
        return [], True
    return [
        Finding("manifest.schema", f"anywaye.yml: {v.path or '<root>'}", v.message)
        for v in violations
    ], False


def check_own_prefix(manifest: dict) -> list[Finding]:
    """`event.own-prefix` — a published type starts with the publisher's name.

    `docs/manifest-conventions.md`, rule 1. Not a schema rule because JSON
    Schema cannot compare two properties of the same instance, and not in
    `schemas/` for the same reason: this function is where the rule is.
    """
    name = manifest.get("name")
    if not isinstance(name, str):
        return []
    return [
        Finding(
            "event.own-prefix", f"anywaye.yml: exposes/events[{index}]",
            f"{event_type!r} must start with this service's own name ({name}.…) — every "
            "event type is <service>.<entity>.<action>",
        )
        for index, event_type in enumerate(_exposes_events(manifest))
        if event_type.split(".")[0] != name
    ]


def check_no_self_consume(manifest: dict) -> list[Finding]:
    """`event.no-self-consume` — a service never consumes its own events.

    Not a schema rule: a set intersection across two arrays, which no JSON
    Schema keyword expresses. In the harness's source, and in
    `docs/manifest-conventions.md` rule 2, which is the document that says so.
    """
    published = set(_exposes_events(manifest))
    consumed = manifest.get("consumes") or []
    if not isinstance(consumed, list):
        return []
    return [
        Finding(
            "event.no-self-consume", f"anywaye.yml: consumes[{index}]",
            f"{event_type!r} is published by this service and must not be in consumes; react "
            "in-process instead of paying for a bus",
        )
        for index, event_type in enumerate(consumed)
        if event_type in published
    ]


def check_unknown_consumed(manifest: dict, catalog: set[str]) -> list[Finding]:
    """`event.unknown-consumed` — every consumed type exists in the catalog.

    `docs/manifest-conventions.md`, rule 6. A subscription to a type nobody
    publishes is a typo that otherwise ships silently and fails at run time, on
    someone else's deploy.
    """
    consumed = manifest.get("consumes") or []
    if not isinstance(consumed, list):
        return []
    return [
        Finding(
            "event.unknown-consumed", f"anywaye.yml: consumes[{index}]",
            f"{event_type!r} is consumed here and no publisher in core's catalog declares it",
        )
        for index, event_type in enumerate(consumed)
        if event_type not in catalog
    ]


def check_unknown_published(manifest: dict, catalog: set[str]) -> list[Finding]:
    """`event.unknown-published` — every published type exists in the catalog.

    The other half of the same fact, and it is a separate rule because it fails
    differently: a published type nothing else has heard of is a service
    announcing an event no subscriber is waiting for, which is a design bug
    rather than a typo, and it is invisible until someone generates a client.
    """
    return [
        Finding(
            "event.unknown-published", f"anywaye.yml: exposes/events[{index}]",
            f"{event_type!r} is published here and core's catalog does not list it, so no "
            "consumer is known to be waiting for it",
        )
        for index, event_type in enumerate(_exposes_events(manifest))
        if event_type not in catalog
    ]


def check_payload_schema(manifest: dict, core: Path) -> list[Finding]:
    """`event.payload-schema-missing` — a published type has a payload schema.

    `schemas/events/<service>/<entity>/<action>.schema.json` is where the `data`
    of a type is described, and a type with no schema is a type whose payload is
    whatever the publisher felt like that week. Existence is the whole check
    here; validating a payload is a live-response test and is not built — see
    docs/contract-harness.md.
    """
    return [
        Finding(
            "event.payload-schema-missing", f"anywaye.yml: exposes/events[{index}]",
            f"{event_type!r} is published with no payload schema at "
            f"schemas/events/{event_type.replace('.', '/')}.schema.json",
        )
        for index, event_type in enumerate(_exposes_events(manifest))
        if not (core / "schemas" / "events" / (event_type.replace(".", "/") + ".schema.json")).is_file()
    ]


def check_core_version(manifest: dict, core: Path, where: str = "anywaye.yml: core") -> list[Finding]:
    """`core.constraint-unmet` — the service compiles against a core it declined.

    The adapter between the harness's finding vocabulary and
    `harness/core_version.py`, and the only reason the resolver is a separate
    module: the grammar is stated once, here is the translation.

    Two of the three rule ids this rule can raise are findings and one is a
    refusal, and that split is the design rather than an implementation detail.
    A service whose `core:` disagrees with what core publishes is **wrong** —
    exit 1, fix the manifest. A core that publishes no version means the check
    **could not happen** — exit 2, fix the checkout. Reporting the second as the
    first would tell a service owner to change a manifest that was not the
    problem, which is the same shape of defect as the four skipped test tiers
    this repository already documents.
    """
    try:
        return core_version.check(manifest, core, Finding, where)
    except core_version.VersionAbsent as absent:
        raise Refusal(
            "core.version-absent", f"{core}/{core_version.VERSION_FILE}", str(absent)
        )


def check_api_file_exists(manifest: dict, service: Path) -> list[Finding]:
    """`manifest.api-file-missing` — `exposes.api` resolves inside the repository.

    The schema pins the *shape* of the path and cannot check that the file is
    there, so this is a rule in the harness. It is the rule a path error breaks:
    `cafe dev`, every SDK generator and this harness itself all resolve the same
    string.
    """
    reference = (manifest.get("exposes") or {}).get("api")
    if not isinstance(reference, str) or not reference:
        return []
    if (service / reference).is_file():
        return []
    return [
        Finding(
            "manifest.api-file-missing", f"anywaye.yml: exposes/api",
            f"{reference!r} does not exist in this repository; exposes.api is resolved by "
            "`cafe dev`, by the SDK generators and by this harness",
        )
    ]


def check_document_is_31(document: dict, where: str) -> list[Finding]:
    """`openapi.document-is-31` — the document declares OpenAPI 3.1.

    `docs/openapi-conventions.md`, "Versioning" and the endpoint checklist. 3.1
    is what makes `null` a type rather than a keyword that changes meaning, and a
    3.0 document cannot express half of what core's payload schemas say.
    """
    declared = document.get("openapi")
    if isinstance(declared, str) and declared.startswith("3.1"):
        return []
    return [
        Finding(
            "openapi.document-is-31", where,
            f"the document declares openapi: {declared!r}; core requires 3.1",
        )
    ]


def check_info_version(document: dict, where: str) -> list[Finding]:
    """`openapi.info-version` — `info.version` is present and `X.Y.Z`.

    `docs/openapi-conventions.md`, "Versioning". It is the only signal a consumer
    has for telling "nothing moved" from "the whole document was regenerated",
    and core's sync rule — a breaking change bumps the prefix *and* the document
    version in the same commit — is stated entirely in terms of it.

    Both numbers are required and they mean different things, so the presence
    check and the parseability check are one rule: a version nobody can parse
    attributes a deprecation to nothing.
    """
    info = document.get("info")
    version = info.get("version") if isinstance(info, dict) else None
    if isinstance(version, str) and SEMVER_VERSION.match(version):
        return []
    return [
        Finding(
            "openapi.info-version", f"{where}: info/version",
            f"info.version is {version!r}; core requires MAJOR.MINOR.PATCH, and the two "
            "version numbers (the /vN prefix and this one) move together",
        )
    ]


def check_has_paths(document: dict, where: str) -> list[Finding]:
    """`openapi.has-paths` — the document declares at least one path.

    **Two empty sets agree.** A reader that finds no paths and returns an empty
    collection lets a service delete its entire HTTP contract and see a green
    build, because "no path violates the `/v1` rule" and "there is no path" are
    the same sentence. courier's `OpenAPIPaths` refuses rather than under-reads
    for exactly this; this is that rule, in the harness.
    """
    paths = document.get("paths")
    if isinstance(paths, dict) and paths:
        return []
    return [
        Finding(
            "openapi.has-paths", f"{where}: paths",
            f"paths is {paths!r}; a document that declares no operation is not a contract, and "
            "an empty set agrees with an empty set",
        )
    ]


def check_paths_are_versioned(document: dict, where: str) -> list[Finding]:
    """`openapi.paths-are-versioned` — every path sits under a `/vN` prefix.

    `docs/openapi-conventions.md`, "Versioning". The prefix is the only version
    that can ever be frozen, because a published endpoint cannot change shape.
    """
    return [
        Finding(
            "openapi.paths-are-versioned", f"{where}: paths -> {path}",
            f"{path!r} is not under a /vN prefix; core versions the path, never the body",
        )
        for path in _paths(document)
        if not VERSION_PREFIX.match(path)
    ]


def check_one_version_prefix(document: dict, where: str) -> list[Finding]:
    """`openapi.one-version-prefix` — one `/vN` per document.

    `docs/openapi-conventions.md`, "Versioning": a breaking change means a new
    prefix *alongside* the old one, and `/v1` is never mutated in place. A
    document carrying two prefixes is a breaking change that landed without one,
    and it is the shape a doc-vs-router drift test cannot see — a route count
    comparison would not notice a rename either.
    """
    prefixes = {
        match.group(1)
        for path in _paths(document)
        if (match := VERSION_PREFIX.match(path))
    }
    if len(prefixes) <= 1:
        return []
    return [
        Finding(
            "openapi.one-version-prefix", f"{where}: paths",
            f"the document carries prefixes v{sorted(prefixes)}; one document describes one "
            "contract version, and a second prefix is a breaking change that must be a "
            "decision rather than an accident",
        )
    ]




def _local_ref(node: Any, root: Any, depth: int = 0) -> tuple[Any, bool]:
    while isinstance(node, dict) and isinstance(node.get("$ref"), str):
        if depth >= MAX_REF_DEPTH:
            return node, False
        pointer = node["$ref"]
        if not pointer.startswith("#/"):
            return node, False
        target = root
        for raw in pointer[2:].split("/"):
            token = raw.replace("~1", "/").replace("~0", "~")
            if isinstance(target, list) and token.isdigit():
                target = target[int(token)]
            elif isinstance(target, dict) and token in target:
                target = target[token]
            else:
                return node, False
        merged = dict(target) if isinstance(target, dict) else {}
        for key, value in node.items():
            if key != "$ref":
                merged[key] = value
        node = merged
        depth += 1
    return node, True


@dataclass(frozen=True)
class _Operation:

    path: str
    method: str
    operation: dict
    parameters: tuple[dict, ...]
    responses: tuple[tuple[str, Any, bool], ...]
    where: str

    def at(self, part: str) -> str:
        return f"{self.where}: paths -> {self.path} {self.method.upper()} -> {part}"


@dataclass(frozen=True)
class _Scan:

    document: dict
    operations: tuple[_Operation, ...]
    unresolved: list[tuple[str, str]]


def _openapi_scan(document: dict, where: str) -> _Scan:
    unresolved: list[tuple[str, str]] = []
    operations: list[_Operation] = []
    paths_node = document.get("paths")
    paths_node = paths_node if isinstance(paths_node, dict) else {}
    for path in _paths(document):
        item, decided = _local_ref(paths_node.get(path), document)
        if not decided:
            unresolved.append((f"#/paths/{path}", f"paths -> {path}"))
            continue
        if not isinstance(item, dict):
            continue
        inherited, _ = _local_ref(item.get("parameters"), document)
        for key in sorted(item):
            if key.lower() not in HTTP_METHODS:
                continue
            operation = item[key]
            if not isinstance(operation, dict):
                continue
            declared: list[Any] = []
            if isinstance(inherited, list):
                declared.extend(inherited)
            own = operation.get("parameters")
            if isinstance(own, list):
                declared.extend(own)
            parameters = []
            for parameter in declared:
                resolved, ok = _local_ref(parameter, document)
                if not ok:
                    unresolved.append((f"paths -> {path} {key} -> parameters", _ref_of(parameter)))
                    continue
                if isinstance(resolved, dict):
                    parameters.append(resolved)
            responses = []
            raw_responses = operation.get("responses")
            if isinstance(raw_responses, dict):
                for status in sorted(raw_responses, key=str):
                    response, ok = _local_ref(raw_responses[status], document)
                    if not ok:
                        unresolved.append(
                            (
                                f"paths -> {path} {key} -> {status}",
                                _ref_of(raw_responses[status]),
                            )
                        )
                    responses.append((str(status), response, ok))
            operations.append(
                _Operation(
                    path=path,
                    method=key.lower(),
                    operation=operation,
                    parameters=tuple(parameters),
                    responses=tuple(responses),
                    where=where,
                )
            )
    return _Scan(document=document, operations=tuple(operations), unresolved=unresolved)


def _ref_of(node: Any) -> str:
    if isinstance(node, dict) and isinstance(node.get("$ref"), str):
        return node["$ref"]
    return "?"


def _is_success(status: str) -> bool:
    return status[:1] == "2"


def _parameter_named(operation: _Operation, name: str, location: str) -> bool:
    for parameter in operation.parameters:
        if not isinstance(parameter.get("name"), str):
            continue
        if parameter["name"].strip().lower() != name:
            continue
        if str(parameter.get("in", "")).lower() != location:
            continue
        return True
    return False


def _problem_media(response: Any) -> dict | None:
    if not isinstance(response, dict):
        return None
    content = response.get("content")
    if not isinstance(content, dict):
        return None
    media = content.get(PROBLEM_MEDIA_TYPE)
    return media if isinstance(media, dict) else None


def _problem_examples(response: Any) -> list[dict]:
    media = _problem_media(response)
    if media is None:
        return []
    found = []
    if isinstance(media.get("example"), dict):
        found.append(media["example"])
    examples = media.get("examples")
    if isinstance(examples, dict):
        for named in examples.values():
            if isinstance(named, dict) and isinstance(named.get("value"), dict):
                found.append(named["value"])
    return found


def check_errors_are_problems(scan: _Scan) -> list[Finding]:
    """`openapi.errors-are-problems` — every non-2xx response is `problem+json`.

    `docs/openapi-conventions.md`, "Error envelope": "Every non-2xx response is
    `application/problem+json` (RFC 9457) with the anywaye extensions below. No
    service invents its own error body."

    **This is the rule that catches the mistake of defining the schema and
    attaching it to nothing.** A document with a careful
    `components.schemas.Problem` — required fields, `trace_id`, `errors[]` with
    per-field codes — and 401 and 404 that describe themselves in prose and
    carry no `content` at all has shipped an error body that no client will ever
    parse, and it reads as conformant to every check that only looks for the
    schema. The schema existing is not the contract being honoured; the
    response carrying it is.

    A response the harness could not read is not reported, and is counted in
    `scan.unresolved` instead. Reporting it would be a false accusation, and the
    warning is the honest answer.
    """
    findings = []
    for operation in scan.operations:
        for status, response, decided in operation.responses:
            if _is_success(status) or not decided:
                continue
            if _problem_media(response) is not None:
                continue
            has_content = isinstance(response, dict) and bool(response.get("content"))
            declared = (
                "declares no application/problem+json"
                if has_content
                else "declares no content at all"
            )
            findings.append(
                Finding(
                    "openapi.errors-are-problems",
                    operation.at(status),
                    f"a {status} response {declared}. docs/openapi-conventions.md requires "
                    f"{PROBLEM_MEDIA_TYPE} on every non-2xx, so a client parsing errors has "
                    "nothing to parse",
                )
            )
    return findings


def check_problem_code_matches_type(scan: _Scan) -> list[Finding]:
    """`openapi.problem-code-matches-type` — `code` is the last segment of `type`.

    `docs/openapi-conventions.md`, "Error envelope": "`type` is a stable
    `https://docs.anywaye.com/errors/<code>` URI — the machine-readable contract", and
    "`code` is the same slug as the last segment of `type`, in `snake_case`."

    **Two fields that must agree, and a client that can only read one of them.**
    A generated SDK keys its error handling off `code` and a human reads `type`;
    when they disagree, one of the two is always the wrong one and nothing in
    the document says which. The rule is stated per example because an example
    is where a document states a value, and a document that states no examples
    has stated nothing this rule can check — which is recorded in rules.json's
    `notEnforced` rather than left to look like a pass.
    """
    findings = []
    for operation in scan.operations:
        for status, response, decided in operation.responses:
            if _is_success(status) or not decided:
                continue
            for body in _problem_examples(response):
                code = body.get("code")
                declared = body.get("type")
                if not isinstance(code, str) or not isinstance(declared, str):
                    continue
                slug = declared.rstrip("/").rsplit("/", 1)[-1]
                if code == slug and SNAKE_CASE_SLUG.match(code):
                    continue
                findings.append(
                    Finding(
                        "openapi.problem-code-matches-type",
                        operation.at(f"{status} example"),
                        f"code is {code!r} and the last segment of type is {slug!r}; the two "
                        "are the same field written twice, and `code` is that segment in "
                        "snake_case",
                    )
                )
    return findings


def check_problem_type_base(scan: _Scan) -> list[Finding]:
    """`openapi.problem-type-base` — every problem `type` sits at the one base.

    `docs/openapi-conventions.md`, "Error envelope": "`type` is a stable
    `https://docs.anywaye.com/errors/<code>` URI", and PLAN §1 stability rule 2,
    which freezes that base for the life of the platform.

    **The base is the half of the contract that is not in the document.**
    `code` and the last segment of `type` are both written in the same example,
    so a reader can compare them by eye; the base is a fact about a namespace
    that lives nowhere in the file being read, and a service that invents its
    own host — or keeps the retired `errors.anywaye.com` one — publishes an
    identifier nobody can dereference. PLAN §3 L3 swept 292 of those
    references out of the fleet, and this rule is what keeps them out: a check
    that only compared the two fields would have passed every one of them,
    because the slug was right in both places.

    A `type` with nothing after the base is reported too: the URI is
    `<base>/<code>` and a trailing slash is a code-less identifier, which is
    the same defect with the collision moved to the root.

    The other half — that `code` is that same last segment — is
    `openapi.problem-code-matches-type`, and stays a separate rule for the
    reason `ERROR_TYPE_BASE` gives.
    """
    findings = []
    for operation in scan.operations:
        for status, response, decided in operation.responses:
            if _is_success(status) or not decided:
                continue
            for body in _problem_examples(response):
                declared = body.get("type")
                if not isinstance(declared, str):
                    continue
                if declared.startswith(ERROR_TYPE_BASE) and len(declared) > len(ERROR_TYPE_BASE):
                    continue
                findings.append(
                    Finding(
                        "openapi.problem-type-base",
                        operation.at(f"{status} example"),
                        f"type is {declared!r} and every anywaye problem type is "
                        f"{ERROR_TYPE_BASE}<code>; a URI at another host is a link "
                        "nobody can follow, and PLAN §1 stability rule 2 freezes this "
                        "one base",
                    )
                )
    return findings


def check_reserved_error_codes(scan: _Scan) -> list[Finding]:
    """`openapi.reserved-error-codes` — a reserved code carries its fixed status.

    `docs/openapi-conventions.md`, "Error envelope" lists nine reserved codes
    with their statuses. The binding is what makes them worth reserving: a
    client that sees `unauthorized` may act on 401 without reading the document,
    and that is only true while every service means the same thing by it.

    **The other direction is not a rule, and `gateway` is why.** `gateway` enumerates
    `invalid_json`, `account_locked` and `payload_too_large` beside the nine;
    `identity` adds two more; core's own conventions name `cursor_expired` and
    `gone`, which are not on the list. "Reserved" means nobody may take one of
    the nine for something else — it does not mean a service may not have a code
    of its own, and a checker that read it as a ceiling would be wrong about five
    of the seven documents in the workspace.

    Read from examples, for the reason `check_problem_code_matches_type` gives.
    """
    findings = []
    for operation in scan.operations:
        for status, response, decided in operation.responses:
            if _is_success(status) or not decided:
                continue
            for body in _problem_examples(response):
                code = body.get("code")
                declared = body.get("status")
                if not isinstance(code, str) or code not in RESERVED_ERROR_CODES:
                    continue
                expected = RESERVED_ERROR_CODES[code]
                if declared == expected:
                    continue
                findings.append(
                    Finding(
                        "openapi.reserved-error-codes",
                        operation.at(f"{status} example"),
                        f"code {code!r} is reserved for {expected}, and the example says "
                        f"status {declared!r}. A reserved code is worth nothing if a client "
                        "cannot read the status out of it",
                    )
                )
    return findings


def check_problem_has_trace_id(scan: _Scan) -> list[Finding]:
    """`openapi.problem-has-trace-id` — the problem schema requires `trace_id`.

    `docs/openapi-conventions.md`, "Error envelope": "`trace_id` is always
    present and always matches the `X-Trace-Id` response header. Support starts
    from this id."

    It is the one field in the envelope nobody can reconstruct: a client that
    got a 500 without it cannot open a ticket that anybody can act on, and the
    id is gone the moment the response is. "Always present" has to be written
    into the schema's `required`, because a property that is merely *declared* is
    optional in OpenAPI and in JSON Schema both.

    **A composition is not decided, and says so.** If the resolved schema has no
    `required` of its own but is built from `allOf`/`anyOf`/`oneOf`, the
    requirement may be inherited from a member, and guessing would mean
    accusing a document of omitting something it declares one level down. Those
    nodes go to `scan.unresolved` and out as `openapi.unresolved-ref`, which is
    the same honesty `openapi.not-declared` exists for.

    All seven documents in the workspace require it — billing, courier,
    darkroom, gateway, identity, muse and pantry, each with `trace_id` in the
    problem schema's `required`. That is the point of a preventive rule, and it
    is also why this rule can be preventive at all: a document that already
    does the right thing is the one that keeps doing it after core ships the
    check.
    """
    findings = []
    compositions = ("allOf", "anyOf", "oneOf")
    for operation in scan.operations:
        for status, response, decided in operation.responses:
            if _is_success(status) or not decided:
                continue
            media = _problem_media(response)
            if media is None:
                continue
            schema, ok = _local_ref(media.get("schema"), scan.document)
            if not ok:
                scan.unresolved.append(
                    (operation.at(f"{status} schema"), _ref_of(media.get("schema")))
                )
                continue
            if not isinstance(schema, dict):
                continue
            required = schema.get("required")
            if isinstance(required, list):
                names = [name for name in required if isinstance(name, str)]
            elif any(key in schema for key in compositions):
                scan.unresolved.append(
                    (
                        operation.at(f"{status} schema"),
                        "a composed schema (allOf/anyOf/oneOf) whose members are not walked",
                    )
                )
                continue
            else:
                names = []
            if "trace_id" in names:
                continue
            findings.append(
                Finding(
                    "openapi.problem-has-trace-id",
                    operation.at(f"{status} schema"),
                    f"the problem schema requires {names} and not `trace_id`. docs/"
                    "openapi-conventions.md says trace_id is always present — a property that "
                    "is only declared is optional, and a 500 nobody can trace is a 500 nobody "
                    "will fix",
                )
            )
    return findings


def check_no_offset_pagination(scan: _Scan) -> list[Finding]:
    """`openapi.no-offset-pagination` — no offset-style request parameter.

    `docs/openapi-conventions.md`, "Pagination": "Cursor-based everywhere,
    including for admin and export endpoints. Offset pagination does not scale
    past a few thousand rows and cannot be stable while rows are being inserted."

    The second clause is the one that decides it. An offset skips rows that were
    inserted before it, so a client walking a list while the list is being
    written to silently reads the same row twice and drops another — and it is
    not visible in testing, because testing does not insert. "Including for
    admin and export endpoints" is the other half: the exception everybody wants
    is the exception the document has already refused.

    A named list rather than a pattern; see `OFFSET_PARAMETER_NAMES` for why,
    and for what is deliberately left alone.
    """
    findings = []
    for operation in scan.operations:
        for parameter in operation.parameters:
            name = parameter.get("name")
            if not isinstance(name, str) or str(parameter.get("in", "")).lower() != "query":
                continue
            if name.strip().lower() not in OFFSET_PARAMETER_NAMES:
                continue
            findings.append(
                Finding(
                    "openapi.no-offset-pagination",
                    operation.at(f"parameter {name}"),
                    f"a query parameter named {name!r} is offset pagination. "
                    "docs/openapi-conventions.md requires a cursor: an offset skips rows "
                    "inserted before it, so a client paging a list that is being written to "
                    "reads a row twice and drops another",
                )
            )
    return findings


def _is_paginated(operation: _Operation, document: dict) -> bool:
    for parameter in operation.parameters:
        if str(parameter.get("in", "")).lower() != "query":
            continue
        name = parameter.get("name")
        if isinstance(name, str) and name.strip().lower() in PAGINATION_REQUEST_PARAMETERS:
            return True
    shape = _success_schema_shape(operation, document)
    return bool(shape & {"page", "offset"})


def _success_response(operation: _Operation) -> tuple[Any, bool] | None:
    for status, response, decided in operation.responses:
        if _is_success(status) and status != "default":
            return response, decided
    return None


def _success_schema(operation: _Operation, document: dict) -> dict | None:
    found = _success_response(operation)
    if found is None:
        return None
    response, decided = found
    if not decided:
        return None
    content = response.get("content") if isinstance(response, dict) else None
    if not isinstance(content, dict):
        return None
    for media_type in sorted(content):
        media = content[media_type]
        if not isinstance(media, dict):
            continue
        schema, _ok = _local_ref(media.get("schema"), document)
        if isinstance(schema, dict):
            return schema
    return None


def _success_schema_shape(operation: _Operation, document: dict) -> set:
    schema = _success_schema(operation, document)
    if not isinstance(schema, dict):
        return set()
    properties = schema.get("properties")
    return set(properties) if isinstance(properties, dict) else set()


def _types_of(schema: Any) -> set:
    if not isinstance(schema, dict):
        return set()
    declared = schema.get("type")
    if isinstance(declared, str):
        return {declared}
    if isinstance(declared, list):
        return {name for name in declared if isinstance(name, str)}
    return set()


def check_page_envelope(scan: _Scan) -> list[Finding]:
    """`openapi.page-envelope` — cursor in, `{data, page}` out.

    `docs/openapi-conventions.md`, "Pagination": request `?limit=50&cursor=
    <opaque>&order=asc|desc`, response `{"data": [...], "page": {"next_cursor":
    …, "has_more": …}}`, "`data` is always an array, empty rather than absent",
    "`page.next_cursor` is `null` on the last page".

    Both halves are one rule because they are one sentence in the document and
    because a client that sends a cursor and receives something else has to
    handle two pagination protocols. Splitting them would produce two rules that
    always fire together, which is the coupling `event.payload-schema-missing`
    records and wishes it did not have.

    **`limit` without `cursor` is the interesting half.** A service that exposes
    `limit` alone has half-adopted the convention and is still answering with
    something that is not a page — `identity`'s audit log declares `limit` and
    `before` and answers `{"entries": …, "next": …}`, which is a correct
    pagination design and not core's. This rule says so by name.
    """
    findings = []
    for operation in scan.operations:
        if not _is_paginated(operation, scan.document):
            continue
        if not _parameter_named(operation, "cursor", "query"):
            findings.append(
                Finding(
                    "openapi.page-envelope",
                    operation.at("parameters"),
                    "this operation pages and does not accept a `cursor`. "
                    "docs/openapi-conventions.md fixes the request shape at "
                    "?limit=50&cursor=<opaque>&order=, and an offset or a page number "
                    "under any spelling is the thing the convention exists to stop",
                )
            )
        schema = _success_schema(operation, scan.document)
        if schema is None:
            continue
        shape = _success_schema_shape(operation, scan.document)
        missing = {"data", "page"} - shape
        if missing:
            findings.append(
                Finding(
                    "openapi.page-envelope",
                    operation.at("2xx schema"),
                    f"a paginated operation whose success body declares {sorted(shape)} and "
                    f"not {sorted(missing)}. docs/openapi-conventions.md fixes the response "
                    "at {\"data\": [...], \"page\": {\"next_cursor\": …, \"has_more\": …}}",
                )
            )
            continue
        properties = schema.get("properties") or {}
        data = properties.get("data")
        if "array" not in _types_of(data):
            findings.append(
                Finding(
                    "openapi.page-envelope",
                    operation.at("2xx schema -> data"),
                    f"`data` is declared {_types_of(data) or 'untyped'}; it is always an array, "
                    "empty rather than absent, so a client never has to ask whether a page "
                    "with no rows is a null",
                )
            )
        page = properties.get("page")
        page_properties = page.get("properties") if isinstance(page, dict) else None
        if not isinstance(page_properties, dict):
            return findings
        for field in ("next_cursor", "has_more"):
            if field in page_properties:
                continue
            findings.append(
                Finding(
                    "openapi.page-envelope",
                    operation.at(f"2xx schema -> page.{field}"),
                    f"`page.{field}` is not declared. A client cannot tell the end of a "
                    "collection from an unbounded one without it, which is why the "
                    "conventions put next_cursor at null rather than omitting it",
                )
            )
    return findings


def check_idempotency_key(scan: _Scan) -> list[Finding]:
    """`openapi.idempotency-key` — every mutating `POST` accepts the header.

    `docs/openapi-conventions.md`, "Idempotency": "Mutating `POST` endpoints
    that can be retried safely **must** accept `Idempotency-Key`", and the
    checklist says the same in one line: "`Idempotency-Key` accepted on every
    safe-to-retry `POST`."

    **Why the header and not a `409`.** An at-least-once caller — a client
    retrying on a timeout, an event consumer, the outbox's own redelivery — has
    no way to know whether the first attempt landed. Without a key the only
    retry that is safe is no retry, which means the endpoint is a single point of
    failure with a 200 in front of it. With a key the retry is free, and
    `Idempotency-Replayed: true` tells the caller it is looking at the first
    answer.

    **A document cannot say "this POST is unsafe to retry", and that is a real
    gap.** The convention's phrase is "that can be retried safely", which is a
    property of the implementation, not of the document — so this rule takes
    every `POST`. It is the strict reading and it is named as such in rules.json
    and in the report; the cheapest way to loosen it is one `x-anywaye-no-
    idempotency` branch in this function, which is deliberately not written
    because inventing a vendor extension is a contract change and not a worker's
    call.

    `POST` only, not `PUT` and `PATCH`. Those are idempotent by definition in
    HTTP, which is the entire reason the header is needed on `POST` and is a
    fact about the method rather than about this convention.
    """
    findings = []
    for operation in scan.operations:
        if operation.method != "post":
            continue
        if _parameter_named(operation, IDEMPOTENCY_HEADER, "header"):
            continue
        name = operation.operation.get("operationId") or f"{operation.method} {operation.path}"
        findings.append(
            Finding(
                "openapi.idempotency-key",
                operation.at("parameters"),
                f"{name} is a mutating POST that does not accept an `Idempotency-Key` "
                "header. docs/openapi-conventions.md requires it, and without it a caller "
                "who retries on a timeout cannot know whether the first attempt landed — "
                "which for a webhook registration or a payment is a duplicate",
            )
        )
    return findings


def check_idempotency_conflict_documented(scan: _Scan) -> list[Finding]:
    """`openapi.idempotency-conflict-documented` — and it documents the 409.

    `docs/openapi-conventions.md`, "Idempotency": "Replay with the same key but
    a different body returns 409 `idempotency_key_reused`."

    The rule is that the 409 must be *declared*, not that its example must carry
    that exact code: a `POST` may legitimately 409 on a plain `conflict` for an
    unrelated uniqueness check, and insisting on the code would make a document
    that says nothing wrong look wrong. What must be there is the path itself —
    a client that has sent a key has to be able to look up in the document what
    happens when it sends the key twice with different bytes, and an operation
    with no `409` in it has told that client nothing.

    A `4XX` wildcard is accepted; a `default` is not, because `default` hides
    the path rather than describing it, which is the difference between
    documenting a behaviour and declining to be wrong about it.
    """
    findings = []
    for operation in scan.operations:
        if operation.method != "post":
            continue
        if not _parameter_named(operation, IDEMPOTENCY_HEADER, "header"):
            continue
        statuses = {status for status, _response, decided in operation.responses}
        if "409" in statuses or "4XX" in statuses or "4xx" in statuses:
            continue
        findings.append(
            Finding(
                "openapi.idempotency-conflict-documented",
                operation.at("responses"),
                f"this POST accepts Idempotency-Key and declares {sorted(statuses) or 'no'} "
                "response statuses — no 409. docs/openapi-conventions.md: replaying a key "
                "with a different body returns 409 idempotency_key_reused, and a client "
                "holding a key cannot act on a path the document does not describe",
            )
        )
    return findings


def _api_documents_on_disk(service: Path) -> list[str]:
    found = []
    for name in OPENAPI_DOCUMENT_GLOBS:
        if (service / name).is_file():
            found.append(name)
    for directory in OPENAPI_DOCUMENT_DIRECTORIES:
        root = service / directory
        if not root.is_dir():
            continue
        for path in sorted(root.iterdir()):
            if path.is_file() and path.suffix in OPENAPI_DOCUMENT_SUFFIXES:
                found.append(f"{directory}/{path.name}")
    return sorted(set(found))



SLO_DIRECTORY = "slos"
SLO_SUFFIXES = (".yaml", ".yml")

SLO_SCHEMA_RELATIVE = Path("schemas") / "telemetry" / "slo.schema.json"
SLO_CATALOGUE_RELATIVE = Path("schemas") / "telemetry" / "slo-metrics.schema.json"

SLO_WINDOW_TOKEN = "{{.window}}"

SLO_SELECTOR = re.compile(r"([a-z][a-z0-9_]*)\{([^{}]*)\}")

SLO_MATCHER = re.compile(r'([a-z][a-z0-9_]*)="([^"]*)"')

SLO_WINDOW_OVERRIDE_KEYS = (
    "windows",
    "window",
    "factor",
    "slo_period_windows",
    "slo_period_windows_path",
    "period_windows",
    "burn_rate_windows",
    "burnRateWindows",
)


def slo_files(service: Path) -> list[Path]:
    """Every SLO declaration in a service, or none.

    No `slos/` directory is not a refusal: `worker-only.anywaye.yml` declares no
    `exposes.api` and is a valid manifest, so a repository with no HTTP contract
    is checked on no HTTP rules and passes. A service that declares nothing
    declares nothing. What must never happen is the absence reading as a pass
    over the SLOs it *has*, which is what the rules below are for.
    """
    directory = service / SLO_DIRECTORY
    if not directory.is_dir():
        return []
    return [
        path
        for path in sorted(directory.iterdir())
        if path.is_file() and path.suffix in SLO_SUFFIXES
    ]


def load_slo_catalogue(core: Path) -> dict:
    """The SLI catalogue, read out of core's own schema.

    Three things come out of it: the metric names any query may use, the label
    allowlist, and the two denylists. All of it from `schemas/`, so the digest
    `--expect-digest` pins covers the catalogue too — a second copy in this file
    would be a second answer to "which metrics exist", which is the drift the
    digest exists to prevent.
    """
    schema = _load_schema(core / SLO_CATALOGUE_RELATIVE)
    entries = schema["properties"]["slis"]["properties"]
    return {
        "slis": {
            name: {
                "totalMetric": entry["properties"]["totalMetric"]["const"],
                "errorMetric": entry["properties"]["errorMetric"]["const"],
                "errorSelector": entry["properties"]["errorSelector"]["default"],
                "requiredLabels": entry["properties"]["requiredLabels"]["default"],
                "labels": entry["properties"]["labels"]["items"]["enum"],
            }
            for name, entry in entries.items()
        },
        "metrics": {
            metric
            for entry in entries.values()
            for metric in (
                entry["properties"]["totalMetric"]["const"],
                entry["properties"]["errorMetric"]["const"],
            )
        },
        "allowedLabels": schema["properties"]["allowedLabels"]["items"]["enum"],
        "forbidden": {
            group: values["items"]["enum"]
            for group, values in schema["properties"]["forbidden"]["properties"].items()
        },
    }


def _slo_entries(document: Any) -> list[dict]:
    slos = document.get("slos") if isinstance(document, dict) else None
    if not isinstance(slos, list):
        return []
    return [slo for slo in slos if isinstance(slo, dict)]


def _slo_queries(slo: dict) -> list[tuple[str, str]]:
    events = slo.get("sli")
    events = events.get("events") if isinstance(events, dict) else None
    if not isinstance(events, dict):
        return []
    return [
        (role, events[role])
        for role in ("total_query", "error_query")
        if isinstance(events.get(role), str)
    ]


def slo_matchers(labels: Any, service: Any, extra: dict) -> str:
    """The selector body, canonical: sorted, comma-separated, no spaces.

    A canonical spelling is what makes "exactly this string" checkable. Without
    one, `check_slo_sli_is_canonical` would have to parse PromQL to compare two
    queries that mean the same thing, and this repository does not parse PromQL.
    `service_name` comes from the declaration's `service` field and cannot be
    overridden by the SLO's own `labels`, which is one of the two reasons the
    schema refuses that key there.
    """
    matchers = dict(labels) if isinstance(labels, dict) else {}
    matchers.pop("service_name", None)
    if isinstance(service, str):
        matchers["service_name"] = service
    matchers.update(extra)
    return ",".join(f'{name}="{value}"' for name, value in sorted(matchers.items()))


def slo_query(metric: str, labels: Any, service: Any, extra: dict) -> str:
    """The one expression an SLI may be, for a catalogue entry and a set of labels."""
    body = slo_matchers(labels, service, extra)
    return f"sum(rate({metric}{{{body}}}[{SLO_WINDOW_TOKEN}]))"


def check_slo_schema(document: Any, core: Path, where: str) -> list[Finding]:
    """`slo.schema` — the declaration against `slo.schema.json`.

    The schema is where the 28-day period, the tier that alone derives both alert
    switches, the refusal of the acronym an agreement would carry, and
    `objective` with an exclusive maximum of 100 all live. A service that sets
    `page_alert.disable: false` on a `low` SLO is asking for a 3am page about a
    twenty-user deployment, and this is the rule that says so.
    """
    schema = _load_schema(core / SLO_SCHEMA_RELATIVE)
    return [
        Finding("slo.schema", f"{where}: {violation.path or '<root>'}", violation.message)
        for violation in evaluate(document, schema)
    ]


def check_slo_window_token(slo: dict, where: str) -> list[Finding]:
    """`slo.window-token` — both queries carry `{{.window}}`.

    The highest-value check in this file, and the one Sloth does not make. Sloth
    substitutes the token with each burn-rate window when it generates the alerts;
    a query without it evaluates over whatever window the recording rule happens
    to carry. The alert still fires, still looks plausible, and is measuring a
    different period from the one its own label names.
    """
    return [
        Finding(
            "slo.window-token", f"{where}: sli/events/{role}",
            f"the query has no {SLO_WINDOW_TOKEN} token, so the generated alert evaluates it "
            "over the recording rule's window rather than this burn-rate window",
        )
        for role, query in _slo_queries(slo)
        if SLO_WINDOW_TOKEN not in query
    ]


def check_slo_metric_allowlist(slo: dict, catalogue: dict, where: str) -> list[Finding]:
    """`slo.unknown-metric` — every metric in a query is one core names.

    This allowlist is the check that replaces a shared client library. A metric
    name nothing exports does not fail loudly: Prometheus answers `no data`, the
    SLI reports an error rate of zero, no budget is burned, and the service is
    free to be on fire for a quarter.
    """
    allowed = catalogue["metrics"]
    found = []
    for role, query in _slo_queries(slo):
        for metric, _ in SLO_SELECTOR.findall(query):
            if metric not in allowed:
                found.append(Finding(
                    "slo.unknown-metric", f"{where}: sli/events/{role}",
                    f"{metric!r} is not a metric any anywaye SLI may count. The catalogue is "
                    "schemas/telemetry/slo-metrics.schema.json, and a query on anything else "
                    "reads `no data` — which reports an error rate of zero",
                ))
    return found


def _denylisted(
    slo: dict, catalogue: dict, group: str, rule: str, reason: str, where: str
) -> list[Finding]:
    needles = catalogue["forbidden"].get(group) or []
    haystacks: list[tuple[str, str]] = []
    labels = slo.get("labels")
    if isinstance(labels, dict):
        for name, value in labels.items():
            haystacks.append((f"{where}: labels", f"{name}={value}"))
    for role, query in _slo_queries(slo):
        text = query
        for matchers in SLO_SELECTOR.findall(query):
            text += " " + matchers[1]
        haystacks.append((f"{where}: sli/events/{role}", text))
    return [
        Finding(
            rule, path,
            f"{needle!r} appears in {haystack!r}, and {reason}",
        )
        for path, haystack in haystacks
        for needle in needles
        if needle in haystack
    ]


def check_slo_unbounded_dimension(slo: dict, catalogue: dict, where: str) -> list[Finding]:
    """`slo.no-unbounded-dimension` — no unbounded dimension in a query.

    **Cardinality, and already decided elsewhere.** OpenTelemetry caps aggregation
    at 2000 distinct attribute combinations and folds everything into one point on
    overflow, dropping every measurement attribute: totals stay right and every
    breakdown undercounts, silently. `metrics.schema.json` prohibits all four of
    these as measurement attributes and *requires* `tenant_id` and `account_id` on
    `resourceAttributes`, which are exempt from the cap. A per-tenant SLI is
    therefore not merely discouraged — it is unreachable, and the honest form of a
    per-tenant view is a recording rule over the resource attributes.
    """
    return _denylisted(
        slo, catalogue, "unboundedDimensions", "slo.no-unbounded-dimension",
        "it is an unbounded identifier. metrics.schema.json already bars it as a "
        "measurement attribute on the 2000-combination-cap grounds, and the place for it "
        "is resourceAttributes — where it is exempt from the cap. Per-tenant answers are "
        "recording rules and logs and traces, not a metric dimension.",
        where,
    )


def check_slo_infrastructure_signal(slo: dict, catalogue: dict, where: str) -> list[Finding]:
    """`slo.no-infrastructure-slo` — no infrastructure signal in a query.

    **Not a cardinality rule: an SLO on these is not an SLO.** `cpu`, `memory`,
    pod churn and restarts describe the machine the service runs on and nothing a
    user can notice — a crash-restart loop on a service nobody is calling is green
    in every user-visible measure and red in every infrastructure one. They are
    also the measures a deployment has to keep away from its limits, which is a
    capacity decision with an owner and a lead time rather than an error budget.
    """
    return _denylisted(
        slo, catalogue, "infrastructureSignals", "slo.no-infrastructure-slo",
        "an SLO on it is not an SLO on behaviour. It measures the machine rather than "
        "anything a user can notice, and keeping it away from its limits is a capacity "
        "decision with an owner and a lead time, not an error budget a pager spends.",
        where,
    )


def check_slo_sli_is_canonical(
    slo: dict, catalogue: dict, service: Any, where: str
) -> list[Finding]:
    """`slo.sli-canonical` — the queries are what the catalogue entry composes to.

    The strongest check in this file and the one Sloth has no equivalent of: each
    query must be **exactly** `sum(rate(<metric>{<labels>}[{{.window}}]))`, with the
    metric, the labels and the bad-half matcher all coming from the catalogue entry
    the SLO names. R7 constrains the SLI's *shape* rather than its content, and
    every alerting rule, budget calculator and report we will ever write assumes a
    numerator, a denominator and a threshold — so a hand-written numerator is how
    one fleet ends up with seven error rates and no way to compare them.

    It also catches what a label allowlist cannot: a query that selects the wrong
    *population* while naming nothing forbidden.
    """
    slis = slo.get("sli")
    name = slis.get("catalogEntry") if isinstance(slis, dict) else None
    if not isinstance(name, str):
        return []
    entry = catalogue["slis"].get(name)
    if entry is None:
        return [Finding(
            "slo.sli-canonical", f"{where}: sli/catalogEntry",
            f"{name!r} is not an entry in core's SLI catalogue. An SLO whose SLI is not in "
            "the catalogue names no metric and no labels anyone else can check it against.",
        )]
    labels = slo.get("labels") if isinstance(slo.get("labels"), dict) else {}
    found = [
        Finding(
            "slo.sli-canonical", f"{where}: labels",
            f"the catalogue entry {name!r} requires {label!r}, and this SLO does not pin it. "
            "An operation-scoped SLI that does not say which operation is a service-scoped "
            "one wearing a specific name.",
        )
        for label in entry["requiredLabels"]
        if not labels.get(label)
    ]
    events = slis.get("events") if isinstance(slis.get("events"), dict) else {}
    for role, extra in (("total_query", {}), ("error_query", entry["errorSelector"])):
        metric = entry["totalMetric"] if role == "total_query" else entry["errorMetric"]
        expected = slo_query(metric, labels, service, extra)
        query = events.get(role)
        if not isinstance(query, str) or query == expected:
            continue
        found.append(Finding(
            "slo.sli-canonical", f"{where}: sli/events/{role}",
            f"the query is not the canonical composition of {name!r} for this service's "
            f"labels. expected: {expected} declared: {query}",
        ))
    return found


def check_slo_window_override(document: Any, where: str) -> list[Finding]:
    """`slo.window-override` — no burn-rate catalog of the service's own.

    The catalog is pinned once, in core, and `slo-windows.schema.json` refuses a
    ninth window. Sloth takes `--slo-period-windows-path` so a project can carry
    its own, which is exactly why the declaration is closed. Reported by name as
    well as by `additionalProperties`, because a service that adds this key wants
    to know it is overriding the fleet's windows and not merely misspelling a
    field.
    """
    found: list[Finding] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                child = _join(path, key)
                if key in SLO_WINDOW_OVERRIDE_KEYS:
                    found.append(Finding(
                        "slo.window-override", f"{where}: {child}",
                        f"{key!r} would give this service its own burn-rate catalog. The "
                        "windows are pinned once, in core, at 14.4/6/3/1 — two dashboards "
                        "that both say \"error budget\" and disagree about the threshold is "
                        "worse than one dashboard.",
                    ))
                walk(value, child)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, _join(path, index))

    walk(document, "")
    return found


def check_slo_names_are_unique(declarations: list[tuple[Path, Any]]) -> list[Finding]:
    """`slo.duplicate-name` — one name per SLO, across the service's files.

    The generated recording rules and alerts are keyed by `<service>-<name>`, so
    two SLOs sharing a name means Prometheus keeps the second and the first is
    silently unreferenced. `sloth validate` catches duplicate identities inside
    one file; this is the half that spans files, and it is here because the
    harness is what a service runs when Sloth is not available.
    """
    seen: dict[tuple[Any, Any], str] = {}
    found = []
    for path, document in declarations:
        for index, slo in enumerate(_slo_entries(document)):
            key = (document.get("service"), slo.get("name"))
            if key[0] is None or key[1] is None:
                continue
            where = f"{SLO_DIRECTORY}/{path.name}: slos[{index}]"
            if key in seen:
                found.append(Finding(
                    "slo.duplicate-name", where,
                    f"{key[1]!r} is declared twice for {key[0]!r}; it is also in {seen[key]}. "
                    "The recording rules and the alerts are keyed by this name, so Prometheus "
                    "keeps one of them and the other is unreferenced.",
                ))
            else:
                seen[key] = where
    return found


def _check_slos(service: Path, core: Path) -> list[Finding]:
    files = slo_files(service)
    if not files:
        return []
    catalogue = load_slo_catalogue(core)
    findings: list[Finding] = []
    declarations: list[tuple[Path, Any]] = []
    for path in files:
        where = f"{SLO_DIRECTORY}/{path.name}"
        document = read_yaml(path.read_text(encoding="utf-8"), path)
        if not isinstance(document, dict):
            raise Refusal(
                "yaml.unsupported", str(path), "an SLO declaration must be a mapping"
            )
        declarations.append((path, document))
        findings.extend(check_slo_window_override(document, where))
        findings.extend(check_slo_schema(document, core, where))
        for index, slo in enumerate(_slo_entries(document)):
            at = f"{where}: slos[{index}]"
            findings.extend(check_slo_window_token(slo, at))
            findings.extend(check_slo_metric_allowlist(slo, catalogue, at))
            findings.extend(check_slo_unbounded_dimension(slo, catalogue, at))
            findings.extend(check_slo_infrastructure_signal(slo, catalogue, at))
            findings.extend(
                check_slo_sli_is_canonical(slo, catalogue, document.get("service"), at)
            )
    findings.extend(check_slo_names_are_unique(declarations))
    return findings



POSTGRES_REPOSITORY = "postgres"

POSTGRES_TAG_FILE = "POSTGRES_TAG"

POSTGRES_TAG_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

POSTGRES_FLOATING_TAG = "latest"

IMAGE_KEY = "image"

COMPOSE_FILE_PATTERN = re.compile(r"^(docker-)?compose(\..+)?\.(ya?ml)$")

COMPOSE_SCAN_DEPTH = 2

COMPOSE_SCAN_MAX_DIRECTORIES = 2000

COMPOSE_SCAN_SKIP = frozenset(
    {
        ".git", ".venv", "venv", "node_modules", "vendor", "deps", "_build",
        "target", "build", "dist", ".next", ".nuxt", ".tox", ".mypy_cache",
        ".pytest_cache", ".ruff_cache", "coverage", ".elixir_ls", ".gradle",
        ".terraform", "site-packages", "htmlcov",
    }
)

WORKFLOW_DIRECTORY = Path("ci")

SCRIPT_DIRECTORY = "bin"
SCRIPT_FILE_NAMES = ("Makefile", "makefile")
SCRIPT_GLOBS = ("*.sh",)

CONTAINER_IMAGE_VERBS = ("run", "create")

CONTAINER_RUNTIME_PATTERN = re.compile(
    r"(?:^|[;&|]\s*|\(\s*)(?:sudo\s+)?(docker|podman)\b"
)
COMPOSE_RUN_PATTERN = re.compile(r"^(?:docker\s+compose|docker-compose)$")

POSTGRES_EXCEPTIONS_FILE = "postgres-pin-exceptions.yaml"

POSTGRES_EXCEPTION_FIELDS = ("reason", "owner", "until")


def read_postgres_tag(core_root: Path) -> str:
    """Read the postgres tag core publishes, or refuse.

    Raises `Refusal("compose.postgres-tag-absent")` for anything that is not one
    readable line, on exactly the reasoning `core.version-absent` gives: a core
    that publishes no standard cannot have the standard enforced against it, and
    a run that cannot find what it is checking has converted an unknown into a
    pass. That is a **refusal, exit 2** — not a violation, because a service's
    compose file is not the thing that is broken.
    """
    path = Path(core_root) / POSTGRES_TAG_FILE
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise Refusal(
            "compose.postgres-tag-absent", str(path),
            f"no readable {POSTGRES_TAG_FILE}: {error}",
        ) from error
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) != 1:
        raise Refusal(
            "compose.postgres-tag-absent", str(path),
            f"{path} holds {len(lines)} non-blank lines, want exactly 1: a tag file "
            f"that has been appended to is not a tag, and reading the first line would "
            f"make it one again",
        )
    tag = lines[0]
    if not POSTGRES_TAG_PATTERN.match(tag):
        raise Refusal(
            "compose.postgres-tag-absent", str(path),
            f"{path} holds {tag!r}, which is not a docker tag: the rule compares it for "
            f"equality with every image reference a service makes, so a value that is "
            f"not a tag makes every comparison meaningless",
        )
    if tag == POSTGRES_FLOATING_TAG:
        raise Refusal(
            "compose.postgres-tag-absent", str(path),
            f"{path} holds {tag!r}. That is the one value a tag can take that is "
            f"guaranteed to change, so declaring it would make the rule pass exactly "
            f"the references it exists to fail.",
        )
    return tag


@dataclass(frozen=True)
class _ImageRef:

    raw: str
    kind: str
    tag: str | None

    @property
    def summary(self) -> str:
        """The reference as a reader should see it, and no longer.

        A digest is truncated to twelve characters on purpose. It is not a secret,
        and it is still 64 characters of hex that says nothing a reader needs and
        pushes the sentence that explains the finding off the end of the line.
        """
        if self.kind == "digest":
            return f"{self.raw[:19]}… ({len(self.raw)} characters)"
        return self.raw


def _resolve_compose_default(value: str) -> str | None:
    text = value
    while True:
        match = re.search(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(:?[-=?])([^{}]*)\}", text)
        if match is None:
            break
        name, operator, operand = match.groups()
            return None
        if operator == "?":
            return None
        text = text[: match.start()] + operand + text[match.end():]
    if "${" in text or re.search(r"\$[A-Za-z_{]", text):
        return None
    return text


def parse_image_reference(value: Any) -> _ImageRef | None:
    """Read one `image:` value, or `None` if it does not name a postgres image.

    `None` means "not this rule's business", and it is the answer for the
    sibling images a compose file carries — `redis:7.4.1-alpine`,
    `grafana/grafana:11.3.0`, a service's own `anywaye/muse:dev`. The repository
    must be `postgres`, optionally registry-qualified, because a repository named
    `postgres` under someone's namespace is that namespace's image and the fleet
    standard says nothing about it.

    The DSN guard falls out of the tag pattern rather than being special-cased,
    and it is worth saying why it is load-bearing: `postgres://user:pass@host/db`
    is not a rare string in this fleet, it is a **secret-bearing** one, and a
    scanner that read `postgres:` at the start of it as a floating image
    reference would print a connection string — password and all — into a build
    log as the *evidence* for a finding. A tag cannot begin with `/`, so
    `postgres://…` matches nothing here, and `test_a_dsn_is_not_a_postgres_image_
    reference` runs this function over core's own self-test scripts, which really
    do contain `postgres://gate:should-never-be-printed@localhost:5432/gate`.
    """
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if "${" in raw or re.search(r"(?<!\\)\$[A-Za-z_{]", raw):
        expanded = _resolve_compose_default(raw)
        if expanded is None:
            return _ImageRef(raw=raw, kind="variable", tag=None)
        return parse_image_reference(expanded)
    if "@" in raw:
        name, _, digest = raw.partition("@")
        if not digest.startswith("sha256:"):
            return None
        repository, separator, tag = name.partition(":")
        if not _is_postgres(repository):
            return None
        if separator and POSTGRES_TAG_PATTERN.match(tag):
            return _ImageRef(raw=raw, kind="digest", tag=tag)
        return _ImageRef(raw=raw, kind="digest", tag=None) if _is_postgres(name) else None
    name, separator, tag = raw.partition(":")
    if not _is_postgres(name):
        return None
    if not separator:
        return _ImageRef(raw=raw, kind="untagged", tag=None)
    if not POSTGRES_TAG_PATTERN.match(tag):
        return _ImageRef(raw=raw, kind="untagged", tag=None)
    return _ImageRef(raw=raw, kind="tag", tag=tag)


def _is_postgres(repository: str) -> bool:
    return repository == POSTGRES_REPOSITORY or repository.endswith(
        f"/{POSTGRES_REPOSITORY}"
    )


@dataclass(frozen=True)
class _Pin:

    path: str
    where: str
    line: int | None
    reference: _ImageRef

    def located(self) -> str:
        """The finding's `path`: greppable, and never a bare filename.

        YAML declarations get a structural location (`docker-compose.yml
        services/postgres/image`) because the reader has one and a line number
        would be a second, drifting, way of naming the same fact. Script
        declarations get `path:line` because a script has no structure to name
        and the line is the only handle a reader has.
        """
        if self.line is None:
            return f"{self.path} {self.where}"
        return f"{self.path}:{self.line}"


def _walk_compose_files(service: Path) -> tuple[list[Path], list[Path]]:
    inside: list[Path] = []
    outside: list[Path] = []
    visited = 0
    exhausted = False

    def visit(directory: Path, depth: int) -> None:
        nonlocal visited, exhausted
        if exhausted:
            return
        visited += 1
        if visited > COMPOSE_SCAN_MAX_DIRECTORIES:
            exhausted = True
            return
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            return
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if entry.name not in COMPOSE_SCAN_SKIP:
                    visit(entry, depth + 1)
                continue
            if not entry.is_file() or not COMPOSE_FILE_PATTERN.match(entry.name):
                continue
            relative = entry.relative_to(service)
            if len(relative.parts) - 1 <= COMPOSE_SCAN_DEPTH:
                inside.append(entry)
            else:
                outside.append(entry)

    visit(service, 0)
    if exhausted:
        outside.append(service)
    return inside, outside


def _yields_pin(document: Any) -> Any:
    stack: list[tuple[Any, tuple[Any, ...]]] = [(document, ())]
    while stack:
        node, path = stack.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                here = path + (key,)
                if key == IMAGE_KEY:
                    yield "/".join(str(part) for part in here), value
                stack.append((value, here))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                stack.append((value, path + (index,)))


def postgres_references(service: Path) -> tuple[list[_Pin], list[Path]]:
    """Every postgres image declaration in a repository, and the files missed.

    Bounded in three ways, each of which is a decision recorded in the constants
    above: compose files are matched by name inside `COMPOSE_SCAN_DEPTH`, the
    workflows directory is read one level deep because GitHub supports no other,
    and scripts are the root's own shell files and `Makefile`. Nothing here
    recurses into a dependency directory, follows a symlink, or reaches for the
    network.
    """
    pins: list[_Pin] = []
    missed: list[Path] = []
    compose_files, below_bound = _walk_compose_files(service)
    missed.extend(below_bound)
    candidates: list[tuple[Path, str]] = [(path, "compose") for path in compose_files]

    workflows = service / WORKFLOW_DIRECTORY
    if workflows.is_dir():
        candidates.extend(
            (entry, "workflow")
            for entry in sorted(workflows.iterdir())
            if entry.is_file() and not entry.is_symlink() and entry.suffix in (".yml", ".yaml")
        )

    for path, source in candidates:
        try:
            document = read_yaml(path.read_text(encoding="utf-8"), path)
        except Refusal:
            continue
        except OSError:
            continue
        relative = path.relative_to(service).as_posix()
        for where, value in _yields_pin(document):
            reference = parse_image_reference(value)
            if reference is not None:
                pins.append(
                    _Pin(
                        path=relative,
                        where=f"{source} {where}",
                        line=None,
                        reference=reference,
                    )
                )

    for path in _script_files(service):
        relative = path.relative_to(service).as_posix()
        for number, line in _script_pin_lines(path.read_text(encoding="utf-8")):
            reference = parse_image_reference(line)
            if reference is not None:
                pins.append(
                    _Pin(path=relative, where="script", line=number, reference=reference)
                )
    return pins, missed


def _script_files(service: Path) -> list[Path]:
    found: list[Path] = []
    for name in SCRIPT_FILE_NAMES:
        candidate = service / name
        if candidate.is_file() and not candidate.is_symlink():
            found.append(candidate)
    for pattern in SCRIPT_GLOBS:
        found.extend(
            path
            for path in sorted(service.glob(pattern))
            if path.is_file() and not path.is_symlink()
        )
    directory = service / SCRIPT_DIRECTORY
    if directory.is_dir():
        found.extend(
            path
            for path in sorted(directory.iterdir())
            if path.is_file() and not path.is_symlink() and os.access(path, os.X_OK)
        )
    return sorted(set(found))


def _script_pin_lines(text: str) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = _strip_shell_comment(raw)
        words = line.split()
        if not words:
            continue
        runner = CONTAINER_RUNTIME_PATTERN.search(line)
        if runner is None:
            continue
        try:
            cursor = words.index(runner.group(1)) + 1
        except ValueError:
            continue
        if cursor < len(words) and COMPOSE_RUN_PATTERN.match(words[cursor]):
            cursor += 1
        for verb in CONTAINER_IMAGE_VERBS:
            if cursor >= len(words) or words[cursor] != verb:
                continue
            for word in words[cursor + 1:]:
                token = word.strip("\"'`,;)]}")
                reference = parse_image_reference(token)
                if reference is not None and reference.kind == "tag":
                    found.append((number, token))
            break
    return found


def _strip_shell_comment(line: str) -> str:
    quote = ""
    for index, character in enumerate(line):
        if quote:
            if character == quote and line[index - 1] != "\\":
                quote = ""
            continue
        if character in "\"'":
            quote = character
            continue
        if character == "#" and (index == 0 or line[index - 1] in " \t"):
            return line[:index]
    return line


def _read_postgres_exceptions(service: Path) -> tuple[list[dict], list[Finding]]:
    path = service / POSTGRES_EXCEPTIONS_FILE
    if not path.is_file():
        return [], []
    document = read_yaml(path.read_text(encoding="utf-8"), path)
    if not isinstance(document, dict):
        raise Refusal(
            "yaml.unsupported", str(path),
            f"a {POSTGRES_EXCEPTIONS_FILE} must be a mapping at the top level",
        )
    entries = document.get("exceptions")
    if not isinstance(entries, list):
        raise Refusal(
            "yaml.unsupported", str(path),
            f"`exceptions:` must be a list, got {type(entries).__name__}. A declaration "
            f"file whose key is misspelled is a file that declares nothing while "
            f"looking like it declares something.",
        )
    return [entry for entry in entries if isinstance(entry, dict)], []


def _exception_is_reviewable(entry: dict) -> bool:
    return all(
        isinstance(entry.get(field), str) and entry.get(field).strip()
        for field in POSTGRES_EXCEPTION_FIELDS
    ) and bool(isinstance(entry.get("file"), str) and entry.get("file").strip())


def check_postgres_exception_shape(
    entries: list[dict], declared_tag: str, where: str
) -> list[Finding]:
    """Four ways an exception can be wrong, all of them findings.

    This is the whole reason an exception is a declaration rather than a flag:

      1. **It must carry a reason, an owner and a horizon.** A bare entry is a
         wish, and the next person to read it cannot tell whether the author is
         still there.
      2. **An exception for the declared tag is not an exception.** If
         `postgres:17-alpine` appears here, the entry hides nothing today and
         hides the *next* change to `POSTGRES_TAG` behind a line that looks like
         it was reviewed. It is drift in the declaration, reported as drift.
      3. **An entry that matches nothing is a finding.** A stale exception is an
         escape hatch nobody re-reads, and it is the same rule kit enforces on
         its skip allowlist and identity on its coverage exclusions: an entry
         matching nothing is a failure, because otherwise deleting the pin does
         not delete the permission.
      4. **A file that is not a string, or an image that is not a postgres
         image, is a finding** — a declaration aimed at nothing.

    And the half that is easy to get wrong, because it is not one of the four:
    **an entry that fails any of them does not GRANT.** It is reported *and*
    inert, via `_exception_is_reviewable`. A suppression nobody can review must
    not suppress, so a `postgres:16-alpine` whose entry has no `owner` keeps the
    finding it was written to silence, and the reader is told which field is
    missing. Reporting an entry and honouring it at the same time is the one
    outcome a declaration mechanism must never produce: it is a line that both
    looks reviewed and does nothing, which is strictly worse than a line that
    looks unreviewed and does nothing.

    `until` is required and **not compared against a date.** The harness has one
    answer for every input or it does not have a rule: it never resolves a `$ref`
    over the network because a check that needs the network gets a different
    answer on a different day, and an exception list that expires by itself is
    that failure wearing a calendar. A horizon is a promise to a reader, and the
    reader is a human.
    """
    found: list[Finding] = []
    for index, entry in enumerate(entries):
        at = f"{where}: exceptions[{index}]"
        for field in POSTGRES_EXCEPTION_FIELDS:
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                found.append(
                    Finding(
                        "compose.postgres-pin",
                        at,
                        f"no `{field}`. An exception is a declaration, and a declaration "
                        f"with no {field} is a suppression nobody can review: not who "
                        f"asked for it, not why, and not when it was supposed to stop. "
                        f"All three are required, and `until` is deliberately not "
                        f"compared against a date — a rule whose answer depends on the "
                        f"day it runs is not a rule.",
                    )
                )
        image = entry.get("image")
        reference = parse_image_reference(image)
        if reference is None:
            found.append(
                Finding(
                    "compose.postgres-pin",
                    at,
                    f"`image` is {image!r}, which is not a postgres image reference. An "
                    f"exception aimed at something this rule does not decide is a line "
                    f"that reads like permission and grants none.",
                )
            )
        elif reference.tag == declared_tag:
            found.append(
                Finding(
                    "compose.postgres-pin",
                    at,
                    f"`image` is `{reference.summary}`, which is the tag core already "
                    f"declares. An exception for the standard is not an exception: it "
                    f"grants nothing today and hides the next change to {POSTGRES_TAG_FILE} "
                    f"behind a line that looks reviewed. Delete it, and if the pin it "
                    f"names is wrong, fix the pin.",
                )
            )
        if not isinstance(entry.get("file"), str) or not str(entry.get("file")).strip():
            found.append(
                Finding(
                    "compose.postgres-pin",
                    at,
                    "no `file`. An exception names the one file it applies to, and the "
                    "harness matches on that exact path. A wildcard would be a blanket "
                    "exemption, which is the thing a rule exists to prevent.",
                )
            )
    return found


def check_postgres_pin(service: Path, core: Path) -> tuple[list[Finding], list[Warning]]:
    """`compose.postgres-pin` — one postgres image, one tag, declared by core.

    The adoption ceiling was measured, and it is **not** what D24 recorded. Over
    the eleven `image:` declarations in the fleet's compose files and workflow
    `services:` blocks, nine are `postgres:17-alpine` and two are not:
    `identity`'s CI pins `postgres:17.11-alpine` while its own compose pins
    `postgres:17-alpine` — a divergence *inside one repository*, and one its CI
    comment already documents — and `kit`'s fleet template defaults to
    `postgres:${KIT_POSTGRES_TAG:-16.6-alpine}`, so a developer running `bin/dev`
    gets postgres 16.6. The rule is a hard failure anyway, because a severity
    chosen to make today's tree green is a warning wearing a rule's clothes, and
    those two are the rule working on the day it lands. Nothing adopts this yet
    (the harness deliberately migrates no service), so no build turns red
    today; the two are named in `REPORT-core-18-pgpin` for their own packets.

    Returns findings and warnings, in that order and for the same reason
    `_check_openapi` does: they are different answers to different questions, and
    a caller that has to guess which it got will treat a warning as a pass.
    """
    tag = read_postgres_tag(core)
    pins, missed = postgres_references(service)
    entries, _ = _read_postgres_exceptions(service)

    warnings: list[Warning] = []
    for path in missed:
        relative = path.relative_to(service)
        warnings.append(
            Warning(
                "compose.pin-scan-truncated",
                relative.as_posix(),
                f"a compose-shaped file is deeper than the {COMPOSE_SCAN_DEPTH}-level bound "
                f"this rule scans, so nothing in it was read. There may be a postgres pin "
                f"in there that no rule has checked. Move it up, or widen "
                f"COMPOSE_SCAN_DEPTH in harness/anywaye_contract.py — deliberately, "
                f"because the bound is what stops this walk from entering node_modules.",
            )
        )

    findings = check_postgres_exception_shape(entries, tag, POSTGRES_EXCEPTIONS_FILE)

    granted = set()
    for entry in entries:
        declared_file = entry.get("file")
        parsed = parse_image_reference(entry.get("image"))
        if not isinstance(declared_file, str) or not declared_file.strip():
            continue
        if parsed is None or parsed.tag == tag:
            continue
        if not _exception_is_reviewable(entry):
            continue
        granted.add((declared_file.strip(), parsed.summary))
    offenders = [
        pin
        for pin in pins
        if pin.reference.tag != tag
        and (pin.path, pin.reference.summary) not in granted
    ]

    inventory: dict[str, list[str]] = {}
    for pin in offenders:
        key = pin.reference.tag if pin.reference.tag is not None else pin.reference.kind
        inventory.setdefault(key, []).append(pin.located())

    for pin in offenders:
        findings.append(
            Finding(
                "compose.postgres-pin",
                pin.located(),
                _postgres_pin_message(pin, tag, inventory),
            )
        )
    return findings, warnings


def _postgres_pin_message(pin: _Pin, tag: str, inventory: dict[str, list[str]]) -> str:
    reference = pin.reference
    declared_here = f"`{reference.summary}`"
    disagreement = ""
    if len(inventory) > 1:
        rendered = "; ".join(
            f"`{value}` at {where}"
            for value, places in sorted(inventory.items())
            for where in places
        )
        disagreement = (
            f" This repository names {len(inventory)} different tags ({rendered}), and a "
            f"developer and a runner testing different database builds is the drift this "
            f"rule exists to fail on."
        )

    if reference.kind == "digest":
        if reference.tag is None:
            return (
                f"{declared_here} is a digest with no tag, and the rule compares tags. A "
                f"digest is a stronger pin than a tag and this rule has no business "
                f"calling it weaker — but it has nothing to compare, and a rule that "
                f"passed it would be a rule that decided nothing while reporting that it "
                f"did. core declares `{tag}` in {POSTGRES_TAG_FILE}. If the digest is "
                f"deliberate — an arm64 workstation and a linux/amd64 runner resolve "
                f"different ones, which identity's CI says out loud — declare it in "
                f"{POSTGRES_EXCEPTIONS_FILE} with a reason, an owner and a horizon."
            )
        return (
            f"pins a digest of tag `{reference.tag}`, and core declares `{tag}` in "
            f"{POSTGRES_TAG_FILE}. The digest is the stronger pin and is not what this "
            f"finding is about; the tag beside it is. A digest with no tag is reported "
            f"too — it is a pin this rule cannot compare — so the two cases are the same "
            f"rule and the same answer.{disagreement}"
        )
    if reference.kind == "variable":
        return (
            f"{declared_here} names its tag through a variable with no default, so the tag "
            f"is whatever the environment says and no rule can decide it. core declares "
            f"`{tag}` in {POSTGRES_TAG_FILE}. Give the variable a default "
            f"(`${{KIT_POSTGRES_TAG:-{tag}}}`), which is what the developer with nothing "
            f"set gets, or declare the exception."
        )
    if reference.kind == "untagged" or reference.tag == POSTGRES_FLOATING_TAG:
        return (
            f"pins {declared_here}, which floats: "
            + (
                f"no tag resolves to `postgres:{POSTGRES_FLOATING_TAG}`, and `latest` is "
                f"the one value a tag can hold that is guaranteed to change. "
                if reference.kind == "untagged"
                else f"`{POSTGRES_FLOATING_TAG}` is the one value a tag can hold that is "
                f"guaranteed to change. "
            )
            + f"core declares `{tag}` in {POSTGRES_TAG_FILE}.{disagreement}"
        )
    if "." not in reference.tag and "-" not in reference.tag:
        return (
            f"pins {declared_here}, and core declares `{tag}` in {POSTGRES_TAG_FILE}. The "
            f"major is right and the minor floats: a bare major is better than `latest` "
            f"and still lets two runs a month apart resolve different images, which is "
            f"the same dependence this rule exists to remove.{disagreement}"
        )
    return (
        f"pins {declared_here}, and core declares `{tag}` in {POSTGRES_TAG_FILE}. A tag is a "
        f"commitment about what the suite ran against, and this one is not the commitment "
        f"the platform made.{disagreement} If this major is genuinely needed, declare it in "
        f"{POSTGRES_EXCEPTIONS_FILE} with a reason, an owner and a horizon — declared, "
        f"never inferred, so the next reader can see who asked for it and when it was "
        f"supposed to stop."
    )




def _load_schema(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as error:
        raise Refusal("core.not-a-checkout", str(path), str(error))


def _exposes_events(manifest: dict) -> list[str]:
    events = (manifest.get("exposes") or {}).get("events")
    if not isinstance(events, list):
        return []
    return [event for event in events if isinstance(event, str)]


def _paths(document: dict) -> list[str]:
    paths = document.get("paths")
    if not isinstance(paths, dict):
        return []
    return [path for path in paths if isinstance(path, str)]


def run(
    service_root: Path,
    core_root: Path | None = None,
    expect_digest: str | None = None,
    env: dict | None = None,
) -> Result:
    """Check one service against core's contracts. Never raises `Refusal`.

    A `Refusal` becomes a `Result` whose exit code is 2, because a caller that
    has to catch an exception to learn the run did not happen is a caller that
    will eventually not catch it.
    """
    service = Path(service_root)
    core = Path(core_root) if core_root is not None else None
    digest = None
    try:
        if core is None:
            core = resolve_core(env=env)
        if not is_core_checkout(core):
            raise Refusal("core.not-a-checkout", str(core))
        digest = contract_digest(core)
        if expect_digest and digest != expect_digest:
            return Result(
                service_root=service,
                core_root=core,
                digest=digest,
                findings=(Finding(
                    "core.digest-mismatch", "schemas/",
                    f"core's contract surface digests {digest} and the pin is {expect_digest}. "
                    "Either core moved or the pin did; both are a deliberate one-line change, "
                    "and neither is something to discover in a service's build.",
                ),),
                core_commit=core_commit(core),
            )
        return _check_service(service, core, digest)
    except Refusal as refusal:
        return Result(
            service_root=service,
            core_root=core,
            digest=digest,
            findings=(Finding(refusal.rule, refusal.path, str(refusal)),),
            refused=True,
        )


def _check_service(service: Path, core: Path, digest: str) -> Result:
    manifest_path = service / "anywaye.yml"
    if not manifest_path.is_file():
        raise Refusal("service.manifest-absent", str(manifest_path))
    manifest = read_yaml(manifest_path.read_text(encoding="utf-8"), manifest_path)
    if not isinstance(manifest, dict):
        raise Refusal(
            "yaml.unsupported", str(manifest_path),
            "a manifest must be a mapping at the top level",
        )

    result = Result(service_root=service, core_root=core, digest=digest, core_commit=core_commit(core))
    schema_findings, schema_held = check_manifest_schema(manifest, core, service)
    if not schema_held:
        return Result(
            service_root=service,
            core_root=core,
            digest=digest,
            findings=tuple(schema_findings),
            stopped_after_schema=True,
            core_commit=result.core_commit,
        )

    catalog = event_catalog(core)
    findings: list[Finding] = []
    warnings: list[Warning] = []
    findings.extend(check_core_version(manifest, core))
    findings.extend(check_own_prefix(manifest))
    findings.extend(check_no_self_consume(manifest))
    findings.extend(check_unknown_consumed(manifest, catalog))
    findings.extend(check_unknown_published(manifest, catalog))
    findings.extend(check_payload_schema(manifest, core))
    findings.extend(check_api_file_exists(manifest, service))
    pin_findings, pin_warnings = check_postgres_pin(service, core)
    findings.extend(pin_findings)
    warnings.extend(pin_warnings)
    openapi_findings, openapi_warnings = _check_openapi(manifest, service)
    findings.extend(openapi_findings)
    warnings.extend(openapi_warnings)
    findings.extend(_check_slos(service, core))
    result.findings = tuple(findings)
    result.warnings = tuple(warnings)
    return result


def _check_openapi(
    manifest: dict, service: Path
) -> tuple[list[Finding], list[Warning]]:
    reference = (manifest.get("exposes") or {}).get("api")
    if not isinstance(reference, str) or not reference:
        return [], [_warn_missing_document(manifest, service)]
    path = service / reference
    if not path.is_file():
        return [], []
    where = reference
    document = read_yaml(path.read_text(encoding="utf-8"), path)
    if not isinstance(document, dict):
        raise Refusal("yaml.unsupported", str(path), "an OpenAPI document must be a mapping")

    scan = _openapi_scan(document, where)
    findings: list[Finding] = []
    findings.extend(check_document_is_31(document, where))
    findings.extend(check_info_version(document, where))
    findings.extend(check_has_paths(document, where))
    findings.extend(check_paths_are_versioned(document, where))
    findings.extend(check_one_version_prefix(document, where))
    findings.extend(check_errors_are_problems(scan))
    findings.extend(check_problem_code_matches_type(scan))
    findings.extend(check_problem_type_base(scan))
    findings.extend(check_reserved_error_codes(scan))
    findings.extend(check_problem_has_trace_id(scan))
    findings.extend(check_no_offset_pagination(scan))
    findings.extend(check_page_envelope(scan))
    findings.extend(check_idempotency_key(scan))
    findings.extend(check_idempotency_conflict_documented(scan))
    return findings, _unresolved_warnings(scan)


def _warn_missing_document(manifest: dict, service: Path) -> Warning:
    on_disk = _api_documents_on_disk(service)
    if on_disk:
        return Warning(
            "openapi.not-declared",
            "anywaye.yml: exposes/api",
            f"{WARNINGS['openapi.not-declared']} Found beside the manifest: "
            f"{', '.join(on_disk)}.",
        )
    return Warning(
        "openapi.no-document", "anywaye.yml: exposes/api", WARNINGS["openapi.no-document"]
    )


def _unresolved_warnings(scan: _Scan) -> list[Warning]:
    seen: list[tuple[str, str]] = []
    for pointer, place in scan.unresolved:
        entry = (pointer, place)
        if entry not in seen:
            seen.append(entry)
    return [
        Warning(
            "openapi.unresolved-ref",
            place,
            f"{WARNINGS['openapi.unresolved-ref']} ({pointer})",
        )
        for pointer, place in seen
    ]


# --------------------------------------------------------------------------
# the command
# --------------------------------------------------------------------------


def render(result: Result) -> str:
    """The whole report, as one string. Deterministic: no colour, no width.

    **Findings, then warnings, then the verdict, always in that order.** The
    order is the argument: a line that ends a build is above a line that
    explains why a check did less than it appears to, and the verdict is last so
    that a CI log which stops early has still shown the reason. A reader
    branching on the last line gets the same answer whichever of the three states
    the run was in, and `WARN` is a distinct prefix from `FAIL` so a log
    grepping for problems does not pick up the sentence about what was not
    checked.
    """
    lines = []
    for finding in result.findings:
        lines.append(f"FAIL {finding.rule} {finding.path}: {finding.message}")
    for warning in result.warnings:
        lines.append(f"WARN {warning.rule} {warning.path}: {warning.message}")
    if result.findings:
        rules = sorted({finding.rule for finding in result.findings})
        lines.append("")
        lines.append(
            f"{'REFUSED' if result.refused else f'{len(result.findings)} violation(s)'}"
            f" against core {result.core_root} "
            f"({result.digest[:12] if result.digest else 'no core read'}): " + ", ".join(rules)
        )
        return "\n".join(lines)
    lines.append(
        f"OK {result.service_root} conforms to core "
        f"{result.core_root} ({result.digest[:12] if result.digest else 'no digest'}"
        + (f", {result.core_commit[:12]}" if result.core_commit else "")
        + ")"
    )
    if result.warnings:
        rules = sorted({warning.rule for warning in result.warnings})
        lines.append(
            f"note: {len(result.warnings)} warning(s) — {', '.join(rules)} — and no violation. "
            "A warning names what was NOT checked; it does not change the exit code, and it "
            "is the reason a green run above is not a claim about the whole contract"
        )
    if result.stopped_after_schema:
        lines.append("note: the manifest failed the schema, so the cross-field rules did not run")
    return "\n".join(lines)


def rule_inventory_path() -> Path:
    return Path(__file__).resolve().parent / "rules.json"


def load_rule_inventory() -> dict:
    path = rule_inventory_path()
    try:
        with path.open(encoding="utf-8") as handle:
            inventory = json.load(handle)
    except (OSError, ValueError) as error:
        raise Refusal("core.not-a-checkout", str(path), f"the rule inventory is unreadable: {error}")
    _check_inventory_declares(inventory)
    return inventory


def _check_inventory_declares(inventory: dict) -> None:
    if not isinstance(inventory, dict):
        raise Refusal(
            "inventory.out-of-date", str(rule_inventory_path()), "the inventory is not an object"
        )
    rules = inventory.get("rules")
    warnings = inventory.get("warnings")

    def ids_of(entries: Any) -> set:
        if not isinstance(entries, list):
            return set()
        return {
            entry.get("id") for entry in entries if isinstance(entry, dict) and entry.get("id")
        }

    for emitted, named, kind in (
        (set(RULE_IDS), ids_of(rules), "rules"),
        (set(WARNING_IDS), ids_of(warnings), "warnings"),
    ):
        missing = sorted(emitted - named)
        extra = sorted(named - emitted)
        if missing or extra:
            raise Refusal(
                "inventory.out-of-date",
                str(rule_inventory_path()),
                f"under {kind!r} the inventory declares {sorted(named) or 'nothing'} and the "
                f"harness emits {sorted(emitted)}; missing {missing or 'nothing'}, undeclared "
                f"{extra or 'nothing'}",
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="anywaye-contract",
        description=(
            "Check a service's declared contract surface against core's contracts. "
            "Offline: core is read from a checkout, never fetched."
        ),
    )
    parser.add_argument("service", nargs="?", default=".", help="the service repository root (default: .)")
    parser.add_argument("--core", help="a anywaye/core checkout (default: $ANYWAYE_CORE)")
    parser.add_argument(
        "--expect-digest",
        help="fail unless core's schemas/ digests to this sha256 — the pin, in one argument",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable findings on stdout")
    parser.add_argument(
        "--list-rules", action="store_true", help="print the rule inventory and exit"
    )
    arguments = parser.parse_args(argv)

    if sys.version_info < MINIMUM_PYTHON:
        print(
            f"anywaye-contract needs python >= "
            f"{MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]}; this is {sys.version.split()[0]}",
            file=sys.stderr,
        )
        return EXIT_REFUSED

    if arguments.list_rules:
        try:
            inventory = load_rule_inventory()
        except Refusal as refusal:
            print(f"FAIL {refusal}", file=sys.stderr)
            return EXIT_REFUSED
        print(json.dumps(inventory, indent=2, sort_keys=False))
        return EXIT_CONFORMS

    result = run(
        service_root=Path(arguments.service),
        core_root=Path(arguments.core) if arguments.core else None,
        expect_digest=arguments.expect_digest,
    )
    if arguments.json:
        print(json.dumps({
            "service": str(result.service_root),
            "core": str(result.core_root),
            "coreCommit": result.core_commit,
            "digest": result.digest,
            "stoppedAfterSchema": result.stopped_after_schema,
            "exitCode": result.exit_code,
            "findings": [
                {"rule": f.rule, "path": f.path, "message": f.message} for f in result.findings
            ],
            "warnings": [
                {"rule": w.rule, "path": w.path, "message": w.message} for w in result.warnings
            ],
        }, indent=2, sort_keys=False))
        return result.exit_code
    print(render(result))
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
