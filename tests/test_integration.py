"""Integration tests for the full layout pipeline."""

import json
import math
import tempfile
from pathlib import Path

import pytest

from include_what_costs.layout import (
    apply_filter,
    build_layout_graph,
    classify_edges,
    compute_depths,
    compute_positions,
    extract_angles,
    render_graph,
    EdgeType,
)


class TestFullPipeline:
    """Integration tests for the complete layout pipeline."""

    def test_full_pipeline(self, complex_graph):
        """Run the complete pipeline and verify invariants."""
        edges, direct_includes = complex_graph

        # Step 1: Compute depths
        headers_by_depth, header_to_depth = compute_depths(edges, direct_includes)

        # Verify: every node has depth >= 1
        for node, depth in header_to_depth.items():
            assert depth >= 1, f"Node {node} has invalid depth {depth}"

        # Step 2: Classify edges
        classified = classify_edges(edges, header_to_depth)

        # Step 3: Build layout graph
        layout_graph = build_layout_graph(edges, header_to_depth, classified)

        # Verify: layout graph is a tree
        num_nodes = layout_graph.number_of_nodes()
        num_edges = layout_graph.number_of_edges()
        assert num_edges == num_nodes - 1, "Layout graph is not a tree"

        # Step 4: Extract angles
        angles = extract_angles(layout_graph)

        # Step 5: Compute positions
        positions = compute_positions(angles, header_to_depth)

        # Verify: positions are on concentric circles
        base_radius = 100
        ring_spacing = 100
        for header, (x, y) in positions.items():
            depth = header_to_depth[header]
            expected_radius = base_radius + (depth - 1) * ring_spacing
            actual_radius = math.sqrt(x**2 + y**2)
            assert abs(actual_radius - expected_radius) < 0.01

        # Verify: tree edges connect adjacent rings only
        for parent, child in classified[EdgeType.TREE]:
            parent_depth = header_to_depth[parent]
            child_depth = header_to_depth[child]
            assert child_depth == parent_depth + 1

    def test_pipeline_with_filter(self, filter_test_graph):
        """Run pipeline with filtering."""
        edges, direct_includes, filter_prefix = filter_test_graph

        # Get all nodes
        all_nodes = set(edges.keys())
        for children in edges.values():
            all_nodes.update(children)

        # Compute depths for all nodes first
        headers_by_depth, header_to_depth = compute_depths(edges, direct_includes)

        # Apply filter
        filter_result = apply_filter(edges, filter_prefix, all_nodes)

        # Verify: included nodes match prefix
        for node in filter_result.included_nodes:
            assert node.startswith(filter_prefix) or node.startswith(
                str(Path(filter_prefix).resolve())
            )

        # Verify: has warnings about external paths
        assert len(filter_result.warnings) > 0

    def test_render_creates_file(self, complex_graph):
        """Render should create an HTML file."""
        edges, direct_includes = complex_graph

        headers_by_depth, header_to_depth = compute_depths(edges, direct_includes)
        classified = classify_edges(edges, header_to_depth)
        layout_graph = build_layout_graph(edges, header_to_depth, classified)
        angles = extract_angles(layout_graph)
        positions = compute_positions(angles, header_to_depth)

        include_counts = {h: 1 for h in header_to_depth}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
            output_path = Path(f.name)

        try:
            render_graph(
                positions=positions,
                edges=edges,
                classified_edges=classified,
                filter_result=None,
                include_counts=include_counts,
                output_path=output_path,
                root_name="root.h",
            )

            assert output_path.exists()
            content = output_path.read_text()

            # Verify basic HTML structure
            assert "<html" in content
            assert "</html>" in content
            assert "vis-network" in content.lower() or "network" in content.lower()
        finally:
            output_path.unlink()

    def test_invariant_every_node_one_depth(self, complex_graph):
        """Every node should appear at exactly one depth."""
        edges, direct_includes = complex_graph
        headers_by_depth, header_to_depth = compute_depths(edges, direct_includes)

        # Check via headers_by_depth
        seen_nodes: set[str] = set()
        for depth, nodes in headers_by_depth.items():
            for node in nodes:
                assert node not in seen_nodes, f"{node} appears at multiple depths"
                seen_nodes.add(node)

        # Check via header_to_depth (should match)
        assert seen_nodes == set(header_to_depth.keys())

    def test_invariant_depth_parent_relationship(self, complex_graph):
        """Every node at depth d > 1 has at least one parent at depth d-1."""
        edges, direct_includes = complex_graph
        headers_by_depth, header_to_depth = compute_depths(edges, direct_includes)

        # Build reverse edge map
        child_to_parents: dict[str, set[str]] = {}
        for parent, children in edges.items():
            for child in children:
                if child not in child_to_parents:
                    child_to_parents[child] = set()
                child_to_parents[child].add(parent)

        for node, depth in header_to_depth.items():
            if depth > 1:
                parents = child_to_parents.get(node, set())
                parent_depths = {
                    header_to_depth.get(p) for p in parents if p in header_to_depth
                }
                assert depth - 1 in parent_depths, (
                    f"Node {node} at depth {depth} has no parent at depth {depth - 1}"
                )

    def test_concentric_radius_invariant(self, complex_graph):
        """All nodes at the same depth should have the same radius."""
        edges, direct_includes = complex_graph

        headers_by_depth, header_to_depth = compute_depths(edges, direct_includes)
        classified = classify_edges(edges, header_to_depth)
        layout_graph = build_layout_graph(edges, header_to_depth, classified)
        angles = extract_angles(layout_graph)

        positions = compute_positions(angles, header_to_depth)

        # Group radii by depth
        radii_by_depth: dict[int, list[float]] = {}
        for header, (x, y) in positions.items():
            depth = header_to_depth[header]
            radius = math.sqrt(x**2 + y**2)
            if depth not in radii_by_depth:
                radii_by_depth[depth] = []
            radii_by_depth[depth].append(radius)

        # All nodes at the same depth should have the same radius
        for depth, radii in radii_by_depth.items():
            first_radius = radii[0]
            for radius in radii:
                assert abs(radius - first_radius) < 0.01, (
                    f"Nodes at depth {depth} have different radii"
                )

        # Radii should increase with depth
        sorted_depths = sorted(radii_by_depth.keys())
        for i in range(len(sorted_depths) - 1):
            d1, d2 = sorted_depths[i], sorted_depths[i + 1]
            assert radii_by_depth[d1][0] < radii_by_depth[d2][0], (
                f"Depth {d1} radius should be less than depth {d2} radius"
            )


