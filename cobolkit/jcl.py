"""JCL parsing: jobs, steps, programs and dataset lineage.

A COBOL program on its own tells you nothing about *when* it runs or *what
data* it runs against. The JCL does, and it is usually the only place the batch
schedule is written down. Reading it gives you the pairing that makes a
modernization plan possible: this job writes the dataset that job reads.

Continuation rules are the trap here. An operand field continues when the line
ends in a comma, and the continuation card restarts with ``//`` plus blanks.
Parsing cards independently splits ``DISP=(NEW,CATLG,`` from ``DELETE)`` and
every dataset comes out misclassified.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

_CARD = re.compile(r"^//(\S*)\s*(.*)$")
_OPERATION = re.compile(r"^(JOB|EXEC|DD|PROC|PEND|SET|IF|ELSE|ENDIF|INCLUDE|JCLLIB|OUTPUT)\b", re.I)
_PGM = re.compile(r"\bPGM\s*=\s*([A-Za-z0-9@#$][A-Za-z0-9@#$]*)", re.I)
_PROC = re.compile(r"\bPROC\s*=\s*([A-Za-z0-9@#$][A-Za-z0-9@#$]*)", re.I)
_DSN = re.compile(r"\bDSN(?:AME)?\s*=\s*([^,\s]+)", re.I)
_DISP = re.compile(r"\bDISP\s*=\s*(?:\(\s*([^,)]*)[^)]*\)|([A-Za-z]+))", re.I)
_SYSOUT = re.compile(r"\bSYSOUT\s*=", re.I)
_COND = re.compile(r"\b(COND|IF)\s*=", re.I)

#: DISP values that mean the step reads the dataset.
INPUT_DISP = {"SHR", "OLD"}
#: DISP values that mean the step writes it.
OUTPUT_DISP = {"NEW", "MOD"}


@dataclass
class Dataset:
    """One DD statement."""

    ddname: str
    dsn: str | None
    disp: str | None
    direction: str  # input | output | inline | sysout | unknown
    line: int

    @property
    def temporary(self) -> bool:
        """True for a temporary dataset (``&&NAME``) that never outlives the job."""
        return bool(self.dsn and self.dsn.startswith("&&"))

    @property
    def generation(self) -> bool:
        """True for a GDG reference such as ``PROD.FILE(+1)``."""
        return bool(self.dsn and re.search(r"\([+-]?\d+\)$", self.dsn))


@dataclass
class Step:
    """One EXEC statement and the DD statements that belong to it."""

    name: str
    program: str | None
    procedure: str | None
    line: int
    conditional: bool = False
    datasets: list[Dataset] = field(default_factory=list)

    @property
    def inputs(self) -> list[Dataset]:
        return [d for d in self.datasets if d.direction == "input" and d.dsn]

    @property
    def outputs(self) -> list[Dataset]:
        return [d for d in self.datasets if d.direction == "output" and d.dsn]


@dataclass
class Job:
    """A whole JCL member."""

    name: str
    path: str
    steps: list[Step] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def programs(self) -> list[str]:
        return [s.program for s in self.steps if s.program]

    def lineage(self) -> list[tuple[str, str, str]]:
        """``(producing step, dataset, consuming step)`` within this job."""
        written: dict[str, str] = {}
        out: list[tuple[str, str, str]] = []
        for step in self.steps:
            for dataset in step.inputs:
                if dataset.dsn in written:
                    out.append((written[dataset.dsn], dataset.dsn, step.name))
            for dataset in step.outputs:
                written[dataset.dsn] = step.name
        return out


def parse(raw: str, path: str = "<memory>") -> Job:
    """Parse one JCL member."""
    job = Job(name=os.path.splitext(os.path.basename(path))[0].upper(), path=path)
    current: Step | None = None

    # _cards() has already folded continuations and swallowed inline data, so
    # every tuple here is one complete statement.
    for name, operation, operands, line_number in _cards(raw):
        if operation == "JOB":
            job.name = name or job.name
            continue

        if operation == "EXEC":
            program = _search(_PGM, operands)
            procedure = _search(_PROC, operands)
            if not program and not procedure:
                # `// EXEC MYPROC` names a procedure positionally.
                bare = operands.split(",")[0].strip()
                if bare and "=" not in bare:
                    procedure = bare.upper()
            current = Step(
                name=name or f"STEP{len(job.steps) + 1:03d}",
                program=program,
                procedure=procedure,
                line=line_number,
                conditional=bool(_COND.search(operands)),
            )
            job.steps.append(current)
            continue

        if operation == "DD":
            if current is None:
                job.warnings.append(
                    f"line {line_number}: DD statement {name} appears before any EXEC"
                )
                continue
            current.datasets.append(_dataset(name, operands, line_number))
            continue

        if operation in ("IF", "ELSE", "ENDIF"):
            job.warnings.append(
                f"line {line_number}: conditional step execution ({operation}); "
                "the step list is the static order, not the executed order"
            )

    return job


def parse_file(path: str) -> Job:
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return parse(handle.read(), path)


#: Extensions treated as JCL.
JCL_SUFFIXES = (".jcl", ".job", ".prc", ".proc", ".cntl")


def parse_tree(root: str, suffixes: tuple[str, ...] = JCL_SUFFIXES) -> list[Job]:
    """Walk ``root`` and parse every JCL member found."""
    if os.path.isfile(root):
        return [parse_file(root)]
    jobs: list[Job] = []
    for directory, _, names in os.walk(root):
        for name in sorted(names):
            if name.lower().endswith(suffixes):
                jobs.append(parse_file(os.path.join(directory, name)))
    return jobs


def _cards(raw: str):
    """Yield ``(name, operation, operands, line)`` with continuations folded."""
    pending: tuple[str, str, list[str], int] | None = None
    in_inline = False

    for index, physical in enumerate(raw.splitlines(), start=1):
        line = physical.expandtabs(8)

        if in_inline:
            if line.startswith("/*") or line.startswith("//"):
                in_inline = False
            else:
                continue

        if line.startswith("//*") or not line.strip():
            continue
        if line.startswith("/*"):
            continue

        # Only the first 71 columns are JCL; 72 is the continuation indicator.
        body = line[:72].rstrip()
        card = _CARD.match(body)

        if pending is not None:
            if card and not _OPERATION.match(card.group(2).strip()):
                # A continuation card: `//` then blanks then more operands.
                pending[2].append(card.group(2).strip())
                if not pending[2][-1].endswith(","):
                    name, operation, parts, start = pending
                    operands = "".join(parts)
                    if operation == "DD" and _is_inline(operands):
                        in_inline = True
                    yield name, operation, operands, start
                    pending = None
                continue
            name, operation, parts, start = pending
            operands = "".join(parts)
            if operation == "DD" and _is_inline(operands):
                in_inline = True
            yield name, operation, operands, start
            pending = None

        if not card:
            continue

        name = card.group(1).upper()
        rest = card.group(2).strip()
        operation_match = _OPERATION.match(rest)
        if not operation_match:
            continue
        operation = operation_match.group(1).upper()
        operands = rest[operation_match.end() :].strip()

        if operands.endswith(","):
            pending = (name, operation, [operands], index)
            continue

        if operation == "DD" and _is_inline(operands):
            in_inline = True
        yield name, operation, operands, index

    if pending is not None:
        name, operation, parts, start = pending
        yield name, operation, "".join(parts), start


def _is_inline(operands: str) -> bool:
    head = operands.split(",")[0].strip()
    return head in ("*", "DATA")


def _dataset(ddname: str, operands: str, line: int) -> Dataset:
    dsn = _search(_DSN, operands, upper=False)
    disp = _search(_DISP, operands) or _search(_DISP, operands, group=2)

    if _is_inline(operands):
        direction = "inline"
    elif _SYSOUT.search(operands):
        direction = "sysout"
    elif disp and disp.upper() in OUTPUT_DISP:
        direction = "output"
    elif disp and disp.upper() in INPUT_DISP:
        direction = "input"
    elif dsn:
        # No DISP defaults to NEW for a fresh allocation, but in practice an
        # omitted DISP on a named dataset is almost always a read.
        direction = "input"
    else:
        direction = "unknown"

    return Dataset(
        ddname=ddname or "(unnamed)",
        dsn=dsn.upper() if dsn else None,
        disp=disp.upper() if disp else None,
        direction=direction,
        line=line,
    )


def _search(
    pattern: re.Pattern[str], text: str, group: int = 1, upper: bool = True
) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    value = match.group(group)
    if value is None:
        return None
    value = value.strip()
    return value.upper() if upper else value
