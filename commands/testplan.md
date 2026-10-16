---
description: Build a characterization-test plan and fixtures so a rewrite can be proven equivalent
argument-hint: <path to copybook> [path to program]
allowed-tools: Bash(python -m cobolkit:*), Read, Write
---

Build a characterization-test plan for the record layout at `$1`, for the
program at `$2` if given.

Follow the `cobol-forensics` skill, including its section on building a
characterization suite. Steps:

1. Run `python -m cobolkit boundaries $1` for the per-field obligations.
2. Generate a fixture for every case and save them:
   ```
   python -m cobolkit testdata $1 --case zero        -o fixtures/zero.bin
   python -m cobolkit testdata $1 --case min         -o fixtures/min.bin
   python -m cobolkit testdata $1 --case max         -o fixtures/max.bin
   python -m cobolkit testdata $1 --case typical     -o fixtures/typical.bin
   python -m cobolkit testdata $1 --case low-values  -o fixtures/low.bin
   python -m cobolkit testdata $1 --case high-values -o fixtures/high.bin
   ```
   These are EBCDIC by default, which is what the program reads. Use
   `--charset ascii` only for a human-readable copy.
3. If `$2` is given, read it and add one case per business rule: each decision
   point needs an input that takes each branch.
4. Produce the plan as a table: case, what it proves, which fields it pins,
   expected disposition.

State these explicitly in the plan:

- The current program's output **is** the expected output, bugs included. Any
  case where the current behaviour looks wrong gets flagged for the client to
  decide, and is still pinned as-is until they do.
- Which fields could not be exercised and why: variable-length tables, fields
  only reachable through a dynamic call, dead paragraphs.
- That a passing suite proves equivalence **on these inputs only**. Say what
  production data you would need to sample to raise confidence, and name the
  fields most likely to hold values outside their declared range.

Write to `docs/testplan-<RECORD>.md` if `docs/` exists; otherwise print it.
