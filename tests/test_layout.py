"""Tests for twopi.py layout module."""

import math

import pytest

from include_what_costs.layout.classify import EdgeType, classify_edges
from include_what_costs.layout.depth import compute_depths
from include_what_costs.layout.twopi import (
    ROOT_NODE,
    build_layout_graph,
    compute_positions,
    extract_angles,
)


class TestBuildLayoutGraph:
    """Tests for build_layout_graph function."""

    def test_layout_graph_is_tree(self, complex_graph):
        """Layout graph should be a tree (|edges| == |nodes| - 1)."""
        edges, direct_includes = complex_graph
        _, header_to_depth = compute_depths(edges, direct_includes)
        classified = classify_edges(edges, header_to_depth)
        layout_graph = build_layout_graph(edges, header_to_depth, classified)

        num_nodes = layout_graph.number_of_nodes()
        num_edges = layout_graph.number_of_edges()

        # Tree property: |E| = |V| - 1
        assert num_edges == num_nodes - 1

    def test_cross_edges_excluded(self, back_edge_graph):
        """Back edges should not be in layout graph."""
        edges, direct_includes = back_edge_graph
        _, header_to_depth = compute_depths(edges, direct_includes)
        classified = classify_edges(edges, header_to_depth)
        layout_graph = build_layout_graph(edges, header_to_depth, classified)

        # C->A is a back edge and should not be in layout graph
        assert not layout_graph.has_edge("C", "A")

    def test_all_nodes_reachable_from_root(self, complex_graph):
        """All nodes should be reachable from __root__."""
        import networkx as nx

        edges, direct_includes = complex_graph
        _, header_to_depth = compute_depths(edges, direct_includes)
        classified = classify_edges(edges, header_to_depth)
        layout_graph = build_layout_graph(edges, header_to_depth, classified)

        # Check all non-root nodes are reachable from root
        descendants = nx.descendants(layout_graph, ROOT_NODE)
        non_root_nodes = set(layout_graph.nodes()) - {ROOT_NODE}

        assert descendants == non_root_nodes

    def test_multi_parent_nodes_have_one_parent(self, diamond_graph):
        """Nodes with multiple potential parents get exactly one in layout graph."""
        edges, direct_includes = diamond_graph
        _, header_to_depth = compute_depths(edges, direct_includes)
        classified = classify_edges(edges, header_to_depth)
        layout_graph = build_layout_graph(edges, header_to_depth, classified)

        # D has two potential parents (B and C), should have exactly one
        d_predecessors = list(layout_graph.predecessors("D"))
        assert len(d_predecessors) == 1
        assert d_predecessors[0] in ("B", "C")

    def test_root_connected_to_depth1(self, multiple_roots):
        """Root should be connected to all depth-1 nodes."""
        edges, direct_includes = multiple_roots
        _, header_to_depth = compute_depths(edges, direct_includes)
        classified = classify_edges(edges, header_to_depth)
        layout_graph = build_layout_graph(edges, header_to_depth, classified)

        # Both A and B should be children of __root__
        root_children = list(layout_graph.successors(ROOT_NODE))
        assert "A" in root_children
        assert "B" in root_children


class TestExtractAngles:
    """Tests for extract_angles function."""

    def test_angles_in_valid_range(self, simple_chain):
        """Angles should be in [-pi, pi] range."""
        edges, direct_includes = simple_chain
        _, header_to_depth = compute_depths(edges, direct_includes)
        classified = classify_edges(edges, header_to_depth)
        layout_graph = build_layout_graph(edges, header_to_depth, classified)
        angles = extract_angles(layout_graph)

        for node, angle in angles.items():
            assert -math.pi <= angle <= math.pi, f"Angle {angle} for {node} out of range"

    def test_root_not_in_angles(self, simple_chain):
        """Root node should not have an angle."""
        edges, direct_includes = simple_chain
        _, header_to_depth = compute_depths(edges, direct_includes)
        classified = classify_edges(edges, header_to_depth)
        layout_graph = build_layout_graph(edges, header_to_depth, classified)
        angles = extract_angles(layout_graph)

        assert ROOT_NODE not in angles

    def test_all_nodes_have_angles(self, complex_graph):
        """All non-root nodes should have angles."""
        edges, direct_includes = complex_graph
        _, header_to_depth = compute_depths(edges, direct_includes)
        classified = classify_edges(edges, header_to_depth)
        layout_graph = build_layout_graph(edges, header_to_depth, classified)
        angles = extract_angles(layout_graph)

        for node in layout_graph.nodes():
            if node != ROOT_NODE:
                assert node in angles, f"Node {node} missing from angles"


class TestComputePositions:
    """Tests for compute_positions function."""

    def test_positions_on_concentric_circles(self, simple_chain):
        """Positions should lie on concentric circles based on depth."""
        edges, direct_includes = simple_chain
        _, header_to_depth = compute_depths(edges, direct_includes)
        classified = classify_edges(edges, header_to_depth)
        layout_graph = build_layout_graph(edges, header_to_depth, classified)
        angles = extract_angles(layout_graph)

        base_radius = 100
        ring_spacing = 100
        positions = compute_positions(angles, header_to_depth, base_radius, ring_spacing)

        for header, (x, y) in positions.items():
            depth = header_to_depth[header]
            expected_radius = base_radius + (depth - 1) * ring_spacing
            actual_radius = math.sqrt(x**2 + y**2)

            assert abs(actual_radius - expected_radius) < 0.01, (
                f"Node {header} at depth {depth} has radius {actual_radius}, "
                f"expected {expected_radius}"
            )

    def test_same_depth_same_radius(self, diamond_graph):
        """Nodes at the same depth should have the same radius."""
        edges, direct_includes = diamond_graph
        _, header_to_depth = compute_depths(edges, direct_includes)
        classified = classify_edges(edges, header_to_depth)
        layout_graph = build_layout_graph(edges, header_to_depth, classified)
        angles = extract_angles(layout_graph)
        positions = compute_positions(angles, header_to_depth)

        # B and C are at same depth
        bx, by = positions["B"]
        cx, cy = positions["C"]

        b_radius = math.sqrt(bx**2 + by**2)
        c_radius = math.sqrt(cx**2 + cy**2)

        assert abs(b_radius - c_radius) < 0.01

    def test_custom_radii_parameters(self, simple_chain):
        """Custom base_radius and ring_spacing should be respected."""
        edges, direct_includes = simple_chain
        _, header_to_depth = compute_depths(edges, direct_includes)
        classified = classify_edges(edges, header_to_depth)
        layout_graph = build_layout_graph(edges, header_to_depth, classified)
        angles = extract_angles(layout_graph)

        base_radius = 200
        ring_spacing = 50
        positions = compute_positions(angles, header_to_depth, base_radius, ring_spacing)

        # Check A at depth 1
        ax, ay = positions["A"]
        a_radius = math.sqrt(ax**2 + ay**2)
        assert abs(a_radius - 200) < 0.01  # base_radius

        # Check B at depth 2
        bx, by = positions["B"]
        b_radius = math.sqrt(bx**2 + by**2)
        assert abs(b_radius - 250) < 0.01  # base_radius + 1 * ring_spacing

        # Check C at depth 3
        cx, cy = positions["C"]
        c_radius = math.sqrt(cx**2 + cy**2)
        assert abs(c_radius - 300) < 0.01  # base_radius + 2 * ring_spacing
