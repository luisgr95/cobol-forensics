"""Program inventory, call graph and resource extraction.

What this answers, for a codebase nobody alive fully understands:

* which programs exist, and which call which
* which calls are *dynamic*, i.e. resolved from a working-storage variable at
  run time -- the reason naive call graphs are quietly incomplete
* which copybooks, DB2 tables, CICS transactions and datasets each program
  touches
* which constructs will make a rewrite expensive (``ALTER``, ``GO TO``,
  dynamic SQL, variable-length tables)

Everything here is lexical. It does not resolve ``COPY ... REPLACING``, so a
field introduced by a replacing clause is reported as the copybook it came
from, not as the substituted text.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .source import Line, inside_literal, literal_spans, normalize, strip_literals

_PROGRAM_ID = re.compile(r"\bPROGRAM-ID\s*\.?\s*([A-Za-z0-9][A-Za-z0-9\-_]*)", re.I)
_ENTRY = re.compile(r"\bENTRY\s+'([^']+)'", re.I)
_CALL = re.compile(
    r"\bCALL\s+(?:'([^']+)'|\"([^\"]+)\"|([A-Za-z0-9][A-Za-z0-9\-_]*))", re.I
)
_COPY = re.compile(
    r"\bCOPY\s+([A-Za-z0-9][A-Za-z0-9\-_]*)"
    r"(?:\s+(?:IN|OF)\s+([A-Za-z0-9][A-Za-z0-9\-_]*))?",
    re.I,
)
_EXEC_SQL = re.compile(r"\bEXEC\s+SQL\b(.*?)\bEND-EXEC\b", re.I | re.S)
_EXEC_CICS = re.compile(r"\bEXEC\s+CICS\b(.*?)\bEND-EXEC\b", re.I | re.S)
_FILE_SELECT = re.compile(
    r"\bSELECT\s+(?:OPTIONAL\s+)?([A-Za-z0-9][A-Za-z0-9\-_]*)\s+ASSIGN\s+(?:TO\s+)?"
    r"(?:'([^']+)'|([A-Za-z0-9][A-Za-z0-9\-_]*))",
    re.I,
)
_PERFORM = re.compile(
    r"\bPERFORM\s+([A-Za-z0-9][A-Za-z0-9\-_]*)"
    r"(?:\s+(?:THRU|THROUGH)\s+([A-Za-z0-9][A-Za-z0-9\-_]*))?",
    re.I,
)
_DIVISION = re.compile(r"\b(IDENTIFICATION|ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION", re.I)
_PARAGRAPH = re.compile(r"^([A-Za-z0-9][A-Za-z0-9\-_]*)\s*$")

_SQL_TABLE = re.compile(
    r"\b(?:FROM|JOIN|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+"
    r"([A-Za-z][A-Za-z0-9_$#]*(?:\.[A-Za-z][A-Za-z0-9_$#]*)?)",
    re.I,
)
_SQL_CURSOR = re.compile(r"\bDECLARE\s+([A-Za-z0-9][A-Za-z0-9\-_]*)\s+CURSOR", re.I)
# EXEC SQL INCLUDE is the SQL precompiler's COPY; the member it pulls in is a
# copybook in every sense that matters for impact analysis.
_SQL_INCLUDE = re.compile(r"\bINCLUDE\s+([A-Za-z0-9][A-Za-z0-9\-_]*)", re.I)
_SQL_DYNAMIC = re.compile(r"\b(PREPARE|EXECUTE\s+IMMEDIATE)\b", re.I)
_CICS_PROGRAM = re.compile(
    r"\b(LINK|XCTL)\b[^)]*?\bPROGRAM\s*\(\s*'?([A-Za-z0-9][A-Za-z0-9\-_]*)'?", re.I | re.S
)
_CICS_VERB = re.compile(r"^\s*([A-Z][A-Z0-9-]*)", re.I)

#: Constructs that reliably make a rewrite more expensive, and why.
RISKS = {
    "alter": (re.compile(r"\bALTER\b", re.I), "ALTER rewrites a GO TO at run time"),
    "goto_depending": (
        re.compile(r"\bGO\s+TO\b[^.]*\bDEPENDING\s+ON\b", re.I | re.S),
        "computed GO TO: control flow depends on a subscript",
    ),
    "sort": (re.compile(r"\bSORT\b|\bMERGE\b", re.I), "internal SORT/MERGE"),
    "dynamic_sql": (_SQL_DYNAMIC, "dynamic SQL: table access is not statically known"),
    "goback_mix": (
        re.compile(r"\bSTOP\s+RUN\b", re.I),
        "STOP RUN inside a called module terminates the whole run unit",
    ),
}


@dataclass
class Program:
    """Everything extracted from a single compilation unit."""

    path: str
    program_id: str
    entry_points: list[str] = field(default_factory=list)
    static_calls: list[str] = field(default_factory=list)
    dynamic_calls: list[str] = field(default_factory=list)
    copybooks: list[str] = field(default_factory=list)
    sql_tables: list[str] = field(default_factory=list)
    sql_cursors: list[str] = field(default_factory=list)
    cics_commands: list[str] = field(default_factory=list)
    files: list[tuple[str, str]] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)
    perform_targets: list[str] = field(default_factory=list)
    goto_count: int = 0
    source_lines: int = 0
    risks: list[str] = field(default_factory=list)

    @property
    def dead_paragraphs(self) -> list[str]:
        """Paragraphs never named by a PERFORM or GO TO in the same program.

        Lexical only: a paragraph reached solely by fallthrough from the one
        above it is listed here and is not necessarily dead.
        """
        referenced = {t.upper() for t in self.perform_targets}
        return [p for p in self.paragraphs[1:] if p.upper() not in referenced]


@dataclass
class Inventory:
    """A whole codebase: programs, plus the edges between them."""

    programs: list[Program] = field(default_factory=list)

    @property
    def by_id(self) -> dict[str, Program]:
        return {p.program_id.upper(): p for p in self.programs}

    @property
    def edges(self) -> list[tuple[str, str, str]]:
        """``(caller, callee, kind)`` for every call, static or dynamic."""
        out: list[tuple[str, str, str]] = []
        for program in self.programs:
            for target in program.static_calls:
                out.append((program.program_id, target, "static"))
            for target in program.dynamic_calls:
                out.append((program.program_id, target, "dynamic"))
        return out

    @property
    def missing(self) -> list[str]:
        """Statically called programs with no source in the analyzed set."""
        known = set(self.by_id)
        for program in self.programs:
            known.update(e.upper() for e in program.entry_points)
        called = {
            t.upper() for p in self.programs for t in p.static_calls
        }
        return sorted(called - known)

    @property
    def orphans(self) -> list[str]:
        """Programs nothing in the set calls -- batch entry points, or dead."""
        called = {t.upper() for p in self.programs for t in p.static_calls}
        return sorted(
            p.program_id for p in self.programs if p.program_id.upper() not in called
        )


def analyze(raw: str, path: str = "<memory>", source_format: str | None = None) -> Program:
    """Extract one program's facts from its source text."""
    lines = normalize(raw, source_format)
    blob = "\n".join(line.text for line in lines)

    program = Program(
        path=path,
        program_id=_first(_PROGRAM_ID, blob) or _stem(path),
        source_lines=len(lines),
    )

    # COPY takes a bare member name, so scanning with literals blanked out
    # cannot lose a real match and cannot invent one from prose in a DISPLAY.
    program.copybooks = _unique(
        m.group(1).upper() for m in _COPY.finditer(strip_literals(blob))
    )
    program.entry_points = _unique(m.group(1).upper() for m in _ENTRY.finditer(blob))

    # Pull the embedded SQL and CICS out first: both contain words that mean
    # something else in COBOL (SQL's SELECT is not FILE-CONTROL's SELECT).
    sql_blocks = [m.group(1) for m in _EXEC_SQL.finditer(blob)]
    cics_blocks = [m.group(1) for m in _EXEC_CICS.finditer(blob)]
    cobol_only = _EXEC_CICS.sub(" ", _EXEC_SQL.sub(" ", blob))

    for block in sql_blocks:
        program.sql_tables.extend(m.group(1).upper() for m in _SQL_TABLE.finditer(block))
        program.sql_cursors.extend(
            m.group(1).upper() for m in _SQL_CURSOR.finditer(block)
        )
        program.copybooks.extend(m.group(1).upper() for m in _SQL_INCLUDE.finditer(block))
    program.sql_tables = _unique(program.sql_tables)
    program.sql_cursors = _unique(program.sql_cursors)
    program.copybooks = _unique(program.copybooks)

    for block in cics_blocks:
        verb = _CICS_VERB.match(block.strip())
        if verb:
            program.cics_commands.append(verb.group(1).upper())
        for match in _CICS_PROGRAM.finditer(block):
            program.static_calls.append(match.group(2).upper())
    program.cics_commands = _unique(program.cics_commands)

    # Calls: a quoted operand is resolved at link time, a bare identifier at
    # run time. The second kind is what breaks impact analysis.
    literal_free = strip_literals(cobol_only)
    spans = literal_spans(cobol_only)
    for match in _CALL.finditer(cobol_only):
        # The CALL keyword itself must not sit inside a literal, or
        # DISPLAY 'CALL THE OPERATOR' reports a subprogram named THE.
        if inside_literal(match.start(), spans):
            continue
        literal = match.group(1) or match.group(2)
        if literal:
            program.static_calls.append(literal.upper())
        elif match.group(3):
            program.dynamic_calls.append(match.group(3).upper())
    program.static_calls = _unique(program.static_calls)
    program.dynamic_calls = _unique(program.dynamic_calls)

    for match in _FILE_SELECT.finditer(cobol_only):
        logical = match.group(1).upper()
        physical = (match.group(2) or match.group(3) or "").upper()
        program.files.append((logical, physical))

    program.paragraphs = _paragraphs(lines)
    targets: list[str] = []
    for match in _PERFORM.finditer(literal_free):
        targets.append(match.group(1).upper())
        if match.group(2):
            targets.append(match.group(2).upper())
    program.perform_targets = _unique(targets)
    program.goto_count = len(re.findall(r"\bGO\s+TO\b", literal_free, re.I))

    for name, (pattern, description) in RISKS.items():
        haystack = blob if name == "dynamic_sql" else literal_free
        if pattern.search(haystack):
            program.risks.append(description)
    if program.dynamic_calls:
        program.risks.append(
            f"{len(program.dynamic_calls)} dynamic CALL target(s): "
            "the call graph cannot be completed without run-time data"
        )

    return program