class TestEdgeCases:
    """Edge case tests."""

    def test_single_node_graph(self):
        """Graph with single node."""
        edges = {"/proj/A.h": set()}
        direct_includes = {"/proj/A.h"}

        headers_by_depth, header_to_depth = compute_depths(edges, direct_includes)
        classified = classify_edges(edges, header_to_depth)
        layout_graph = build_layout_graph(edges, header_to_depth, classified)
        angles = extract_angles(layout_graph)
        positions = compute_positions(angles, header_to_depth)

        assert len(positions) == 1
        assert "/proj/A.h" in positions

    def test_disconnected_nodes(self):
        """Nodes not reachable from direct includes are not in output."""
        edges = {
            "/proj/A.h": {"/proj/B.h"},
            "/proj/B.h": set(),
            "/proj/C.h": set(),  # Disconnected
        }
        direct_includes = {"/proj/A.h"}

        headers_by_depth, header_to_depth = compute_depths(edges, direct_includes)

        # C should not have a depth (unreachable)
        assert "/proj/A.h" in header_to_depth
        assert "/proj/B.h" in header_to_depth
        assert "/proj/C.h" not in header_to_depth

    def test_self_loop(self):
        """Self-loop should be classified as same-level."""
        edges = {
            "/proj/A.h": {"/proj/A.h"},  # Self-loop
        }
        direct_includes = {"/proj/A.h"}

        headers_by_depth, header_to_depth = compute_depths(edges, direct_includes)
        classified = classify_edges(edges, header_to_depth)

        # Self-loop is same-level (depth 1 -> depth 1)
        assert ("/proj/A.h", "/proj/A.h") in classified[EdgeType.SAME_LEVEL]

    def test_very_deep_graph(self):
        """Deep graph (10 levels) should work correctly."""
        edges = {}
        prev = "/proj/h0.h"
        direct_includes = {prev}

        for i in range(1, 10):
            curr = f"/proj/h{i}.h"
            edges[prev] = {curr}
            prev = curr
        edges[prev] = set()

        headers_by_depth, header_to_depth = compute_depths(edges, direct_includes)

        # Verify depths are correct
        for i in range(10):
            assert header_to_depth[f"/proj/h{i}.h"] == i + 1
