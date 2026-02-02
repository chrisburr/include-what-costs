"""Spanning Tree + Sweep Refinement algorithm for node placement in visualizations.

This module implements a graph layout algorithm optimized for radial visualization
of include dependency graphs. The algorithm:

1. Extracts a spanning tree from the DAG by BFS
2. Assigns each subtree a contiguous angular wedge (crossing-free for tree edges)
3. Optimizes placement for non-tree edges using local swaps and Sugiyama-style sweeping
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Mapping, Set


def extract_spanning_tree(
    root: str,
    edges: Mapping[str, Set[str]],
    headers_by_depth: dict[int, list[str]],
) -> dict[str, str]:
    """Extract a spanning tree by BFS, assigning each node a single primary parent.

    Args:
        root: Root node identifier (e.g., "__root__").
        edges: Graph edges mapping parent -> children.
        headers_by_depth: Mapping from depth to list of headers at that depth.

    Returns:
        Mapping from each header to its primary parent in the spanning tree.
    """
    primary_parent: dict[str, str] = {}
    visited: set[str] = set()
    queue: deque[str] = deque([root])

    while queue:
        node = queue.popleft()
        if node in visited:
            continue
        visited.add(node)

        for child in edges.get(node, []):
            if child not in primary_parent:
                primary_parent[child] = node
            if child not in visited:
                queue.append(child)

    return primary_parent


def compute_subtree_sizes(
    node: str,
    edges: Mapping[str, Set[str]],
    primary_parent: dict[str, str],
    cache: dict[str, int] | None = None,
) -> int:
    """Count descendants in the spanning tree (including the node itself).

    Args:
        node: Node to compute size for.
        edges: Graph edges mapping parent -> children.
        primary_parent: Mapping from child to its primary parent in spanning tree.
        cache: Optional cache dict for memoization.

    Returns:
        Number of nodes in subtree rooted at this node.
    """
    if cache is None:
        cache = {}

    if node in cache:
        return cache[node]

    children = [c for c in edges.get(node, []) if primary_parent.get(c) == node]
    size = 1 + sum(
        compute_subtree_sizes(c, edges, primary_parent, cache) for c in children
    )
    cache[node] = size
    return size


def layout_tree(
    node: str,
    edges: Mapping[str, Set[str]],
    primary_parent: dict[str, str],
    start_angle: float,
    end_angle: float,
    header_angles: dict[str, float],
    size_cache: dict[str, int],
) -> None:
    """Recursively assign angles using angular wedges proportional to subtree size.

    This ensures children of the same parent are contiguous on their ring,
    producing zero crossings for tree edges.

    Args:
        node: Current node being laid out.
        edges: Graph edges mapping parent -> children.
        primary_parent: Mapping from child to its primary parent.
        start_angle: Start of angular wedge for this subtree.
        end_angle: End of angular wedge for this subtree.
        header_angles: Output dict mapping headers to angles (modified in place).
        size_cache: Cache of subtree sizes.
    """
    # Place this node at center of its wedge
    header_angles[node] = (start_angle + end_angle) / 2

    # Get children in the spanning tree (nodes whose primary parent is this node)
    children = [c for c in edges.get(node, []) if primary_parent.get(c) == node]
    if not children:
        return

    # Compute sizes for proportional wedge division
    sizes = [compute_subtree_sizes(c, edges, primary_parent, size_cache) for c in children]
    total = sum(sizes)

    if total == 0:
        return

    # Divide wedge proportionally by subtree size
    current_angle = start_angle
    for child, size in zip(children, sizes):
        wedge = (end_angle - start_angle) * size / total
        layout_tree(
            child,
            edges,
            primary_parent,
            current_angle,
            current_angle + wedge,
            header_angles,
            size_cache,
        )
        current_angle += wedge


def count_crossings(
    headers_by_depth: dict[int, list[str]],
    edges: Mapping[str, Set[str]],
    header_to_depth: dict[str, int],
) -> int:
    """Count edge crossings in the current layout.

    Two edges cross if their endpoints are interleaved on their respective rings.
    For edges (a, b) and (c, d) where a, c are on ring i and b, d are on ring j:
    They cross if order(a, c) != order(b, d) on their respective rings.

    Args:
        headers_by_depth: Current ordering of headers on each ring.
        edges: Graph edges.
        header_to_depth: Mapping from header to its depth.

    Returns:
        Total number of edge crossings.
    """
    # Build position maps for each ring
    position: dict[str, int] = {}
    for depth, headers in headers_by_depth.items():
        for i, h in enumerate(headers):
            position[h] = i

    # Collect all edges between adjacent rings
    edge_list: list[tuple[str, str, int, int]] = []  # (parent, child, parent_depth, child_depth)

    for parent, children in edges.items():
        parent_depth = header_to_depth.get(parent)
        if parent_depth is None:
            continue
        for child in children:
            child_depth = header_to_depth.get(child)
            if child_depth is None:
                continue
            if parent in position and child in position:
                edge_list.append((parent, child, parent_depth, child_depth))

    # Count crossings between edges on adjacent ring pairs
    crossings = 0
    for i, (p1, c1, pd1, cd1) in enumerate(edge_list):
        for p2, c2, pd2, cd2 in edge_list[i + 1 :]:
            # Only check edges that share ring pairs
            if not (pd1 == pd2 and cd1 == cd2):
                continue
            # Check for crossing: interleaved positions
            pos_p1 = position[p1]
            pos_p2 = position[p2]
            pos_c1 = position[c1]
            pos_c2 = position[c2]

            # Edges cross if order is interleaved
            # (p1 < p2 and c1 > c2) or (p1 > p2 and c1 < c2)
            if (pos_p1 < pos_p2) != (pos_c1 < pos_c2):
                if pos_p1 != pos_p2 and pos_c1 != pos_c2:  # Not same node
                    crossings += 1

    return crossings


def adjacent_swap_optimization(
    headers_by_depth: dict[int, list[str]],
    edges: Mapping[str, Set[str]],
    header_to_depth: dict[str, int],
    max_iterations: int = 50,
) -> bool:
    """Swap adjacent nodes if it reduces crossings.

    Args:
        headers_by_depth: Current ordering (modified in place).
        edges: Graph edges.
        header_to_depth: Mapping from header to depth.
        max_iterations: Maximum optimization iterations.

    Returns:
        True if any improvement was made.
    """
    any_improvement = False

    for _ in range(max_iterations):
        improved = False
        for depth, headers in headers_by_depth.items():
            n = len(headers)
            for i in range(n - 1):
                # Count crossings before swap
                crossings_before = count_crossings(headers_by_depth, edges, header_to_depth)

                # Try swapping adjacent nodes
                headers[i], headers[i + 1] = headers[i + 1], headers[i]

                # Count crossings after swap
                crossings_after = count_crossings(headers_by_depth, edges, header_to_depth)

                if crossings_after >= crossings_before:
                    # Revert swap - no improvement
                    headers[i], headers[i + 1] = headers[i + 1], headers[i]
                else:
                    improved = True
                    any_improvement = True

        if not improved:
            break

    return any_improvement


def compute_barycenter(
    header: str,
    neighbor_positions: list[int],
    ring_size: int,
) -> float:
    """Compute barycenter (average position) of a node's neighbors.

    Args:
        header: The header to compute barycenter for.
        neighbor_positions: Positions of neighbors on adjacent ring.
        ring_size: Size of the ring the neighbors are on.

    Returns:
        Average position (barycenter) as a float.
    """
    if not neighbor_positions:
        return 0.0
    return sum(neighbor_positions) / len(neighbor_positions)


def optimize_ring_order(
    ring_headers: list[str],
    fixed_ring_headers: list[str],
    edges: Mapping[str, Set[str]],
    child_to_parents: dict[str, set[str]],
    is_outward: bool,
) -> list[str]:
    """Reorder nodes on a ring using barycenter heuristic.

    Args:
        ring_headers: Headers on the ring to optimize (will be reordered).
        fixed_ring_headers: Headers on the adjacent fixed ring.
        edges: Parent -> children edges.
        child_to_parents: Child -> parents mapping.
        is_outward: True if fixed ring is parent (outward sweep), False if child (inward).

    Returns:
        Reordered list of headers.
    """
    # Build position map for fixed ring
    fixed_positions = {h: i for i, h in enumerate(fixed_ring_headers)}

    # Compute barycenter for each header on the ring being optimized
    barycenters: list[tuple[float, str]] = []
    for header in ring_headers:
        if is_outward:
            # Fixed ring is parents, get positions of parents
            neighbors = child_to_parents.get(header, set())
        else:
            # Fixed ring is children, get positions of children
            neighbors = edges.get(header, set())

        neighbor_positions = [
            fixed_positions[n] for n in neighbors if n in fixed_positions
        ]

        if neighbor_positions:
            bc = compute_barycenter(header, neighbor_positions, len(fixed_ring_headers))
        else:
            # No neighbors on fixed ring, keep relative position
            bc = ring_headers.index(header)

        barycenters.append((bc, header))

    # Sort by barycenter
    barycenters.sort(key=lambda x: x[0])
    return [h for _, h in barycenters]


def sugiyama_sweeps(
    headers_by_depth: dict[int, list[str]],
    edges: Mapping[str, Set[str]],
    child_to_parents: dict[str, set[str]],
    num_passes: int = 5,
) -> None:
    """Perform Sugiyama-style barycenter sweeps to reduce crossings.

    Alternates between outward sweeps (ring 1 -> N) and inward sweeps (ring N -> 1).

    Args:
        headers_by_depth: Headers organized by depth (modified in place).
        edges: Parent -> children edges.
        child_to_parents: Child -> parents mapping.
        num_passes: Number of full sweep passes.
    """
    depths = sorted(headers_by_depth.keys())
    if len(depths) < 2:
        return

    for _ in range(num_passes):
        # Outward sweep: optimize each ring based on previous ring (parents)
        for i, depth in enumerate(depths[1:], start=1):
            prev_depth = depths[i - 1]
            headers_by_depth[depth] = optimize_ring_order(
                headers_by_depth[depth],
                headers_by_depth[prev_depth],
                edges,
                child_to_parents,
                is_outward=True,
            )

        # Inward sweep: optimize each ring based on next ring (children)
        for i in range(len(depths) - 2, -1, -1):
            depth = depths[i]
            next_depth = depths[i + 1]
            headers_by_depth[depth] = optimize_ring_order(
                headers_by_depth[depth],
                headers_by_depth[next_depth],
                edges,
                child_to_parents,
                is_outward=False,
            )


def optimize_placement(
    headers_by_depth: dict[int, list[str]],
    child_to_parents: dict[str, set[str]],
    edges: Mapping[str, Set[str]],
    max_depth: int | None = None,
) -> dict[str, float]:
    """Optimize node placement using spanning tree + sweep refinement.

    This is the main entry point. The algorithm:
    1. Extracts a spanning tree via BFS
    2. Assigns contiguous angular wedges based on subtree size
    3. Refines placement with Sugiyama-style sweeps
    4. Further refines with adjacent swap optimization

    Args:
        headers_by_depth: Mapping from depth to list of headers at that depth.
        child_to_parents: Mapping from child header to set of parent headers.
        edges: Graph edges (parent -> children).
        max_depth: Only optimize rings up to this depth (None = all rings).

    Returns:
        Mapping from header to angle in radians.
    """
    # Filter to only include rings up to max_depth
    if max_depth is not None:
        headers_by_depth = {
            d: list(h) for d, h in headers_by_depth.items() if d <= max_depth
        }
    else:
        headers_by_depth = {d: list(h) for d, h in headers_by_depth.items()}

    total_nodes = sum(len(headers) for headers in headers_by_depth.values())
    print(f"Running spanning tree + sweep optimization for {total_nodes} nodes...")

    # Build header-to-depth mapping
    header_to_depth: dict[str, int] = {}
    for depth, headers in headers_by_depth.items():
        for h in headers:
            header_to_depth[h] = depth

    # Build edges including root -> depth1 edges
    all_edges: dict[str, set[str]] = {k: set(v) for k, v in edges.items()}

    # Add root edges from child_to_parents
    depth1_headers = headers_by_depth.get(1, [])
    for h in depth1_headers:
        parents = child_to_parents.get(h, set())
        if "__root__" in parents:
            if "__root__" not in all_edges:
                all_edges["__root__"] = set()
            all_edges["__root__"].add(h)

    # Phase 1: Extract spanning tree via BFS from root
    primary_parent = extract_spanning_tree("__root__", all_edges, headers_by_depth)

    # Phase 2: Compute subtree sizes and assign angular wedges
    header_angles: dict[str, float] = {}
    size_cache: dict[str, int] = {}

    # Start with root at top (-pi/2)
    header_angles["__root__"] = -math.pi / 2

    # Layout tree from root with full circle (0 to 2*pi)
    layout_tree(
        "__root__",
        all_edges,
        primary_parent,
        start_angle=0,
        end_angle=2 * math.pi,
        header_angles=header_angles,
        size_cache=size_cache,
    )

    # Convert angles to ring ordering
    for depth, headers in headers_by_depth.items():
        # Sort headers by their assigned angles
        headers.sort(key=lambda h: header_angles.get(h, 0))

    # Phase 3: Sugiyama-style sweeps to optimize for non-tree edges
    sugiyama_sweeps(headers_by_depth, all_edges, child_to_parents, num_passes=5)

    # Phase 4: Local swap refinement
    adjacent_swap_optimization(headers_by_depth, all_edges, header_to_depth, max_iterations=30)

    # Convert final ordering back to angles
    final_angles: dict[str, float] = {"__root__": -math.pi / 2}
    for depth, headers in headers_by_depth.items():
        n = len(headers)
        for i, h in enumerate(headers):
            final_angles[h] = 2 * math.pi * i / n - math.pi / 2

    crossings = count_crossings(headers_by_depth, all_edges, header_to_depth)
    print(f"Optimization complete: {total_nodes} nodes, {crossings} crossings")

    return final_angles
