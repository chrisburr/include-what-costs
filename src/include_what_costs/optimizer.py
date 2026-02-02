"""Graph layout using Graphviz twopi for radial positioning."""

from __future__ import annotations

import math
import time
from collections.abc import Mapping, Set


def optimize_placement(
    headers_by_depth: dict[int, list[str]],
    child_to_parents: dict[str, set[str]],
    edges: Mapping[str, Set[str]],
    max_depth: int | None = None,
) -> dict[str, float]:
    """Optimize node placement using Graphviz twopi radial layout."""
    import networkx as nx

    # Filter by max_depth if specified
    if max_depth is not None:
        headers_by_depth = {
            d: list(h) for d, h in headers_by_depth.items() if d <= max_depth
        }
    else:
        headers_by_depth = {d: list(h) for d, h in headers_by_depth.items()}

    total_nodes = sum(len(headers) for headers in headers_by_depth.values())
    print(f"Running twopi layout for {total_nodes} nodes...")
    start_time = time.perf_counter()

    # Build NetworkX DiGraph
    G = nx.DiGraph()
    all_nodes = set()
    for headers in headers_by_depth.values():
        for h in headers:
            G.add_node(h)
            all_nodes.add(h)
    G.add_node("__root__")

    # Add edges
    for parent, children in edges.items():
        if parent in all_nodes:
            for child in children:
                if child in all_nodes:
                    G.add_edge(parent, child)

    # Add root -> depth1 edges
    for child, parents in child_to_parents.items():
        if "__root__" in parents and child in all_nodes:
            G.add_edge("__root__", child)

    # Get twopi layout
    pos = nx.nx_agraph.graphviz_layout(G, prog="twopi", root="__root__")

    # Extract angles relative to root
    root_x, root_y = pos.get("__root__", (0, 0))
    angles: dict[str, float] = {"__root__": -math.pi / 2}

    for node, (x, y) in pos.items():
        if node == "__root__":
            continue
        dx, dy = x - root_x, y - root_y
        angles[node] = math.atan2(dy, dx) if (dx or dy) else 0.0

    # Reorder headers_by_depth by angle (backward compatibility)
    for depth in headers_by_depth:
        headers_by_depth[depth].sort(key=lambda h: angles.get(h, 0))

    elapsed = time.perf_counter() - start_time
    print(f"Layout complete: {total_nodes} nodes ({elapsed:.2f}s)")

    return angles
