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

    # Build node-to-depth mapping
    node_to_depth: dict[str, int] = {}
    all_nodes: set[str] = set()
    for depth, headers in headers_by_depth.items():
        for h in headers:
            node_to_depth[h] = depth
            all_nodes.add(h)

    # Count children per parent (for tie-breaking)
    children_count: dict[str, int] = {}
    for parent, children in edges.items():
        children_count[parent] = len([c for c in children if c in all_nodes])

    # Build reverse mapping: child -> list of parents in all_nodes
    all_parents: dict[str, list[str]] = {}
    for parent, children in edges.items():
        if parent not in all_nodes:
            continue
        for child in children:
            if child in all_nodes:
                if child not in all_parents:
                    all_parents[child] = []
                all_parents[child].append(parent)

    # Also include parents from child_to_parents (for root edges)
    for child, parents in child_to_parents.items():
        if child not in all_nodes:
            continue
        for p in parents:
            if p == "__root__" or p in all_nodes:
                if child not in all_parents:
                    all_parents[child] = []
                if p not in all_parents[child]:
                    all_parents[child].append(p)

    # Select BEST parent for each node:
    # - Prefer parent whose depth is closest to child_depth - 1
    # - Tie-break by fewer children (less angular crowding)
    best_parent: dict[str, str] = {}
    for child in all_nodes:
        child_depth = node_to_depth[child]
        candidates = all_parents.get(child, [])

        if not candidates:
            continue

        # Score: (depth_distance, children_count)
        # Lower is better
        def score(p: str) -> tuple[int, int]:
            if p == "__root__":
                p_depth = 0
            else:
                p_depth = node_to_depth.get(p, 0)
            depth_dist = abs((child_depth - 1) - p_depth)
            return (depth_dist, children_count.get(p, 0))

        best = min(candidates, key=score)
        best_parent[child] = best

    # Build layout graph with dummy nodes for edges that skip levels
    G = nx.DiGraph()
    G.add_node("__root__")
    for h in all_nodes:
        G.add_node(h)

    dummy_count = 0
    for child, parent in best_parent.items():
        child_depth = node_to_depth[child]

        if parent == "__root__":
            parent_depth = 0
        else:
            parent_depth = node_to_depth.get(parent, 0)

        gap = child_depth - parent_depth

        if gap <= 0:
            # Cross-edge or back-edge, skip for layout
            continue
        elif gap == 1:
            # Normal tree edge
            G.add_edge(parent, child)
        else:
            # Gap > 1: insert dummy nodes at intermediate depths
            prev_node = parent
            for d in range(parent_depth + 1, child_depth):
                dummy_name = f"__dummy_{dummy_count}"
                dummy_count += 1
                G.add_node(dummy_name)
                G.add_edge(prev_node, dummy_name)
                prev_node = dummy_name
            G.add_edge(prev_node, child)

    # Find nodes still unreachable from __root__
    reachable = nx.descendants(G, "__root__") | {"__root__"}
    unreachable = all_nodes - reachable

    # Add fallback edges for unreachable nodes (with dummy chains if needed)
    for node in unreachable:
        depth = node_to_depth[node]
        if depth == 1:
            G.add_edge("__root__", node)
        else:
            # Connect from first node on depth-1 ring via dummy chain if needed
            prev_ring = headers_by_depth.get(depth - 1, [])
            if prev_ring:
                G.add_edge(prev_ring[0], node)
            else:
                # No depth-1 ring, chain from root with dummies
                prev_node = "__root__"
                for d in range(1, depth):
                    dummy_name = f"__dummy_{dummy_count}"
                    dummy_count += 1
                    G.add_node(dummy_name)
                    G.add_edge(prev_node, dummy_name)
                    prev_node = dummy_name
                G.add_edge(prev_node, node)

    # Get twopi layout
    pos = nx.nx_agraph.graphviz_layout(G, prog="twopi", root="__root__")

    # Extract angles relative to root (only for real nodes, not dummies)
    root_x, root_y = pos.get("__root__", (0, 0))
    angles: dict[str, float] = {"__root__": -math.pi / 2}

    for node, (x, y) in pos.items():
        if node == "__root__" or node.startswith("__dummy_"):
            continue
        dx, dy = x - root_x, y - root_y
        angles[node] = math.atan2(dy, dx) if (dx or dy) else 0.0

    # Reorder headers_by_depth by angle (backward compatibility)
    for depth in headers_by_depth:
        headers_by_depth[depth].sort(key=lambda h: angles.get(h, 0))

    elapsed = time.perf_counter() - start_time
    print(f"Layout complete: {total_nodes} nodes, {dummy_count} dummies ({elapsed:.2f}s)")

    return angles
