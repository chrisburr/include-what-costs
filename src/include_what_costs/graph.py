"""Build include dependency graph using gcc -H."""

import json
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class IncludeGraph:
    """Represents an include dependency graph."""

    edges: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    include_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    all_headers: set[str] = field(default_factory=set)
    header_depths: dict[str, int] = field(default_factory=dict)  # Min depth for each header
    root: str | None = None  # The root header file being analyzed
    direct_includes: set[str] = field(default_factory=set)  # Depth-1 includes from root


def _extract_flags_from_command(cmd: dict) -> list[str]:
    """Extract -I, -D, -isystem, -std flags from a compile command.

    Args:
        cmd: A compile command entry with a "command" key.

    Returns:
        List of extracted compiler flags.
    """
    parts = cmd["command"].split()
    flags = []
    i = 0
    while i < len(parts):
        if parts[i] == "-isystem" and i + 1 < len(parts):
            flags.extend([parts[i], parts[i + 1]])
            i += 2
        elif parts[i].startswith(("-I", "-D", "-isystem", "-std")):
            flags.append(parts[i])
            i += 1
        else:
            i += 1
    return flags


def extract_compile_flags(
    compile_commands_path: Path,
    root_header: Path,
) -> str:
    """Extract -I, -D, -isystem flags from compile_commands.json.

    Args:
        compile_commands_path: Path to compile_commands.json.
        root_header: Root header path to auto-detect which source file's flags to use.

    Returns:
        Space-separated string of compiler flags.

    Raises:
        RuntimeError: If no suitable compile command is found.
    """
    with open(compile_commands_path) as f:
        commands = json.load(f)

    # Auto-detect source pattern from root header path
    # Extract component name from path like .../Phys/FunctorCore/include/...
    source_pattern = None
    parts = root_header.parts
    for i, part in enumerate(parts):
        if part == "include" and i > 0:
            source_pattern = parts[i - 1]  # e.g., "FunctorCore"
            break

    # First pass: try to match source pattern
    if source_pattern:
        for cmd in commands:
            if source_pattern not in cmd["file"]:
                continue
            if not cmd["file"].endswith(".cpp"):
                continue
            flags = _extract_flags_from_command(cmd)
            if flags:
                return " ".join(flags)

    # Fallback: use first available .cpp file's flags
    if source_pattern:
        print(
            f"Warning: No compile command found matching pattern '{source_pattern}', "
            "using fallback",
            file=sys.stderr,
        )

    for cmd in commands:
        if not cmd["file"].endswith(".cpp"):
            continue
        flags = _extract_flags_from_command(cmd)
        if flags:
            return " ".join(flags)

    raise RuntimeError(
        "No suitable compile command found"
        + (f" (searched for pattern: {source_pattern})" if source_pattern else "")
    )


def run_gcc_h(
    header_path: Path,
    compile_flags: str,
    wrapper: str | None = None,
) -> str:
    """Run gcc -H to extract include hierarchy.

    Args:
        header_path: Path to the header file to analyze.
        compile_flags: Compiler flags (includes, defines, etc.).
        wrapper: Optional wrapper command (e.g., "./Rec/run").

    Returns:
        stderr output from gcc -H containing the include tree.
    """
    gcc_cmd = f"g++ -H -E {compile_flags} {header_path}"
    if wrapper:
        # Wrap the gcc command in bash -c so the wrapper correctly passes all arguments
        # Redirect stderr to a temp file to avoid mixing with stdout
        import shlex
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.stderr', delete=False) as f:
            stderr_file = f.name
        gcc_cmd_with_redirect = f"{gcc_cmd} 2>{stderr_file}"
        cmd = f"{wrapper} bash -c {shlex.quote(gcc_cmd_with_redirect)}"
        subprocess.run(cmd, shell=True, capture_output=True, text=True)
        with open(stderr_file) as f:
            stderr_output = f.read()
        Path(stderr_file).unlink()  # Clean up temp file
        return stderr_output
    else:
        result = subprocess.run(gcc_cmd, shell=True, capture_output=True, text=True)
        return result.stderr


def supplement_edges_from_parsing(graph: IncludeGraph) -> int:
    """Add missing edges by parsing #include directives directly from headers.

    gcc -H only shows the first time each header is included, so edges can be
    missing when a header is included by multiple parents. This function parses
    each header file directly to find all #include directives and adds any
    missing edges.

    Args:
        graph: The include graph to supplement.

    Returns:
        Number of edges added.
    """
    from .parse_header import parse_includes

    # Build a lookup from include paths to full paths
    # e.g., "Functors/Function.h" -> "/full/path/.../Functors/Function.h"
    include_to_full: dict[str, str] = {}
    for header in graph.all_headers:
        # Add various suffix lengths for matching
        parts = Path(header).parts
        for i in range(1, min(len(parts) + 1, 6)):  # Up to 5 path components
            suffix = "/".join(parts[-i:])
            # Only store if not already mapped (prefer shorter suffixes)
            if suffix not in include_to_full:
                include_to_full[suffix] = header

    edges_added = 0

    for header in graph.all_headers:
        header_path = Path(header)
        if not header_path.exists():
            continue

        try:
            includes = parse_includes(header_path)
        except (OSError, UnicodeDecodeError):
            continue

        for inc in includes:
            # Try to resolve the include to a known full path
            target = include_to_full.get(inc)
            if target and target != header:
                # Check if this edge is missing
                if target not in graph.edges.get(header, set()):
                    graph.edges[header].add(target)
                    edges_added += 1

    return edges_added


def _compute_depths_bfs(graph: IncludeGraph) -> None:
    """Compute minimum depths using BFS from root through edges.

    This gives true shortest-path depths rather than gcc -H encounter order.
    Modifies graph.header_depths in place.
    """
    from collections import deque

    graph.header_depths.clear()

    # BFS from virtual root through direct_includes
    queue: deque[tuple[str, int]] = deque()
    for header in graph.direct_includes:
        if header in graph.all_headers:
            queue.append((header, 1))
            graph.header_depths[header] = 1

    while queue:
        node, depth = queue.popleft()
        for child in graph.edges.get(node, set()):
            if child not in graph.header_depths:
                graph.header_depths[child] = depth + 1
                queue.append((child, depth + 1))


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

            # Track direct includes (depth 1 = directly included by root)
            if depth == 1:
                graph.direct_includes.add(header)

            # Pop stack to get to parent level
            while len(stack) >= depth:
                stack.pop()

            # Add edge from parent to this header
            if stack:
                graph.edges[stack[-1]].add(header)

            stack.append(header)

    # Compute true minimum depths via BFS (gcc -H order isn't reliable)
    _compute_depths_bfs(graph)

    return graph
