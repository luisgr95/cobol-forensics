"""Characterization-test support: boundary matrices and byte-exact fixtures.

The only safe way to rewrite a COBOL program is to pin its *current* behaviour
first -- bugs included -- then prove the replacement matches. That needs real
input records, and real records mean getting the on-disk encoding exactly
right: zoned decimal sign overpunch, packed-decimal sign nibbles, big-endian
binary, EBCDIC collation.

Output is EBCDIC (cp037) by default, because that is what the program under
test actually reads. ASCII mode exists so a human can eyeball the character
fields; signed DISPLAY fields in ASCII mode carry a plain trailing digit
instead of an overpunch, so ASCII fixtures are not sign-accurate.
"""

from __future__ import annotations

from dataclasses import dataclass

from .copybook import Field, Record
from .pic import BINARY, DISPLAY, FLOAT_LONG, FLOAT_SHORT, NATIONAL, PACKED, value_range

EBCDIC = "cp037"

#: Whole-record fill cases, applied as raw bytes rather than per field.
FILL_CASES = {
    "low-values": 0x00,
    "high-values": 0xFF,
}

#: Per-field cases and why each one is worth a test.
FIELD_CASES = {
    "zero": "numerics at zero, text blank: the initialized-but-unset record",
    "min": "numeric lower bound; negative where the field is signed",
    "max": "numeric upper bound and full-width text: catches truncation",
    "typical": "a plausible production value, for the happy path",
}

CASES = {**FIELD_CASES, **{k: f"every byte set to 0x{v:02X}" for k, v in FILL_CASES.items()}}


class EncodingError(ValueError):
    """Raised when a value cannot be represented in a field."""


def pack_zoned(value: int, digits: int, signed: bool, charset: str) -> bytes:
    """Zoned decimal (USAGE DISPLAY numeric)."""
    text = str(abs(value)).rjust(digits, "0")[-digits:]
    if charset != EBCDIC:
        return text.encode("ascii")
    out = bytearray(0xF0 | int(character) for character in text)
    if signed:
        # High nibble of the final byte carries the sign: C positive, D negative.
        out[-1] = (0xD0 if value < 0 else 0xC0) | (out[-1] & 0x0F)
    return bytes(out)


def pack_decimal(value: int, digits: int, signed: bool) -> bytes:
    """Packed decimal (COMP-3): one nibble per digit plus a trailing sign nibble."""
    text = str(abs(value)).rjust(digits, "0")[-digits:]
    sign = "D" if (signed and value < 0) else ("C" if signed else "F")
    nibbles = text + sign
    if len(nibbles) % 2:
        nibbles = "0" + nibbles
    return bytes.fromhex(nibbles)


def pack_binary(value: int, size: int) -> bytes:
    """COMP / BINARY: big-endian two's complement.

    Always signed, because that is how z/OS stores it regardless of whether the
    PICTURE carries an ``S``.
    """
    try:
        return value.to_bytes(size, "big", signed=True)
    except OverflowError as error:
        raise EncodingError(f"{value} does not fit in {size} bytes") from error


