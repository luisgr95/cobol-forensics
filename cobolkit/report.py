"""Markdown rendering.

Reports are written for two readers at once: a developer who needs exact
offsets, and an analyst who needs to know what the program is for. Both get
tables; neither gets prose invented by this module. Anything interpretive is
left for the model to add on top of these facts.
"""

from __future__ import annotations

from .copybook import Record
from .graph import Inventory, Program
from .jcl import Job
from .records import Boundary, boundaries


def copybook_report(records: list[Record], title: str = "Copybook byte map") -> str:
    out = [f"# {title}", ""]
    for record in records:
        out.append(f"## {record.name}")
        out.append("")
        out.append(f"Record length: **{record.length} bytes**")
        variable = [f for f in record.flatten() if f.depending_on]
        if variable:
            out.append("")
            out.append(
                "> Variable length. The figure above is the maximum, with every "
                "`OCCURS DEPENDING ON` at its upper bound."
            )
        out.append("")
        out.append("| Lvl | Field | Pos | Len | PIC | Usage | Occurs | Redefines |")
        out.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for node in record.flatten():
            indent = "&nbsp;" * (node.level - 1) * 2
            picture = node.picture.source if node.picture else ""
            usage = node.usage if not node.is_group else ""
            occurs = str(node.occurs) if node.occurs > 1 else ""
            if node.depending_on:
                occurs = f"{node.occurs_min}-{node.occurs} dep. {node.depending_on}"
            out.append(
                f"| {node.level:02d} | {indent}`{node.name}` | {node.position} "
                f"| {node.total_size} | `{picture}` | {usage} | {occurs} "
                f"| {node.redefines or ''} |"
            )
        out.append("")

        conditions = [(f, f.conditions) for f in record.flatten() if f.conditions]
        if conditions:
            out.append("### Condition names")
            out.append("")
            out.append("| Field | Condition | Value |")
            out.append("| --- | --- | --- |")
            for node, items in conditions:
                for name, value in items:
                    out.append(f"| `{node.name}` | `{name}` | `{value}` |")
            out.append("")
            out.append(
                "Condition names are the closest thing to documented business "
                "rules in most copybooks. Carry them into the replacement as "
                "named constants, not as magic literals."
            )
            out.append("")

        if record.warnings:
            out.append("### Parser warnings")
            out.append("")
            for warning in record.warnings:
                out.append(f"- {warning}")
            out.append("")
    return "\n".join(out)


def boundaries_report(records: list[Record]) -> str:
    out = ["# Characterization-test boundary matrix", ""]
    out.append(
        "Each row is a field and the values a regression suite must pin before "
        "anything is rewritten. The notes call out behaviour the replacement "
        "will not reproduce by accident."
    )
    out.append("")
    for record in records:
        out.append(f"## {record.name}")
        out.append("")
        rows: list[Boundary] = boundaries(record)
        out.append("| Field | Pos | Len | PIC | Usage | Values to cover |")
        out.append("| --- | --- | --- | --- | --- | --- |")
        for row in rows:
            values = ", ".join(f"`{v}`" for v in row.values)
            out.append(
                f"| `{row.path}` | {row.position} | {row.length} | `{row.picture}` "
                f"| {row.usage} | {values} |"
            )
        out.append("")
        noted = [row for row in rows if row.notes]
        if noted:
            out.append("### Field notes")
            out.append("")
            for row in noted:
                out.append(f"**`{row.path}`**")
                for note in row.notes:
                    out.append(f"- {note}")
                out.append("")
    return "\n".join(out)


def inventory_report(inventory: Inventory) -> str:
    out = ["# Program inventory", ""]
    out.append(f"{len(inventory.programs)} compilation unit(s) analyzed.")
    out.append("")

    out.append("| Program | Lines | Paragraphs | Calls | Copybooks | DB2 | CICS |")
    out.append("| --- | --- | --- | --- | --- | --- | --- |")
    for program in sorted(inventory.programs, key=lambda p: p.program_id):
        calls = len(program.static_calls) + len(program.dynamic_calls)
        out.append(
            f"| `{program.program_id}` | {program.source_lines} "
            f"| {len(program.paragraphs)} | {calls} | {len(program.copybooks)} "
            f"| {len(program.sql_tables)} | {len(program.cics_commands)} |"
        )
    out.append("")

    out.append("## Call graph")
    out.append("")
    edges = inventory.edges
    if not edges:
        out.append("No inter-program calls found.")
    else:
        out.append("```mermaid")
        out.append("graph LR")
        for caller, callee, kind in edges:
            arrow = "-->" if kind == "static" else "-.->"
            out.append(f"  {_node(caller)}{arrow}{_node(callee)}")
        out.append("```")
        out.append("")
        out.append("Solid edges are static calls. Dashed edges are dynamic.")
    out.append("")

    dynamic = [(p.program_id, p.dynamic_calls) for p in inventory.programs if p.dynamic_calls]
    if dynamic:
        out.append("## Dynamic calls")
        out.append("")
        out.append(
            "These targets come from a variable, so the real callee is only known "
            "at run time. Resolve them from production load-module traces or "
            "a CALL trace before trusting any impact analysis."
        )
        out.append("")
        for program_id, targets in dynamic:
            out.append(f"- `{program_id}` calls via {', '.join(f'`{t}`' for t in targets)}")
        out.append("")

    if inventory.missing:
        out.append("## Called but not present")
        out.append("")
        out.append(
            "Referenced by a static CALL with no source in this set. Either the "
            "source is missing from the extract, or it is a vendor or system module."
        )
        out.append("")
        for name in inventory.missing:
            out.append(f"- `{name}`")
        out.append("")

    if inventory.orphans:
        out.append("## Entry points")
        out.append("")
        out.append(
            "Nothing in this set calls these, so they are started from JCL, CICS "
            "or a scheduler -- or they are dead."
        )
        out.append("")
        for name in inventory.orphans:
            out.append(f"- `{name}`")
        out.append("")

    out.append("## Per-program detail")
    out.append("")
    for program in sorted(inventory.programs, key=lambda p: p.program_id):
        out.append(_program_detail(program))
    return "\n".join(out)


