#!/usr/bin/env python3
import json
import os
import sys

TIER_NAMES = ("SOURCE", "JSON", "WIRE")
ALL_TIERS = frozenset(TIER_NAMES)

TABLE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "breaking_tiers.json")


class TierError(ValueError):
    """A tier selection or a table row that cannot be read.

    A distinct class rather than a bare `ValueError` because the callers that
    want to report one of these as a finding and the callers that want to assert
    it in a test do different things with it, and `except ValueError` catches
    every other mistake in the file too.
    """


TABLE_RELATIVE = os.path.join("harness", "breaking_tiers.json")


def _table_file(path):
    if path is None:
        return TABLE_PATH
    if os.path.isdir(path):
        return os.path.join(path, TABLE_RELATIVE)
    return path


def table(path=None):
    """The published table, or a `TierError` naming what is wrong with it.

    Every structural check happens HERE rather than at the call site, so a table
    that has drifted into a shape nobody can classify raises before a caller can
    read a tier out of it and believe it.
    """
    with open(_table_file(path), encoding="utf-8") as handle:
        raw = json.load(handle)

    for key in ("tiers", "defaultTiers", "rules"):
        if key not in raw:
            raise TierError(f"the table has no {key!r}; a table without one is "
                            f"not a smaller table, it is a different document")

    for name, description in raw["tiers"].items():
        if name not in TIER_NAMES:
            raise TierError(f"tier {name!r} is declared and is not one of "
                            f"{', '.join(TIER_NAMES)}")
        if not description:
            raise TierError(f"tier {name!r} has no description; a tier nobody "
                            f"can read is a tier nobody selects")

    _selection(raw["defaultTiers"], "defaultTiers")

    seen = set()
    for rule in raw["rules"]:
        for key in ("id", "buf", "tiers", "purpose", "why"):
            if not rule.get(key):
                raise TierError(f"a rule row has no {key!r}: {rule.get('id', rule)!r}")
        if rule["id"] in seen:
            raise TierError(f"two rules are both {rule['id']!r}; a duplicated id "
                            f"means one of them never fires and reads exactly "
                            f"like a document that is clean")
        seen.add(rule["id"])
        tiers = _selection(rule["tiers"], f"rule {rule['id']}")
        if not tiers:
            raise TierError(f"rule {rule['id']!r} breaks no tier; a change that "
                            f"breaks nothing is not a change kind")

    return raw


def _selection(values, where):
    if isinstance(values, str) or not isinstance(values, (list, tuple, set)):
        raise TierError(f"{where} is {values!r}, which is not a list of tier names")
    out = set()
    for value in values:
        if value not in TIER_NAMES:
            raise TierError(f"{where} names {value!r}, which is not one of "
                            f"{', '.join(TIER_NAMES)}")
        out.add(value)
    return frozenset(out)


def parse_tiers(selection):
    """A consumer's `--tiers` string as a frozenset of tier names.

    `all` is the whole set, because spelling out three names to mean "everything"
    is a chance to forget one. An EMPTY selection is an error rather than the
    empty set, and that is the one judgement here worth stating: the empty set
    intersects nothing, so `--tiers ''` would be a way to turn the gate green. A
    gate that can be passed by naming no tiers is not a gate.
    """
    if selection is None:
        raise TierError("no tiers selected: pick from source, json, wire, or all")
    tiers = set()
    for field in str(selection).split(","):
        name = field.strip().lower()
        if not name:
            raise TierError(f"no tiers selected by {selection!r}: an empty entry "
                            f"is a typo that would silently mean nothing")
        if name == "all":
            tiers |= ALL_TIERS
            continue
        if name not in (n.lower() for n in TIER_NAMES):
            raise TierError(f"unknown tier {field!r}: pick from source, json, "
                            f"wire, or all")
        tiers.add(name.upper())
    if not tiers:
        raise TierError(f"no tiers selected by {selection!r}")
    return frozenset(tiers)


def tiers_for(rule_id, published=None):
    """The tiers one change kind breaks."""
    published = published or table()
    for rule in published["rules"]:
        if rule["id"] == rule_id:
            return frozenset(rule["tiers"])
    known = ", ".join(r["id"] for r in published["rules"])
    raise TierError(f"no rule {rule_id!r} in the published table; known: {known}")


def breaks(rule_id, selection, published=None):
    """Whether a change kind is breaking FOR A CONSUMER WHO SELECTED `selection`.

    The intersection, and the intersection is the whole point: `property-same-name`
    is breaking for a consumer who selected SOURCE or JSON and is not breaking at
    all for one who selected only WIRE, and the same change answers both ways
    without the table having two rows for it.
    """
    return bool(tiers_for(rule_id, published) & parse_tiers(selection))


def default_tiers(published=None):
    """The tiers a declaration that says nothing is taken to select."""
    return _selection((published or table())["defaultTiers"], "defaultTiers")


def check(path=None):
    """The table's own findings, in this harness's vocabulary.

    Returns a list of `(severity, finding, message)`. A table that cannot be read
    at all is a FAILURE and not a skip: a rule that cannot be checked is a rule
    nobody was told about, which is the one outcome this repository calls the
    only real failure.
    """
    findings = []
    try:
        published = table(path)
    except TierError as exc:
        return [("fail", "breaking.tiers-unreadable",
                 f"the published breaking-tier table cannot be read: {exc}")]
    except (OSError, json.JSONDecodeError) as exc:
        return [("fail", "breaking.tiers-unreadable",
                 f"the published breaking-tier table cannot be read: {exc}")]

    tier_sets = [frozenset(r["tiers"]) for r in published["rules"]]
    for rule, tiers in zip(published["rules"], tier_sets):
        if len(tiers) == len(TIER_NAMES):
            continue
        others = [t for t in tier_sets if t != tiers]
        if any(tiers < other for other in others):
            break
    else:
        findings.append((
            "fail", "breaking.tiers-indistinguishable",
            "no rule breaks a strict subset of another rule's tiers, so selecting "
            "a tier cannot change any answer and the three tiers are one thing "
            "with three names"))

    default = frozenset(published["defaultTiers"])
    if default not in tier_sets:
        findings.append((
            "fail", "breaking.default-unclassified",
            f"the default selection {names(default)} is not the tier set of any "
            f"published rule, so a declaration that says nothing is not taken to "
            f"mean any change kind at all"))

    return findings


def _names(tiers):
    return [name for name in TIER_NAMES if name in tiers]


def names(tiers):
    """The public spelling of `_names`, because a message needs it too."""
    return "+".join(_names(tiers))


def main(argv):
    if len(argv) > 1 and argv[1] in ("--check", "-c"):
        findings = check(argv[2] if len(argv) > 2 else None)
        for severity, finding, message in findings:
            print(f"{severity} {finding}: {message}")
        return 1 if findings else 0

    published = table()
    print(f"breaking tiers: {', '.join(TIER_NAMES)}")
    print(f"default selection: {names(default_tiers(published))}")
    print()
    width = max(len(r["id"]) for r in published["rules"])
    for rule in published["rules"]:
        print(f"  {rule['id']:<{width}}  {names(frozenset(rule['tiers'])):<16}  "
              f"{rule['purpose']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))