---
description: Write a functional specification for a COBOL program from its source and JCL
argument-hint: <path to program> [path to JCL tree]
allowed-tools: Bash(python -m cobolkit:*), Glob, Grep, Read, Write
---

Write a functional specification for the program at `$1`.

Follow the `cobol-forensics` skill, including its section on writing a
functional specification. Steps:

1. Run `python -m cobolkit inventory $1 --json` for the program's structural
   facts.
2. Map every copybook it uses with `python -m cobolkit copybook`.
3. If `$2` is given, or a JCL directory exists in the tree, run
   `python -m cobolkit jcl` to find which job and step runs this program and
   which datasets it is given.
4. Now read the source, for business logic only. The structure is already
   known; do not re-derive it by reading.
5. Produce the specification with these sections, in order: Purpose, Trigger,
   Inputs and outputs, Business rules (numbered), Error handling, Open
   questions.

Requirements:

- Every business rule cites the paragraph it came from.
- Every inference is marked as an inference. "The program appears to..." is
  correct where you are inferring; "The program..." is for what the code
  states.
- The Open questions section must not be empty. If you believe you understood
  everything, you have not looked at the dynamic calls, the computed GO TOs, or
  the paragraphs reachable only by fallthrough.
- Quote conditions from the source, but keep quotes to the single condition
  under discussion. Never paste whole paragraphs of a client's source into the
  document.

Write to `docs/<PROGRAM-ID>.md` if `docs/` exists; otherwise print it.
