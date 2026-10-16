"""Source-format normalization for COBOL and JCL.

Legacy COBOL arrives in fixed format, a punched-card layout that most generic
parsers get wrong:

    cols 1-6    sequence number (ignored)
    col  7      indicator: '*' or '/' comment, '-' continuation, 'D' debug
    cols 8-11   Area A (division, section, paragraph and level 01/77 headers)
    cols 12-72  Area B (everything else)
    cols 73-80  identification (ignored)

Anything past column 72 is NOT code. Reading it as code is the single most
common way a copybook byte map comes out wrong, because trailing identification
text gets glued onto the last clause of the entry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Source formats we accept.
FIXED = "fixed"
FREE = "free"

_SEQ_END = 6
_INDICATOR = 6  # 0-based index of column 7
_AREA_A_START = 7
_CODE_END = 72

_FREE_DIRECTIVE = re.compile(r">>\s*SOURCE\s+FORMAT\s+IS\s+FREE", re.IGNORECASE)
_FIXED_DIRECTIVE = re.compile(r">>\s*SOURCE\s+FORMAT\s+IS\s+FIXED", re.IGNORECASE)


@dataclass(frozen=True)
class Line:
    """One logical source line after format normalization.

    ``number`` is the 1-based physical line number in the original file, kept so
    every finding can be reported at a location a developer can open.
    """

    number: int
    text: str
    area_a: bool
    continuation: bool


def detect_format(raw: str) -> str:
    """Guess the source format of ``raw``.

    Explicit ``>>SOURCE FORMAT`` directives win. Otherwise we score the file on
    whether its lines look card-shaped: a blank-or-numeric sequence area and a
    legal indicator column. Repositories that stripped the sequence numbers
    score low and are treated as free format.
    """
    if _FREE_DIRECTIVE.search(raw):
        return FREE
    if _FIXED_DIRECTIVE.search(raw):
        return FIXED

    card_like = 0
    considered = 0
    for line in raw.splitlines():
        if not line.strip():
            continue
        considered += 1
        seq = line[:_SEQ_END]
        indicator = line[_INDICATOR : _INDICATOR + 1]
        seq_ok = seq.strip() == "" or seq.strip().isdigit()
        ind_ok = indicator in ("", " ", "*", "/", "-", "D", "d", "$")
        # Code starting in column 1 is the giveaway for free format.
        starts_col_1 = bool(line[:1].strip()) and not seq.strip().isdigit()
        if seq_ok and ind_ok and not starts_col_1:
            card_like += 1

    if considered == 0:
        return FIXED
    return FIXED if card_like / considered >= 0.6 else FREE


def normalize(raw: str, source_format: str | None = None) -> list[Line]:
    """Strip comments and card columns, then fold continuation lines.

    Returns logical lines with ``area_a`` set when the statement began in
    Area A, which is how level 01/77 entries and paragraph names are told apart
    from clauses that merely wrapped onto a new card.
    """
    fmt = source_format or detect_format(raw)
    physical: list[Line] = []

    for index, line in enumerate(raw.splitlines(), start=1):
        if fmt == FIXED:
            # Tabs would shift every column; expand before slicing.
            line = line.expandtabs(8)
            indicator = line[_INDICATOR : _INDICATOR + 1]
            if indicator in ("*", "/", "D", "d", "$"):
                continue
            code = line[_AREA_A_START:_CODE_END]
            if not code.strip():
                continue
            offset_in_code = len(code) - len(code.lstrip())
            physical.append(
                Line(
                    number=index,
                    text=code.strip(),
                    # Area A is columns 8-11, i.e. the first 4 slots of `code`.
                    area_a=offset_in_code < 4,
                    continuation=indicator == "-",
                )
            )
        else:
            stripped = line.strip()
            if not stripped or stripped.startswith("*>") or stripped.startswith("*"):
                continue
            indent = len(line) - len(line.lstrip())
            physical.append(
                Line(
                    number=index,
                    text=stripped,
                    area_a=indent < 4,
                    continuation=False,
                )
            )

    return _fold_continuations(physical)


def _fold_continuations(lines: list[Line]) -> list[Line]:
    """Join lines whose indicator column held ``-`` onto the previous line."""
    folded: list[Line] = []
    for line in lines:
        if line.continuation and folded:
            previous = folded[-1]
            folded[-1] = Line(
                number=previous.number,
                text=f"{previous.text} {line.text}".strip(),
                area_a=previous.area_a,
                continuation=False,
            )
        else:
            folded.append(line)
    return folded


# A period ends a COBOL entry only when followed by whitespace or end of line.
# This matters because an edited PIC clause legitimately contains periods
# (PIC ZZ,ZZ9.99), and splitting on every '.' shreds it.
_ENTRY_END = re.compile(r"\.(?=\s|$)")


@dataclass(frozen=True)
class Entry:
    """A period-terminated COBOL entry, reassembled across cards."""

    number: int
    text: str
    area_a: bool


def entries(lines: list[Line]) -> list[Entry]:
    """Group normalized lines into period-terminated entries."""
    out: list[Entry] = []
    buffer: list[str] = []
    start: int | None = None
    area_a = False

    for line in lines:
        if start is None:
            start = line.number
            area_a = line.area_a
        remainder = line.text
        while True:
            match = _ENTRY_END.search(remainder)
            if not match:
                if remainder.strip():
                    buffer.append(remainder.strip())
                break
            head = remainder[: match.start()]
            if head.strip():
                buffer.append(head.strip())
            if buffer:
                out.append(Entry(number=start, text=" ".join(buffer), area_a=area_a))
            buffer = []
            remainder = remainder[match.end() :]
            start = line.number
            area_a = line.area_a
            if not remainder.strip():
                start = None
                break

    if buffer and start is not None:
        out.append(Entry(number=start, text=" ".join(buffer), area_a=area_a))
    return out


_LITERAL = re.compile(r"'[^']*'|\"[^\"]*\"")


def strip_literals(text: str, placeholder: str = " ") -> str:
    """Blank out quoted literals so keyword scans cannot match inside them.

    Without this, a program containing ``DISPLAY 'CALL THE BANK'`` reports a
    phantom subprogram call.
    """
    return _LITERAL.sub(lambda m: placeholder * len(m.group(0)), text)


def literals(text: str) -> list[str]:
    """Return the quoted literals in ``text``, without their quotes."""
    return [m.group(0)[1:-1] for m in _LITERAL.finditer(text)]


def literal_spans(text: str) -> list[tuple[int, int]]:
    """Character ranges occupied by quoted literals.

    Needed where a scan must read a literal operand -- ``CALL 'PAYCALC'`` --
    while ignoring the same keyword appearing *inside* some other literal, as
    in ``DISPLAY 'CALL THE OPERATOR'``.
    """
    return [m.span() for m in _LITERAL.finditer(text)]


def inside_literal(position: int, spans: list[tuple[int, int]]) -> bool:
    """True when ``position`` falls within one of ``spans``."""
    return any(start <= position < end for start, end in spans)