def analyze_file(path: str, source_format: str | None = None) -> Program:
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return analyze(handle.read(), path.replace(os.sep, "/"), source_format)


#: Extensions treated as COBOL compilation units.
COBOL_SUFFIXES = (".cbl", ".cob", ".cobol", ".pco", ".sqb")


def analyze_tree(
    root: str, source_format: str | None = None, suffixes: tuple[str, ...] = COBOL_SUFFIXES
) -> Inventory:
    """Walk ``root`` and analyze every COBOL source file found."""
    inventory = Inventory()
    if os.path.isfile(root):
        inventory.programs.append(analyze_file(root, source_format))
        return inventory
    for directory, _, names in os.walk(root):
        for name in sorted(names):
            if name.lower().endswith(suffixes):
                inventory.programs.append(
                    analyze_file(os.path.join(directory, name), source_format)
                )
    return inventory


def _paragraphs(lines: list[Line]) -> list[str]:
    """Paragraph names: a bare name in Area A, inside the PROCEDURE DIVISION."""
    out: list[str] = []
    in_procedure = False
    for line in lines:
        division = _DIVISION.search(line.text)
        if division:
            in_procedure = division.group(1).upper() == "PROCEDURE"
            continue
        if not in_procedure or not line.area_a:
            continue
        candidate = line.text.strip().rstrip(".")
        match = _PARAGRAPH.match(candidate)
        if match and not candidate.upper().endswith("SECTION"):
            name = match.group(1).upper()
            if name not in ("EXIT", "CONTINUE"):
                out.append(name)
    return _unique(out)


def _first(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group(1).upper() if match else None


def _stem(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0].upper()


def _unique(values) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        seen.setdefault(value, None)
    return list(seen)
