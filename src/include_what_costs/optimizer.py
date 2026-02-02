"""Circular Median + All-Neighbors algorithm for node placement in visualizations.

This module implements a graph layout algorithm optimized for radial visualization
of include dependency graphs. The algorithm:

1. Places each node at the circular median of ALL its parents' angles
2. Iteratively repositions nodes toward circular median of ALL neighbors (parents + children)
3. Refines placement with local swap optimization
"""

from __future__ import annotations

import math
import time
from collections.abc import Mapping, Set


def circular_distance(a: float, b: float) -> float:
    """Compute shortest angular distance between two angles (in radians)."""
    d = abs(a - b) % (2 * math.pi)
    return min(d, 2 * math.pi - d)


def circular_mean(angles: list[float], weights: list[float] | None = None) -> float:
    """Compute circular mean using vector averaging."""
    if not angles:
        return 0.0
    if weights is None:
        weights = [1.0] * len(angles)
    total_weight = sum(weights)
    if total_weight == 0:
        return 0.0
    avg_x = sum(w * math.cos(a) for a, w in zip(angles, weights)) / total_weight
    avg_y = sum(w * math.sin(a) for a, w in zip(angles, weights)) / total_weight
    return math.atan2(avg_y, avg_x)


def circular_median(angles: list[float], weights: list[float] | None = None) -> float:
    """Find angle that minimizes weighted circular distance to all input angles."""
    if not angles:
        return 0.0
    if weights is None:
        weights = [1.0] * len(angles)
    # Test at each candidate angle (only need to test at input angles)
    best_angle = angles[0]
    best_cost = float("inf")
    for candidate in angles:
        cost = sum(w * circular_distance(candidate, a) for a, w in zip(angles, weights))
        if cost < best_cost:
            best_cost = cost
            best_angle = candidate
    return best_angle


def spread_with_minimum_gap(
    placements: list[tuple[float, str]],
    min_gap: float,
) -> list[tuple[float, str]]:
    """Adjust angles to enforce minimum separation while preserving proximity.

    Uses the largest gap in target angles to find the circular 'cut point',
    then resolves overlaps linearly.
    """
    if len(placements) <= 1:
        return placements

    n = len(placements)
    TWO_PI = 2 * math.pi

    # Step 1: Find the largest angular gap to determine cut point
    # This avoids splitting clusters that straddle 0/2π
    raw_angles = sorted([a % TWO_PI for a, _ in placements])

    max_gap = 0.0
    cut_after_idx = -1
    for i in range(n):
        next_i = (i + 1) % n
        gap = (raw_angles[next_i] - raw_angles[i]) % TWO_PI
        if gap > max_gap:
            max_gap = gap
            cut_after_idx = i

    # The cut point is in the middle of the largest gap
    cut_angle = (raw_angles[cut_after_idx] + max_gap / 2) % TWO_PI

    # Step 2: Sort by angle relative to cut point (linearizes the circle)
    def circular_sort_key(item: tuple[float, str]) -> float:
        return (item[0] - cut_angle) % TWO_PI

    placements = sorted(placements, key=circular_sort_key)

    # Step 3: Resolve overlaps - push apart nodes that are too close
    # Work in the linearized space [cut_angle, cut_angle + 2π)
    adjusted = [[circular_sort_key(p), p[1]] for p in placements]

    # Forward pass: ensure each node is at least min_gap after previous
    for i in range(1, n):
        if adjusted[i][0] - adjusted[i - 1][0] < min_gap:
            adjusted[i][0] = adjusted[i - 1][0] + min_gap

    # Check if we've wrapped past 2π (overflowed the circle)
    total_span = adjusted[-1][0] - adjusted[0][0]
    available = TWO_PI - min_gap  # leave min_gap for the cut gap too

    if total_span > available:
        # Too many nodes / too large min_gap: spread evenly but
        # centered on the cluster's center of mass
        even_gap = TWO_PI / n
        center_angle = circular_mean([a for a, _ in placements])
        center = (center_angle - cut_angle) % TWO_PI
        start = center - even_gap * (n - 1) / 2
        adjusted = [[start + i * even_gap, h] for i, (_, h) in enumerate(adjusted)]

    # Step 4: Convert back to absolute angles
    result = [((a + cut_angle) % TWO_PI, h) for a, h in adjusted]
    return result


