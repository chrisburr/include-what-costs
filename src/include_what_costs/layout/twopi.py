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


def compute_positions(
    angles: dict[str, float],
    header_to_depth: dict[str, int],
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
        min_node_spacing: Minimum pixels between adjacent nodes on a ring.
        min_ring_gap: Minimum gap between consecutive rings.

    Returns:
        Dictionary mapping header to (x, y) position.
    """
    # Redistribute angles to even spacing while preserving order
    redistributed = redistribute_angles(angles, header_to_depth)

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
