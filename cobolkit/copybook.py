"""DATA DIVISION and copybook parsing into an exact byte map.

The output is the artifact every modernization actually needs first: for each
field, where it starts, how long it is, and what it means. Getting this wrong
by one byte shifts every field after it, which is why the hard cases --
``REDEFINES``, ``OCCURS``, ``COMP-3`` and ``SYNCHRONIZED`` slack -- are handled
explicitly rather than approximated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .pic import Picture, Storage, USAGE_ALIASES, parse_picture, storage_for
from .source import Entry, entries, normalize

_LEVEL = re.compile(r"^(\d{1,2})\s+(.*)$", re.DOTALL)
_NAME = re.compile(r"^(FILLER|[A-Za-z0-9][A-Za-z0-9\-_]*)\s*(.*)$", re.DOTALL)
_PIC = re.compile(r"\bPIC(?:TURE)?\s+(?:IS\s+)?(\S+)", re.IGNORECASE)
_REDEFINES = re.compile(r"\bREDEFINES\s+([A-Za-z0-9][A-Za-z0-9\-_]*)", re.IGNORECASE)
_OCCURS = re.compile(
    r"\bOCCURS\s+(\d+)(?:\s+TO\s+(\d+))?\s*(?:TIMES)?", re.IGNORECASE
)
_DEPENDING = re.compile(
    r"\bDEPENDING\s+(?:ON\s+)?([A-Za-z0-9][A-Za-z0-9\-_]*)", re.IGNORECASE
)
_VALUE = re.compile(r"\bVALUE\s+(?:IS\s+)?(.*?)(?:\s+(?:PIC|USAGE|OCCURS)\b|$)", re.IGNORECASE)
_SYNC = re.compile(r"\bSYNC(?:HRONIZED)?\b", re.IGNORECASE)
_SIGN_SEPARATE = re.compile(r"\bSEPARATE\b", re.IGNORECASE)
_SIGN = re.compile(r"\bSIGN\b", re.IGNORECASE)

# Longest alias first so COMP-3 is never shortened to COMP.
_USAGE_WORDS = sorted(USAGE_ALIASES, key=len, reverse=True)
_USAGE = re.compile(
    r"\b(?:USAGE\s+(?:IS\s+)?)?(" + "|".join(re.escape(u) for u in _USAGE_WORDS) + r")\b",
    re.IGNORECASE,
)

#: Levels that declare no storage of their own.
CONDITION_LEVEL = 88
RENAMES_LEVEL = 66
STANDALONE_LEVEL = 77


@dataclass
class Field:
    """One DATA DIVISION entry, with its computed position in the record."""

    level: int
    name: str
    line: int
    picture: Picture | None = None
    usage: str = "DISPLAY"
    occurs: int = 1
    occurs_min: int | None = None
    depending_on: str | None = None
    redefines: str | None = None
    value: str | None = None
    sync: bool = False
    sign_separate: bool = False
    children: list["Field"] = field(default_factory=list)
    conditions: list[tuple[str, str]] = field(default_factory=list)
    parent: "Field | None" = None

    # Filled in by :func:`layout`.
    offset: int = 0
    unit_size: int = 0
    total_size: int = 0
    slack_before: int = 0
    storage: Storage | None = None

    @property
    def is_group(self) -> bool:
        return bool(self.children)

    @property
    def position(self) -> int:
        """1-based start position, the way a record layout is normally read."""
        return self.offset + 1

    @property
    def path(self) -> str:
        names = [self.name]
        node = self.parent
        while node is not None:
            names.append(node.name)
            node = node.parent
        return ".".join(reversed(names))

    @property
    def variable(self) -> bool:
        """True when the field's length depends on a runtime value."""
        if self.depending_on:
            return True
        return any(child.variable for child in self.children)

    @property
    def ancestors(self) -> list["Field"]:
        """This field's parents, nearest first."""
        out: list["Field"] = []
        node = self.parent
        while node is not None:
            out.append(node)
            node = node.parent
        return out

    @property
    def under_redefinition(self) -> bool:
        """True when this field, or a group containing it, redefines other storage.

        Such a field shares its bytes with the primary definition, so it can be
        read but never populated independently.
        """
        return bool(self.redefines) or any(a.redefines for a in self.ancestors)

    @property
    def repetition(self) -> list["Field"]:
        """Self and ancestors that carry an OCCURS clause, outermost last."""
        return [n for n in [self, *self.ancestors] if n.occurs > 1 or n.depending_on]


@dataclass
class Record:
    """A top-level (level 01 or 77) record and its byte map."""

    name: str
    fields: list[Field]
    length: int
    warnings: list[str] = field(default_factory=list)

    def flatten(self, elementary_only: bool = False) -> list[Field]:
        out: list[Field] = []

        def walk(nodes: list[Field]) -> None:
            for node in nodes:
                if not elementary_only or not node.is_group:
                    out.append(node)
                walk(node.children)

        walk(self.fields)
        return out

    def find(self, name: str) -> Field | None:
        target = name.upper()
        for node in self.flatten():
            if node.name.upper() == target:
                return node
        return None


class CopybookError(ValueError):
    """Raised when a copybook cannot be parsed into a byte map."""


def parse(raw: str, source_format: str | None = None) -> list[Record]:
    """Parse copybook or DATA DIVISION text into records with byte maps."""
    parsed = [
        _parse_entry(entry)
        for entry in entries(normalize(raw, source_format))
        if _LEVEL.match(entry.text.strip())
    ]
    parsed = [f for f in parsed if f is not None]
    if not parsed:
        return []
    return _build(parsed)


