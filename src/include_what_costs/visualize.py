"""Generate visualization outputs."""

import csv
import json
from pathlib import Path

from .graph import IncludeGraph


def generate_dot(
    graph: IncludeGraph,
    output_file: Path,
    prefix: str | None = None,
    direct_includes: list[str] | None = None,
) -> None:
    """Generate Graphviz DOT file from include graph.

    Args:
        graph: The include graph to visualize.
        output_file: Path to write the DOT file.
        prefix: Only include headers under this path prefix.
        direct_includes: List of headers directly included by root (from parsing the file).
                        If None, uses graph.direct_includes (which may be incomplete due to
                        gcc -H not showing headers at depth 1 if already included deeper).
    """
    # Filter headers by prefix
    if prefix:
        prefix_resolved = str(Path(prefix).resolve())
        relevant = {h for h in graph.all_headers if h.startswith(prefix_resolved)}
        # Debug: show what's being filtered
        print(f"Prefix filter: {prefix_resolved}")
        print(f"Sample headers (first 5):")
        for h in list(graph.all_headers)[:5]:
            print(f"  {h} -> matches: {h.startswith(prefix_resolved)}")
        print(f"Headers matching prefix: {len(relevant)}")
    else:
        relevant = graph.all_headers

    with open(output_file, "w") as f:
        f.write("digraph includes {\n")
        # Use radial layout settings (rendered with twopi)
        f.write("  overlap=false;\n")
        f.write("  splines=true;\n")
        f.write("  node [shape=box, fontsize=10];\n")

        # Add root header as entry point (if set and matches prefix)
        root_name = None
        if graph.root:
            root_name = Path(graph.root).name
            # Mark as root for twopi radial layout
            f.write(
                f'  "{root_name}" [root=true, fillcolor=lightblue, style=filled, '
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
        # Use provided direct_includes (parsed from file) or fall back to graph.direct_includes
        root_children = direct_includes if direct_includes else graph.direct_includes
        if root_name and root_children:
            for child in root_children:
                # direct_includes from parse_includes() are relative (e.g., "Functors/Adapters.h")
                # We need to find matching full paths in relevant
                child_name = Path(child).name
                # Check if any relevant header ends with this include path
                for full_path in relevant:
                    if full_path.endswith(child) or Path(full_path).name == child_name:
                        f.write(f'  "{root_name}" -> "{Path(full_path).name}";\n')
                        break

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