def _program_detail(program: Program) -> str:
    out = [f"### `{program.program_id}`", ""]
    out.append(f"Source: `{program.path}` ({program.source_lines} code lines)")
    out.append("")
    if program.entry_points:
        out.append(f"- Alternate entry points: {_csv(program.entry_points)}")
    if program.static_calls:
        out.append(f"- Static calls: {_csv(program.static_calls)}")
    if program.dynamic_calls:
        out.append(f"- Dynamic call variables: {_csv(program.dynamic_calls)}")
    if program.copybooks:
        out.append(f"- Copybooks: {_csv(program.copybooks)}")
    if program.sql_tables:
        out.append(f"- DB2 tables: {_csv(program.sql_tables)}")
    if program.sql_cursors:
        out.append(f"- Cursors: {_csv(program.sql_cursors)}")
    if program.cics_commands:
        out.append(f"- CICS commands: {_csv(program.cics_commands)}")
    if program.files:
        out.append("- Files:")
        for logical, physical in program.files:
            out.append(f"  - `{logical}` assigned to `{physical}`")
    if program.goto_count:
        out.append(f"- `GO TO` statements: {program.goto_count}")
    if program.dead_paragraphs:
        out.append(
            f"- Paragraphs never PERFORMed: {_csv(program.dead_paragraphs)} "
            "(may still be reached by fallthrough)"
        )
    if program.risks:
        out.append("- Modernization risks:")
        for risk in program.risks:
            out.append(f"  - {risk}")
    out.append("")
    return "\n".join(out)


def jcl_report(jobs: list[Job]) -> str:
    out = ["# JCL and batch data flow", ""]
    for job in jobs:
        out.append(f"## {job.name}")
        out.append("")
        out.append(f"Source: `{job.path}` -- {len(job.steps)} step(s)")
        out.append("")
        out.append("| Step | Program | Procedure | Inputs | Outputs |")
        out.append("| --- | --- | --- | --- | --- |")
        for step in job.steps:
            inputs = ", ".join(f"`{d.dsn}`" for d in step.inputs) or "-"
            outputs = ", ".join(f"`{d.dsn}`" for d in step.outputs) or "-"
            flag = " (conditional)" if step.conditional else ""
            out.append(
                f"| `{step.name}`{flag} | `{step.program or ''}` "
                f"| `{step.procedure or ''}` | {inputs} | {outputs} |"
            )
        out.append("")

        lineage = job.lineage()
        if lineage:
            out.append("### Intra-job lineage")
            out.append("")
            out.append("```mermaid")
            out.append("graph LR")
            for producer, dataset, consumer in lineage:
                # Quoted, because dataset names carry parentheses and ampersands
                # that otherwise end the Mermaid label early.
                out.append(
                    f'  {_node(producer)}-->|"{dataset}"|{_node(consumer)}'
                )
            out.append("```")
            out.append("")

        gdg = [d for s in job.steps for d in s.datasets if d.generation]
        if gdg:
            out.append(
                "> Generation data groups in use "
                f"({_csv(sorted({d.dsn for d in gdg if d.dsn}))}). Relative "
                "generation numbers resolve at run time, so the dataset a step "
                "actually reads depends on what ran before it."
            )
            out.append("")

        if job.warnings:
            out.append("### Parser warnings")
            out.append("")
            for warning in job.warnings:
                out.append(f"- {warning}")
            out.append("")
    return "\n".join(out)


def _node(name: str) -> str:
    safe = name.replace("-", "_")
    return f"{safe}[{name}]"


def _csv(values) -> str:
    return ", ".join(f"`{value}`" for value in values)