def parse_file(path: str, source_format: str | None = None) -> list[Record]:
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return parse(handle.read(), source_format)


def _parse_entry(entry: Entry) -> Field | None:
    text = entry.text.strip()
    level_match = _LEVEL.match(text)
    if not level_match:
        return None
    level = int(level_match.group(1))
    remainder = level_match.group(2).strip()

    name_match = _NAME.match(remainder)
    if name_match:
        name = name_match.group(1).upper()
        clauses = name_match.group(2)
        # A clause keyword in the name slot means the entry was unnamed.
        if name in ("PIC", "PICTURE", "USAGE", "REDEFINES", "OCCURS", "VALUE"):
            name = "FILLER"
            clauses = remainder
    else:
        name = "FILLER"
        clauses = remainder

    node = Field(level=level, name=name, line=entry.number)

    if level == CONDITION_LEVEL:
        value = _VALUE.search(clauses)
        node.value = value.group(1).strip() if value else None
        return node

    pic_match = _PIC.search(clauses)
    if pic_match:
        node.picture = parse_picture(pic_match.group(1))

    # Blank the PIC string before scanning for usage: a picture such as
    # S9(4)COMP would otherwise be matched twice.
    scan = _PIC.sub(" ", clauses)
    usage_match = _USAGE.search(scan)
    if usage_match:
        node.usage = USAGE_ALIASES[usage_match.group(1).upper()]

    redefines = _REDEFINES.search(clauses)
    if redefines:
        node.redefines = redefines.group(1).upper()

    occurs = _OCCURS.search(clauses)
    if occurs:
        low = int(occurs.group(1))
        high = int(occurs.group(2)) if occurs.group(2) else None
        node.occurs = high or low
        node.occurs_min = low if high else None
        depending = _DEPENDING.search(clauses)
        if depending:
            node.depending_on = depending.group(1).upper()

    value = _VALUE.search(clauses)
    if value and value.group(1).strip():
        node.value = value.group(1).strip()

    node.sync = bool(_SYNC.search(clauses))
    node.sign_separate = bool(_SIGN.search(clauses) and _SIGN_SEPARATE.search(clauses))
    return node


def _build(parsed: list[Field]) -> list[Record]:
    """Assemble the flat entry list into records using a level stack."""
    records: list[Record] = []
    roots: list[Field] = []
    stack: list[Field] = []

    for node in parsed:
        if node.level == CONDITION_LEVEL:
            if stack:
                stack[-1].conditions.append((node.name, node.value or ""))
            continue
        if node.level == RENAMES_LEVEL:
            continue  # RENAMES declares an alias, never storage.

        if node.level in (1, STANDALONE_LEVEL):
            stack = [node]
            roots.append(node)
            continue

        while stack and stack[-1].level >= node.level:
            stack.pop()
        if not stack:
            # A fragment that opens below 01; treat it as its own root.
            roots.append(node)
            stack = [node]
            continue
        parent = stack[-1]
        node.parent = parent
        parent.children.append(node)
        stack.append(node)

    for root in roots:
        warnings: list[str] = []
        length = _layout(root, 0, warnings)
        records.append(
            Record(name=root.name, fields=[root], length=length, warnings=warnings)
        )
    return records


def _layout(node: Field, start: int, warnings: list[str]) -> int:
    """Assign offsets and sizes to ``node`` and its subtree. Returns total size."""
    aligned = start
    if node.sync and not node.is_group:
        alignment = _alignment_for(node, warnings)
        if alignment > 1:
            aligned = _round_up(start, alignment)
            node.slack_before = aligned - start
    node.offset = aligned

    if node.children:
        cursor = aligned
        for child in node.children:
            if child.redefines:
                target = _resolve_redefines(node, child, warnings)
                child_start = target.offset if target else cursor
            else:
                child_start = cursor
            _layout(child, child_start, warnings)
            end = child.offset + child.total_size
            # A redefinition shares storage, so it may not shrink the record.
            cursor = end if not child.redefines else max(cursor, end)
        node.unit_size = cursor - aligned
        if node.sync:
            warnings.append(
                f"{node.path}: SYNCHRONIZED on a group item; slack bytes inside "
                "groups are compiler-dependent and are not modelled"
            )
    else:
        try:
            node.storage = storage_for(node.picture, node.usage, node.sign_separate)
        except Exception as error:  # noqa: BLE001 - reported, not raised
            warnings.append(f"{node.path} (line {node.line}): {error}")
            node.storage = Storage(0, node.usage, 1)
        node.unit_size = node.storage.size
        for note in node.storage.notes:
            warnings.append(f"{node.path}: {note}")

    node.total_size = node.unit_size * node.occurs

    if node.depending_on:
        warnings.append(
            f"{node.path}: OCCURS {node.occurs_min} TO {node.occurs} DEPENDING ON "
            f"{node.depending_on}; the map shows the maximum length"
        )
    return node.total_size


def _alignment_for(node: Field, warnings: list[str]) -> int:
    if node.storage is not None:
        return node.storage.alignment
    try:
        return storage_for(node.picture, node.usage, node.sign_separate).alignment
    except Exception:  # noqa: BLE001
        return 1


def _resolve_redefines(
    parent: Field, child: Field, warnings: list[str]
) -> Field | None:
    for sibling in parent.children:
        if sibling is child:
            break
        if sibling.name == child.redefines:
            return sibling
    warnings.append(
        f"{child.path} (line {child.line}): REDEFINES {child.redefines}, which is "
        "not a preceding item at the same level; offset may be wrong"
    )
    return None


def _round_up(value: int, boundary: int) -> int:
    remainder = value % boundary
    return value if remainder == 0 else value + (boundary - remainder)
