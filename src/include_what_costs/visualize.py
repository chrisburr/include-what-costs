"""Generate visualization outputs."""

import csv
import json
from collections import defaultdict
from pathlib import Path

from .graph import IncludeGraph
from .layout import (
    apply_filter,
    build_layout_graph,
    classify_edges,
    compute_depths,
    compute_positions,
    extract_angles,
    render_graph,
)


def generate_html(
    graph: IncludeGraph,
    output_file: Path,
    prefix: str | None = None,
    direct_includes: list[str] | None = None,
    benchmark_results: list[dict] | None = None,
) -> None:
    """Generate interactive HTML visualization using pyvis.

    Nodes are positioned in concentric circles based on include depth,
    using twopi for angular positioning.

    Args:
        graph: The include graph to visualize.
        output_file: Path to write the HTML file.
        prefix: Only include headers under this path prefix.
        direct_includes: List of headers directly included by root (from parsing the file).
        benchmark_results: Optional list of benchmark result dicts with header costs.
    """
    # Convert IncludeGraph edges to dict format expected by layout module
    edges = {k: set(v) for k, v in graph.edges.items()}

    # Resolve direct includes to full paths
    root_children = direct_includes if direct_includes else list(graph.direct_includes)
    direct_include_names = {Path(inc).name for inc in root_children}
    direct_include_suffixes = set(root_children)

    def match_direct_include(header: str) -> bool:
        """Check if header is directly included by root."""
        name = Path(header).name
        if name in direct_include_names:
            for suffix in direct_include_suffixes:
                if header.endswith(suffix):
                    return True
        return False

    # Find depth-1 headers (full paths)
    depth1_headers: set[str] = set()
    for header in graph.all_headers:
        if match_direct_include(header):
            depth1_headers.add(header)

    # Use new layout module for depth computation
    headers_by_depth, header_to_depth = compute_depths(edges, depth1_headers)

    # Classify edges by type
    classified = classify_edges(edges, header_to_depth)

    # Apply filter first if specified (so layout is computed for visible nodes only)
    filter_result = None
    if prefix:
        filter_result = apply_filter(edges, prefix, graph.all_headers)
        # Print any warnings about paths through external headers
        for warning in filter_result.warnings:
            print(f"Warning: {warning}")

    # Determine which nodes will be visible
    if filter_result:
        visible_nodes = filter_result.included_nodes | filter_result.intermediate_nodes
    else:
        visible_nodes = set(header_to_depth.keys())

    # Filter depths and edges to only visible nodes for layout computation
    visible_depths = {h: d for h, d in header_to_depth.items() if h in visible_nodes}
    visible_edges = {
        parent: {child for child in children if child in visible_nodes}
        for parent, children in edges.items()
        if parent in visible_nodes
    }

    # Reclassify edges for visible nodes only
    visible_classified = classify_edges(visible_edges, visible_depths)

    # Build layout graph and extract angles for visible nodes only
    layout_graph = build_layout_graph(visible_edges, visible_depths, visible_classified)
    angles = extract_angles(layout_graph)

    # Compute positions with adaptive radii and ring alignment
    positions = compute_positions(angles, visible_depths, visible_edges)

    # Convert benchmark results to dict keyed by header
    benchmark_by_header: dict[str, dict] = {}
    if benchmark_results:
        for r in benchmark_results:
            if r.get("success"):
                benchmark_by_header[r["header"]] = {
                    "rss_kb": r["max_rss_kb"],
                    "time_s": r["wall_time_s"],
                }

    # Render the graph
    root_name = Path(graph.root).name if graph.root else None
    render_graph(
        positions=positions,
        edges=visible_edges,
        classified_edges=visible_classified,
        filter_result=filter_result,
        include_counts=dict(graph.include_counts),
        output_path=output_file,
        root_name=root_name,
        root_path=graph.root,
        benchmark_data=benchmark_by_header,
    )


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
    from collections import defaultdict

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

    # Group headers by depth for ring layout
    headers_by_depth: dict[int, list[str]] = defaultdict(list)
    for header in relevant:
        depth = graph.header_depths.get(header, 1)
        headers_by_depth[depth].append(header)

    max_depth = max(headers_by_depth.keys()) if headers_by_depth else 1
    print(f"Include depths: 1 to {max_depth} (headers per ring: {', '.join(f'd{d}={len(headers_by_depth[d])}' for d in sorted(headers_by_depth.keys())[:5])}...)")

    with open(output_file, "w") as f:
        f.write("digraph includes {\n")
        # Use radial layout settings (rendered with twopi)
        f.write("  overlap=false;\n")
        f.write("  splines=true;\n")
        f.write("  ranksep=1.5;\n")  # Space between rings
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

        # Write nodes grouped by depth using subgraphs with rank=same
        for depth in sorted(headers_by_depth.keys()):
            headers = headers_by_depth[depth]
            f.write(f"  subgraph depth_{depth} {{\n")
            f.write("    rank=same;\n")
            for header in headers:
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
                    f'    "{name}" [fillcolor={color}, style=filled, '
                    f'label="{name}\\n({count}x, d{depth})"];\n'
                )
            f.write("  }\n")

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

    fieldnames = [
        "header", "max_rss_kb", "wall_time_s", "success", "error", "command",
        "prmon_rss_kb", "prmon_wtime_s", "time_rss_kb", "time_cpu_s",
    ]

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
