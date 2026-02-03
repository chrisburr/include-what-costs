"""Twopi layout graph construction and angle extraction."""

import math

import networkx as nx

from .classify import EdgeType

# Synthetic root node name
ROOT_NODE = "__root__"


def build_layout_graph(
    edges: dict[str, set[str]],
    header_to_depth: dict[str, int],
    classified_edges: dict[EdgeType, list[tuple[str, str]]],
) -> nx.DiGraph:
    """Build tree-only graph for twopi layout.

    Contains only:
    - __root__ -> all depth-1 nodes
    - Tree edges (parent_depth + 1 == child_depth)

    For multi-parent nodes (diamonds), pick parent with fewer children.

    Args:
        edges: Full adjacency list (parent -> children).
        header_to_depth: Mapping from header to its depth.
        classified_edges: Edges classified by type.

    Returns:
        NetworkX DiGraph containing only tree structure.
    """
    G = nx.DiGraph()

    # Add root node
    G.add_node(ROOT_NODE)

    # Add all nodes first
    for header in header_to_depth:
        G.add_node(header)

    # Add edges from root to all depth-1 nodes
    for header, depth in header_to_depth.items():
        if depth == 1:
            G.add_edge(ROOT_NODE, header)

    # Build parent candidates for each node (from tree edges only)
    # For nodes with multiple potential tree parents, pick the one with fewer children
    child_to_parents: dict[str, list[str]] = {}
    for parent, child in classified_edges[EdgeType.TREE]:
        if child not in child_to_parents:
            child_to_parents[child] = []
        child_to_parents[child].append(parent)

    # Count children for each parent to help break ties
    parent_child_count: dict[str, int] = {}
    for parent in edges:
        parent_child_count[parent] = len(edges.get(parent, set()))

    # Add exactly one tree edge per non-depth-1 node
    for child, parents in child_to_parents.items():
        if header_to_depth.get(child, 0) == 1:
            # Depth-1 nodes are connected to root, not other nodes
            continue

        if len(parents) == 1:
            G.add_edge(parents[0], child)
        else:
            # Pick parent with fewer children (to balance the tree)
            best_parent = min(parents, key=lambda p: parent_child_count.get(p, 0))
            G.add_edge(best_parent, child)

    return G


def extract_angles(layout_graph: nx.DiGraph) -> dict[str, float]:
    """Run twopi layout and extract angles.

    Uses networkx graphviz_layout with twopi program.

    Args:
        layout_graph: Tree-only graph with __root__ node.

    Returns:
        Angles in [-pi, pi] range for each node (excluding __root__).
    """
    # Use twopi layout from graphviz
    pos = nx.nx_agraph.graphviz_layout(layout_graph, prog="twopi", root=ROOT_NODE)

    # Extract angles from positions
    angles: dict[str, float] = {}
    root_x, root_y = pos[ROOT_NODE]

    for node, (x, y) in pos.items():
        if node == ROOT_NODE:
            continue
        # Compute angle from root
        dx = x - root_x
        dy = y - root_y
        angles[node] = math.atan2(dy, dx)

    return angles


def redistribute_angles(
    angles: dict[str, float],
    header_to_depth: dict[str, int],
) -> dict[str, float]:
    """Redistribute angles evenly while preserving relative order from twopi.

    For each depth level, nodes are spread evenly around the circle but maintain
    the same relative angular ordering that twopi computed. This reduces overlap
    while keeping related nodes near each other.

    Args:
        angles: Original angles from twopi layout.
        header_to_depth: Mapping from header to its depth.

    Returns:
        New angles with even spacing per depth level.
    """
    # Group nodes by depth
    nodes_by_depth: dict[int, list[str]] = {}
    for header, depth in header_to_depth.items():
        if header not in angles:
            continue
        if depth not in nodes_by_depth:
            nodes_by_depth[depth] = []
        nodes_by_depth[depth].append(header)

    new_angles: dict[str, float] = {}

    for depth, nodes in nodes_by_depth.items():
        if len(nodes) == 1:
            # Single node keeps its angle
            new_angles[nodes[0]] = angles[nodes[0]]
            continue

        # Sort nodes by their original angle to preserve relative order
        nodes_sorted = sorted(nodes, key=lambda h: angles[h])

        # Redistribute evenly around the circle, starting from top (-pi/2)
        n = len(nodes_sorted)
        for i, header in enumerate(nodes_sorted):
            new_angles[header] = 2 * math.pi * i / n - math.pi / 2

    return new_angles


def _normalize_angle(angle: float) -> float:
    """Normalize angle to [-pi, pi] range."""
    while angle > math.pi:
        angle -= 2 * math.pi
    while angle < -math.pi:
        angle += 2 * math.pi
    return angle


def _angular_diff(a: float, b: float) -> float:
    """Compute signed angular difference (a - b) in [-pi, pi]."""
    return _normalize_angle(a - b)


