"""Generate visualization outputs."""

import csv
import json
from pathlib import Path

from .graph import IncludeGraph


def generate_dot(
    graph: IncludeGraph,
    output_file: Path,
    focus_patterns: list[str] | None = None,
    max_nodes: int = 200,
    focus_depth: int = 1,
) -> None:
    """Generate Graphviz DOT file from include graph.

    Args:
        graph: The include graph to visualize.
        output_file: Path to write the DOT file.
        focus_patterns: If provided, only include headers matching any of these patterns
                        plus children up to focus_depth levels deep.
        max_nodes: Maximum number of nodes to include (most-included first).
        focus_depth: How many levels of children to include beyond focused headers.
    """
    def get_children(h: str, depth: int, visited: set[str] | None = None) -> set[str]:
        """Get children of a header up to a certain depth."""
        if visited is None:
            visited = set()
        if depth <= 0 or h in visited:
            return set()
        visited.add(h)
        children = set()
        for child in graph.edges.get(h, set()):
            children.add(child)
            if depth > 1:
                children.update(get_children(child, depth - 1, visited))
        return children

    # Determine which headers to include
    if focus_patterns:
        # Find headers matching any of the patterns
        focused = set()
        for pattern in focus_patterns:
            pattern_lower = pattern.lower()
            for h in graph.all_headers:
                if pattern_lower in h.lower():
                    focused.add(h)

        # Include focused headers plus their children up to focus_depth
        relevant = set(focused)
        for h in focused:
            relevant.update(get_children(h, focus_depth))
    else:
        sorted_headers = sorted(graph.include_counts.items(), key=lambda x: -x[1])
        relevant = {h for h, _ in sorted_headers[:max_nodes]}

    # Always include direct includes from root so the graph is connected
    relevant.update(graph.direct_includes)

    with open(output_file, "w") as f:
        f.write("digraph includes {\n")
        f.write("  rankdir=TB;\n")
        f.write("  node [shape=box, fontsize=10];\n")

        # Add root header as entry point (if set)
        root_name = None
        if graph.root:
            root_name = Path(graph.root).name
            f.write(
                f'  "{root_name}" [fillcolor=lightblue, style=filled, '
                f'shape=doubleoctagon, label="{root_name}\\n(root)"];\n'
            )

        # Write nodes with color based on include count
        for header in relevant:
            count = graph.include_counts.get(header, 0)
            if count > 10:
                color = "red"
            elif count > 5:
                color = "orange"
            elif count > 2:
                color = "yellow"
            else:
                color = "white"

            name = Path(header).name
            f.write(
                f'  "{name}" [fillcolor={color}, style=filled, '
                f'label="{name}\\n({count}x)"];\n'
            )

        # Write edges from root to direct includes
        if root_name and graph.direct_includes:
            for child in graph.direct_includes:
                if child in relevant:
                    child_name = Path(child).name
                    f.write(f'  "{root_name}" -> "{child_name}";\n')

        # Write edges between headers
        for parent, children in graph.edges.items():
            if parent not in relevant:
                continue
            for child in children:
                if child not in relevant:
                    continue
                parent_name = Path(parent).name
                child_name = Path(child).name
                f.write(f'  "{parent_name}" -> "{child_name}";\n')

        f.write("}\n")


def generate_json(graph: IncludeGraph, output_file: Path) -> None:
    """Generate JSON analysis file from include graph.

    Args:
        graph: The include graph to analyze.
        output_file: Path to write the JSON file.
    """
    # Compute transitive dependencies (handling cycles)
    cache: dict[str, set[str]] = {}
    visiting: set[str] = set()  # Track current path to detect cycles

    def get_deps(h: str) -> set[str]:
        if h in cache:
            return cache[h]
        if h in visiting:
            # Cycle detected, return empty to break recursion
            return set()
        visiting.add(h)
        deps: set[str] = set()
        for c in graph.edges.get(h, set()):
            deps.add(c)
            deps.update(get_deps(c))
        visiting.discard(h)
        cache[h] = deps
        return deps

    for h in graph.all_headers:
        get_deps(h)

    analysis = {
        "total_unique_headers": len(graph.all_headers),
        "graph": {k: list(v) for k, v in graph.edges.items()},
        "include_counts": dict(graph.include_counts),
        "transitive_dep_counts": {k: len(v) for k, v in cache.items()},
        "top_included": sorted(graph.include_counts.items(), key=lambda x: -x[1])[:30],
    }

    with open(output_file, "w") as f:
        json.dump(analysis, f, indent=2)


def generate_csv(results: list, output_file: Path) -> None:
    """Generate CSV file from benchmark results.

    Args:
        results: List of BenchmarkResult objects (as dicts).
        output_file: Path to write the CSV file.
    """
    if not results:
        return

    fieldnames = ["header", "max_rss_kb", "wall_time_s", "success", "error"]

    with open(output_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            if isinstance(r, dict):
                writer.writerow(r)
            else:
                writer.writerow(r.__dict__)


def generate_summary(
    graph: IncludeGraph, results: list | None, output_file: Path
) -> None:
    """Generate human-readable summary file.

    Args:
        graph: The include graph.
        results: Optional list of benchmark results.
        output_file: Path to write the summary file.
    """
    with open(output_file, "w") as f:
        f.write("=" * 60 + "\n")
        f.write("Include-What-Costs Analysis Summary\n")
        f.write("=" * 60 + "\n\n")

        f.write(f"Total unique headers: {len(graph.all_headers)}\n")
        f.write(f"Total include edges: {sum(len(v) for v in graph.edges.values())}\n\n")

        f.write("Top 20 Most-Included Headers:\n")
        f.write("-" * 40 + "\n")
        for header, count in sorted(
            graph.include_counts.items(), key=lambda x: -x[1]
        )[:20]:
            f.write(f"  {count:4d}x  {Path(header).name}\n")

        if results:
            f.write("\n")
            f.write("=" * 60 + "\n")
            f.write("Benchmark Results\n")
            f.write("=" * 60 + "\n\n")

            ok = [r for r in results if r.get("success", False)]
            failed = [r for r in results if not r.get("success", False)]

            f.write(f"Successful: {len(ok)}\n")
            f.write(f"Failed: {len(failed)}\n\n")

            if ok:
                f.write("Top 10 by RSS:\n")
                f.write("-" * 40 + "\n")
                for r in sorted(ok, key=lambda x: -x["max_rss_kb"])[:10]:
                    rss_mb = r["max_rss_kb"] / 1024
                    f.write(f"  {rss_mb:6.0f} MB  {r['header']}\n")

                f.write("\nTop 10 by compile time:\n")
                f.write("-" * 40 + "\n")
                for r in sorted(ok, key=lambda x: -x["wall_time_s"])[:10]:
                    f.write(f"  {r['wall_time_s']:6.1f} s   {r['header']}\n")
