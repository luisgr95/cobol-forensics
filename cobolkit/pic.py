"""PICTURE and USAGE analysis: storage size, value domain, alignment.

Storage rules follow IBM Enterprise COBOL for z/OS. The cases that bite:

* ``S`` costs no byte under DISPLAY -- the sign is overpunched into the last
  digit -- unless ``SIGN IS SEPARATE`` is in force.
* ``V`` and ``P`` are positional only and cost nothing, but ``P`` still counts
  toward the digit total that sizes a packed or binary field.
* COMP-3 is ``ceil((digits + 1) / 2)`` bytes: one nibble per digit plus a sign
  nibble, so an odd digit count packs with no waste.
* COMP width comes off the digit count in bands (1-4, 5-9, 10-18), not off the
  value range.
* ``PIC N`` and ``USAGE NATIONAL`` are UTF-16: two bytes per position.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

DISPLAY = "DISPLAY"
PACKED = "COMP-3"
BINARY = "COMP"
FLOAT_SHORT = "COMP-1"
FLOAT_LONG = "COMP-2"
NATIONAL = "NATIONAL"
INDEX = "INDEX"
POINTER = "POINTER"

#: Spellings accepted for each canonical usage.
USAGE_ALIASES = {
    "DISPLAY": DISPLAY,
    "DISPLAY-1": DISPLAY,
    "PACKED-DECIMAL": PACKED,
    "COMP-3": PACKED,
    "COMPUTATIONAL-3": PACKED,
    "BINARY": BINARY,
    "COMP": BINARY,
    "COMPUTATIONAL": BINARY,
    "COMP-4": BINARY,
    "COMPUTATIONAL-4": BINARY,
    "COMP-5": BINARY,
    "COMPUTATIONAL-5": BINARY,
    "COMP-1": FLOAT_SHORT,
    "COMPUTATIONAL-1": FLOAT_SHORT,
    "COMP-2": FLOAT_LONG,
    "COMPUTATIONAL-2": FLOAT_LONG,
    "NATIONAL": NATIONAL,
    "INDEX": INDEX,
    "POINTER": POINTER,
    "FUNCTION-POINTER": POINTER,
    "PROCEDURE-POINTER": POINTER,
}

# Two-character symbols must be tried before single characters or 'C' and 'D'
# would be consumed as unknown symbols.
_SYMBOL = re.compile(r"(CR|DB|[9XANZPSVBG0/,.+\-*$])(?:\((\d+)\))?", re.IGNORECASE)

#: Symbols that occupy one byte under DISPLAY.
_BYTE_SYMBOLS = set("9XAZBG0/,.+-*$")
#: Symbols that count as digit positions when sizing packed and binary fields.
_DIGIT_SYMBOLS = set("9P")


class PictureError(ValueError):
    """Raised when a PICTURE string cannot be understood."""


@dataclass(frozen=True)
class Picture:
    """A parsed PICTURE clause."""

    source: str
    symbols: str
    digits: int
    scale: int
    signed: bool
    category: str  # numeric | numeric-edited | alphanumeric | alphabetic | national

    @property
    def is_numeric(self) -> bool:
        return self.category in ("numeric", "numeric-edited")


def parse_picture(source: str) -> Picture:
    """Expand a PICTURE string into its symbol sequence and numeric traits."""
    text = source.strip().rstrip(".")
    if not text:
        raise PictureError("empty PICTURE clause")

    symbols: list[str] = []
    position = 0
    while position < len(text):
        match = _SYMBOL.match(text, position)
        if not match:
            raise PictureError(f"unexpected symbol at {position!r} in {source!r}")
        symbol = match.group(1).upper()
        repeat = int(match.group(2)) if match.group(2) else 1
        symbols.extend([symbol] * repeat)
        position = match.end()

    expanded = "".join(s if len(s) == 1 else "C" for s in symbols)
    digits = sum(1 for s in symbols if s in _DIGIT_SYMBOLS)
    # Everything after V is fractional. P before V scales down, P after scales up.
    scale = 0
    if "V" in symbols:
        tail = symbols[symbols.index("V") + 1 :]
        scale = sum(1 for s in tail if s in _DIGIT_SYMBOLS)

    signed = "S" in symbols
    category = _categorize(symbols)
    return Picture(
        source=text,
        symbols=expanded,
        digits=digits,
        scale=scale,
        signed=signed,
        category=category,
    )


def _categorize(symbols: list[str]) -> str:
    joined = set(symbols)
    if "N" in joined:
        return "national"
    if joined & set("XG"):
        return "alphanumeric"
    if "A" in joined and not joined & set("9ZP*"):
        return "alphabetic"
    if joined & set("Z*,.+-$") or "CR" in symbols or "DB" in symbols:
        return "numeric-edited"
    if joined & set("9P"):
        return "numeric"
    return "alphanumeric"


@dataclass(frozen=True)
class Storage:
    """How many bytes a field occupies, and how it must be aligned."""

    size: int
    usage: str
    alignment: int  # 1 = no alignment requirement
    notes: tuple[str, ...] = field(default=())


def storage_for(
    picture: Picture | None,
    usage: str = DISPLAY,
    sign_separate: bool = False,
) -> Storage:
    """Compute the byte size of an elementary item."""
    canonical = USAGE_ALIASES.get(usage.upper(), usage.upper())

    if canonical == INDEX:
        return Storage(4, INDEX, 4)
    if canonical == POINTER:
        return Storage(4, POINTER, 4)
    if canonical == FLOAT_SHORT:
        return Storage(4, FLOAT_SHORT, 4)
    if canonical == FLOAT_LONG:
        return Storage(8, FLOAT_LONG, 8)

    if picture is None:
        raise PictureError(f"usage {usage} requires a PICTURE clause")

    if canonical == PACKED:
        if not picture.is_numeric:
            raise PictureError("COMP-3 requires a numeric PICTURE")
        return Storage(math.ceil((picture.digits + 1) / 2), PACKED, 1)

    if canonical == BINARY:
        if not picture.is_numeric:
            raise PictureError("COMP requires a numeric PICTURE")
        size = binary_size(picture.digits)
        return Storage(size, BINARY, size)

    if canonical == NATIONAL or picture.category == "national":
        return Storage(2 * len(picture.symbols), NATIONAL, 2)

    # DISPLAY: one byte per occupying symbol.
    size = sum(1 for s in picture.symbols if s in _BYTE_SYMBOLS)
    size += 2 * picture.symbols.count("C")  # CR / DB occupy two bytes
    notes: list[str] = []
    if picture.signed and sign_separate:
        size += 1
        notes.append("SIGN IS SEPARATE adds one byte for the sign")
    return Storage(size, DISPLAY, 1, tuple(notes))


def binary_size(digits: int) -> int:
    """COMP width in bytes for a given digit count (TRUNC(STD) bands)."""
    if digits <= 0:
        raise PictureError("binary field needs at least one digit")
    if digits <= 4:
        return 2
    if digits <= 9:
        return 4
    if digits <= 18:
        return 8
    raise PictureError(f"{digits} digits exceeds the 18-digit COBOL limit")


def value_range(picture: Picture, usage: str = DISPLAY) -> tuple[int, int]:
    """Smallest and largest *unscaled* integers the field can hold."""
    canonical = USAGE_ALIASES.get(usage.upper(), usage.upper())
    if not picture.is_numeric:
        raise PictureError("value_range applies to numeric fields only")

    if canonical == BINARY:
        # COMP is two's complement across its full width, so it accepts values
        # the PICTURE forbids. Modernizations that re-type these to a decimal
        # of the declared precision silently truncate real production data.
        bits = binary_size(picture.digits) * 8 - 1
        hard_low, hard_high = -(2**bits), 2**bits - 1
        declared = 10**picture.digits - 1
        low = -declared if picture.signed else 0
        return (max(low, hard_low), min(declared, hard_high))

    high = 10**picture.digits - 1
    return (-high if picture.signed else 0, high)