def encode(node: Field, value, charset: str = EBCDIC) -> bytes:
    """Encode one elementary field's value into its on-disk bytes."""
    if node.storage is None:
        raise EncodingError(f"{node.path}: no computed storage")
    size = node.storage.size
    picture = node.picture

    if node.usage in (FLOAT_SHORT, FLOAT_LONG):
        import struct

        fmt = ">f" if node.usage == FLOAT_SHORT else ">d"
        return struct.pack(fmt, float(value))

    if node.usage == PACKED:
        return pack_decimal(int(value), picture.digits, picture.signed)

    if node.usage == BINARY:
        return pack_binary(int(value), size)

    if node.usage == NATIONAL or (picture and picture.category == "national"):
        text = str(value)[: size // 2].ljust(size // 2)
        return text.encode("utf-16-be")

    if picture and picture.is_numeric and picture.category == "numeric":
        return pack_zoned(int(value), picture.digits, picture.signed, charset)

    # Alphanumeric, alphabetic and numeric-edited all travel as characters.
    text = str(value)[:size].ljust(size)
    return text.encode(charset, errors="replace")


def build(record: Record, case: str = "typical", charset: str = EBCDIC) -> bytes:
    """Render a whole record for a named case."""
    if case in FILL_CASES:
        return bytes([FILL_CASES[case]]) * record.length
    if case not in FIELD_CASES:
        raise EncodingError(f"unknown case {case!r}; try {', '.join(CASES)}")

    buffer = bytearray(b"\x40" if charset == EBCDIC else b" ") * record.length
    for node in record.flatten(elementary_only=True):
        if node.storage is None or node.storage.size == 0:
            continue
        if node.picture and node.picture.category == "numeric-edited":
            continue  # Edited pictures are output-only; never feed them input.
        if node.under_redefinition:
            # A redefinition shares bytes with the primary definition, so
            # writing both would mean the last one parsed silently wins. The
            # primary definition is authoritative; use --record to pick the
            # other reading deliberately.
            continue
        try:
            value = case_value(node, case)
            encoded = encode(node, value, charset)
        except (EncodingError, ValueError):
            continue
        # Fill every occurrence, including those of any enclosing OCCURS group.
        for start in _occurrences(node):
            if start + len(encoded) <= len(buffer):
                buffer[start : start + len(encoded)] = encoded
    return bytes(buffer)


def _occurrences(node) -> list[int]:
    """Every byte offset at which ``node`` appears, expanding nested OCCURS."""
    offsets = [node.offset]
    for group in node.ancestors:
        if group.occurs > 1:
            offsets = [
                offset + index * group.unit_size
                for offset in offsets
                for index in range(group.occurs)
            ]
    if node.occurs > 1:
        offsets = [
            offset + index * node.unit_size
            for offset in offsets
            for index in range(node.occurs)
        ]
    return offsets


def case_value(node: Field, case: str):
    """The value this field takes in a named case."""
    picture = node.picture
    size = node.storage.size if node.storage else 0

    if picture is None or not picture.is_numeric:
        if case in ("zero", "min"):
            return ""
        if case == "max":
            return "X" * size
        # A recognizable value, so a failing fixture points at its own field.
        return node.name.replace("-", "")[:size] or "SAMPLE"[:size]

    low, high = value_range(picture, node.usage)
    if case == "zero":
        return 0
    if case == "min":
        return low
    if case == "max":
        return high
    # A typical value: mid-range, scaled so the fractional digits are exercised.
    return high // 3 if high >= 3 else high


@dataclass
class Boundary:
    """One field's test obligations."""

    path: str
    position: int
    length: int
    picture: str
    usage: str
    values: list[str]
    notes: list[str]


def boundaries(record: Record) -> list[Boundary]:
    """Derive the per-field boundary matrix a characterization suite must cover."""
    out: list[Boundary] = []
    for node in record.flatten(elementary_only=True):
        if node.storage is None:
            continue
        picture = node.picture
        values: list[str] = []
        notes: list[str] = []

        if picture and picture.is_numeric and picture.category == "numeric":
            low, high = value_range(picture, node.usage)
            values = ["0", str(low), str(high)]
            if picture.scale:
                notes.append(
                    f"implied {picture.scale} decimal place(s): the stored integer "
                    f"is the value times 10^{picture.scale}"
                )
            if not picture.signed:
                notes.append(
                    "unsigned: a negative result is stored as its absolute value, "
                    "silently. Test that the replacement does the same"
                )
            if node.usage == BINARY:
                notes.append(
                    f"COMP occupies {node.storage.size} bytes, so it physically "
                    "accepts values outside the PICTURE's range; production data "
                    "may already contain them"
                )
            if node.usage == PACKED:
                notes.append(
                    "COMP-3 sign nibble is C/D when signed and F when not; an "
                    "unsigned field fed a negative value keeps nibble F"
                )
            if node.usage == DISPLAY and picture.signed:
                notes.append(
                    "signed DISPLAY: the sign is overpunched into the last digit, "
                    "so the field is not plain ASCII digits"
                )
        elif picture and picture.category == "numeric-edited":
            values = ["(output only)"]
            notes.append("edited PICTURE: a display format, never an input field")
        else:
            values = ["spaces", "1 character", f"{node.storage.size} characters"]
            notes.append(
                "EBCDIC collation is not alphabetical: digits sort above letters, "
                "so any ordering the program relies on changes under ASCII"
            )

        # OCCURS is usually declared on an enclosing group, so the obligation
        # has to be inherited or every field inside a table loses it.
        for group in node.repetition:
            where = "this field" if group is node else f"enclosing `{group.name}`"
            if group.occurs > 1:
                notes.append(
                    f"OCCURS {group.occurs} on {where}: test the first and last "
                    f"element, and subscripts 0 and {group.occurs + 1} if the "
                    "program computes them (COBOL does not bounds-check "
                    "without SSRANGE)"
                )
            if group.depending_on:
                notes.append(
                    f"length of {where} depends on {group.depending_on}: test the "
                    f"minimum ({group.occurs_min}), the maximum ({group.occurs}), "
                    "and one past each"
                )
        if node.redefines:
            notes.append(
                f"REDEFINES {node.redefines}: the same bytes carry two meanings. "
                "A test must cover both readings"
            )
        if node.slack_before:
            notes.append(
                f"{node.slack_before} slack byte(s) inserted before this field by "
                "SYNCHRONIZED; they are not part of any field and may hold garbage"
            )

        out.append(
            Boundary(
                path=node.path,
                position=node.position,
                length=node.storage.size,
                picture=picture.source if picture else "(group)",
                usage=node.usage,
                values=values,
                notes=notes,
            )
        )
    return out


def hexdump(data: bytes, width: int = 16, charset: str = EBCDIC) -> str:
    """Render bytes with both hex and the decoded characters."""
    lines: list[str] = []
    for offset in range(0, len(data), width):
        chunk = data[offset : offset + width]
        hex_part = " ".join(f"{byte:02X}" for byte in chunk).ljust(width * 3 - 1)
        try:
            text = chunk.decode(charset, errors="replace")
        except LookupError:
            text = ""
        printable = "".join(c if c.isprintable() else "." for c in text)
        lines.append(f"{offset:06X}  {hex_part}  |{printable}|")
    return "\n".join(lines)
