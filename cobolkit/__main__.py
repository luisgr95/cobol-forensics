"""Command line interface.

    python -m cobolkit copybook   CUSTREC.cpy
    python -m cobolkit inventory  src/
    python -m cobolkit jcl        jcl/
    python -m cobolkit boundaries CUSTREC.cpy
    python -m cobolkit testdata   CUSTREC.cpy --case max -o max.bin

Every subcommand takes ``--json`` so an agent can consume the facts directly
instead of re-reading the source.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys

from . import copybook, graph, jcl, records, report
from .records import EBCDIC


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cobolkit",
        description="Deterministic facts from legacy COBOL, JCL and copybooks.",
    )
    parser.add_argument(
        "--format",
        choices=("fixed", "free"),
        default=None,
        help="COBOL source format; detected per file when omitted",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("copybook", "byte map of a copybook or DATA DIVISION"),
        ("boundaries", "characterization-test boundary matrix"),
    ):
        sub = subparsers.add_parser(name, help=help_text)
        sub.add_argument("path")
        sub.add_argument("--json", action="store_true", help="emit JSON")

    inventory = subparsers.add_parser("inventory", help="programs, calls and resources")
    inventory.add_argument("path", help="a source file or a directory to walk")
    inventory.add_argument("--json", action="store_true", help="emit JSON")

    jcl_parser = subparsers.add_parser("jcl", help="jobs, steps and dataset lineage")
    jcl_parser.add_argument("path", help="a JCL member or a directory to walk")
    jcl_parser.add_argument("--json", action="store_true", help="emit JSON")

    testdata = subparsers.add_parser("testdata", help="emit a fixture record")
    testdata.add_argument("path")
    testdata.add_argument(
        "--case", default="typical", help=f"one of: {', '.join(records.CASES)}"
    )
    testdata.add_argument("--record", default=None, help="record name, if the file has several")
    testdata.add_argument(
        "--charset", default=EBCDIC, help="cp037 (default, mainframe) or ascii"
    )
    testdata.add_argument("-o", "--output", default=None, help="write bytes to a file")
    testdata.add_argument("--hex", action="store_true", help="print a hex dump")

    args = parser.parse_args(argv)

    try:
        return _dispatch(args)
    except FileNotFoundError as error:
        print(f"cobolkit: {error.strerror}: {error.filename}", file=sys.stderr)
        return 2
    except (copybook.CopybookError, records.EncodingError, ValueError) as error:
        print(f"cobolkit: {error}", file=sys.stderr)
        return 1


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "copybook":
        parsed = copybook.parse_file(args.path, args.format)
        if not parsed:
            print("cobolkit: no DATA DIVISION entries found", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps([_record_json(r) for r in parsed], indent=2))
        else:
            print(report.copybook_report(parsed, f"Byte map: {args.path}"))
        return 0

    if args.command == "boundaries":
        parsed = copybook.parse_file(args.path, args.format)
        if args.json:
            payload = [
                {
                    "record": record.name,
                    "fields": [dataclasses.asdict(b) for b in records.boundaries(record)],
                }
                for record in parsed
            ]
            print(json.dumps(payload, indent=2))
        else:
            print(report.boundaries_report(parsed))
        return 0

    if args.command == "inventory":
        found = graph.analyze_tree(args.path, args.format)
        if args.json:
            print(json.dumps(_inventory_json(found), indent=2))
        else:
            print(report.inventory_report(found))
        return 0

    if args.command == "jcl":
        jobs = jcl.parse_tree(args.path)
        if args.json:
            print(json.dumps([_job_json(j) for j in jobs], indent=2))
        else:
            print(report.jcl_report(jobs))
        return 0

    if args.command == "testdata":
        parsed = copybook.parse_file(args.path, args.format)
        if not parsed:
            print("cobolkit: no records found", file=sys.stderr)
            return 1
        record = _pick(parsed, args.record)
        charset = EBCDIC if args.charset.lower() in ("cp037", "ebcdic") else "ascii"
        data = records.build(record, args.case, charset)
        if args.output:
            with open(args.output, "wb") as handle:
                handle.write(data)
            print(
                f"{len(data)} bytes written to {args.output} "
                f"({record.name}, case {args.case}, {charset})",
                file=sys.stderr,
            )
        if args.hex or not args.output:
            print(records.hexdump(data, charset=charset))
        return 0

    return 2


def _pick(parsed: list[copybook.Record], name: str | None) -> copybook.Record:
    if name is None:
        return parsed[0]
    for record in parsed:
        if record.name.upper() == name.upper():
            return record
    available = ", ".join(r.name for r in parsed)
    raise ValueError(f"no record named {name!r}; found: {available}")


def _record_json(record: copybook.Record) -> dict:
    return {
        "name": record.name,
        "length": record.length,
        "variable": any(f.depending_on for f in record.flatten()),
        "warnings": record.warnings,
        "fields": [
            {
                "level": node.level,
                "name": node.name,
                "path": node.path,
                "position": node.position,
                "offset": node.offset,
                "length": node.total_size,
                "unit_length": node.unit_size,
                "picture": node.picture.source if node.picture else None,
                "usage": node.usage if not node.is_group else None,
                "group": node.is_group,
                "digits": node.picture.digits if node.picture else None,
                "scale": node.picture.scale if node.picture else None,
                "signed": node.picture.signed if node.picture else None,
                "occurs": node.occurs,
                "depending_on": node.depending_on,
                "redefines": node.redefines,
                "slack_before": node.slack_before,
                "conditions": [
                    {"name": name, "value": value} for name, value in node.conditions
                ],
                "line": node.line,
            }
            for node in record.flatten()
        ],
    }


def _inventory_json(inventory: graph.Inventory) -> dict:
    return {
        "programs": [
            {
                **{
                    key: value
                    for key, value in dataclasses.asdict(program).items()
                },
                "dead_paragraphs": program.dead_paragraphs,
            }
            for program in inventory.programs
        ],
        "edges": [
            {"caller": caller, "callee": callee, "kind": kind}
            for caller, callee, kind in inventory.edges
        ],
        "missing": inventory.missing,
        "entry_points": inventory.orphans,
    }


def _job_json(job: jcl.Job) -> dict:
    return {
        "name": job.name,
        "path": job.path,
        "warnings": job.warnings,
        "steps": [
            {
                "name": step.name,
                "program": step.program,
                "procedure": step.procedure,
                "conditional": step.conditional,
                "line": step.line,
                "datasets": [dataclasses.asdict(d) for d in step.datasets],
            }
            for step in job.steps
        ],
        "lineage": [
            {"producer": producer, "dataset": dataset, "consumer": consumer}
            for producer, dataset, consumer in job.lineage()
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