def align_rings_to_parents(
    angles: dict[str, float],
    header_to_depth: dict[str, int],
    edges: dict[str, set[str]],
) -> dict[str, float]:
    """Rotate each ring to align children with their parents.

    For each depth level >= 2, find the optimal rotation that minimizes
    angular distance between nodes and their parents. This makes edges
    more radial (straight from center).

    Args:
        angles: Current angles for each header.
        header_to_depth: Mapping from header to its depth.
        edges: Adjacency list (parent -> children).

    Returns:
        New angles with rings rotated to align with parents.
    """
    # Build child -> parents mapping
    child_to_parents: dict[str, list[str]] = {}
    for parent, children in edges.items():
        for child in children:
            if child not in child_to_parents:
                child_to_parents[child] = []
            child_to_parents[child].append(parent)

    # Group nodes by depth
    nodes_by_depth: dict[int, list[str]] = {}
    for header, depth in header_to_depth.items():
        if header not in angles:
            continue
        if depth not in nodes_by_depth:
            nodes_by_depth[depth] = []
        nodes_by_depth[depth].append(header)

    aligned = dict(angles)  # Start with current angles

    # Process each depth from 2 onwards
    for depth in sorted(nodes_by_depth.keys()):
        if depth <= 1:
            continue

        nodes = nodes_by_depth[depth]
        if not nodes:
            continue

        # Compute optimal rotation for this ring
        # For each node, find its parent's angle and compute the difference
        angle_diffs: list[float] = []
        for node in nodes:
            parents = child_to_parents.get(node, [])
            # Find parents at depth-1
            parent_angles = [
                aligned[p]
                for p in parents
                if p in aligned and header_to_depth.get(p) == depth - 1
            ]
            if parent_angles:
                # Use mean parent angle as target
                # For circular mean, use vector addition
                target_x = sum(math.cos(a) for a in parent_angles) / len(parent_angles)
                target_y = sum(math.sin(a) for a in parent_angles) / len(parent_angles)
                target_angle = math.atan2(target_y, target_x)
                diff = _angular_diff(target_angle, aligned[node])
                angle_diffs.append(diff)

        if not angle_diffs:
            continue

        # Compute mean rotation using circular mean
        mean_x = sum(math.cos(d) for d in angle_diffs) / len(angle_diffs)
        mean_y = sum(math.sin(d) for d in angle_diffs) / len(angle_diffs)
        rotation = math.atan2(mean_y, mean_x)

        # Apply rotation to all nodes at this depth
        for node in nodes:
            aligned[node] = _normalize_angle(aligned[node] + rotation)

    return aligned


def compute_positions(
    angles: dict[str, float],
    header_to_depth: dict[str, int],
    edges: dict[str, set[str]] | None = None,
    min_node_spacing: float = 80,
    min_ring_gap: float = 100,
) -> dict[str, tuple[float, float]]:
    """Compute final (x, y) positions with adaptive ring radii.

    Ring radii are computed to ensure adequate spacing between nodes:
    - Each ring is large enough that arc length between nodes >= min_node_spacing
    - Each ring is at least min_ring_gap further out than the previous ring

    Args:
        angles: Angle for each header in radians.
        header_to_depth: Mapping from header to its depth.
        edges: Optional adjacency list for aligning rings to parents.
        min_node_spacing: Minimum pixels between adjacent nodes on a ring.
        min_ring_gap: Minimum gap between consecutive rings.

    Returns:
        Dictionary mapping header to (x, y) position.
    """
    # Redistribute angles to even spacing while preserving order
    redistributed = redistribute_angles(angles, header_to_depth)

    # Align rings to parent positions if edges provided
    if edges:
        redistributed = align_rings_to_parents(redistributed, header_to_depth, edges)

    # Group nodes by depth to count nodes per ring
    nodes_by_depth: dict[int, list[str]] = {}
    for header, depth in header_to_depth.items():
        if header not in redistributed:
            continue
        if depth not in nodes_by_depth:
            nodes_by_depth[depth] = []
        nodes_by_depth[depth].append(header)

    # Compute adaptive radii for each depth
    # Arc length = 2π × radius / n_nodes >= min_node_spacing
    # Therefore: radius >= n_nodes × min_node_spacing / (2π)
    ring_radii: dict[int, float] = {}
    current_radius = 0.0
    for depth in sorted(nodes_by_depth.keys()):
        n_nodes = len(nodes_by_depth[depth])
        min_radius_for_spacing = n_nodes * min_node_spacing / (2 * math.pi)
        ring_radii[depth] = max(current_radius + min_ring_gap, min_radius_for_spacing)
        current_radius = ring_radii[depth]

    positions: dict[str, tuple[float, float]] = {}

    for header, angle in redistributed.items():
        depth = header_to_depth.get(header, 1)
        radius = ring_radii.get(depth, min_ring_gap)
        x = radius * math.cos(angle)
        y = radius * math.sin(angle)
        positions[header] = (x, y)

    return positions
