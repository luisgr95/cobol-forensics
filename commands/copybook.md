---
description: Produce an exact byte map and data dictionary for a copybook
argument-hint: <path to copybook or program>
allowed-tools: Bash(python -m cobolkit:*), Read, Write
---

Produce a byte map and data dictionary for the copybook at `$1`.

Follow the `cobol-forensics` skill. Steps:

1. Run `python -m cobolkit copybook $1` for the map, and
   `python -m cobolkit copybook $1 --json` if you need to reason over fields.
2. Present the byte map as returned. Do not recompute or adjust any offset.
3. Add a data dictionary: for each field, its business meaning, inferred from
   the field name, its condition names and its picture. Mark every inference
   as an inference. Where a name is opaque, say so rather than inventing a
   meaning.
4. Call out, as a separate section, anything that will not survive a naive
   migration to a modern type system:
   - `REDEFINES`: the same bytes with two meanings, and which one is primary
   - `OCCURS DEPENDING ON`: the record is variable length
   - `COMP` fields whose storage admits values the picture forbids
   - signed `DISPLAY` fields, which are not plain digits on disk
   - `SYNCHRONIZED` slack bytes, which belong to no field
5. Report every parser warning verbatim. They are the known-unknowns.

If the file is a program rather than a copybook, the tool reads its
DATA DIVISION; note which record you mapped if there are several.
