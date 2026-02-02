"""Build include dependency graph using gcc -H."""

import json
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class IncludeGraph:
    """Represents an include dependency graph."""

    edges: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    include_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    all_headers: set[str] = field(default_factory=set)


def extract_compile_flags(
    compile_commands_path: Path, source_pattern: str | None = None
) -> str:
    """Extract -I, -D, -isystem flags from compile_commands.json.

    Args:
        compile_commands_path: Path to compile_commands.json.
        source_pattern: Optional pattern to match source file names.

    Returns:
        Space-separated string of compiler flags.

    Raises:
        RuntimeError: If no suitable compile command is found.
    """
    with open(compile_commands_path) as f:
        commands = json.load(f)

    for cmd in commands:
        if source_pattern and source_pattern not in cmd["file"]:
            continue
        if not cmd["file"].endswith(".cpp"):
            continue

        parts = cmd["command"].split()
        flags = []
        i = 0
        while i < len(parts):
            if parts[i] == "-isystem" and i + 1 < len(parts):
                flags.extend([parts[i], parts[i + 1]])
                i += 2
            elif parts[i].startswith(("-I", "-D", "-isystem")):
                flags.append(parts[i])
                i += 1
            else:
                i += 1

        if flags:
            return " ".join(flags)

    raise RuntimeError("No suitable compile command found")


def run_gcc_h(header_path: Path, compile_flags: str, cxx_std: str = "c++20") -> str:
    """Run gcc -H to extract include hierarchy.

    Args:
        header_path: Path to the header file to analyze.
        compile_flags: Compiler flags (includes, defines, etc.).
        cxx_std: C++ standard to use.

    Returns:
        stderr output from gcc -H containing the include tree.
    """
    cmd = f"g++ -H -E -std={cxx_std} {compile_flags} {header_path}"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stderr


def parse_gcc_h_output(output: str) -> IncludeGraph:
    """Parse gcc -H output (dots indicate depth) into a graph.

    The gcc -H output format uses dots to indicate include depth:
    . header1.h
    .. header2.h (included by header1.h)
    ... header3.h (included by header2.h)
    .. header4.h (included by header1.h)

    Args:
        output: stderr output from gcc -H.

    Returns:
        IncludeGraph containing edges, counts, and all headers.
    """
    graph = IncludeGraph()
    stack: list[str] = []

    for line in output.split("\n"):
        match = re.match(r"^(\.+)\s+(.+)$", line)
        if match:
            depth = len(match.group(1))
            header = match.group(2).strip()

            graph.include_counts[header] += 1
            graph.all_headers.add(header)

            # Pop stack to get to parent level
            while len(stack) >= depth:
                stack.pop()

            # Add edge from parent to this header
            if stack:
                graph.edges[stack[-1]].add(header)

            stack.append(header)

    return graph
