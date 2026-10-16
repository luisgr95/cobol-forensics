"""cobolkit -- deterministic facts from legacy COBOL, JCL and copybooks.

The design rule: anything that can be computed is computed here, in Python,
with tests. Anything that requires judgement -- what a program is *for*, which
business rule a condition name encodes -- is left to a reader, human or model,
working from these facts.

That split is what makes the output trustworthy enough to put in front of a
client, and what keeps a 50,000-line codebase affordable to analyze.
"""

from .copybook import Field, Record, parse as parse_copybook, parse_file as parse_copybook_file
from .graph import Inventory, Program, analyze, analyze_file, analyze_tree
from .jcl import Dataset, Job, Step, parse as parse_jcl, parse_file as parse_jcl_file
from .pic import Picture, Storage, parse_picture, storage_for, value_range
from .records import boundaries, build, encode, hexdump

__version__ = "0.1.0"

__all__ = [
    "Dataset",
    "Field",
    "Inventory",
    "Job",
    "Picture",
    "Program",
    "Record",
    "Step",
    "Storage",
    "analyze",
    "analyze_file",
    "analyze_tree",
    "boundaries",
    "build",
    "encode",
    "hexdump",
    "parse_copybook",
    "parse_copybook_file",
    "parse_jcl",
    "parse_jcl_file",
    "parse_picture",
    "storage_for",
    "value_range",
]
