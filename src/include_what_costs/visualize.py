"""Generate visualization outputs."""

import csv
import json
import math
from collections import defaultdict
from pathlib import Path

from .graph import IncludeGraph


def _optimize_placement(
    headers_by_depth: dict[int, list[str]],
    child_to_parents: dict[str, set[str]],
    edges: dict[str, set[str]],
    max_depth: int | None = None,
) -> dict[str, float]:
    """Optimize node placement using spanning tree + sweep refinement.

    Args:
        headers_by_depth: Mapping from depth to list of headers.
        child_to_parents: Mapping from child to parent headers.
        edges: Graph edges.
        max_depth: Only optimize rings up to this depth (None = all).

    Returns:
        Mapping from header to angle in radians.
    """
    from .optimizer import optimize_placement

    return optimize_placement(
        headers_by_depth, child_to_parents, edges, max_depth=max_depth
    )


def generate_html(
    graph: IncludeGraph,
    output_file: Path,
    prefix: str | None = None,
    direct_includes: list[str] | None = None,
) -> None:
    """Generate interactive HTML visualization using pyvis.

    Nodes are positioned in concentric circles based on include depth.

    Args:
        graph: The include graph to visualize.
        output_file: Path to write the HTML file.
        prefix: Only include headers under this path prefix.
        direct_includes: List of headers directly included by root (from parsing the file).
    """
    from pyvis.network import Network

    # Filter headers by prefix
    if prefix:
        prefix_resolved = str(Path(prefix).resolve())
        relevant = {h for h in graph.all_headers if h.startswith(prefix_resolved)}
    else:
        relevant = graph.all_headers

    # Build set of direct include basenames for quick lookup
    root_children = direct_includes if direct_includes else graph.direct_includes
    direct_include_names = {Path(inc).name for inc in root_children}
    direct_include_suffixes = set(root_children)  # e.g., "Functors/TES.h"

    def match_direct_include(header: str) -> bool:
        """Check if header is directly included by root."""
        name = Path(header).name
        if name in direct_include_names:
            # Also check suffix matches to avoid false positives on common names
            for suffix in direct_include_suffixes:
                if header.endswith(suffix):
                    return True
        return False

    # Compute depths via BFS from direct includes (gcc -H order is unreliable)
    # First, resolve direct includes to full paths in relevant
    depth1_headers: set[str] = set()
    for header in relevant:
        if match_direct_include(header):
            depth1_headers.add(header)

    # BFS to compute true minimum depths
    from collections import deque

    header_depths: dict[str, int] = {}
    queue: deque[tuple[str, int]] = deque()
    for h in depth1_headers:
        header_depths[h] = 1
        queue.append((h, 1))

    while queue:
        node, depth = queue.popleft()
        for child in graph.edges.get(node, set()):
            if child in relevant and child not in header_depths:
                header_depths[child] = depth + 1
                queue.append((child, depth + 1))

    # Group headers by depth for concentric circle layout
    headers_by_depth: dict[int, list[str]] = defaultdict(list)
    header_display_depth: dict[str, int] = {}  # Track actual display depth for labels
    for header in relevant:
        depth = header_depths.get(header, 1)  # Default to 1 if unreachable
        headers_by_depth[depth].append(header)
        header_display_depth[header] = depth

    max_depth = max(headers_by_depth.keys()) if headers_by_depth else 1

    # Build reverse edge map (child -> parents that include it)
    child_to_parents: dict[str, set[str]] = defaultdict(set)
    for parent, children in graph.edges.items():
        if parent in relevant:
            for child in children:
                if child in relevant:
                    child_to_parents[child].add(parent)

    # Also add edges from root to direct includes
    if graph.root:
        for inc in root_children:
            for h in relevant:
                if h.endswith(inc) or Path(h).name == Path(inc).name:
                    child_to_parents[h].add("__root__")
                    break

    # Optimize all rings with spanning tree + sweep algorithm
    header_angles = _optimize_placement(
        headers_by_depth, child_to_parents, graph.edges, max_depth=None
    )

    # Create network with physics disabled (we set fixed positions)
    net = Network(
        height="900px",
        width="100%",
        bgcolor="#ffffff",
        directed=True,
    )
    net.toggle_physics(False)

    # Calculate positions for concentric circles
    min_node_spacing = 80  # minimum pixels between adjacent nodes on a ring
    min_ring_gap = 100  # minimum gap between rings
    header_to_name: dict[str, str] = {}  # full path -> display name

    # Pre-calculate radii for each depth to ensure nodes aren't too dense
    # Radius must be large enough that arc length between nodes >= min_node_spacing
    # Arc length = 2 * pi * radius / n_nodes >= min_node_spacing
    # Therefore: radius >= n_nodes * min_node_spacing / (2 * pi)
    ring_radii: dict[int, float] = {}
    current_radius = 0.0
    for depth in sorted(headers_by_depth.keys()):
        n_nodes = len(headers_by_depth[depth])
        min_radius_for_spacing = n_nodes * min_node_spacing / (2 * math.pi)
        # Radius must be at least min_ring_gap more than previous ring
        ring_radii[depth] = max(current_radius + min_ring_gap, min_radius_for_spacing)
        current_radius = ring_radii[depth]

    # Add root node at center
    root_name = None
    if graph.root:
        root_name = Path(graph.root).name
        net.add_node(
            root_name,
            label=root_name,
            title=f"{graph.root}\n(root)",
            x=0,
            y=0,
            fixed=True,
            color="#87CEEB",  # light blue
            shape="box",
            font={"size": 12},
        )

    # Add nodes in concentric circles by depth
    for depth in sorted(headers_by_depth.keys()):
        headers = headers_by_depth[depth]
        n_nodes = len(headers)
        radius = ring_radii[depth]

        for i, header in enumerate(headers):
            # Distribute nodes evenly around the circle
            angle = 2 * math.pi * i / n_nodes - math.pi / 2  # Start from top
            x = radius * math.cos(angle)
            y = radius * math.sin(angle)

            name = Path(header).name
            header_to_name[header] = name
            count = graph.include_counts.get(header, 0)

            # Color based on include count
            if count > 10:
                color = "#ff6b6b"  # red
            elif count > 5:
                color = "#ffa94d"  # orange
            elif count > 2:
                color = "#ffd43b"  # yellow
            else:
                color = "#e9ecef"  # light gray

            net.add_node(
                name,
                label=f"{name}\n({count}x, d{depth})",
                title=f"{header}\nIncluded {count}x\nDepth: {depth}",
                x=x,
                y=y,
                fixed=True,
                color=color,
                shape="box",
                font={"size": 10},
            )

    # Add edges from root to direct includes
    if root_name and root_children:
        for child in root_children:
            child_name = Path(child).name
            for full_path in relevant:
                if full_path.endswith(child) or Path(full_path).name == child_name:
                    target_name = header_to_name.get(full_path, Path(full_path).name)
                    try:
                        net.add_edge(root_name, target_name, color="#888888")
                    except Exception:
                        pass  # Node might not exist if filtered
                    break

    # Add edges between headers
    for parent, children in graph.edges.items():
        if parent not in relevant:
            continue
        parent_name = header_to_name.get(parent)
        if not parent_name:
            continue
        for child in children:
            if child not in relevant:
                continue
            child_name = header_to_name.get(child)
            if child_name:
                try:
                    net.add_edge(parent_name, child_name, color="#cccccc")
                except Exception:
                    pass  # Skip if edge already exists or nodes missing

    # Configure interaction options with highlighting
    # physics.enabled: false is critical - without it, vis.js force simulation moves nodes
    net.set_options("""
    {
        "physics": {"enabled": false},
        "interaction": {
            "navigationButtons": true,
            "zoomView": true,
            "dragView": true,
            "hover": true,
            "selectConnectedEdges": true,
            "tooltipDelay": 100
        },
        "edges": {
            "arrows": {"to": {"enabled": true, "scaleFactor": 0.5}},
            "smooth": {"type": "continuous"},
            "selectionWidth": 2,
            "hoverWidth": 2
        },
        "nodes": {
            "borderWidth": 1,
            "borderWidthSelected": 3
        }
    }
    """)

    net.save_graph(str(output_file))

    # Inject custom JavaScript for better selection highlighting
    _inject_highlight_script(output_file)


