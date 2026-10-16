# cobol-forensics

Recover intent from legacy COBOL before you rewrite it.

A Claude Code plugin, plus a dependency-free Python CLI, for the work that
comes *before* a mainframe modernization: finding out what the code actually
does, where every byte of every record lives, and how to prove a replacement
behaves identically.

## Why this exists

Reading COBOL is not the hard part. The hard part is that nobody knows *why*
the code does what it does — why a field is nine digits, which of three status
codes is still reachable, whether the rounding is deliberate. That knowledge
left with the people who wrote it, and the comments were last updated in 1998.

Consultancies bill a great deal of money to rediscover it. Most of that work is
mechanical and belongs in a tool.

## The design rule

**Anything that can be computed is computed in Python, with tests. Anything
requiring judgement is left to a reader, human or model.**

This matters for three reasons:

- **Correctness.** A language model asked to compute the byte offset of the
  fourteenth field in a copybook with `REDEFINES`, `OCCURS` and packed decimal
  will usually be close and occasionally wrong. Close is useless: an error of
  one byte shifts every field after it. So offsets come from a parser with 127
  tests behind them, not from a prompt.
- **Cost.** A 50,000-line codebase does not fit in a context window, and
  shouldn't have to. `inventory --json` answers who-calls-what for the whole
  tree in milliseconds, so the model reads only the programs that matter.
- **Trust.** You can hand a client a report and say which lines are measured
  and which are inferred. That distinction is the whole product.

## Install

```bash
/plugin install cobol-forensics --marketplace luisgr95/cobol-forensics
```

The CLI needs Python 3.10+ and nothing else. No pip install, no dependencies —
deliberately, because the machines that hold this kind of source are often the
ones where you cannot install anything.

## Use it

Four slash commands, each backed by the same deterministic tools:

| Command | What you get |
| --- | --- |
| `/cobol:inventory <dir>` | Programs, call graph, DB2 tables, datasets, ranked risk, and a recommended reading order |
| `/cobol:copybook <file>` | Exact byte map plus a data dictionary, with inferences marked as inferences |
| `/cobol:document <program>` | A functional specification: purpose, trigger, numbered business rules, open questions |
| `/cobol:testplan <copybook>` | A characterization-test plan and byte-exact EBCDIC fixtures |

Or drive the CLI directly:

```bash
python -m cobolkit copybook   CUSTREC.cpy              # byte map
python -m cobolkit boundaries CUSTREC.cpy              # test obligations
python -m cobolkit inventory  src/                     # programs and calls
python -m cobolkit jcl        jcl/                     # steps and lineage
python -m cobolkit testdata   CUSTREC.cpy --case max   # a fixture record
```

Every subcommand takes `--json`.

## What it looks like

A byte map, from the synthetic copybook in `fixtures/`:

```
| Lvl | Field               | Pos | Len | PIC          | Usage   | Occurs                    | Redefines |
| 01  | CUSTOMER-RECORD     | 1   | 172 |              |         |                           |           |
| 05  | CUST-ID             | 1   | 8   | 9(8)         | DISPLAY |                           |           |
| 05  | CUST-STATUS         | 9   | 1   | X            | DISPLAY |                           |           |
| 05  | CUST-NAME           | 10  | 50  |              |         |                           |           |
| 10  | CUST-FIRST          | 10  | 20  | X(20)        | DISPLAY |                           |           |
| 10  | CUST-LAST           | 30  | 30  | X(30)        | DISPLAY |                           |           |
| 05  | CUST-NAME-FLAT      | 10  | 50  | X(50)        | DISPLAY |                           | CUST-NAME |
| 05  | CUST-BALANCE        | 60  | 6   | S9(9)V99     | COMP-3  |                           |           |
| 05  | CUST-REGION-CODE    | 79  | 2   | 9(4)         | COMP    |                           |           |
| 05  | CUST-PHONES         | 83  | 80  |              |         | 1-5 dep. CUST-PHONE-COUNT |           |
```

Note what that required getting right: the redefinition shares `CUST-NAME`'s
offset and adds nothing to the length; `S9(9)V99 COMP-3` is six bytes because
eleven digits plus a sign nibble round up; `9(4) COMP` is two bytes from its
digit count, not its value range; and the record is variable-length, so 172 is
a maximum.

And a fixture, byte-exact, in EBCDIC, as the program would read it:

```
000000  F9 F9 F9 F9 F9 F9 F9 F9 E7 E7 E7 E7 E7 E7 E7 E7  |99999999XXXXXXXX|
000030  E7 E7 E7 E7 E7 E7 E7 E7 E7 E7 E7 99 99 99 99 99  |XXXXXXXXXXXrrrrr|
000040  9C 99 99 99 99 9C F9 F9 F9 F9 F9 F9 F9 F9 27 0F  |.rrrr.99999999..|
```

`99 99 99 99 99 9C` is the packed balance at position 60, sign nibble `C`.
`27 0F` is the binary region code at 79. Those are the bytes, not a
description of them.

See [`examples/sample-report.md`](examples/sample-report.md) for the full
inventory and JCL reports these fixtures produce, call graph included.

## What it will not tell you

Named up front, because a tool that hides its limits is worse than no tool.

- **Dynamic `CALL`.** When the target is a variable, the call graph is
  incomplete by construction. The reports say so, per program, rather than
  presenting a tidy graph that happens to be missing edges.
- **Dynamic SQL.** `PREPARE` and `EXECUTE IMMEDIATE` mean the tables touched
  are not statically knowable.
- **`COPY ... REPLACING`** is not expanded; fields are reported as the copybook
  declares them.
- **Dead code** is lexical. "Never `PERFORM`ed" does not mean unreachable — a
  paragraph can be reached by fallthrough.
- **`SYNCHRONIZED` on a group item.** Elementary alignment is computed; slack
  inside groups is compiler-dependent, so the tool warns instead of guessing.
- **Conditional JCL.** With `IF` or `COND`, the step list is static order, not
  executed order.

It is a lexical analyzer, not a compiler. It does not resolve the full COBOL
grammar, and it is not a substitute for compiling the code.

## Your client's source stays put

The CLI makes no network calls. It reads files and writes reports.

The reports carry field names, offsets, metrics and risk flags — not source
text — so they are safe to share in a way the source is not. Before sending
anyone's COBOL to any model, check that the engagement permits it; many
financial and public-sector contracts require a zero-retention data processing
agreement first, and some forbid it outright.

Everything in `fixtures/` is synthetic, written for this repository to exercise
the parser against the cases that break naive tools. It is not derived from any
real system.

## Tests

```bash
python -m unittest discover -s tests -t .
```

127 tests. The storage sizing tests are hand-computed from the IBM Enterprise
COBOL rules; the fixtures deliberately include a group `REDEFINES`, COMP-3 at
both odd and even digit counts, `OCCURS DEPENDING ON`, `SYNCHRONIZED`
alignment, a `CALL` inside a `DISPLAY` literal, SQL `SELECT` next to
FILE-CONTROL `SELECT`, JCL operand continuation, and inline SYSIN data.

Two bugs found by writing those tests, both still covered by regressions: a
`DISPLAY 'CALL THE OPERATOR'` literal registering a subprogram named `THE`,
and `OCCURS` obligations being dropped when declared on a parent group.

## Scope

Targets IBM Enterprise COBOL for z/OS, with JCL, the DB2 precompiler and CICS.
Fixed and free source formats are both detected. Other dialects mostly work,
since the storage rules are shared, but they are not tested here.

## Licence

MIT. See [LICENSE](LICENSE).