def initial_placement(
    headers_by_depth: dict[int, list[str]],
    child_to_parents: dict[str, set[str]],
    header_angles: dict[str, float],
) -> None:
    """Place each node at circular median of its parents' angles."""
    header_angles["__root__"] = -math.pi / 2

    for depth in sorted(headers_by_depth.keys()):
        headers = headers_by_depth[depth]
        placements: list[tuple[float, str]] = []

        for header in headers:
            parents = child_to_parents.get(header, set())
            parent_angles = [header_angles[p] for p in parents if p in header_angles]

            if parent_angles:
                angle = circular_median(parent_angles)
            else:
                angle = 0.0  # fallback
            placements.append((angle, header))

        # Spread with minimum gap while preserving angular proximity
        n = len(placements)
        min_gap = (2 * math.pi / n) * 0.5  # half of uniform spacing as minimum
        placements = spread_with_minimum_gap(placements, min_gap)

        for angle, header in placements:
            header_angles[header] = angle

        # Update headers_by_depth to reflect new order
        headers_by_depth[depth] = [h for _, h in placements]


def reposition_sweep(
    headers_by_depth: dict[int, list[str]],
    edges: Mapping[str, Set[str]],
    child_to_parents: dict[str, set[str]],
    header_angles: dict[str, float],
) -> bool:
    """One sweep pass: reposition each node toward its neighbors."""
    moved = False

    for depth in sorted(headers_by_depth.keys()):
        headers = headers_by_depth[depth]
        new_positions: list[tuple[float, str]] = []

        for header in headers:
            # Collect ALL neighbors (parents + children)
            neighbors = set(child_to_parents.get(header, set()))
            neighbors.update(edges.get(header, set()))

            neighbor_angles = [header_angles[n] for n in neighbors if n in header_angles]

            if neighbor_angles:
                target = circular_median(neighbor_angles)
            else:
                target = header_angles[header]

            new_positions.append((target, header))

        # Spread with minimum gap while preserving angular proximity
        n = len(new_positions)
        min_gap = (2 * math.pi / n) * 0.5
        new_positions = spread_with_minimum_gap(new_positions, min_gap)
        new_order = [h for _, h in new_positions]

        if new_order != headers:
            moved = True
            headers_by_depth[depth] = new_order
            # Update angles from spread positions
            for angle, h in new_positions:
                header_angles[h] = angle

    return moved


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


def optimize_placement(
    headers_by_depth: dict[int, list[str]],
    child_to_parents: dict[str, set[str]],
    edges: Mapping[str, Set[str]],
    max_depth: int | None = None,
) -> dict[str, float]:
    """Optimize node placement using circular median + all-neighbors repositioning.

    This is the main entry point. The algorithm:
    1. Places each node at circular median of ALL its parents' angles
    2. Iteratively repositions nodes toward circular median of ALL neighbors
    3. Refines with adjacent swap optimization

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
    print(f"Running circular median + all-neighbors optimization for {total_nodes} nodes...")
    start_time = time.perf_counter()

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

    # Phase 1: Initial placement - circular median of parents
    header_angles: dict[str, float] = {}
    initial_placement(headers_by_depth, child_to_parents, header_angles)

    # Phase 2: Iterative all-neighbors repositioning (10 passes)
    for _ in range(10):
        if not reposition_sweep(headers_by_depth, all_edges, child_to_parents, header_angles):
            break

    # Phase 3: Adjacent swap refinement
    adjacent_swap_optimization(headers_by_depth, all_edges, header_to_depth, max_iterations=30)

    # Final angles: use swap-optimized order with uniform spacing
    # (swaps optimize for crossings; respect that order)
    final_angles: dict[str, float] = {"__root__": -math.pi / 2}
    for depth, headers in headers_by_depth.items():
        n = len(headers)
        for i, h in enumerate(headers):
            final_angles[h] = 2 * math.pi * i / n - math.pi / 2

    crossings = count_crossings(headers_by_depth, all_edges, header_to_depth)
    elapsed = time.perf_counter() - start_time
    print(f"Optimization complete: {total_nodes} nodes, {crossings} crossings ({elapsed:.2f}s)")

    return final_angles
