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


def compute_positions(
    angles: dict[str, float],
    header_to_depth: dict[str, int],
    base_radius: float = 100,
    ring_spacing: float = 100,
) -> dict[str, tuple[float, float]]:
    """Compute final (x, y) positions with strict concentric radii.

    Args:
        angles: Angle for each header in radians.
        header_to_depth: Mapping from header to its depth.
        base_radius: Radius of the first ring (depth 1).
        ring_spacing: Distance between consecutive rings.

    Returns:
        Dictionary mapping header to (x, y) position.
    """
    positions: dict[str, tuple[float, float]] = {}

    for header, angle in angles.items():
        depth = header_to_depth.get(header, 1)
        radius = base_radius + (depth - 1) * ring_spacing
        x = radius * math.cos(angle)
        y = radius * math.sin(angle)
        positions[header] = (x, y)

    return positions
