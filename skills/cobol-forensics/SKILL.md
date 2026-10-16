---
name: cobol-forensics
description: Recover intent from legacy COBOL, JCL and copybooks before rewriting them. Use when analyzing or modernizing mainframe code - reading a copybook or record layout, mapping which program calls which, tracing batch dataset lineage, writing a functional specification for a COBOL program, or building characterization tests so a rewrite can be proven equivalent. Triggers on COBOL, copybook, PIC clause, COMP-3, packed decimal, JCL, z/OS, CICS, DB2 precompiler, mainframe modernization, EBCDIC.
---

# COBOL forensics

Legacy COBOL is rarely hard to read line by line. What is missing is *intent*:
why a field is nine digits, which of three status codes is still reachable,
what the rounding rule is. That knowledge left with the people who wrote it.

This skill recovers it in a fixed order, and the order matters. Each step
depends on the one before, and skipping ahead produces documentation that reads
well and is wrong.

## The method

1. **Measure before reading.** Run the tools. Never hand-compute an offset or
   guess a call graph from reading source.
2. **Separate fact from inference.** Everything the CLI prints is a fact.
   Everything you add is inference, and must be labelled as such.
3. **Pin behaviour before changing it.** A rewrite is only safe against a
   characterization suite built from the *current* program, bugs included.
4. **Record what you could not determine.** An honest gap is worth more than a
   confident guess. Dynamic calls, computed GO TOs and dynamic SQL are real
   limits, not failures to work around.

## The tools

All output is deterministic and tested. Prefer `--json` when you need to reason
over the facts; prefer the default Markdown when the output is the deliverable.

```bash
python -m cobolkit copybook   <file>            # exact byte map
python -m cobolkit boundaries <file>            # per-field test obligations
python -m cobolkit inventory  <file-or-dir>     # programs, calls, resources
python -m cobolkit jcl        <file-or-dir>     # steps and dataset lineage
python -m cobolkit testdata   <file> --case max # a byte-exact fixture record
```

Run `inventory` on the whole tree first. It is cheap and it tells you which
programs are worth reading at all.

**Do not read a 5,000-line program into context to answer a structural
question.** `inventory --json` already answers who calls what, which copybooks
and tables are touched, and where the risk is. Read source only for the
business logic of a program you have decided matters.

## What the tools cannot tell you

Say so explicitly in any document you produce:

- **Dynamic `CALL`.** The target comes from a variable. The call graph is
  incomplete by construction. Resolving it needs production load-module traces.
- **Dynamic SQL.** `PREPARE` / `EXECUTE IMMEDIATE` means the tables touched are
  not statically knowable.
- **`COPY ... REPLACING`.** Field names are reported as written in the
  copybook, not after substitution.
- **Dead code.** "Never `PERFORM`ed" is lexical. A paragraph reached by
  fallthrough from the one above it is live.
- **`SYNCHRONIZED` on a group.** Slack bytes inside groups are
  compiler-dependent; the tool warns rather than guessing.
- **Conditional JCL.** `IF`/`COND` means the step list is static order, not
  executed order.

## Storage rules worth knowing

The parser implements these. Knowing them tells you when a report is surprising
versus wrong.

| Declaration | Bytes | Why |
| --- | --- | --- |
| `PIC 9(8)` | 8 | one byte per digit under DISPLAY |
| `PIC S9(5)` | 5 | the sign is overpunched into the last digit, free |
| `PIC S9(5)` SIGN SEPARATE | 6 | now the sign costs a byte |
| `PIC S9(9)V99 COMP-3` | 6 | 11 digits + sign nibble = 12 nibbles |
| `PIC S9(8) COMP-3` | 5 | 9 nibbles, rounded up |
| `PIC 9(4) COMP` | 2 | digit bands: 1-4 halfword, 5-9 fullword, 10-18 double |
| `PIC ZZ,ZZ9.99` | 9 | editing characters occupy bytes; only 3 are digits |
| `PIC N(10)` | 20 | NATIONAL is UTF-16 |
| `PIC 9(3)PPP` | 3 | `P` scales without occupying storage |

`V` never occupies a byte. A `REDEFINES` item starts at the same offset as what
it redefines and adds nothing to the record length.

## Writing a functional specification

Work from `inventory --json` and the copybook map, then structure it so a
business analyst and a developer can both use it:

1. **Purpose** - one paragraph. What does this program accomplish for the
   business? Derive it from the paragraph names, the datasets in the JCL, and
   the tables it updates, and say which of those you inferred it from.
2. **Trigger** - which job and step runs it, and under what condition.
3. **Inputs and outputs** - from FILE-CONTROL plus the JCL DD statements, with
   the record layouts linked.
4. **Business rules** - one numbered rule per decision point. Quote the
   condition from the source. Condition names (`88` levels) are the highest
   quality evidence available; they were named by someone who knew the domain.
5. **Error handling** - every abend path and what it means operationally.
6. **Open questions** - what the code cannot tell you. Always non-empty.

Number the rules. A rewrite's tests get traced back to those numbers, and so
does any dispute about whether the rewrite is faithful.

## Building a characterization suite

`boundaries` produces the matrix. Turn it into tests this way:

1. Generate fixtures for `zero`, `min`, `max` and `typical`, plus
   `low-values` and `high-values` to see how the program handles garbage.
2. Capture the current program's output for each. **That output is the
   specification.** Do not clean it up.
3. Add a case per business rule from the functional spec.
4. Only then write the replacement, and make it match.

Rules that trip up every rewrite, and that your tests must pin:

- `COMPUTE` without `ROUNDED` **truncates toward zero**. A rewrite using
  banker's rounding produces different money.
- Moving a negative value into an unsigned field **silently stores its
  absolute value**.
- `COMP` physically holds values its `PICTURE` forbids, so production data may
  already be out of declared range.
- EBCDIC collation is not alphabetical: digits sort **above** letters. Any
  sort order the program relies on changes under ASCII.
- COBOL does not bounds-check subscripts unless compiled with `SSRANGE`, so
  out-of-range reads currently return adjacent memory rather than failing.

## Handling someone else's source

Treat the code as confidential by default.

- Never copy source you were given into a commit, an issue, a report or a
  public example. Reports carry names, offsets and metrics, not source text.
- Check whether the engagement permits sending the source to a model at all.
  Many financial and public-sector contracts do not, and a signed data
  processing agreement with zero retention is normally the precondition.
- When you need a shareable example, build it from this repository's
  `fixtures/`, which are synthetic.
