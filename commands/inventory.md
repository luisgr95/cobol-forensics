---
description: Inventory a COBOL codebase - programs, call graph, resources and modernization risk
argument-hint: [path to source tree]
allowed-tools: Bash(python -m cobolkit:*), Glob, Read, Write
---

Build a program inventory for the COBOL source at `$1` (default: the current
directory).

Follow the `cobol-forensics` skill. Steps:

1. Run `python -m cobolkit inventory $1 --json` to get the facts. If JCL is
   present anywhere in the tree, also run `python -m cobolkit jcl` on it.
2. Report, in this order:
   - how many programs, and the five largest by line count
   - the call graph, and which programs are entry points
   - statically called programs with no source present, flagged as a gap in
     the extract
   - every dynamic call, named as an explicit limit on the analysis
   - the DB2 tables and datasets the codebase touches
   - programs carrying modernization risk, ranked, with the reason
3. Recommend a reading order: which three programs to document first, and why.
   Base it on fan-in, resource breadth and risk, not on size alone.

Do not read program source during this task unless the inventory itself is
ambiguous. The point of the inventory is to decide what deserves reading.

Write the report to `docs/inventory.md` if that directory exists; otherwise
print it.