def _inject_highlight_script(output_file: Path) -> None:
    """Inject custom JavaScript for better selection highlighting.

    When a node is selected, this highlights:
    - Incoming edges (headers that include this one) in blue
    - Outgoing edges (headers this one includes) in green
    """
    with open(output_file, "r") as f:
        html = f.read()

    # JavaScript to add after the network is created
    custom_script = """
    <script type="text/javascript">
    // Wait for network to be ready
    document.addEventListener('DOMContentLoaded', function() {
        // Give vis.js time to initialize
        setTimeout(function() {
            if (typeof network === 'undefined') return;

            // Create info panel
            var infoPanel = document.createElement('div');
            infoPanel.id = 'infoPanel';
            infoPanel.style.cssText = 'position:fixed;top:10px;right:10px;padding:15px;background:white;border:1px solid #ccc;border-radius:5px;font-family:monospace;font-size:12px;max-width:400px;display:none;z-index:1000;box-shadow:0 2px 10px rgba(0,0,0,0.1);';
            document.body.appendChild(infoPanel);

            // Create legend
            var legend = document.createElement('div');
            legend.innerHTML = '<div style="position:fixed;bottom:10px;right:10px;padding:10px;background:white;border:1px solid #ccc;border-radius:5px;font-family:sans-serif;font-size:11px;">' +
                '<div><span style="display:inline-block;width:20px;height:3px;background:#2ecc71;margin-right:5px;vertical-align:middle;"></span> includes (outgoing)</div>' +
                '<div><span style="display:inline-block;width:20px;height:3px;background:#3498db;margin-right:5px;vertical-align:middle;"></span> included by (incoming)</div>' +
                '</div>';
            document.body.appendChild(legend);

            var originalColors = {};

            network.on('selectNode', function(params) {
                var selectedNode = params.nodes[0];
                var connectedEdges = network.getConnectedEdges(selectedNode);
                var incoming = [];
                var outgoing = [];

                // Store original colors and categorize edges
                connectedEdges.forEach(function(edgeId) {
                    var edge = edges.get(edgeId);
                    if (!originalColors[edgeId]) {
                        originalColors[edgeId] = edge.color;
                    }

                    if (edge.to === selectedNode) {
                        incoming.push({edge: edgeId, from: edge.from});
                        edges.update({id: edgeId, color: {color: '#3498db', highlight: '#3498db'}, width: 2});
                    } else {
                        outgoing.push({edge: edgeId, to: edge.to});
                        edges.update({id: edgeId, color: {color: '#2ecc71', highlight: '#2ecc71'}, width: 2});
                    }
                });

                // Update info panel
                infoPanel.innerHTML = '<strong>' + selectedNode + '</strong><br><br>' +
                    '<span style="color:#2ecc71">▶ Includes ' + outgoing.length + ' headers:</span><br>' +
                    outgoing.slice(0, 10).map(function(e) { return '&nbsp;&nbsp;' + e.to; }).join('<br>') +
                    (outgoing.length > 10 ? '<br>&nbsp;&nbsp;... and ' + (outgoing.length - 10) + ' more' : '') +
                    '<br><br>' +
                    '<span style="color:#3498db">◀ Included by ' + incoming.length + ' headers:</span><br>' +
                    incoming.slice(0, 10).map(function(e) { return '&nbsp;&nbsp;' + e.from; }).join('<br>') +
                    (incoming.length > 10 ? '<br>&nbsp;&nbsp;... and ' + (incoming.length - 10) + ' more' : '');
                infoPanel.style.display = 'block';
            });

            network.on('deselectNode', function(params) {
                // Restore original edge colors
                Object.keys(originalColors).forEach(function(edgeId) {
                    edges.update({id: edgeId, color: originalColors[edgeId], width: 1});
                });
                originalColors = {};
                infoPanel.style.display = 'none';
            });

        }, 500);
    });
    </script>
    """

    # Insert before closing body tag
    html = html.replace("</body>", custom_script + "</body>")

    with open(output_file, "w") as f:
        f.write(html)


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
